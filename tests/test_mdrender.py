import json
import math
import re

import pytest

from p2c.mdrender import (
    _STATE_BOX_HEIGHT,
    Animate,
    AnimateError,
    FigureError,
    mermaid_problem,
    parse_animate,
    parse_figure,
    render_course,
)

FM = """---
title: Operating Systems
subject_domain: systems
theme: slate
source_decks:
  - week1.pdf
---
"""


def course(body: str) -> str:
    return FM + "\n# Operating Systems\n\n" + body


MODULE = """## Virtual Memory

```prereq
- Binary arithmetic
```

<!-- topic: tlb -->
### The TLB

Plain framing first.

```analogy
A passport stamp you already have in your pocket.
```

The TLB caches mappings. The page table is bigger.

```mermaid
flowchart LR
  VA[Virtual address] --> TLB{In TLB?}
```

```quiz
q: What does a TLB cache?
- [ ] Page contents
- [x] Virtual-to-physical mappings
- [ ] The page table itself
why: It caches translations, not data.
```

<!-- topic: thrashing -->
### Thrashing

When the working set exceeds memory.

```quiz
q: What is thrashing?
- [x] Paging dominating useful work
- [ ] A CPU stall
- [ ] A disk failure
why: The clue is where the time goes.
```

```glossary
TLB: A cache of recently used virtual-to-physical page mappings.
Page table: The full in-memory map from virtual pages to physical frames.
```
"""


@pytest.mark.parametrize(
    "body",
    [
        "flowchart LR\n  A --> B",
        "  \n\nsequenceDiagram\n  A->>B: hi",
        "stateDiagram-v2\n  [*] --> Idle",
        'graph TD\n  A["a label"] --> B',
        "flowchart LR\n  A --> B\n  style A fill:#2e7d32,color:#fff",
        "flowchart LR\n  A --> B\n  style A stroke:#dc3545",
    ],
)
def test_mermaid_problem_accepts_valid_diagrams(body):
    assert mermaid_problem(body) is None


@pytest.mark.parametrize(
    "body,message",
    [
        ("", "empty"),
        ("   \n  ", "empty"),
        ("nonsense LR\n A --> B", "unrecognised diagram type"),
        ("flowchart LR\n  A[unclosed --> B", "unbalanced"),
        ('flowchart LR\n  A["unclosed --> B', "unbalanced"),
        (
            "flowchart LR\n  A --> B\n  style A fill:#f8d7da,stroke:#dc3545",
            "fill without color",
        ),
    ],
)
def test_mermaid_problem_rejects_broken_diagrams(body, message):
    assert message in mermaid_problem(body)


def test_renders_headings_with_stable_anchors_and_a_nested_toc():
    r = render_course(course(MODULE))
    assert [(s.level, s.id, s.topic_id) for s in r.sections] == [
        (1, "operating-systems", None),
        (2, "virtual-memory", None),
        (3, "the-tlb", "tlb"),
        (3, "thrashing", "thrashing"),
    ]
    assert '<h3 id="the-tlb">The TLB</h3>' in r.html_body
    assert '<li class="toc__module"><a href="#virtual-memory">' in r.toc_html
    assert '<li class="toc__topic"><a href="#the-tlb">' in r.toc_html
    assert r.toc_html.count("<ul") == r.toc_html.count("</ul>")
    assert "operating-systems" not in r.toc_html
    # The template's appendix sections always exist (see {{GLOSSARY}}/{{SOURCES}}
    # in template.html), so the TOC always links to them too -- otherwise they're
    # reachable only by scrolling past the footer.
    assert '<li class="toc__module"><a href="#glossary">Glossary</a></li>' in r.toc_html
    assert '<li class="toc__module"><a href="#sources">Sources</a></li>' in r.toc_html


def test_topic_markers_do_not_reach_the_html():
    r = render_course(course(MODULE))
    assert "<!-- topic:" not in r.html_body
    assert r.topic_ids == ["tlb", "thrashing"]


def test_quiz_ids_are_scoped_to_their_topic_and_counted():
    r = render_course(course(MODULE))
    assert 'data-quiz="the-tlb-q1"' in r.html_body
    assert 'data-quiz="thrashing-q1"' in r.html_body
    assert r.quiz_count == 2
    assert r.quizzes_per_topic == {"tlb": 1, "thrashing": 1}
    assert r.errors == []


def test_a_topic_with_no_quiz_is_recorded_as_zero():
    body = "## M\n\n<!-- topic: bare -->\n### Bare\n\nNo check here.\n"
    r = render_course(course(body))
    assert r.quizzes_per_topic == {"bare": 0}


def test_a_malformed_quiz_becomes_an_error_and_is_dropped():
    body = "## M\n\n<!-- topic: t -->\n### T\n\n```quiz\nq: only two\n- [x] a\n- [ ] b\nwhy: w\n```\n"
    r = render_course(course(body))
    assert any("3 or 4 options" in e for e in r.errors)
    assert "quiz__option" not in r.html_body


def test_callouts_render_as_asides_with_labels():
    r = render_course(course(MODULE))
    assert '<aside class="callout callout--analogy">' in r.html_body
    assert "<p class=\"callout__label\">Analogy</p>" in r.html_body
    assert '<aside class="callout callout--prereq">' in r.html_body
    assert "Before this module" in r.html_body
    assert "<li>Binary arithmetic</li>" in r.html_body


def test_unverified_callout_is_supported():
    body = "## M\n\n<!-- topic: t -->\n### T\n\n```unverified\nSources did not confirm this.\n```\n"
    r = render_course(course(body))
    assert '<aside class="callout callout--unverified">' in r.html_body
    assert "Not fully verified" in r.html_body


def test_mermaid_blocks_become_divs_and_set_the_flag():
    r = render_course(course(MODULE))
    assert '<div class="mermaid" dir="ltr">flowchart LR' in r.html_body
    assert r.uses_mermaid is True
    # Escaped in the source, decoded back to "-->" by textContent when Mermaid reads it.
    assert "--&gt; TLB" in r.html_body


def test_an_animate_block_sets_the_uses_animate_flag():
    md = course(
        '<!-- topic: tlb -->\n### The TLB\n\n'
        '```animate\npattern: state-toggle\nbefore: Ready\nafter: Running\n```\n\n'
        '```quiz\nq: q\n- [ ] a\n- [x] b\n- [ ] c\nwhy: because\n```\n\n'
        '```glossary\nTLB: definition\n```\n'
    )
    rendered = render_course(md)
    assert rendered.errors == []
    assert rendered.uses_animate is True


def test_uses_animate_is_false_with_no_animate_blocks():
    rendered = render_course(course(MODULE))  # MODULE has no animate block
    assert rendered.uses_animate is False


def test_a_broken_mermaid_block_degrades_to_a_fallback_and_never_sets_the_flag():
    body = "## M\n\n<!-- topic: t -->\n### T\n\n```mermaid\nnope LR\n A --> B\n```\n"
    r = render_course(course(body))
    assert r.uses_mermaid is False
    assert 'class="diagram-fallback"' in r.html_body
    assert any("unrecognised diagram type" in e for e in r.errors)


def test_glossary_blocks_leave_the_body_and_become_an_appendix():
    r = render_course(course(MODULE))
    assert "```glossary" not in r.html_body
    assert "Page table: The full in-memory map" not in r.html_body
    assert '<dt id="def-page-table">Page table</dt>' in r.glossary_html
    assert set(r.glossary) == {"TLB", "Page table"}


def test_terms_are_injected_once_per_topic_and_never_in_headings():
    r = render_course(course(MODULE))
    assert r.html_body.count('class="term"') == 2  # TLB and page table, in the TLB topic
    assert '<h3 id="the-tlb">The TLB</h3>' in r.html_body
    assert 'aria-controls="def-tlb"' in r.html_body


def test_inline_code_is_never_term_injected():
    body = (
        "## M\n\n<!-- topic: t -->\n### T\n\nUse `TLB` carefully.\n\n"
        "```glossary\nTLB: A cache.\n```\n"
    )
    r = render_course(course(body))
    assert "<code>TLB</code>" in r.html_body
    assert 'class="term"' not in r.html_body


def test_ordinary_code_fences_still_render_as_code():
    body = "## M\n\n<!-- topic: t -->\n### T\n\n```python\nx = 1\n```\n"
    r = render_course(course(body))
    assert "<code" in r.html_body and "x = 1" in r.html_body


def test_front_matter_is_returned_and_stripped_from_the_body():
    r = render_course(course(MODULE))
    assert r.front_matter.theme == "slate"
    assert "subject_domain" not in r.html_body


def test_duplicate_titles_get_distinct_anchors():
    body = (
        "## M\n\n<!-- topic: a -->\n### Caching\n\nOne.\n\n"
        "<!-- topic: b -->\n### Caching\n\nTwo.\n"
    )
    r = render_course(course(body))
    assert [s.id for s in r.sections if s.level == 3] == ["caching", "caching-2"]


def test_a_heading_like_line_inside_an_ordinary_code_fence_is_not_parsed_as_a_heading():
    # Reproduces the reviewer's report: a `#`-commented line inside an unhandled
    # (e.g. ```c) code fence must not be mistaken for a real heading, must not steal
    # the real topic's anchor, and must not leak attr-list syntax into the rendered
    # <pre><code> block.
    body = (
        "## M\n\n"
        "### Intro\n\n"
        "```c\n"
        "# The TLB\n"
        "int x;\n"
        "```\n\n"
        "<!-- topic: tlb -->\n"
        "### The TLB\n\n"
        "Some text.\n\n"
        "```quiz\nq: Q?\n- [ ] a\n- [x] b\n- [ ] c\nwhy: w\n```\n"
    )
    r = render_course(course(body))

    titles = [s.title for s in r.sections]
    assert titles.count("The TLB") == 1  # no phantom section from inside the fence
    ids = [s.id for s in r.sections]
    assert "the-tlb" in ids
    assert "the-tlb-2" not in ids  # the phantom did not steal the real anchor
    assert 'data-quiz="the-tlb-q1"' in r.html_body  # quiz id not bumped by a phantom
    assert "{: #" not in r.html_body  # attr-list syntax never leaks into output
    # Only the real "# Operating Systems" course title is an <h1>; the code sample's
    # "# The TLB" line must not produce a second one.
    assert r.html_body.count("<h1") == 1
    assert "# The TLB" in r.html_body  # the line still renders as plain code text


def test_a_topic_marker_inside_an_ordinary_code_fence_is_not_treated_as_a_real_marker():
    # A `<!-- topic: id -->` line that appears as *example text* inside a code sample
    # must not be consumed as a real marker (which would both swallow it and leave a
    # stale pending_topic attached to the next actual heading).
    body = (
        "## M\n\n"
        "```markdown\n"
        "<!-- topic: bogus -->\n"
        "### Not a real heading\n"
        "```\n\n"
        "<!-- topic: tlb -->\n"
        "### The TLB\n\nText.\n"
    )
    r = render_course(course(body))
    assert [s.topic_id for s in r.sections if s.level == 3] == ["tlb"]
    assert "bogus" not in r.topic_ids


def test_an_unterminated_code_fence_does_not_swallow_the_rest_of_the_document():
    # Reproduces the fence-tracking regression: a code fence that opens but never
    # closes must not suppress heading/topic-marker detection for everything that
    # follows it. p2c.blocks.extract_fences's own contract is that an unterminated
    # fence "is left untouched" -- the same must hold here.
    body = (
        "## M\n\n### Intro\n\n"
        "```python\nx = 1\n# not closed\n\n"
        "<!-- topic: tlb -->\n### The TLB\n\nSome text.\n"
    )
    r = render_course(course(body))
    titles = [s.title for s in r.sections]
    assert "The TLB" in titles
    assert [s.topic_id for s in r.sections if s.level == 3 and s.title == "The TLB"] == [
        "tlb"
    ]
    assert r.topic_ids == ["tlb"]


def test_content_inside_a_never_closed_fence_is_treated_as_ordinary_markdown_by_design():
    # This locks in EXPECTED behavior, not a bug: an unterminated fence is
    # inherently ambiguous input (nothing downstream can tell whether the author
    # meant "the rest of the document is code" or "I forgot a closing ```, the rest
    # is real markdown"). p2c.blocks.extract_fences already committed the whole
    # pipeline to the second reading ("an unterminated fence is left untouched").
    # Confirmed independently: feeding this exact body through extract_fences() and
    # then real markdown.markdown(), with no mdrender involved at all, also renders
    # "## fake module" as a genuine <h2> and leaves "<!-- topic: bogus -->" as a
    # plain HTML comment. mdrender must stay consistent with that reading rather
    # than invent a third, bespoke interpretation of malformed input -- so a
    # #-style line or a <!-- topic: ... --> example inside the dangling body of a
    # fence that never closes IS parsed as real structure here too.
    body = (
        "## M\n\n<!-- topic: real1 -->\n### Intro\n\n"
        "```bash\necho hi\n## fake module\n<!-- topic: bogus -->\n\n"
        "```quiz\nq: real quiz?\n- [x] a\n- [ ] b\n- [ ] c\nwhy: w\n```\n\n"
        "<!-- topic: tlb -->\n### The TLB\n\nSome text.\n"
    )
    r = render_course(course(body))
    titles = [s.title for s in r.sections]
    # The dangling "## fake module" line becomes a genuine (if unintended-by-the-
    # author) section, exactly as plain extract_fences + markdown.markdown() would
    # render it -- this is the documented, expected consequence of the ambiguity.
    assert "fake module" in titles
    # Real structure that follows the dangling body still recovers correctly.
    assert "The TLB" in titles
    assert r.topic_ids[-1] == "tlb"


def test_quiz_error_string_matches_the_anchor_colon_message_contract_exactly():
    body = "## M\n\n<!-- topic: t -->\n### T\n\n```quiz\nq: only two\n- [x] a\n- [ ] b\nwhy: w\n```\n"
    r = render_course(course(body))
    assert r.errors == ["t: quiz needs 3 or 4 options, found 2"]


def test_mermaid_error_string_matches_the_anchor_colon_mermaid_message_contract_exactly():
    body = "## M\n\n<!-- topic: t -->\n### T\n\n```mermaid\nnope LR\n A --> B\n```\n"
    r = render_course(course(body))
    assert r.errors == ["t: mermaid unrecognised diagram type 'nope'"]


def test_glossary_error_string_starts_with_the_glossary_block_prefix_exactly():
    body = (
        "## M\n\n<!-- topic: t -->\n### T\n\nText.\n\n"
        "```glossary\nBadLineNoColon\n```\n"
    )
    r = render_course(course(body))
    assert len(r.errors) == 1
    assert r.errors[0].startswith("glossary block: ")


def test_multiple_quizzes_in_one_topic_get_distinct_scoped_ids_and_are_all_counted():
    body = (
        "## M\n\n"
        "<!-- topic: tlb -->\n### The TLB\n\nText.\n\n"
        "```quiz\nq: Q1?\n- [x] a\n- [ ] b\n- [ ] c\nwhy: w1\n```\n\n"
        "```quiz\nq: Q2?\n- [ ] a\n- [x] b\n- [ ] c\nwhy: w2\n```\n\n"
        "<!-- topic: thrashing -->\n### Thrashing\n\nText.\n\n"
        "```quiz\nq: Q3?\n- [x] a\n- [ ] b\n- [ ] c\nwhy: w3\n```\n"
    )
    r = render_course(course(body))
    assert r.quizzes_per_topic == {"tlb": 2, "thrashing": 1}
    assert r.quiz_count == 3
    assert 'data-quiz="the-tlb-q1"' in r.html_body
    assert 'data-quiz="the-tlb-q2"' in r.html_body
    assert 'data-quiz="thrashing-q1"' in r.html_body
    assert r.errors == []


def test_parse_figure_extracts_source_and_caption():
    source, caption = parse_figure("source: week1.pdf#12\ncaption: The TLB lookup path.")
    assert source == "week1.pdf#12"
    assert caption == "The TLB lookup path."


def test_parse_figure_rejects_a_missing_source():
    with pytest.raises(FigureError, match="missing a 'source:'"):
        parse_figure("caption: Only a caption.")


def test_parse_figure_rejects_a_missing_caption():
    with pytest.raises(FigureError, match="missing a 'caption:'"):
        parse_figure("source: week1.pdf#12")


def test_parse_figure_rejects_a_malformed_source_ref():
    with pytest.raises(FigureError, match="must look like 'deck.pdf#12'"):
        parse_figure("source: week1.pdf\ncaption: Missing the page number.")


def test_figure_block_renders_a_pending_placeholder():
    md = course(
        '<!-- topic: tlb -->\n### The TLB\n\n'
        '```figure\nsource: week1.pdf#12\ncaption: The lookup path.\n```\n\n'
        '```quiz\nq: q\n- [ ] a\n- [x] b\n- [ ] c\nwhy: because\n```\n\n'
        '```glossary\nTLB: definition\n```\n'
    )
    rendered = render_course(md)
    assert rendered.errors == []
    assert 'data-p2c-image-pending="week1.pdf#12"' in rendered.html_body
    assert 'data-p2c-topic="tlb"' in rendered.html_body
    assert '<figcaption>The lookup path.</figcaption>' in rendered.html_body
    assert '<img alt="The lookup path.">' in rendered.html_body


def test_a_broken_figure_block_becomes_an_error_not_a_crash():
    md = course(
        '<!-- topic: tlb -->\n### The TLB\n\n'
        '```figure\ncaption: No source at all.\n```\n\n'
        '```quiz\nq: q\n- [ ] a\n- [x] b\n- [ ] c\nwhy: because\n```\n\n'
        '```glossary\nTLB: definition\n```\n'
    )
    rendered = render_course(md)
    assert any("figure" in e for e in rendered.errors)


def test_parse_animate_state_machine_linear_chain():
    anim = parse_animate(
        "pattern: state-machine\n"
        "states:\n"
        "  - Ready\n"
        "  - Running\n"
        "  - Terminated\n"
        "transitions:\n"
        "  - Ready -> Running: scheduled\n"
        "  - Running -> Terminated: exits\n"
    )
    assert anim == Animate(
        pattern="state-machine",
        states=["Ready", "Running", "Terminated"],
        transitions=[("Ready", "Running", "scheduled"), ("Running", "Terminated", "exits")],
    )


def test_parse_animate_state_machine_with_a_trailing_back_edge():
    anim = parse_animate(
        "pattern: state-machine\n"
        "states:\n"
        "  - Idle\n"
        "  - Requesting\n"
        "  - Granted\n"
        "transitions:\n"
        "  - Idle -> Requesting: request\n"
        "  - Requesting -> Granted: grant\n"
        "  - Granted -> Idle: release\n"
    )
    assert anim == Animate(
        pattern="state-machine",
        states=["Idle", "Requesting", "Granted"],
        transitions=[
            ("Idle", "Requesting", "request"),
            ("Requesting", "Granted", "grant"),
            ("Granted", "Idle", "release"),
        ],
    )


def test_parse_animate_state_toggle():
    anim = parse_animate(
        "pattern: state-toggle\nbefore: Marked Shared\nafter: Marked Modified"
    )
    assert anim == Animate(pattern="state-toggle", before="Marked Shared", after="Marked Modified")


def test_parse_animate_rejects_an_unknown_pattern():
    with pytest.raises(AnimateError, match="animate pattern must be"):
        parse_animate("pattern: spin\nstates:\n  - a\n  - b")


def test_parse_animate_rejects_a_state_machine_with_one_state():
    with pytest.raises(AnimateError, match="at least 2 states"):
        parse_animate("pattern: state-machine\nstates:\n  - only one\ntransitions:")


def test_parse_animate_rejects_a_state_machine_with_no_transitions():
    with pytest.raises(AnimateError, match="at least 1 transition"):
        parse_animate("pattern: state-machine\nstates:\n  - A\n  - B\ntransitions:")


def test_parse_animate_state_machine_rejects_an_unknown_state_in_a_transition():
    with pytest.raises(AnimateError, match="unknown state 'C'"):
        parse_animate(
            "pattern: state-machine\nstates:\n  - A\n  - B\n"
            "transitions:\n  - A -> C: go\n"
        )


def test_parse_animate_state_machine_rejects_a_non_adjacent_forward_transition():
    with pytest.raises(AnimateError, match="must connect consecutive states"):
        parse_animate(
            "pattern: state-machine\nstates:\n  - A\n  - B\n  - C\n"
            "transitions:\n  - A -> C: skip\n"
        )


def test_parse_animate_state_machine_rejects_a_back_edge_that_is_not_last():
    with pytest.raises(AnimateError, match="must connect consecutive states"):
        parse_animate(
            "pattern: state-machine\nstates:\n  - A\n  - B\n  - C\n"
            "transitions:\n  - B -> A: back\n  - B -> C: forward\n"
        )


def test_parse_animate_state_machine_rejects_branching():
    """A state may have at most one outgoing transition (except the one permitted
    trailing back-edge case, which is a property of the LAST state, not a second
    outgoing edge from an earlier one) -- branching is out of scope, see the design
    spec's rationale (a single continuous marker cannot meaningfully choose a branch).
    """
    with pytest.raises(AnimateError, match="must connect consecutive states"):
        parse_animate(
            "pattern: state-machine\nstates:\n  - A\n  - B\n  - C\n"
            "transitions:\n  - A -> B: one\n  - A -> C: two\n"
        )


def test_parse_animate_state_machine_rejects_a_duplicated_back_edge_line():
    """The "at most one back-edge" guard must be POSITIONAL, not value-based. Two
    identical back-edge lines both compare equal to transitions_raw[-1], so a
    value-equality check accepts BOTH -- producing two back-edges where the
    renderer (and _state_machine_html's back-edge detection, which only inspects
    transitions[-1]) assumes at most one. Only the line that is actually last by
    POSITION may be the permitted back-edge; the earlier duplicate is just a
    non-consecutive transition and is rejected like any other.
    """
    with pytest.raises(AnimateError, match="must connect consecutive states"):
        parse_animate(
            "pattern: state-machine\nstates:\n  - A\n  - B\n  - C\n"
            "transitions:\n  - A -> B: go\n  - B -> C: go2\n"
            "  - C -> A: loop\n  - C -> A: loop\n"
        )


def test_parse_animate_state_machine_rejects_a_malformed_transition_line():
    with pytest.raises(AnimateError, match="invalid state-machine transition"):
        parse_animate(
            "pattern: state-machine\nstates:\n  - A\n  - B\n"
            "transitions:\n  - A to B without an arrow\n"
        )


def test_parse_animate_state_machine_rejects_array_and_points_fields():
    with pytest.raises(
        AnimateError,
        match="state-machine does not use 'before:'/'after:'/'array:'/'ops:'/'points:'/'caption:'",
    ):
        parse_animate(
            "pattern: state-machine\nstates:\n  - A\n  - B\n"
            "transitions:\n  - A -> B: go\narray:\n  - 1\n"
        )


def test_parse_animate_rejects_a_state_toggle_missing_after():
    with pytest.raises(AnimateError, match="needs both 'before:' and 'after:'"):
        parse_animate("pattern: state-toggle\nbefore: only before")


def test_parse_animate_array_ops():
    anim = parse_animate(
        "pattern: array-ops\narray:\n  - 5\n  - 3\n  - 8\n  - 1\n"
        "ops:\n  - compare 0 1\n  - swap 0 1\n  - highlight 2"
    )
    assert anim == Animate(
        pattern="array-ops",
        array=[5, 3, 8, 1],
        ops=[("compare", 0, 1), ("swap", 0, 1), ("highlight", 2, None)],
    )


def test_parse_animate_array_ops_rejects_too_few_values():
    with pytest.raises(AnimateError, match="at least 2 array values"):
        parse_animate("pattern: array-ops\narray:\n  - 5\nops:\n  - highlight 0")


def test_parse_animate_array_ops_rejects_a_non_integer_value():
    with pytest.raises(AnimateError, match="array item 'five' is not an integer"):
        parse_animate(
            "pattern: array-ops\narray:\n  - five\n  - 3\nops:\n  - highlight 0"
        )


def test_parse_animate_array_ops_rejects_no_ops():
    with pytest.raises(AnimateError, match="at least one op"):
        parse_animate("pattern: array-ops\narray:\n  - 1\n  - 2\nops:")


def test_parse_animate_array_ops_rejects_a_malformed_op():
    with pytest.raises(AnimateError, match="invalid array-ops operation: 'flip 0'"):
        parse_animate(
            "pattern: array-ops\narray:\n  - 1\n  - 2\nops:\n  - flip 0"
        )


def test_parse_animate_array_ops_rejects_compare_with_one_index():
    with pytest.raises(AnimateError, match="invalid array-ops operation: 'compare 0'"):
        parse_animate(
            "pattern: array-ops\narray:\n  - 1\n  - 2\nops:\n  - compare 0"
        )


def test_parse_animate_array_ops_rejects_highlight_with_two_indices():
    with pytest.raises(AnimateError, match="invalid array-ops operation: 'highlight 0 1'"):
        parse_animate(
            "pattern: array-ops\narray:\n  - 1\n  - 2\nops:\n  - highlight 0 1"
        )


def test_parse_animate_array_ops_rejects_an_out_of_range_index():
    with pytest.raises(AnimateError, match=r"index 2 out of range for array of length 2"):
        parse_animate(
            "pattern: array-ops\narray:\n  - 1\n  - 2\nops:\n  - highlight 2"
        )


def test_parse_animate_array_ops_rejects_before_after():
    with pytest.raises(AnimateError, match="array-ops does not use 'before:'/'after:'"):
        parse_animate(
            "pattern: array-ops\narray:\n  - 1\n  - 2\nops:\n  - highlight 0\nbefore: x"
        )


def test_pipeline_parses_stages_into_name_change_pairs():
    anim = parse_animate(
        "pattern: pipeline\n"
        "stages:\n"
        "  - Raw image: single RGB frame\n"
        "  - Encoder: compresses into a feature map\n"
    )
    assert anim.pattern == "pipeline"
    assert anim.stages == [
        ("Raw image", "single RGB frame"),
        ("Encoder", "compresses into a feature map"),
    ]


def test_pipeline_rejects_fewer_than_two_stages():
    with pytest.raises(AnimateError, match="at least 2 stages"):
        parse_animate("pattern: pipeline\nstages:\n  - Only one: does nothing\n")


def test_pipeline_rejects_more_than_six_stages():
    body = "pattern: pipeline\nstages:\n" + "".join(
        f"  - Stage {i}: does thing {i}\n" for i in range(7)
    )
    with pytest.raises(AnimateError, match="at most 6 stages"):
        parse_animate(body)


def test_pipeline_rejects_stage_without_a_change_description():
    with pytest.raises(AnimateError, match="must be written as"):
        parse_animate("pattern: pipeline\nstages:\n  - Encoder\n  - Decoder: expands\n")


def test_pipeline_rejects_keys_from_other_patterns():
    with pytest.raises(AnimateError, match="does not use"):
        parse_animate(
            "pattern: pipeline\nstages:\n  - A: does a\n  - B: does b\n"
            "points:\n  - 0, 1\n"
        )


@pytest.mark.parametrize(
    "block",
    [
        # step-reveal is retired (see docs/superpowers/specs/2026-08-06-v1.3.0-bugfixes-design.md).
        # state-machine is deliberately absent too: like the old step-reveal, its
        # transitions play sequentially by design (see
        # test_state_machine_transitions_play_sequentially_not_all_at_once in
        # this file), so it emits no "<" position for THIS test to check the
        # escaping of -- its "<" coverage comes from array-ops below instead.
        'pattern: state-toggle\nbefore: Shared\nafter: Modified',
        'pattern: array-ops\narray:\n  - 5\n  - 3\n  - 8\nops:\n  - compare 0 1\n  - swap 0 1',
    ],
)
def test_timeline_island_position_tokens_are_not_html_escaped(block):
    """A <script> is an HTML *raw text* element, so character references inside it
    are never decoded. html.escape()-ing the island would hand JSON.parse the four
    literal characters "&lt;" instead of "<", turning anime.js's
    "start with the previous step" position token into an unrecognized string and
    silently making parallel steps play sequentially. The island must therefore
    contain no "&lt;", and every position that means "<" must parse back to "<".
    """
    md = course(
        '<!-- topic: tlb -->\n### The TLB\n\n'
        f'```animate\n{block}\n```\n\n'
        '```quiz\nq: q\n- [ ] a\n- [x] b\n- [ ] c\nwhy: because\n```\n\n'
        '```glossary\nTLB: definition\n```\n'
    )
    rendered = render_course(md)
    assert rendered.errors == []
    match = re.search(
        r'<script type="application/json" class="anim__timeline"[^>]*>(.*?)</script>',
        rendered.html_body,
        re.DOTALL,
    )
    assert match, "no anim__timeline data island found"
    raw = match.group(1)
    assert "&lt;" not in raw
    # No literal "<" survives either, so the payload can never begin a "</script>"
    # sequence that would break out of the island.
    assert "<" not in raw
    positions = [s.get("position") for s in json.loads(raw)["steps"]]
    assert "<" in positions, positions


def test_state_machine_renders_boxes_arrows_and_a_timeline_island():
    md = course(
        '<!-- topic: tlb -->\n### The TLB\n\n'
        '```animate\npattern: state-machine\nstates:\n  - Ready\n  - Running\n  - Done\n'
        'transitions:\n  - Ready -> Running: schedule\n  - Running -> Done: exit\n```\n\n'
        '```quiz\nq: q\n- [ ] a\n- [x] b\n- [ ] c\nwhy: because\n```\n\n'
        '```glossary\nTLB: definition\n```\n'
    )
    rendered = render_course(md)
    assert rendered.errors == []
    assert '<div class="anim anim--state-machine">' in rendered.html_body
    # Three state boxes, each labeled with its state text.
    assert '>Ready<' in rendered.html_body
    assert '>Running<' in rendered.html_body
    assert '>Done<' in rendered.html_body
    # Two static arrows (one per transition) -- always visible, not hidden.
    assert rendered.html_body.count('class="anim__state-arrow"') == 2
    # Two transition-label texts, both initially hidden (opacity driven to 0 by
    # CSS default, not inline -- see the CSS assertions below); their TEXT must
    # already be present in the markup (for reduced-motion/print and for the
    # timeline's onBegin/onComplete to just toggle opacity, not inject text).
    assert '>schedule<' in rendered.html_body
    assert '>exit<' in rendered.html_body
    match = re.search(
        r'<script type="application/json" class="anim__timeline"[^>]*>(.*?)</script>',
        rendered.html_body,
        re.DOTALL,
    )
    assert match, "no anim__timeline data island found"
    timeline = json.loads(match.group(1))
    assert timeline["loop"] is True
    assert '<ol class="anim__state-steps-static">' in rendered.html_body
    assert '<li>Ready — schedule — Running</li>' in rendered.html_body
    assert '<li>Running — exit — Done</li>' in rendered.html_body


def test_state_machine_transitions_play_sequentially_not_all_at_once():
    """Mirrors the old step-reveal sequencing test: each transition must play
    ONE AT A TIME (marker travels, THEN the next transition begins), never all
    at once. No "<" position on the marker-travel steps themselves.
    """
    md = course(
        '<!-- topic: tlb -->\n### The TLB\n\n'
        '```animate\npattern: state-machine\nstates:\n  - A\n  - B\n  - C\n'
        'transitions:\n  - A -> B: go1\n  - B -> C: go2\n```\n\n'
        '```quiz\nq: q\n- [ ] a\n- [x] b\n- [ ] c\nwhy: because\n```\n\n'
        '```glossary\nTLB: definition\n```\n'
    )
    rendered = render_course(md)
    assert rendered.errors == []
    match = re.search(
        r'<script type="application/json" class="anim__timeline"[^>]*>(.*?)</script>',
        rendered.html_body,
        re.DOTALL,
    )
    steps = json.loads(match.group(1))["steps"]
    marker_travel_positions = [
        s.get("position") for s in steps if s.get("kind") == "path-segment"
    ]
    # The first marker-travel step starts the timeline (position None, i.e.
    # "append after the previous step ends" from an empty timeline); the second
    # ALSO has no "<" -- it must wait for the first transition to finish, not
    # start in parallel with it.
    assert marker_travel_positions == [None, None]


def test_state_machine_with_a_back_edge_animates_it_as_a_real_transition():
    md = course(
        '<!-- topic: tlb -->\n### The TLB\n\n'
        '```animate\npattern: state-machine\nstates:\n  - A\n  - B\n'
        'transitions:\n  - A -> B: go\n  - B -> A: reset\n```\n\n'
        '```quiz\nq: q\n- [ ] a\n- [x] b\n- [ ] c\nwhy: because\n```\n\n'
        '```glossary\nTLB: definition\n```\n'
    )
    rendered = render_course(md)
    assert rendered.errors == []
    match = re.search(
        r'<script type="application/json" class="anim__timeline"[^>]*>(.*?)</script>',
        rendered.html_body,
        re.DOTALL,
    )
    steps = json.loads(match.group(1))["steps"]
    marker_travels = [s for s in steps if s.get("kind") == "path-segment"]
    # Both transitions (A->B and the authored B->A back-edge) are real,
    # animated marker travels -- exactly 2, not 1 plus an invisible reset.
    assert len(marker_travels) == 2
    # No trailing invisible "kind": "set" reset of the marker's position back to
    # state A's box -- that reset only happens when there is NO authored
    # back-edge (see test_state_machine_without_a_back_edge_resets_invisibly).
    trailing_kind_set_on_marker = [
        s for s in steps
        if s.get("kind") == "set" and "anim-state-marker" in " ".join(s.get("targets", []))
    ]
    assert trailing_kind_set_on_marker == []


def test_state_machine_without_a_back_edge_resets_invisibly():
    """A finite chain (no authored back-edge) must NOT visibly loop back to the
    first state -- the restart is an invisible kind:"set" snap, never a drawn or
    animated arrow, so a reader never mistakes the replay-for-engagement loop
    for a real "final -> first" transition that was never authored.
    """
    md = course(
        '<!-- topic: tlb -->\n### The TLB\n\n'
        '```animate\npattern: state-machine\nstates:\n  - A\n  - B\n  - C\n'
        'transitions:\n  - A -> B: go1\n  - B -> C: go2\n```\n\n'
        '```quiz\nq: q\n- [ ] a\n- [x] b\n- [ ] c\nwhy: because\n```\n\n'
        '```glossary\nTLB: definition\n```\n'
    )
    rendered = render_course(md)
    match = re.search(
        r'<script type="application/json" class="anim__timeline"[^>]*>(.*?)</script>',
        rendered.html_body,
        re.DOTALL,
    )
    steps = json.loads(match.group(1))["steps"]
    marker_travels = [s for s in steps if s.get("kind") == "path-segment"]
    # Exactly 2 real transitions were authored -- no third, phantom "C -> A" travel.
    assert len(marker_travels) == 2
    trailing_kind_set_on_marker = [
        s for s in steps
        if s.get("kind") == "set" and "anim-state-marker" in " ".join(s.get("targets", []))
    ]
    assert len(trailing_kind_set_on_marker) == 1


def test_state_machine_box_highlight_targets_the_rect_not_the_group():
    """The only visible shape in a state box is its child <rect>; animating `fill`
    on the wrapping <g> never reaches a rendered pixel (the rect carries its own
    fill). Every fill-animating step -- arrival highlight, settle-back-to-idle,
    and both trailing kind:"set" resets -- must therefore target the RECT ids
    (anim-state-rect-*), never the group ids (anim-state-box-*). Mirrors
    _array_ops_html, which already targets its rect_ids for exactly this reason.
    """
    md = course(
        '<!-- topic: tlb -->\n### The TLB\n\n'
        '```animate\npattern: state-machine\nstates:\n  - A\n  - B\n  - C\n'
        'transitions:\n  - A -> B: go1\n  - B -> C: go2\n```\n\n'
        '```quiz\nq: q\n- [ ] a\n- [x] b\n- [ ] c\nwhy: because\n```\n\n'
        '```glossary\nTLB: definition\n```\n'
    )
    rendered = render_course(md)
    assert rendered.errors == []
    # The rect carries the idle fill as its own attribute (array-ops's convention),
    # so it renders correctly before JS runs and under reduced-motion/print.
    assert 'fill="var(--anim-state-idle)"' in rendered.html_body
    assert 'id="anim-state-rect-' in rendered.html_body
    match = re.search(
        r'<script type="application/json" class="anim__timeline"[^>]*>(.*?)</script>',
        rendered.html_body,
        re.DOTALL,
    )
    steps = json.loads(match.group(1))["steps"]
    fill_steps = [s for s in steps if "fill" in (s.get("props") or {})]
    assert fill_steps, "no fill-animating steps found"
    for step in fill_steps:
        for target in step["targets"]:
            assert target.startswith("#anim-state-rect-"), (
                f"fill step targets {target!r}; animating fill on the <g> group is "
                "overridden by the rect's own fill and never renders"
            )


def test_state_machine_draws_no_arrow_for_an_unauthored_state_pair():
    """Only AUTHORED transitions are ever drawn as edges (design spec's standing
    rule, and this renderer's own docstring). A chain of three states with only
    ONE authored transition must draw exactly one arrow -- not one per adjacent
    pair of states.
    """
    md = course(
        '<!-- topic: tlb -->\n### The TLB\n\n'
        '```animate\npattern: state-machine\nstates:\n  - A\n  - B\n  - C\n'
        'transitions:\n  - A -> B: go\n```\n\n'
        '```quiz\nq: q\n- [ ] a\n- [x] b\n- [ ] c\nwhy: because\n```\n\n'
        '```glossary\nTLB: definition\n```\n'
    )
    rendered = render_course(md)
    assert rendered.errors == []
    # Three boxes are still drawn (states are structure), but only the one
    # authored A -> B edge gets an arrow; B -> C was never authored.
    assert rendered.html_body.count('class="anim__state-box"') == 3
    assert rendered.html_body.count('class="anim__state-arrow"') == 1


def test_state_machine_marker_and_arrow_paint_before_the_boxes():
    """The traveling marker and every forward arrow sit at the boxes' own
    vertical center (a real flowchart line entering/exiting each box at its
    edge) -- but they must be emitted BEFORE the boxes in the SVG's document
    order, so a box's opaque rect visually covers the marker/arrow-end
    whenever either is at/behind it (SVG paints later elements on top). A
    marker painted AFTER the boxes would float in front of the diagram's
    structure and could obscure a box's own text.
    """
    md = course(
        '<!-- topic: tlb -->\n### The TLB\n\n'
        '```animate\npattern: state-machine\nstates:\n  - A\n  - B\n'
        'transitions:\n  - A -> B: go\n```\n\n'
        '```quiz\nq: q\n- [ ] a\n- [x] b\n- [ ] c\nwhy: because\n```\n\n'
        '```glossary\nTLB: definition\n```\n'
    )
    rendered = render_course(md)
    assert rendered.errors == []
    body = rendered.html_body
    marker_index = body.index('class="anim__state-marker"')
    arrow_index = body.index('class="anim__state-arrow"')
    first_box_index = body.index('class="anim__state-box"')
    assert arrow_index < first_box_index
    assert marker_index < first_box_index
    # The marker and the arrow travel/sit at the SAME y as the box's own
    # vertical center -- not a separate lane -- since the boxes painting on
    # top is what keeps them from visually crossing the box's text.
    box_match = re.search(r'<rect id="anim-state-rect-\S+" x="\S+" y="(\S+)"', body)
    box_center_y = float(box_match.group(1)) + _STATE_BOX_HEIGHT / 2
    marker_match = re.search(r'class="anim__state-marker"[^>]*cy="(\S+)"', body)
    assert float(marker_match.group(1)) == box_center_y
    arrow_match = re.search(r'class="anim__state-arrow"[^>]*y1="(\S+)"', body)
    assert float(arrow_match.group(1)) == box_center_y


def test_state_machine_labels_paint_after_the_boxes_with_a_background_chip():
    """Unlike the marker/arrow, a transition's action label is authored prose,
    not diagram structure -- it must stay fully legible even where it
    overhangs a box's edge, so it (and its background chip) paint AFTER the
    boxes, on top of everything, and carry their own background rect sized
    from the label text so real glyphs never spill outside it.
    """
    md = course(
        '<!-- topic: tlb -->\n### The TLB\n\n'
        '```animate\npattern: state-machine\nstates:\n  - A\n  - B\n'
        'transitions:\n  - A -> B: a moderately long action description\n```\n\n'
        '```quiz\nq: q\n- [ ] a\n- [x] b\n- [ ] c\nwhy: because\n```\n\n'
        '```glossary\nTLB: definition\n```\n'
    )
    rendered = render_course(md)
    assert rendered.errors == []
    body = rendered.html_body
    last_box_index = body.rindex('class="anim__state-box"')
    label_group_index = body.index('class="anim__state-transition-label-group"')
    assert label_group_index > last_box_index
    bg_match = re.search(
        r'<rect class="anim__state-transition-label-bg" x="(\S+)" y="\S+" width="(\S+)"',
        body,
    )
    assert bg_match, "no label background chip found"
    chip_width = float(bg_match.group(2))
    # The chip must be wide enough to plausibly contain the actual authored
    # text -- a hard floor well below any reasonable per-character estimate,
    # not a tight bound on the exact formula (which is free to tune).
    assert chip_width > len("a moderately long action description") * 4


def test_state_machine_back_edge_marker_follows_the_drawn_arc_not_a_straight_line():
    """Bug: the back-edge's marker travel step used a plain straight-line tween
    through the lane, ignoring the curved arc actually drawn for it -- the
    marker cut straight across underneath the boxes instead of visibly
    following the dashed arc above them. The back-edge's own path-segment step
    must carry via1/via2 control points matching the drawn <path>'s own cubic
    Bezier control points exactly, so the traveling marker traces that same
    curve. No other path-segment step (a forward transition) has via1/via2.
    """
    md = course(
        '<!-- topic: tlb -->\n### The TLB\n\n'
        '```animate\npattern: state-machine\nstates:\n  - A\n  - B\n'
        'transitions:\n  - A -> B: go\n  - B -> A: reset\n```\n\n'
        '```quiz\nq: q\n- [ ] a\n- [x] b\n- [ ] c\nwhy: because\n```\n\n'
        '```glossary\nTLB: definition\n```\n'
    )
    rendered = render_course(md)
    assert rendered.errors == []
    back_edge_match = re.search(
        r'<path class="anim__state-arrow anim__state-arrow--back" '
        r'd="M (\S+) (\S+) C (\S+) (\S+), (\S+) (\S+), (\S+) (\S+)"',
        rendered.html_body,
    )
    assert back_edge_match, "no back-edge <path> found"
    x_from, y_top, cx1, cy1, cx2, cy2, x_to, y_top2 = (float(g) for g in back_edge_match.groups())
    match = re.search(
        r'<script type="application/json" class="anim__timeline"[^>]*>(.*?)</script>',
        rendered.html_body,
        re.DOTALL,
    )
    steps = json.loads(match.group(1))["steps"]
    marker_travels = [s for s in steps if s.get("kind") == "path-segment"]
    assert len(marker_travels) == 2
    forward_step, back_step = marker_travels
    assert "via1" not in forward_step
    assert "via2" not in forward_step
    assert back_step["via1"] == [cx1, cy1]
    assert back_step["via2"] == [cx2, cy2]
    assert back_step["from"] == [x_from, y_top]
    assert back_step["to"] == [x_to, y_top2]


def test_state_toggle_renders_before_and_after_with_a_timeline_island():
    md = course(
        '<!-- topic: tlb -->\n### The TLB\n\n'
        '```animate\npattern: state-toggle\nbefore: Shared\nafter: Modified\n```\n\n'
        '```quiz\nq: q\n- [ ] a\n- [x] b\n- [ ] c\nwhy: because\n```\n\n'
        '```glossary\nTLB: definition\n```\n'
    )
    rendered = render_course(md)
    assert rendered.errors == []
    assert re.search(
        r'<div class="anim__state anim__state--before" id="[^"]+">'
        r'<span class="anim__state-label">Before</span>Shared</div>',
        rendered.html_body,
    )
    assert re.search(
        r'<div class="anim__state anim__state--after" id="[^"]+">'
        r'<span class="anim__state-label">After</span>Modified</div>',
        rendered.html_body,
    )
    match = re.search(
        r'<script type="application/json" class="anim__timeline"[^>]*>(.*?)</script>',
        rendered.html_body,
        re.DOTALL,
    )
    assert match, "no anim__timeline data island found"
    timeline = json.loads(match.group(1))
    assert timeline["loop"] is True
    assert len(timeline["steps"]) == 4


def test_a_broken_animate_block_becomes_an_error_not_a_crash():
    md = course(
        '<!-- topic: tlb -->\n### The TLB\n\n'
        '```animate\npattern: nonsense\n```\n\n'
        '```quiz\nq: q\n- [ ] a\n- [x] b\n- [ ] c\nwhy: because\n```\n\n'
        '```glossary\nTLB: definition\n```\n'
    )
    rendered = render_course(md)
    assert any("animate" in e for e in rendered.errors)


def test_a_topic_with_a_mermaid_diagram_is_not_missing_a_visual():
    rendered = render_course(course(MODULE))  # MODULE already has a mermaid block for 'tlb'
    assert "tlb" not in rendered.topics_missing_visual


def test_a_topic_with_no_visual_and_no_justification_is_flagged():
    md = course(
        '<!-- topic: bare -->\n### Bare topic\n\nJust prose, no visual at all.\n\n'
        '```quiz\nq: q\n- [ ] a\n- [x] b\n- [ ] c\nwhy: because\n```\n'
    )
    rendered = render_course(md)
    assert rendered.topics_missing_visual == ["bare"]


def test_a_topic_with_an_inline_svg_is_not_missing_a_visual():
    md = course(
        '<!-- topic: bare -->\n### Bare topic\n\n<svg><circle r="1"/></svg>\n\n'
        '```quiz\nq: q\n- [ ] a\n- [x] b\n- [ ] c\nwhy: because\n```\n'
    )
    rendered = render_course(md)
    assert rendered.topics_missing_visual == []


def test_a_no_visual_comment_justifies_skipping_the_visual():
    md = course(
        '<!-- topic: bare -->\n### Bare topic\n\n'
        '<!-- no-visual: purely definitional, nothing spatial to draw -->\n\n'
        'Just prose.\n\n```quiz\nq: q\n- [ ] a\n- [x] b\n- [ ] c\nwhy: because\n```\n'
    )
    rendered = render_course(md)
    assert rendered.topics_missing_visual == []


def test_a_no_quiz_comment_justifies_a_topic_with_zero_quizzes():
    md = course(
        '<!-- topic: goals -->\n### Course Goals\n\n'
        'This course covers the TLB and thrashing.\n\n'
        '<!-- no-quiz: brief administrative topic, nothing to check -->\n'
    )
    rendered = render_course(md)
    assert rendered.quizzes_per_topic["goals"] == 0
    assert "goals" not in rendered.topics_missing_quiz


def test_a_topic_with_zero_quizzes_and_no_justification_is_still_missing():
    md = course(
        '<!-- topic: goals -->\n### Course Goals\n\nJust prose, no quiz, no comment.\n'
    )
    rendered = render_course(md)
    assert "goals" in rendered.topics_missing_quiz


def test_a_real_quiz_is_never_downgraded_by_a_stray_no_quiz_comment():
    md = course(
        '<!-- topic: goals -->\n### Course Goals\n\n'
        '<!-- no-quiz: irrelevant leftover comment -->\n\n'
        '```quiz\nq: q\n- [ ] a\n- [x] b\n- [ ] c\nwhy: because\n```\n'
    )
    rendered = render_course(md)
    assert rendered.quizzes_per_topic["goals"] == 1
    assert "goals" not in rendered.topics_missing_quiz


def test_a_figure_or_animate_block_also_counts_as_a_visual():
    md = course(
        '<!-- topic: bare -->\n### Bare topic\n\n'
        '```figure\nsource: week1.pdf#1\ncaption: c\n```\n\n'
        '```quiz\nq: q\n- [ ] a\n- [x] b\n- [ ] c\nwhy: because\n```\n'
    )
    rendered = render_course(md)
    assert rendered.topics_missing_visual == []


def test_parse_animate_path_trace():
    anim = parse_animate(
        "pattern: path-trace\npoints:\n  - 0, 10\n  - 5, 2\n  - 10, 8\n  - 15, 0\n"
        "caption: Gradient descent converging toward the minimum"
    )
    assert anim == Animate(
        pattern="path-trace",
        points=[(0.0, 10.0), (5.0, 2.0), (10.0, 8.0), (15.0, 0.0)],
        caption="Gradient descent converging toward the minimum",
    )


def test_parse_animate_path_trace_rejects_one_point():
    with pytest.raises(AnimateError, match="at least 2 points"):
        parse_animate("pattern: path-trace\npoints:\n  - 0, 0\ncaption: c")


def test_parse_animate_path_trace_rejects_a_malformed_point():
    with pytest.raises(AnimateError, match=r"invalid path-trace point: 'not-a-point'"):
        parse_animate(
            "pattern: path-trace\npoints:\n  - 0, 0\n  - not-a-point\ncaption: c"
        )


def test_parse_animate_path_trace_rejects_missing_caption():
    with pytest.raises(AnimateError, match="path-trace needs 'caption:'"):
        parse_animate("pattern: path-trace\npoints:\n  - 0, 0\n  - 1, 1")


def test_parse_animate_path_trace_rejects_steps():
    with pytest.raises(AnimateError, match="path-trace does not use 'before:'/'after:'"):
        parse_animate(
            "pattern: path-trace\npoints:\n  - 0, 0\n  - 1, 1\ncaption: c\nbefore: x"
        )


def test_array_ops_renders_bars_and_a_timeline_island():
    md = course(
        '<!-- topic: tlb -->\n### The TLB\n\n'
        '```animate\npattern: array-ops\narray:\n  - 5\n  - 3\n  - 8\n  - 1\n'
        'ops:\n  - compare 0 1\n  - swap 0 1\n  - highlight 2\n```\n\n'
        '```quiz\nq: q\n- [ ] a\n- [x] b\n- [ ] c\nwhy: because\n```\n\n'
        '```glossary\nTLB: definition\n```\n'
    )
    rendered = render_course(md)
    assert rendered.errors == []
    assert rendered.html_body.count('<g class="anim__array-bar"') == 4
    assert rendered.html_body.count('<text class="anim__array-label"') == 4
    assert '>5<' in rendered.html_body
    assert '>3<' in rendered.html_body
    assert '>8<' in rendered.html_body
    assert '>1<' in rendered.html_body
    assert 'class="anim__array-legend"' in rendered.html_body
    assert 'class="anim__caption"' in rendered.html_body
    assert 'transform-box: fill-box; transform-origin: center' in rendered.html_body
    assert 'transform="translate(' not in rendered.html_body  # the SVG-transform-attribute gotcha
    assert '<ol class="anim__array-steps-static">' in rendered.html_body
    assert '<li>compare index 0 and 1</li>' in rendered.html_body
    assert '<li>swap index 0 and 1</li>' in rendered.html_body
    assert '<li>highlight index 2</li>' in rendered.html_body

    match = re.search(
        r'<script type="application/json" class="anim__timeline"[^>]*>(.*?)</script>',
        rendered.html_body,
        re.DOTALL,
    )
    assert match, "no anim__timeline data island found"
    timeline = json.loads(match.group(1))
    assert timeline["loop"] is True
    kinds = [step.get("kind", "add") for step in timeline["steps"]]
    assert kinds[-1] == "set" and kinds[-2] == "set"  # the loop-reset pair, last in the list
    swap_steps = [s for s in timeline["steps"] if s.get("caption", "").startswith("swapping")]
    assert len(swap_steps) >= 1

    # Fill-only steps carry no "ease": their keyframes are var(--anim-array-*)
    # references, which anime.js cannot interpolate as colors (its classifier only
    # accepts #hex/rgb()/rgba()/hsl()/hsla()), so the swap is an instant cut and an
    # ease would only advertise a smoothness that never happens. Steps that animate
    # a real numeric property (scale/translateX) still ease.
    fill_only = [
        s for s in timeline["steps"]
        if s.get("kind", "add") == "add" and set(s["props"]) == {"fill"}
    ]
    assert len(fill_only) == 3  # one per op: compare, swap, highlight
    assert all("ease" not in s for s in fill_only), fill_only
    motion_steps = [
        s for s in timeline["steps"]
        if s.get("kind", "add") == "add" and s["props"] and "fill" not in s["props"]
    ]
    assert motion_steps and all("ease" in s for s in motion_steps)


def test_array_ops_swap_displacement_lands_each_bar_in_the_other_bars_slot():
    """A swap's translateX must be each bar's ABSOLUTE displacement from its own
    home slot -- (slot_of_bar[i] - i) * slot_width computed independently per bar,
    never `delta` and `-delta`. The mirrored form is only right when both bars
    start in their home slots; after any earlier swap has already displaced one of
    them it sends that bar to the wrong x. `swap 0 2` then `swap 0 1` exercises
    exactly that: by the second swap, bar 1 sits in slot 0 and bar 0 sits in slot
    2, so the two bars' displacements are NOT negatives of each other.
    """
    md = course(
        '<!-- topic: tlb -->\n### The TLB\n\n'
        '```animate\npattern: array-ops\narray:\n  - 5\n  - 3\n  - 8\n  - 1\n'
        'ops:\n  - swap 0 2\n  - swap 0 1\n```\n\n'
        '```quiz\nq: q\n- [ ] a\n- [x] b\n- [ ] c\nwhy: because\n```\n\n'
        '```glossary\nTLB: definition\n```\n'
    )
    rendered = render_course(md)
    assert rendered.errors == []
    match = re.search(
        r'<script type="application/json" class="anim__timeline"[^>]*>(.*?)</script>',
        rendered.html_body,
        re.DOTALL,
    )
    assert match
    timeline = json.loads(match.group(1))

    # Recover each bar's rendered home x from its <rect> so the expected
    # displacements are derived from the real emitted geometry, not a constant
    # duplicated from the implementation.
    home_x = {
        int(m.group(1)): float(m.group(2))
        for m in re.finditer(r'<rect id="anim-rect-\d+-(\d)" x="([\d.]+)"', rendered.html_body)
    }
    assert len(home_x) == 4

    # translateX steps, in emission order, keyed by the bar id they target.
    moves = [
        (int(re.search(r"-(\d)$", s["targets"][0]).group(1)), s["props"]["translateX"])
        for s in timeline["steps"]
        if s.get("kind") != "set" and "translateX" in s.get("props", {})
    ]
    # swap 0 2 moves bars 0 and 2; swap 0 1 then moves bars 0 and 1.
    assert [bar for bar, _ in moves] == [0, 2, 0, 1]

    # After both swaps: slot_of_bar == [1, 0, 2 -> see below]. Walk it explicitly.
    slot_of_bar = [0, 1, 2, 3]
    slot_of_bar[0], slot_of_bar[2] = slot_of_bar[2], slot_of_bar[0]
    slot_of_bar[0], slot_of_bar[1] = slot_of_bar[1], slot_of_bar[0]
    assert slot_of_bar == [1, 2, 0, 3]

    # Each move must place its bar exactly on the home x of the slot it now occupies.
    final = {}
    for bar, dx in moves:
        final[bar] = home_x[bar] + dx
    for bar in (0, 1, 2):
        assert final[bar] == home_x[slot_of_bar[bar]], (
            f"bar {bar} landed at {final[bar]}, slot {slot_of_bar[bar]} is at "
            f"{home_x[slot_of_bar[bar]]}"
        )
    # The second swap's two deltas are genuinely NOT mirror images -- this is the
    # case the naive `delta`/`-delta` pair gets wrong.
    assert moves[2][1] != -moves[3][1]


def test_path_trace_renders_gridlines_trail_and_a_timeline_island():
    md = course(
        '<!-- topic: tlb -->\n### The TLB\n\n'
        '```animate\npattern: path-trace\npoints:\n  - 0, 10\n  - 5, 2\n  - 10, 8\n  - 15, 0\n'
        'caption: TLB hit rate rising\n```\n\n'
        '```quiz\nq: q\n- [ ] a\n- [x] b\n- [ ] c\nwhy: because\n```\n\n'
        '```glossary\nTLB: definition\n```\n'
    )
    rendered = render_course(md)
    assert rendered.errors == []
    assert '<line class="anim__path-axis"' in rendered.html_body
    assert '<text class="anim__path-tick"' in rendered.html_body
    assert '<polyline class="anim__path-line"' in rendered.html_body
    assert '<path class="anim__path-trail"' in rendered.html_body
    assert '<circle class="anim__path-marker"' in rendered.html_body
    # Both classes: .anim__caption is the live-narration hook, .anim__path-caption
    # marks this caption as the author's own text so the print/reduced-motion rules
    # (scoped to .anim--array-ops) leave it visible.
    assert 'class="anim__caption anim__path-caption"' in rendered.html_body
    assert '<ol class="anim__path-steps-static">' in rendered.html_body
    assert '<li>from (0, 10) to (5, 2)</li>' in rendered.html_body
    assert '<li>from (5, 2) to (10, 8)</li>' in rendered.html_body
    assert '<li>from (10, 8) to (15, 0)</li>' in rendered.html_body

    match = re.search(
        r'<script type="application/json" class="anim__timeline"[^>]*>(.*?)</script>',
        rendered.html_body,
        re.DOTALL,
    )
    assert match, "no anim__timeline data island found"
    timeline = json.loads(match.group(1))
    assert timeline["loop"] is True
    # One path-segment step per segment (0->5->10->15), plus the two reset steps
    # that snap the marker/trail back to the start before the loop restarts.
    segments = [s for s in timeline["steps"] if s["kind"] == "path-segment"]
    assert len(segments) == 3
    assert [s["kind"] for s in timeline["steps"][3:]] == ["set", "set-attr"]
    assert segments[0]["caption"] == "Moving from (0, 10) to (5, 2)"

    # Constant visual speed: each segment's duration is proportional to its real
    # Euclidean length. (0,10)->(5,2) spans hypot(5, 8) = 9.434 units while
    # (5,2)->(10,8) spans only hypot(5, 6) = 7.810, so the FIRST segment is the
    # longer one and must get the longer duration.
    durations = [s["duration"] for s in segments]
    assert durations[0] > durations[1]
    assert durations[0] == durations[2]  # (0,10)->(5,2) and (10,8)->(15,0) are congruent
    # Proportionality, not merely ordering: ms-per-unit is constant across segments.
    ratios = [d / math.hypot(s["to"][0] - s["from"][0], s["to"][1] - s["from"][1])
              for d, s in zip(durations, segments)]
    assert all(abs(r - ratios[0]) < 1.0 for r in ratios)


def test_a_broken_array_ops_block_becomes_an_error_not_a_crash():
    md = course(
        '<!-- topic: tlb -->\n### The TLB\n\n'
        '```animate\npattern: array-ops\narray:\n  - 1\nops:\n  - highlight 0\n```\n\n'
        '```quiz\nq: q\n- [ ] a\n- [x] b\n- [ ] c\nwhy: because\n```\n\n'
        '```glossary\nTLB: definition\n```\n'
    )
    rendered = render_course(md)
    assert any("array-ops" in e for e in rendered.errors)


def test_a_broken_path_trace_block_becomes_an_error_not_a_crash():
    md = course(
        '<!-- topic: tlb -->\n### The TLB\n\n'
        '```animate\npattern: path-trace\npoints:\n  - 0, 0\ncaption: c\n```\n\n'
        '```quiz\nq: q\n- [ ] a\n- [x] b\n- [ ] c\nwhy: because\n```\n\n'
        '```glossary\nTLB: definition\n```\n'
    )
    rendered = render_course(md)
    assert any("path-trace" in e for e in rendered.errors)


def test_an_array_ops_block_also_counts_as_a_visual():
    md = course(
        '<!-- topic: bare -->\n### Bare topic\n\n'
        '```animate\npattern: array-ops\narray:\n  - 1\n  - 2\nops:\n  - highlight 0\n```\n\n'
        '```quiz\nq: q\n- [ ] a\n- [x] b\n- [ ] c\nwhy: because\n```\n'
    )
    rendered = render_course(md)
    assert rendered.topics_missing_visual == []


def test_a_path_trace_block_also_counts_as_a_visual():
    md = course(
        '<!-- topic: bare -->\n### Bare topic\n\n'
        '```animate\npattern: path-trace\npoints:\n  - 0, 0\n  - 1, 1\ncaption: c\n```\n\n'
        '```quiz\nq: q\n- [ ] a\n- [x] b\n- [ ] c\nwhy: because\n```\n'
    )
    rendered = render_course(md)
    assert rendered.topics_missing_visual == []
