-- Ejecutar en Supabase > SQL Editor

-- 1. Tabla principal de registros operacionales
create table if not exists records (
  row_hash    text primary key,              -- huella de contenido: evita duplicados
  fecha       date,
  cliente     text,
  categoria   text,
  cantidad    int,                           -- viene en Excel
  referencia  text,                          -- viene en PDF
  valor       numeric,
  estado      text,
  issues      text,                          -- incidencias detectadas (calidad del dato)
  source_file text,
  source_type text,                          -- xlsx | pdf
  ingested_at timestamptz default now()
);

-- 2. Historial de procesamiento para idempotencia de correos y archivos
create table if not exists processed_items (
  item_id      text primary key,             -- mail:<mid> o file:<sha256>
  kind         text,                         -- mail | file
  detail       text,
  status       text default 'ok',            -- ok | error
  processed_at timestamptz default now()
);

-- 3. Resúmenes ejecutivos generados por IA (o fallback)
create table if not exists summaries (
  id         bigserial primary key,
  text       text,
  model      text,
  created_at timestamptz default now()
);

-- 4. Seguridad: Row Level Security (RLS)
alter table records enable row level security;
alter table processed_items enable row level security;
alter table summaries enable row level security;

-- Políticas de lectura para rol anon (Dashboard en Streamlit)
create policy "anon read records"   on records   for select to anon using (true);
create policy "anon read summaries" on summaries for select to anon using (true);

-- processed_items queda sin política anon: solo service_role tiene acceso
