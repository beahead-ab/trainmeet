"""A small PDF writer for the tests: text, lines and round marks on one A4 page, laid out as the
planning program prints its pages, or a scanned page as a picture without text. Coordinates from
the top left, as on the screen."""

from __future__ import annotations

import zlib
from dataclasses import dataclass, field

WIDTH, HEIGHT = 842.0, 595.0
KAPPA = 0.5523  # a quarter circle as a Bézier curve


@dataclass
class Sheet:
    ops: list[str] = field(default_factory=list)
    scan: tuple[int, int, bytes] | None = None  # a scanned page: width, height, grey pixels

    def scanned(self, width: int, height: int, pixels: bytes) -> Sheet:
        """The whole page a picture, as a scanner makes it: 8-bit grey, no text."""
        self.scan = (width, height, pixels)
        self.ops.append(f"q {WIDTH} 0 0 {HEIGHT} 0 0 cm /Im0 Do Q")
        return self

    def text(self, x: float, baseline: float, words: str, size: float = 9) -> Sheet:
        raw = words.encode("cp1252").replace(b"\\", b"\\\\").replace(b"(", b"\\(")
        literal = raw.replace(b")", b"\\)").decode("latin-1")
        self.ops.append(f"BT /F1 {size} Tf {x:.2f} {HEIGHT - baseline:.2f} Td ({literal}) Tj ET")
        return self

    def line(self, a: tuple[float, float], b: tuple[float, float], width: float = 4) -> Sheet:
        self.ops.append(
            f"{width} w {a[0]:.2f} {HEIGHT - a[1]:.2f} m {b[0]:.2f} {HEIGHT - b[1]:.2f} l S"
        )
        return self

    def mark(self, x: float, y: float, r: float = 1.75) -> Sheet:
        cy, k = HEIGHT - y, KAPPA * r
        self.ops.append(
            f"2 w {x + r:.2f} {cy:.2f} m "
            f"{x + r:.2f} {cy + k:.2f} {x + k:.2f} {cy + r:.2f} {x:.2f} {cy + r:.2f} c "
            f"{x - k:.2f} {cy + r:.2f} {x - r:.2f} {cy + k:.2f} {x - r:.2f} {cy:.2f} c "
            f"{x - r:.2f} {cy - k:.2f} {x - k:.2f} {cy - r:.2f} {x:.2f} {cy - r:.2f} c "
            f"{x + k:.2f} {cy - r:.2f} {x + r:.2f} {cy - k:.2f} {x + r:.2f} {cy:.2f} c S"
        )
        return self


def pdf(*sheets: Sheet) -> bytes:
    """The sheets as a PDF, one page each, in Helvetica."""
    objects: list[bytes] = []
    kids = " ".join(f"{3 + 2 * i} 0 R" for i in range(len(sheets)))
    font = 3 + 2 * len(sheets)
    objects.append(b"<< /Type /Catalog /Pages 2 0 R >>")
    objects.append(f"<< /Type /Pages /Kids [{kids}] /Count {len(sheets)} >>".encode())
    images: list[bytes] = []
    for i, sheet in enumerate(sheets):
        stream = "\n".join(sheet.ops).encode("latin-1")
        xobject = ""
        if sheet.scan:
            width, height, pixels = sheet.scan
            body = zlib.compress(pixels)
            xobject = f" /XObject << /Im0 {font + 1 + len(images)} 0 R >>"
            images.append(
                f"<< /Type /XObject /Subtype /Image /Width {width} /Height {height} "
                f"/ColorSpace /DeviceGray /BitsPerComponent 8 /Filter /FlateDecode "
                f"/Length {len(body)} >>\nstream\n".encode()
                + body
                + b"\nendstream"
            )
        objects.append(
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {WIDTH} {HEIGHT}] "
            f"/Contents {4 + 2 * i} 0 R "
            f"/Resources << /Font << /F1 {font} 0 R >>{xobject} >> >>".encode()
        )
        objects.append(f"<< /Length {len(stream)} >>\nstream\n".encode() + stream + b"\nendstream")
    objects.append(
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>"
    )
    objects.extend(images)
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for number, body in enumerate(objects, 1):
        offsets.append(len(out))
        out += f"{number} 0 obj\n".encode() + body + b"\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode()
    out += b"".join(f"{offset:010d} 00000 n \n".encode() for offset in offsets)
    out += (
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    )
    return bytes(out)
