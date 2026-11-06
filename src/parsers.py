"""File parser module. It reads Excel and PDF files into structured Record objects."""
import re
from datetime import datetime, date
from pathlib import Path
import openpyxl, pdfplumber
from .schema import Record

# Dictionary to map different column names to standard keys
ALIASES = {
    "fecha": "fecha", "cliente": "cliente", "cliente empresa": "cliente",
    "categoria": "categoria", "categoría": "categoria",
    "cantidad": "cantidad", "valor": "valor", "estado": "estado",
    "referencia": "referencia", "numero de referencia": "referencia", "número de referencia": "referencia"
}

def to_date(v):
    """Converts a raw date string or date object into ISO format (YYYY-MM-DD)."""
    if v in (None, ""):
        return None
    if isinstance(v, (datetime, date)):
        return v.date().isoformat() if isinstance(v, datetime) else v.isoformat()
    s = str(v).strip()
    for f in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%Y/%m/%d"):
        try:
            return datetime.strptime(s, f).date().isoformat()
        except ValueError:
            pass
    return None

def to_money(v):
    """Converts a money string or number into a float value."""
    if v in (None, ""):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    s = re.sub(r"[^\d,.\-]", "", str(v))
    if not s:
        return None
    # Detect decimal separator when both dot and comma exist
    if "," in s and "." in s:
        dec = "," if s.rfind(",") > s.rfind(".") else "."
        s = s.replace("." if dec == "," else ",", "").replace(dec, ".")
    elif s.count(".") > 1 or re.fullmatch(r"-?\d{1,3}(\.\d{3})+", s):
        s = s.replace(".", "")
    elif s.count(",") > 1 or re.fullmatch(r"-?\d{1,3}(,\d{3})+", s):
        s = s.replace(",", "")
    else:
        s = s.replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return None

def _clean(v):
    """Trims whitespace and returns clean text or None."""
    s = None if v is None else str(v).strip()
    return s or None

def _build(row: dict, name: str, typ: str) -> Record:
    """Builds a single Record instance from a dictionary of raw values."""
    cant = row.get("cantidad")
    return Record(
        fecha=to_date(row.get("fecha")),
        cliente=_clean(row.get("cliente")),
        categoria=_clean(row.get("categoria")),
        valor=to_money(row.get("valor")),
        estado=_clean(row.get("estado")),
        cantidad=int(cant) if str(cant or "").isdigit() else None,
        referencia=_clean(row.get("referencia")),
        source_file=name,
        source_type=typ
    )

def _rows(headers, values, name, typ):
    """Maps header columns and table rows into a list of Record objects."""
    keys = [ALIASES.get(str(h or "").strip().lower()) for h in headers]
    if not any(keys):
        return []
    out = []
    for vals in values:
        if all(v in (None, "") for v in vals):
            continue
        mapped = {k: v for k, v in zip(keys, vals) if k and v not in (None, "")}
        if not mapped:
            continue
        out.append(_build(mapped, name, typ))
    return out

def parse_excel(path: Path) -> list[Record]:
    """Reads rows from an Excel file (.xlsx) and returns a list of Record objects."""
    ws = openpyxl.load_workbook(path, data_only=True).active
    it = ws.iter_rows(values_only=True)
    return _rows(next(it), it, Path(path).name, "xlsx")

# Regex pattern for single-line rows in PDF text
LINE = re.compile(r"^(\d{4}-\d{2}-\d{2}|\d{2}/\d{2}/\d{4})\s+(.+?)\s+([A-Z]{2,5}-?\d+)\s+(.+?)\s+(\$?\s?-?[\d.,]+)\s+(\S+)$")

# Regex pattern for key-value lines in PDF text
KV_LINE = re.compile(
    r"^\s*(?:[-•*]\s*)?(fecha|cliente(?:\s+empresa)?|n[uú]mero\s+de\s+referencia|referencia|categor[ií]a|cantidad|valor|estado)\s*:?\s+(.+?)\s*$",
    re.IGNORECASE,
)

def parse_pdf(path: Path) -> list[Record]:
    """Reads tables, line regex, or key-value pairs from a PDF file."""
    out, name = [], Path(path).name
    with pdfplumber.open(path) as pdf:
        for page in pdf.pages:
            page_rows = []
            # 1. Try extracting structured tables
            tables = [t for t in page.extract_tables() if t and len(t) > 1]
            for t in tables:
                page_rows += _rows(t[0], t[1:], name, "pdf")

            # 2. If no table is found, parse plain text line by line
            if not page_rows:
                kv = {}
                for line in (page.extract_text() or "").splitlines():
                    s = line.strip()
                    # Check for horizontal single line row
                    m = LINE.match(s)
                    if m:
                        page_rows.append(_build(dict(zip(["fecha", "cliente", "referencia", "categoria", "valor", "estado"], m.groups())), name, "pdf"))
                        continue
                    # Check for vertical key-value line
                    km = KV_LINE.match(s)
                    if km:
                        k = ALIASES.get(re.sub(r"\s+", " ", km.group(1).strip().lower()))
                        val = km.group(2).lstrip(": ").strip()
                        if k and val:
                            if k in kv and len(kv) >= 2:
                                page_rows.append(_build(kv, name, "pdf"))
                                kv = {}
                            kv[k] = val
                # Save any remaining key-value block
                if len(kv) >= 2:
                    page_rows.append(_build(kv, name, "pdf"))
            out += page_rows
    return out

def parse_file(path: Path) -> list[Record]:
    """Dispatches a file to Excel or PDF parser based on its extension."""
    ext = Path(path).suffix.lower()
    if ext in (".xlsx", ".xlsm"):
        return parse_excel(path)
    if ext == ".pdf":
        return parse_pdf(path)
    raise ValueError(f"Formato no soportado: {ext}")
