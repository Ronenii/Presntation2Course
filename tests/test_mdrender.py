import json
import math
import re

import pytest

from p2c.mdrender import (
    _LAYER_GAP,
    _LAYER_HEIGHT,
    _LAYER_TOP_MARGIN,
    _LAYER_WIDTH,
    _PIPE_BOX_HEIGHT,
    _PIPE_BOX_WIDTH,
    _PIPE_GAP,
    _PIPE_TOP_MARGIN,
    _STATE_BOX_HEIGHT,
    _STATE_LABEL_CHAR_WIDTH,
    _STATE_LABEL_CHIP_PAD_X,
    _XFORM_BOX_HEIGHT,
    _XFORM_BOX_WIDTH,
    _XFORM_RUNG_GAP,
    _XFORM_TOP_MARGIN,
    _state_machine_html,
    Animate,
    AnimateError,
    FigureError,
    _animate_html,
    _build_up_html,
    _compare_html,
    _layer_stack_html,
    _pipeline_html,
    _split_merge_html,
    _transform_html,
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


def test_removed_patterns_are_rejected():
    for pattern in ("array-ops", "path-trace"):
        with pytest.raises(AnimateError, match="animate pattern must be"):
            parse_animate(
                f"pattern: {pattern}\narray:\n  - 1\n  - 2\nops:\n  - swap 0 1\n"
            )


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


def test_parse_animate_state_machine_rejects_a_stray_before_key():
    with pytest.raises(
        AnimateError,
        match="state-machine does not use 'before:'/'after:'/'caption:'",
    ):
        parse_animate(
            "pattern: state-machine\nstates:\n  - A\n  - B\n"
            "transitions:\n  - A -> B: go\nbefore: something\n"
        )


def test_a_removed_patterns_key_is_no_longer_a_list_header():
    """`array:`/`ops:`/`points:` died with array-ops and path-trace, so they are
    not list headers any more. A block still carrying one is rejected as an
    unrecognised line rather than by a pattern's cross-key guard -- different
    message, same outcome: it never parses and never gets silently discarded.
    """
    with pytest.raises(AnimateError, match="unrecognised line in animate block"):
        parse_animate(
            "pattern: state-machine\nstates:\n  - A\n  - B\n"
            "transitions:\n  - A -> B: go\narray:\n  - 1\n"
        )


def test_parse_animate_state_machine_rejects_a_stray_stages_key():
    """Cross-key guards were extended for the three new patterns' keys
    (stages/layers/steps/direction/from/to) when they were added, but every
    PRE-EXISTING pattern's guard was written against the old key set and so
    silently accepted -- and discarded -- these six keys. This asserts the
    fix: state-machine now rejects a stray `stages:` list exactly like it
    already rejects `array:`.
    """
    with pytest.raises(AnimateError, match="state-machine does not use"):
        parse_animate(
            "pattern: state-machine\nstates:\n  - A\n  - B\n"
            "transitions:\n  - A -> B: go\nstages:\n  - X: y\n"
        )


def test_parse_animate_rejects_a_state_toggle_missing_after():
    with pytest.raises(AnimateError, match="needs both 'before:' and 'after:'"):
        parse_animate("pattern: state-toggle\nbefore: only before")


def test_parse_animate_state_toggle_rejects_a_stray_layers_key():
    with pytest.raises(AnimateError, match="state-toggle does not use"):
        parse_animate(
            "pattern: state-toggle\nbefore: Shared\nafter: Modified\n"
            "layers:\n  - X: y\n"
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
            "layers:\n  - X: adds x\n"
        )


def test_pipeline_rejects_caption():
    """Settled convention: a pattern that does not RENDER a caption REJECTS it.
    path-trace was the only pattern that ever rendered one, and it is gone, so
    no surviving pattern accepts `caption:`. pipeline never renders
    anim.caption (see _pipeline_html), so it must reject the key rather than
    silently accept-and-discard it.
    """
    with pytest.raises(AnimateError, match="does not use"):
        parse_animate(
            "pattern: pipeline\nstages:\n  - A: does a\n  - B: does b\n"
            "caption: some caption\n"
        )


def _pipeline_anim():
    return parse_animate(
        "pattern: pipeline\n"
        "stages:\n"
        "  - Raw image: single RGB frame\n"
        "  - Encoder: compresses into a feature map\n"
        "  - Depth map: one distance per pixel\n"
    )


def test_pipeline_html_pins_ltr_and_lists_every_stage_statically():
    out = _pipeline_html(_pipeline_anim(), "ANIMTOKEN3")
    assert 'dir="ltr"' in out
    assert 'class="anim anim--pipeline"' in out
    # Static fallback carries every stage, so print/reduced-motion shows them all.
    for name in ("Raw image", "Encoder", "Depth map"):
        assert name in out
    assert out.count("<li>") == 3


def test_pipeline_html_draws_connectors_with_dashoffset():
    out = _pipeline_html(_pipeline_anim(), "ANIMTOKEN3")
    data = json.loads(
        re.search(
            r'<script type="application/json" class="anim__timeline">(.*?)</script>',
            out, re.S,
        ).group(1)
    )
    dash_steps = [
        s for s in data["steps"]
        if "strokeDashoffset" in (s.get("props") or {}) and s.get("kind") != "set"
    ]
    # One drawing animation per connector: N stages => N-1 connectors.
    assert len(dash_steps) == 2


def test_pipeline_timeline_resets_every_animated_property_for_the_loop():
    out = _pipeline_html(_pipeline_anim(), "ANIMTOKEN3")
    data = json.loads(
        re.search(
            r'<script type="application/json" class="anim__timeline">(.*?)</script>',
            out, re.S,
        ).group(1)
    )
    assert data["loop"] is True
    animated = {
        prop
        for step in data["steps"] if step.get("kind") != "set"
        for prop in (step.get("props") or {})
    }
    reset = {
        prop
        for step in data["steps"] if step.get("kind") == "set"
        for prop in (step.get("props") or {})
    }
    # Gotcha 2: absolute values compound across laps unless every one is reset.
    assert animated <= reset


def test_pipeline_layout_constants_are_divisible_by_four():
    for value in (_PIPE_BOX_WIDTH, _PIPE_BOX_HEIGHT, _PIPE_GAP, _PIPE_TOP_MARGIN):
        assert value % 4 == 0


def test_pipeline_box_width_grows_to_fit_a_long_stage_description():
    """Neither _PIPE_BOX_WIDTH nor anything else in _pipeline_html sized the box
    from the stage's own text: a fixed 140px box against real course prose (the
    doc's own example, 'single RGB frame, no depth information', estimates to
    ~274px at _STATE_LABEL_CHAR_WIDTH) overflows into the neighbouring box and
    across the connector. This asserts the fix reuses _state_machine_html's own
    "estimate width from character count" approach: every rendered box is at
    least as wide as its own longest line (name or change) needs.
    """
    long_change = "single RGB frame, no depth information"
    anim = parse_animate(
        "pattern: pipeline\nstages:\n"
        f"  - Raw image: {long_change}\n  - Depth map: one distance per pixel\n"
    )
    out = _pipeline_html(anim, "ANIMTOKEN3")
    estimated_text_width = (
        len(long_change) * _STATE_LABEL_CHAR_WIDTH + 2 * _STATE_LABEL_CHIP_PAD_X
    )
    widths = [
        float(w)
        for w in re.findall(r'<rect class="anim__pipe-box"[^>]*width="([\d.]+)"', out)
    ]
    assert widths, "expected at least one anim__pipe-box rect"
    assert all(w >= estimated_text_width for w in widths), (
        widths, estimated_text_width,
    )


def test_layer_stack_parses_layers_bottom_up_and_defaults_direction_up():
    anim = parse_animate(
        "pattern: layer-stack\n"
        "layers:\n"
        "  - Pixels: raw sensor values\n"
        "  - Edges: local intensity changes\n"
        "  - Objects: assembled shapes\n"
    )
    assert anim.pattern == "layer-stack"
    assert anim.layers[0] == ("Pixels", "raw sensor values")
    assert anim.direction == "up"


def test_layer_stack_accepts_explicit_down_direction():
    anim = parse_animate(
        "pattern: layer-stack\ndirection: down\n"
        "layers:\n  - Top: starts here\n  - Bottom: ends here\n"
    )
    assert anim.direction == "down"


def test_layer_stack_rejects_an_unknown_direction():
    with pytest.raises(AnimateError, match="direction"):
        parse_animate(
            "pattern: layer-stack\ndirection: sideways\n"
            "layers:\n  - A: does a\n  - B: does b\n"
        )


def test_layer_stack_rejects_bad_layer_counts():
    with pytest.raises(AnimateError, match="at least 2 layers"):
        parse_animate("pattern: layer-stack\nlayers:\n  - Only: one\n")
    body = "pattern: layer-stack\nlayers:\n" + "".join(
        f"  - L{i}: does {i}\n" for i in range(7)
    )
    with pytest.raises(AnimateError, match="at most 6 layers"):
        parse_animate(body)


def test_layer_stack_rejects_a_stray_from_line():
    with pytest.raises(AnimateError, match="does not use"):
        parse_animate(
            "pattern: layer-stack\nfrom: 0, 0\n"
            "layers:\n  - A: does a\n  - B: does b\n"
        )


def test_layer_stack_rejects_caption():
    with pytest.raises(AnimateError, match="does not use"):
        parse_animate(
            "pattern: layer-stack\nlayers:\n  - A: does a\n  - B: does b\n"
            "caption: some caption\n"
        )


def test_layer_stack_html_is_ltr_and_static_lists_every_layer():
    anim = parse_animate(
        "pattern: layer-stack\n"
        "layers:\n  - Pixels: raw values\n  - Edges: gradients\n  - Objects: shapes\n"
    )
    out = _layer_stack_html(anim, "ANIMTOKEN4")
    assert 'dir="ltr"' in out
    assert out.count("<li>") == 3
    assert "Pixels" in out and "Objects" in out


def test_layer_stack_timeline_resets_animated_properties():
    anim = parse_animate(
        "pattern: layer-stack\n"
        "layers:\n  - Pixels: raw values\n  - Edges: gradients\n"
    )
    out = _layer_stack_html(anim, "ANIMTOKEN4")
    data = json.loads(
        re.search(
            r'<script type="application/json" class="anim__timeline">(.*?)</script>',
            out, re.S,
        ).group(1)
    )
    animated = {
        p for s in data["steps"] if s.get("kind") != "set" for p in (s.get("props") or {})
    }
    reset = {
        p for s in data["steps"] if s.get("kind") == "set" for p in (s.get("props") or {})
    }
    assert animated <= reset


def test_layer_stack_constants_are_divisible_by_four():
    for value in (_LAYER_WIDTH, _LAYER_HEIGHT, _LAYER_GAP, _LAYER_TOP_MARGIN):
        assert value % 4 == 0


def test_transform_parses_endpoints_and_steps():
    anim = parse_animate(
        "pattern: transform\n"
        "from: Disparity map\n"
        "to: Metric depth map\n"
        "steps:\n"
        "  - Invert each disparity value\n"
        "  - Scale by the focal-length constant\n"
    )
    assert anim.from_entity == "Disparity map"
    assert anim.to_entity == "Metric depth map"
    assert anim.steps == [
        "Invert each disparity value",
        "Scale by the focal-length constant",
    ]


def test_transform_requires_both_endpoints():
    with pytest.raises(AnimateError, match="needs both 'from:' and 'to:'"):
        parse_animate("pattern: transform\nfrom: Only a start\nsteps:\n  - Does a thing\n")


def test_transform_rejects_bad_step_counts():
    with pytest.raises(AnimateError, match="at least 1 step"):
        parse_animate("pattern: transform\nfrom: A\nto: B\n")
    body = "pattern: transform\nfrom: A\nto: B\nsteps:\n" + "".join(
        f"  - Step {i}\n" for i in range(5)
    )
    with pytest.raises(AnimateError, match="at most 4 steps"):
        parse_animate(body)


def test_transform_rejects_a_stray_direction_line():
    with pytest.raises(AnimateError, match="does not use"):
        parse_animate(
            "pattern: transform\nfrom: A\nto: B\ndirection: up\n"
            "steps:\n  - Does a thing\n"
        )


def test_transform_rejects_caption():
    with pytest.raises(AnimateError, match="does not use"):
        parse_animate(
            "pattern: transform\nfrom: A\nto: B\nsteps:\n  - Does a thing\n"
            "caption: some caption\n"
        )


def test_transform_html_is_ltr_and_shows_both_endpoints_statically():
    anim = parse_animate(
        "pattern: transform\nfrom: Disparity map\nto: Metric depth map\n"
        "steps:\n  - Invert each value\n"
    )
    out = _transform_html(anim, "ANIMTOKEN5")
    assert 'dir="ltr"' in out
    assert "Disparity map" in out and "Metric depth map" in out
    assert "Invert each value" in out


@pytest.mark.parametrize(
    "html_out,svg_class",
    [
        (
            _pipeline_html(_pipeline_anim(), "ANIMTOKEN3"),
            "anim__pipeline",
        ),
        (
            _layer_stack_html(
                parse_animate(
                    "pattern: layer-stack\nlayers:\n"
                    "  - Pixels: raw sensor values\n  - Edges: local intensity changes\n"
                ),
                "ANIMTOKEN4",
            ),
            "anim__layer-stack",
        ),
        (
            _transform_html(
                parse_animate(
                    "pattern: transform\nfrom: A\nto: B\nsteps:\n  - Change it\n"
                ),
                "ANIMTOKEN5",
            ),
            "anim__transform",
        ),
    ],
)
def test_new_pattern_svgs_carry_explicit_width_height_matching_their_viewbox(html_out, svg_class):
    """.anim__pipeline/.anim__layer-stack/.anim__transform's CSS rule caps growth
    with `max-width: 100%` rather than forcing `width: 100%` (see
    test_new_animate_pattern_svgs_scroll_instead_of_shrinking_text in
    test_assets.py) -- but that only keeps a wide diagram legible if the SVG's
    own natural size is its viewBox, not the browser's 300x150 default for an
    <svg> with no width/height. Each renderer must therefore emit explicit
    width/height presentation attributes equal to its viewBox, one CSS px per
    viewBox unit, so "natural size" means "big enough to read".
    """
    svg_open = re.search(rf'<svg class="{svg_class}"[^>]*>', html_out).group(0)
    view_box = re.search(r'viewBox="0 0 ([\d.]+) ([\d.]+)"', svg_open)
    width = re.search(r'width="([\d.]+)"', svg_open)
    height = re.search(r'height="([\d.]+)"', svg_open)
    assert view_box and width and height
    assert float(width.group(1)) == float(view_box.group(1))
    assert float(height.group(1)) == float(view_box.group(2))


def test_transform_timeline_resets_animated_properties():
    anim = parse_animate(
        "pattern: transform\nfrom: A thing\nto: Another thing\n"
        "steps:\n  - Change it\n  - Change it again\n"
    )
    out = _transform_html(anim, "ANIMTOKEN5")
    data = json.loads(
        re.search(
            r'<script type="application/json" class="anim__timeline">(.*?)</script>',
            out, re.S,
        ).group(1)
    )
    animated = {
        p for s in data["steps"] if s.get("kind") != "set" for p in (s.get("props") or {})
    }
    reset = {
        p for s in data["steps"] if s.get("kind") == "set" for p in (s.get("props") or {})
    }
    assert animated <= reset


def test_transform_constants_are_divisible_by_four():
    for value in (_XFORM_BOX_WIDTH, _XFORM_BOX_HEIGHT, _XFORM_RUNG_GAP, _XFORM_TOP_MARGIN):
        assert value % 4 == 0


def _xf():
    return parse_animate(
        "pattern: transform\nfrom: Latin aqua\nto: French eau\n"
        "steps:\n  - Intervocalic weakening\n  - Loss of the final vowel\n  - Vowel fronting\n"
    )


def test_transform_steps_accumulate_rather_than_replace():
    """The old renderer flashed one step label on and off in a single fixed
    position over a horizontal connector, so only ever one was visible and the
    sequence itself -- the whole teaching point -- could never be seen at once.
    The redesign lands each step as its own rung on a vertical spine and never
    fades it back out: no non-`set` step may animate a step group's opacity
    down to 0.
    """
    out = _transform_html(_xf(), "ANIMTOKEN1")
    data = json.loads(
        re.search(r'class="anim__timeline">(.*?)</script>', out, re.S).group(1)
    )
    fades = [
        s for s in data["steps"]
        if s.get("kind") != "set"
        and "step" in str(s.get("targets"))
        and (s.get("props") or {}).get("opacity") == 0
    ]
    assert fades == []


def test_transform_every_step_has_its_own_position():
    out = _transform_html(_xf(), "ANIMTOKEN1")
    ys = re.findall(r'anim__xform-step[^>]*\bcy="([\d.]+)"', out)
    assert len(set(ys)) == 3, "each rung must sit at its own height on the spine"


def test_transform_result_text_inverts_on_accent():
    """The result box fills with the accent once every rung has landed, so its
    label must invert to stay legible (--color-fg on solid accent measures
    1.82:1-3.83:1 across the themes, below the 4.5:1 floor). Per the
    anim__text-on-accent convention used everywhere else in this file, that is
    a stacked, pre-inverted <text> whose OPACITY the timeline animates -- never
    a `fill` tween between two var() tokens, which animejs's colour detector
    cannot interpolate.
    """
    out = _transform_html(_xf(), "ANIMTOKEN1")
    assert "anim__text-on-accent" in out
    data = json.loads(
        re.search(r'class="anim__timeline">(.*?)</script>', out, re.S).group(1)
    )
    inverts = [
        s for s in data["steps"]
        if "opacity" in (s.get("props") or {})
        and "inverted" in str(s.get("targets"))
    ]
    assert inverts, "the result box fills with accent, so its text must invert"


def test_transform_resets_every_animated_property():
    out = _transform_html(_xf(), "ANIMTOKEN1")
    data = json.loads(
        re.search(r'class="anim__timeline">(.*?)</script>', out, re.S).group(1)
    )
    animated = {p for s in data["steps"] if s.get("kind") != "set"
                for p in (s.get("props") or {})}
    reset = {p for s in data["steps"] if s.get("kind") == "set"
             for p in (s.get("props") or {})}
    assert animated <= reset


def test_build_up_parses_whole_and_parts():
    anim = parse_animate(
        "pattern: build-up\nwhole: A valid syllogism\n"
        "parts:\n  - Major premise: all men are mortal\n"
        "  - Minor premise: Socrates is a man\n"
        "  - Conclusion: Socrates is mortal\n"
    )
    assert anim.whole == "A valid syllogism"
    assert anim.parts[0] == ("Major premise", "all men are mortal")
    assert len(anim.parts) == 3


def test_build_up_rejects_bad_part_counts():
    with pytest.raises(AnimateError, match="at least 2 parts"):
        parse_animate("pattern: build-up\nwhole: W\nparts:\n  - Only: one\n")
    body = "pattern: build-up\nwhole: W\nparts:\n" + "".join(
        f"  - P{i}: does {i}\n" for i in range(7)
    )
    with pytest.raises(AnimateError, match="at most 6 parts"):
        parse_animate(body)


def test_build_up_requires_whole():
    with pytest.raises(AnimateError, match="needs 'whole:'"):
        parse_animate("pattern: build-up\nparts:\n  - A: a\n  - B: b\n")


def test_build_up_rejects_keys_it_does_not_use():
    for stray in ("caption: c", "direction: up", "from: X"):
        with pytest.raises(AnimateError, match="does not use"):
            parse_animate(
                f"pattern: build-up\nwhole: W\nparts:\n  - A: a\n  - B: b\n{stray}\n"
            )


def test_build_up_parts_settle_and_stay():
    anim = parse_animate(
        "pattern: build-up\nwhole: W\nparts:\n  - A: a\n  - B: b\n  - C: c\n"
    )
    out = _build_up_html(anim, "ANIMTOKEN1")
    assert 'dir="ltr"' in out
    data = json.loads(
        re.search(r'class="anim__timeline">(.*?)</script>', out, re.S).group(1)
    )
    assert any("fillOpacity" in str(k) for s in data["steps"]
               for k in (s.get("props") or {}))
    animated = {p for s in data["steps"] if s.get("kind") != "set"
                for p in (s.get("props") or {})}
    reset = {p for s in data["steps"] if s.get("kind") == "set"
             for p in (s.get("props") or {})}
    assert animated <= reset


def test_compare_parses_two_tracks():
    anim = parse_animate(
        "pattern: compare\nleft: First-come\nright: Round robin\n"
        "steps:\n  - A long job blocks the queue | Each job gets a slice\n"
        "  - Short jobs wait | Short jobs finish early\n"
    )
    assert anim.left == "First-come"
    assert anim.right == "Round robin"
    assert anim.rows[0] == ("A long job blocks the queue", "Each job gets a slice")


def test_compare_requires_both_sides_of_every_row():
    with pytest.raises(AnimateError, match="must be written as"):
        parse_animate(
            "pattern: compare\nleft: L\nright: R\nsteps:\n  - only one side\n"
        )


def test_compare_requires_both_headers():
    with pytest.raises(AnimateError, match="needs both 'left:' and 'right:'"):
        parse_animate("pattern: compare\nleft: L\nsteps:\n  - a | b\n")


def test_compare_rejects_bad_row_counts():
    with pytest.raises(AnimateError, match="at least 1 step"):
        parse_animate("pattern: compare\nleft: L\nright: R\n")
    body = "pattern: compare\nleft: L\nright: R\nsteps:\n" + "".join(
        f"  - l{i} | r{i}\n" for i in range(6)
    )
    with pytest.raises(AnimateError, match="at most 5 steps"):
        parse_animate(body)


def test_compare_inverts_text_on_the_accent_flash():
    anim = parse_animate(
        "pattern: compare\nleft: L\nright: R\nsteps:\n  - a | b\n  - c | d\n"
    )
    out = _compare_html(anim, "ANIMTOKEN1")
    assert 'dir="ltr"' in out
    assert "anim__text-on-accent" in out
    data = json.loads(
        re.search(r'class="anim__timeline">(.*?)</script>', out, re.S).group(1)
    )
    inverts = [
        s for s in data["steps"]
        if "opacity" in (s.get("props") or {}) and "inverted" in str(s.get("targets"))
    ]
    assert inverts


def test_compare_resets_every_animated_property():
    anim = parse_animate(
        "pattern: compare\nleft: L\nright: R\nsteps:\n  - a | b\n  - c | d\n"
    )
    out = _compare_html(anim, "ANIMTOKEN1")
    data = json.loads(
        re.search(r'class="anim__timeline">(.*?)</script>', out, re.S).group(1)
    )
    animated = {p for s in data["steps"] if s.get("kind") != "set"
                for p in (s.get("props") or {})}
    reset = {p for s in data["steps"] if s.get("kind") == "set"
             for p in (s.get("props") or {})}
    assert animated <= reset


def _sm2():
    return parse_animate(
        "pattern: split-merge\nsource: Proof by cases\n"
        "branches:\n  - Case n even: divide by two\n  - Case n odd: apply 3n + 1\n"
        "merged: Both cases reach 1\n"
    )


def test_split_merge_parses_source_branches_and_merge():
    anim = _sm2()
    assert anim.source == "Proof by cases"
    assert anim.merged == "Both cases reach 1"
    assert anim.branches[0] == ("Case n even", "divide by two")


def test_split_merge_requires_source_and_merged():
    with pytest.raises(AnimateError, match="needs both 'source:' and 'merged:'"):
        parse_animate(
            "pattern: split-merge\nsource: S\nbranches:\n  - A: a\n  - B: b\n"
        )


def test_split_merge_rejects_bad_branch_counts():
    with pytest.raises(AnimateError, match="at least 2 branches"):
        parse_animate(
            "pattern: split-merge\nsource: S\nmerged: M\nbranches:\n  - A: a\n"
        )
    body = ("pattern: split-merge\nsource: S\nmerged: M\nbranches:\n"
            + "".join(f"  - B{i}: does {i}\n" for i in range(5)))
    with pytest.raises(AnimateError, match="at most 4 branches"):
        parse_animate(body)


def test_split_merge_renders_and_resets():
    out = _split_merge_html(_sm2(), "ANIMTOKEN1")
    assert 'dir="ltr"' in out
    data = json.loads(
        re.search(r'class="anim__timeline">(.*?)</script>', out, re.S).group(1)
    )
    animated = {p for s in data["steps"] if s.get("kind") != "set"
                for p in (s.get("props") or {})}
    reset = {p for s in data["steps"] if s.get("kind") == "set"
             for p in (s.get("props") or {})}
    assert animated <= reset
    # the merged box goes solid accent, so its label must invert
    assert "anim__text-on-accent" in out
    inverts = [
        s for s in data["steps"]
        if "opacity" in (s.get("props") or {}) and "inverted" in str(s.get("targets"))
    ]
    assert inverts


@pytest.mark.parametrize(
    "block",
    [
        # step-reveal is retired (see docs/superpowers/specs/2026-08-06-v1.3.0-bugfixes-design.md).
        # state-machine is deliberately absent too: like the old step-reveal, its
        # transitions play sequentially by design (see
        # test_state_machine_transitions_play_sequentially_not_all_at_once in
        # this file), so it emits no "<<" position for THIS test to check the
        # escaping of.
        'pattern: state-toggle\nbefore: Shared\nafter: Modified',
    ],
)
def test_timeline_island_position_tokens_are_not_html_escaped(block):
    """A <script> is an HTML *raw text* element, so character references inside it
    are never decoded. html.escape()-ing the island would hand JSON.parse the four
    literal characters "&lt;" instead of "<", turning anime.js's
    "start together with the previous step" position token ("<<" -- a bare "<"
    means "start after the previous step ENDS", not alongside it) into an
    unrecognized string and silently making parallel steps play sequentially.
    The island must therefore contain no "&lt;", and every position that means
    "<<" must parse back to "<<".
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
    assert "<<" in positions, positions


def test_state_machine_renders_boxes_track_arcs_and_a_timeline_island():
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
    # Two drawn track arcs (one per transition) -- always visible, not hidden.
    assert rendered.html_body.count('class="anim__state-track"') == 2
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
    # Both transitions (A->B and the authored B->A back-edge) are real, animated
    # marker travels -- not one travel plus an invisible reset. A wide sweep is
    # split into several cubics, so assert on the journey the steps describe
    # rather than on their count: the marker must start at A, reach B, and come
    # back to A entirely through animated segments.
    assert len(marker_travels) >= 2
    for previous, following in zip(marker_travels, marker_travels[1:]):
        assert previous["to"] == following["from"], "marker teleports between segments"
    assert marker_travels[0]["from"] == marker_travels[-1]["to"], (
        "a cycle's marker must end the lap where it began"
    )
    waypoints = [tuple(s["from"]) for s in marker_travels] + [tuple(marker_travels[-1]["to"])]
    assert len(set(waypoints)) >= 2, "marker never actually leaves its starting state"
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
    """A state box is a <g> wrapping a <rect> and two <text> elements, and every
    child carries its own `fill` attribute. Animating `fill` on the wrapping <g>
    never reaches a rendered pixel, because a child's own fill outranks anything
    inherited from the group. Every fill-animating step -- the arrival highlight
    and settle-back-to-idle -- must therefore target a rect id, never a group id
    (anim-state-box-*). (The label inversion no longer animates `fill` at all;
    see test_state_machine_inverts_active_label_text_and_restores_it for why.)
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
    # The wash rect carries its fill and a zero fill-opacity as its own
    # attributes, so it renders correctly (fully idle) before JS runs and under
    # reduced-motion/print, with nothing in the stylesheet competing with the
    # value the timeline interpolates.
    assert 'fill="var(--color-accent)" fill-opacity="0"' in rendered.html_body
    assert 'id="anim-state-rect-' in rendered.html_body
    match = re.search(
        r'<script type="application/json" class="anim__timeline"[^>]*>(.*?)</script>',
        rendered.html_body,
        re.DOTALL,
    )
    steps = json.loads(match.group(1))["steps"]
    fill_steps = [s for s in steps if "fill" in (s.get("props") or {})]
    fill_opacity_steps = [s for s in steps if "fillOpacity" in (s.get("props") or {})]
    assert fill_opacity_steps, "no fill-opacity-animating steps found"
    assert not fill_steps, (
        "a step animates `fill` directly -- this is the exact mechanism that "
        "broke against a real animejs, which cannot interpolate a var() string"
    )
    for step in fill_opacity_steps:
        for target in step["targets"]:
            assert target.startswith("#anim-state-rect-"), (
                f"fillOpacity step targets {target!r}; animating it on the <g> "
                "group is overridden by the rect's own fill-opacity and never renders"
            )


def test_state_machine_draws_no_track_arc_for_an_unauthored_state_pair():
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
    assert rendered.html_body.count('class="anim__state-track"') == 1


def test_state_machine_marker_and_track_paint_before_the_boxes():
    """The track and the traveling marker must be emitted BEFORE the boxes in
    document order, so each box's opaque base rect covers them whenever either
    passes behind it (SVG has no z-index; it paints later elements on top). A
    marker painted AFTER the boxes floats in front of the diagram's structure
    and covers each state's own label as it goes by -- the exact bug this
    ordering prevents.
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
    track_index = body.index('class="anim__state-track"')
    marker_index = body.index('class="anim__state-marker"')
    first_box_index = body.index('class="anim__state-box"')
    assert track_index < first_box_index
    assert marker_index < first_box_index
    # The marker starts at the first state's own centre, so it reads as sitting
    # in that box rather than floating somewhere on the track.
    box_match = re.search(
        r'<rect class="anim__state-base" x="(\S+)" y="(\S+)" width="(\S+)"', body
    )
    box_x, box_y, box_w = (float(box_match.group(i)) for i in (1, 2, 3))
    marker_match = re.search(
        r'class="anim__state-marker-dot"[^>]*cx="(\S+)" cy="(\S+)"', body
    )
    assert float(marker_match.group(1)) == pytest.approx(box_x + box_w / 2, abs=0.05)
    assert float(marker_match.group(2)) == pytest.approx(
        box_y + _STATE_BOX_HEIGHT / 2, abs=0.05
    )


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


def test_state_machine_marker_follows_the_drawn_track_not_a_straight_line():
    """Every transition is an arc on the ring, so every path-segment step must
    carry via1/via2 cubic controls -- a straight tween between two states would
    visibly cut across the middle of the ring instead of riding the drawn track.

    The drawn <path> is TRIMMED short of its destination so the arrowhead lands
    on the box's edge rather than hidden under the box, while the marker travels
    the FULL arc to the box's centre. So the step's controls are deliberately
    not the drawn path's controls; what must match is the curve they describe.
    This checks the marker's own arc stays on the ring.
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
    match = re.search(
        r'<script type="application/json" class="anim__timeline"[^>]*>(.*?)</script>',
        rendered.html_body,
        re.DOTALL,
    )
    steps = json.loads(match.group(1))["steps"]
    marker_travels = [s for s in steps if s.get("kind") == "path-segment"]
    # A wide sweep is split into several cubics, so there are at least as many
    # path-segment steps as transitions, and they chain end-to-start.
    assert len(marker_travels) >= 2
    for previous, following in zip(marker_travels, marker_travels[1:]):
        assert previous["to"] == following["from"], "marker teleports between segments"

    # Every state centre lies on one circle; recover it from the box positions.
    boxes = re.findall(
        r'<rect class="anim__state-base" x="(\S+)" y="(\S+)" width="(\S+)" height="(\S+)"',
        rendered.html_body,
    )
    centres = [
        (float(x) + float(w) / 2, float(y) + float(h) / 2) for x, y, w, h in boxes
    ]
    ring_cx = sum(p[0] for p in centres) / len(centres)
    ring_cy = sum(p[1] for p in centres) / len(centres)
    radius = math.hypot(centres[0][0] - ring_cx, centres[0][1] - ring_cy)

    def cubic(p0, c1, c2, p3, t):
        mt = 1 - t
        return (
            mt ** 3 * p0[0] + 3 * mt ** 2 * t * c1[0] + 3 * mt * t ** 2 * c2[0] + t ** 3 * p3[0],
            mt ** 3 * p0[1] + 3 * mt ** 2 * t * c1[1] + 3 * mt * t ** 2 * c2[1] + t ** 3 * p3[1],
        )

    for step in marker_travels:
        assert "via1" in step and "via2" in step, "a segment tweens in a straight line"
        for i in range(21):
            point = cubic(step["from"], step["via1"], step["via2"], step["to"], i / 20)
            offset = math.hypot(point[0] - ring_cx, point[1] - ring_cy)
            # A straight chord between two ring points would dip far inside the
            # ring; the arc must stay on it within sub-pixel tolerance.
            assert abs(offset - radius) < 1.0, (
                f"marker leaves the ring: {offset:.2f} vs radius {radius:.2f}"
            )


def _dialectic():
    return parse_animate(
        "pattern: state-machine\n"
        "states:\n  - Thesis\n  - Antithesis\n  - Synthesis\n"
        "transitions:\n"
        "  - Thesis -> Antithesis: provokes\n"
        "  - Antithesis -> Synthesis: resolves\n"
        "  - Synthesis -> Thesis: becomes the next thesis\n"
    )


def test_state_machine_paints_marker_behind_boxes():
    """SVG has no z-index: document order IS paint order. A marker emitted after
    the boxes covers each label as it passes. Correct order is
    track -> marker -> boxes -> labels.
    """
    out = _state_machine_html(_dialectic(), "ANIMTOKEN1")
    svg = out[out.index("<svg"):out.index("</svg>")]
    track = svg.index("anim__state-track")
    marker = svg.index("anim__state-marker")
    first_box = svg.index("anim__state-box")
    first_label = svg.index("anim__state-transition-label")
    assert track < marker < first_box < first_label


def test_state_machine_box_width_grows_with_its_label():
    """A fixed 130px box clipped any state name longer than ~16 characters.
    Width must derive from the authored text so long names stay readable.
    """
    short = parse_animate(
        "pattern: state-machine\nstates:\n  - A\n  - B\ntransitions:\n  - A -> B: x\n"
    )
    long = parse_animate(
        "pattern: state-machine\n"
        "states:\n  - A state with a considerably longer name\n  - B\n"
        "transitions:\n  - A state with a considerably longer name -> B: x\n"
    )

    def widest(html_text):
        return max(
            float(w)
            for w in re.findall(r'anim__state-rect[^>]*width="([\d.]+)"', html_text)
        )

    assert widest(_state_machine_html(long, "ANIMTOKEN2")) > widest(
        _state_machine_html(short, "ANIMTOKEN3")
    )


def test_state_machine_visited_states_hold_their_tint():
    """A visited state keeps a faint accent wash instead of reverting to idle,
    so the path travelled so far is readable at any moment. The wash is a
    fill-opacity animation (see .anim__visited), not a fill swap.
    """
    out = _state_machine_html(_dialectic(), "ANIMTOKEN1")
    data = json.loads(
        re.search(r'class="anim__timeline">(.*?)</script>', out, re.S).group(1)
    )
    assert any(
        "fillOpacity" in str(key)
        for step in data["steps"]
        for key in (step.get("props") or {})
    )


def test_state_machine_label_windows_do_not_overlap():
    """Each transition label must be hidden again before the next one shows.
    When labels ran on a period that did not divide the lap evenly, every label
    the marker had already passed kept blinking over the current one.
    """
    anim = _dialectic()
    out = _state_machine_html(anim, "ANIMTOKEN1")
    data = json.loads(
        re.search(r'class="anim__timeline">(.*?)</script>', out, re.S).group(1)
    )
    shows = [
        s for s in data["steps"]
        if "opacity" in (s.get("props") or {}) and "label" in str(s.get("targets"))
    ]
    # One fade-in and one fade-out per transition, at minimum.
    assert len(shows) >= 2 * len(anim.transitions)


def _svg_rects(markup, class_name):
    return [
        (float(x), float(y), float(w), float(h))
        for x, y, w, h in re.findall(
            rf'{class_name}" x="(\S+)" y="(\S+)" width="(\S+)" height="(\S+)"', markup
        )
    ]


def _boxes_overlap(a, b):
    return not (
        a[0] + a[2] <= b[0] or b[0] + b[2] <= a[0]
        or a[1] + a[3] <= b[1] or b[1] + b[3] <= a[1]
    )


@pytest.mark.parametrize("count", range(2, 13))
def test_state_machine_geometry_never_collides_or_clips(count):
    """The ring's radius and every label's push distance are computed, not fixed.
    A fixed radius looked right at three states and overlapped badly at six; a
    label pushed a constant distance past the ring sat on top of the boxes,
    which straddle it. This sweeps the whole plausible range and asserts nothing
    overlaps anything and nothing escapes the viewBox.
    """
    names = tuple(f"State {i}" for i in range(count))
    transitions = "".join(
        f"  - {names[i]} -> {names[(i + 1) % count]}: transition {i}\n"
        for i in range(count)
    )
    anim = parse_animate(
        "pattern: state-machine\nstates:\n"
        + "".join(f"  - {n}\n" for n in names)
        + "transitions:\n"
        + transitions
    )
    out = _state_machine_html(anim, "ANIMTOKEN1")
    boxes = _svg_rects(out, "anim__state-base")
    chips = _svg_rects(out, "anim__state-transition-label-bg")
    assert len(boxes) == count

    view_x, view_y, width, height = (
        float(v) for v in re.search(r'viewBox="(\S+) (\S+) (\S+) (\S+)"', out).groups()
    )
    for i in range(len(boxes)):
        for j in range(i + 1, len(boxes)):
            assert not _boxes_overlap(boxes[i], boxes[j]), f"boxes {i} and {j} overlap"
    for box in boxes:
        for chip in chips:
            assert not _boxes_overlap(box, chip), "a transition label sits on a state box"
    for i in range(len(chips)):
        for j in range(i + 1, len(chips)):
            assert not _boxes_overlap(chips[i], chips[j]), "two labels overlap"
    for x, y, w, h in boxes + chips:
        assert x >= view_x - 0.5 and y >= view_y - 0.5
        assert x + w <= view_x + width + 0.5 and y + h <= view_y + height + 0.5
    # A long label should widen the diagram somewhat, but not distort it into a
    # sliver: the bug this guards against pushed a 22-character label 244px past
    # an 88px-radius ring, more than tripling one axis while the other stayed
    # small, and squashed the whole ring into a corner of a wildly wide viewBox.
    assert max(width, height) / min(width, height) < 3.5


def test_state_machine_one_long_label_does_not_distort_the_diagram():
    """Regression for a real bug: a label's push distance was inflated by its
    OWN full chip width, so a 22-character transition on an otherwise compact
    ring got pushed ~244px out (radius ~88) -- nearly triple the ring's own
    size. That dragged the viewBox out to a wide sliver and squeezed the ring
    into one corner, which is what a reviewer flagged as looking broken. A chip
    must instead sit just outside the ring and only step out further when an
    actual collision demands it.

    Bounding on aspect ratio alone was tried first and did not catch this: a
    slightly different label produced a wide-but-not-absurd 1.96 ratio under
    the SAME bug, comfortably under a naive 3.5 threshold. The real signature
    of the bug is the RING shrinking relative to the overall canvas, so this
    measures the ring's diameter as a fraction of the viewBox's larger side
    instead -- that is what "squeezed into a corner" actually means.
    """
    anim = parse_animate(
        "pattern: state-machine\n"
        "states:\n  - Thesis\n  - Antithesis\n  - Synthesis\n"
        "transitions:\n"
        "  - Thesis -> Antithesis: provokes\n"
        "  - Antithesis -> Synthesis: resolves\n"
        "  - Synthesis -> Thesis: becomes the next thesis\n"
    )
    out = _state_machine_html(anim, "ANIMTOKEN1")
    boxes = _svg_rects(out, "anim__state-base")
    chips = _svg_rects(out, "anim__state-transition-label-bg")
    for i in range(len(boxes)):
        for j in range(i + 1, len(boxes)):
            assert not _boxes_overlap(boxes[i], boxes[j])
    for box in boxes:
        for chip in chips:
            assert not _boxes_overlap(box, chip)

    centres = [(x + w / 2, y + h / 2) for x, y, w, h in boxes]
    ring_cx = sum(p[0] for p in centres) / len(centres)
    ring_cy = sum(p[1] for p in centres) / len(centres)
    ring_radius = max(math.hypot(x - ring_cx, y - ring_cy) for x, y in centres)

    _, _, width, height = (
        float(v) for v in re.search(r'viewBox="(\S+) (\S+) (\S+) (\S+)"', out).groups()
    )
    assert max(width, height) / min(width, height) < 3.5, (
        f"a long label distorted the diagram into a {width:.0f}x{height:.0f} sliver"
    )
    # The bug shrank the ring to well under a third of the canvas; a healthy
    # layout keeps the ring as most of whichever side it's laid out along.
    assert (2 * ring_radius) / max(width, height) > 0.35, (
        f"ring diameter {2 * ring_radius:.0f} is tiny next to the "
        f"{width:.0f}x{height:.0f} canvas -- squeezed into a corner"
    )


def _state_machine_timeline(transitions):
    anim = parse_animate(
        "pattern: state-machine\nstates:\n  - A\n  - B\n  - C\n"
        f"transitions:\n{transitions}"
    )
    out = _state_machine_html(anim, "ANIMTOKEN1")
    island = re.search(r'class="anim__timeline"[^>]*>(.*?)</script>', out, re.S)
    return out, json.loads(island.group(1))


_ALL_PATTERN_BLOCKS = {
    "state-machine": (
        "pattern: state-machine\nstates:\n  - A\n  - B\n  - C\n"
        "transitions:\n  - A -> B: go\n  - B -> C: next\n  - C -> A: back\n"
    ),
    "state-toggle": "pattern: state-toggle\nbefore: X\nafter: Y\n",
    "pipeline": "pattern: pipeline\nstages:\n  - A: x\n  - B: y\n",
    "layer-stack": "pattern: layer-stack\nlayers:\n  - A: x\n  - B: y\n",
    "transform": "pattern: transform\nfrom: A\nto: B\nsteps:\n  - one\n",
    "build-up": "pattern: build-up\nwhole: W\nparts:\n  - A: a\n  - B: b\n",
    "compare": "pattern: compare\nleft: L\nright: R\nsteps:\n  - a | b\n",
    "split-merge": (
        "pattern: split-merge\nsource: S\nmerged: M\nbranches:\n  - A: a\n  - B: b\n"
    ),
}


def test_no_animate_pattern_animates_fill_or_stroke_with_a_css_variable():
    """Real animejs (v4.5.0)'s colour detector (isCol in core/helpers) only
    recognises hex, rgb(), rgba(), and hsl() -- a bare var(--token) reference
    matches none of those. decomposeRawValue then falls through its number
    path, defaults to the literal 0, and never revisits it: a `fill` tween
    between two var() strings silently renders as black and never recovers.

    Verified directly against the real library (not a hand-written stub): a
    generated state-machine's arrival flash was invisible-forever after the
    first lap. Confirmed here at the source instead, so a future JS-tween
    color animation using a var() reference is caught without a Node
    dependency: EVERY animate pattern's generated timeline is scanned for a
    non-`set` step whose `fill`/`stroke` prop contains "var(--", across a
    representative block for each of the eight patterns.
    """
    for name, body in _ALL_PATTERN_BLOCKS.items():
        out = _animate_html(parse_animate(body), "ANIMTOKEN1")
        for match in re.finditer(
            r'class="anim__timeline"[^>]*>(.*?)</script>', out, re.S
        ):
            data = json.loads(match.group(1))
            for step in data["steps"]:
                if step.get("kind") == "set":
                    continue
                for prop in ("fill", "stroke"):
                    value = (step.get("props") or {}).get(prop)
                    if value is None:
                        continue
                    values = value if isinstance(value, list) else [value]
                    for v in values:
                        assert "var(--" not in str(v), (
                            f"{name}: a tween step animates {prop} to {v!r} -- "
                            "animejs cannot interpolate a CSS variable as a colour"
                        )


def test_no_animate_pattern_uses_a_bare_less_than_position():
    """anime.js v4's Timeline.add() treats a bare "<" as "start once the
    PREVIOUS step ends" -- only "<<" means "start together with it". A "<"
    written with parallel-start intent silently serialises two steps that were
    meant to run at once, and the delay compounds lap over lap on a looping
    timeline: a 5-transition state-machine drifted by 3500ms across one lap
    (measured against the real animejs library), which surfaced as labels
    firing long after the marker had already moved on and highlights lagging
    visibly behind the dot. Every "run alongside the previous step" position
    in this renderer must be "<<"; this scans all eight patterns' generated
    timelines for a lingering bare "<" to catch a regression before it ships.
    """
    for name, body in _ALL_PATTERN_BLOCKS.items():
        out = _animate_html(parse_animate(body), "ANIMTOKEN1")
        for match in re.finditer(
            r'class="anim__timeline"[^>]*>(.*?)</script>', out, re.S
        ):
            data = json.loads(match.group(1))
            for step in data["steps"]:
                position = step.get("position")
                assert position != "<", (
                    f"{name}: a step has position '<', which starts it only "
                    "after the previous step ends -- use '<<' for a parallel start"
                )


@pytest.mark.parametrize(
    "transitions",
    (
        "  - A -> B: go\n  - B -> C: next\n",                     # no back-edge
        "  - A -> B: go\n  - B -> C: next\n  - C -> A: back\n",   # with back-edge
    ),
    ids=("no-back-edge", "with-back-edge"),
)
def test_state_machine_resets_every_animated_property(transitions):
    """anime.js loop invariant: a property animated on a looping timeline that is
    never reset by a trailing `set` compounds across laps. The back-edge branch
    used to reset `fill` but not `opacity`, so on a cycle every transition label
    kept whatever opacity it ended the previous lap on.
    """
    _, data = _state_machine_timeline(transitions)
    animated = {
        prop
        for step in data["steps"] if step.get("kind") != "set"
        for prop in (step.get("props") or {})
    }
    reset = {
        prop
        for step in data["steps"] if step.get("kind") == "set"
        for prop in (step.get("props") or {})
    }
    assert animated, "timeline animates nothing at all"
    assert animated <= reset, f"never reset: {sorted(animated - reset)}"


@pytest.mark.parametrize(
    "transitions",
    (
        "  - A -> B: go\n  - B -> C: next\n",
        "  - A -> B: go\n  - B -> C: next\n  - C -> A: back\n",
    ),
    ids=("no-back-edge", "with-back-edge"),
)
def test_state_machine_inverts_active_label_text_and_restores_it(transitions):
    """A state's label sits on a rect the timeline fills with --color-accent.
    --color-fg on that fill measures 1.82:1 to 3.83:1 across the three themes,
    below the 4.5:1 floor, so the label must invert to --color-accent-contrast
    on the same clock -- and every inverted target must be restored, or the
    inversion persists onto an idle box next lap.

    The inversion is implemented as TWO STACKED <text> elements (one plain, one
    pre-coloured --color-accent-contrast starting at opacity 0), with OPACITY
    animated to flip between them -- never as a `fill` tween between two CSS
    var() strings. Confirmed against the real animejs library that a bare
    var() reference is not recognised as a colour (its isCol() only matches
    hex/rgb()/rgba()/hsl()) and silently decomposes to the literal number 0,
    which rendered every label permanently black after the first lap.
    """
    out, data = _state_machine_timeline(transitions)
    # Two stacked texts at the same position: the plain one always present,
    # the inverted one starting invisible.
    assert out.count('class="anim__state-name') >= 2
    assert 'fill="var(--color-accent-contrast)"' in out
    assert 'class="anim__state-name anim__state-name-inverted"' in out

    def targets_where(predicate):
        return {
            target
            for step in data["steps"] if predicate(step)
            for target in step["targets"]
        }

    inverted_shown = targets_where(
        lambda s: s.get("kind") != "set"
        and (s.get("props") or {}).get("opacity") == [0, 1]
        and "anim-state-text" in str(s.get("targets"))
    )
    inverted_hidden = targets_where(
        lambda s: (s.get("props") or {}).get("opacity") in (0, [1, 0])
        and "anim-state-text" in str(s.get("targets"))
    )
    # No step may animate `fill` on the inverted-text id at all: that is the
    # exact mechanism that broke.
    fill_on_inverted = targets_where(
        lambda s: "fill" in (s.get("props") or {})
        and "anim-state-text" in str(s.get("targets"))
    )
    assert inverted_shown, "no label's inverted copy ever fades in"
    assert inverted_shown <= inverted_hidden, (
        f"never hidden again: {sorted(inverted_shown - inverted_hidden)}"
    )
    assert not fill_on_inverted, (
        f"a step still animates `fill` on the inverted text: {sorted(fill_on_inverted)}"
    )


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


def test_animations_per_topic_counts_blocks_and_backfills_zeros():
    md = course(
        '<!-- topic: topic-a -->\n### Topic A\n\n'
        '```animate\npattern: pipeline\nstages:\n  - Raw: unprocessed\n  - Done: processed\n```\n\n'
        '<!-- topic: topic-b -->\n### Topic B\n\n'
        'Prose only.\n'
    )
    rendered = render_course(md)
    assert rendered.animations_per_topic["topic-a"] == 1
    # Backfilled, not absent: the floor check divides over every topic.
    assert rendered.animations_per_topic["topic-b"] == 0
