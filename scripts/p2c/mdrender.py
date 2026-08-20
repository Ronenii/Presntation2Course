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
    r"^(?P<key>pattern|before|after|caption|direction|from|to"
    r"|whole|left|right|source|merged):\s*(?P<value>.*)$"
)
_ANIMATE_STEP = re.compile(r"^\s*-\s*(?P<text>.+)$")
_TRANSITION = re.compile(r"^(?P<from>.+?)\s*->\s*(?P<to>.+?):\s*(?P<action>.+)$")
_STAGE = re.compile(r"^(?P<name>.+?):\s*(?P<change>.+)$")
# Split on the first UNESCAPED "|": a compare row's two halves may legitimately
# contain a literal "\|" the author wants rendered, so a plain str.split("|")
# would cut the wrong text in two. "(?<!\\)" is a negative lookbehind for the
# escape character itself.
_COMPARE_ROW = re.compile(r"^(?P<left>.+?)(?<!\\)\|(?P<right>.+)$")

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
    caption: str = ""
    states: list[str] = field(default_factory=list)
    transitions: list[tuple[str, str, str]] = field(default_factory=list)
    stages: list[tuple[str, str]] = field(default_factory=list)
    layers: list[tuple[str, str]] = field(default_factory=list)
    direction: str = "up"
    from_entity: str = ""
    to_entity: str = ""
    steps: list[str] = field(default_factory=list)
    whole: str = ""
    parts: list[tuple[str, str]] = field(default_factory=list)
    left: str = ""
    right: str = ""
    rows: list[tuple[str, str]] = field(default_factory=list)
    source: str = ""
    merged: str = ""
    branches: list[tuple[str, str]] = field(default_factory=list)


_LIST_HEADERS = {
    "states:": "states", "transitions:": "transitions",
    "stages:": "stages", "layers:": "layers", "steps:": "steps",
    "parts:": "parts", "branches:": "branches",
}


_PATTERNS = (
    "state-machine", "pipeline", "layer-stack", "transform",
    "build-up", "compare", "split-merge",
)


def _require_known_pattern(pattern: str | None) -> None:
    if pattern not in _PATTERNS:
        raise AnimateError(
            "animate pattern must be 'state-machine', 'pipeline', "
            "'layer-stack', 'transform', 'build-up', 'compare', or 'split-merge', "
            f"got {pattern!r}"
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
    parts_raw: list[str] = []
    branches_raw: list[str] = []
    caption: str | None = None
    direction: str | None = None
    from_value: str | None = None
    to_value: str | None = None
    whole_value: str | None = None
    left_value: str | None = None
    right_value: str | None = None
    source_value: str | None = None
    merged_value: str | None = None
    section: str | None = None

    lists = {
        "states": states_raw, "transitions": transitions_raw,
        "stages": stages_raw, "layers": layers_raw, "steps": steps_raw,
        "parts": parts_raw, "branches": branches_raw,
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
            elif name == "whole":
                whole_value = value
            elif name == "left":
                left_value = value
            elif name == "right":
                right_value = value
            elif name == "source":
                source_value = value
            elif name == "merged":
                merged_value = value
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
            or parts_raw or branches_raw or whole_value or left_value or right_value
            or source_value or merged_value
        ):
            raise AnimateError(
                "state-machine does not use 'before:'/'after:'/'caption:'/'stages:'/"
                "'layers:'/'steps:'/'direction:'/'from:'/'to:'/'whole:'/'parts:'/"
                "'left:'/'right:'/'source:'/'merged:'/'branches:'"
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
    elif pattern == "pipeline":
        if (
            before or after or states_raw or transitions_raw
            or caption or layers_raw or steps_raw or direction
            or from_value or to_value
            or parts_raw or branches_raw or whole_value or left_value or right_value
            or source_value or merged_value
        ):
            raise AnimateError(
                "pipeline does not use 'before:'/'after:'/'states:'/'transitions:'/"
                "'caption:'/'layers:'/'steps:'/'direction:'/'from:'/'to:'/'whole:'/"
                "'parts:'/'left:'/'right:'/'source:'/'merged:'/'branches:'"
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
            or parts_raw or branches_raw or whole_value or left_value or right_value
            or source_value or merged_value
        ):
            raise AnimateError(
                "layer-stack does not use 'before:'/'after:'/'states:'/'transitions:'/"
                "'caption:'/'stages:'/'steps:'/'from:'/'to:'/'whole:'/'parts:'/"
                "'left:'/'right:'/'source:'/'merged:'/'branches:'"
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
            or parts_raw or branches_raw or whole_value or left_value or right_value
            or source_value or merged_value
        ):
            raise AnimateError(
                "transform does not use 'before:'/'after:'/'direction:'/'states:'/"
                "'transitions:'/'caption:'/'stages:'/'layers:'/'whole:'/'parts:'/"
                "'left:'/'right:'/'source:'/'merged:'/'branches:'"
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
    elif pattern == "build-up":
        if (
            before or after or direction or states_raw or transitions_raw
            or caption or stages_raw or layers_raw or steps_raw
            or from_value or to_value or branches_raw
            or left_value or right_value or source_value or merged_value
        ):
            raise AnimateError(
                "build-up does not use 'before:'/'after:'/'direction:'/'states:'/"
                "'transitions:'/'caption:'/'stages:'/'layers:'/'steps:'/'from:'/"
                "'to:'/'left:'/'right:'/'source:'/'merged:'/'branches:'"
            )
        if not whole_value:
            raise AnimateError("build-up needs 'whole:'")
        if len(parts_raw) < 2:
            raise AnimateError("build-up needs at least 2 parts")
        if len(parts_raw) > 6:
            raise AnimateError("build-up takes at most 6 parts")
        parts: list[tuple[str, str]] = []
        for line in parts_raw:
            match = _STAGE.match(line)
            if not match:
                raise AnimateError(
                    f"build-up part {line!r} must be written as "
                    "'<name>: <what it contributes>'"
                )
            parts.append((match.group("name").strip(), match.group("change").strip()))
        return Animate(pattern=pattern, whole=whole_value, parts=parts)
    elif pattern == "compare":
        if (
            before or after or direction or states_raw or transitions_raw
            or caption or stages_raw or layers_raw
            or from_value or to_value or parts_raw or branches_raw
            or whole_value or source_value or merged_value
        ):
            raise AnimateError(
                "compare does not use 'before:'/'after:'/'direction:'/'states:'/"
                "'transitions:'/'caption:'/'stages:'/'layers:'/'from:'/'to:'/"
                "'whole:'/'parts:'/'source:'/'merged:'/'branches:'"
            )
        if not left_value or not right_value:
            raise AnimateError("compare needs both 'left:' and 'right:'")
        if not steps_raw:
            raise AnimateError("compare needs at least 1 step")
        if len(steps_raw) > 5:
            raise AnimateError("compare takes at most 5 steps")
        rows: list[tuple[str, str]] = []
        for line in steps_raw:
            match = _COMPARE_ROW.match(line)
            if not match:
                raise AnimateError(
                    f"compare row {line!r} must be written as '<left text> | <right text>'"
                )
            rows.append((match.group("left").strip(), match.group("right").strip()))
        return Animate(pattern=pattern, left=left_value, right=right_value, rows=rows)
    elif pattern == "split-merge":
        if (
            before or after or direction or states_raw or transitions_raw
            or caption or stages_raw or layers_raw or steps_raw
            or from_value or to_value or parts_raw
            or whole_value or left_value or right_value
        ):
            raise AnimateError(
                "split-merge does not use 'before:'/'after:'/'direction:'/'states:'/"
                "'transitions:'/'caption:'/'stages:'/'layers:'/'steps:'/'from:'/"
                "'to:'/'whole:'/'parts:'/'left:'/'right:'"
            )
        if not source_value or not merged_value:
            raise AnimateError("split-merge needs both 'source:' and 'merged:'")
        if len(branches_raw) < 2:
            raise AnimateError("split-merge needs at least 2 branches")
        if len(branches_raw) > 4:
            raise AnimateError("split-merge takes at most 4 branches")
        branches: list[tuple[str, str]] = []
        for line in branches_raw:
            match = _STAGE.match(line)
            if not match:
                raise AnimateError(
                    f"split-merge branch {line!r} must be written as "
                    "'<name>: <what it does>'"
                )
            branches.append((match.group("name").strip(), match.group("change").strip()))
        return Animate(
            pattern=pattern, source=source_value, merged=merged_value, branches=branches,
        )
    else:
        # The whitelist above admits exactly seven patterns and every one of
        # them is handled by a branch, so reaching here means a pattern was
        # added to the whitelist without a parse branch. Raise rather than
        # fall through: an earlier version ended in a bare `else` that parsed
        # the last pattern, which would silently mis-parse any newly
        # whitelisted name.
        raise AnimateError(f"animate pattern {pattern!r} has no parser branch")


_PIPE_BOX_WIDTH = 140
_PIPE_BOX_HEIGHT = 64
_PIPE_GAP = 56  # horizontal gap between stage boxes; also each connector's length
_PIPE_TOP_MARGIN = 24

_LAYER_WIDTH = 260
_LAYER_HEIGHT = 44
_LAYER_GAP = 12
_LAYER_TOP_MARGIN = 20
_LAYER_DWELL_MS = 700  # pause after a row's highlight lands, before the next
                       # row starts arriving -- gives real prose time to be
                       # read instead of the stack advancing as fast as each
                       # fade completes

_XFORM_BOX_WIDTH = 200
_XFORM_BOX_HEIGHT = 40
_XFORM_RUNG_GAP = 32  # vertical space between one step's rung and the next
_XFORM_TOP_MARGIN = 12

_BUILD_ROW_WIDTH = 320
_BUILD_ROW_HEIGHT = 40
_BUILD_ROW_GAP = 8
_BUILD_MARGIN = 12
_BUILD_DWELL_MS = 400  # pause after a part settles, before the next starts
                       # arriving -- gives real prose time to be read instead
                       # of the whole accumulating as fast as each fade completes

_CMP_ROW_HEIGHT = 52
_CMP_GUTTER = 28
_CMP_MARGIN = 12

_SPLIT_BOX_WIDTH = 152
_SPLIT_BOX_HEIGHT = 48
_SPLIT_SOURCE_HEIGHT = 36
_SPLIT_MARGIN = 12
_SPLIT_BRANCH_GAP = 24  # horizontal clearance between two adjacent branch boxes
_SPLIT_ROW_GAP = 44  # vertical space between source/branches and branches/merged

_STATE_BOX_HEIGHT = 44
_STATE_BOX_MIN_WIDTH = 96  # a two-letter state still reads as a box, not a chip
_STATE_BOX_PAD_X = 24  # horizontal padding inside a state box, around its label
_STATE_NAME_CHAR_WIDTH = 7.6  # rough px-per-character at the box label's 13px/600
                              # weight font. SVG cannot measure real text at render
                              # time, so a box's width is estimated from its
                              # authored string's length -- generous enough that
                              # real glyphs stay inside it. The old renderer used a
                              # fixed 130px box instead and clipped every longer name.
_STATE_RING_RADIUS = 76  # minimum radius of the closed track the marker rides.
                         # The actual radius grows with the state count and the
                         # widest box, so neighbours never collide -- see the
                         # chord calculation in _state_machine_html.
_STATE_BOX_GAP = 28  # clear space required between two adjacent boxes on the ring
_STATE_TRACK_MARGIN = 28  # space between the track's bounding box and the SVG edge,
                          # enough for a node box straddling the track plus its
                          # transition chip
_STATE_LABEL_CHIP_PAD_X = 8  # horizontal padding inside a label's background chip
_STATE_LABEL_CHIP_PAD_Y = 3  # vertical padding inside a label's background chip
_STATE_LABEL_CHAR_WIDTH = 7.2  # rough px-per-character at the label's 12px/600
                               # weight font -- same estimation caveat as
                               # _STATE_NAME_CHAR_WIDTH above
_STATE_MARKER_RADIUS = 7
_STATE_SEGMENT_MS = 900  # marker travel time for one transition
_STATE_DWELL_MS = 500  # pause at each state before the next transition begins
_STATE_VISITED_OPACITY = 0.14  # the faint accent wash a visited state settles to
                               # and keeps. Light enough that --color-fg stays
                               # legible on it (so the arrival inversion can be
                               # undone), strong enough to read as "been here".
                               # Mirrors --anim-visited-strength in layout.css,
                               # which the reduced-motion and print blocks use
                               # where no timeline runs to apply this.


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
    if anim.pattern == "pipeline":
        return _pipeline_html(anim, token)
    if anim.pattern == "layer-stack":
        return _layer_stack_html(anim, token)
    if anim.pattern == "transform":
        return _transform_html(anim, token)
    if anim.pattern == "build-up":
        return _build_up_html(anim, token)
    if anim.pattern == "compare":
        return _compare_html(anim, token)
    return _split_merge_html(anim, token)


def _ring_positions(count: int, cx: float, cy: float, radius: float) -> list[tuple[float, float]]:
    """Evenly spaced points on a circle, first one at the top, going clockwise.

    Starting at the top (rather than at angle 0, which is the 3 o'clock
    position) puts state[0] where a reader's eye lands first, and clockwise
    matches the direction people expect a cycle to run.
    """
    positions = []
    for i in range(count):
        angle = -math.pi / 2 + (2 * math.pi * i / count)
        positions.append((cx + radius * math.cos(angle), cy + radius * math.sin(angle)))
    return positions


def _arc_between(
    start: tuple[float, float], end: tuple[float, float], cx: float, cy: float
) -> tuple[float, float, float, float]:
    """Cubic control points approximating the circular arc from start to end.

    The marker rides the track by reusing the existing "path-segment" step kind,
    which interpolates a cubic Bezier through via1/via2 (see wireAnimations in
    course.js). A circular arc is not exactly a cubic, but the standard
    tangent-handle approximation is visually indistinguishable at these radii,
    and it means the track needs no new client-side machinery.

    Handle length k = 4/3 * tan(theta/4) is the classic minimal-error constant
    for approximating a circular arc of sweep theta with one cubic. Error grows
    sharply with sweep: measured against a true circle of radius 76, a 120-degree
    sweep (3 states) deviates 0.12px, but a 180-degree one (2 states) deviates
    1.4px -- visible as the arc bulging off the ring. _ARC_MAX_SWEEP caps this by
    splitting a wide sweep, so callers get a list of cubics rather than one.
    """
    ax, ay = start[0] - cx, start[1] - cy
    bx, by = end[0] - cx, end[1] - cy
    theta = math.atan2(ax * by - ay * bx, ax * bx + ay * by)
    if theta <= 0:
        theta += 2 * math.pi
    k = 4 / 3 * math.tan(theta / 4)
    # Tangent at each endpoint, rotated 90 degrees from the radius, scaled by k.
    return (
        start[0] - k * ay,
        start[1] + k * ax,
        end[0] + k * by,
        end[1] - k * bx,
    )


_ARC_MAX_SWEEP = math.pi * 2 / 3  # 120 degrees; see _arc_between's error note


def _rects_overlap(
    a: tuple[float, float, float, float], b: tuple[float, float, float, float]
) -> bool:
    """True if two (x, y, width, height) rectangles intersect."""
    return not (
        a[0] + a[2] <= b[0] or b[0] + b[2] <= a[0]
        or a[1] + a[3] <= b[1] or b[1] + b[3] <= a[1]
    )


def _arc_chain(
    start: tuple[float, float], end: tuple[float, float], cx: float, cy: float
) -> list[tuple[tuple[float, float], tuple[float, float], tuple[float, float]]]:
    """The arc from start to end as one or more cubics, each within _ARC_MAX_SWEEP.

    Returns [(control1, control2, endpoint), ...]; the caller already knows the
    start point. Splitting keeps a wide sweep (a 2-state machine's 180 degrees)
    from bulging visibly off the ring.
    """
    ax, ay = start[0] - cx, start[1] - cy
    bx, by = end[0] - cx, end[1] - cy
    theta = math.atan2(ax * by - ay * bx, ax * bx + ay * by)
    if theta <= 0:
        theta += 2 * math.pi
    pieces = max(1, math.ceil(theta / _ARC_MAX_SWEEP))
    radius = math.hypot(ax, ay)
    start_angle = math.atan2(ay, ax)
    out = []
    previous = start
    for i in range(1, pieces + 1):
        angle = start_angle + theta * i / pieces
        point = (cx + radius * math.cos(angle), cy + radius * math.sin(angle))
        c1x, c1y, c2x, c2y = _arc_between(previous, point, cx, cy)
        out.append(((c1x, c1y), (c2x, c2y), point))
        previous = point
    return out


def _state_machine_html(anim: Animate, token: str) -> str:
    """States sit on a closed track that the marker rides, one lap per cycle.

    The track is the shape: a process that returns to its first state is drawn
    as a ring like any other, rather than as a special-cased arc bolted above a
    straight row. A chain that never returns simply leaves its final arc
    undrawn, so the same geometry serves both.

    Three behaviours carry the meaning:

    - A state takes the accent as the marker arrives, then settles to a faint
      accent wash and KEEPS it (.anim__visited, a fill-opacity animation). The
      path travelled so far therefore stays readable at any moment, instead of
      each state flashing back to blank behind the marker.
    - Only the in-progress transition's label is visible. Each label fades in as
      its own segment begins and out as it ends, so N labels never compete for
      attention at once.
    - Box width derives from the authored state name, so a long name is not
      clipped.

    Movement reuses the "path-segment" step kind, whose via1/via2 cubic controls
    already exist for the old back-edge arc; each track segment is one such
    cubic (see _arc_between).
    """
    # The token's literal text must never appear in this function's return
    # value: blocks.restore() does an unconditional second substitution pass
    # keyed on the token, so an id containing it would be corrupted. Only the
    # token's ordinal digits are used to build element ids.
    token_seed = re.sub(r"\D", "", token) or "0"
    count = len(anim.states)
    rect_ids = [f"anim-state-rect-{token_seed}-{i}" for i in range(count)]
    text_ids = [f"anim-state-text-{token_seed}-{i}" for i in range(count)]
    label_ids = [f"anim-state-label-{token_seed}-{i}" for i in range(len(anim.transitions))]
    marker_id = f"anim-state-marker-{token_seed}"

    box_widths = [
        max(
            _STATE_BOX_MIN_WIDTH,
            len(name) * _STATE_NAME_CHAR_WIDTH + 2 * _STATE_BOX_PAD_X,
        )
        for name in anim.states
    ]

    # The ring must be big enough that adjacent boxes do not collide. Neighbours
    # sit 2*pi/count apart, so the chord between their centres is
    # 2*R*sin(pi/count); requiring that to exceed the two half-widths plus a gap
    # gives the minimum radius. A fixed radius was the first version's mistake:
    # it looked right for three states and overlapped badly at five or six.
    widest = max(box_widths)
    chord_needed = widest + _STATE_BOX_GAP
    radius = max(
        _STATE_RING_RADIUS,
        chord_needed / (2 * math.sin(math.pi / count)),
    )
    # The ring is laid out around a provisional origin; the viewBox is then
    # derived from where the content actually ended up (see the shift below).
    # Computing bounds up front instead would mean predicting each label's push
    # distance twice, and the first version of this function got that prediction
    # wrong -- labels clipped the SVG edge at several state counts.
    cx = cy = 0.0
    centers = _ring_positions(count, cx, cy, radius)

    # The track: one arc per AUTHORED transition, never one per adjacent pair.
    # A chain whose transitions do not cover every pair legitimately has a gap,
    # and closing the ring across it would draw an edge the course-writer never
    # wrote -- the standing rule that only authored transitions are ever drawn.
    # A cycle closes its own ring naturally, because its final authored
    # transition returns to the first state.
    #
    # Each arc is a separate <path> rather than one subpath chain, so a gap is a
    # real absence rather than a straight line closing it.
    def _cubic_at(p0, c1, c2, p3, t):
        mt = 1 - t
        return (
            mt ** 3 * p0[0] + 3 * mt ** 2 * t * c1[0] + 3 * mt * t ** 2 * c2[0] + t ** 3 * p3[0],
            mt ** 3 * p0[1] + 3 * mt ** 2 * t * c1[1] + 3 * mt * t ** 2 * c2[1] + t ** 3 * p3[1],
        )

    def _lerp(a, b, t):
        return (a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t)

    def _outside_box(point, box_x, box_y, box_w, box_h, margin):
        return (
            point[0] < box_x - margin or point[0] > box_x + box_w + margin
            or point[1] < box_y - margin or point[1] > box_y + box_h + margin
        )

    track_segments = []
    for from_state, to_state, _action in anim.transitions:
        from_i = anim.states.index(from_state)
        to_i = anim.states.index(to_state)
        start = centers[from_i]
        pieces = _arc_chain(start, centers[to_i], cx, cy)

        # The drawn arc stops short of the destination box rather than running to
        # its centre, so the arrowhead lands on the box's edge where it can be
        # seen. Only the LAST piece is trimmed; earlier ones are drawn whole.
        #
        # The stop point is where the curve first enters the box's own
        # rectangle (plus a small margin), not a fixed "half the box's width"
        # radius: a box is wider than it is tall, so a clearance sized off its
        # width stopped the arc far short whenever the approach was closer to
        # vertical -- the arc ended up floating 50-70px from the box it should
        # have pointed into. t is found by walking the curve rather than
        # solving analytically: a cubic's arc length has no closed form, and
        # 60 samples is well under a pixel at these radii.
        last_c1, last_c2, last_end = pieces[-1]
        piece_start = pieces[-2][2] if len(pieces) > 1 else start
        box_x = centers[to_i][0] - box_widths[to_i] / 2
        box_y = centers[to_i][1] - _STATE_BOX_HEIGHT / 2
        arrow_clearance = 6  # visible gap between the arrowhead's tip and the box edge
        # Binary search for the crossing rather than a coarse fixed step: a
        # linear scan's last "outside" SAMPLE can sit several pixels short of
        # the box's actual boundary between samples, which is what left the
        # arrow visibly floating short of its destination. 30 halvings is
        # comfortably under a millipixel at these coordinate magnitudes.
        outside_t, inside_t = 0.0, 1.0
        for _ in range(30):
            mid = (outside_t + inside_t) / 2
            point = _cubic_at(piece_start, last_c1, last_c2, last_end, mid)
            if _outside_box(
                point, box_x, box_y, box_widths[to_i], _STATE_BOX_HEIGHT,
                margin=arrow_clearance,
            ):
                outside_t = mid
            else:
                inside_t = mid
        trim_t = outside_t
        # de Casteljau split at trim_t. The leading sub-curve's controls are the
        # first interpolation point (p01) and the second-level one (q0); its end
        # is the third-level point, which is the curve's own value at trim_t.
        p01 = _lerp(piece_start, last_c1, trim_t)
        p12 = _lerp(last_c1, last_c2, trim_t)
        q0 = _lerp(p01, p12, trim_t)
        tip = _cubic_at(piece_start, last_c1, last_c2, last_end, trim_t)

        d = [f"M {start[0]:.1f} {start[1]:.1f}"]
        for control1, control2, endpoint in pieces[:-1]:
            d.append(
                f"C {control1[0]:.1f} {control1[1]:.1f}, "
                f"{control2[0]:.1f} {control2[1]:.1f}, "
                f"{endpoint[0]:.1f} {endpoint[1]:.1f}"
            )
        d.append(
            f"C {p01[0]:.1f} {p01[1]:.1f}, {q0[0]:.1f} {q0[1]:.1f}, "
            f"{tip[0]:.1f} {tip[1]:.1f}"
        )
        track_segments.append(
            f'<path class="anim__state-track" fill="none" d="{" ".join(d)}" '
            f'marker-end="url(#anim-arrowhead-{token_seed})"></path>'
        )
    track_html = "".join(track_segments)

    # The arrowhead is shared by every arc, so a reader sees each transition's
    # direction without having to infer it from the marker's motion.
    defs_html = (
        f'<defs><marker id="anim-arrowhead-{token_seed}" markerWidth="8" '
        f'markerHeight="8" refX="7" refY="4" orient="auto">'
        f'<path class="anim__state-arrowhead" d="M0,0 L8,4 L0,8 Z"></path>'
        f"</marker></defs>"
    )

    # A dot plus a soft halo. Both circles sit at the group's own origin and the
    # GROUP carries the cx/cy the timeline drives, so one path-segment step moves
    # both -- no second animation target and no new key in the step contract.
    marker_html = (
        f'<g class="anim__state-marker">'
        f'<circle id="{marker_id}" class="anim__state-marker-dot" '
        f'cx="{centers[0][0]:.1f}" cy="{centers[0][1]:.1f}" '
        f'r="{_STATE_MARKER_RADIUS}"></circle>'
        f'<circle id="{marker_id}-glow" class="anim__state-marker-glow" '
        f'cx="{centers[0][0]:.1f}" cy="{centers[0][1]:.1f}" '
        f'r="{_STATE_MARKER_RADIUS * 2}"></circle>'
        "</g>"
    )

    # Boxes paint AFTER the marker so the marker passes BEHIND them: SVG has no
    # z-index, document order is paint order, and a marker drawn last would
    # cover each state's label as it went by.
    #
    # Each box is two stacked rects: an opaque base that hides the track and the
    # marker behind it, and a wash rect above it whose fill-opacity the timeline
    # animates. Animating opacity on a single rect would fade the box out
    # instead, revealing the track through it.
    # Every drawn rectangle's extent, accumulated so the viewBox can be derived
    # from real content rather than predicted.
    extents: list[tuple[float, float, float, float]] = []

    boxes_html = []
    box_rects: list[tuple[float, float, float, float]] = []
    for i, name in enumerate(anim.states):
        width = box_widths[i]
        x = centers[i][0] - width / 2
        y = centers[i][1] - _STATE_BOX_HEIGHT / 2
        extents.append((x, y, x + width, y + _STATE_BOX_HEIGHT))
        box_rects.append((x, y, width, _STATE_BOX_HEIGHT))
        label_x, label_y = centers[i][0], centers[i][1] + 5
        # Two stacked <text> elements, not one whose `fill` is animated between
        # "var(--color-fg)" and "var(--color-accent-contrast)". anime.js only
        # recognises hex/rgb()/rgba()/hsl() as colour values (see its isCol
        # helper); a bare var() reference matches none of those, falls through
        # decomposeRawValue's number path, and silently becomes the literal 0 --
        # rendering as black and never restoring, which is what made every
        # state's label go dark and stay dark after the first lap. Animating
        # OPACITY between two pre-coloured, stacked texts sidesteps the colour
        # pipeline entirely; opacity is a plain number anime.js handles natively.
        boxes_html.append(
            f'<g class="anim__state-box">'
            f'<rect class="anim__state-base" x="{x:.1f}" y="{y:.1f}" '
            f'width="{width:.1f}" height="{_STATE_BOX_HEIGHT}" rx="10"></rect>'
            f'<rect class="anim__state-rect anim__visited" id="{rect_ids[i]}" '
            f'x="{x:.1f}" y="{y:.1f}" '
            f'width="{width:.1f}" height="{_STATE_BOX_HEIGHT}" rx="10" '
            f'fill="var(--color-accent)" fill-opacity="0"></rect>'
            f'<text class="anim__state-name" '
            f'x="{label_x:.1f}" y="{label_y:.1f}" '
            f'fill="var(--color-fg)">{html.escape(name)}</text>'
            f'<text class="anim__state-name anim__state-name-inverted" '
            f'id="{text_ids[i]}" '
            f'x="{label_x:.1f}" y="{label_y:.1f}" opacity="0" '
            f'fill="var(--color-accent-contrast)">{html.escape(name)}</text>'
            "</g>"
        )
    # Labels paint LAST: authored prose stays legible above everything. Each sits
    # at the midpoint of its own arc, pushed far enough outward that its chip
    # clears the boxes -- which straddle the ring, so a label only just outside
    # the radius would sit on top of them.
    labels_html = []
    placed_chips: list[tuple[float, float, float, float]] = []
    for i, (from_state, to_state, action) in enumerate(anim.transitions):
        from_i = anim.states.index(from_state)
        to_i = anim.states.index(to_state)
        chip_width = len(action) * _STATE_LABEL_CHAR_WIDTH + 2 * _STATE_LABEL_CHIP_PAD_X
        chip_height = 12 + 2 * _STATE_LABEL_CHIP_PAD_Y
        # Direction from the ring's centre to the arc's midpoint. For a 2-state
        # machine the two centres are diametrically opposite, so their midpoint
        # IS the centre and the direction is undefined; fall back to the
        # perpendicular of the chord, which sends the two labels to opposite
        # sides instead of stacking them both at the centre.
        mid_x = (centers[from_i][0] + centers[to_i][0]) / 2 - cx
        mid_y = (centers[from_i][1] + centers[to_i][1]) / 2 - cy
        length = math.hypot(mid_x, mid_y)
        if length < 1e-6:
            chord_x = centers[to_i][0] - centers[from_i][0]
            chord_y = centers[to_i][1] - centers[from_i][1]
            chord_length = math.hypot(chord_x, chord_y) or 1.0
            mid_x, mid_y = -chord_y / chord_length, chord_x / chord_length
            length = 1.0
        unit_x, unit_y = mid_x / length, mid_y / length
        # Sit the chip just outside the ring, then push it out only as far as an
        # actual collision demands. Inflating the push by the chip's own length
        # up front (an earlier version did) sends a long label flying: a
        # 22-character chip on a radius-88 ring was pushed 244px out, three times
        # the ring's size, dragging the viewBox with it and squashing the diagram
        # into a corner.
        push = radius + chip_height / 2 + 10
        lx = cx + unit_x * push
        ly = cy + unit_y * push
        for _attempt in range(24):
            chip_box = (
                lx - chip_width / 2, ly - chip_height / 2, chip_width, chip_height,
            )
            blocked = any(
                _rects_overlap(chip_box, (bx, by, bw, bh))
                for bx, by, bw, bh in box_rects
            ) or any(
                _rects_overlap(chip_box, placed) for placed in placed_chips
            )
            if not blocked:
                break
            push += 6
            lx = cx + unit_x * push
            ly = cy + unit_y * push
        placed_chips.append(
            (lx - chip_width / 2, ly - chip_height / 2, chip_width, chip_height)
        )
        extents.append((
            lx - chip_width / 2, ly - chip_height / 2,
            lx + chip_width / 2, ly + chip_height / 2,
        ))
        labels_html.append(
            f'<g class="anim__state-transition-label-group" id="{label_ids[i]}" '
            f'opacity="0">'
            f'<rect class="anim__state-transition-label-bg" '
            f'x="{lx - chip_width / 2:.1f}" y="{ly - chip_height / 2:.1f}" '
            f'width="{chip_width:.1f}" height="{chip_height:.1f}" rx="4"></rect>'
            f'<text class="anim__state-transition-label" '
            f'x="{lx:.1f}" y="{ly + 4:.1f}">{html.escape(action)}</text>'
            "</g>"
        )

    # Timeline. Each transition is one lap segment: label in, marker travels the
    # arc, arriving state takes the accent and holds the wash, label out.
    steps_json: list[dict] = []
    for i, (from_state, to_state, _action) in enumerate(anim.transitions):
        from_i = anim.states.index(from_state)
        to_i = anim.states.index(to_state)
        start = centers[from_i]
        end = centers[to_i]
        pieces = _arc_chain(start, end, cx, cy)

        steps_json.append({
            "targets": [f"#{label_ids[i]}"],
            "props": {"opacity": [0, 1]},
            "duration": 200,
        })
        # A wide sweep is split into several cubics (see _arc_chain), each its
        # own path-segment step running back-to-back. Splitting the travel this
        # way needs no new client-side machinery, and the segments share the
        # transition's total duration so travel speed is unchanged.
        piece_ms = _STATE_SEGMENT_MS / len(pieces)
        piece_start = start
        for piece_index, (control1, control2, endpoint) in enumerate(pieces):
            steps_json.append({
                "kind": "path-segment",
                "marker": f"#{marker_id}, #{marker_id}-glow",
                "from": [round(piece_start[0], 1), round(piece_start[1], 1)],
                "to": [round(endpoint[0], 1), round(endpoint[1], 1)],
                "via1": [round(control1[0], 1), round(control1[1], 1)],
                "via2": [round(control2[0], 1), round(control2[1], 1)],
                "duration": round(piece_ms),
                # Ease in on the first piece and out on the last, but run the
                # middle at a constant rate: easing every piece would make the
                # marker stutter at each internal join.
                "ease": (
                    "inOutQuad" if len(pieces) == 1
                    else "inQuad" if piece_index == 0
                    else "outQuad" if piece_index == len(pieces) - 1
                    else "linear"
                ),
                "position": None,
            })
            piece_start = endpoint
        # Arrival is a full-strength accent flash, so the eye is drawn to the
        # state the marker just reached.
        steps_json.append({
            "targets": [f"#{rect_ids[to_i]}"],
            "props": {"fillOpacity": [0, 1]},
            "duration": 300,
            "position": "-=260",
        })
        # The inverted (accent-contrast) copy of the label fades in on the same
        # clock as the flash: --color-fg on a solid accent measures 1.82:1 to
        # 3.83:1 across the themes, below the 4.5:1 floor. Animating opacity on
        # a pre-coloured stacked <text>, rather than animating `fill` itself,
        # because anime.js cannot interpolate a bare var() reference as a
        # colour -- see the boxes_html comment above.
        steps_json.append({
            "targets": [f"#{text_ids[to_i]}"],
            "props": {"opacity": [0, 1]},
            "duration": 300,
            # "<<" starts together with the PREVIOUS step; a bare "<" instead
            # starts right after it ENDS (anime.js v4's actual semantics --
            # counter to what the single-bracket name suggests), which silently
            # serialised every one of this function's "run alongside" steps and
            # was the real cause of labels drifting later lap over lap.
            "position": "<<",
        })
        # The flash then settles to the faint wash and KEEPS it -- no later step
        # animates it back down mid-lap. That is the whole point: the path
        # travelled so far stays visible instead of each state flashing back to
        # blank behind the marker. Only the trailing reset clears it, so the next
        # lap starts clean. The inverted label copy fades back out, uncovering
        # the plain --color-fg one beneath it, legible again once the fill is
        # this pale.
        steps_json.append({
            "targets": [f"#{rect_ids[to_i]}"],
            "props": {"fillOpacity": _STATE_VISITED_OPACITY},
            "duration": _STATE_DWELL_MS,
        })
        steps_json.append({
            "targets": [f"#{text_ids[to_i]}"],
            "props": {"opacity": 0},
            "duration": 200,
            "position": "<<",
        })
        # The label leaves with its own segment, so exactly one is ever visible.
        steps_json.append({
            "targets": [f"#{label_ids[i]}"],
            "props": {"opacity": [1, 0]},
            "duration": 200,
            "position": "<<",
        })

    # Every animated property is reset before the loop restarts. anime.js
    # compounds absolute values across laps otherwise: the wash would already be
    # at full opacity when the next lap tried to animate it up again, and the
    # inverted label colour would sit on an idle box.
    steps_json.append({
        "kind": "set",
        "targets": [f"#{r}" for r in rect_ids],
        "props": {"fillOpacity": 0},
    })
    steps_json.append({
        "kind": "set",
        "targets": [f"#{t}" for t in text_ids],
        "props": {"opacity": 0},
    })
    steps_json.append({
        "kind": "set",
        "targets": [f"#{l}" for l in label_ids],
        "props": {"opacity": 0},
    })
    # The marker only needs snapping back when the authored transitions do NOT
    # return it to the first state. A true cycle ends its lap where it began, so
    # emitting the reset anyway would be a no-op that reads, to anyone auditing
    # the timeline, like an invisible unauthored "last -> first" jump.
    ends_where_it_started = (
        anim.states.index(anim.transitions[-1][1]) == 0
    )
    if not ends_where_it_started:
        steps_json.append({
            "kind": "set",
            "targets": [f"#{marker_id}", f"#{marker_id}-glow"],
            "props": {"cx": round(centers[0][0], 1), "cy": round(centers[0][1], 1)},
        })

    timeline = {"loop": True, "loopDelay": 800, "steps": steps_json}
    timeline_json = _timeline_island_json(timeline)

    static_lines = "".join(
        f"<li>{html.escape(f)} — {html.escape(a)} — {html.escape(t)}</li>"
        for f, t, a in anim.transitions
    )
    static_fallback = f'<ol class="anim__state-steps-static">{static_lines}</ol>'

    # The viewBox is derived from where the content actually landed, plus the
    # marker's glow (which straddles the ring and can reach past every box when
    # a state sits at an extreme) and a uniform margin. The ring was laid out
    # around origin (0, 0), so these bounds are negative on two sides; rather
    # than translate every coordinate, the viewBox's own origin is moved.
    left = min(e[0] for e in extents)
    top = min(e[1] for e in extents)
    right = max(e[2] for e in extents)
    bottom = max(e[3] for e in extents)
    glow = _STATE_MARKER_RADIUS * 2
    left = min(left, -radius - glow)
    top = min(top, -radius - glow)
    right = max(right, radius + glow)
    bottom = max(bottom, radius + glow)
    view_x = left - _STATE_TRACK_MARGIN
    view_y = top - _STATE_TRACK_MARGIN
    total_width = (right - left) + 2 * _STATE_TRACK_MARGIN
    total_height = (bottom - top) + 2 * _STATE_TRACK_MARGIN

    # Paint order, which SVG derives from document order alone:
    #   track -> marker -> boxes -> labels
    # The marker precedes the boxes so it passes BEHIND them, reading as a token
    # entering each box rather than covering the box's own label. The labels
    # come last so authored prose is never occluded.
    return (
        '<div class="anim anim--state-machine">'
        f'<svg class="anim__state-machine" dir="ltr" '
        f'width="{total_width:.0f}" height="{total_height:.0f}" '
        f'viewBox="{view_x:.1f} {view_y:.1f} {total_width:.1f} {total_height:.1f}">'
        f"{track_html}{marker_html}{''.join(boxes_html)}{''.join(labels_html)}</svg>"
        f'<script type="application/json" class="anim__timeline">{timeline_json}</script>'
        f"{static_fallback}</div>"
    )


def _pipeline_html(anim: Animate, token: str) -> str:
    """Stages light up left-to-right; each connector draws itself between them.

    Only one stage carries the accent at a time (diagram-design's focal rule):
    the arriving stage goes accent, and the previous one is returned to idle in
    the same step, so the reader's eye always has exactly one target.
    """
    token_seed = re.sub(r"\D", "", token) or "0"
    rect_ids = [f"anim-pipe-rect-{token_seed}-{i}" for i in range(len(anim.stages))]
    name_text_ids = [f"anim-pipe-name-{token_seed}-{i}" for i in range(len(anim.stages))]
    change_text_ids = [f"anim-pipe-change-{token_seed}-{i}" for i in range(len(anim.stages))]
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
        # Two rects (idle base + accent overlay whose OPACITY is animated, never
        # its FILL between two var() tokens -- animejs's colour detector only
        # recognises hex/rgb()/rgba()/hsl(), so a bare var(--anim-pipe-active)
        # reference silently decomposes to the literal number 0 and the stage
        # never actually highlighted in a real browser) and two stacked text
        # pairs per line, the same "plain + pre-inverted, opacity-swapped"
        # mechanism state-machine uses, since a solid accent fill also fails
        # contrast for both --color-fg (3.33:1/2.00:1 across themes) and
        # --color-muted (1.21:1/1.04:1) -- a defect invisible until the fill
        # animation actually worked.
        boxes_html.append(
            f'<g class="anim__pipe-stage">'
            f'<rect class="anim__pipe-box" x="{x:g}" '
            f'y="{_PIPE_TOP_MARGIN}" width="{box_width:g}" '
            f'height="{_PIPE_BOX_HEIGHT}" rx="8" '
            f'fill="var(--anim-pipe-idle)"></rect>'
            f'<rect class="anim__pipe-box anim__pipe-box-active" id="{rect_ids[i]}" '
            f'x="{x:g}" y="{_PIPE_TOP_MARGIN}" width="{box_width:g}" '
            f'height="{_PIPE_BOX_HEIGHT}" rx="8" '
            f'fill="var(--anim-pipe-active)" opacity="0"></rect>'
            f'<text class="anim__pipe-name" x="{center_x:g}" '
            f'y="{box_center_y - 4:g}" text-anchor="middle" '
            f'fill="var(--color-fg)">{html.escape(name)}</text>'
            f'<text class="anim__pipe-name anim__text-on-accent" '
            f'id="{name_text_ids[i]}" x="{center_x:g}" '
            f'y="{box_center_y - 4:g}" text-anchor="middle" opacity="0">'
            f'{html.escape(name)}</text>'
            f'<text class="anim__pipe-change" x="{center_x:g}" '
            f'y="{box_center_y + 14:g}" text-anchor="middle" '
            f'fill="var(--color-muted)">{html.escape(change)}</text>'
            f'<text class="anim__pipe-change anim__text-on-accent" '
            f'id="{change_text_ids[i]}" x="{center_x:g}" '
            f'y="{box_center_y + 14:g}" text-anchor="middle" opacity="0">'
            f'{html.escape(change)}</text>'
            f'</g>'
        )

    steps_json: list[dict] = []
    for i in range(len(anim.stages)):
        steps_json.append({
            "targets": [f"#{rect_ids[i]}", f"#{name_text_ids[i]}", f"#{change_text_ids[i]}"],
            "props": {"opacity": [0, 1]},
            "duration": 400,
            "ease": "outQuad",
        })
        if i > 0:
            steps_json.append({
                "targets": [
                    f"#{rect_ids[i - 1]}",
                    f"#{name_text_ids[i - 1]}",
                    f"#{change_text_ids[i - 1]}",
                ],
                "props": {"opacity": 0},
                "duration": 400,
                "ease": "outQuad",
                # "<<" starts together with the reveal above; a bare "<" would
                # wait for it to finish first (anime.js v4's real semantics).
                "position": "<<",
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
        "kind": "set",
        "targets": [f"#{r}" for r in rect_ids] + [f"#{t}" for t in name_text_ids]
        + [f"#{t}" for t in change_text_ids],
        "props": {"opacity": 0},
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

    Each row is one <g>, invisible at rest, that fades in as a WHOLE unit --
    box, name, and description together -- rather than the box appearing first
    and its text being highlighted separately. There is nothing to read until
    a row's own reveal step fires.
    """
    token_seed = re.sub(r"\D", "", token) or "0"
    count = len(anim.layers)
    row_group_ids = [f"anim-layer-row-{token_seed}-{i}" for i in range(count)]
    active_rect_ids = [f"anim-layer-active-{token_seed}-{i}" for i in range(count)]
    name_text_ids = [f"anim-layer-name-{token_seed}-{i}" for i in range(count)]
    adds_text_ids = [f"anim-layer-adds-{token_seed}-{i}" for i in range(count)]
    total_height = _LAYER_TOP_MARGIN * 2 + count * _LAYER_HEIGHT + (count - 1) * _LAYER_GAP
    total_width = _LAYER_WIDTH + _LAYER_TOP_MARGIN * 2

    def layer_y(i: int) -> float:
        # i == 0 is the bottom layer: count it down from the stack's base.
        from_top = count - 1 - i
        return _LAYER_TOP_MARGIN + from_top * (_LAYER_HEIGHT + _LAYER_GAP)

    rows_html = []
    for i, (name, adds) in enumerate(anim.layers):
        y = layer_y(i)
        name_x = _LAYER_TOP_MARGIN + 12
        adds_x = _LAYER_TOP_MARGIN + _LAYER_WIDTH - 12
        text_y = y + _LAYER_HEIGHT / 2 + 4
        # The row's own reveal (the GROUP's opacity, 0->1) is a separate
        # property from its accent HIGHLIGHT (a second, stacked rect whose
        # opacity is animated, never a `fill` tween between two var() tokens --
        # animejs's colour detector only recognises hex/rgb()/rgba()/hsl(), so
        # the highlight never actually rendered in a real browser). Labels get
        # the same plain + pre-inverted, opacity-swapped pair state-machine and
        # pipeline use, since --color-fg/--color-muted both fail contrast
        # against a solid --color-accent fill.
        rows_html.append(
            f'<g class="anim__layer-row" id="{row_group_ids[i]}" opacity="0">'
            f'<rect class="anim__layer-box" '
            f'x="{_LAYER_TOP_MARGIN}" y="{y:g}" width="{_LAYER_WIDTH}" '
            f'height="{_LAYER_HEIGHT}" rx="6" fill="var(--anim-layer-idle)"></rect>'
            f'<rect class="anim__layer-box anim__layer-box-active" '
            f'id="{active_rect_ids[i]}" '
            f'x="{_LAYER_TOP_MARGIN}" y="{y:g}" width="{_LAYER_WIDTH}" '
            f'height="{_LAYER_HEIGHT}" rx="6" fill="var(--anim-layer-active)" '
            f'opacity="0"></rect>'
            f'<text class="anim__layer-name" x="{name_x}" y="{text_y:g}" '
            f'fill="var(--color-fg)">{html.escape(name)}</text>'
            f'<text class="anim__layer-name anim__text-on-accent" '
            f'id="{name_text_ids[i]}" x="{name_x}" y="{text_y:g}" opacity="0">'
            f'{html.escape(name)}</text>'
            f'<text class="anim__layer-adds" x="{adds_x}" y="{text_y:g}" '
            f'text-anchor="end" fill="var(--color-muted)">{html.escape(adds)}</text>'
            f'<text class="anim__layer-adds anim__text-on-accent" '
            f'id="{adds_text_ids[i]}" x="{adds_x}" y="{text_y:g}" '
            f'text-anchor="end" opacity="0">{html.escape(adds)}</text>'
            f'</g>'
        )

    order = range(count) if anim.direction == "up" else range(count - 1, -1, -1)
    steps_json: list[dict] = []
    for position, i in enumerate(order):
        # The whole row (box, name, description) fades in together, so there
        # is nothing to read -- not even a plain box -- until this fires. The
        # PREVIOUS row's highlight fades out on this SAME clock (both "<<" off
        # this step, added right after it), so the handoff from one active
        # row to the next reads as one continuous moment rather than a fade-out
        # followed by a gap followed by a fade-in.
        steps_json.append({
            "targets": [f"#{row_group_ids[i]}"],
            "props": {"opacity": [0, 1]},
            "duration": 500,
            "ease": "outQuad",
        })
        if position > 0:
            previous = list(order)[position - 1]
            steps_json.append({
                "targets": [
                    f"#{active_rect_ids[previous]}",
                    f"#{name_text_ids[previous]}",
                    f"#{adds_text_ids[previous]}",
                ],
                "props": {"opacity": 0},
                "duration": 500,
                "ease": "outQuad",
                "position": "<<",
            })
        steps_json.append({
            "targets": [f"#{active_rect_ids[i]}", f"#{name_text_ids[i]}", f"#{adds_text_ids[i]}"],
            "props": {"opacity": [0, 1]},
            "duration": 500,
            "ease": "outQuad",
            # "<<" starts together with the row reveal above; a bare "<"
            # would wait for it to finish first (anime.js v4's real semantics).
            "position": "<<",
        })
        # A dwell after the highlight lands, before the next row starts
        # arriving, so a real sentence of prose has time to be read rather
        # than the stack advancing as fast as each fade completes. Appended
        # with no position, so it starts only once every step above (whichever
        # ends latest) has finished, and the NEXT iteration's row reveal then
        # appends after this, inheriting the same "no position" append point.
        steps_json.append({
            "targets": [f"#{active_rect_ids[i]}"],
            "props": {"opacity": 1},
            "duration": _LAYER_DWELL_MS,
        })

    steps_json.append({
        "kind": "set",
        "targets": (
            [f"#{g}" for g in row_group_ids]
            + [f"#{r}" for r in active_rect_ids]
            + [f"#{t}" for t in name_text_ids]
            + [f"#{t}" for t in adds_text_ids]
        ),
        "props": {"opacity": 0},
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


def _build_up_html(anim: Animate, token: str) -> str:
    """A whole assembling from its parts, in authored order, top to bottom.

    Each part fades in as a WHOLE unit -- box and both text lines together,
    nothing showing beforehand -- then holds the faint accent wash it settles
    to. Unlike layer-stack, where only one tier is ever "active" at a time,
    every part here stays lit once it has joined the whole, so the
    accumulated structure reads at a glance.
    """
    token_seed = re.sub(r"\D", "", token) or "0"
    count = len(anim.parts)
    part_group_ids = [f"anim-build-part-{token_seed}-{i}" for i in range(count)]
    rect_ids = [f"anim-build-rect-{token_seed}-{i}" for i in range(count)]
    name_text_ids = [f"anim-build-name-{token_seed}-{i}" for i in range(count)]
    contrib_text_ids = [f"anim-build-contrib-{token_seed}-{i}" for i in range(count)]

    row_width = max(
        _BUILD_ROW_WIDTH,
        max(
            (len(name) + len(contrib)) * _STATE_LABEL_CHAR_WIDTH
            for name, contrib in anim.parts
        ) + 4 * _STATE_LABEL_CHIP_PAD_X,
    )
    total_width = row_width + _BUILD_MARGIN * 2
    total_height = (
        _BUILD_MARGIN * 2 + count * _BUILD_ROW_HEIGHT + (count - 1) * _BUILD_ROW_GAP
    )

    rows_html = []
    for i, (name, contrib) in enumerate(anim.parts):
        y = _BUILD_MARGIN + i * (_BUILD_ROW_HEIGHT + _BUILD_ROW_GAP)
        name_x = _BUILD_MARGIN + 12
        contrib_x = _BUILD_MARGIN + row_width - 12
        text_y = y + _BUILD_ROW_HEIGHT / 2 + 4
        # The GROUP's own opacity (0->1) reveals the whole part -- box and both
        # text lines together -- as one unit; there is nothing to read before
        # this fires. The stacked rect inside it is the accent wash whose
        # FILL-OPACITY the timeline separately animates once the group is
        # already visible -- same .anim__visited convention as state-machine,
        # so the settle never needs a `fill` tween between two var() tokens,
        # which animejs's colour detector cannot interpolate.
        rows_html.append(
            f'<g class="anim__build-part" id="{part_group_ids[i]}" opacity="0">'
            f'<rect class="anim__build-base" x="{_BUILD_MARGIN}" y="{y:g}" '
            f'width="{row_width:g}" height="{_BUILD_ROW_HEIGHT}" rx="8"></rect>'
            f'<rect class="anim__build-rect anim__visited" id="{rect_ids[i]}" '
            f'x="{_BUILD_MARGIN}" y="{y:g}" width="{row_width:g}" '
            f'height="{_BUILD_ROW_HEIGHT}" rx="8" fill="var(--color-accent)" '
            f'fill-opacity="0"></rect>'
            f'<text class="anim__build-name" x="{name_x}" y="{text_y:g}" '
            f'fill="var(--color-fg)">{html.escape(name)}</text>'
            f'<text class="anim__build-name anim__text-on-accent" '
            f'id="{name_text_ids[i]}" x="{name_x}" y="{text_y:g}" opacity="0">'
            f'{html.escape(name)}</text>'
            f'<text class="anim__build-contrib" x="{contrib_x}" y="{text_y:g}" '
            f'text-anchor="end" fill="var(--color-muted)">{html.escape(contrib)}</text>'
            f'<text class="anim__build-contrib anim__text-on-accent" '
            f'id="{contrib_text_ids[i]}" x="{contrib_x}" y="{text_y:g}" '
            f'text-anchor="end" opacity="0">{html.escape(contrib)}</text>'
            f'</g>'
        )

    steps_json: list[dict] = []
    for i in range(count):
        # The whole part fades in as one unit -- nothing shows until this
        # fires.
        steps_json.append({
            "targets": [f"#{part_group_ids[i]}"],
            "props": {"opacity": [0, 1]},
            "duration": 400,
            "ease": "outQuad",
        })
        steps_json.append({
            "targets": [f"#{rect_ids[i]}"],
            "props": {"fillOpacity": [0, 1]},
            "duration": 400,
            "ease": "outQuad",
            "position": "<<",
        })
        steps_json.append({
            "targets": [f"#{name_text_ids[i]}", f"#{contrib_text_ids[i]}"],
            "props": {"opacity": [0, 1]},
            "duration": 400,
            "ease": "outQuad",
            "position": "<<",
        })
        steps_json.append({
            "targets": [f"#{rect_ids[i]}"],
            "props": {"fillOpacity": _STATE_VISITED_OPACITY},
            "duration": 400,
        })
        steps_json.append({
            "targets": [f"#{name_text_ids[i]}", f"#{contrib_text_ids[i]}"],
            "props": {"opacity": 0},
            "duration": 250,
            "position": "<<",
        })
        # A dwell before the next part starts arriving, so a real phrase has
        # time to be read rather than the whole accumulating as fast as each
        # fade completes. Appended with no position, so it starts only once
        # every step above has finished.
        steps_json.append({
            "targets": [f"#{part_group_ids[i]}"],
            "props": {"opacity": 1},
            "duration": _BUILD_DWELL_MS,
        })

    steps_json.append({
        "kind": "set", "targets": [f"#{g}" for g in part_group_ids], "props": {"opacity": 0},
    })
    steps_json.append({
        "kind": "set", "targets": [f"#{r}" for r in rect_ids], "props": {"fillOpacity": 0},
    })
    steps_json.append({
        "kind": "set",
        "targets": [f"#{t}" for t in name_text_ids] + [f"#{t}" for t in contrib_text_ids],
        "props": {"opacity": 0},
    })

    timeline_json = _timeline_island_json(
        {"loop": True, "loopDelay": 900, "steps": steps_json}
    )
    static_lines = "".join(
        f"<li>{html.escape(n)} — {html.escape(c)}</li>" for n, c in anim.parts
    )
    return (
        '<div class="anim anim--build-up">'
        f'<svg class="anim__build-up" dir="ltr" '
        f'width="{total_width:g}" height="{total_height:g}" '
        f'viewBox="0 0 {total_width:g} {total_height:g}">'
        f"{''.join(rows_html)}</svg>"
        f'<script type="application/json" class="anim__timeline">{timeline_json}</script>'
        f'<ol class="anim__build-static">{static_lines}</ol></div>'
    )


def _compare_html(anim: Animate, token: str) -> str:
    """Two tracks advancing in lockstep, so the contrast lands row by row.

    Both columns' boxes flash the accent TOGETHER on the same row, then fade
    back to idle -- unlike build-up or state-machine's visited wash, a
    comparison's point is the momentary contrast at each row, not an
    accumulating structure, so nothing here is meant to stay lit.
    """
    token_seed = re.sub(r"\D", "", token) or "0"
    count = len(anim.rows)
    left_rect_ids = [f"anim-cmp-left-{token_seed}-{i}" for i in range(count)]
    right_rect_ids = [f"anim-cmp-right-{token_seed}-{i}" for i in range(count)]
    left_active_ids = [f"anim-cmp-left-active-{token_seed}-{i}" for i in range(count)]
    right_active_ids = [f"anim-cmp-right-active-{token_seed}-{i}" for i in range(count)]
    left_text_ids = [f"anim-cmp-left-text-{token_seed}-{i}" for i in range(count)]
    right_text_ids = [f"anim-cmp-right-text-{token_seed}-{i}" for i in range(count)]
    left_inverted_ids = [f"anim-cmp-left-inverted-{token_seed}-{i}" for i in range(count)]
    right_inverted_ids = [f"anim-cmp-right-inverted-{token_seed}-{i}" for i in range(count)]

    col_width = max(
        _CMP_ROW_HEIGHT * 3,
        max(
            max(len(lt), len(rt)) for lt, rt in anim.rows
        ) * _STATE_LABEL_CHAR_WIDTH + 4 * _STATE_LABEL_CHIP_PAD_X,
    )
    header_height = 24
    total_width = col_width * 2 + _CMP_GUTTER + _CMP_MARGIN * 2
    total_height = (
        _CMP_MARGIN + header_height + count * _CMP_ROW_HEIGHT
        + (count - 1) * 8 + _CMP_MARGIN
    )
    left_x = _CMP_MARGIN
    right_x = _CMP_MARGIN + col_width + _CMP_GUTTER
    divider_x = left_x + col_width + _CMP_GUTTER / 2

    headers_html = (
        f'<text class="anim__cmp-heading" x="{left_x + col_width / 2:g}" '
        f'y="{_CMP_MARGIN + 14:g}" text-anchor="middle">{html.escape(anim.left)}</text>'
        f'<text class="anim__cmp-heading" x="{right_x + col_width / 2:g}" '
        f'y="{_CMP_MARGIN + 14:g}" text-anchor="middle">{html.escape(anim.right)}</text>'
        f'<line class="anim__cmp-divider" x1="{divider_x:g}" y1="{_CMP_MARGIN:g}" '
        f'x2="{divider_x:g}" y2="{total_height - _CMP_MARGIN:g}"></line>'
    )

    def cell(x: float, y: float, text: str, rect_id: str, active_id: str, inv_id: str) -> str:
        text_x = x + col_width / 2
        text_y = y + _CMP_ROW_HEIGHT / 2 + 4
        return (
            f'<rect class="anim__cmp-box" id="{rect_id}" x="{x:g}" y="{y:g}" '
            f'width="{col_width:g}" height="{_CMP_ROW_HEIGHT}" rx="8"></rect>'
            f'<rect class="anim__cmp-box anim__cmp-box-active" id="{active_id}" '
            f'x="{x:g}" y="{y:g}" width="{col_width:g}" height="{_CMP_ROW_HEIGHT}" '
            f'rx="8" fill="var(--anim-cmp-active)" opacity="0"></rect>'
            f'<text class="anim__cmp-text" x="{text_x:g}" y="{text_y:g}" '
            f'text-anchor="middle" fill="var(--color-fg)">{html.escape(text)}</text>'
            f'<text class="anim__cmp-text anim__text-on-accent" id="{inv_id}" '
            f'x="{text_x:g}" y="{text_y:g}" text-anchor="middle" opacity="0">'
            f'{html.escape(text)}</text>'
        )

    rows_html = []
    for i, (left_text, right_text) in enumerate(anim.rows):
        y = _CMP_MARGIN + header_height + i * (_CMP_ROW_HEIGHT + 8)
        rows_html.append(
            '<g class="anim__cmp-row">'
            + cell(left_x, y, left_text, left_rect_ids[i], left_active_ids[i], left_inverted_ids[i])
            + cell(right_x, y, right_text, right_rect_ids[i], right_active_ids[i], right_inverted_ids[i])
            + "</g>"
        )

    steps_json: list[dict] = []
    for i in range(count):
        flash_targets = [
            f"#{left_active_ids[i]}", f"#{left_inverted_ids[i]}",
            f"#{right_active_ids[i]}", f"#{right_inverted_ids[i]}",
        ]
        steps_json.append({
            "targets": flash_targets,
            "props": {"opacity": [0, 1]},
            "duration": 350,
            "ease": "outQuad",
        })
        steps_json.append({
            "targets": flash_targets,
            "props": {"opacity": 0},
            "duration": 350,
            "ease": "outQuad",
        })

    steps_json.append({
        "kind": "set",
        "targets": (
            [f"#{a}" for a in left_active_ids] + [f"#{a}" for a in right_active_ids]
            + [f"#{t}" for t in left_inverted_ids] + [f"#{t}" for t in right_inverted_ids]
        ),
        "props": {"opacity": 0},
    })

    timeline_json = _timeline_island_json(
        {"loop": True, "loopDelay": 900, "steps": steps_json}
    )
    static_lines = "".join(
        f"<li>{html.escape(lt)} — {html.escape(rt)}</li>" for lt, rt in anim.rows
    )
    return (
        '<div class="anim anim--compare">'
        f'<svg class="anim__compare" dir="ltr" '
        f'width="{total_width:g}" height="{total_height:g}" '
        f'viewBox="0 0 {total_width:g} {total_height:g}">'
        f"{headers_html}{''.join(rows_html)}</svg>"
        f'<script type="application/json" class="anim__timeline">{timeline_json}</script>'
        f'<ol class="anim__cmp-static">{static_lines}</ol></div>'
    )


def _cubic_length(
    p0: tuple[float, float], c1: tuple[float, float],
    c2: tuple[float, float], p3: tuple[float, float], samples: int = 40,
) -> float:
    """Approximate arc length by summing chord lengths between sampled points.

    A cubic Bezier's arc length has no closed form. 40 samples is comfortably
    under a pixel of error at the coordinate magnitudes this renderer works in
    -- the same trade-off _state_machine_html's binary search already makes.
    Computed at RENDER time in Python rather than the client calling
    getTotalLength(), so stroke-dasharray/dashoffset are static, correct
    values in the markup from the first frame.
    """
    def at(t: float) -> tuple[float, float]:
        mt = 1 - t
        x = (
            mt ** 3 * p0[0] + 3 * mt ** 2 * t * c1[0]
            + 3 * mt * t ** 2 * c2[0] + t ** 3 * p3[0]
        )
        y = (
            mt ** 3 * p0[1] + 3 * mt ** 2 * t * c1[1]
            + 3 * mt * t ** 2 * c2[1] + t ** 3 * p3[1]
        )
        return (x, y)

    length = 0.0
    prev = at(0.0)
    for i in range(1, samples + 1):
        point = at(i / samples)
        length += math.hypot(point[0] - prev[0], point[1] - prev[1])
        prev = point
    return length


def _split_merge_html(anim: Animate, token: str) -> str:
    """One thing dividing into parallel branches, then recombining.

    Fan-out connectors draw from the source to each branch; fan-in connectors
    draw from each branch back to the merged result. Branch boxes settle to
    the faint accent wash (they do work, but are not the conclusion); the
    merged box takes the solid accent with inverted text, since it is.
    """
    token_seed = re.sub(r"\D", "", token) or "0"
    count = len(anim.branches)
    branch_rect_ids = [f"anim-split-branch-{token_seed}-{i}" for i in range(count)]
    fan_out_ids = [f"anim-split-out-{token_seed}-{i}" for i in range(count)]
    fan_in_ids = [f"anim-split-in-{token_seed}-{i}" for i in range(count)]
    merged_active_id = f"anim-split-merged-active-{token_seed}"
    merged_inverted_id = f"anim-split-merged-inverted-{token_seed}"

    branch_widths = [
        max(
            _SPLIT_BOX_WIDTH,
            max(len(name), len(what)) * _STATE_LABEL_CHAR_WIDTH + 2 * _STATE_BOX_PAD_X,
        )
        for name, what in anim.branches
    ]
    row_width = sum(branch_widths) + (count - 1) * _SPLIT_BRANCH_GAP
    total_width = max(row_width, _SPLIT_BOX_WIDTH * 2) + _SPLIT_MARGIN * 2
    source_y = _SPLIT_MARGIN
    branch_y = source_y + _SPLIT_SOURCE_HEIGHT + _SPLIT_ROW_GAP
    merged_y = branch_y + _SPLIT_BOX_HEIGHT + _SPLIT_ROW_GAP
    total_height = merged_y + _SPLIT_BOX_HEIGHT + _SPLIT_MARGIN

    center_x = total_width / 2
    source_center = (center_x, source_y + _SPLIT_SOURCE_HEIGHT / 2)
    merged_center = (center_x, merged_y + _SPLIT_BOX_HEIGHT / 2)

    branch_xs = []
    x = (total_width - row_width) / 2
    for width in branch_widths:
        branch_xs.append(x)
        x += width + _SPLIT_BRANCH_GAP

    source_html = (
        f'<g class="anim__split-endpoint">'
        f'<rect class="anim__split-box" x="{center_x - _SPLIT_BOX_WIDTH / 2:g}" '
        f'y="{source_y:g}" width="{_SPLIT_BOX_WIDTH}" height="{_SPLIT_SOURCE_HEIGHT}" '
        f'rx="8" fill="var(--anim-split-idle)"></rect>'
        f'<text class="anim__split-name" x="{center_x:g}" '
        f'y="{source_y + _SPLIT_SOURCE_HEIGHT / 2 + 4:g}" text-anchor="middle" '
        f'fill="var(--color-fg)">{html.escape(anim.source)}</text>'
        f'</g>'
    )

    connectors_out = []
    connectors_in = []
    branches_html = []
    fan_out_lengths = []
    fan_in_lengths = []
    for i, ((name, what), bx) in enumerate(zip(anim.branches, branch_xs)):
        branch_center = (bx + branch_widths[i] / 2, branch_y + _SPLIT_BOX_HEIGHT / 2)
        out_p0 = (source_center[0], source_y + _SPLIT_SOURCE_HEIGHT)
        out_p3 = (branch_center[0], branch_y)
        out_mid_y = (out_p0[1] + out_p3[1]) / 2
        out_c1 = (out_p0[0], out_mid_y)
        out_c2 = (out_p3[0], out_mid_y)
        out_length = _cubic_length(out_p0, out_c1, out_c2, out_p3)
        fan_out_lengths.append(out_length)
        connectors_out.append(
            f'<path class="anim__split-line anim__split-line-out" id="{fan_out_ids[i]}" '
            f'fill="none" d="M {out_p0[0]:.1f} {out_p0[1]:.1f} '
            f'C {out_c1[0]:.1f} {out_c1[1]:.1f}, {out_c2[0]:.1f} {out_c2[1]:.1f}, '
            f'{out_p3[0]:.1f} {out_p3[1]:.1f}" '
            f'stroke-dasharray="{out_length:.1f}" stroke-dashoffset="{out_length:.1f}"></path>'
        )

        in_p0 = (branch_center[0], branch_y + _SPLIT_BOX_HEIGHT)
        in_p3 = (merged_center[0], merged_y)
        in_mid_y = (in_p0[1] + in_p3[1]) / 2
        in_c1 = (in_p0[0], in_mid_y)
        in_c2 = (in_p3[0], in_mid_y)
        in_length = _cubic_length(in_p0, in_c1, in_c2, in_p3)
        fan_in_lengths.append(in_length)
        connectors_in.append(
            f'<path class="anim__split-line anim__split-line-in" id="{fan_in_ids[i]}" '
            f'fill="none" d="M {in_p0[0]:.1f} {in_p0[1]:.1f} '
            f'C {in_c1[0]:.1f} {in_c1[1]:.1f}, {in_c2[0]:.1f} {in_c2[1]:.1f}, '
            f'{in_p3[0]:.1f} {in_p3[1]:.1f}" '
            f'stroke-dasharray="{in_length:.1f}" stroke-dashoffset="{in_length:.1f}"></path>'
        )

        branches_html.append(
            f'<g class="anim__split-endpoint">'
            f'<rect class="anim__split-box anim__visited" id="{branch_rect_ids[i]}" '
            f'x="{bx:g}" y="{branch_y:g}" width="{branch_widths[i]:g}" '
            f'height="{_SPLIT_BOX_HEIGHT}" rx="8" fill="var(--color-accent)" '
            f'fill-opacity="0"></rect>'
            f'<text class="anim__split-name" x="{branch_center[0]:g}" '
            f'y="{branch_y + _SPLIT_BOX_HEIGHT / 2:g}" text-anchor="middle" '
            f'fill="var(--color-fg)">{html.escape(name)}</text>'
            f'<text class="anim__split-what" x="{branch_center[0]:g}" '
            f'y="{branch_y + _SPLIT_BOX_HEIGHT / 2 + 14:g}" text-anchor="middle" '
            f'fill="var(--color-muted)">{html.escape(what)}</text>'
            f'</g>'
        )

    merged_html = (
        f'<g class="anim__split-endpoint">'
        f'<rect class="anim__split-box" x="{center_x - _SPLIT_BOX_WIDTH / 2:g}" '
        f'y="{merged_y:g}" width="{_SPLIT_BOX_WIDTH}" height="{_SPLIT_BOX_HEIGHT}" '
        f'rx="8" fill="var(--anim-split-idle)"></rect>'
        f'<text class="anim__split-name" x="{center_x:g}" '
        f'y="{merged_y + _SPLIT_BOX_HEIGHT / 2 + 4:g}" text-anchor="middle" '
        f'fill="var(--color-fg)">{html.escape(anim.merged)}</text>'
        f'<rect class="anim__split-box anim__split-box-active" id="{merged_active_id}" '
        f'x="{center_x - _SPLIT_BOX_WIDTH / 2:g}" y="{merged_y:g}" '
        f'width="{_SPLIT_BOX_WIDTH}" height="{_SPLIT_BOX_HEIGHT}" rx="8" '
        f'fill="var(--anim-split-active)" opacity="0"></rect>'
        f'<text class="anim__split-name anim__text-on-accent" id="{merged_inverted_id}" '
        f'x="{center_x:g}" y="{merged_y + _SPLIT_BOX_HEIGHT / 2 + 4:g}" '
        f'text-anchor="middle" opacity="0">{html.escape(anim.merged)}</text>'
        f'</g>'
    )

    steps_json: list[dict] = []
    for i in range(count):
        steps_json.append({
            "targets": [f"#{fan_out_ids[i]}"],
            "props": {"strokeDashoffset": [fan_out_lengths[i], 0]},
            "duration": 500,
            "ease": "outQuad",
            **({"position": "<<"} if i > 0 else {}),
        })
    for i in range(count):
        steps_json.append({
            "targets": [f"#{branch_rect_ids[i]}"],
            "props": {"fillOpacity": [0, 1]},
            "duration": 400,
            "ease": "outQuad",
            **({"position": "<<"} if i > 0 else {}),
        })
    for i in range(count):
        steps_json.append({
            "targets": [f"#{fan_in_ids[i]}"],
            "props": {"strokeDashoffset": [fan_in_lengths[i], 0]},
            "duration": 500,
            "ease": "outQuad",
            **({"position": "<<"} if i > 0 else {}),
        })
    steps_json.append({
        "targets": [f"#{merged_active_id}", f"#{merged_inverted_id}"],
        "props": {"opacity": [0, 1]},
        "duration": 500,
        "ease": "outQuad",
    })

    steps_json.append({
        "kind": "set", "targets": [f"#{fid}" for fid in fan_out_ids],
        "props": {"strokeDashoffset": fan_out_lengths},
    })
    steps_json.append({
        "kind": "set", "targets": [f"#{r}" for r in branch_rect_ids],
        "props": {"fillOpacity": 0},
    })
    steps_json.append({
        "kind": "set", "targets": [f"#{fid}" for fid in fan_in_ids],
        "props": {"strokeDashoffset": fan_in_lengths},
    })
    steps_json.append({
        "kind": "set", "targets": [f"#{merged_active_id}", f"#{merged_inverted_id}"],
        "props": {"opacity": 0},
    })

    timeline_json = _timeline_island_json(
        {"loop": True, "loopDelay": 900, "steps": steps_json}
    )
    static_lines = "".join(
        f"<li>{html.escape(n)} — {html.escape(w)}</li>" for n, w in anim.branches
    )
    return (
        '<div class="anim anim--split-merge">'
        f'<svg class="anim__split-merge" dir="ltr" '
        f'width="{total_width:g}" height="{total_height:g}" '
        f'viewBox="0 0 {total_width:g} {total_height:g}">'
        f"{''.join(connectors_out)}{''.join(connectors_in)}"
        f"{source_html}{''.join(branches_html)}{merged_html}</svg>"
        f'<script type="application/json" class="anim__timeline">{timeline_json}</script>'
        f'<ol class="anim__split-static">{static_lines}</ol></div>'
    )


def _transform_html(anim: Animate, token: str) -> str:
    """One entity becomes another through a vertical spine of accumulating steps.

    The spine draws downward from the `from` box to the `to` box. Each step
    lands as a rung on that spine and STAYS -- unlike the old horizontal
    connector, where steps flashed on and off in the same position and only
    ever one was visible, so the sequence (the entire teaching point) could
    never be seen at once. The `to` box takes the accent, with its label
    inverted, only once every rung is present.
    """
    token_seed = re.sub(r"\D", "", token) or "0"
    from_id = f"anim-xform-from-{token_seed}"
    to_id = f"anim-xform-to-{token_seed}"
    line_id = f"anim-xform-line-{token_seed}"
    step_ids = [f"anim-xform-step-{token_seed}-{i}" for i in range(len(anim.steps))]
    to_active_id = f"anim-xform-to-active-{token_seed}"
    to_inverted_id = f"anim-xform-to-inverted-{token_seed}"

    # A rung's text sits to the right of the spine and can run wider than the
    # endpoint boxes above and below it -- reusing _state_machine_html's own
    # "estimate width from character count" approach rather than inventing a
    # second one. The SVG's width grows to fit the widest rung so long text is
    # never clipped.
    step_text_widths = [
        len(text) * _STATE_LABEL_CHAR_WIDTH for text in anim.steps
    ]
    widest_step_text = max(step_text_widths, default=0)

    spine_x = _XFORM_BOX_WIDTH / 2
    rung_text_x = _XFORM_BOX_WIDTH + 24
    total_width = max(
        _XFORM_BOX_WIDTH, rung_text_x + widest_step_text + _XFORM_TOP_MARGIN
    )

    box_top_y = _XFORM_TOP_MARGIN
    box_bottom_y = box_top_y + _XFORM_BOX_HEIGHT
    spine_top_y = box_bottom_y
    rung_ys = [
        spine_top_y + _XFORM_RUNG_GAP * (i + 1) for i in range(len(anim.steps))
    ]
    spine_bottom_y = spine_top_y + _XFORM_RUNG_GAP * (len(anim.steps) + 1)
    to_box_top_y = spine_bottom_y
    total_height = to_box_top_y + _XFORM_BOX_HEIGHT + _XFORM_TOP_MARGIN
    spine_length = spine_bottom_y - spine_top_y

    # The `to` endpoint gets a second, stacked accent rect and a pre-inverted
    # label, whose OPACITY the timeline animates once the last rung lands --
    # never a `fill` tween between two var() tokens, which animejs's colour
    # detector cannot interpolate (see .anim__text-on-accent's comment). Only
    # `to` needs this; `from` never changes fill. Both `active_id` and
    # `inverted_id` are None for `from`, where they're unused.
    def endpoint(
        box_id: str, y: float, label: str,
        active_id: str | None = None, inverted_id: str | None = None,
    ) -> str:
        label_x = spine_x
        label_y = y + _XFORM_BOX_HEIGHT / 2 + 4
        extra = ""
        if active_id is not None:
            extra = (
                f'<rect class="anim__xform-box anim__xform-box-active" '
                f'id="{active_id}" x="0" '
                f'y="{y:g}" width="{_XFORM_BOX_WIDTH}" '
                f'height="{_XFORM_BOX_HEIGHT}" rx="8" '
                f'fill="var(--anim-xform-active)" opacity="0"></rect>'
                f'<text class="anim__xform-label anim__text-on-accent" '
                f'id="{inverted_id}" x="{label_x:g}" y="{label_y:g}" '
                f'text-anchor="middle" opacity="0">{html.escape(label)}</text>'
            )
        return (
            f'<g class="anim__xform-endpoint">'
            f'<rect class="anim__xform-box" id="{box_id}" x="0" '
            f'y="{y:g}" width="{_XFORM_BOX_WIDTH}" '
            f'height="{_XFORM_BOX_HEIGHT}" rx="8" '
            f'fill="var(--anim-xform-idle)"></rect>'
            f'<text class="anim__xform-label" x="{label_x:g}" '
            f'y="{label_y:g}" text-anchor="middle" '
            f'fill="var(--color-fg)">{html.escape(label)}</text>'
            f'{extra}'
            f'</g>'
        )

    # Each rung is a dot on the spine plus its own left-aligned text, at its
    # own y -- the accumulating structure this redesign exists to show. Rungs
    # paint after the spine but before the endpoints settle, so a rung is
    # never mistaken for part of either box.
    rungs_html = []
    for i, (text, y) in enumerate(zip(anim.steps, rung_ys)):
        rungs_html.append(
            f'<g class="anim__xform-step" id="{step_ids[i]}" opacity="0">'
            f'<circle class="anim__xform-step-dot" cx="{spine_x:g}" cy="{y:g}" r="5"></circle>'
            f'<text class="anim__xform-step-text" x="{rung_text_x:g}" y="{y + 4:g}" '
            f'text-anchor="start">{html.escape(text)}</text>'
            f'</g>'
        )

    steps_json: list[dict] = [
        {
            "targets": [f"#{line_id}"],
            "props": {"strokeDashoffset": [spine_length, 0]},
            "duration": STEP_SECONDS * 1000,
            "ease": "inOutQuad",
        }
    ]
    for step_id in step_ids:
        steps_json.append({
            "targets": [f"#{step_id}"],
            "props": {"opacity": [0, 1]},
            "duration": 400,
            "ease": "outQuad",
        })
    steps_json.append({
        "targets": [f"#{to_active_id}", f"#{to_inverted_id}"],
        "props": {"opacity": [0, 1]},
        "duration": 500,
        "ease": "outQuad",
    })

    steps_json.append({
        "kind": "set", "targets": [f"#{s}" for s in step_ids], "props": {"opacity": 0},
    })
    steps_json.append({
        "kind": "set", "targets": [f"#{line_id}"],
        "props": {"strokeDashoffset": spine_length},
    })
    steps_json.append({
        "kind": "set", "targets": [f"#{to_active_id}", f"#{to_inverted_id}"],
        "props": {"opacity": 0},
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
        f'<line class="anim__xform-line" id="{line_id}" x1="{spine_x:g}" '
        f'y1="{spine_top_y:g}" x2="{spine_x:g}" y2="{spine_bottom_y:g}" '
        f'stroke-dasharray="{spine_length:g}" stroke-dashoffset="{spine_length:g}"></line>'
        f'{endpoint(from_id, box_top_y, anim.from_entity)}'
        f"{''.join(rungs_html)}"
        f'{endpoint(to_id, to_box_top_y, anim.to_entity, to_active_id, to_inverted_id)}'
        "</svg>"
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
