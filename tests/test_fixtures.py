import re
import zipfile
from pathlib import Path

from fixtures.make_fixtures import make_pdf, make_pptx

FIXTURES = Path(__file__).parent / "fixtures"


def test_committed_pdf_is_a_three_page_pdf():
    data = (FIXTURES / "terse.pdf").read_bytes()
    assert data.startswith(b"%PDF-")
    assert data.rstrip().endswith(b"%%EOF")
    assert re.search(rb"/Count\s+3", data)
    assert b"Virtual memory" in data


def test_committed_pptx_is_a_valid_zip_with_presentation_parts():
    with zipfile.ZipFile(FIXTURES / "terse.pptx") as zf:
        names = set(zf.namelist())
        assert zf.testzip() is None
    assert "[Content_Types].xml" in names
    assert "ppt/presentation.xml" in names
    assert "ppt/slides/slide1.xml" in names


def test_make_pdf_honours_page_count():
    assert re.search(rb"/Count\s+1", make_pdf([["one"]]))
    assert re.search(rb"/Count\s+5", make_pdf([["x"]] * 5))


def test_make_pptx_is_deterministic():
    assert make_pptx(["a", "b"]) == make_pptx(["a", "b"])
