"""Validación con reglas (programación tradicional). Marca, no descarta: el humano decide."""
from datetime import date
from .schema import Record
REQUIRED = ["fecha", "cliente", "categoria", "valor", "estado"]

def validate(records: list[Record], today: date | None = None) -> list[Record]:
    today = today or date.today()
    for r in records:
        for f in REQUIRED:
            if getattr(r, f) in (None, ""): r.issues.append(f"falta {f}")
        if r.valor is not None and r.valor <= 0: r.issues.append("valor no positivo")
        if r.fecha and r.fecha > today.isoformat(): r.issues.append("fecha futura")
    return records
