"""Capa de datos con Supabase (PostgreSQL + PostgREST).
Reemplaza SQLite manteniendo la misma interfaz pública para pipeline, dashboard y tests.
Idempotencia en registros con row_hash (PK) y conteo con Opción A."""
import os
import pandas as pd
from typing import Optional

try:
    import truststore
    truststore.inject_into_ssl()
except ImportError:
    pass

COLS = [
    "row_hash", "fecha", "cliente", "categoria", "cantidad",
    "referencia", "valor", "estado", "issues", "source_file", "source_type"
]

def _get_credential(key_name: str) -> Optional[str]:
    """Obtiene credenciales desde streamlit secrets o variables de entorno."""
    try:
        import streamlit as st
        if hasattr(st, "secrets") and key_name in st.secrets:
            return str(st.secrets[key_name])
    except Exception:
        pass
    return os.getenv(key_name)

def connect(service_role: bool = True, url: str | None = None, key: str | None = None, client=None):
    """Crea y retorna un cliente de Supabase.
    - service_role=True: usa SUPABASE_SERVICE_KEY (pipeline de ingesta, bypass RLS).
    - service_role=False: usa SUPABASE_ANON_KEY (dashboard, solo lectura por RLS).
    Si se pasa `client` directamente, se reutiliza (útil para tests e inyección)."""
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
    """Verifica si un correo o archivo ya fue procesado previamente."""
    res = client.table("processed_items").select("item_id").eq("item_id", item_id).limit(1).execute()
    return bool(res.data)

def mark(client, item_id: str, kind: str, detail: str = "", status: str = "ok"):
    """Registra o actualiza el estado de procesamiento de un archivo o correo."""
    client.table("processed_items").upsert({
        "item_id": item_id,
        "kind": kind,
        "detail": detail,
        "status": status
    }).execute()

def insert_records(client, records: list) -> tuple[int, int]:
    """Inserta registros con Opción A de deduplicación:
    1. Consulta hashes existentes en Supabase por lotes.
    2. Identifica filas nuevas vs duplicadas.
    3. Realiza upsert solo de filas nuevas en lotes.
    Retorna (nuevos, duplicados)."""
    if not records:
        return 0, 0

    hashes = [r.row_hash for r in records]
    existing_hashes = set()

    # Consultar hashes existentes en chunks de 100
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

    for r in records:
        h = r.row_hash
        if h in existing_hashes or h in seen_in_batch:
            dup_count += 1
        else:
            seen_in_batch.add(h)
            to_insert.append(r.to_row())
            new_count += 1

    # Insertar en lotes de 200 filas
    insert_batch_size = 200
    for i in range(0, len(to_insert), insert_batch_size):
        batch = to_insert[i:i + insert_batch_size]
        client.table("records").upsert(batch, on_conflict="row_hash", ignore_duplicates=True).execute()

    return new_count, dup_count

def load_df(client) -> pd.DataFrame:
    """Carga todos los registros paginados desde Supabase (PostgREST limita a 1000 por request)."""
    rows = []
    step = 1000
    start = 0

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
    """Guarda el resumen ejecutivo generado por IA en la tabla summaries."""
    client.table("summaries").insert({"text": text, "model": model}).execute()

def latest_summary(client) -> Optional[tuple[str, str, str]]:
    """Obtiene el último resumen ejecutivo registrado: (texto, modelo, fecha_creacion)."""
    res = client.table("summaries").select("text, model, created_at").order("id", desc=True).limit(1).execute()
    if res.data:
        first = res.data[0]
        return first.get("text", ""), first.get("model", ""), first.get("created_at", "")
    return None

def load_processed_history(client) -> pd.DataFrame:
    """Carga historial de archivos procesados si el rol tiene permisos."""
    try:
        res = client.table("processed_items").select("processed_at, kind, status, detail").eq("kind", "file").order("processed_at", desc=True).execute()
        df = pd.DataFrame(res.data or [])
        if df.empty:
            return pd.DataFrame(columns=["processed_at", "kind", "status", "detail"])
        return df
    except Exception:
        # Rol anon no tiene acceso por RLS (política de seguridad)
        return pd.DataFrame(columns=["processed_at", "kind", "status", "detail"])
