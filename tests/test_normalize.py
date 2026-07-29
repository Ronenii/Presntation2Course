import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from fixtures.make_fixtures import make_pdf
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


def test_collect_inputs_expands_a_directory_sorted(tmp_path):
    (tmp_path / "b.pdf").write_bytes(make_pdf([["b"]]))
    (tmp_path / "a.pdf").write_bytes(make_pdf([["a"]]))
    (tmp_path / "notes.txt").write_text("ignored")
    assert [p.name for p in collect_inputs([tmp_path])] == ["a.pdf", "b.pdf"]


def test_collect_inputs_rejects_a_directory_with_no_decks(tmp_path):
    with pytest.raises(BadDeck, match="no PDF or PPTX"):
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
