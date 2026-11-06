# Plan de migración: SQLite → Supabase (Solución 1)

## 1. Situación actual
- `src/db.py` usa `sqlite3` (archivo `data/records.db`) con 3 tablas: `records` (PK `row_hash`), `processed_items` (idempotencia correo/archivo), `summaries`.
- Consumidores de la BD:
  - `src/pipeline.py`: `db.connect/seen/mark/insert_records/load_df` y un `INSERT INTO summaries` directo con `c.execute`.
  - `dashboard.py`: `db.connect()`, `db.load_df(c)` y un `SELECT ... FROM summaries` directo.
  - `tests/test_core.py`: `db.connect(str(tmp_path/"t.db"))`.
  - `.github/workflows/ingest.yml`: persiste el `.db` con `actions/cache` (frágil; con Supabase deja de ser necesario).
- Problema que resuelve la migración: el dashboard en Streamlit Cloud y el job de GitHub Actions no comparten disco; con Supabase ambos leen/escriben la misma BD.

## 2. Arquitectura objetivo
```
GitHub Actions (cron horario 8-18 h Bogotá) → pipeline.py → Supabase (service_role) ← dashboard.py (Streamlit Cloud)
```
- Cliente: `supabase-py` (API REST/PostgREST). Alternativa descartada: `psycopg` directo (requiere pooler/IPv6 y más configuración; la API REST basta para este volumen).
- Escritura (pipeline): `SUPABASE_SERVICE_KEY` (solo en GitHub Secrets / `.env`, nunca en el repo).
- Lectura (dashboard): **decidido → `anon` + RLS** de solo `select` sobre `records` y `summaries` (mínimo privilegio, igual que sol. 2). `processed_items` no tiene política `anon`, por lo que el dashboard no puede leerla (intencional). `service_role` queda exclusivamente en el pipeline.

## 3. Fases

### Fase 0 – Preparación (≈15 min)
1. Crear proyecto Supabase (free tier). Anotar `Project URL`, `anon key`, `service_role key`.
2. Crear rama `feat/supabase` para poder volver atrás.

### Fase 1 – Esquema en Supabase (≈15 min)
Ejecutar en SQL Editor (archivo propuesto: `supabase/schema.sql`):
```sql
create table if not exists records (
  row_hash text primary key,
  fecha date, cliente text, categoria text, cantidad int, referencia text,
  valor numeric, estado text, issues text, source_file text, source_type text,
  ingested_at timestamptz default now()
);
create table if not exists processed_items (
  item_id text primary key, kind text, detail text, status text,
  processed_at timestamptz default now()
);
create table if not exists summaries (
  id bigserial primary key, text text, model text, created_at timestamptz default now()
);
alter table records enable row level security;
alter table processed_items enable row level security;
alter table summaries enable row level security;
create policy "anon read records"   on records   for select to anon using (true);
create policy "anon read summaries" on summaries for select to anon using (true);
-- processed_items sin política anon: solo service_role (bypass RLS)
```
Mapeo de tipos: `TEXT fecha → date`, `REAL valor → numeric`, `CURRENT_TIMESTAMP → now()`, `AUTOINCREMENT → bigserial`.

### Fase 2 – Capa de datos (`src/db.py`) (≈1 h)
Reescribir manteniendo **la misma interfaz pública** para tocar poco código:
| Función | Implementación Supabase |
|---|---|
| `connect()` | `create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)`; falla claro si faltan variables |
| `seen(c, item_id)` | `select item_id` con `.eq("item_id", id).limit(1)` |
| `mark(c, id, kind, detail, status)` | `upsert` en `processed_items` |
| `insert_records(c, records)` | **Decidido → opción A:** consultar `row_hash` existentes (`select row_hash where row_hash in (...)`, por lotes) → `dup` = coincidencias, `new` = resto; luego `upsert(rows, on_conflict="row_hash", ignore_duplicates=True)` solo con las filas nuevas. PostgREST no informa de las filas ignoradas. Una carrera entre ejecuciones simultáneas solo desajustaría el contador, nunca duplicaría datos (lo garantiza el PK) |
| `load_df(c)` | `select *` paginado (`range` de 1000 en 1000) → `pd.DataFrame`; `fecha` a datetime |
| **nuevas** `save_summary(c, text, model)` y `latest_summary(c)` | reemplazan los SQL directos de `pipeline.py` y `dashboard.py` |

Notas: enviar lotes (p. ej. 500 filas) en el upsert; convertir `NaN`/`None` a `null`; `valor`/`cantidad` como tipos nativos JSON.

### Fase 3 – Adaptar consumidores (≈30 min)
- `pipeline.py`: reemplazar `c.execute("INSERT INTO summaries...")` por `db.save_summary`.
- `dashboard.py`: reemplazar el `SELECT ... summaries` por `db.latest_summary`; quitar `import sqlite3`. Credenciales desde `st.secrets` (con fallback a variables de entorno).
- `requirements.txt`: agregar `supabase>=2`.
- `.env.example`: quitar `DB_PATH`; añadir `SUPABASE_URL`, `SUPABASE_SERVICE_KEY`, `SUPABASE_ANON_KEY`.

### Fase 4 – Migración de datos existentes (≈20 min, opcional)
Script único `tools/migrate_sqlite_to_supabase.py`:
1. Leer `data/records.db` (`records`, `processed_items`, `summaries`).
2. Insertar por lotes con `upsert` idempotente (`on_conflict`), de modo que pueda re-ejecutarse sin duplicar.
3. Validar: `count(*)` origen == destino y comparar `sum(valor)`.
Si solo hay datos de demo, omitir y reprocesar `shared/samples`.

### Fase 5 – Pruebas (≈1 h)
- Los tests actuales usan SQLite temporal. Opciones:
  - **Recomendada**: tests unitarios con un *fake client* en memoria (dict) que implemente las mismas llamadas, más un test de integración marcado `@pytest.mark.integration` contra un proyecto Supabase de pruebas (se omite si no hay variables).
- Casos mínimos: idempotencia por correo y por archivo; mismo `row_hash` dos veces → 1 fila y `dup` correcto; archivo corrupto queda con `status=error`; paginación de `load_df` con >1000 filas; resumen guardado y recuperado.
- Prueba de punta a punta: `python -m src.pipeline --local ../shared/samples` dos veces → la segunda no inserta nada.

### Fase 6 – Automatización y despliegue (≈30 min)
- `ingest.yml`: eliminar el paso de `actions/cache` de la BD; agregar secrets `SUPABASE_URL` y `SUPABASE_SERVICE_KEY`.
- **Frecuencia (decisión del usuario):** cada hora y solo de 8:00 a 18:00 hora Colombia (UTC-5), sin ejecuciones nocturnas. GitHub Actions interpreta el cron en **UTC**, por lo que 8–18 h locales = 13–23 h UTC:
  ```yaml
  on:
    schedule: [{cron: "0 13-23 * * *"}]   # 8:00-18:00 America/Bogota (11 ejecuciones/día)
    workflow_dispatch:
  ```
  Notas: GitHub puede retrasar algunos minutos los cron en horas pico; si se quiere incluir también sábados/domingos o excluirlos, ajustar el campo día de la semana (p. ej. `1-5` para lunes a viernes). El cron no cubre la noche, por lo que hay que documentar que un correo recibido fuera de ese horario se procesa en la siguiente ejecución (8:00). Impacto en Supabase free tier: al no haber actividad nocturna ni de fin de semana (si se excluyen), el proyecto sigue activo mientras haya ejecuciones al menos una vez cada 7 días.
- Streamlit Community Cloud: configurar `SUPABASE_URL` y `SUPABASE_ANON_KEY` en *Secrets*.
- Actualizar `README.md` (arquitectura, configuración, limitaciones).

### Fase 7 – Cierre
- Verificar que `.env` no esté versionado y que `service_role` no aparezca en el código ni en el front.
- Eliminar `data/records.db` del flujo (mantener en `.gitignore`).
- Actualizar `docs/ARQUITECTURA.md`, `docs/DECISIONES.md` (nueva decisión: Supabase en sol. 1) y `docs/CHECKLIST_ENTREGA.md`.

## 4. Riesgos y mitigaciones
| Riesgo | Mitigación |
|---|---|
| Free tier de Supabase pausa el proyecto tras ~7 días sin actividad | El cron horario (8–18 h) genera actividad diaria; documentar cómo reactivarlo |
| Conteo new/dup inexacto con `ignore_duplicates` | Opción A: consultar `row_hash` existentes antes del upsert |
| Cron en UTC vs. horario local | Usar `0 13-23 * * *` (UTC) = 8–18 h Bogotá; documentarlo en README |
| Límite de 1000 filas por consulta de PostgREST | Paginación con `range` en `load_df` |
| Fuga de `service_role` | Solo en secrets; dashboard con `anon` + RLS de solo lectura |
| Caídas de red/API durante el pipeline | Reintentos simples y el patrón actual: un archivo fallido no frena el lote (`status=error`) |
| Reprocesamiento al migrar | `upsert` idempotente por `row_hash`/`item_id` |

## 5. Criterios de aceptación
- [ ] Pipeline y dashboard funcionan sin archivo SQLite.
- [ ] Ejecutar el pipeline dos veces no duplica registros ni resúmenes de archivos.
- [ ] El dashboard desplegado muestra los datos escritos por GitHub Actions.
- [ ] Tests pasan (unitarios con fake; integración opcional).
- [ ] Ningún secreto en el repositorio; `.env.example` actualizado.
- [ ] El workflow corre cada hora solo entre 8:00 y 18:00 (Bogotá) y no se ejecuta de noche.
- [ ] El dashboard usa solo la clave `anon` y no puede escribir ni leer `processed_items`.

## 6. Orden de ejecución y estimación
Fase 0 → 1 → 2 → 3 → 5 → 4 → 6 → 7. Total ≈ 4–5 h.
