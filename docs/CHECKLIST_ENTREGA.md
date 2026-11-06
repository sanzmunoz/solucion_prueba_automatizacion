# Checklist de Cobertura de Requisitos de la Prueba Técnica

Matriz de correspondencia entre los requerimientos solicitados en el enunciado y su implementación verificada en **Solucion_entrega**.

---

## 1. Requerimientos Funcionales Obligatorios

| Numeral | Requerimiento del Enunciado | Estado | Implementación en este Repositorio |
|---|---|:---:|---|
| **3.1** | **Conexión a Correo Electrónico:** identificar remitente exacto, descargar archivos PDF/Excel e impedir reprocesamiento de correos o archivos duplicados. | **Completado** | Implementado en `src/mail_client.py` con `IMAP4_SSL`, validación RFC 2822 de `From`, descarga en `data/downloads/` y registro de Message-ID en `processed_items`. |
| **3.2** | **Procesamiento de Documentos:** extraer campos de Excel y PDF (`Fecha, Cliente, Categoría, Valor, Estado, etc.`) y normalizarlos a una estructura común. | **Completado** | Implementado en `src/parsers.py` y `src/schema.py`. Soporta tablas con bordes, texto sin bordes y pares clave-valor verticales (`KV_LINE`). |
| **4** | **Uso de Inteligencia Artificial Justificado:** resolver un problema concreto y justificar por qué no se usó en tareas deterministas. | **Completado** | Implementado en `src/ai.py`. Redacta el resumen ejecutivo con base en estadísticas exactas calculadas por `pandas`. Documentado en `docs/USO_DE_IA.md`. |
| **5** | **Dashboard:** visualizar total de registros, valor total, por categoría, por estado, evolución temporal y **al menos 2 métricas adicionales explicadas**. | **Completado** | Implementado en `dashboard.py` (Streamlit + Plotly). Métricas adicionales: *Ticket promedio*, *Porcentaje de completitud*, *Registros con problemas* y *Clientes únicos*. |
| **6** | **Automatización:** ejecución sin intervención manual mediante flujo programado o programable. | **Completado** | Implementado en `.github/workflows/ingest.yml` con cron horario de 8:00 a 18:00 hora Colombia (`0 13-23 * * *`). |
| **7** | **Persistencia:** almacenamiento estructurado que impida registros duplicados. | **Completado** | Implementado en Supabase (PostgreSQL) con `row_hash` como clave primaria y deduplicación por lotes (Opción A en `src/db.py`). |
| **8** | **Despliegue Gratuito:** disponible en plataformas free tier (Vercel, Streamlit Cloud, Supabase, Actions) con limitaciones explicadas. | **Completado** | Desplegable en Streamlit Community Cloud (front) + GitHub Actions (ingesta) + Supabase (base de datos). |
| **9** | **Defensa de la Solución:** capacidad de explicar arquitectura, decisiones, prompts, errores encontrados y validación. | **Completado** | Documentado en detalle en `docs/DECISIONES.md`, `docs/USO_DE_IA.md` y `docs/ARQUITECTURA.md`. |
| **10** | **Entregables:** repositorio con código, `.gitignore`, `.env.example`, `README` y diagrama de arquitectura. | **Completado** | Todos los archivos organizados en la raíz con commits individuales atómicos. |

---

## 2. Puntos Bonus (Opcionales)

| Bonus | Estado | Detalle de Implementación |
|---|:---:|---|
| **Tests Automatizados** | **Completado** | 20 pruebas automáticas en `tests/test_core.py` ejecutadas con `pytest` (cobertura de parsers, fechas, divisas, deduplicación, errores y live Supabase). |
| **Manejo de Errores** | **Completado** | Bloques defensivos en `mail_client.py`, un archivo corrupto no detiene el lote en `pipeline.py`, y fallback determinista ante fallos de IA en `ai.py`. |
| **Logs del Proceso** | **Completado** | Logging dual simultáneo en consola y en `data/pipeline.log` mediante `logging`, además de registro persistente en la tabla `processed_items` de Supabase. |
| **Historial de Archivos** | **Completado** | Visualizable en el dashboard en la sección *"Historial de archivos procesados"*, con estatus de auditoría (`ok` / `error`) y detalle de filas. |
| **Alertas de Errores e Inconsistencias** | **Completado** | Banners visuales activos en la cabecera del dashboard (`st.error` ante archivos corruptos y `st.warning` ante registros con problemas de calidad). |
| **Detección de Datos Inconsistentes** | **Completado** | Reglas de validación en `src/validate.py` que detectan campos vacíos, importes no positivos y fechas futuras. |
| **GitHub Actions** | **Completado** | Pipeline CI/CD programado en horario laboral con inyección segura de secretos. |
