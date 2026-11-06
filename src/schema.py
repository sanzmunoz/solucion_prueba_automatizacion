"""Estructura común: PDF y Excel se normalizan a este mismo registro."""
import hashlib
from dataclasses import dataclass, asdict, field
from typing import Optional

@dataclass
class Record:
    fecha: Optional[str]          # ISO yyyy-mm-dd
    cliente: Optional[str]
    categoria: Optional[str]
    valor: Optional[float]
    estado: Optional[str]
    cantidad: Optional[int] = None        # solo viene en Excel
    referencia: Optional[str] = None      # solo viene en PDF
    source_file: str = ""
    source_type: str = ""                 # xlsx | pdf
    issues: list = field(default_factory=list)  # problemas de calidad detectados

    @property
    def row_hash(self) -> str:
        """Huella del contenido de negocio: evita duplicados aunque el mismo dato llegue en otro archivo."""
        k = "|".join(str(x) for x in (self.fecha, self.cliente, self.categoria, self.valor, self.estado, self.referencia))
        return hashlib.sha256(k.encode()).hexdigest()[:20]

    def to_row(self) -> dict:
        d = asdict(self); d["issues"] = "; ".join(self.issues); d["row_hash"] = self.row_hash
        return d
