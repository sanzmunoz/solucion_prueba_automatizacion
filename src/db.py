"""Database module for Supabase (PostgreSQL). It stores records, tracks processed files, and saves summaries."""
import os
import pandas as pd
from typing import Optional

try:
    import truststore
    truststore.inject_into_ssl()
except ImportError:
    pass

# Columns expected in the records table
COLS = [
    "row_hash", "fecha", "cliente", "categoria", "cantidad",
    "referencia", "valor", "estado", "issues", "source_file", "source_type"
]

def _get_credential(key_name: str) -> Optional[str]:
    """Gets a secret key from Streamlit secrets or environment variables."""
    try:
        import streamlit as st
        if hasattr(st, "secrets") and key_name in st.secrets:
            return str(st.secrets[key_name])
    except Exception:
        pass
    return os.getenv(key_name)

def connect(service_role: bool = True, url: str | None = None, key: str | None = None, client=None):
    """Creates a Supabase client.
    - service_role=True: uses service key for pipeline write operations.
    - service_role=False: uses anon key for read-only dashboard access.
    """
    if client is not None:
        return client

    from supabase import create_client

    supabase_url = url or _get_credential("SUPABASE_URL")
    if not supabase_url:
        raise ValueError("SUPABASE_URL no configurada. Define la variable de entorno o secret.")

    if service_role:
        supabase_key = key or _get_credential("SUPABASE_SERVICE_KEY")
        if not supabase_key:
            raise ValueError("SUPABASE_SERVICE_KEY no configurada para acceso de escritura en pipeline.")
    else:
        supabase_key = key or _get_credential("SUPABASE_ANON_KEY")
        if not supabase_key:
            raise ValueError("SUPABASE_ANON_KEY no configurada para acceso de lectura en dashboard.")

    return create_client(supabase_url, supabase_key)

def seen(client, item_id: str) -> bool:
    """Checks if a file or email ID was already processed."""
    res = client.table("processed_items").select("item_id").eq("item_id", item_id).limit(1).execute()
    return bool(res.data)

def mark(client, item_id: str, kind: str, detail: str = "", status: str = "ok"):
    """Saves or updates the processing state of an item."""
    client.table("processed_items").upsert({
        "item_id": item_id,
        "kind": kind,
        "detail": detail,
        "status": status
    }).execute()

def insert_records(client, records: list) -> tuple[int, int]:
    """Inserts new records and counts duplicates. Returns (new_count, dup_count)."""
    if not records:
        return 0, 0

    hashes = [r.row_hash for r in records]
    existing_hashes = set()

    # Step 1: Query existing hashes in chunks of 100
    chunk_size = 100
    for i in range(0, len(hashes), chunk_size):
        chunk = hashes[i:i + chunk_size]
        res = client.table("records").select("row_hash").in_("row_hash", chunk).execute()
        if res.data:
            existing_hashes.update(row["row_hash"] for row in res.data)

    seen_in_batch = set()
    to_insert = []
    new_count = 0
    dup_count = 0

    # Step 2: Separate new records from duplicate records
    for r in records:
        h = r.row_hash
        if h in existing_hashes or h in seen_in_batch:
            dup_count += 1
        else:
            seen_in_batch.add(h)
            to_insert.append(r.to_row())
            new_count += 1

    # Step 3: Insert new records in batches of 200
    insert_batch_size = 200
    for i in range(0, len(to_insert), insert_batch_size):
        batch = to_insert[i:i + insert_batch_size]
        client.table("records").upsert(batch, on_conflict="row_hash", ignore_duplicates=True).execute()

    return new_count, dup_count

def load_df(client) -> pd.DataFrame:
    """Loads all records from Supabase into a Pandas DataFrame using pagination."""
    rows = []
    step = 1000
    start = 0

    # Fetch rows page by page (1000 rows per request)
    while True:
        res = client.table("records").select("*").range(start, start + step - 1).execute()
        chunk = res.data or []
        rows.extend(chunk)
        if len(chunk) < step:
            break
        start += step

    df = pd.DataFrame(rows)
    if df.empty:
        df = pd.DataFrame(columns=COLS)
    df["fecha"] = pd.to_datetime(df["fecha"], errors="coerce")
    return df

def save_summary(client, text: str, model: str):
    """Saves the AI executive summary text to the database."""
    client.table("summaries").insert({"text": text, "model": model}).execute()

def latest_summary(client) -> Optional[tuple[str, str, str]]:
    """Gets the most recent executive summary: (text, model, created_at)."""
    res = client.table("summaries").select("text, model, created_at").order("id", desc=True).limit(1).execute()
    if res.data:
        first = res.data[0]
        return first.get("text", ""), first.get("model", ""), first.get("created_at", "")
    return None

def load_processed_history(client) -> pd.DataFrame:
    """Loads the history of processed files for the status dashboard."""
    try:
        res = client.table("processed_items").select("processed_at, kind, status, detail").eq("kind", "file").order("processed_at", desc=True).execute()
        df = pd.DataFrame(res.data or [])
        if df.empty:
            return pd.DataFrame(columns=["processed_at", "kind", "status", "detail"])
        return df
    except Exception:
        # Return empty DataFrame if user has no read permission
        return pd.DataFrame(columns=["processed_at", "kind", "status", "detail"])
