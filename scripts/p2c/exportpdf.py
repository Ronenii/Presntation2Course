"""Course HTML -> matching PDF via headless Chromium, using the same print.css the
in-page Download PDF button uses, so the two outputs cannot drift.

Mermaid renders client-side, so the print must not start before the diagrams exist.
--virtual-time-budget advances timers and waits for the page to quiesce, which covers
Mermaid's render; course.js also sets data-mermaid-ready="true" when it finishes, which is
what a future CDP-based exporter would wait on.
"""

import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

from p2c.normalize import BadDeck, CHROMIUM_CANDIDATES, find_chromium, pdf_page_count

SKIP_REASON = (
    "headless Chromium was not found, so the PDF was not written. "
    "Open the course HTML and use the Download PDF button instead."
)
VIRTUAL_TIME_BUDGET_MS = 20000


class ExportError(Exception):
    """Chromium was available but the export failed."""


@dataclass
class ExportResult:
    pdf: Path | None
    pages: int
    skipped: bool
    reason: str | None


def pdf_command(
    chromium: str, html_path: Path, pdf_path: Path, profile_dir: Path
) -> list[str]:
    return [
        chromium,
        "--headless=new",
        "--disable-gpu",
        "--no-sandbox",
        "--no-first-run",
        "--no-pdf-header-footer",
        f"--user-data-dir={profile_dir}",
        f"--virtual-time-budget={VIRTUAL_TIME_BUDGET_MS}",
        "--run-all-compositor-stages-before-draw",
        f"--print-to-pdf={pdf_path}",
        Path(html_path).resolve().as_uri(),
    ]


def export_pdf(
    html_path: Path,
    pdf_path: Path,
    chromium: str | None = None,
    timeout: int = 180,
) -> ExportResult:
    html_path, pdf_path = Path(html_path), Path(pdf_path)
    if not html_path.is_file():
        raise ExportError(f"{html_path}: no such file")

    browser = find_chromium(chromium)
    if browser is None:
        return ExportResult(pdf=None, pages=0, skipped=True, reason=SKIP_REASON)

    pdf_path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="p2c-chrome-") as profile:
        command = pdf_command(browser, html_path, pdf_path, Path(profile))
        try:
            proc = subprocess.run(command, capture_output=True, text=True, timeout=timeout)
        except subprocess.TimeoutExpired as exc:
            raise ExportError(f"{browser} timed out after {timeout}s") from exc
    if proc.returncode != 0:
        raise ExportError(f"{browser} exited {proc.returncode}: {proc.stderr.strip()}")
    if not pdf_path.is_file():
        raise ExportError(f"{browser} exited 0 but wrote no PDF at {pdf_path}")
    try:
        pages = pdf_page_count(pdf_path.read_bytes())
    except BadDeck as exc:
        raise ExportError(f"{pdf_path} is not a usable PDF: {exc}") from exc
    return ExportResult(pdf=pdf_path, pages=pages, skipped=False, reason=None)


def main(argv: list[str]) -> int:
    import argparse
    import json
    import sys

    parser = argparse.ArgumentParser(
        prog="export-pdf", description="Render the course HTML to a matching PDF."
    )
    parser.add_argument("--html", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--chromium", default=None)
    parser.add_argument("--timeout", type=int, default=180)
    args = parser.parse_args(argv)

    result = export_pdf(args.html, args.out, args.chromium, args.timeout)
    print(
        json.dumps(
            {
                "pdf": str(result.pdf) if result.pdf else None,
                "pages": result.pages,
                "skipped": result.skipped,
                "reason": result.reason,
            },
            indent=2,
        )
    )
    if result.skipped:
        print(f"SKIP: {result.reason}", file=sys.stderr)
        return 6
    return 0
