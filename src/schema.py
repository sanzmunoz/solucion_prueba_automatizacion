"""Data schema module. It normalizes data from PDF and Excel files into one structure."""
import hashlib
from dataclasses import dataclass, asdict, field
from typing import Optional

@dataclass
class Record:
    """Stores data of a single record from Excel or PDF."""
    fecha: Optional[str]          # Date in ISO format (YYYY-MM-DD)
    cliente: Optional[str]        # Customer name
    categoria: Optional[str]      # Category name
    valor: Optional[float]        # Money value
    estado: Optional[str]         # Status of record
    cantidad: Optional[int] = None        # Item count (only in Excel)
    referencia: Optional[str] = None      # Reference code (only in PDF)
    source_file: str = ""         # Source file name
    source_type: str = ""         # File type: xlsx or pdf
    issues: list = field(default_factory=list)  # List of validation issues

    @property
    def row_hash(self) -> str:
        """Creates a unique hash for the record. It prevents duplicate rows."""
        k = "|".join(str(x) for x in (self.fecha, self.cliente, self.categoria, self.valor, self.estado, self.referencia))
        return hashlib.sha256(k.encode()).hexdigest()[:20]

    def to_row(self) -> dict:
        """Converts the record to a dictionary for database storage."""
        d = asdict(self)
        d["issues"] = "; ".join(self.issues)
        d["row_hash"] = self.row_hash
        return d
