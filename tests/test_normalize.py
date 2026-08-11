import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from fixtures.make_fixtures import make_pdf, make_pptx
from p2c.normalize import (
    BadDeck,
    NormalizeResult,
    SofficeMissing,
    collect_inputs,
    normalize,
    pdf_page_count,
)

FIXTURES = Path(__file__).parent / "fixtures"
REPO = Path(__file__).resolve().parents[1]


def test_page_count_of_fixture():
    assert pdf_page_count((FIXTURES / "terse.pdf").read_bytes()) == 3


def test_page_count_of_single_page():
    assert pdf_page_count(make_pdf([["only"]])) == 1


def test_page_count_rejects_non_pdf():
    with pytest.raises(BadDeck, match="not a PDF"):
        pdf_page_count(b"PK\x03\x04 this is a zip")


def test_page_count_rejects_zero_pages():
    with pytest.raises(BadDeck, match="zero pages"):
        pdf_page_count(make_pdf([]))


def test_page_count_rejects_zero_pages_with_a_spoofed_trailing_count():
    # A zero-page PDF with an unrelated "/Count 5" appended after the real
    # %%EOF marker must still be rejected -- a blind max()-over-every-/Count
    # scan would otherwise be fooled into reporting 5 pages.
    spoofed = make_pdf([]) + b"\n/Count 5\n"
    with pytest.raises(BadDeck, match="zero pages"):
        pdf_page_count(spoofed)


def test_collect_inputs_expands_a_directory_sorted(tmp_path):
    (tmp_path / "b.pdf").write_bytes(make_pdf([["b"]]))
    (tmp_path / "a.pdf").write_bytes(make_pdf([["a"]]))
    (tmp_path / "notes.txt").write_text("ignored")
    assert [p.name for p in collect_inputs([tmp_path])] == ["a.pdf", "b.pdf"]


def test_collect_inputs_rejects_a_directory_with_no_decks(tmp_path):
    with pytest.raises(BadDeck, match="no PDF, PPTX, or DOCX"):
        collect_inputs([tmp_path])


def test_collect_inputs_rejects_an_unsupported_file(tmp_path):
    odd = tmp_path / "deck.key"
    odd.write_text("nope")
    with pytest.raises(BadDeck, match="unsupported"):
        collect_inputs([odd])


def test_normalize_copies_pdfs_and_reports_pages(tmp_path):
    out = tmp_path / "normalized"
    result = normalize([FIXTURES / "terse.pdf"], out, soffice=None)
    assert isinstance(result, NormalizeResult)
    assert [p.name for p in result.pdfs] == ["terse.pdf"]
    assert result.converted == []
    assert result.pages == {"terse.pdf": 3}
    assert (out / "terse.pdf").read_bytes() == (FIXTURES / "terse.pdf").read_bytes()


def test_normalize_dedupes_colliding_stems(tmp_path):
    one = tmp_path / "a"
    two = tmp_path / "b"
    for d in (one, two):
        d.mkdir()
        (d / "week1.pdf").write_bytes(make_pdf([["x"]]))
    result = normalize([one / "week1.pdf", two / "week1.pdf"], tmp_path / "out", None)
    assert [p.name for p in result.pdfs] == ["week1.pdf", "week1-2.pdf"]


_FAKE_SOFFICE = '''#!/usr/bin/env python3
"""Stand-in for `soffice --headless --convert-to pdf --outdir DIR SRC`.

Mimics LibreOffice's naming (always "<stem>.pdf" in --outdir) but derives its
one-page content from a hash of the source file's bytes, so two different
source decks sharing a stem produce distinguishable output -- this is what
lets the test prove a same-stemmed second conversion didn't clobber the
first's already-placed output.
"""
import hashlib
import sys
from pathlib import Path


def _build_pdf(marker: str) -> bytes:
    objs = [
        "<< /Type /Catalog /Pages 2 0 R >>",
        "<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 200 200] "
        "/Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
        "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    body = f"BT /F1 12 Tf 10 100 Td ({marker}) Tj ET"
    objs.append(f"<< /Length {len(body)} >>\\nstream\\n{body}\\nendstream")
    out = bytearray(b"%PDF-1.4\\n")
    offsets = []
    for n, obj in enumerate(objs, start=1):
        offsets.append(len(out))
        out += f"{n} 0 obj\\n{obj}\\nendobj\\n".encode("latin-1")
    xref = len(out)
    out += f"xref\\n0 {len(objs) + 1}\\n".encode()
    out += b"0000000000 65535 f \\n"
    for off in offsets:
        out += f"{off:010d} 00000 n \\n".encode()
    out += (
        f"trailer\\n<< /Size {len(objs) + 1} /Root 1 0 R >>\\n"
        f"startxref\\n{xref}\\n%%EOF\\n"
    ).encode()
    return bytes(out)


args = sys.argv[1:]
outdir = Path(args[args.index("--outdir") + 1])
src = Path(args[-1])
marker = hashlib.sha256(src.read_bytes()).hexdigest()[:12]
(outdir / f"{src.stem}.pdf").write_bytes(_build_pdf(marker))
'''


def test_normalize_dedupes_colliding_pptx_stems_without_clobbering(tmp_path):
    fake_soffice = tmp_path / "fake_soffice.py"
    fake_soffice.write_text(_FAKE_SOFFICE)
    fake_soffice.chmod(0o755)

    one, two = tmp_path / "a", tmp_path / "b"
    for d, lines in ((one, ["alpha"]), (two, ["beta", "gamma"])):
        d.mkdir()
        (d / "week1.pptx").write_bytes(make_pptx(lines))

    out = tmp_path / "out"
    result = normalize([one / "week1.pptx", two / "week1.pptx"], out, str(fake_soffice))

    assert [p.name for p in result.pdfs] == ["week1.pdf", "week1-2.pdf"]
    assert [p.name for p in result.converted] == ["week1.pdf", "week1-2.pdf"]
    first = (out / "week1.pdf").read_bytes()
    second = (out / "week1-2.pdf").read_bytes()
    assert first != second
    assert pdf_page_count(first) == 1
    assert pdf_page_count(second) == 1


def test_normalize_converts_docx_via_soffice(tmp_path):
    fake_soffice = tmp_path / "fake_soffice.py"
    fake_soffice.write_text(_FAKE_SOFFICE)
    fake_soffice.chmod(0o755)
    src_dir = tmp_path / "src"
    src_dir.mkdir()
    (src_dir / "essay.docx").write_bytes(b"not a real docx, soffice is faked")
    out = tmp_path / "out"
    result = normalize([src_dir / "essay.docx"], out, str(fake_soffice))
    assert [p.name for p in result.pdfs] == ["essay.pdf"]
    assert [p.name for p in result.converted] == ["essay.pdf"]
    assert result.pages == {"essay.pdf": 1}


def test_normalize_hard_fails_on_docx_without_soffice(tmp_path):
    (tmp_path / "essay.docx").write_bytes(b"not a real docx")
    with pytest.raises(SofficeMissing):
        normalize([tmp_path / "essay.docx"], tmp_path / "out", soffice=None)


def test_collect_inputs_error_message_lists_all_supported_formats(tmp_path):
    odd = tmp_path / "deck.key"
    odd.write_text("nope")
    with pytest.raises(BadDeck, match=r"PDF, PPTX, or DOCX"):
        collect_inputs([odd])


def test_normalize_hard_fails_on_pptx_without_soffice(tmp_path):
    with pytest.raises(SofficeMissing) as exc:
        normalize([FIXTURES / "terse.pptx"], tmp_path / "out", soffice=None)
    assert exc.value.exit_code == 4
    assert "libreoffice" in str(exc.value).lower()


def test_normalize_rejects_a_corrupt_pdf(tmp_path):
    bad = tmp_path / "broken.pdf"
    bad.write_bytes(b"not really a pdf")
    with pytest.raises(BadDeck, match="broken.pdf"):
        normalize([bad], tmp_path / "out", None)


def _run_cli(*args):
    return subprocess.run(
        [sys.executable, str(REPO / "scripts" / "normalize"), *map(str, args)],
        capture_output=True,
        text=True,
    )


def test_cli_succeeds_on_pdf_and_prints_json(tmp_path):
    proc = _run_cli(FIXTURES / "terse.pdf", "--out", tmp_path / "out")
    assert proc.returncode == 0, proc.stderr
    report = json.loads(proc.stdout)
    assert report["pages"] == {"terse.pdf": 3}
    assert report["converted"] == []


def test_cli_exit_4_on_pptx_without_soffice(tmp_path, monkeypatch):
    proc = subprocess.run(
        [
            sys.executable,
            str(REPO / "scripts" / "normalize"),
            str(FIXTURES / "terse.pptx"),
            "--out",
            str(tmp_path / "out"),
            "--soffice",
            "definitely-not-installed-soffice",
        ],
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 4
    assert "apt install libreoffice" in proc.stderr


def test_cli_exit_5_on_corrupt_deck(tmp_path):
    bad = tmp_path / "broken.pdf"
    bad.write_bytes(b"garbage")
    proc = _run_cli(bad, "--out", tmp_path / "out")
    assert proc.returncode == 5


def test_cli_exit_2_without_arguments():
    assert _run_cli().returncode == 2


@pytest.mark.skipif(shutil.which("soffice") is None, reason="LibreOffice not installed")
def test_pptx_converts_when_soffice_is_present(tmp_path):
    result = normalize([FIXTURES / "terse.pptx"], tmp_path / "out", shutil.which("soffice"))
    assert [p.name for p in result.converted] == ["terse.pdf"]
    assert result.pages["terse.pdf"] >= 1
