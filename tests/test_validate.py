import pytest

from p2c.mdrender import is_linear_mermaid, render_course
from p2c.validate import (
    ROUTE_FOR_CODE,
    Finding,
    anchor_to_module,
    blocking,
    findings_to_json,
    validate_course,
)

OUTLINE = {
    "title": "Operating Systems",
    "subject_domain": "systems",
    "source_decks": ["week1.pdf"],
    "modules": [
        {
            "id": "m-memory",
            "title": "Virtual Memory",
            "prerequisites": [],
            "topics": [
                {"id": "tlb", "title": "The TLB", "slide_refs": ["week1.pdf#1"],
                 "jargon": ["TLB"], "diagrams": [], "gaps": []},
                {"id": "thrashing", "title": "Thrashing", "slide_refs": ["week1.pdf#2"],
                 "jargon": [], "diagrams": [], "gaps": []},
            ],
        }
    ],
}

HEAD = """---
title: Operating Systems
subject_domain: systems
theme: slate
source_decks:
  - week1.pdf
---

# Operating Systems

## Virtual Memory
"""

GOOD_QUIZ = """```quiz
q: What does a TLB cache?
- [ ] Page contents
- [x] Virtual-to-physical mappings
- [ ] The page table
why: It caches translations, not data.
```"""


def course(*, tlb_body=None, thrashing_body=None, glossary="TLB: A cache of mappings."):
    tlb = tlb_body if tlb_body is not None else (
        "The TLB is fast.\n\n"
        "<!-- no-visual: test fixture prose, nothing spatial to draw -->\n\n"
        f"{GOOD_QUIZ}"
    )
    thrash = thrashing_body if thrashing_body is not None else (
        "Paging dominates.\n\n"
        "<!-- no-visual: test fixture prose, nothing spatial to draw -->\n\n"
        f"{GOOD_QUIZ}"
    )
    parts = [HEAD, "\n<!-- topic: tlb -->\n### The TLB\n\n", tlb, "\n"]
    if thrashing_body != "":
        parts += ["\n<!-- topic: thrashing -->\n### Thrashing\n\n", thrash, "\n"]
    if glossary:
        parts += ["\n```glossary\n", glossary, "\n```\n"]
    return "".join(parts)


def check(course_md, html_text="<html><body>ok</body></html>", outline=OUTLINE):
    return validate_course(render_course(course_md), outline, html_text)


def codes(findings):
    return sorted(f.code for f in findings)


def test_a_clean_course_produces_no_findings():
    assert check(course()) == []


def test_every_code_has_a_route():
    for code in ROUTE_FOR_CODE:
        assert ROUTE_FOR_CODE[code] in {"writer", "researcher", "summarizer", "build"}


def test_anchor_to_module_attributes_topics_to_their_module():
    rendered = render_course(course())
    mapping = anchor_to_module(rendered, OUTLINE)
    assert mapping["virtual-memory"] == "m-memory"
    assert mapping["the-tlb"] == "m-memory"
    assert mapping["thrashing"] == "m-memory"


def test_a_malformed_quiz_is_blocking_and_routes_to_the_writer():
    bad = "The TLB is fast.\n\n```quiz\nq: two only\n- [x] a\n- [ ] b\nwhy: w\n```"
    findings = check(course(tlb_body=bad))
    quiz = [f for f in findings if f.code == "quiz_malformed"]
    assert len(quiz) == 1
    assert quiz[0].blocking is True
    assert quiz[0].route == "writer"
    assert quiz[0].module == "m-memory"
    # The topic also loses its only quiz, so that is reported too.
    assert "topic_without_quiz" in codes(findings)


def test_a_topic_with_no_quiz_is_blocking_and_names_the_topic():
    findings = check(course(tlb_body="The TLB is fast, with no check at all."))
    missing = [f for f in findings if f.code == "topic_without_quiz"]
    assert len(missing) == 1
    assert missing[0].topic == "tlb"
    assert missing[0].module == "m-memory"
    assert missing[0].blocking is True


def test_a_no_quiz_comment_suppresses_topic_without_quiz():
    body = "Plain prose only.\n\n<!-- no-quiz: brief administrative topic, nothing to check -->"
    findings = check(course(tlb_body=body))
    assert "topic_without_quiz" not in codes(findings)


def test_a_topic_with_no_visual_and_no_justification_is_blocking():
    findings = check(course(tlb_body="The TLB is fast, with nothing spatial about it drawn."))
    missing = [f for f in findings if f.code == "topic_without_visual"]
    assert len(missing) == 1
    assert missing[0].topic == "tlb"
    assert missing[0].module == "m-memory"
    assert missing[0].blocking is True
    assert missing[0].route == "writer"


def test_a_figure_block_counts_as_a_visual_for_the_coverage_check():
    body = "The TLB is fast.\n\n```figure\nsource: week1.pdf#1\ncaption: c\n```\n\n" + GOOD_QUIZ
    findings = check(course(tlb_body=body))
    assert "topic_without_visual" not in codes(findings)


def test_a_missing_topic_routes_to_the_summarizer():
    findings = check(course(thrashing_body=""))
    missing = [f for f in findings if f.code == "topic_missing"]
    assert [f.topic for f in missing] == ["thrashing"]
    assert missing[0].route == "summarizer"
    assert missing[0].blocking is True


def test_an_unknown_topic_in_the_course_is_noted_not_blocking():
    extra = course() + "\n<!-- topic: invented -->\n### Invented\n\nText.\n"
    findings = check(extra)
    unknown = [f for f in findings if f.code == "topic_unknown"]
    assert unknown[0].topic == "invented"
    assert unknown[0].blocking is False


def test_jargon_without_a_glossary_entry_is_blocking():
    findings = check(course(glossary="Page table: The full map."))
    gap = [f for f in findings if f.code == "jargon_without_glossary"]
    assert len(gap) == 1
    assert "TLB" in gap[0].message
    assert gap[0].blocking is True
    assert gap[0].route == "writer"
    # Attributed to the one topic that owns the term, so only its writer re-runs.
    assert gap[0].module == "m-memory"
    assert gap[0].topic == "tlb"


def test_glossary_matching_ignores_case():
    assert check(course(glossary="tlb: a cache of mappings.")) == []


def test_a_malformed_glossary_block_is_blocking():
    findings = check(course(glossary="no colon at all"))
    bad = [f for f in findings if f.code == "glossary_malformed"]
    assert len(bad) == 1
    # The glossary block is global, not scoped to one module/topic — mdrender's
    # glossary parser errors before anchor tracking even starts, so this finding
    # can never be attributed to a single writer. Per the routing invariant,
    # unattributable findings route to "build" (a re-render, no agent re-run).
    assert bad[0].module is None
    assert bad[0].topic is None
    assert bad[0].route == "build"


def test_a_broken_mermaid_block_is_blocking_and_routes_to_the_writer():
    body = f"The TLB is fast.\n\n```mermaid\nnope\n```\n\n{GOOD_QUIZ}"
    findings = check(course(tlb_body=body))
    bad = [f for f in findings if f.code == "mermaid_unparseable"]
    assert len(bad) == 1
    assert bad[0].route == "writer"
    assert bad[0].module == "m-memory"


@pytest.mark.parametrize(
    "text", ["TODO: explain this", "TBD", "FIXME later", "XXX", "Lorem ipsum dolor",
             "[insert example here]", "<placeholder>"]
)
def test_placeholders_are_blocking(text):
    findings = check(course(tlb_body=f"The TLB is fast. {text}\n\n{GOOD_QUIZ}"))
    placeholders = [f for f in findings if f.code == "placeholder"]
    assert len(placeholders) == 1
    assert placeholders[0].blocking is True


def test_ordinary_prose_is_not_mistaken_for_a_placeholder():
    body = f"The todos of a scheduler are queued; XXXV is a Roman numeral.\n\n{GOOD_QUIZ}"
    assert [f for f in check(course(tlb_body=body)) if f.code == "placeholder"] == []


@pytest.mark.parametrize(
    "html_text",
    [
        '<script src="https://cdn.example.com/x.js"></script>',
        '<img src="http://example.com/a.png">',
        '<link rel="stylesheet" href="//example.com/s.css">',
        "<style>@import url(https://fonts.example.com/f.css);</style>",
        "<style>body { background: url(https://example.com/bg.png); }</style>",
        "<script>fetch('https://example.com/track')</script>",
        "<script>new XMLHttpRequest()</script>",
    ],
)
def test_external_requests_are_blocking_and_route_to_build(html_text):
    findings = validate_course(render_course(course()), OUTLINE, html_text)
    external = [f for f in findings if f.code == "external_request"]
    assert external, html_text
    assert external[0].route == "build"
    assert external[0].blocking is True


@pytest.mark.parametrize(
    "html_text",
    [
        '<a href="https://example.com/paper.pdf">the paper</a>',
        '<img src="data:image/png;base64,AAA">',
        '<div class="mermaid">flowchart LR</div>',
        '<p>Visit https://example.com for more.</p>',
    ],
)
def test_citations_and_data_uris_are_not_external_requests(html_text):
    findings = validate_course(render_course(course()), OUTLINE, html_text)
    assert [f for f in findings if f.code == "external_request"] == []


def test_blocking_filters_and_json_round_trips():
    findings = [
        Finding(code="a", message="m", blocking=True, route="writer", module="m1", topic="t1"),
        Finding(code="b", message="n", blocking=False, route="build"),
    ]
    assert [f.code for f in blocking(findings)] == ["a"]
    assert findings_to_json(findings)[0] == {
        "code": "a", "message": "m", "blocking": True,
        "route": "writer", "module": "m1", "topic": "t1",
    }


def test_linear_chain_is_detected():
    assert is_linear_mermaid("flowchart LR\n  A --> B\n  B --> C\n")


def test_branching_diagram_is_not_linear():
    # A is the source of two edges: that fan-out is what mermaid draws well.
    assert not is_linear_mermaid("flowchart LR\n  A --> B\n  A --> C\n")


def test_single_edge_counts_as_linear():
    assert is_linear_mermaid("flowchart LR\n  A --> B\n")


def test_diagram_with_no_edges_is_not_linear():
    assert not is_linear_mermaid("flowchart LR\n  A\n")


def test_labelled_edges_are_still_linear():
    assert is_linear_mermaid("flowchart LR\n  A -->|yes| B\n  B -->|next| C\n")


def test_node_labels_do_not_break_source_identity():
    # Regression: real diagrams write the label on first mention only, so `M["x"]`
    # and a later bare `M` are the SAME source. A regex that folds the label into
    # the id scores this fan-out as linear.
    assert not is_linear_mermaid(
        'flowchart LR\n  M["camera"] -->|"a"| A["roof"]\n  M -->|"b"| B["ground"]\n'
    )


def test_bracketed_nodes_on_a_straight_chain_are_linear():
    assert is_linear_mermaid(
        'flowchart LR\n  A["Start"] --> B["Middle"]\n  B --> C["End"]\n'
    )


# --- animation coverage floor -----------------------------------------------
#
# A dedicated 4-topic outline/course builder: the animation-floor arithmetic
# needs more topics than the 2-topic OUTLINE/course() fixtures above provide,
# and each topic below carries its own quiz so `animation_floor` is the only
# finding under test (no unrelated topic_without_quiz noise).

FLOOR_OUTLINE = {
    "title": "Networking",
    "subject_domain": "systems",
    "source_decks": ["week2.pdf"],
    "modules": [
        {
            "id": "m-net",
            "title": "Networking Basics",
            "prerequisites": [],
            "topics": [
                {"id": "t1", "title": "Topic One", "slide_refs": ["week2.pdf#1"],
                 "jargon": [], "diagrams": [], "gaps": []},
                {"id": "t2", "title": "Topic Two", "slide_refs": ["week2.pdf#2"],
                 "jargon": [], "diagrams": [], "gaps": []},
                {"id": "t3", "title": "Topic Three", "slide_refs": ["week2.pdf#3"],
                 "jargon": [], "diagrams": [], "gaps": []},
                {"id": "t4", "title": "Topic Four", "slide_refs": ["week2.pdf#4"],
                 "jargon": [], "diagrams": [], "gaps": []},
            ],
        }
    ],
}

FLOOR_HEAD = """---
title: Networking
subject_domain: systems
theme: slate
source_decks:
  - week2.pdf
---

# Networking

## Networking Basics
"""

ANIMATE_BLOCK = "```animate\npattern: state-toggle\nbefore: Ready\nafter: Running\n```"

LINEAR_MERMAID_BLOCK = "```mermaid\nflowchart LR\n  A --> B\n  B --> C\n```"

BRANCHING_MERMAID_BLOCK = "```mermaid\nflowchart LR\n  A --> B\n  A --> C\n```"

NO_VISUAL = "<!-- no-visual: test fixture prose, nothing spatial to draw -->"


def _quiz(question):
    return (
        f"```quiz\nq: {question}\n- [ ] wrong\n- [x] right\n- [ ] also wrong\n"
        "why: because.\n```"
    )


def floor_course(bodies: dict[str, str]) -> str:
    """Build a 4-topic course; bodies maps topic id -> extra content before its quiz."""
    parts = [FLOOR_HEAD]
    for topic_id in ("t1", "t2", "t3", "t4"):
        title = {"t1": "Topic One", "t2": "Topic Two",
                 "t3": "Topic Three", "t4": "Topic Four"}[topic_id]
        extra = bodies.get(topic_id, NO_VISUAL)
        parts.append(f"\n<!-- topic: {topic_id} -->\n### {title}\n\n")
        parts.append(f"Some prose about {title.lower()}.\n\n{extra}\n\n")
        parts.append(_quiz(f"a question about {title.lower()}") + "\n")
    return "".join(parts)


def floor_check(bodies):
    return check(floor_course(bodies), outline=FLOOR_OUTLINE)


def test_animation_floor_is_met_when_a_quarter_of_owing_topics_animate():
    # 4 topics, none justified -> denominator 4, requires 1. t1 animates.
    findings = floor_check({
        "t1": ANIMATE_BLOCK,
        "t2": NO_VISUAL,
        "t3": NO_VISUAL,
        "t4": NO_VISUAL,
    })
    assert "animation_floor" not in codes(findings)


def test_animation_floor_is_blocking_when_under_and_names_conversion_candidates():
    # 4 topics, none animate. t2 and t3 carry linear mermaid chains: candidates.
    findings = floor_check({
        "t1": NO_VISUAL,
        "t2": LINEAR_MERMAID_BLOCK,
        "t3": LINEAR_MERMAID_BLOCK,
        "t4": NO_VISUAL,
    })
    floor = [f for f in findings if f.code == "animation_floor"]
    assert len(floor) == 1
    assert floor[0].blocking is True
    assert floor[0].route == "writer"
    assert "t2" in floor[0].message and "t3" in floor[0].message


def test_animation_floor_requirement_rounds_up():
    # t4 is no-visual justified (drops out) -> 3 owing topics (t1-t3), each with a
    # plain, non-justified visual (mermaid) and no animation. 3 * 0.25 = 0.75,
    # which still rounds up to requiring 1 -- none animate, so this fails.
    findings_under = floor_check({
        "t1": BRANCHING_MERMAID_BLOCK,
        "t2": BRANCHING_MERMAID_BLOCK,
        "t3": BRANCHING_MERMAID_BLOCK,
        "t4": NO_VISUAL,
    })
    assert "animation_floor" in codes(findings_under)

    # Same 3-owing-topic shape, but t1 now animates -> 1 of 3 meets the
    # rounded-up requirement of 1.
    findings_ok = floor_check({
        "t1": ANIMATE_BLOCK,
        "t2": BRANCHING_MERMAID_BLOCK,
        "t3": BRANCHING_MERMAID_BLOCK,
        "t4": NO_VISUAL,
    })
    assert "animation_floor" not in codes(findings_ok)


def test_no_visual_justified_topics_leave_the_animation_floor_denominator():
    # t1 animates; t3/t4 are no-visual justified (drop out of the denominator);
    # t2 has a plain (non-justified) visual. Denominator is {t1, t2} = 2, requires
    # 1, and t1 alone satisfies it.
    findings = floor_check({
        "t1": ANIMATE_BLOCK,
        "t2": BRANCHING_MERMAID_BLOCK,
        "t3": NO_VISUAL,
        "t4": NO_VISUAL,
    })
    assert "animation_floor" not in codes(findings)


def test_animation_floor_is_skipped_when_no_topic_owes_a_visual():
    # All 4 topics justified -> denominator 0 -> check skipped entirely.
    findings = floor_check({
        "t1": NO_VISUAL,
        "t2": NO_VISUAL,
        "t3": NO_VISUAL,
        "t4": NO_VISUAL,
    })
    assert "animation_floor" not in codes(findings)


def test_animation_floor_failure_says_no_linear_when_no_candidates_exist():
    # 4 topics, none animate, none carry a linear mermaid chain to convert.
    findings = floor_check({
        "t1": NO_VISUAL,
        "t2": BRANCHING_MERMAID_BLOCK,
        "t3": NO_VISUAL,
        "t4": NO_VISUAL,
    })
    floor = [f for f in findings if f.code == "animation_floor"]
    assert len(floor) == 1
    assert "no linear" in floor[0].message.lower()


def test_animation_floor_routes_to_the_writer():
    assert ROUTE_FOR_CODE["animation_floor"] == "writer"
