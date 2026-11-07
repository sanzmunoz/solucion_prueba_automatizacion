"""Unit and integration test suite. It verifies parsers, validation, database operations, and AI summaries."""
import os
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import pytest
from src import db, ai
from src.parsers import to_money, to_date, parse_file
from src.pipeline import process_file, file_sha
from src.schema import Record
from src.validate import validate

# Path to sample files for testing
SAMPLES = pathlib.Path(__file__).resolve().parents[1] / "data" / "samples"

class FakeQuery:
    """Simulates PostgREST query operations in memory for testing."""
    def __init__(self, table: str, store: dict):
        self.table = table
        self.store = store
        self._filters = []
        self._order_by = None
        self._desc = False
        self._limit = None
        self._range = None

    def select(self, cols="*"):
        """Sets selected columns."""
        return self

    def eq(self, col, val):
        """Adds an equality filter."""
        self._filters.append(lambda r: r.get(col) == val)
        return self

    def in_(self, col, vals):
        """Adds an IN filter for a list of values."""
        val_set = set(vals)
        self._filters.append(lambda r: r.get(col) in val_set)
        return self

    def order(self, col, desc=False):
        """Sets sorting column and order direction."""
        self._order_by = col
        self._desc = desc
        return self

    def limit(self, count):
        """Limits the maximum number of rows returned."""
        self._limit = count
        return self

    def range(self, start, end):
        """Sets range limits for pagination."""
        self._range = (start, end)
        return self

    def execute(self):
        """Executes the query and returns matching rows."""
        rows = list(self.store.get(self.table, []))
        for f in self._filters:
            rows = [r for r in rows if f(r)]
        if self._order_by:
            rows = sorted(rows, key=lambda r: r.get(self._order_by, 0), reverse=self._desc)
        if self._range:
            # Simulate PostgREST limit of 1000 rows per request
            start, end = self._range
            max_end = min(end, start + 999)
            rows = rows[start:max_end + 1]
        elif self._limit:
            rows = rows[:self._limit]
        else:
            rows = rows[:1000]

        class Result:
            def __init__(self, data):
                self.data = data
        return Result(rows)

    def upsert(self, data, on_conflict=None, ignore_duplicates=False):
        """Inserts or updates rows using primary key."""
        items = data if isinstance(data, list) else [data]
        pk = on_conflict or "item_id"
        tbl = self.store.setdefault(self.table, [])
        existing_map = {r.get(pk): r for r in tbl if r.get(pk) is not None}
        for item in items:
            key = item.get(pk)
            if key in existing_map:
                if not ignore_duplicates:
                    existing_map[key].update(item)
            else:
                new_row = dict(item)
                tbl.append(new_row)
                if key is not None:
                    existing_map[key] = new_row
        return self

    def insert(self, data):
        """Inserts new rows with automatic ID and timestamp."""
        items = data if isinstance(data, list) else [data]
        tbl = self.store.setdefault(self.table, [])
        for item in items:
            row = dict(item)
            if "id" not in row:
                row["id"] = len(tbl) + 1
            if "created_at" not in row:
                row["created_at"] = "2026-11-06T12:00:00Z"
            tbl.append(row)
        return self

class FakeSupabaseClient:
    """In-memory Supabase emulator for unit tests."""
    def __init__(self):
        self.store = {"records": [], "processed_items": [], "summaries": []}

    def table(self, name: str):
        """Returns a query object for the specified table."""
        return FakeQuery(name, self.store)

@pytest.fixture
def fake_client():
    """Provides a fresh fake Supabase client for each test."""
    return FakeSupabaseClient()

@pytest.mark.parametrize("raw,exp", [
    ("$1.250.000", 1250000.0),
    ("1,250,000.50", 1250000.5),
    (95000, 95000.0),
    ("$ 85.000", 85000.0),
    ("", None),
    ("abc", None)
])
def test_money(raw, exp):
    """Tests money parsing with different text formats."""
    assert to_money(raw) == exp

def test_date():
    """Tests date string conversion to ISO format."""
    assert to_date("15/10/2026") == "2026-10-15"
    assert to_date("x") is None

def test_both_formats_same_schema():
    """Tests that both Excel and PDF files map into the same Record schema."""
    x = parse_file(SAMPLES / "reporte_semana_1.xlsx")
    p = parse_file(SAMPLES / "informe_1.pdf")
    assert len(x) == 12 and len(p) == 8
    assert x[0].source_type == "xlsx" and p[0].source_type == "pdf" and p[0].referencia.startswith("REF-")

def test_validation_flags_bad_rows():
    """Tests that validation flags missing fields and negative values."""
    recs = validate(parse_file(SAMPLES / "reporte_semana_2.xlsx"))
    assert any("falta cliente" in r.issues for r in recs)
    assert any("valor no positivo" in r.issues for r in recs)

def test_idempotent_and_no_duplicates(fake_client):
    """Tests that processing the same file twice does not insert duplicates."""
    f = SAMPLES / "reporte_semana_2.xlsx"
    r1 = process_file(fake_client, f)
    r2 = process_file(fake_client, f)

    assert r2["skipped"] is True
    assert r1["dup"] == 1
    assert len(fake_client.store["records"]) == r1["new"]

    # Test inserting duplicate records directly
    recs = validate(parse_file(f))
    new2, dup2 = db.insert_records(fake_client, recs)
    assert new2 == 0 and dup2 == len(recs)
    assert len(fake_client.store["records"]) == r1["new"]

def test_mail_idempotency(fake_client):
    """Tests that emails are tracked by ID to prevent reprocessing."""
    mid = "mail:<msg-001@empresa.com>"
    assert db.seen(fake_client, mid) is False
    db.mark(fake_client, mid, "mail", "2 adjuntos")
    assert db.seen(fake_client, mid) is True
    assert db.seen(fake_client, "mail:<otro@empresa.com>") is False

def test_corrupt_file_marks_error(fake_client, tmp_path):
    """Tests that invalid files are caught and marked with error status."""
    bad_file = tmp_path / "corrupto.xlsx"
    bad_file.write_bytes(b"no es un zip ni un excel valido")

    res = process_file(fake_client, bad_file)
    assert "error" in res
    sha = file_sha(bad_file)
    assert db.seen(fake_client, "file:" + sha) is True
    saved = next(i for i in fake_client.store["processed_items"] if i["item_id"] == "file:" + sha)
    assert saved["status"] == "error"

def test_load_df_pagination_over_1000(fake_client):
    """Tests pagination when database contains more than 1000 rows."""
    records = [
        Record(
            fecha="2026-10-15",
            cliente=f"Cliente {i}",
            categoria="Servicio A",
            valor=float(1000 + i),
            estado="Completado",
            referencia=f"REF-{i:05d}",
            source_file="lote_grande.pdf",
            source_type="pdf"
        )
        for i in range(1250)
    ]
    new, dup = db.insert_records(fake_client, records)
    assert new == 1250 and dup == 0

    df = db.load_df(fake_client)
    assert len(df) == 1250

def test_summary_fallback_has_real_numbers(fake_client, monkeypatch):
    """Tests that fallback summary works without API keys and uses real numbers."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    process_file(fake_client, SAMPLES / "reporte_semana_1.xlsx")
    text, model = ai.executive_summary(db.load_df(fake_client))
    assert model == "fallback"
    assert "12 registros" in text

def test_summary_with_google_gemini(fake_client, monkeypatch):
    """Tests executive summary generation using Gemini API mock."""
    monkeypatch.setenv("GOOGLE_API_KEY", "test-google-key")
    monkeypatch.setenv("GEMINI_MODEL", "gemini-flash-lite-latest")

    class FakeResp:
        def raise_for_status(self): pass
        def json(self):
            return {"candidates": [{"content": {"parts": [{"text": "Resumen generado con Gemini."}]}}]}

    monkeypatch.setattr(ai.httpx, "post", lambda *a, **kw: FakeResp())
    process_file(fake_client, SAMPLES / "reporte_semana_1.xlsx")
    text, model = ai.executive_summary(db.load_df(fake_client))
    assert model == "gemini-flash-lite-latest"
    assert text == "Resumen generado con Gemini."

def test_summaries_storage(fake_client):
    """Tests saving and retrieving executive summaries from database."""
    db.save_summary(fake_client, "Resumen de prueba", "claude-haiku-5-5")
    latest = db.latest_summary(fake_client)
    assert latest is not None
    assert latest[0] == "Resumen de prueba"
    assert latest[1] == "claude-haiku-5-5"

def test_connect_anon_never_uses_service_key(monkeypatch):
    """Tests that anonymous connection fails if anon key is missing."""
    monkeypatch.setenv("SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.setenv("SUPABASE_SERVICE_KEY", "secret-service-key")
    monkeypatch.delenv("SUPABASE_ANON_KEY", raising=False)
    with pytest.raises(ValueError, match="SUPABASE_ANON_KEY"):
        db.connect(service_role=False)

def test_mail_client_error_handling_and_logout(monkeypatch, tmp_path):
    """Tests IMAP client error handling and connection cleanup."""
    from src import mail_client
    monkeypatch.delenv("IMAP_HOST", raising=False)
    with pytest.raises(ValueError, match="Credenciales IMAP"):
        mail_client.fetch_attachments("a@b.com", tmp_path, lambda _: False)

    monkeypatch.setenv("IMAP_HOST", "imap.test.com")
    monkeypatch.setenv("IMAP_USER", "u@test.com")
    monkeypatch.setenv("IMAP_PASSWORD", "secret")
    logged_out = {"called": False}

    class FakeIMAP:
        def __init__(self, host): pass
        def login(self, u, p): pass
        def select(self, box, readonly=True): raise RuntimeError("Fallo simulado de red IMAP")
        def logout(self): logged_out["called"] = True

    monkeypatch.setattr(mail_client.imaplib, "IMAP4_SSL", FakeIMAP)
    with pytest.raises(RuntimeError, match="Fallo simulado"):
        mail_client.fetch_attachments("a@b.com", tmp_path, lambda _: False)
    assert logged_out["called"] is True

def test_processed_history_for_alerts(fake_client):
    """Tests loading file history and counting error statuses for alerts."""
    db.mark(fake_client, "file:abc", "file", "reporte_ok.xlsx: 10 nuevos, 0 duplicados", "ok")
    db.mark(fake_client, "file:def", "file", "corrupto.pdf: archivo dañado", "error")
    hist = db.load_processed_history(fake_client)
    assert len(hist) == 2
    assert (hist["status"] == "error").sum() == 1

@pytest.mark.integration
def test_supabase_live_integration():
    """Runs live Supabase integration check when credentials are provided."""
    url = os.getenv("SUPABASE_URL")
    key = os.getenv("SUPABASE_SERVICE_KEY")
    if not url or not key or "your-project" in url:
        pytest.skip("Variables reales SUPABASE_URL y SUPABASE_SERVICE_KEY no configuradas")
    c = db.connect(service_role=True)
    df = db.load_df(c)
    assert isinstance(df.shape[0], int)
