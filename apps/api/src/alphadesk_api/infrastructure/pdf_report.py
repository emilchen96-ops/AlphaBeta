"""Generate a CJK-capable PDF research artifact on demand."""

from __future__ import annotations

from io import BytesIO


def markdown_to_pdf(markdown: str, *, title: str) -> bytes:
    try:
        from reportlab.lib.pagesizes import A4  # type: ignore[import-untyped]
        from reportlab.pdfbase import pdfmetrics  # type: ignore[import-untyped]
        from reportlab.pdfbase.cidfonts import UnicodeCIDFont  # type: ignore[import-untyped]
        from reportlab.pdfgen.canvas import Canvas  # type: ignore[import-untyped]
    except ImportError as exc:  # pragma: no cover - deployment dependency guard
        raise RuntimeError("PDF export dependency is not installed") from exc

    pdfmetrics.registerFont(UnicodeCIDFont("STSong-Light"))
    buffer = BytesIO()
    canvas = Canvas(buffer, pagesize=A4)
    _, height = A4
    canvas.setTitle(title)
    canvas.setFont("STSong-Light", 11)
    y = height - 48
    for raw_line in markdown.splitlines():
        line = raw_line.lstrip("#>- ").strip()
        if not line:
            y -= 8
            continue
        chunks = [line[index : index + 45] for index in range(0, len(line), 45)] or [""]
        for chunk in chunks:
            if y < 48:
                canvas.showPage()
                canvas.setFont("STSong-Light", 11)
                y = height - 48
            canvas.drawString(48, y, chunk)
            y -= 17
    canvas.save()
    return buffer.getvalue()
