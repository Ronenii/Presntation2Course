"""Phase 0: everything becomes a PDF, or the run stops.

Text extraction is deliberately not a fallback. The architecture diagram is usually
the most valuable thing on a slide, and extraction silently discards it.
"""

import json
import os
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

import markdown

SUPPORTED = {".pdf", ".pptx", ".docx", ".txt", ".md"}
INSTALL_HINT = (
    "PPTX input requires LibreOffice. Install it and re-run:\n"
    "  sudo apt install libreoffice        # Debian/Ubuntu\n"
    "  brew install --cask libreoffice     # macOS"
)
CHROMIUM_INSTALL_HINT = (
    "TXT/MD input requires headless Chromium to render page images. Install it "
    "and re-run:\n"
    "  sudo apt install chromium         # Debian/Ubuntu\n"
    "  brew install --cask chromium      # macOS"
)

CHROMIUM_CANDIDATES = (
    "chromium",
    "chromium-browser",
    "google-chrome",
    "google-chrome-stable",
    "chrome",
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Chromium.app/Contents/MacOS/Chromium",
)


def find_chromium(explicit: str | None = None) -> str | None:
    """An explicitly requested browser is honoured or refused, never substituted."""
    requested = explicit or os.environ.get("P2C_CHROMIUM")
    if requested:
        if Path(requested).is_file() or shutil.which(requested):
            return requested
        return None
    for candidate in CHROMIUM_CANDIDATES:
        if Path(candidate).is_file():
            return candidate
        found = shutil.which(candidate)
        if found:
            return found
    return None


class NormalizeError(Exception):
    exit_code = 1


class SofficeMissing(NormalizeError):
    exit_code = 4


class BadDeck(NormalizeError):
    exit_code = 5


class ChromiumMissing(NormalizeError):
    exit_code = 7


@dataclass
class NormalizeResult:
    pdfs: list[Path] = field(default_factory=list)
    converted: list[Path] = field(default_factory=list)
    pages: dict[str, int] = field(default_factory=dict)


def pdf_page_count(data: bytes) -> int:
    """Page count from /Type /Page leaves, falling back to the /Pages dict's /Count.

    Neither signal is trusted blindly. A blind ``max()`` over every "/Count"
    match anywhere in the byte stream can be fooled by a stray leftover value
    from an incremental-save artifact, or by adversarial/corrupt bytes tacked
    onto the file -- that would wrongly report a nonzero page count for a
    deck that is actually empty or broken. So:

    1. Count real page leaf objects ("/Type /Page", never "/Type /Pages" --
       the trailing "s" breaks the regex's word boundary). Each one
       corresponds 1:1 to an actual page, so this is the primary signal and
       wins whenever it's nonzero.
    2. Only when no leaf objects are found (e.g. pages live inside a
       compressed object stream this regex-only reader can't see into) fall
       back to the specific /Type /Pages dictionary's own /Count field --
       scanned in a bounded window right after that dictionary's /Type match,
       not anywhere in the file.
    3. Anything appended after the final "%%EOF" marker is ignored outright,
       so trailing garbage can't spoof either signal.
    """
    if not data.startswith(b"%PDF-"):
        raise BadDeck("not a PDF (missing %PDF- header)")

    eof = data.rfind(b"%%EOF")
    body = data[: eof + len(b"%%EOF")] if eof != -1 else data

    n = len(re.findall(rb"/Type\s*/Page\b", body))
    if not n:
        pages_obj = re.search(rb"/Type\s*/Pages\b", body)
        if pages_obj:
            window = body[pages_obj.start() : pages_obj.start() + 500]
            count_match = re.search(rb"/Count\s+(\d+)", window)
            if count_match:
                n = int(count_match.group(1))

    if n < 1:
        raise BadDeck("PDF reports zero pages")
    return n


def collect_inputs(paths: list[Path]) -> list[Path]:
    """Expand directories to their decks; validate extensions. Sorted, stable."""
    found: list[Path] = []
    for path in paths:
        if path.is_dir():
            decks = sorted(
                p for p in path.rglob("*") if p.suffix.lower() in SUPPORTED and p.is_file()
            )
            if not decks:
                raise BadDeck(f"{path}: no PDF, PPTX, DOCX, TXT, or MD files found")
            found.extend(decks)
        elif path.is_file():
            if path.suffix.lower() not in SUPPORTED:
                raise BadDeck(f"{path}: unsupported input (expected PDF, PPTX, DOCX, TXT, or MD)")
            found.append(path)
        else:
            raise BadDeck(f"{path}: no such file or directory")
    if not found:
        raise BadDeck("no inputs given")
    return found


def _unique(out_dir: Path, stem: str, taken: set[str]) -> Path:
    name, n = f"{stem}.pdf", 1
    while name in taken:
        n += 1
        name = f"{stem}-{n}.pdf"
    taken.add(name)
    return out_dir / name


def _convert_office_doc(src: Path, out_dir: Path, soffice: str, target: Path) -> Path:
    """Convert src (.pptx or .docx) to PDF in a private scratch dir, then place it
    at target.

    LibreOffice always names its output "<stem>.pdf" and has no notion of
    normalize()'s stem-collision dedup. Converting straight into the shared
    out_dir would let a second same-stemmed source's conversion silently
    clobber the first's output on disk before it's ever moved to its
    (distinct) deduplicated target name. A private temp directory per
    conversion makes that collision impossible regardless of ordering.
    """
    with tempfile.TemporaryDirectory(dir=out_dir) as scratch:
        proc = subprocess.run(
            [soffice, "--headless", "--convert-to", "pdf", "--outdir", scratch, str(src)],
            capture_output=True,
            text=True,
            timeout=300,
        )
        produced = Path(scratch) / f"{src.stem}.pdf"
        if proc.returncode != 0 or not produced.exists():
            raise BadDeck(f"{src}: LibreOffice conversion failed\n{proc.stdout}\n{proc.stderr}")
        produced.replace(target)
    return target


_TEXT_SOURCE_TEMPLATE = """<!doctype html>
<html><head><meta charset="utf-8">
<style>
  body {{ font-family: serif; font-size: 14px; line-height: 1.5;
          max-width: 40rem; margin: 2rem auto; }}
  h1, h2, h3 {{ font-family: sans-serif; }}
</style>
</head><body>
{body}
</body></html>
"""

# Plain "extra"/"sane_lists" only -- the same extension list p2c.mdrender._md()
# uses, but this is never routed through mdrender._md() or
# p2c.blocks.extract_fences() itself. Those two understand P2C's own
# quiz/glossary/animate fence grammar; a generic external article is not
# course-authored content and must not be interpreted through that lens.
_TEXT_SOURCE_MD_EXTENSIONS = ["extra", "sane_lists"]


def _render_text_source_to_pdf(src: Path, chromium: str, target: Path) -> Path:
    """Render a .txt/.md file to a one-shot standalone HTML page, then print
    that to PDF via headless Chromium -- the same print-to-pdf mechanism
    p2c.exportpdf uses for course output, reused here via find_chromium
    (see module-level docstring for why this lives in normalize.py, not
    exportpdf.py)."""
    text = src.read_text(encoding="utf-8")
    if src.suffix.lower() == ".md":
        body_html = markdown.Markdown(extensions=_TEXT_SOURCE_MD_EXTENSIONS).convert(text)
    else:
        import html as _html
        body_html = f"<pre>{_html.escape(text)}</pre>"
    page_html = _TEXT_SOURCE_TEMPLATE.format(body=body_html)

    with tempfile.TemporaryDirectory() as scratch:
        html_path = Path(scratch) / f"{src.stem}.html"
        html_path.write_text(page_html, encoding="utf-8")
        with tempfile.TemporaryDirectory() as profile:
            command = [
                chromium,
                "--headless=new",
                "--disable-gpu",
                "--no-sandbox",
                "--no-first-run",
                "--no-pdf-header-footer",
                f"--user-data-dir={profile}",
                "--virtual-time-budget=20000",
                f"--print-to-pdf={target}",
                html_path.resolve().as_uri(),
            ]
            proc = subprocess.run(command, capture_output=True, text=True, timeout=180)
        if proc.returncode != 0 or not target.exists():
            raise BadDeck(
                f"{src}: Chromium print-to-pdf failed\n{proc.stdout}\n{proc.stderr}"
            )
    return target


def normalize(
    inputs: list[Path], out_dir: Path, soffice: str | None
) -> NormalizeResult:
    decks = collect_inputs([Path(p) for p in inputs])
    if any(d.suffix.lower() in (".pptx", ".docx") for d in decks) and (
        soffice is None or shutil.which(soffice) is None
    ):
        raise SofficeMissing(INSTALL_HINT)
    chromium_bin = find_chromium()

    out_dir.mkdir(parents=True, exist_ok=True)
    result = NormalizeResult()
    taken: set[str] = set()
    for deck in decks:
        target = _unique(out_dir, deck.stem, taken)
        if deck.suffix.lower() == ".pdf":
            data = deck.read_bytes()
            try:
                pages = pdf_page_count(data)
            except BadDeck as exc:
                raise BadDeck(f"{deck}: {exc}") from exc
            target.write_bytes(data)
        elif deck.suffix.lower() in (".pptx", ".docx"):
            produced = _convert_office_doc(deck, out_dir, soffice, target)  # type: ignore[arg-type]
            pages = pdf_page_count(produced.read_bytes())
            result.converted.append(produced)
        elif deck.suffix.lower() in (".txt", ".md"):
            if chromium_bin is None:
                raise ChromiumMissing(CHROMIUM_INSTALL_HINT)
            produced = _render_text_source_to_pdf(deck, chromium_bin, target)
            pages = pdf_page_count(produced.read_bytes())
            result.converted.append(produced)
        else:
            raise BadDeck(f"{deck}: unsupported input (expected PDF, PPTX, or DOCX, TXT, or MD)")
        result.pdfs.append(target)
        result.pages[target.name] = pages
    return result


def main(argv: list[str]) -> int:
    import argparse

    parser = argparse.ArgumentParser(
        prog="normalize", description="Normalize decks to PDFs for visual reading."
    )
    parser.add_argument("inputs", nargs="+", type=Path)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--soffice", default="soffice")
    args = parser.parse_args(argv)

    result = normalize(args.inputs, args.out, args.soffice)
    print(
        json.dumps(
            {
                "pdfs": [str(p) for p in result.pdfs],
                "converted": [str(p) for p in result.converted],
                "pages": result.pages,
                "total_pages": sum(result.pages.values()),
            },
            indent=2,
        )
    )
    return 0
