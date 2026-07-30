import pytest

from p2c.blocks import restore
from p2c.glossary import (
    GlossaryError,
    TermInjector,
    glossary_html,
    merge_glossaries,
    parse_glossary_block,
    term_ids,
)

BLOCK = """TLB: A small cache holding recently used virtual-to-physical mappings.
Page table: The full in-memory map from virtual pages to physical frames.
Thrashing: When the working set exceeds physical memory, so the system spends
    most of its time paging rather than computing.
"""


def test_parses_terms_and_wrapped_definitions():
    terms = parse_glossary_block(BLOCK)
    assert list(terms) == ["TLB", "Page table", "Thrashing"]
    assert terms["TLB"].startswith("A small cache")
    assert terms["Thrashing"].endswith("rather than computing.")
    assert "\n" not in terms["Thrashing"]


@pytest.mark.parametrize(
    "body,message",
    [
        ("no colon here\n", "expected 'term: definition'"),
        (": missing term\n", "term is empty"),
        ("TLB:\n", "definition for 'TLB' is empty"),
        ("    orphan continuation\n", "continuation line before any term"),
        ("TLB: a\nTLB: b\n", "duplicate term 'TLB'"),
        ("", "glossary block is empty"),
    ],
)
def test_rejects_malformed_glossary_blocks(body, message):
    with pytest.raises(GlossaryError, match=message):
        parse_glossary_block(body)


def test_merge_is_case_insensitive_and_first_wins():
    merged = merge_glossaries([{"TLB": "first"}, {"tlb": "second"}, {"MESI": "third"}])
    assert merged == {"TLB": "first", "MESI": "third"}


def test_term_ids_are_slugged_and_keyed_lowercase():
    ids = term_ids({"Page table": "x", "TLB": "y"})
    assert ids == {"page table": "def-page-table", "tlb": "def-tlb"}


def test_term_ids_stay_distinct_when_slugs_collide():
    # Non-Latin terms both ASCII-fold to "" and fall back to slugify's default
    # ("section"); term_ids must still hand out unique ids, the same way
    # AnchorAllocator already does for heading anchors.
    ids = term_ids({"טבלת עמודים": "x", "קבוצת עבודה": "y"})
    assert ids == {
        "טבלת עמודים": "def-section",
        "קבוצת עבודה": "def-section-2",
    }
    assert len(set(ids.values())) == len(ids)


def test_glossary_html_is_a_sorted_escaped_definition_list():
    terms = {"TLB": "Caches <mappings>", "Page table": "The map & nothing else"}
    out = glossary_html(terms, term_ids(terms))
    assert out.index("Page table") < out.index("TLB")
    assert '<dl class="glossary">' in out
    assert '<dt id="def-tlb">TLB</dt>' in out
    assert "Caches &lt;mappings&gt;" in out
    assert "The map &amp; nothing else" in out


TERMS = {"TLB": "Caches mappings.", "Page table": "The full map.",
         "Page table walk": "Following the map level by level."}
IDS = term_ids(TERMS)


def test_injects_only_the_first_occurrence_of_each_term():
    inj = TermInjector(TERMS, IDS)
    out = inj.inject("The TLB is fast. The TLB is small.")
    assert out.count("P2CTERM") == 1
    html_out = restore(out, inj.replacements)
    assert html_out.count('class="term"') == 1
    assert "The TLB is small." in html_out


def test_prefers_the_longest_matching_term():
    inj = TermInjector(TERMS, IDS)
    html_out = restore(inj.inject("A page table walk is slow."), inj.replacements)
    assert 'aria-controls="def-page-table-walk"' in html_out
    assert 'aria-controls="def-page-table"' not in html_out


def test_keeps_the_authors_casing_but_matches_insensitively():
    inj = TermInjector(TERMS, IDS)
    html_out = restore(inj.inject("The tlb is fast."), inj.replacements)
    assert ">tlb</button>" in html_out
    assert 'aria-controls="def-tlb"' in html_out


def test_skips_headings_and_topic_markers():
    inj = TermInjector(TERMS, IDS)
    md = "<!-- topic: tlb -->\n### The TLB\n\nThe TLB is fast.\n"
    out = inj.inject(md)
    assert "### The TLB" in out
    assert "<!-- topic: tlb -->" in out
    assert out.count("P2CTERM") == 1


def test_does_not_match_inside_extraction_tokens():
    inj = TermInjector({"block": "a unit", "code": "instructions"}, term_ids({"block": "", "code": ""}))
    out = inj.inject("P2CBLOCK0ENDBLOCK P2CCODE1ENDCODE")
    assert out == "P2CBLOCK0ENDBLOCK P2CCODE1ENDCODE"


def test_each_call_gets_a_fresh_first_occurrence_but_unique_tokens():
    inj = TermInjector(TERMS, IDS)
    first = inj.inject("The TLB is fast.")
    second = inj.inject("The TLB is small.")
    assert first != second
    assert len(inj.replacements) == 2
