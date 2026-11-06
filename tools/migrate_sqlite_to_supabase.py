"""Script de migración: copia datos desde un SQLite local existente hacia Supabase.
Uso:
  python tools/migrate_sqlite_to_supabase.py --sqlite data/records.db
"""
import argparse
import os
import sqlite3
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

    # 1. Migrar records
    try:
        c_sqlite.execute("SELECT * FROM records")
        records = [dict(row) for row in c_sqlite.fetchall()]
        print(f"Encontrados {len(records)} registros en SQLite records.")
        if records:
            # Upsert en lotes
            step = 200
            for i in range(0, len(records), step):
                batch = records[i:i + step]
                c_supa.table("records").upsert(batch, on_conflict="row_hash").execute()
            print(f"Migrados {len(records)} registros a Supabase records.")
    except Exception as e:
        print(f"Error migrando records: {e}")

    # 2. Migrar processed_items
    try:
        c_sqlite.execute("SELECT * FROM processed_items")
        items = [dict(row) for row in c_sqlite.fetchall()]
        print(f"Encontrados {len(items)} items en processed_items.")
        if items:
            step = 200
            for i in range(0, len(items), step):
                batch = items[i:i + step]
                c_supa.table("processed_items").upsert(batch, on_conflict="item_id").execute()
            print(f"Migrados {len(items)} items a Supabase processed_items.")
    except Exception as e:
        print(f"Error migrando processed_items: {e}")

    # 3. Migrar summaries
    try:
        c_sqlite.execute("SELECT text, model, created_at FROM summaries ORDER BY id ASC")
        summaries = [dict(row) for row in c_sqlite.fetchall()]
        print(f"Encontrados {len(summaries)} resúmenes.")
        for s in summaries:
            c_supa.table("summaries").insert({
                "text": s["text"],
                "model": s["model"]
            }).execute()
        print(f"Migrados {len(summaries)} resúmenes.")
    except Exception as e:
        print(f"Error migrando summaries: {e}")

    print("Migración completada exitosamente.")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Migración SQLite a Supabase")
    parser.add_argument("--sqlite", default="data/records.db", help="Ruta al archivo SQLite")
    args = parser.parse_args()
    migrate(args.sqlite)
