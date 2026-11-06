"""IMAP (sirve con Gmail, Outlook, etc.). Solo correos del remitente autorizado y con adjuntos PDF/xlsx."""
import imaplib, email, os, hashlib
from email.utils import parseaddr
from pathlib import Path

EXTS = (".pdf", ".xlsx", ".xlsm")

def fetch_attachments(sender: str, dest: Path, is_seen):
    """Devuelve [(message_id, [paths])]. `is_seen(message_id)` evita reprocesar correos."""
    dest.mkdir(parents=True, exist_ok=True)
    M = imaplib.IMAP4_SSL(os.environ["IMAP_HOST"]); M.login(os.environ["IMAP_USER"], os.environ["IMAP_PASSWORD"])
    M.select("INBOX", readonly=True)
    _, data = M.search(None, "FROM", f'"{sender}"')
    out = []
    for num in data[0].split():
        _, md = M.fetch(num, "(BODY.PEEK[])")
        msg = email.message_from_bytes(md[0][1])
        if parseaddr(msg.get("From", ""))[1].lower() != sender.lower(): continue   # valida remitente exacto (anti-spoof básico de display name)
        mid = (msg.get("Message-ID") or num.decode()).strip()
        if is_seen(mid): continue
        paths = []
        for part in msg.walk():
            name = part.get_filename()
            if name and name.lower().endswith(EXTS):
                p = dest / f"{hashlib.md5(mid.encode()).hexdigest()[:8]}_{Path(name).name}"
                p.write_bytes(part.get_payload(decode=True)); paths.append(p)
        out.append((mid, paths))
    M.logout(); return out
