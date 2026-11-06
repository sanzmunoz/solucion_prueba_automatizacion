"""Pipeline runner module. It orchestrates reading files, validation, database insertion, and AI summary."""
import argparse, hashlib, logging, os
from pathlib import Path
from dotenv import load_dotenv
from . import db, ai
from .parsers import parse_file
from .validate import validate

log = logging.getLogger("pipeline")

def setup_logging(log_path: Path = Path("data/pipeline.log")):
    """Sets up logging to both a file and the console output."""
    log_path.parent.mkdir(parents=True, exist_ok=True)
    fmt = logging.Formatter("%(asctime)s %(levelname)s [%(name)s] %(message)s")
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    # Add file handler if not already present
    if not any(isinstance(h, logging.FileHandler) for h in root.handlers):
        fh = logging.FileHandler(log_path, encoding="utf-8")
        fh.setFormatter(fmt)
        root.addHandler(fh)
    # Add console stream handler if not already present
    if not any(isinstance(h, logging.StreamHandler) and not isinstance(h, logging.FileHandler) for h in root.handlers):
        sh = logging.StreamHandler()
        sh.setFormatter(fmt)
        root.addHandler(sh)

def file_sha(p: Path) -> str:
    """Calculates the SHA-256 hash of a file for tracking."""
    return hashlib.sha256(p.read_bytes()).hexdigest()

def process_file(c, path: Path) -> dict:
    """Parses, validates, and inserts one file into the database."""
    sha = file_sha(path)
    # Skip file if already processed
    if db.seen(c, "file:" + sha):
        log.info("omitido (ya procesado): %s", path.name)
        return {"file": path.name, "skipped": True}

    try:
        # Parse and validate file records
        recs = validate(parse_file(path))
        # Insert records into database
        new, dup = db.insert_records(c, recs)
        # Mark file as successfully processed
        db.mark(c, "file:" + sha, "file", f"{path.name}: {new} nuevos, {dup} duplicados")
        bad = sum(1 for r in recs if r.issues)
        log.info("%s -> %d filas, %d nuevas, %d duplicadas, %d con problemas", path.name, len(recs), new, dup, bad)
        return {"file": path.name, "rows": len(recs), "new": new, "dup": dup, "issues": bad}
    except Exception as e:
        # Log error and mark file with error status
        log.error("ERROR en %s: %s", path.name, e)
        try:
            db.mark(c, "file:" + sha, "file", f"{path.name}: {e}", "error")
        except Exception as db_err:
            log.error("No se pudo registrar estado de error en Supabase para %s: %s", path.name, db_err)
        return {"file": path.name, "error": str(e)}

def run(local_dir: str | None = None):
    """Executes the pipeline using local folder files or email attachments."""
    load_dotenv()
    setup_logging()
    c = db.connect(service_role=True)
    results = []

    # Step 1: Collect files from local directory or IMAP email
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

    # Step 2: Process each file
    for f in files:
        results.append(process_file(c, f))

    # Step 3: Generate and save the AI executive summary
    try:
        df = db.load_df(c)
        text, model = ai.executive_summary(df)
        db.save_summary(c, text, model)
        log.info("Resumen (%s): %s", model, text)
    except Exception as sum_err:
        log.error("Error generando o guardando el resumen ejecutivo: %s", sum_err)

    return results

if __name__ == "__main__":
    # Command line arguments parser
    ap = argparse.ArgumentParser()
    ap.add_argument("--local")
    run(ap.parse_args().local)
