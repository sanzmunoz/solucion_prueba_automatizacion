"""AI executive summary module. It calculates exact metrics and generates text with Gemini or Claude. It uses a safe fallback if no API key is available."""
import os, json, logging
import httpx
import pandas as pd

log = logging.getLogger("ai")

try:
    import truststore
    truststore.inject_into_ssl()
except ImportError:
    pass

# Prompt for the AI model: use exact numbers only
SYSTEM_PROMPT = (
    "Eres analista de datos. Redacta un resumen ejecutivo de 3-4 frases en español "
    "usando EXCLUSIVAMENTE las cifras dadas. No inventes datos. "
    "Menciona riesgos si hay registros con problemas."
)

def compute_stats(df: pd.DataFrame) -> dict:
    """Calculates basic summary numbers from the dataframe."""
    n = len(df)
    # Count rows with validation problems
    inc = int((df["issues"].fillna("") != "").sum()) if n else 0
    # Find the top category
    top = df["categoria"].value_counts(normalize=True) if n else pd.Series(dtype=float)

    return {
        "registros": n,
        "valor_total": float(df["valor"].sum()) if n else 0.0,
        "categoria_principal": top.index[0] if len(top) else None,
        "pct_categoria_principal": round(float(top.iloc[0]) * 100) if len(top) else 0,
        "registros_con_problemas": inc,
        "por_estado": df["estado"].value_counts().to_dict() if n else {},
        "periodo": [str(df["fecha"].min().date()), str(df["fecha"].max().date())] if n and df["fecha"].notna().any() else None
    }

def fallback_summary(s: dict) -> str:
    """Builds a summary text without AI using a simple template."""
    if not s["registros"]:
        return "Aún no hay registros procesados."
    p = f" entre {s['periodo'][0]} y {s['periodo'][1]}" if s["periodo"] else ""
    return (
        f"Durante el periodo analizado{p} se procesaron {s['registros']} registros por un valor total de "
        f"${s['valor_total']:,.0f}. El {s['pct_categoria_principal']}% corresponde a {s['categoria_principal']} "
        f"y existen {s['registros_con_problemas']} registros con información incompleta o inconsistente."
    ).replace(",", ".")

def _call_gemini(stats_json: str, api_key: str) -> tuple[str, str]:
    """Sends the summary request to Google Generative Language API (Gemini)."""
    model = os.getenv("GEMINI_MODEL") or "gemini-3.5-flash"
    if model == "gemini-2.5-flash":
        model = "gemini-3.5-flash"

    payload = {
        "system_instruction": {"parts": [{"text": SYSTEM_PROMPT}]},
        "contents": [{"role": "user", "parts": [{"text": stats_json}]}],
        "generationConfig": {"maxOutputTokens": 300}
    }
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
    resp = httpx.post(url, headers={"x-goog-api-key": api_key}, json=payload, timeout=30.0)
    resp.raise_for_status()
    text = resp.json()["candidates"][0]["content"]["parts"][0]["text"].strip()
    return text, model

def _call_anthropic(stats_json: str, api_key: str) -> tuple[str, str]:
    """Sends the summary request to Anthropic Claude API."""
    import anthropic
    model = os.getenv("ANTHROPIC_MODEL") or "claude-haiku-5-5"
    msg = anthropic.Anthropic(api_key=api_key).messages.create(
        model=model, max_tokens=300,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": stats_json}]
    )
    return msg.content[0].text.strip(), model

def executive_summary(df: pd.DataFrame) -> tuple[str, str]:
    """Creates the executive summary. It tries AI first and uses fallback on error."""
    # Compute summary numbers
    s = compute_stats(df)
    if not s["registros"]:
        return fallback_summary(s), "fallback"

    # Check for available API keys
    google_key = os.getenv("GOOGLE_API_KEY")
    anthropic_key = os.getenv("ANTHROPIC_API_KEY")
    if not google_key and not anthropic_key:
        return fallback_summary(s), "fallback"

    # Try AI call with error protection
    stats_json = json.dumps(s, ensure_ascii=False)
    try:
        if google_key:
            return _call_gemini(stats_json, google_key)
        return _call_anthropic(stats_json, anthropic_key)
    except Exception as e:
        log.warning("Fallo al generar resumen con IA (%s): %s. Usando fallback.", "Google Gemini" if google_key else "Anthropic", e)
        # Return fallback text if API call fails
        return fallback_summary(s), "fallback"
