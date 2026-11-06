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

def setup_logging(log_path: Path = Path("data/pipeline.log")):
    log_path.parent.mkdir(parents=True, exist_ok=True)
    fmt = logging.Formatter("%(asctime)s %(levelname)s [%(name)s] %(message)s")
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    if not any(isinstance(h, logging.FileHandler) for h in root.handlers):
        fh = logging.FileHandler(log_path, encoding="utf-8")
        fh.setFormatter(fmt)
        root.addHandler(fh)
    if not any(isinstance(h, logging.StreamHandler) and not isinstance(h, logging.FileHandler) for h in root.handlers):
        sh = logging.StreamHandler()
        sh.setFormatter(fmt)
        root.addHandler(sh)

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
        try:
            db.mark(c, "file:" + sha, "file", f"{path.name}: {e}", "error")
        except Exception as db_err:
            log.error("No se pudo registrar estado de error en Supabase para %s: %s", path.name, db_err)
        return {"file": path.name, "error": str(e)}

def run(local_dir: str | None = None):
    load_dotenv()
    setup_logging()
    c = db.connect(service_role=True)
    results = []

    if local_dir:
        files = sorted(p for p in Path(local_dir).iterdir() if p.suffix.lower() in (".pdf", ".xlsx", ".xlsm"))
    else:
        from .mail_client import fetch_attachments
        files = []
        try:
            mails = fetch_attachments(
                os.getenv("ALLOWED_SENDER", ""),
                Path("data/downloads"),
                lambda m: db.seen(c, "mail:" + m)
            )
            for mid, paths in mails:
                files += paths
                db.mark(c, "mail:" + mid, "mail", f"{len(paths)} adjuntos")
        except Exception as mail_err:
            log.error("Fallo al consultar buzón de correo IMAP: %s", mail_err)
            return [{"mail_error": str(mail_err)}]

    for f in files:
        results.append(process_file(c, f))

    try:
        df = db.load_df(c)
        text, model = ai.executive_summary(df)
        db.save_summary(c, text, model)
        log.info("Resumen (%s): %s", model, text)
    except Exception as sum_err:
        log.error("Error generando o guardando el resumen ejecutivo: %s", sum_err)

    return results

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--local")
    run(ap.parse_args().local)
