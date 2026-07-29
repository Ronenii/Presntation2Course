"""Phase 0: everything becomes a PDF, or the run stops.

Text extraction is deliberately not a fallback. The architecture diagram is usually
the most valuable thing on a slide, and extraction silently discards it.
"""

import json
import re
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

SUPPORTED = {".pdf", ".pptx"}
INSTALL_HINT = (
    "PPTX input requires LibreOffice. Install it and re-run:\n"
    "  sudo apt install libreoffice        # Debian/Ubuntu\n"
    "  brew install --cask libreoffice     # macOS"
)


class NormalizeError(Exception):
    exit_code = 1


class SofficeMissing(NormalizeError):
    exit_code = 4


class BadDeck(NormalizeError):
    exit_code = 5


@dataclass
class NormalizeResult:
    pdfs: list[Path] = field(default_factory=list)
    converted: list[Path] = field(default_factory=list)
    pages: dict[str, int] = field(default_factory=dict)


def pdf_page_count(data: bytes) -> int:
    """Page count from /Count, falling back to counting /Type /Page objects."""
    if not data.startswith(b"%PDF-"):
        raise BadDeck("not a PDF (missing %PDF- header)")
    counts = [int(m.group(1)) for m in re.finditer(rb"/Count\s+(\d+)", data)]
    n = max(counts) if counts else len(re.findall(rb"/Type\s*/Page\b", data))
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
                raise BadDeck(f"{path}: no PDF or PPTX files found")
            found.extend(decks)
        elif path.is_file():
            if path.suffix.lower() not in SUPPORTED:
                raise BadDeck(f"{path}: unsupported input (expected .pdf or .pptx)")
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


def _convert_pptx(src: Path, out_dir: Path, soffice: str) -> Path:
    proc = subprocess.run(
        [soffice, "--headless", "--convert-to", "pdf", "--outdir", str(out_dir), str(src)],
        capture_output=True,
        text=True,
        timeout=300,
    )
    produced = out_dir / f"{src.stem}.pdf"
    if proc.returncode != 0 or not produced.exists():
        raise BadDeck(f"{src}: LibreOffice conversion failed\n{proc.stdout}\n{proc.stderr}")
    return produced


def normalize(
    inputs: list[Path], out_dir: Path, soffice: str | None
) -> NormalizeResult:
    decks = collect_inputs([Path(p) for p in inputs])
    if any(d.suffix.lower() == ".pptx" for d in decks) and (
        soffice is None or shutil.which(soffice) is None
    ):
        raise SofficeMissing(INSTALL_HINT)

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
        else:
            produced = _convert_pptx(deck, out_dir, soffice)  # type: ignore[arg-type]
            if produced != target:
                produced.replace(target)
            pages = pdf_page_count(target.read_bytes())
            result.converted.append(target)
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
