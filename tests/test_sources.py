import pytest

from p2c.sources import Source, SourceError, parse_research_sources, sources_html_by_topic

RESEARCH_FILE = """---
topic: tlb
unverified: false
---

## Notes

The TLB caches virtual-to-physical mappings.

## Sources
- Operating Systems: Three Easy Pieces: https://pages.cs.wisc.edu/~remzi/OSTEP/
- Intel SDM Vol 3A: https://intel.com/sdm
"""


def test_parses_a_valid_sources_section():
    sources = parse_research_sources(RESEARCH_FILE)
    assert sources == [
        Source("Operating Systems: Three Easy Pieces", "https://pages.cs.wisc.edu/~remzi/OSTEP/"),
        Source("Intel SDM Vol 3A", "https://intel.com/sdm"),
    ]


def test_returns_empty_list_when_no_sources_heading():
    assert parse_research_sources("---\ntopic: x\n---\n\n## Notes\nJust prose.\n") == []


def test_rejects_a_line_missing_a_colon():
    with pytest.raises(SourceError, match="expected 'Title: url'"):
        parse_research_sources("## Sources\n- not a valid line\n")


def test_rejects_a_non_http_url():
    with pytest.raises(SourceError, match="must start with http"):
        parse_research_sources("## Sources\n- Some Title: ftp://example.com/x\n")


def test_stops_reading_sources_at_the_next_heading():
    text = "## Sources\n- A: https://a.example\n\n## Something Else\n- B: https://b.example\n"
    assert parse_research_sources(text) == [Source("A", "https://a.example")]


def test_sources_html_escapes_content():
    html_out = sources_html_by_topic(
        {"tlb": [Source("A < B", "https://a.example?x=1&y=2")]},
        {"tlb": "The TLB"},
    )
    assert "&lt; B" in html_out
    assert "&amp;y=2" in html_out
    assert "https://a.example?x=1&amp;y=2" in html_out


def test_sources_html_groups_by_topic_with_a_heading():
    html_out = sources_html_by_topic(
        {"tlb": [Source("A", "https://a.example")], "sched": [Source("B", "https://b.example")]},
        {"tlb": "The TLB", "sched": "Scheduling"},
    )
    assert '<h3>The TLB</h3>' in html_out
    assert '<h3>Scheduling</h3>' in html_out
    assert html_out.index("The TLB") < html_out.index("Scheduling")


def test_sources_html_skips_topics_with_no_sources():
    html_out = sources_html_by_topic({"tlb": []}, {"tlb": "The TLB"})
    assert html_out == ""


def test_sources_html_empty_dict_returns_empty_string():
    assert sources_html_by_topic({}, {}) == ""
