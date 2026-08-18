"""course.md -> HTML body, TOC, glossary appendix.

Fenced blocks are extracted to tokens before python-markdown runs and restored as HTML
afterwards. Anchors, quiz ids and glossary term ids are all allocated here so nothing
downstream has to guess them.
"""

import html
import json
import math
import re
from dataclasses import dataclass, field

import markdown

from p2c.assemble import FrontMatter, parse_front_matter
from p2c.blocks import extract_fences, protect_inline_code, restore
from p2c.glossary import (
    GlossaryError,
    TermInjector,
    glossary_html,
    merge_glossaries,
    parse_glossary_block,
    term_ids,
)
from p2c.quiz import QuizError, parse_quiz, quiz_to_html
from p2c.text import AnchorAllocator

HANDLED_KINDS = ("quiz", "mermaid", "glossary", "analogy", "prereq", "unverified", "figure", "animate")
MERMAID_KEYWORDS = (
    "flowchart", "graph", "sequenceDiagram", "stateDiagram", "stateDiagram-v2",
    "classDiagram", "erDiagram", "journey", "gantt", "pie", "mindmap", "timeline",
    "quadrantChart", "xychart-beta", "block-beta", "architecture-beta",
)
CALLOUT_LABELS = {
    "analogy": "Analogy",
    "prereq": "Before this module",
    "unverified": "Not fully verified",
}

_FIGURE_KEY = re.compile(r"^(?P<key>source|caption):\s*(?P<value>.*)$")
_FIGURE_SOURCE = re.compile(r"^.+#\d+$")


class FigureError(ValueError):
    """A figure block that does not satisfy the grammar."""


def parse_figure(body: str) -> tuple[str, str]:
    source: str | None = None
    caption: str | None = None
    current: str | None = None

    for raw in body.split("\n"):
        line = raw.rstrip()
        if not line.strip():
            continue
        key = _FIGURE_KEY.match(line)
        if key:
            name, value = key.group("key"), key.group("value").strip()
            if name == "source":
                if source is not None:
                    raise FigureError("figure has more than one 'source:' line")
                source, current = value, "source"
            else:
                if caption is not None:
                    raise FigureError("figure has more than one 'caption:' line")
                caption, current = value, "caption"
            continue
        if current == "caption" and raw and raw[0].isspace():
            caption = f"{caption} {line.strip()}".strip()
            continue
        raise FigureError(f"unrecognised line in figure block: {line.strip()!r}")

    if not source:
        raise FigureError("figure is missing a 'source:' line")
    if not caption:
        raise FigureError("figure is missing a 'caption:' line")
    if not _FIGURE_SOURCE.match(source):
        raise FigureError(f"figure source {source!r} must look like 'deck.pdf#12'")
    return source, caption


def _figure_html(source: str, caption: str, topic_id: str | None) -> str:
    return (
        f'<figure class="figure" data-p2c-image-pending="{html.escape(source, quote=True)}" '
        f'data-p2c-topic="{html.escape(topic_id or "", quote=True)}">'
        f'<img alt="{html.escape(caption, quote=True)}">'
        f'<figcaption>{html.escape(caption)}</figcaption>'
        f'</figure>'
    )


STEP_SECONDS = 2

_ANIMATE_KEY = re.compile(
    r"^(?P<key>pattern|before|after|caption|direction|from|to):\s*(?P<value>.*)$"
)
_ANIMATE_STEP = re.compile(r"^\s*-\s*(?P<text>.+)$")
_TRANSITION = re.compile(r"^(?P<from>.+?)\s*->\s*(?P<to>.+?):\s*(?P<action>.+)$")
_STAGE = re.compile(r"^(?P<name>.+?):\s*(?P<change>.+)$")

# Matches "A --> B", "A -->|label| B", "A --- B", "A -.-> B", "A ==> B",
# with or without a node label: real course diagrams are written
# `M["מצלמה"] -->|"depth"| A["roof"]`, so the optional bracket/paren/brace
# label after the node id MUST be skipped -- otherwise the same node reads as
# two different sources depending on whether that occurrence carried a label,
# and a fan-out is silently scored as linear. Verified against
# unit2_lecture_tutorial-course: 17 of 42 blocks are linear chains.
_MERMAID_EDGE = re.compile(
    r"(?P<from>[A-Za-z0-9_-]+)\s*"
    r"(?:\[[^\]]*\]|\([^)]*\)|\{[^}]*\})?\s*"
    r"(?:-{2,3}>|-{3}|-\.-+>|={2,}>)"
    r"(?:\|[^|]*\|)?\s*"
    r"(?P<to>[A-Za-z0-9_-]+)"
)


def is_linear_mermaid(body: str) -> bool:
    """True when no node is the source of more than one edge.

    That shape -- a straight line of boxes -- is what `references/agents/
    course-writer.md` already calls a sequence rather than a flowchart. A
    diagram with no edges at all is not a chain and returns False.
    """
    sources: dict[str, int] = {}
    edges = 0
    for match in _MERMAID_EDGE.finditer(body):
        source = match.group("from")
        sources[source] = sources.get(source, 0) + 1
        edges += 1
    if edges == 0:
        return False
    return max(sources.values()) == 1


class AnimateError(ValueError):
    """An animate block that does not satisfy the grammar."""


@dataclass
class Animate:
    pattern: str
    before: str = ""
    after: str = ""
    caption: str = ""
    states: list[str] = field(default_factory=list)
    transitions: list[tuple[str, str, str]] = field(default_factory=list)
    stages: list[tuple[str, str]] = field(default_factory=list)
    layers: list[tuple[str, str]] = field(default_factory=list)
    direction: str = "up"
    from_entity: str = ""
    to_entity: str = ""
    steps: list[str] = field(default_factory=list)


_LIST_HEADERS = {
    "states:": "states", "transitions:": "transitions",
    "stages:": "stages", "layers:": "layers", "steps:": "steps",
}


_PATTERNS = ("state-machine", "state-toggle", "pipeline", "layer-stack", "transform")


def _require_known_pattern(pattern: str | None) -> None:
    if pattern not in _PATTERNS:
        raise AnimateError(
            "animate pattern must be 'state-machine', 'state-toggle', 'pipeline', "
            f"'layer-stack', or 'transform', got {pattern!r}"
        )


def parse_animate(body: str) -> Animate:
    pattern: str | None = None
    before: str | None = None
    after: str | None = None
    states_raw: list[str] = []
    transitions_raw: list[str] = []
    stages_raw: list[str] = []
    layers_raw: list[str] = []
    steps_raw: list[str] = []
    caption: str | None = None
    direction: str | None = None
    from_value: str | None = None
    to_value: str | None = None
    section: str | None = None

    lists = {
        "states": states_raw, "transitions": transitions_raw,
        "stages": stages_raw, "layers": layers_raw, "steps": steps_raw,
    }

    for raw in body.split("\n"):
        line = raw.rstrip()
        if not line.strip():
            continue
        item = _ANIMATE_STEP.match(line) if section else None
        if item:
            lists[section].append(item.group("text").strip())
            continue
        key = _ANIMATE_KEY.match(line)
        if key:
            name, value = key.group("key"), key.group("value").strip()
            section = None
            if name == "pattern":
                if pattern is not None:
                    raise AnimateError("animate has more than one 'pattern:' line")
                # Validated here rather than after the loop so the pattern name is
                # what the author hears about first. A removed pattern's block
                # still carries its old keys ("array:", "points:"), which are no
                # longer list headers -- checking later would report the stray key
                # and never mention that the pattern itself is gone.
                _require_known_pattern(value)
                pattern = value
            elif name == "before":
                before = value
            elif name == "after":
                after = value
            elif name == "direction":
                direction = value
            elif name == "from":
                from_value = value
            elif name == "to":
                to_value = value
            else:
                caption = value
            continue
        if line.strip() in _LIST_HEADERS:
            section = _LIST_HEADERS[line.strip()]
            continue
        raise AnimateError(f"unrecognised line in animate block: {line.strip()!r}")

    # Re-checked after the loop to cover the block that never named a pattern at
    # all: the in-loop call above only fires on a "pattern:" line.
    _require_known_pattern(pattern)

    if pattern == "state-machine":
        if (
            before or after or caption
            or stages_raw or layers_raw or steps_raw or direction or from_value or to_value
        ):
            raise AnimateError(
                "state-machine does not use 'before:'/'after:'/'caption:'/'stages:'/"
                "'layers:'/'steps:'/'direction:'/'from:'/'to:'"
            )
        states = states_raw
        if len(states) < 2:
            raise AnimateError("state-machine needs at least 2 states")
        if not transitions_raw:
            raise AnimateError("state-machine needs at least 1 transition")
        transitions: list[tuple[str, str, str]] = []
        for line_index, line in enumerate(transitions_raw):
            match = _TRANSITION.match(line)
            if not match:
                raise AnimateError(f"invalid state-machine transition: {line!r}")
            from_state = match.group("from").strip()
            to_state = match.group("to").strip()
            action = match.group("action").strip()
            if from_state not in states:
                raise AnimateError(f"state-machine transition names unknown state {from_state!r}")
            if to_state not in states:
                raise AnimateError(f"state-machine transition names unknown state {to_state!r}")
            from_index = states.index(from_state)
            to_index = states.index(to_state)
            is_consecutive_forward = to_index == from_index + 1
            # The one permitted exception: a transition FROM the last state back
            # to any earlier state, but only as the LAST authored transition --
            # checked by POSITION (this line's index is the final index) combined
            # with from_index being the last state's index. A back-edge appearing
            # anywhere else (including a second outgoing edge from a non-final
            # state, i.e. branching) is rejected by the same "must connect
            # consecutive states" message.
            #
            # The index comparison must stay positional, never `line ==
            # transitions_raw[-1]`: two IDENTICAL back-edge lines both compare
            # equal to the last line by value, so a value check would accept
            # BOTH as "the permitted trailing back-edge" and produce two
            # back-edges -- but _state_machine_html's back-edge detection only
            # inspects transitions[-1] and assumes there is at most one.
            is_final_line = line_index == len(transitions_raw) - 1
            is_permitted_back_edge = (
                is_final_line and from_index == len(states) - 1 and to_index < from_index
            )
            if not is_consecutive_forward and not is_permitted_back_edge:
                raise AnimateError(
                    f"state-machine transition {line!r} must connect consecutive "
                    "states (or be a single trailing transition from the last "
                    "state back to an earlier one)"
                )
            transitions.append((from_state, to_state, action))
        return Animate(pattern=pattern, states=states, transitions=transitions)
    elif pattern == "state-toggle":
        if not before or not after:
            raise AnimateError("state-toggle needs both 'before:' and 'after:'")
        if (
            states_raw or transitions_raw or caption
            or stages_raw or layers_raw or steps_raw or direction or from_value or to_value
        ):
            raise AnimateError(
                "state-toggle does not use 'states:'/'transitions:'/'caption:'/"
                "'stages:'/'layers:'/'steps:'/'direction:'/'from:'/'to:'"
            )
    elif pattern == "pipeline":
        if (
            before or after or states_raw or transitions_raw
            or caption or layers_raw or steps_raw or direction
            or from_value or to_value
        ):
            raise AnimateError(
                "pipeline does not use 'before:'/'after:'/'states:'/'transitions:'/"
                "'caption:'/'layers:'/'steps:'/'direction:'/'from:'/'to:'"
            )
        if len(stages_raw) < 2:
            raise AnimateError("pipeline needs at least 2 stages")
        if len(stages_raw) > 6:
            raise AnimateError("pipeline takes at most 6 stages")
        stages: list[tuple[str, str]] = []
        for line in stages_raw:
            match = _STAGE.match(line)
            if not match:
                raise AnimateError(
                    f"pipeline stage {line!r} must be written as '<name>: <what changes>'"
                )
            stages.append((match.group("name").strip(), match.group("change").strip()))
        return Animate(pattern=pattern, stages=stages)
    elif pattern == "layer-stack":
        if (
            before or after or states_raw or transitions_raw
            or caption or stages_raw or steps_raw or from_value or to_value
        ):
            raise AnimateError(
                "layer-stack does not use 'before:'/'after:'/'states:'/'transitions:'/"
                "'caption:'/'stages:'/'steps:'/'from:'/'to:'"
            )
        if direction is not None and direction not in ("up", "down"):
            raise AnimateError(
                f"layer-stack direction must be 'up' or 'down', got {direction!r}"
            )
        if len(layers_raw) < 2:
            raise AnimateError("layer-stack needs at least 2 layers")
        if len(layers_raw) > 6:
            raise AnimateError("layer-stack takes at most 6 layers")
        layers: list[tuple[str, str]] = []
        for line in layers_raw:
            match = _STAGE.match(line)
            if not match:
                raise AnimateError(
                    f"layer-stack layer {line!r} must be written as '<name>: <what it adds>'"
                )
            layers.append((match.group("name").strip(), match.group("change").strip()))
        return Animate(
            pattern=pattern, layers=layers, direction=direction or "up",
        )
    elif pattern == "transform":
        if (
            before or after or direction or states_raw or transitions_raw
            or caption or stages_raw or layers_raw
        ):
            raise AnimateError(
                "transform does not use 'before:'/'after:'/'direction:'/'states:'/"
                "'transitions:'/'caption:'/'stages:'/'layers:'"
            )
        if not from_value or not to_value:
            raise AnimateError("transform needs both 'from:' and 'to:'")
        if not steps_raw:
            raise AnimateError("transform needs at least 1 step")
        if len(steps_raw) > 4:
            raise AnimateError("transform takes at most 4 steps")
        return Animate(
            pattern=pattern, from_entity=from_value, to_entity=to_value,
            steps=list(steps_raw),
        )
    else:
        # The whitelist above admits exactly five patterns and every one of them
        # is handled by a branch, so reaching here means a pattern was added to
        # the whitelist without a parse branch. Raise rather than fall through:
        # the previous version ended in a bare `else` that parsed the last
        # pattern, which would silently mis-parse any newly whitelisted name.
        raise AnimateError(f"animate pattern {pattern!r} has no parser branch")

    return Animate(pattern=pattern, before=before or "", after=after or "")


_PIPE_BOX_WIDTH = 140
_PIPE_BOX_HEIGHT = 64
_PIPE_GAP = 56  # horizontal gap between stage boxes; also each connector's length
_PIPE_TOP_MARGIN = 24

_LAYER_WIDTH = 260
_LAYER_HEIGHT = 44
_LAYER_GAP = 12
_LAYER_TOP_MARGIN = 20

_XFORM_BOX_WIDTH = 180
_XFORM_BOX_HEIGHT = 60
_XFORM_GAP = 120  # MINIMUM room between the two endpoint boxes for the step labels --
                  # widened per-block below when a step's authored text needs more
                  # (see _transform_html), so this is a floor, not the final gap.
_XFORM_TOP_MARGIN = 24
_XFORM_STEP_BG_HEIGHT = 20  # matches _STATE_LABEL_CHIP_HEIGHT's own 12 + 2*pad recipe
                            # (12 + 2*_STATE_LABEL_CHIP_PAD_Y at pad=4 would be 20; kept
                            # as its own constant, not reused verbatim, since a wider
                            # mask reads better with a touch more vertical breathing
                            # room than a state-machine transition chip needs) and stays
                            # divisible by 4 per this branch's layout-constant rule.

_STATE_BOX_WIDTH = 130
_STATE_BOX_HEIGHT = 56
_STATE_GAP = 70  # horizontal gap between box edges, wide enough for an arrow + label
_STATE_TOP_MARGIN = 20  # headroom above the row when there is no back-edge arc
_STATE_BACK_EDGE_HEADROOM = 40  # extra top margin so the back-edge's arc and its
                                # arrowhead never clip the SVG's own top edge
_STATE_LABEL_LANE_OFFSET = 22  # a transition label sits this far above the row,
                               # clear of the box tops -- its own background
                               # chip (see _STATE_LABEL_CHIP_*) keeps it legible
                               # even where a long label overhangs a box edge
_STATE_LABEL_CHIP_PAD_X = 8  # horizontal padding inside a label's background chip
_STATE_LABEL_CHIP_PAD_Y = 3  # vertical padding inside a label's background chip
_STATE_LABEL_CHAR_WIDTH = 7.2  # rough px-per-character at the label's 12px/600
                               # weight font -- SVG cannot measure real text
                               # width at render time, so the chip's size is
                               # estimated from the authored string's length,
                               # generous enough that real glyphs stay inside it
_STATE_MARKER_RADIUS = 9


def _timeline_island_json(timeline: dict) -> str:
    """Serialize a timeline for embedding in <script type="application/json">.

    html.escape() must NOT be used here. A <script> element is an HTML *raw text*
    element: character references inside it are never decoded, so an escaped "<"
    reaches JSON.parse as the four literal characters "&lt;" rather than "<". That
    silently corrupts every step whose `position` is "<" (anime.js's
    "start with the previous step" token) into an unrecognized position string,
    so steps meant to run in parallel play sequentially instead.

    Escaping "<" as the JSON escape \\u003c is the correct encoding: it is decoded
    by JSON.parse (not by the HTML parser), so the value arrives as a real "<",
    while no literal "<" remains in the markup to begin a "</script>" sequence --
    strictly safer than html.escape(..., quote=False), which left ">" intact.
    """
    return json.dumps(timeline).replace("<", "\\u003c")


def _animate_html(anim: Animate, token: str) -> str:
    if anim.pattern == "state-machine":
        return _state_machine_html(anim, token)
    if anim.pattern == "state-toggle":
        return _state_toggle_html(anim, token)
    if anim.pattern == "pipeline":
        return _pipeline_html(anim, token)
    if anim.pattern == "layer-stack":
        return _layer_stack_html(anim, token)
    return _transform_html(anim, token)


def _state_machine_html(anim: Animate, token: str) -> str:
    """A marker travels between labeled state boxes as each transition fires.

    Movement uses the "path-segment" step kind: a tweened {x, y} state object
    mirrored onto the marker's cx/cy via onUpdate, rather than animating cx/cy
    directly, because they are SVG geometry attributes and not every browser
    animates them reliably as CSS properties. Each transition's action label is
    invisible at rest and fades in and out only during its own step, via a
    parallel "position": "<" step that pairs the opacity change with the
    movement tween.

    Only AUTHORED transitions are ever drawn or animated. If the chain has no
    authored back-edge (parse_animate guarantees at most one, and only from
    the last state), the loop-restart is an invisible "kind": "set" snap of
    the marker back to the first box and every label/box back to idle -- never
    a drawn or animated arrow -- so a reader never mistakes the animation's
    replay-for-engagement loop for a transition that was never authored.
    """
    # The token's literal text must never appear in this function's return
    # value: blocks.restore() does an unconditional second substitution pass
    # keyed on the token, so an id containing it would be corrupted. Only the
    # token's ordinal digits are used to build element ids.
    token_seed = re.sub(r"\D", "", token) or "0"
    box_ids = [f"anim-state-box-{token_seed}-{i}" for i in range(len(anim.states))]
    # The <g> wrapper is never the fill-animation target: the only VISIBLE shape
    # is its child <rect>, whose own fill wins over anything inherited from the
    # group, so an animated fill on the <g> never reaches a rendered pixel.
    # Hence a separate rect id per state, and an inline
    # fill="var(--anim-state-idle)" attribute rather than a stylesheet rule, so
    # nothing competes with the interpolated value while still rendering
    # correctly before JS runs and under reduced-motion/print.
    rect_ids = [f"anim-state-rect-{token_seed}-{i}" for i in range(len(anim.states))]
    text_ids = [f"anim-state-text-{token_seed}-{i}" for i in range(len(anim.states))]
    label_ids = [f"anim-state-label-{token_seed}-{i}" for i in range(len(anim.transitions))]
    marker_id = f"anim-state-marker-{token_seed}"

    # A back-edge's arc peaks above the row (see below), so the row itself is
    # pushed down by _STATE_BACK_EDGE_HEADROOM whenever one exists -- otherwise
    # the arc and its arrowhead have nowhere to go but past the SVG's own top
    # edge (y=0), clipping. A chain with no back-edge keeps the smaller,
    # plain _STATE_TOP_MARGIN.
    has_back_edge_precheck = False
    last_index_precheck = len(anim.states) - 1
    last_transition_precheck = anim.transitions[-1]
    if (
        anim.states.index(last_transition_precheck[1]) < last_index_precheck
        and anim.states.index(last_transition_precheck[0]) == last_index_precheck
    ):
        has_back_edge_precheck = True
    row_y = _STATE_BACK_EDGE_HEADROOM if has_back_edge_precheck else _STATE_TOP_MARGIN
    # Forward arrows and the traveling marker run at the boxes' own vertical
    # center -- a real flowchart line entering/exiting each box at its edge --
    # rather than a separate lane below. Never through a box's own text
    # despite sharing its height: boxes paint LAST (see the return value's
    # paint-order comment below), so each box's opaque rect covers the arrow's
    # end and the marker's full extent whenever either is at/behind a box.
    box_center_y = row_y + _STATE_BOX_HEIGHT / 2

    def box_x(i: int) -> int:
        return _STATE_GAP + i * (_STATE_BOX_WIDTH + _STATE_GAP)

    def box_center_x(i: int) -> float:
        return box_x(i) + _STATE_BOX_WIDTH / 2

    total_width = len(anim.states) * (_STATE_BOX_WIDTH + _STATE_GAP) + _STATE_GAP
    total_height = row_y + _STATE_BOX_HEIGHT + _STATE_LABEL_LANE_OFFSET + 4

    boxes_html = []
    for i, label in enumerate(anim.states):
        x = box_x(i)
        # The label carries its own id so it can invert to
        # --color-accent-contrast in step with its rect taking the accent fill.
        # --color-fg on --color-accent measures 1.82:1 to 3.83:1 across the three
        # themes, well under the 4.5:1 floor, so an active state's label was
        # briefly unreadable every lap.
        boxes_html.append(
            f'<g class="anim__state-box" id="{box_ids[i]}">'
            f'<rect id="{rect_ids[i]}" x="{x}" y="{row_y}" '
            f'width="{_STATE_BOX_WIDTH}" height="{_STATE_BOX_HEIGHT}" rx="8" '
            f'fill="var(--anim-state-idle)"></rect>'
            f'<text id="{text_ids[i]}" x="{x + _STATE_BOX_WIDTH / 2:g}" '
            f'y="{row_y + _STATE_BOX_HEIGHT / 2 + 5:g}" '
            f'fill="var(--color-fg)">'
            f"{html.escape(label)}</text>"
            "</g>"
        )

    # Static arrows: one per AUTHORED forward transition, always visible -- this
    # is the diagram's permanent structure. Derived from anim.transitions, never
    # from every adjacent pair in anim.states: the grammar only requires
    # transitions to cover the consecutive pairs they actually name, so a chain
    # may legitimately have a gap, and drawing an arrow across that gap would
    # invent an edge the course-writer never authored (the standing rule is that
    # only authored transitions are ever drawn or animated as edges). A trailing
    # authored back-edge (from the last state to an earlier one) is excluded
    # here -- it gets its own curved arrow above the row instead, visually
    # distinct from the forward chain.
    arrows_html = []
    forward_transitions = [
        t for t in anim.transitions
        if anim.states.index(t[1]) == anim.states.index(t[0]) + 1
    ]
    for from_state, to_state, _action in forward_transitions:
        i = anim.states.index(from_state)
        x1 = box_center_x(i)
        x2 = box_center_x(i + 1)
        arrows_html.append(
            f'<line class="anim__state-arrow" x1="{x1:g}" y1="{box_center_y:g}" '
            f'x2="{x2:g}" y2="{box_center_y:g}" marker-end="url(#anim-arrowhead-{token_seed})">'
            "</line>"
        )

    back_edge = None
    back_edge_curve: tuple[float, float, float, float] | None = None
    last_index = len(anim.states) - 1
    last_transition = anim.transitions[-1]
    if anim.states.index(last_transition[1]) < last_index and anim.states.index(last_transition[0]) == last_index:
        back_target_index = anim.states.index(last_transition[1])
        x_from = box_center_x(last_index)
        x_to = box_center_x(back_target_index)
        y_top = row_y
        arc_y = row_y - (_STATE_BACK_EDGE_HEADROOM - 10)
        back_edge = (
            f'<path class="anim__state-arrow anim__state-arrow--back" '
            f'd="M {x_from:g} {y_top} C {x_from:g} {arc_y:g}, {x_to:g} {arc_y:g}, '
            f'{x_to:g} {y_top}" marker-end="url(#anim-arrowhead-{token_seed})"></path>'
        )
        # The traveling marker's back-edge step reuses these exact two control
        # points (see the timeline-building loop below) so it visibly follows
        # this same drawn arc instead of cutting a straight line beneath it.
        back_edge_curve = (x_from, arc_y, x_to, arc_y)

    # Each label gets a background chip behind its text (a rect sized from the
    # authored action string's estimated width) so it stays legible even where
    # it overhangs a box's edge -- both chip and text paint AFTER the boxes
    # (see the return value's paint-order comment), the opposite of the
    # arrow/marker, which paint BEFORE the boxes precisely so the boxes can
    # cover them. A label is never meant to be partly hidden; an arrow/marker
    # sliding behind a box is the intended "enters the box" look.
    labels_html = []
    for i, (from_state, to_state, action) in enumerate(anim.transitions):
        from_i = anim.states.index(from_state)
        to_i = anim.states.index(to_state)
        lx = (box_center_x(from_i) + box_center_x(to_i)) / 2
        # The back-edge's label sits higher, above its own arc, clear of the
        # forward labels' band right above the row -- same distinction the
        # original (pre-lane) layout drew between the two cases.
        is_this_the_back_edge = back_edge_curve is not None and i == len(anim.transitions) - 1
        ly = (row_y - (_STATE_BACK_EDGE_HEADROOM - 6)) if is_this_the_back_edge else (row_y - _STATE_LABEL_LANE_OFFSET)
        chip_width = len(action) * _STATE_LABEL_CHAR_WIDTH + 2 * _STATE_LABEL_CHIP_PAD_X
        chip_height = 12 + 2 * _STATE_LABEL_CHIP_PAD_Y
        # Grouped under one id so the timeline's single opacity animation (see
        # below) fades the chip and its text together -- an empty chip left
        # behind by an invisible label would otherwise read as a stray box.
        labels_html.append(
            f'<g class="anim__state-transition-label-group" id="{label_ids[i]}">'
            f'<rect class="anim__state-transition-label-bg" '
            f'x="{lx - chip_width / 2:g}" y="{ly - chip_height + 4:g}" '
            f'width="{chip_width:g}" height="{chip_height:g}" rx="4"></rect>'
            f'<text class="anim__state-transition-label" '
            f'x="{lx:g}" y="{ly:g}">{html.escape(action)}</text>'
            "</g>"
        )

    marker_x0, marker_y0 = box_center_x(0), box_center_y
    marker_html = (
        f'<circle class="anim__state-marker" id="{marker_id}" '
        f'cx="{marker_x0:g}" cy="{marker_y0:g}" r="{_STATE_MARKER_RADIUS}"></circle>'
    )

    defs = (
        f'<defs><marker id="anim-arrowhead-{token_seed}" markerWidth="8" markerHeight="8" '
        f'refX="6" refY="4" orient="auto"><path class="anim__state-arrowhead" '
        f'd="M0,0 L8,4 L0,8 Z"></path></marker></defs>'
    )

    steps_json: list[dict] = []
    for i, (from_state, to_state, action) in enumerate(anim.transitions):
        from_i = anim.states.index(from_state)
        to_i = anim.states.index(to_state)
        fx, fy = box_center_x(from_i), box_center_y
        tx, ty = box_center_x(to_i), box_center_y
        marker_step: dict = {
            "kind": "path-segment",
            "marker": f"#{marker_id}",
            "from": [fx, fy],
            "to": [tx, ty],
            "duration": 900,
            "ease": "inOutQuad",
            "position": None,
        }
        # The back-edge (always the LAST authored transition, per the grammar)
        # gets the same two cubic-Bezier control points as its own drawn arc
        # (see back_edge_curve above), so the marker visibly follows that curve
        # instead of cutting a straight line beneath it -- its "from"/"to" are
        # overridden to the arc's own endpoints (the box's TOP edge, row_y, not
        # box_center_y), since the arc starts/ends there, arcing above the row.
        if back_edge_curve is not None and i == len(anim.transitions) - 1:
            via1_x, via1_y, via2_x, via2_y = back_edge_curve
            marker_step["from"] = [box_center_x(from_i), row_y]
            marker_step["to"] = [box_center_x(to_i), row_y]
            marker_step["via1"] = [via1_x, via1_y]
            marker_step["via2"] = [via2_x, via2_y]
        # The label must be fully visible BEFORE the marker starts moving and
        # stay visible until AFTER it arrives, so it leads and trails the
        # marker's own travel window rather than fading in lockstep with it.
        # anime.js spaces a single tween's keyframes evenly across its one
        # duration, so syncing both start times (as one opacity [0,1,1,0]
        # step used to do) put the fade-in mid-travel instead of ahead of
        # it. Three steps in strict sequence fix this: fade in first (its
        # own 200ms), then the marker travels while the label sits at full
        # opacity, then fade out (another 200ms) -- each step with no
        # "position" override runs sequentially after the one before it, so
        # this chain alone guarantees "label visible" fully brackets
        # "marker moving" on both ends. The box-fill highlight below must
        # still align with the marker's OWN start, so it is anchored via a
        # negative offset from this chain's start rather than "<" (which
        # would now resolve against the fade-in, not the marker).
        steps_json.append({
            "targets": [f"#{label_ids[i]}"],
            "props": {"opacity": [0, 1]},
            "duration": 200,
        })
        steps_json.append(marker_step)
        steps_json.append({
            "targets": [f"#{label_ids[i]}"],
            "props": {"opacity": [1, 0]},
            "duration": 200,
        })
        steps_json.append({
            "targets": [f"#{rect_ids[to_i]}"],
            "props": {"fill": ["var(--anim-state-idle)", "var(--anim-state-current)"]},
            "duration": 300, "position": "-=1100",
        })
        # Invert the arriving state's label on the SAME clock as its fill, so the
        # text is never --color-fg on a solid accent (1.82:1 to 3.83:1 across the
        # themes -- unreadable). "<" starts it with the fill step above.
        steps_json.append({
            "targets": [f"#{text_ids[to_i]}"],
            "props": {"fill": ["var(--color-fg)", "var(--color-accent-contrast)"]},
            "duration": 300, "position": "<",
        })
        if i > 0:
            previous_to_i = anim.states.index(anim.transitions[i - 1][1])
            steps_json.append({
                "targets": [f"#{rect_ids[previous_to_i]}"],
                "props": {"fill": ["var(--anim-state-current)", "var(--anim-state-idle)"]},
                "duration": 300, "position": "-=300",
            })
            steps_json.append({
                "targets": [f"#{text_ids[previous_to_i]}"],
                "props": {"fill": ["var(--color-accent-contrast)", "var(--color-fg)"]},
                "duration": 300, "position": "<",
            })

    has_back_edge = back_edge is not None
    if not has_back_edge:
        # Hold on the final state briefly, then snap everything back to the
        # start invisibly -- never a drawn/animated "final -> first" arrow.
        steps_json.append({"targets": [f"#{marker_id}"], "props": {}, "duration": 900})
        steps_json.append({
            "kind": "set", "targets": [f"#{marker_id}"],
            "props": {"cx": marker_x0, "cy": marker_y0},
        })
        steps_json.append({
            "kind": "set", "targets": [f"#{r}" for r in rect_ids],
            "props": {"fill": "var(--anim-state-idle)"},
        })
        steps_json.append({
            "kind": "set", "targets": [f"#{t}" for t in text_ids],
            "props": {"fill": "var(--color-fg)"},
        })
        steps_json.append({
            "kind": "set", "targets": [f"#{l}" for l in label_ids],
            "props": {"opacity": 0},
        })
    else:
        # The back-edge's own arrival-box highlight (added in the loop above)
        # already returns the diagram toward state[0] visibly, but the box
        # fill from that final arrival must still settle back to idle before
        # the loop restarts, exactly like every other arrival does.
        last_to_i = anim.states.index(anim.transitions[-1][1])
        steps_json.append({
            "kind": "set", "targets": [f"#{rect_ids[last_to_i]}"],
            "props": {"fill": "var(--anim-state-idle)"},
        })
        # Every text that was inverted during the lap resets too: without this the
        # accent-contrast fill persists into the next lap, where the box beneath
        # it is idle again -- dark-on-dark.
        steps_json.append({
            "kind": "set", "targets": [f"#{t}" for t in text_ids],
            "props": {"fill": "var(--color-fg)"},
        })
        # Transition labels reset here as well. The no-back-edge branch above
        # already did this; this branch did not, so on a looping cycle every
        # label kept whatever opacity it ended the lap on.
        steps_json.append({
            "kind": "set", "targets": [f"#{l}" for l in label_ids],
            "props": {"opacity": 0},
        })

    timeline = {"loop": True, "loopDelay": 800, "steps": steps_json}
    timeline_json = _timeline_island_json(timeline)

    static_lines = "".join(
        f"<li>{html.escape(f)} — {html.escape(a)} — {html.escape(t)}</li>"
        for f, t, a in anim.transitions
    )
    static_fallback = f'<ol class="anim__state-steps-static">{static_lines}</ol>'

    back_edge_svg = back_edge or ""
    # Paint order matters here, in two opposite directions:
    # - Arrows and the marker come BEFORE the boxes, so a box's opaque rect
    #   covers the arrow's end and the marker's full extent whenever either is
    #   at/behind it -- the marker reads as a token entering the box, and the
    #   arrow reads as originating/terminating exactly at the box's edge,
    #   never floating in front of the box or its text.
    # - Labels (with their own background chip) come AFTER the boxes, on top
    #   of everything -- a label is authored prose, not diagram structure, and
    #   must stay fully legible even where it overhangs a box's edge.
    return (
        '<div class="anim anim--state-machine">'
        f'<svg class="anim__state-machine" dir="ltr" '
        f'viewBox="0 0 {total_width} {total_height}">'
        f"{defs}{''.join(arrows_html)}{back_edge_svg}"
        f"{marker_html}{''.join(boxes_html)}{''.join(labels_html)}</svg>"
        f'<script type="application/json" class="anim__timeline">{timeline_json}</script>'
        f"{static_fallback}</div>"
    )


def _state_toggle_html(anim: Animate, token: str) -> str:
    # See _step_reveal_html's token_seed comment: only the token's ordinal digits
    # are used to build element ids, never the token's literal text.
    token_seed = re.sub(r"\D", "", token) or "0"
    before_id = f"anim-state-before-{token_seed}"
    after_id = f"anim-state-after-{token_seed}"
    # "Before"/"After" are literal English UI chrome -- like the "Analogy" callout
    # label, added by the render layer rather than the course-writer, so they stay
    # legible regardless of course language (including RTL). They are hidden during
    # normal animated playback and shown only in the print/reduced-motion static
    # presentation; see .anim__state-label in layout.css/print.css.
    #
    # The trailing pair of "kind": "set" steps resets both states back to their
    # resting opacity once the crossfade completes, so the NEXT loop iteration
    # starts from the same opacity as the first: "after" ends the visible
    # crossfade at opacity 1 and must be snapped back to 0 before the loop
    # restarts, and vice versa for "before" -- otherwise the second lap plays
    # from the wrong starting point.
    timeline = {
        "loop": True,
        "loopDelay": 0,
        "steps": [
            {"targets": [f"#{before_id}"], "props": {"opacity": [1, 0]}, "duration": 4000, "ease": "inOutQuad"},
            {"targets": [f"#{after_id}"], "props": {"opacity": [0, 1]}, "duration": 4000, "ease": "inOutQuad", "position": "<"},
            {"kind": "set", "targets": [f"#{before_id}"], "props": {"opacity": 1}},
            {"kind": "set", "targets": [f"#{after_id}"], "props": {"opacity": 0}},
        ],
    }
    timeline_json = _timeline_island_json(timeline)
    return (
        '<div class="anim anim--state-toggle">'
        f'<div class="anim__state anim__state--before" id="{before_id}">'
        f'<span class="anim__state-label">Before</span>{html.escape(anim.before)}</div>'
        f'<div class="anim__state anim__state--after" id="{after_id}">'
        f'<span class="anim__state-label">After</span>{html.escape(anim.after)}</div>'
        f'<script type="application/json" class="anim__timeline">{timeline_json}</script>'
        "</div>"
    )


def _pipeline_html(anim: Animate, token: str) -> str:
    """Stages light up left-to-right; each connector draws itself between them.

    Only one stage carries the accent at a time (diagram-design's focal rule):
    the arriving stage goes accent, and the previous one is returned to idle in
    the same step, so the reader's eye always has exactly one target.
    """
    token_seed = re.sub(r"\D", "", token) or "0"
    rect_ids = [f"anim-pipe-rect-{token_seed}-{i}" for i in range(len(anim.stages))]
    line_ids = [f"anim-pipe-line-{token_seed}-{i}" for i in range(len(anim.stages) - 1)]

    # Every box must be at least as wide as its OWN longest line (name or
    # change) needs, or authored prose overflows into the neighbouring box and
    # across the connector -- reusing _state_machine_html's own "estimate width
    # from character count" approach (_STATE_LABEL_CHAR_WIDTH,
    # _STATE_LABEL_CHIP_PAD_X) rather than inventing a second mechanism. Every
    # box in the row is then sized to the WIDEST stage, not just its own text,
    # so the row reads as one consistent grid rather than a jagged staircase of
    # differently sized boxes; _PIPE_BOX_WIDTH remains the floor for short text.
    box_width = max(
        [_PIPE_BOX_WIDTH]
        + [
            max(len(name), len(change)) * _STATE_LABEL_CHAR_WIDTH
            + 2 * _STATE_LABEL_CHIP_PAD_X
            for name, change in anim.stages
        ]
    )

    box_center_y = _PIPE_TOP_MARGIN + _PIPE_BOX_HEIGHT / 2
    total_width = len(anim.stages) * box_width + (len(anim.stages) - 1) * _PIPE_GAP
    total_height = _PIPE_TOP_MARGIN * 2 + _PIPE_BOX_HEIGHT

    def box_x(i: int) -> float:
        return i * (box_width + _PIPE_GAP)

    # Connectors are emitted BEFORE the boxes so z-order puts lines behind nodes
    # (diagram-design: "Draw arrows before boxes"), and each box's opaque rect
    # then covers the connector's ends.
    lines_html = []
    for i in range(len(anim.stages) - 1):
        x1 = box_x(i) + box_width
        x2 = box_x(i + 1)
        lines_html.append(
            f'<line class="anim__pipe-line" id="{line_ids[i]}" '
            f'x1="{x1:g}" y1="{box_center_y:g}" x2="{x2:g}" y2="{box_center_y:g}" '
            # The connector starts fully "undrawn": a dash as long as the line
            # itself, pushed entirely out of view. The timeline animates the
            # offset to 0, which walks the stroke into existence.
            f'stroke-dasharray="{_PIPE_GAP}" stroke-dashoffset="{_PIPE_GAP}"></line>'
        )

    boxes_html = []
    for i, (name, change) in enumerate(anim.stages):
        x = box_x(i)
        center_x = x + box_width / 2
        boxes_html.append(
            f'<g class="anim__pipe-stage">'
            f'<rect class="anim__pipe-box" id="{rect_ids[i]}" x="{x:g}" '
            f'y="{_PIPE_TOP_MARGIN}" width="{box_width:g}" '
            f'height="{_PIPE_BOX_HEIGHT}" rx="8" '
            f'fill="var(--anim-pipe-idle)"></rect>'
            f'<text class="anim__pipe-name" x="{center_x:g}" '
            f'y="{box_center_y - 4:g}" text-anchor="middle">{html.escape(name)}</text>'
            f'<text class="anim__pipe-change" x="{center_x:g}" '
            f'y="{box_center_y + 14:g}" text-anchor="middle">'
            f'{html.escape(change)}</text>'
            f'</g>'
        )

    steps_json: list[dict] = []
    for i in range(len(anim.stages)):
        steps_json.append({
            "targets": [f"#{rect_ids[i]}"],
            "props": {"fill": "var(--anim-pipe-active)"},
            "duration": 400,
            "ease": "outQuad",
        })
        if i > 0:
            steps_json.append({
                "targets": [f"#{rect_ids[i - 1]}"],
                "props": {"fill": "var(--anim-pipe-idle)"},
                "duration": 400,
                "ease": "outQuad",
                "position": "<",
            })
        if i < len(anim.stages) - 1:
            steps_json.append({
                "targets": [f"#{line_ids[i]}"],
                "props": {"strokeDashoffset": [_PIPE_GAP, 0]},
                "duration": STEP_SECONDS * 1000 // 2,
                "ease": "inOutQuad",
            })

    # Gotcha 2: snap every animated property back to baseline before the loop
    # restarts, or lap two starts from lap one's end state.
    steps_json.append({
        "kind": "set", "targets": [f"#{r}" for r in rect_ids],
        "props": {"fill": "var(--anim-pipe-idle)"},
    })
    steps_json.append({
        "kind": "set", "targets": [f"#{l}" for l in line_ids],
        "props": {"strokeDashoffset": _PIPE_GAP},
    })

    timeline_json = _timeline_island_json(
        {"loop": True, "loopDelay": 800, "steps": steps_json}
    )
    static_lines = "".join(
        f"<li>{html.escape(n)} — {html.escape(c)}</li>" for n, c in anim.stages
    )
    return (
        '<div class="anim anim--pipeline">'
        f'<svg class="anim__pipeline" dir="ltr" '
        f'width="{total_width:g}" height="{total_height:g}" '
        f'viewBox="0 0 {total_width:g} {total_height:g}">'
        f"{''.join(lines_html)}{''.join(boxes_html)}</svg>"
        f'<script type="application/json" class="anim__timeline">{timeline_json}</script>'
        f'<ol class="anim__pipeline-static">{static_lines}</ol></div>'
    )


def _layer_stack_html(anim: Animate, token: str) -> str:
    """Tiers appear one at a time, bottom-up by default.

    `layers` is authored bottom-up, so index 0 is drawn at the LARGEST y (the
    bottom of the SVG). A `direction: down` block reverses only the reveal
    ORDER, never the drawn positions -- the stack's geometry is the same
    picture either way, which is what makes the static fallback correct for both.
    """
    token_seed = re.sub(r"\D", "", token) or "0"
    count = len(anim.layers)
    rect_ids = [f"anim-layer-rect-{token_seed}-{i}" for i in range(count)]
    total_height = _LAYER_TOP_MARGIN * 2 + count * _LAYER_HEIGHT + (count - 1) * _LAYER_GAP
    total_width = _LAYER_WIDTH + _LAYER_TOP_MARGIN * 2

    def layer_y(i: int) -> float:
        # i == 0 is the bottom layer: count it down from the stack's base.
        from_top = count - 1 - i
        return _LAYER_TOP_MARGIN + from_top * (_LAYER_HEIGHT + _LAYER_GAP)

    rows_html = []
    for i, (name, adds) in enumerate(anim.layers):
        y = layer_y(i)
        rows_html.append(
            f'<g class="anim__layer-row">'
            f'<rect class="anim__layer-box" id="{rect_ids[i]}" '
            f'x="{_LAYER_TOP_MARGIN}" y="{y:g}" width="{_LAYER_WIDTH}" '
            f'height="{_LAYER_HEIGHT}" rx="6" fill="var(--anim-layer-idle)" '
            f'opacity="0"></rect>'
            f'<text class="anim__layer-name" x="{_LAYER_TOP_MARGIN + 12}" '
            f'y="{y + _LAYER_HEIGHT / 2 + 4:g}">{html.escape(name)}</text>'
            f'<text class="anim__layer-adds" '
            f'x="{_LAYER_TOP_MARGIN + _LAYER_WIDTH - 12}" '
            f'y="{y + _LAYER_HEIGHT / 2 + 4:g}" text-anchor="end">'
            f'{html.escape(adds)}</text>'
            f'</g>'
        )

    order = range(count) if anim.direction == "up" else range(count - 1, -1, -1)
    steps_json: list[dict] = []
    for position, i in enumerate(order):
        steps_json.append({
            "targets": [f"#{rect_ids[i]}"],
            "props": {"opacity": [0, 1], "fill": "var(--anim-layer-active)"},
            "duration": 500,
            "ease": "outQuad",
        })
        if position > 0:
            previous = list(order)[position - 1]
            steps_json.append({
                "targets": [f"#{rect_ids[previous]}"],
                "props": {"fill": "var(--anim-layer-idle)"},
                "duration": 500,
                "ease": "outQuad",
                "position": "<",
            })

    steps_json.append({
        "kind": "set", "targets": [f"#{r}" for r in rect_ids],
        "props": {"opacity": 0, "fill": "var(--anim-layer-idle)"},
    })

    timeline_json = _timeline_island_json(
        {"loop": True, "loopDelay": 900, "steps": steps_json}
    )
    static_lines = "".join(
        f"<li>{html.escape(n)} — {html.escape(a)}</li>" for n, a in anim.layers
    )
    return (
        '<div class="anim anim--layer-stack">'
        f'<svg class="anim__layer-stack" dir="ltr" '
        f'width="{total_width:g}" height="{total_height:g}" '
        f'viewBox="0 0 {total_width:g} {total_height:g}">'
        f"{''.join(rows_html)}</svg>"
        f'<script type="application/json" class="anim__timeline">{timeline_json}</script>'
        f'<ol class="anim__layer-static">{static_lines}</ol></div>'
    )


def _transform_html(anim: Animate, token: str) -> str:
    """One entity becomes another; each step's label appears over the connector.

    The two endpoint boxes are permanent structure. What animates is the
    connector drawing itself and the step labels appearing in order over it,
    with the destination box taking the accent only once the last step lands.
    """
    token_seed = re.sub(r"\D", "", token) or "0"
    from_id = f"anim-xform-from-{token_seed}"
    to_id = f"anim-xform-to-{token_seed}"
    line_id = f"anim-xform-line-{token_seed}"
    step_ids = [f"anim-xform-step-{token_seed}-{i}" for i in range(len(anim.steps))]

    # Each step's mask must be at least as wide as its own authored text -- reusing
    # _state_machine_html's exact "estimate width from character count" approach
    # (_STATE_LABEL_CHAR_WIDTH, _STATE_LABEL_CHIP_PAD_X) rather than inventing a
    # second sizing mechanism. The connector's gap is then widened, if needed, to
    # the WIDEST step's mask plus a further _STATE_LABEL_CHIP_PAD_X of clearance
    # on each side (so the mask itself never touches an endpoint box), so the
    # longest authored step never overhangs the mask meant to keep the connector
    # from bleeding through its text (_XFORM_GAP remains the floor for short steps).
    step_widths = [
        len(text) * _STATE_LABEL_CHAR_WIDTH + 2 * _STATE_LABEL_CHIP_PAD_X
        for text in anim.steps
    ]
    widest_step = max(step_widths, default=0)
    gap = max(_XFORM_GAP, widest_step + 2 * _STATE_LABEL_CHIP_PAD_X)

    box_center_y = _XFORM_TOP_MARGIN + _XFORM_BOX_HEIGHT / 2
    total_width = _XFORM_BOX_WIDTH * 2 + gap
    total_height = _XFORM_TOP_MARGIN * 2 + _XFORM_BOX_HEIGHT
    line_x1 = _XFORM_BOX_WIDTH
    line_x2 = _XFORM_BOX_WIDTH + gap
    label_center_x = line_x1 + gap / 2

    def endpoint(box_id: str, x: float, label: str) -> str:
        return (
            f'<g class="anim__xform-endpoint">'
            f'<rect class="anim__xform-box" id="{box_id}" x="{x:g}" '
            f'y="{_XFORM_TOP_MARGIN}" width="{_XFORM_BOX_WIDTH}" '
            f'height="{_XFORM_BOX_HEIGHT}" rx="8" '
            f'fill="var(--anim-xform-idle)"></rect>'
            f'<text class="anim__xform-label" x="{x + _XFORM_BOX_WIDTH / 2:g}" '
            f'y="{box_center_y + 4:g}" text-anchor="middle">{html.escape(label)}</text>'
            f'</g>'
        )

    # Step labels sit ABOVE the connector with a visible gap (diagram-design
    # rule 2: never let a label sit on its line), each over its own opaque mask
    # rect so the connector cannot bleed through the text.
    labels_html = []
    for i, text in enumerate(anim.steps):
        mask_width = step_widths[i]
        labels_html.append(
            f'<g class="anim__xform-step" id="{step_ids[i]}" opacity="0">'
            f'<rect class="anim__xform-step-bg" x="{label_center_x - mask_width / 2:g}" '
            f'y="{box_center_y - 26:g}" width="{mask_width:g}" '
            f'height="{_XFORM_STEP_BG_HEIGHT}" rx="2"></rect>'
            f'<text class="anim__xform-step-text" x="{label_center_x:g}" '
            f'y="{box_center_y - 13:g}" text-anchor="middle">'
            f'{html.escape(text)}</text>'
            f'</g>'
        )

    steps_json: list[dict] = [
        {
            "targets": [f"#{line_id}"],
            "props": {"strokeDashoffset": [gap, 0]},
            "duration": STEP_SECONDS * 1000,
            "ease": "inOutQuad",
        }
    ]
    for i, step_id in enumerate(step_ids):
        steps_json.append({
            "targets": [f"#{step_id}"],
            "props": {"opacity": [0, 1]},
            "duration": 400,
            "ease": "outQuad",
        })
        if i > 0:
            steps_json.append({
                "targets": [f"#{step_ids[i - 1]}"],
                "props": {"opacity": 0},
                "duration": 400,
                "ease": "outQuad",
                "position": "<",
            })
    steps_json.append({
        "targets": [f"#{to_id}"],
        "props": {"fill": "var(--anim-xform-active)"},
        "duration": 500,
        "ease": "outQuad",
    })

    steps_json.append({
        "kind": "set", "targets": [f"#{s}" for s in step_ids], "props": {"opacity": 0},
    })
    steps_json.append({
        "kind": "set", "targets": [f"#{line_id}"],
        "props": {"strokeDashoffset": gap},
    })
    steps_json.append({
        "kind": "set", "targets": [f"#{to_id}"],
        "props": {"fill": "var(--anim-xform-idle)"},
    })

    timeline_json = _timeline_island_json(
        {"loop": True, "loopDelay": 900, "steps": steps_json}
    )
    static_steps = "".join(f"<li>{html.escape(s)}</li>" for s in anim.steps)
    return (
        '<div class="anim anim--transform">'
        f'<svg class="anim__transform" dir="ltr" '
        f'width="{total_width:g}" height="{total_height:g}" '
        f'viewBox="0 0 {total_width:g} {total_height:g}">'
        f'<line class="anim__xform-line" id="{line_id}" x1="{line_x1:g}" '
        f'y1="{box_center_y:g}" x2="{line_x2:g}" y2="{box_center_y:g}" '
        f'stroke-dasharray="{gap:g}" stroke-dashoffset="{gap:g}"></line>'
        f'{endpoint(from_id, 0, anim.from_entity)}'
        f'{endpoint(to_id, _XFORM_BOX_WIDTH + gap, anim.to_entity)}'
        f"{''.join(labels_html)}</svg>"
        f'<script type="application/json" class="anim__timeline">{timeline_json}</script>'
        f'<ol class="anim__xform-static">{static_steps}</ol></div>'
    )


_TOPIC_MARKER = re.compile(r"^\s*<!--\s*topic:\s*(?P<id>[^\s>]+)\s*-->\s*$")
_HEADING = re.compile(r"^(?P<hashes>#{1,6})\s+(?P<text>.+?)\s*$")
_NO_VISUAL = re.compile(r"^\s*<!--\s*no-visual:\s*.+-->\s*$")
_NO_QUIZ = re.compile(r"^\s*<!--\s*no-quiz:\s*.+-->\s*$")
_VISUAL_FENCE_KINDS = {"mermaid", "figure", "animate"}


def _note_visual(status: dict[str, str], topic_id: str | None, value: str) -> None:
    """'visual' always wins over 'justified', so a real visual is never
    downgraded by an incidental no-visual comment elsewhere in the same topic."""
    if not topic_id:
        return
    if value == "visual" or status.get(topic_id) != "visual":
        status[topic_id] = value


_EXTENSIONS = ["extra", "sane_lists"]
# Same fence-line shape p2c.blocks.extract_fences uses: HANDLED_KINDS fences are
# already tokenized before the line walk runs, so any ``` line seen there opens or
# closes an ordinary (unhandled-kind) code sample.
_FENCE_OPEN = re.compile(r"^\s{0,3}```\s*(?P<info>[A-Za-z0-9_-]*)\s*$")
_FENCE_CLOSE = re.compile(r"^\s{0,3}```\s*$")


def _fenced_line_indices(lines: list[str]) -> set[int]:
    """Indices that fall inside a *genuinely closed* ordinary code fence.

    Mirrors p2c.blocks.extract_fences's own forward-looking open -> find-matching-
    close algorithm exactly, so an opening ``` line only counts as a fence when a
    later closing line actually exists. An unterminated fence is left untouched
    (its opening line, and everything after it, resumes normal heading/topic-marker
    scanning) -- a single-pass stateful toggle cannot know this in advance, since it
    has no way to look ahead for a matching close.

    Deliberate consequence, not a bug: if a fence never closes, anything that looks
    like a heading or topic marker inside its dangling body (e.g. a `#`-style shell
    comment, or a literal `<!-- topic: ... -->` example) IS treated as real markdown
    structure. That is by design, not an oversight -- an unterminated fence is
    inherently ambiguous input (did the author mean "the rest of the document is
    code", or "I forgot a closing ```, everything after is real markdown"?), and
    p2c.blocks.extract_fences already committed the whole pipeline to the second
    reading for exactly this situation. Confirmed by running extract_fences() and
    real markdown.markdown() on the same malformed input with no mdrender involved
    at all: a "## fake module" line living inside a never-closed fence's dangling
    body renders as a genuine <h2> there too. Matching that here keeps mdrender
    consistent with the rest of the pipeline instead of inventing a third, bespoke
    interpretation of malformed input. See
    test_content_inside_a_never_closed_fence_is_treated_as_ordinary_markdown_by_design
    in tests/test_mdrender.py, which locks this in as expected behavior.
    """
    protected: set[int] = set()
    i = 0
    n = len(lines)
    while i < n:
        if _FENCE_OPEN.match(lines[i]):
            close = next(
                (j for j in range(i + 1, n) if _FENCE_CLOSE.match(lines[j])), None
            )
            if close is not None:
                protected.update(range(i, close + 1))
                i = close + 1
                continue
        i += 1
    return protected


def _md(text: str) -> str:
    return markdown.Markdown(extensions=_EXTENSIONS).convert(text)


_STYLE_FILL_LINE = re.compile(r"^\s*style\s+(\S+)\s+(.*)$")


def mermaid_problem(body: str) -> str | None:
    """A structural check, not a real parse. Mermaid itself is the final authority."""
    stripped = body.strip()
    if not stripped:
        return "diagram body is empty"
    first = stripped.split("\n", 1)[0].strip()
    if not any(first.startswith(kw) for kw in MERMAID_KEYWORDS):
        return f"unrecognised diagram type {first.split()[0]!r}"
    if stripped.count('"') % 2:
        return "unbalanced quotes"
    for opener, closer in (("[", "]"), ("(", ")"), ("{", "}")):
        if stripped.count(opener) != stripped.count(closer):
            return f"unbalanced '{opener}{closer}' brackets"
    for line in stripped.splitlines():
        match = _STYLE_FILL_LINE.match(line)
        if not match:
            continue
        node, props = match.group(1), match.group(2)
        if "fill:" in props and "color:" not in props:
            return (
                f"style {node!r} sets fill without color -- the theme's default text "
                "color is not guaranteed to stay readable against a custom fill, so "
                "every 'fill:' must be paired with an explicit 'color:' on the same line"
            )
    return None


@dataclass
class Section:
    level: int
    id: str
    title: str
    topic_id: str | None = None


@dataclass
class Rendered:
    front_matter: FrontMatter
    html_body: str
    toc_html: str
    glossary_html: str
    sections: list[Section] = field(default_factory=list)
    glossary: dict[str, str] = field(default_factory=dict)
    quizzes_per_topic: dict[str, int] = field(default_factory=dict)
    animations_per_topic: dict[str, int] = field(default_factory=dict)
    linear_mermaid_topics: list[str] = field(default_factory=list)
    quiz_count: int = 0
    uses_mermaid: bool = False
    uses_animate: bool = False
    topics_missing_visual: list[str] = field(default_factory=list)
    topics_visual_justified: list[str] = field(default_factory=list)
    topics_missing_quiz: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    @property
    def topic_ids(self) -> list[str]:
        return [s.topic_id for s in self.sections if s.topic_id]


def _callout_html(kind: str, body: str) -> str:
    label = CALLOUT_LABELS[kind]
    return (
        f'<aside class="callout callout--{kind}">'
        f'<p class="callout__label">{label}</p>'
        f"{_md(body.strip())}</aside>"
    )


def _toc_html(sections: list[Section]) -> str:
    rows = ['<ul class="toc__list">']
    open_child = False
    for section in sections:
        if section.level <= 1:
            continue
        if section.level == 2:
            if open_child:
                rows.append("</ul></li>")
                open_child = False
            rows.append(
                f'<li class="toc__module"><a href="#{section.id}">'
                f"{html.escape(section.title)}</a>"
            )
            rows.append('<ul class="toc__topics">')
            open_child = True
        else:
            rows.append(
                f'<li class="toc__topic"><a href="#{section.id}">'
                f"{html.escape(section.title)}</a></li>"
            )
    if open_child:
        rows.append("</ul></li>")
    # The template's appendix sections (glossary, sources) always exist, even when
    # empty -- see {{GLOSSARY}}/{{SOURCES}} in template.html -- so the TOC always
    # links to them too, the same literal English chrome as their <h2> labels.
    rows.append('<li class="toc__module"><a href="#glossary">Glossary</a></li>')
    rows.append('<li class="toc__module"><a href="#sources">Sources</a></li>')
    rows.append("</ul>")
    return "\n".join(rows)


def render_course(course_md: str) -> Rendered:
    front_matter, body = parse_front_matter(course_md)
    body, fences = extract_fences(body, kinds=HANDLED_KINDS)
    errors: list[str] = []

    glossary_blocks: list[dict[str, str]] = []
    for fence in fences:
        if fence.kind != "glossary":
            continue
        try:
            glossary_blocks.append(parse_glossary_block(fence.body))
        except GlossaryError as exc:
            errors.append(f"glossary block: {exc}")
    terms = merge_glossaries(glossary_blocks)
    ids = term_ids(terms)
    injector = TermInjector(terms, ids)

    anchors = AnchorAllocator()
    sections: list[Section] = []
    topic_visual_status: dict[str, str] = {}
    topic_quiz_status: dict[str, str] = {}
    out: list[str] = []
    buffer: list[str] = []
    token_owner: dict[str, tuple[str, str | None]] = {}
    pending_topic: str | None = None
    current: tuple[str, str | None] = ("course", None)

    def flush() -> None:
        if not buffer:
            return
        protected, code_map = protect_inline_code("\n".join(buffer))
        out.append(restore(injector.inject(protected), code_map))
        buffer.clear()

    body_lines = body.split("\n")
    fenced_lines = _fenced_line_indices(body_lines)
    for index, line in enumerate(body_lines):
        if index in fenced_lines:
            # Inside an ordinary (unhandled-kind) code fence that genuinely closes
            # later: HANDLED_KINDS fences were already tokenized to P2CBLOCK lines
            # before this walk runs, so this is a plain code sample. Its contents
            # must not be scanned for headings or topic markers (e.g. a
            # `#`-commented line inside a ```c sample is not a heading). An
            # unterminated fence is NOT in this set (see _fenced_line_indices), so
            # it never suppresses real structure that follows it.
            buffer.append(line)
            continue
        marker = _TOPIC_MARKER.match(line)
        if marker:
            pending_topic = marker.group("id")
            continue
        heading = _HEADING.match(line)
        if heading:
            flush()
            level = len(heading.group("hashes"))
            title = heading.group("text")
            anchor = anchors.take(title)
            topic_id = pending_topic if level >= 3 else None
            sections.append(Section(level=level, id=anchor, title=title, topic_id=topic_id))
            out.append(f"{'#' * level} {title} {{: #{anchor} }}")
            current = (anchor, topic_id)
            pending_topic = None
            continue
        if line.strip().startswith("P2CBLOCK"):
            token_owner[line.strip()] = current
        elif current[1]:
            if "<svg" in line:
                _note_visual(topic_visual_status, current[1], "visual")
            elif _NO_VISUAL.match(line):
                _note_visual(topic_visual_status, current[1], "justified")
            elif _NO_QUIZ.match(line):
                topic_quiz_status[current[1]] = "justified"
        buffer.append(line)
    flush()

    replacements: dict[str, str] = {}
    quizzes_per_topic: dict[str, int] = {}
    animations_per_topic: dict[str, int] = {}
    quiz_numbers: dict[str, int] = {}
    quiz_count = 0
    uses_mermaid = False
    uses_animate = False
    mermaid_linearity: dict[str, list[bool]] = {}

    for fence in fences:
        anchor, topic_id = token_owner.get(fence.token, ("course", None))
        if fence.kind in _VISUAL_FENCE_KINDS:
            _note_visual(topic_visual_status, topic_id, "visual")
        if fence.kind == "quiz":
            try:
                quiz = parse_quiz(fence.body)
            except QuizError as exc:
                errors.append(f"{anchor}: {exc}")
                replacements[fence.token] = ""
                continue
            quiz_numbers[anchor] = quiz_numbers.get(anchor, 0) + 1
            replacements[fence.token] = quiz_to_html(
                quiz, f"{anchor}-q{quiz_numbers[anchor]}"
            )
            quiz_count += 1
            if topic_id:
                quizzes_per_topic[topic_id] = quizzes_per_topic.get(topic_id, 0) + 1
                topic_quiz_status[topic_id] = "has_quiz"
        elif fence.kind == "mermaid":
            problem = mermaid_problem(fence.body)
            if problem:
                errors.append(f"{anchor}: mermaid {problem}")
                replacements[fence.token] = (
                    '<div class="diagram-fallback"><p>Diagram unavailable: '
                    f"{html.escape(problem)}</p></div>"
                )
            else:
                uses_mermaid = True
                if topic_id:
                    mermaid_linearity.setdefault(topic_id, []).append(
                        is_linear_mermaid(fence.body)
                    )
                replacements[fence.token] = (
                    f'<div class="mermaid" dir="ltr">{html.escape(fence.body)}</div>'
                )
        elif fence.kind == "glossary":
            replacements[fence.token] = ""
        elif fence.kind == "figure":
            try:
                source, caption = parse_figure(fence.body)
            except FigureError as exc:
                errors.append(f"{anchor}: figure {exc}")
                replacements[fence.token] = ""
                continue
            replacements[fence.token] = _figure_html(source, caption, topic_id)
        elif fence.kind == "animate":
            try:
                anim = parse_animate(fence.body)
            except AnimateError as exc:
                errors.append(f"{anchor}: animate {exc}")
                replacements[fence.token] = ""
                continue
            uses_animate = True
            if topic_id:
                animations_per_topic[topic_id] = animations_per_topic.get(topic_id, 0) + 1
            replacements[fence.token] = _animate_html(anim, fence.token)
        else:
            replacements[fence.token] = _callout_html(fence.kind, fence.body)

    html_body = _md("\n".join(out))
    html_body = restore(html_body, replacements)
    html_body = restore(html_body, injector.replacements)

    for topic_id in (s.topic_id for s in sections if s.topic_id):
        quizzes_per_topic.setdefault(topic_id, 0)

    for topic_id in (s.topic_id for s in sections if s.topic_id):
        animations_per_topic.setdefault(topic_id, 0)

    # A topic qualifies only when EVERY mermaid block it has is linear: a topic
    # that also carries a genuinely branching diagram is not a mis-classification.
    linear_mermaid_topics = [
        tid for tid, flags in mermaid_linearity.items() if flags and all(flags)
    ]

    topics_missing_visual = [
        tid for tid in dict.fromkeys(s.topic_id for s in sections if s.topic_id)
        if topic_visual_status.get(tid) not in ("visual", "justified")
    ]

    topics_visual_justified = [
        tid for tid in dict.fromkeys(s.topic_id for s in sections if s.topic_id)
        if topic_visual_status.get(tid) == "justified"
    ]

    topics_missing_quiz = [
        tid for tid in dict.fromkeys(s.topic_id for s in sections if s.topic_id)
        if quizzes_per_topic.get(tid, 0) == 0 and topic_quiz_status.get(tid) != "justified"
    ]

    return Rendered(
        front_matter=front_matter,
        html_body=html_body,
        toc_html=_toc_html(sections),
        glossary_html=glossary_html(terms, ids) if terms else "",
        sections=sections,
        glossary=terms,
        quizzes_per_topic=quizzes_per_topic,
        animations_per_topic=animations_per_topic,
        linear_mermaid_topics=linear_mermaid_topics,
        quiz_count=quiz_count,
        uses_mermaid=uses_mermaid,
        uses_animate=uses_animate,
        topics_missing_visual=topics_missing_visual,
        topics_visual_justified=topics_visual_justified,
        topics_missing_quiz=topics_missing_quiz,
        errors=errors,
    )
