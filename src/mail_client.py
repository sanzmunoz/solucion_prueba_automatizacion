"""Email client module using IMAP. It downloads attachments from authorized senders."""
import imaplib, email, os, hashlib, logging
from email.utils import parseaddr
from pathlib import Path

log = logging.getLogger("mail_client")

# Allowed attachment file extensions
EXTS = (".pdf", ".xlsx", ".xlsm")

def fetch_attachments(sender: str, dest: Path, is_seen) -> list[tuple[str, list[Path]]]:
    """Connects to IMAP server, finds emails from sender, and downloads valid attachments.
    Returns a list of (message_id, [downloaded_file_paths]).
    """
    # Check required environment variables
    host = os.getenv("IMAP_HOST")
    user = os.getenv("IMAP_USER")
    password = os.getenv("IMAP_PASSWORD")
    if not host or not user or not password or not sender:
        raise ValueError("Credenciales IMAP incompletas (IMAP_HOST, IMAP_USER, IMAP_PASSWORD, ALLOWED_SENDER).")

    dest.mkdir(parents=True, exist_ok=True)
    M = None
    out = []

    try:
        # Connect to IMAP server with SSL
        M = imaplib.IMAP4_SSL(host)
        M.login(user, password)
        M.select("INBOX", readonly=True)

        # Search emails sent by the authorized sender
        _, data = M.search(None, "FROM", f'"{sender}"')

        # Read each matching email
        for num in (data[0] or b"").split():
            try:
                _, md = M.fetch(num, "(BODY.PEEK[])")
                msg = email.message_from_bytes(md[0][1])

                # Verify sender email address matches exactly
                if parseaddr(msg.get("From", ""))[1].lower() != sender.lower():
                    continue

                mid = (msg.get("Message-ID") or num.decode()).strip()

                # Skip email if already processed
                if is_seen(mid):
                    continue

                # Find and save valid attachments
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
        # Always logout from server if connected
        if M is not None:
            try:
                M.logout()
            except Exception:
                pass

    return out
