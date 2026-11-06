"""Uso de IA justificado: generar el RESUMEN EJECUTIVO en lenguaje natural y explicar anomalías.
Los números los calcula pandas (exactos); el LLM solo redacta con esos números -> no puede inventar cifras.
Soporta Google Gemini (GOOGLE_API_KEY) y Anthropic Claude (ANTHROPIC_API_KEY).
Sin API key o ante error: fallback determinista (el pipeline nunca se rompe por la IA)."""
import os, json
import httpx
import pandas as pd

try:
    import truststore
    truststore.inject_into_ssl()
except ImportError:
    pass

SYSTEM_PROMPT = (
    "Eres analista de datos. Redacta un resumen ejecutivo de 3-4 frases en español "
    "usando EXCLUSIVAMENTE las cifras dadas. No inventes datos. "
    "Menciona riesgos si hay registros con problemas."
)

def compute_stats(df: pd.DataFrame) -> dict:
    n = len(df)
    inc = int((df["issues"].fillna("") != "").sum()) if n else 0
    top = df["categoria"].value_counts(normalize=True) if n else pd.Series(dtype=float)
    return {"registros": n, "valor_total": float(df["valor"].sum()) if n else 0.0,
            "categoria_principal": top.index[0] if len(top) else None,
            "pct_categoria_principal": round(float(top.iloc[0]) * 100) if len(top) else 0,
            "registros_con_problemas": inc,
            "por_estado": df["estado"].value_counts().to_dict() if n else {},
            "periodo": [str(df["fecha"].min().date()), str(df["fecha"].max().date())] if n and df["fecha"].notna().any() else None}

def fallback_summary(s: dict) -> str:
    if not s["registros"]: return "Aún no hay registros procesados."
    p = f" entre {s['periodo'][0]} y {s['periodo'][1]}" if s["periodo"] else ""
    return (f"Durante el periodo analizado{p} se procesaron {s['registros']} registros por un valor total de "
            f"${s['valor_total']:,.0f}. El {s['pct_categoria_principal']}% corresponde a {s['categoria_principal']} "
            f"y existen {s['registros_con_problemas']} registros con información incompleta o inconsistente.").replace(",", ".")

def _call_gemini(stats_json: str, api_key: str) -> tuple[str, str]:
    model = os.getenv("GEMINI_MODEL") or "gemini-2.5-flash"
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
    payload = {
        "system_instruction": {"parts": [{"text": SYSTEM_PROMPT}]},
        "contents": [{"parts": [{"text": stats_json}]}],
        "generationConfig": {"maxOutputTokens": 300}
    }
    resp = httpx.post(url, headers={"x-goog-api-key": api_key}, json=payload, timeout=20.0)
    resp.raise_for_status()
    text = resp.json()["candidates"][0]["content"]["parts"][0]["text"].strip()
    return text, model

def _call_anthropic(stats_json: str, api_key: str) -> tuple[str, str]:
    import anthropic
    model = os.getenv("ANTHROPIC_MODEL") or "claude-haiku-5-5"
    msg = anthropic.Anthropic(api_key=api_key).messages.create(
        model=model, max_tokens=300,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": stats_json}])
    return msg.content[0].text.strip(), model

def executive_summary(df: pd.DataFrame) -> tuple[str, str]:
    s = compute_stats(df)
    if not s["registros"]:
        return fallback_summary(s), "fallback"

    google_key = os.getenv("GOOGLE_API_KEY")
    anthropic_key = os.getenv("ANTHROPIC_API_KEY")
    if not google_key and not anthropic_key:
        return fallback_summary(s), "fallback"

    stats_json = json.dumps(s, ensure_ascii=False)
    try:
        if google_key:
            return _call_gemini(stats_json, google_key)
        return _call_anthropic(stats_json, anthropic_key)
    except Exception as e:  # red, cuota, clave inválida...
        return fallback_summary(s) + f" (IA no disponible: {type(e).__name__})", "fallback"
