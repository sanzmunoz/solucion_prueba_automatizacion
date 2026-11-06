"""IMAP (sirve con Gmail, Outlook, etc.). Solo correos del remitente autorizado y con adjuntos PDF/xlsx."""
import imaplib, email, os, hashlib, logging
from email.utils import parseaddr
from pathlib import Path

log = logging.getLogger("mail_client")
EXTS = (".pdf", ".xlsx", ".xlsm")

def fetch_attachments(sender: str, dest: Path, is_seen) -> list[tuple[str, list[Path]]]:
    """Devuelve [(message_id, [paths])]. `is_seen(message_id)` evita reprocesar correos."""
    host = os.getenv("IMAP_HOST")
    user = os.getenv("IMAP_USER")
    password = os.getenv("IMAP_PASSWORD")
    if not host or not user or not password or not sender:
        raise ValueError("Credenciales IMAP incompletas (IMAP_HOST, IMAP_USER, IMAP_PASSWORD, ALLOWED_SENDER).")

    dest.mkdir(parents=True, exist_ok=True)
    M = None
    out = []
    try:
        M = imaplib.IMAP4_SSL(host)
        M.login(user, password)
        M.select("INBOX", readonly=True)
        _, data = M.search(None, "FROM", f'"{sender}"')
        for num in (data[0] or b"").split():
            try:
                _, md = M.fetch(num, "(BODY.PEEK[])")
                msg = email.message_from_bytes(md[0][1])
                if parseaddr(msg.get("From", ""))[1].lower() != sender.lower():
                    continue   # valida remitente exacto (anti-spoof básico de display name)
                mid = (msg.get("Message-ID") or num.decode()).strip()
                if is_seen(mid):
                    continue
                paths = []
                for part in msg.walk():
                    name = part.get_filename()
                    if name and name.lower().endswith(EXTS):
                        payload = part.get_payload(decode=True)
                        if payload:
                            p = dest / f"{hashlib.md5(mid.encode()).hexdigest()[:8]}_{Path(name).name}"
                            p.write_bytes(payload)
                            paths.append(p)
                out.append((mid, paths))
            except Exception as msg_err:
                log.error("Error procesando correo #%s: %s", num, msg_err)
    except Exception as conn_err:
        log.error("Error en conexión IMAP (%s): %s", host, conn_err)
        raise
    finally:
        if M is not None:
            try:
                M.logout()
            except Exception:
                pass
    return out
