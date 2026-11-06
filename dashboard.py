import os
import pandas as pd
import plotly.express as px
import streamlit as st
from dotenv import load_dotenv
from src import db

load_dotenv()
st.set_page_config(page_title="Dashboard Operacional", layout="wide")

try:
    c = db.connect(service_role=False)
    df = db.load_df(c)
except Exception as e:
    st.error(f"Error conectando a Supabase: {e}")
    st.info("Verifica que SUPABASE_URL y SUPABASE_ANON_KEY estén configuradas en .env o Streamlit Secrets.")
    st.stop()

st.title("Dashboard Operacional")

if df.empty:
    st.info("Aún no hay datos en Supabase. Ejecuta: python -m src.pipeline --local data/samples")
    st.stop()

with st.sidebar:
    st.header("Filtros")
    estados_disponibles = sorted(df.estado.dropna().unique())
    est = st.multiselect("Estado", estados_disponibles, default=estados_disponibles)
    clientes_disponibles = sorted(df.cliente.dropna().unique())
    cli = st.multiselect("Cliente", clientes_disponibles)

    d = df[df.estado.isin(est) | df.estado.isna()]
    if cli:
        d = d[d.cliente.isin(cli)]

d = d.copy()
d["problema"] = d.issues.fillna("") != ""

# KPIs obligatorios + métricas adicionales justificadas
done = d[d.estado == "Completado"]
k = st.columns(6)
k[0].metric("Registros", len(d))
k[1].metric("Valor total", f"${d.valor.sum():,.0f}".replace(",", "."))
k[2].metric("Ticket promedio", f"${d.valor.mean():,.0f}".replace(",", ".") if len(d) else "-")      # Extra 1: tamaño típico de operación
k[3].metric("% completado", f"{len(done)/len(d)*100:.0f}%" if len(d) else "-")                       # Extra 2: eficiencia del proceso
k[4].metric("Con problemas", int(d.problema.sum()))                                                  # Extra 3: calidad del dato
k[5].metric("Clientes únicos", d.cliente.nunique())

# Gráficos
a, b = st.columns(2)
cat_data = d.groupby("categoria", dropna=False).size().reset_index(name="registros")
a.plotly_chart(
    px.bar(cat_data, x="categoria", y="registros", title="Registros por categoría"),
    width="stretch"
)
b.plotly_chart(
    px.pie(d, names="estado", title="Registros por estado", hole=0.4),
    width="stretch"
)

# Evolución temporal
time_df = d.dropna(subset=["fecha"]).groupby(pd.Grouper(key="fecha", freq="D")).agg(
    registros=("row_hash", "count"),
    valor=("valor", "sum")
).reset_index()

st.plotly_chart(
    px.line(time_df, x="fecha", y=["registros", "valor"], markers=True, title="Evolución diaria")
    .update_yaxes(matches=None),
    width="stretch"
)

# Resumen ejecutivo con IA
st.subheader("Resumen ejecutivo (IA)")
s = db.latest_summary(c)
if s:
    st.write(s[0])
    st.caption(f"Modelo: {s[1]} · Creado: {s[2]}")
else:
    st.write("Aún no generado.")

# Registros con incidencias
st.subheader("Registros con inconsistencias o datos incompletos")
bad_rows = d[d.problema][["fecha", "cliente", "categoria", "valor", "estado", "issues", "source_file"]]
if not bad_rows.empty:
    st.dataframe(bad_rows, width="stretch")
else:
    st.success("No hay registros con incidencias en la selección actual.")

# Historial de ingesta
st.subheader("Historial de archivos procesados")
hist = db.load_processed_history(c)
if not hist.empty:
    st.dataframe(hist, width="stretch")
else:
    # Resumen de archivos desde los registros cargados
    files_summary = d.groupby("source_file").agg(
        registros=("row_hash", "count"),
        con_problemas=("problema", "sum")
    ).reset_index()
    st.dataframe(files_summary, width="stretch")
