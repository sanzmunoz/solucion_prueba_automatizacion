# Justificación y Documentación del Uso de Inteligencia Artificial

Este documento da cumplimiento explícito a los requerimientos de los **numerales 4 y 9 del enunciado**: justificación del uso de IA, control de alucinaciones, prompts implementados y registro de errores reales superados durante el desarrollo.

---

## 1. Uso de IA dentro de la Solución

### ¿Qué hace la IA?
Genera una **síntesis ejecutiva en lenguaje natural (3 a 4 frases)** a partir de las métricas consolidadas en cada ciclo de ingesta o filtro del dashboard.

### ¿Por qué se decidió usar IA y qué problema resuelve?
- **Problema que resuelve:** Los líderes operacionales necesitan un reporte conciso y accionable que no requiera redactarse a mano en cada corte ni dependa de plantillas estáticas y rígidas.
- **Aporte de valor:** El LLM contextualiza los números clave (volumen total, ticket, categoría dominante) y destaca explícitamente los riesgos asociados a registros con anomalías o inconsistencias.

### ¿Dónde NO se usa IA y por qué?
- **NO en extracción ni parseo de Excel o PDF:** Los formatos siguen un diseño estandarizado. Extraer datos con un LLM sería costoso por tokens, lento (segundos por página), no determinista y propenso a fallas por alucinación en números y comas decimales. El código tradicional (`openpyxl`, `pdfplumber`, regex) es exacto, gratuito y testeable.
- **NO en validación:** Las reglas de negocio (ej. valores mayores a cero, fechas no futuras, campos obligatorios presentes) se resuelven de forma 100% confiable con sentencias lógicas en Python.

---

## 2. Prompts y Control de Alucinaciones

### Prompt de Sistema
```text
Eres analista de datos. Redacta un resumen ejecutivo de 3-4 frases en español usando EXCLUSIVAMENTE las cifras dadas. No inventes datos. Menciona riesgos si hay registros con problemas.
```

### Prompt de Usuario
Un objeto JSON estructurado calculado previamente con `pandas`:
```json
{
  "registros": 53,
  "valor_total": 34504000.0,
  "categoria_principal": "Servicio A",
  "pct_categoria_principal": 34,
  "registros_con_problemas": 2,
  "por_estado": {
    "Completado": 33,
    "Pendiente": 14,
    "Rechazado": 5,
    "vendido - completo": 1
  },
  "periodo": ["2026-10-01", "2026-11-02"]
}
```

### Mecanismo de Validación y Fallback
1. **Control de datos:** El modelo **no hace cálculos matemáticos**; solo redacta con números ya computados por código.
2. **Resiliencia (Fallback determinista):** Si la API de IA no está configurada, no tiene saldo o sufre una caída de red, una función en Python genera automáticamente una síntesis determinista utilizando las mismas variables exactas. El pipeline de automatización **nunca se interrumpe** por fallas del proveedor de IA.

---

## 3. Errores Reales Encontrados y Soluciones Aplicadas

| # | Error Encontrado | Causa Raíz | Solución Técnica Aplicada |
|---|---|---|---|
| **1** | `[SSL: CERTIFICATE_VERIFY_FAILED]` en llamadas HTTPS desde Windows (Python 3.14) | El entorno virtual de Windows no accedía automáticamente a los certificados raíz del sistema operativo. | Se integró `truststore.inject_into_ssl()` en `db.py` y `ai.py` para utilizar los certificados nativos del sistema. |
| **2** | `HTTP 404 / 403` en llamadas a Gemini con API key de Vertex AI (`AQ...`) | Las claves de Google pueden provenir de Google AI Studio (`AIza...`) o de Vertex AI Express (`AQ...`), las cuales apuntan a endpoints REST diferentes. | Se añadió autodetección por prefijo de clave en `_call_gemini()` para enrutar dinámicamente a la URL correcta. |
| **3** | PDF de prueba real devolvía 0 filas con `extract_tables()` | El documento enviado por correo real (`ventaSas.pdf`) tenía una estructura clave-valor vertical (`Cliente Empresa: ...`, `Valor: ...`) en lugar de una tabla con bordes. | Se incorporó una expresión regular especializada (`KV_LINE`) en `parse_pdf()` que reconoce pares clave-valor y construye el registro estándar. |
| **4** | Descarga de adjuntos de correos ajenos generaba registros vacíos | Correos históricos en la bandeja de entrada contenían archivos no relacionados con la prueba. | Se blindó `_rows()` en `parsers.py` para ignorar tablas que no contengan encabezados válidos del negocio. |

---

## 4. Checklist para la Defensa Técnica en Entrevista

- [x] Explicar por qué la IA solo se utiliza en la redacción y no en el cálculo ni en el parseo.
- [x] Explicar el funcionamiento del fallback determinista ante fallos de conexión.
- [x] Demostrar la deduplicación en 3 capas: `Message-ID` de correo, SHA-256 de archivo y `row_hash` de registro.
- [x] Explicar la política de mínimo privilegio con RLS en Supabase (escritura con `service_role`, lectura pública con `anon`).
