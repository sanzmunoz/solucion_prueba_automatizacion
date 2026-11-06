"""Script de migración idempotente: copia datos desde SQLite local hacia Supabase y valida integridad.
Uso:
  python tools/migrate_sqlite_to_supabase.py --sqlite data/records.db
"""
import argparse
import os
import pathlib
import sqlite3
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from dotenv import load_dotenv
from src import db

def migrate(sqlite_path: str):
    load_dotenv()
    if not os.path.exists(sqlite_path):
        print(f"Archivo SQLite no encontrado en: {sqlite_path}")
        return

    print(f"Conectando a SQLite: {sqlite_path}")
    conn = sqlite3.connect(sqlite_path)
    conn.row_factory = sqlite3.Row
    c_sqlite = conn.cursor()

    print("Conectando a Supabase (service_role)...")
    c_supa = db.connect(service_role=True)

    # 1. Migrar records (idempotente por row_hash)
    c_sqlite.execute("SELECT * FROM records")
    records = [dict(row) for row in c_sqlite.fetchall()]
    sqlite_count = len(records)
    sqlite_sum = sum(float(r["valor"] or 0) for r in records)
    print(f"Encontrados {sqlite_count} registros en SQLite (suma valor: {sqlite_sum:,.2f}).")

    if records:
        step = 200
        for i in range(0, len(records), step):
            batch = records[i:i + step]
            c_supa.table("records").upsert(batch, on_conflict="row_hash").execute()
        print(f"Upsert de {sqlite_count} registros en Supabase completado.")

    # 2. Migrar processed_items (idempotente por item_id)
    c_sqlite.execute("SELECT * FROM processed_items")
    items = [dict(row) for row in c_sqlite.fetchall()]
    print(f"Encontrados {len(items)} items en processed_items.")
    if items:
        step = 200
        for i in range(0, len(items), step):
            batch = items[i:i + step]
            c_supa.table("processed_items").upsert(batch, on_conflict="item_id").execute()
        print(f"Upsert de {len(items)} items en Supabase processed_items completado.")

    # 3. Migrar summaries (idempotente por id)
    c_sqlite.execute("SELECT id, text, model, created_at FROM summaries ORDER BY id ASC")
    summaries = [dict(row) for row in c_sqlite.fetchall()]
    print(f"Encontrados {len(summaries)} resúmenes.")
    if summaries:
        c_supa.table("summaries").upsert(summaries, on_conflict="id").execute()
        print(f"Upsert de {len(summaries)} resúmenes en Supabase completado.")

    # 4. Validación origen vs destino (Fase 4 del plan)
    df_dest = db.load_df(c_supa)
    supa_count = len(df_dest)
    supa_sum = float(df_dest["valor"].fillna(0).sum()) if supa_count else 0.0

    print(f"Validación -> SQLite: {sqlite_count} filas (${sqlite_sum:,.2f}) | Supabase: {supa_count} filas (${supa_sum:,.2f})")
    if supa_count >= sqlite_count and abs(supa_sum - sqlite_sum) < 0.01:
        print("OK: Conteo y suma de valores coinciden.")
    else:
        print("ADVERTENCIA: Diferencia detectada entre origen y destino (puede haber datos previos en Supabase).")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Migración SQLite a Supabase")
    parser.add_argument("--sqlite", default="data/records.db", help="Ruta al archivo SQLite")
    args = parser.parse_args()
    migrate(args.sqlite)
