from pathlib import Path

import pytest

from p2c.imagery import ImageryError, extract_page_png

FIXTURES = Path(__file__).parent / "fixtures"
TERSE = FIXTURES / "terse.pdf"


def test_extracts_a_valid_page_as_png_bytes():
    png = extract_page_png(TERSE, 1)
    assert png.startswith(b"\x89PNG\r\n\x1a\n")


def test_extracts_a_later_page_too():
    png = extract_page_png(TERSE, 3)
    assert png.startswith(b"\x89PNG\r\n\x1a\n")


def test_rejects_an_out_of_range_page():
    with pytest.raises(ImageryError, match=r"page 5 out of range \(1-3\)"):
        extract_page_png(TERSE, 5)


def test_rejects_page_zero():
    with pytest.raises(ImageryError, match=r"out of range"):
        extract_page_png(TERSE, 0)


def test_rejects_a_missing_file(tmp_path):
    with pytest.raises(ImageryError, match="no such file"):
        extract_page_png(tmp_path / "missing.pdf", 1)


def test_rejects_a_corrupt_pdf(tmp_path):
    bad = tmp_path / "broken.pdf"
    bad.write_bytes(b"not really a pdf")
    with pytest.raises(ImageryError, match="not a readable PDF"):
        extract_page_png(bad, 1)


def test_higher_dpi_produces_a_larger_image():
    small = extract_page_png(TERSE, 1, dpi=72)
    large = extract_page_png(TERSE, 1, dpi=200)
    assert len(large) > len(small)
