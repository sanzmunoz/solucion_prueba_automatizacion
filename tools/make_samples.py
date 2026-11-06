"""Genera archivos de ejemplo (Excel + PDF) con la estructura de la prueba.
Uso: python make_samples.py <carpeta_salida>
Incluye a propósito filas con problemas (vacíos, valor negativo, duplicado) para demostrar validación."""
import random, sys, pathlib
from datetime import date, timedelta
from openpyxl import Workbook
from reportlab.lib.pagesizes import A4
from reportlab.platypus import SimpleDocTemplate, Table, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet

out = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else "samples"); out.mkdir(parents=True, exist_ok=True)
random.seed(7)
clientes = ["Cliente A", "Cliente B", "Cliente C", "Cliente D"]
cats = ["Servicio A", "Servicio B", "Servicio C"]
estados = ["Completado", "Pendiente", "Rechazado"]

def fila(i, base):
    return [(base + timedelta(days=random.randint(0, 6))).isoformat(), random.choice(clientes),
            random.choice(cats), random.randint(1, 20), random.randrange(50_000, 900_000, 5_000),
            random.choices(estados, [6, 3, 1])[0]]

for n, base in enumerate([date(2026, 10, 1), date(2026, 10, 8), date(2026, 10, 15)], 1):
    wb = Workbook(); ws = wb.active; ws.title = "Reporte"
    ws.append(["Fecha", "Cliente", "Categoría", "Cantidad", "Valor", "Estado"])
    rows = [fila(i, base) for i in range(12)]
    if n == 2:
        rows[3][1] = ""            # cliente faltante
        rows[5][4] = -1000         # valor negativo
        rows.append(list(rows[0])) # duplicado exacto
    for r in rows: ws.append(r)
    wb.save(out / f"reporte_semana_{n}.xlsx")

st = getSampleStyleSheet()
for n, base in enumerate([date(2026, 10, 5), date(2026, 10, 12)], 1):
    doc = SimpleDocTemplate(str(out / f"informe_{n}.pdf"), pagesize=A4)
    data = [["Fecha", "Cliente", "Referencia", "Categoría", "Valor", "Estado"]]
    for i in range(8):
        f = fila(i, base)
        data.append([f[0], f[1], f"REF-{n}{i:03d}", f[2], f"${f[4]:,}".replace(",", "."), f[5]])
    doc.build([Paragraph("Informe operacional", st["Title"]), Spacer(1, 12), Table(data)])
print("OK ->", out.resolve())
