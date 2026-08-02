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

_ANIMATE_KEY = re.compile(r"^(?P<key>pattern|before|after|caption):\s*(?P<value>.*)$")
_ANIMATE_STEP = re.compile(r"^\s*-\s*(?P<text>.+)$")
_ARRAY_OP = re.compile(
    r"^(?P<verb>compare|swap|highlight)\s+(?P<a>\d+)(?:\s+(?P<b>\d+))?$"
)


class AnimateError(ValueError):
    """An animate block that does not satisfy the grammar."""


@dataclass
class Animate:
    pattern: str
    steps: list[str] = field(default_factory=list)
    before: str = ""
    after: str = ""
    array: list[int] = field(default_factory=list)
    ops: list[tuple[str, int, int | None]] = field(default_factory=list)
    points: list[tuple[float, float]] = field(default_factory=list)
    caption: str = ""


_LIST_HEADERS = {"steps:": "steps", "array:": "array", "ops:": "ops", "points:": "points"}


def parse_animate(body: str) -> Animate:
    pattern: str | None = None
    steps: list[str] = []
    before: str | None = None
    after: str | None = None
    array_raw: list[str] = []
    ops_raw: list[str] = []
    points_raw: list[str] = []
    caption: str | None = None
    section: str | None = None

    lists = {"steps": steps, "array": array_raw, "ops": ops_raw, "points": points_raw}

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
                pattern = value
            elif name == "before":
                before = value
            elif name == "after":
                after = value
            else:
                caption = value
            continue
        if line.strip() in _LIST_HEADERS:
            section = _LIST_HEADERS[line.strip()]
            continue
        raise AnimateError(f"unrecognised line in animate block: {line.strip()!r}")

    if pattern not in ("step-reveal", "state-toggle", "array-ops", "path-trace"):
        raise AnimateError(
            "animate pattern must be 'step-reveal', 'state-toggle', 'array-ops', "
            f"or 'path-trace', got {pattern!r}"
        )

    if pattern == "step-reveal":
        if len(steps) < 2:
            raise AnimateError("step-reveal needs at least 2 steps")
        if before or after or array_raw or ops_raw or points_raw or caption:
            raise AnimateError("step-reveal does not use 'before:'/'after:'")
    elif pattern == "state-toggle":
        if not before or not after:
            raise AnimateError("state-toggle needs both 'before:' and 'after:'")
        if steps or array_raw or ops_raw or points_raw or caption:
            raise AnimateError("state-toggle does not use 'steps:'")
    elif pattern == "array-ops":
        if before or after or steps or points_raw or caption:
            raise AnimateError("array-ops does not use 'before:'/'after:'")
        if len(array_raw) < 2:
            raise AnimateError("array-ops needs at least 2 array values")
        array: list[int] = []
        for item in array_raw:
            try:
                array.append(int(item))
            except ValueError:
                raise AnimateError(f"array item {item!r} is not an integer") from None
        if not ops_raw:
            raise AnimateError("array-ops needs at least one op")
        ops: list[tuple[str, int, int | None]] = []
        for line in ops_raw:
            match = _ARRAY_OP.match(line)
            if not match:
                raise AnimateError(f"invalid array-ops operation: {line!r}")
            verb, a, b = match.group("verb"), int(match.group("a")), match.group("b")
            if verb == "highlight":
                if b is not None:
                    raise AnimateError(f"invalid array-ops operation: {line!r}")
                b_val = None
            else:
                if b is None:
                    raise AnimateError(f"invalid array-ops operation: {line!r}")
                b_val = int(b)
            for idx in (a, b_val):
                if idx is not None and idx >= len(array):
                    raise AnimateError(
                        f"array-ops index {idx} out of range for array of length {len(array)}"
                    )
            ops.append((verb, a, b_val))
        return Animate(pattern=pattern, array=array, ops=ops)
    else:  # path-trace
        if before or after or steps or array_raw or ops_raw:
            raise AnimateError("path-trace does not use 'before:'/'after:'")
        if len(points_raw) < 2:
            raise AnimateError("path-trace needs at least 2 points")
        points: list[tuple[float, float]] = []
        for item in points_raw:
            match = re.match(r"^(-?\d+(?:\.\d+)?)\s*,\s*(-?\d+(?:\.\d+)?)$", item)
            if not match:
                raise AnimateError(f"invalid path-trace point: {item!r}")
            points.append((float(match.group(1)), float(match.group(2))))
        if not caption:
            raise AnimateError("path-trace needs 'caption:'")
        return Animate(pattern=pattern, points=points, caption=caption)

    return Animate(pattern=pattern, steps=steps, before=before or "", after=after or "")


_BAR_WIDTH = 36
_BAR_GAP = 18
_BAR_MAX_HEIGHT = 120
_BAR_HEADROOM = 40  # verified in mockup: enough room above the tallest bar for a
                    # 1.15x highlight scale-pulse to never approach the SVG's own edge
_BAR_BASELINE_Y = _BAR_HEADROOM + _BAR_MAX_HEIGHT  # y-coordinate of the x-axis line
_PATH_PADDING = 10
# Constant visual speed: every path-trace segment is timed at the same
# milliseconds-per-viewBox-unit, so a segment twice as long on screen takes twice
# as long to traverse (a fixed per-segment duration would instead make short hops
# crawl and long hops sprint). The max(300, ...) floor keeps a near-zero-length
# segment from flashing past unnoticeably.
_PATH_MS_PER_UNIT = 90
_PATH_MIN_SEGMENT_MS = 300

_ARRAY_VERB_LABEL = {"compare": "comparing", "swap": "swapping", "highlight": "highlighting"}


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
    if anim.pattern == "step-reveal":
        return _step_reveal_html(anim, token)
    if anim.pattern == "state-toggle":
        return _state_toggle_html(anim, token)
    if anim.pattern == "array-ops":
        return _array_ops_html(anim, token)
    # path-trace
    return _path_trace_html(anim, token)


def _step_reveal_html(anim: Animate, token: str) -> str:
    # See _array_ops_html's token_seed comment: the token's literal text must
    # never appear in this function's return value (blocks.restore() does an
    # unconditional second substitution pass keyed on the token), so only the
    # token's ordinal digits are used to build element ids.
    token_seed = re.sub(r"\D", "", token) or "0"
    items = "".join(
        f'<li class="anim__step" id="anim-step-{token_seed}-{i}">{html.escape(step)}</li>'
        for i, step in enumerate(anim.steps)
    )
    n = len(anim.steps)
    cycle = n * STEP_SECONDS
    steps_json = []
    for i in range(n):
        steps_json.append({
            "targets": [f"#anim-step-{token_seed}-{i}"],
            "props": {"opacity": [0.65, 1, 0.65], "fontWeight": [400, 600, 400]},
            "duration": cycle * 1000 // n if n else 0,
            "ease": "linear",
            "position": None if i == 0 else "<",
        })
    timeline = {"loop": True, "loopDelay": 0, "steps": steps_json}
    timeline_json = _timeline_island_json(timeline)
    return (
        f'<div class="anim anim--step-reveal"><ol class="anim__steps">{items}</ol>'
        f'<script type="application/json" class="anim__timeline">{timeline_json}</script>'
        "</div>"
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


def _array_ops_html(anim: Animate, token: str) -> str:
    """Bars occupy fixed slot x-positions expressed as plain SVG attributes (never a
    transform="translate(...)" ATTRIBUTE): animating any transform-family property
    (translateX, scale) makes anime.js set a CSS transform, which fully replaces
    -- does not compose with -- an SVG transform attribute on the same element (see
    .claude/skills/animejs/references/api-reference.md's Gotchas section). Each
    bar's <g> also gets transform-box: fill-box; transform-origin: center so a
    scale-pulse grows from the bar's own visual center, not the SVG viewport's
    (0,0) origin.
    """
    max_value = max(anim.array) or 1
    n = len(anim.array)
    slot_width = _BAR_WIDTH + _BAR_GAP
    width = n * slot_width + _BAR_GAP
    # See _step_reveal_html's token_seed comment: the token's literal text must
    # never appear in this function's return value (blocks.restore() does an
    # unconditional second substitution pass keyed on the token), so only the
    # token's ordinal digits are used to build element ids.
    token_seed = re.sub(r"\D", "", token) or "0"

    # slot_of_bar[original_index] = which slot that bar currently occupies, replayed
    # op by op. Bars are tracked by their ORIGINAL index, so a bar's value/height
    # never changes -- only which slot it sits in does.
    slot_of_bar = list(range(n))
    bar_ids = [f"anim-bar-{token_seed}-{i}" for i in range(n)]
    rect_ids = [f"anim-rect-{token_seed}-{i}" for i in range(n)]
    caption_id = f"anim-caption-{token_seed}"

    def home_x(slot: int) -> int:
        return _BAR_GAP + slot * slot_width

    bars_html = []
    for i in range(n):
        value = anim.array[i]
        height = round((value / max_value) * _BAR_MAX_HEIGHT, 1)
        x = home_x(i)
        y = _BAR_BASELINE_Y - height
        bars_html.append(
            f'<g class="anim__array-bar" id="{bar_ids[i]}" '
            f'style="transform-box: fill-box; transform-origin: center;">'
            f'<rect id="{rect_ids[i]}" x="{x}" y="{y}" width="{_BAR_WIDTH}" height="{height}" '
            f'rx="4" fill="var(--anim-array-idle)"></rect>'
            f'<text class="anim__array-label" x="{x + _BAR_WIDTH / 2:g}" '
            f'y="{_BAR_BASELINE_Y + 20}">{html.escape(str(value))}</text>'
            "</g>"
        )

    steps_json: list[dict] = []
    for verb, a, b in anim.ops:
        if verb == "highlight":
            caption = f"{_ARRAY_VERB_LABEL[verb]} index {a}"
            steps_json.append({
                "targets": [f"#{rect_ids[a]}"],
                "props": {"fill": ["var(--anim-array-idle)", "var(--anim-array-highlight)", "var(--anim-array-highlight)"]},
                "duration": 900, "ease": "outQuad", "position": "+=300", "caption": caption,
            })
            steps_json.append({
                "targets": [f"#{bar_ids[a]}"],
                "props": {"scale": [1, 1.15, 1]},
                "duration": 900, "ease": "outElastic(1, .6)", "position": "<",
            })
        elif verb == "compare":
            caption = f"{_ARRAY_VERB_LABEL[verb]} index {a} and {b}"
            steps_json.append({
                "targets": [f"#{rect_ids[a]}", f"#{rect_ids[b]}"],
                "props": {"fill": ["var(--anim-array-idle)", "var(--anim-array-compare)", "var(--anim-array-idle)"]},
                "duration": 700, "ease": "inOutQuad", "position": None if not steps_json else "+=300",
                "caption": caption,
            })
            steps_json.append({
                "targets": [f"#{bar_ids[a]}", f"#{bar_ids[b]}"],
                "props": {"scale": [1, 1.08, 1]},
                "duration": 700, "ease": "inOutQuad", "position": "<",
            })
        else:  # swap
            slot_of_bar[a], slot_of_bar[b] = slot_of_bar[b], slot_of_bar[a]
            # Each bar's translateX is its OWN absolute displacement from its own
            # home slot -- deliberately NOT a `delta`/`-delta` mirrored pair. The
            # mirrored form is only correct while both bars still sit in their home
            # slots; once an earlier swap has displaced either one, the two bars'
            # required displacements are no longer negatives of each other (e.g.
            # "swap 0 2" then "swap 0 1" needs +54 for bar 0 and +108 for bar 1).
            # Absolute values also survive loop: true, since each lap re-animates
            # toward the same fixed target rather than compounding a relative nudge.
            delta_a = (slot_of_bar[a] - a) * slot_width
            delta_b = (slot_of_bar[b] - b) * slot_width
            caption = f"{_ARRAY_VERB_LABEL[verb]} index {a} and {b}"
            steps_json.append({
                "targets": [f"#{rect_ids[a]}", f"#{rect_ids[b]}"],
                "props": {"fill": ["var(--anim-array-idle)", "var(--anim-array-swap)", "var(--anim-array-idle)"]},
                "duration": 750, "ease": "inOutQuad", "position": "+=300", "caption": caption,
            })
            steps_json.append({
                "targets": [f"#{bar_ids[a]}"], "props": {"translateX": delta_a},
                "duration": 650, "ease": "inOutBack", "position": "<",
            })
            steps_json.append({
                "targets": [f"#{bar_ids[b]}"], "props": {"translateX": delta_b},
                "duration": 650, "ease": "inOutBack", "position": "<",
            })

    # Hold the final state on screen (a no-op animation on an already-idle target,
    # purely for its 900ms of dwell time), then snap every bar's transform/fill back
    # to idle right before the loop restarts (the loop-state-drift gotcha) -- a swap
    # must look like a real, sticky reorder (the swapped bars stay in each other's
    # slots through the following highlight step), never a bounce-back.
    steps_json.append({"targets": [f"#{bar_ids[0]}"], "props": {}, "duration": 900})
    steps_json.append({
        "kind": "set", "targets": [f"#{b}" for b in bar_ids], "props": {"translateX": 0, "scale": 1},
    })
    steps_json.append({
        "kind": "set", "targets": [f"#{r}" for r in rect_ids], "props": {"fill": "var(--anim-array-idle)"},
    })

    timeline = {"loop": True, "loopDelay": 1200, "steps": steps_json}
    timeline_json = _timeline_island_json(timeline)

    legend_items = "".join(
        f'<span class="anim__array-legend-item"><span class="anim__array-legend-swatch '
        f'anim__array-legend-swatch--{kind}"></span>{kind}</span>'
        for kind in ("idle", "compare", "swap", "highlight")
    )

    axis_y = _BAR_BASELINE_Y
    mid_y = _BAR_HEADROOM + _BAR_MAX_HEIGHT / 2
    chrome = (
        f'<line class="anim__array-axis" x1="0" y1="{_BAR_HEADROOM - 4}" '
        f'x2="0" y2="{axis_y}"></line>'
        f'<line class="anim__array-axis" x1="0" y1="{axis_y}" x2="{width}" y2="{axis_y}"></line>'
        f'<line class="anim__array-gridline" x1="0" y1="{mid_y:g}" x2="{width}" y2="{mid_y:g}"></line>'
    )

    # Reduced-motion/print static fallback (same dual-render precedent as
    # state-toggle): the animated <svg> is hidden and this plain step list shown
    # instead, rather than trying to freeze an infinitely-looping timeline
    # mid-cycle.
    op_lines = "".join(
        f"<li>{html.escape(verb)} index {a}" + (f" and {b}" if b is not None else "") + "</li>"
        for verb, a, b in anim.ops
    )
    static_fallback = f'<ol class="anim__array-steps-static">{op_lines}</ol>'

    return (
        f'<div class="anim anim--array-ops">'
        f'<p class="anim__caption" id="{caption_id}" data-anim-id="{caption_id}">'
        f"Step 1 of {len(anim.ops)}</p>"
        f'<svg class="anim__array" dir="ltr" viewBox="0 0 {width} {_BAR_BASELINE_Y + 40}">'
        f"{chrome}{''.join(bars_html)}</svg>"
        f'<div class="anim__array-legend">{legend_items}</div>'
        f'<script type="application/json" class="anim__timeline" data-anim-id="{caption_id}">'
        f"{timeline_json}</script>"
        f"{static_fallback}</div>"
    )


def _path_trace_html(anim: Animate, token: str) -> str:
    """A marker travels the plotted points at constant visual speed, extending a
    fading trail behind it while a live caption names the current segment.

    The "path-segment" step kind exists because the trail is not a tween: its "d"
    attribute must ACCUMULATE one "L x,y" command per frame. anime.js can animate
    SVG attributes like cx/cy directly, but that would expose no per-frame value to
    append with, so the coordinator tweens a plain {x, y} state object instead and
    mirrors it onto both the marker's cx/cy and the trail's growing "d" in onUpdate.

    "set-attr" then rewinds "d" to just its "M x,y" origin before the loop repeats;
    a path-data string is not interpolatable, so it is assigned, not tweened.
    """
    # See _step_reveal_html's token_seed comment: only the token's ordinal digits
    # are used to build element ids, never the token's literal text.
    token_seed = re.sub(r"\D", "", token) or "0"
    marker_id = f"anim-marker-{token_seed}"
    trail_id = f"anim-trail-{token_seed}"
    caption_id = f"anim-caption-{token_seed}"

    xs = [x for x, _ in anim.points]
    ys = [y for _, y in anim.points]
    data_min_x, data_max_x = min(xs), max(xs)
    data_min_y, data_max_y = min(ys), max(ys)
    min_x, max_x = data_min_x - _PATH_PADDING, data_max_x + _PATH_PADDING
    min_y, max_y = data_min_y - _PATH_PADDING, data_max_y + _PATH_PADDING
    points_attr = " ".join(f"{x:g},{y:g}" for x, y in anim.points)
    # Axes drawn at the data's own min edges (not always literal 0), so a plot
    # whose values never cross zero (e.g. all y > 0) still gets a frame of
    # reference at its own floor/left-edge rather than an axis floating away
    # from every data point.
    axis = (
        f'<line class="anim__path-axis" x1="{min_x:g}" y1="{data_max_y:g}" '
        f'x2="{max_x:g}" y2="{data_max_y:g}"></line>'
        f'<line class="anim__path-axis" x1="{data_min_x:g}" y1="{min_y:g}" '
        f'x2="{data_min_x:g}" y2="{max_y:g}"></line>'
    )
    labels = (
        f'<text class="anim__path-tick" x="{data_min_x:g}" y="{data_max_y + 9:g}">'
        f"{data_min_x:g}</text>"
        f'<text class="anim__path-tick" x="{data_max_x:g}" y="{data_max_y + 9:g}">'
        f"{data_max_x:g}</text>"
        f'<text class="anim__path-tick" x="{data_min_x - 2:g}" y="{data_min_y:g}">'
        f"{data_min_y:g}</text>"
        f'<text class="anim__path-tick" x="{data_min_x - 2:g}" y="{data_max_y:g}">'
        f"{data_max_y:g}</text>"
    )

    x0, y0 = anim.points[0]
    steps_json: list[dict] = []
    for (fx, fy), (tx, ty) in zip(anim.points, anim.points[1:]):
        segment_length = math.hypot(tx - fx, ty - fy)
        duration = max(_PATH_MIN_SEGMENT_MS, round(segment_length * _PATH_MS_PER_UNIT))
        steps_json.append({
            "kind": "path-segment",
            "marker": f"#{marker_id}",
            "trail": f"#{trail_id}",
            "from": [fx, fy],
            "to": [tx, ty],
            "duration": duration,
            "ease": "inOutSine",
            # A brief pause at each plotted point makes the vertices legible as
            # data points rather than one continuous sweep. The first segment has
            # no preceding step to offset from.
            "position": None if not steps_json else "+=150",
            "caption": f"Moving from ({fx:g}, {fy:g}) to ({tx:g}, {ty:g})",
        })
    # Snap marker and trail back to the origin before the loop restarts (the
    # loop-state-drift gotcha): the trail's "d" grows by an L command on every
    # frame, so without this reset the second lap would keep appending to a path
    # that already spans the whole plot.
    steps_json.append({
        "kind": "set", "targets": [f"#{marker_id}"],
        "props": {"cx": x0, "cy": y0},
    })
    steps_json.append({
        "kind": "set-attr", "targets": [f"#{trail_id}"],
        "props": {"d": f"M {x0:g},{y0:g}"},
    })

    timeline = {"loop": True, "loopDelay": 1200, "steps": steps_json}
    timeline_json = _timeline_island_json(timeline)

    # Reduced-motion/print static fallback, same dual-render precedent as
    # array-ops: the segment sequence stays fully readable without any motion.
    op_lines = "".join(
        f"<li>from ({fx:g}, {fy:g}) to ({tx:g}, {ty:g})</li>"
        for (fx, fy), (tx, ty) in zip(anim.points, anim.points[1:])
    )
    static_fallback = f'<ol class="anim__path-steps-static">{op_lines}</ol>'

    return (
        '<div class="anim anim--path-trace">'
        f'<p class="anim__caption" id="{caption_id}" data-anim-id="{caption_id}">'
        f"{html.escape(anim.caption)}</p>"
        f'<svg class="anim__path" dir="ltr" '
        f'viewBox="{min_x:g} {min_y:g} {max_x - min_x:g} {max_y - min_y:g}">'
        f"{axis}{labels}"
        f'<polyline class="anim__path-line" points="{points_attr}"></polyline>'
        f'<path class="anim__path-trail" id="{trail_id}" d="M {x0:g},{y0:g}"></path>'
        f'<circle class="anim__path-marker" id="{marker_id}" r="1.2" '
        f'cx="{x0:g}" cy="{y0:g}"></circle>'
        "</svg>"
        f'<script type="application/json" class="anim__timeline" data-anim-id="{caption_id}">'
        f"{timeline_json}</script>"
        f"{static_fallback}</div>"
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
    quiz_count: int = 0
    uses_mermaid: bool = False
    uses_animate: bool = False
    topics_missing_visual: list[str] = field(default_factory=list)
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
    quiz_numbers: dict[str, int] = {}
    quiz_count = 0
    uses_mermaid = False
    uses_animate = False

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
            replacements[fence.token] = _animate_html(anim, fence.token)
        else:
            replacements[fence.token] = _callout_html(fence.kind, fence.body)

    html_body = _md("\n".join(out))
    html_body = restore(html_body, replacements)
    html_body = restore(html_body, injector.replacements)

    for topic_id in (s.topic_id for s in sections if s.topic_id):
        quizzes_per_topic.setdefault(topic_id, 0)

    topics_missing_visual = [
        tid for tid in dict.fromkeys(s.topic_id for s in sections if s.topic_id)
        if topic_visual_status.get(tid) not in ("visual", "justified")
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
        quiz_count=quiz_count,
        uses_mermaid=uses_mermaid,
        uses_animate=uses_animate,
        topics_missing_visual=topics_missing_visual,
        topics_missing_quiz=topics_missing_quiz,
        errors=errors,
    )
