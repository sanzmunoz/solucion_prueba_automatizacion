"""Parsers deterministas. Excel y PDF tienen estructura fija -> NO se usa LLM aquí (más barato, exacto y reproducible)."""
import re
from datetime import datetime, date
from pathlib import Path
import openpyxl, pdfplumber
from .schema import Record

ALIASES = {"fecha": "fecha", "cliente": "cliente", "categoria": "categoria", "categoría": "categoria",
           "cantidad": "cantidad", "valor": "valor", "estado": "estado",
           "referencia": "referencia", "numero de referencia": "referencia", "número de referencia": "referencia"}

def to_date(v):
    if v in (None, ""): return None
    if isinstance(v, (datetime, date)): return v.date().isoformat() if isinstance(v, datetime) else v.isoformat()
    s = str(v).strip()
    for f in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%Y/%m/%d"):
        try: return datetime.strptime(s, f).date().isoformat()
        except ValueError: pass
    return None

def to_money(v):
    """'$1.250.000' (formato CO) | 1250000 | '1,250,000.50' -> float."""
    if v in (None, ""): return None
    if isinstance(v, (int, float)): return float(v)
    s = re.sub(r"[^\d,.\-]", "", str(v))
    if not s: return None
    if "," in s and "." in s:   # el último separador es el decimal
        dec = "," if s.rfind(",") > s.rfind(".") else "."
        s = s.replace("." if dec == "," else ",", "").replace(dec, ".")
    elif s.count(".") > 1 or re.fullmatch(r"-?\d{1,3}(\.\d{3})+", s): s = s.replace(".", "")
    elif s.count(",") > 1 or re.fullmatch(r"-?\d{1,3}(,\d{3})+", s): s = s.replace(",", "")
    else: s = s.replace(",", ".")
    try: return float(s)
    except ValueError: return None

def _clean(v):
    s = None if v is None else str(v).strip()
    return s or None

def _build(row: dict, name: str, typ: str) -> Record:
    cant = row.get("cantidad")
    return Record(fecha=to_date(row.get("fecha")), cliente=_clean(row.get("cliente")),
                  categoria=_clean(row.get("categoria")), valor=to_money(row.get("valor")),
                  estado=_clean(row.get("estado")), cantidad=int(cant) if str(cant or "").isdigit() else None,
                  referencia=_clean(row.get("referencia")), source_file=name, source_type=typ)

def _rows(headers, values, name, typ):
    keys = [ALIASES.get(str(h or "").strip().lower()) for h in headers]
    out = []
    for vals in values:
        if all(v in (None, "") for v in vals): continue
        out.append(_build({k: v for k, v in zip(keys, vals) if k}, name, typ))
    return out

def parse_excel(path: Path) -> list[Record]:
    ws = openpyxl.load_workbook(path, data_only=True).active
    it = ws.iter_rows(values_only=True)
    return _rows(next(it), it, Path(path).name, "xlsx")

LINE = re.compile(r"^(\d{4}-\d{2}-\d{2}|\d{2}/\d{2}/\d{4})\s+(.+?)\s+([A-Z]{2,5}-?\d+)\s+(.+?)\s+(\$?\s?-?[\d.,]+)\s+(\S+)$")

def parse_pdf(path: Path) -> list[Record]:
    """1) tablas con líneas; 2) si no hay, regex por línea de texto (PDF sin bordes)."""
    out, name = [], Path(path).name
    with pdfplumber.open(path) as pdf:
        for page in pdf.pages:
            tables = [t for t in page.extract_tables() if t and len(t) > 1]
            for t in tables: out += _rows(t[0], t[1:], name, "pdf")
            if not tables:
                for line in (page.extract_text() or "").splitlines():
                    m = LINE.match(line.strip())
                    if m: out.append(_build(dict(zip(["fecha", "cliente", "referencia", "categoria", "valor", "estado"], m.groups())), name, "pdf"))
    return out

def parse_file(path: Path) -> list[Record]:
    ext = Path(path).suffix.lower()
    if ext in (".xlsx", ".xlsm"): return parse_excel(path)
    if ext == ".pdf": return parse_pdf(path)
    raise ValueError(f"Formato no soportado: {ext}")
