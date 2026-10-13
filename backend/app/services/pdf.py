"""HTML to PDF, through the browser that is already in the stack.

A teacher's guide that only exists on a screen is not much use to a teacher
whose classroom has no screen in it. The console's Print button hands that job
to whatever browser the operator happens to have; a downloaded file is the same
document every time, and can be sent to somebody who is not sitting at the
console.

Chromium renders it: the stack's browser service where it answers, the one
bundled in this image where it does not (see `browser.py`). One HTML engine,
so the PDF and the reader agree about page breaks.
"""
from __future__ import annotations

import asyncio
import logging

logger = logging.getLogger("cbc-pdf")

# A guide is tens of pages at most. Long enough for a slow render, short enough
# that a wedged browser does not hold a worker.
TIMEOUT_MS = 60_000


class PdfUnavailable(RuntimeError):
    """The browser service could not produce a PDF, and said why."""


async def _render(html: str) -> bytes:
    from .browser import open_browser

    async with open_browser() as browser:
        context = await browser.new_context()
        page = await context.new_page()
        # set_content rather than a URL: the document never leaves this
        # process, so there is nothing to serve and nothing to clean up.
        await page.set_content(html, wait_until="load", timeout=TIMEOUT_MS)
        pdf = await page.pdf(
            format="A4",
            print_background=True,
            # The @page rule in the document owns the margins; overriding
            # them here would fight it.
            prefer_css_page_size=True,
        )
        await context.close()
        return pdf


def from_html(html: str) -> bytes:
    """Render a complete HTML document to PDF bytes."""
    try:
        return asyncio.run(_render(html))
    except Exception as exc:  # noqa: BLE001
        logger.warning("Could not render a PDF: %s", exc)
        raise PdfUnavailable(
            f"Neither the browser service nor the local Chromium could render "
            f"this to PDF ({str(exc).splitlines()[0][:200]}). Check that the "
            f"`playwright` container is running, or that the image has its own "
            f"Chromium (`python -m playwright install --with-deps chromium`). "
            f"In the meantime the guide can be printed from the reader, and "
            f"saved as PDF from the print dialog."
        ) from exc


# ── which pages ──────────────────────────────────────────────────────────────
#
# A school printing forty copies on an L3250 prints the odd pages, turns the
# stack, and prints the even pages. The attendant wants those two PDFs, not
# one PDF and a printer dialog forty times.

def parse_pages(spec: str, total: int) -> list[int]:
    """1-based page numbers for a spec: '', 'all', 'odd', 'even', or ranges
    like '1-4,7,10-'. Out-of-range numbers are dropped; empty means all."""
    spec = (spec or "").strip().lower()
    if not spec or spec == "all":
        return list(range(1, total + 1))
    if spec == "odd":
        return list(range(1, total + 1, 2))
    if spec == "even":
        return list(range(2, total + 1, 2))
    out: list[int] = []
    for part in spec.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            lo, _, hi = part.partition("-")
            try:
                start = int(lo) if lo.strip() else 1
                end = int(hi) if hi.strip() else total
            except ValueError:
                continue
            out += [n for n in range(max(1, start), min(total, end) + 1)]
        else:
            try:
                n = int(part)
            except ValueError:
                continue
            if 1 <= n <= total:
                out.append(n)
    seen: set[int] = set()
    return [n for n in out if not (n in seen or seen.add(n))]


def select_pages(data: bytes, spec: str = "", *, reverse: bool = False) -> bytes:
    """The PDF with only the pages the spec names, in order — reversed when
    the printer stacks face-up and the second pass must run backwards."""
    from io import BytesIO

    from pypdf import PdfReader, PdfWriter

    reader = PdfReader(BytesIO(data))
    total = len(reader.pages)
    wanted = parse_pages(spec, total)
    if wanted == list(range(1, total + 1)) and not reverse:
        return data
    if reverse:
        wanted = list(reversed(wanted))
    writer = PdfWriter()
    for n in wanted:
        writer.add_page(reader.pages[n - 1])
    out = BytesIO()
    writer.write(out)
    return out.getvalue()


def page_count(data: bytes) -> int:
    from io import BytesIO

    from pypdf import PdfReader

    return len(PdfReader(BytesIO(data)).pages)
