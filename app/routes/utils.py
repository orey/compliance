from datetime import date

from flask import abort, send_file

from .. import db

XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def parse_date(value):
    try:
        return date.fromisoformat(value) if value else None
    except ValueError:
        return None


def get_or_404(model, ident):
    obj = db.session.get(model, ident)
    if obj is None:
        abort(404)
    return obj


def send_xlsx(buffer, filename):
    return send_file(buffer, mimetype=XLSX_MIME, as_attachment=True, download_name=filename)


def safe_filename(*parts):
    raw = "_".join(str(p) for p in parts if p)
    return "".join(c if c.isalnum() or c in "-_." else "_" for c in raw)


def safe_next(value, default):
    """Only allow redirects to local paths (absolute referrer URLs are reduced to their path)."""
    from urllib.parse import urlsplit

    if not value:
        return default
    parts = urlsplit(value)
    path = parts.path + (f"?{parts.query}" if parts.query else "")
    return path if path.startswith("/") and not path.startswith("//") else default
