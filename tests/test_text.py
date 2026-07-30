import pytest

from p2c.text import AnchorAllocator, slugify


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("Virtual Memory", "virtual-memory"),
        ("  Leading and trailing  ", "leading-and-trailing"),
        ("TLB: what it caches", "tlb-what-it-caches"),
        ("C++ / Rust", "c-rust"),
        ("Page-table walk", "page-table-walk"),
        ("Réplication", "replication"),
        ("", "section"),
        ("!!!", "section"),
        ("42", "42"),
    ],
)
def test_slugify(raw, expected):
    assert slugify(raw) == expected


def test_anchor_allocator_dedupes():
    a = AnchorAllocator()
    assert a.take("Caching") == "caching"
    assert a.take("Caching") == "caching-2"
    assert a.take("Caching") == "caching-3"
    assert a.take("Other") == "other"


def test_anchor_allocator_instances_are_independent():
    assert AnchorAllocator().take("Caching") == "caching"
    assert AnchorAllocator().take("Caching") == "caching"
