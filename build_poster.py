"""Render poster.html with the current public scan URL encoded in its inline SVG QR."""

from html import escape
from pathlib import Path

from config import settings
from qr_code import qr_svg


ROOT = Path(__file__).parent


def scan_url() -> str:
    base = settings.public_base_url.rstrip("/")
    return f"{base}/scan?location={escape(settings.default_location_code, quote=True)}"


def render_poster() -> str:
    template = (ROOT / "poster_template.html").read_text(encoding="utf-8")
    return template.replace("{{ QR_SVG }}", qr_svg(scan_url()))


if __name__ == "__main__":
    (ROOT / "poster.html").write_text(render_poster(), encoding="utf-8")
    print(f"Wrote poster.html with QR destination: {scan_url()}")
