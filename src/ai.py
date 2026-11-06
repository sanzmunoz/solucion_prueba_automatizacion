"""Uso de IA justificado: generar el RESUMEN EJECUTIVO en lenguaje natural y explicar anomalías.
Los números los calcula pandas (exactos); el LLM solo redacta con esos números -> no puede inventar cifras.
Sin API key o ante error: fallback determinista (el pipeline nunca se rompe por la IA)."""
import os, json
import pandas as pd

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

def executive_summary(df: pd.DataFrame) -> tuple[str, str]:
    s = compute_stats(df)
    key = os.getenv("ANTHROPIC_API_KEY")
    if not key or not s["registros"]: return fallback_summary(s), "fallback"
    try:
        import anthropic
        model = os.getenv("ANTHROPIC_MODEL", "claude-haiku-5-5")
        msg = anthropic.Anthropic(api_key=key).messages.create(
            model=model, max_tokens=300,
            system="Eres analista de datos. Redacta un resumen ejecutivo de 3-4 frases en español usando EXCLUSIVAMENTE las cifras dadas. No inventes datos. Menciona riesgos si hay registros con problemas.",
            messages=[{"role": "user", "content": json.dumps(s, ensure_ascii=False)}])
        return msg.content[0].text.strip(), model
    except Exception as e:  # red, cuota, clave inválida...
        return fallback_summary(s) + f" (IA no disponible: {type(e).__name__})", "fallback"
