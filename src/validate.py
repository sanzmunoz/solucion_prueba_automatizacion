"""Data validation rules. It flags issues on records without deleting them."""
from datetime import date
from .schema import Record

# List of required fields for every record
REQUIRED = ["fecha", "cliente", "categoria", "valor", "estado"]

def validate(records: list[Record], today: date | None = None) -> list[Record]:
    """Checks records for missing values, negative amounts, or future dates."""
    # Use today's date if not provided
    today = today or date.today()

    # Check each record for quality problems
    for r in records:
        # Check required fields
        for f in REQUIRED:
            if getattr(r, f) in (None, ""):
                r.issues.append(f"falta {f}")

        # Check for zero or negative values
        if r.valor is not None and r.valor <= 0:
            r.issues.append("valor no positivo")

        # Check for future dates
        if r.fecha and r.fecha > today.isoformat():
            r.issues.append("fecha futura")

    return records
