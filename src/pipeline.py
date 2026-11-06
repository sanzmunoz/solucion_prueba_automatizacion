"""Orquestador: correo -> descarga -> parseo -> validación -> Supabase -> resumen IA.
Uso:  python -m src.pipeline            (IMAP real)
      python -m src.pipeline --local data/samples   (demo sin correo)"""
import argparse, hashlib, logging, os
from pathlib import Path
from dotenv import load_dotenv
from . import db, ai
from .parsers import parse_file
from .validate import validate

log = logging.getLogger("pipeline")

def file_sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()

def process_file(c, path: Path) -> dict:
    sha = file_sha(path)
    if db.seen(c, "file:" + sha):
        log.info("omitido (ya procesado): %s", path.name)
        return {"file": path.name, "skipped": True}
    try:
        recs = validate(parse_file(path))
        new, dup = db.insert_records(c, recs)
        db.mark(c, "file:" + sha, "file", f"{path.name}: {new} nuevos, {dup} duplicados")
        bad = sum(1 for r in recs if r.issues)
        log.info("%s -> %d filas, %d nuevas, %d duplicadas, %d con problemas", path.name, len(recs), new, dup, bad)
        return {"file": path.name, "rows": len(recs), "new": new, "dup": dup, "issues": bad}
    except Exception as e:      # un archivo corrupto no tumba el lote; queda registrado para alerta
        log.error("ERROR en %s: %s", path.name, e)
        db.mark(c, "file:" + sha, "file", f"{path.name}: {e}", "error")
        return {"file": path.name, "error": str(e)}

def run(local_dir: str | None = None):
    load_dotenv()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    c = db.connect(service_role=True)
    results = []

    if local_dir:
        files = sorted(p for p in Path(local_dir).iterdir() if p.suffix.lower() in (".pdf", ".xlsx", ".xlsm"))
    else:
        from .mail_client import fetch_attachments
        files = []
        mails = fetch_attachments(
            os.environ["ALLOWED_SENDER"],
            Path("data/downloads"),
            lambda m: db.seen(c, "mail:" + m)
        )
        for mid, paths in mails:
            files += paths
            db.mark(c, "mail:" + mid, "mail", f"{len(paths)} adjuntos")

    for f in files:
        results.append(process_file(c, f))

    df = db.load_df(c)
    text, model = ai.executive_summary(df)
    db.save_summary(c, text, model)
    log.info("Resumen (%s): %s", model, text)
    return results

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--local")
    run(ap.parse_args().local)
