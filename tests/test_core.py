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

SAMPLES = pathlib.Path(__file__).resolve().parents[1] / "data" / "samples"

class FakeQuery:
    def __init__(self, table: str, store: dict):
        self.table = table
        self.store = store
        self._filters = []
        self._order_by = None
        self._desc = False
        self._limit = None
        self._range = None

    def select(self, cols="*"):
        return self

    def eq(self, col, val):
        self._filters.append(lambda r: r.get(col) == val)
        return self

    def in_(self, col, vals):
        val_set = set(vals)
        self._filters.append(lambda r: r.get(col) in val_set)
        return self

    def order(self, col, desc=False):
        self._order_by = col
        self._desc = desc
        return self

    def limit(self, count):
        self._limit = count
        return self

    def range(self, start, end):
        self._range = (start, end)
        return self

    def execute(self):
        rows = list(self.store.get(self.table, []))
        for f in self._filters:
            rows = [r for r in rows if f(r)]
        if self._order_by:
            rows = sorted(rows, key=lambda r: r.get(self._order_by, 0), reverse=self._desc)
        if self._range:
            # PostgREST corta en máximo 1000 filas por consulta
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
    """Emulador en memoria de Supabase (incluye límite de 1000 filas de PostgREST)."""
    def __init__(self):
        self.store = {"records": [], "processed_items": [], "summaries": []}

    def table(self, name: str):
        return FakeQuery(name, self.store)

@pytest.fixture
def fake_client():
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
    assert to_money(raw) == exp

def test_date():
    assert to_date("15/10/2026") == "2026-10-15"
    assert to_date("x") is None

def test_both_formats_same_schema():
    x = parse_file(SAMPLES / "reporte_semana_1.xlsx")
    p = parse_file(SAMPLES / "informe_1.pdf")
    assert len(x) == 12 and len(p) == 8
    assert x[0].source_type == "xlsx" and p[0].source_type == "pdf" and p[0].referencia.startswith("REF-")

def test_validation_flags_bad_rows():
    recs = validate(parse_file(SAMPLES / "reporte_semana_2.xlsx"))
    assert any("falta cliente" in r.issues for r in recs)
    assert any("valor no positivo" in r.issues for r in recs)

def test_idempotent_and_no_duplicates(fake_client):
    f = SAMPLES / "reporte_semana_2.xlsx"
    r1 = process_file(fake_client, f)
    r2 = process_file(fake_client, f)

    assert r2["skipped"] is True
    assert r1["dup"] == 1                       # El registro duplicado dentro del archivo se contabiliza
    assert len(fake_client.store["records"]) == r1["new"]

    # Si el mismo contenido llega en otro archivo distinto, tampoco duplica en records
    recs = validate(parse_file(f))
    new2, dup2 = db.insert_records(fake_client, recs)
    assert new2 == 0 and dup2 == len(recs)
    assert len(fake_client.store["records"]) == r1["new"]

def test_mail_idempotency(fake_client):
    mid = "mail:<msg-001@empresa.com>"
    assert db.seen(fake_client, mid) is False
    db.mark(fake_client, mid, "mail", "2 adjuntos")
    assert db.seen(fake_client, mid) is True
    assert db.seen(fake_client, "mail:<otro@empresa.com>") is False

def test_corrupt_file_marks_error(fake_client, tmp_path):
    bad_file = tmp_path / "corrupto.xlsx"
    bad_file.write_bytes(b"no es un zip ni un excel valido")

    res = process_file(fake_client, bad_file)
    assert "error" in res
    sha = file_sha(bad_file)
    assert db.seen(fake_client, "file:" + sha) is True
    saved = next(i for i in fake_client.store["processed_items"] if i["item_id"] == "file:" + sha)
    assert saved["status"] == "error"

def test_load_df_pagination_over_1000(fake_client):
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
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    process_file(fake_client, SAMPLES / "reporte_semana_1.xlsx")
    text, model = ai.executive_summary(db.load_df(fake_client))
    assert model == "fallback"
    assert "12 registros" in text

def test_summaries_storage(fake_client):
    db.save_summary(fake_client, "Resumen de prueba", "claude-haiku-5-5")
    latest = db.latest_summary(fake_client)
    assert latest is not None
    assert latest[0] == "Resumen de prueba"
    assert latest[1] == "claude-haiku-5-5"

def test_connect_anon_never_uses_service_key(monkeypatch):
    monkeypatch.setenv("SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.setenv("SUPABASE_SERVICE_KEY", "secret-service-key")
    monkeypatch.delenv("SUPABASE_ANON_KEY", raising=False)
    with pytest.raises(ValueError, match="SUPABASE_ANON_KEY"):
        db.connect(service_role=False)

@pytest.mark.integration
def test_supabase_live_integration():
    url = os.getenv("SUPABASE_URL")
    key = os.getenv("SUPABASE_SERVICE_KEY")
    if not url or not key or "your-project" in url:
        pytest.skip("Variables reales SUPABASE_URL y SUPABASE_SERVICE_KEY no configuradas")
    c = db.connect(service_role=True)
    df = db.load_df(c)
    assert isinstance(df.shape[0], int)
