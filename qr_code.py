"""Locally generate an inline, self-contained SVG QR code."""

from html import escape

import qrcode


def qr_svg(value: str) -> str:
    if not value:
        raise ValueError("QR destination must not be empty")
    qr = qrcode.QRCode(version=None, error_correction=qrcode.constants.ERROR_CORRECT_M, box_size=1, border=4)
    qr.add_data(value.encode("utf-8"))
    qr.make(fit=True)
    # Check the input byte string handed to the QR encoder before drawing its modules.
    if qr.data_list[0].data != value.encode("utf-8"):
        raise ValueError("QR encoder input differs from configured URL")
    matrix = qr.get_matrix()
    size = len(matrix)
    blocks = [f'<rect width="{size}" height="{size}" fill="#FFFFFF"/>']
    blocks.extend(
        f'<rect x="{x}" y="{y}" width="1" height="1" fill="#000000"/>'
        for y, row in enumerate(matrix)
        for x, dark in enumerate(row)
        if dark
    )
    label = escape(f"QR code for {value}", quote=True)
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {size} {size}" '
        f'role="img" aria-label="{label}" shape-rendering="crispEdges">'
        + "".join(blocks)
        + "</svg>"
    )
