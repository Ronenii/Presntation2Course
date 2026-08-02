"""course.md -> HTML body, TOC, glossary appendix.

Fenced blocks are extracted to tokens before python-markdown runs and restored as HTML
afterwards. Anchors, quiz ids and glossary term ids are all allocated here so nothing
downstream has to guess them.
"""

import html
import json
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


_BAR_WIDTH = 32
_BAR_GAP = 12
_BAR_MAX_HEIGHT = 120
_PATH_PADDING = 10


def _animate_html(anim: Animate, token: str) -> str:
    if anim.pattern == "step-reveal":
        return _step_reveal_html(anim, token)
    if anim.pattern == "state-toggle":
        # "Before"/"After" are literal English UI chrome -- like the "Analogy" callout
        # label, added by the render layer rather than the course-writer, so they stay
        # legible regardless of course language (including RTL). They are hidden during
        # normal animated playback and shown only in the print/reduced-motion static
        # presentation; see .anim__state-label in layout.css/print.css.
        return (
            '<div class="anim anim--state-toggle">'
            '<div class="anim__state anim__state--before">'
            f'<span class="anim__state-label">Before</span>{html.escape(anim.before)}</div>'
            '<div class="anim__state anim__state--after">'
            f'<span class="anim__state-label">After</span>{html.escape(anim.after)}</div>'
            '</div>'
        )
    if anim.pattern == "array-ops":
        return _array_ops_html(anim, token)
    # path-trace
    return _path_trace_html(anim)


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
    timeline_json = html.escape(json.dumps(timeline), quote=False)
    return (
        f'<div class="anim anim--step-reveal"><ol class="anim__steps">{items}</ol>'
        f'<script type="application/json" class="anim__timeline">{timeline_json}</script>'
        "</div>"
    )


def _array_ops_html(anim: Animate, token: str) -> str:
    """Bars occupy fixed slot positions; each bar is a <g> that TRANSLATES
    between slots as ops replay, so a "swap" is a bar physically crossing the
    others rather than two bars quietly changing opacity in place -- the
    previous rects-in-place-with-stacked-style-declarations approach never
    moved anything and silently dropped every op but the last one touching a
    given index (CSS custom-property redeclaration is last-wins). Each op is
    now its own timed step with its own keyframe percentage window, so
    "compare 0 1" and "swap 0 1" both get their own visible moment even when
    they touch the same indices.
    """
    max_value = max(anim.array) or 1
    n = len(anim.array)
    slot_width = _BAR_WIDTH + _BAR_GAP
    width = n * slot_width
    # slot_of_bar[original_index] = which slot that bar currently occupies, replayed
    # step by step. Bars are tracked by their ORIGINAL index (not by slot), so each
    # bar's <g> carries one translate keyframe across every step even as its slot
    # changes when it's swapped -- the value shown on a bar never changes, only its
    # x-position does.
    slot_of_bar = list(range(n))
    timeline: list[list[tuple[int, str]]] = [
        [(slot_of_bar[i], "idle")] for i in range(n)
    ]
    for verb, a, b in anim.ops:
        if verb == "swap":
            slot_of_bar[a], slot_of_bar[b] = slot_of_bar[b], slot_of_bar[a]
        for i in range(n):
            if i == a or i == b:
                timeline[i].append((slot_of_bar[i], verb))
            else:
                timeline[i].append((slot_of_bar[i], "idle"))
    steps = len(anim.ops)
    cycle = (steps + 1) * STEP_SECONDS
    groups = []
    keyframes = []
    # Keyframe names must be unique per animate block on the page (they are NOT
    # scoped by the surrounding <style> tag -- @keyframes names are document-global),
    # and deterministic across identical reruns (this project's whole build is
    # required to be byte-reproducible, so id()/random-based names are never an
    # option here). fence.token ("P2CBLOCK{n}ENDBLOCK") is already a stable,
    # unique-per-occurrence string, but the token's own literal text must NEVER
    # appear inside this function's returned HTML: blocks.restore() does a second,
    # unconditional text.replace(token, value) pass after substituting every
    # token, and if `value` (this return value) itself contains the token
    # substring, that second pass matches it too and splices the whole HTML block
    # in a second time, nested inside its own keyframe name. Extracting just the
    # digits (the token's ordinal, e.g. "0" from "P2CBLOCK0ENDBLOCK") keeps
    # uniqueness/determinism without ever reproducing the marker text itself.
    token_seed = re.sub(r"\D", "", token) or "0"
    for bar_index in range(n):
        value = anim.array[bar_index]
        height = round((value / max_value) * _BAR_MAX_HEIGHT, 1)
        y = _BAR_MAX_HEIGHT - height
        frames = timeline[bar_index]
        name = f"anim-array-bar-{token_seed}-{bar_index}"
        # A CSS class can only apply one fixed look for the whole animation, but a
        # bar's highlight needs to change PER STEP (idle most of the time, colored
        # only during the step(s) that touch it) -- so color is driven by the same
        # per-step keyframe as position, as a `fill` value alongside `transform`,
        # rather than a static class. Each step gets a sharp on/off transition (two
        # stops at the same percentage) so a highlight reads as a discrete step,
        # not a fade.
        pct_stops = []
        for step_i, (slot, kind) in enumerate(frames):
            start_pct = round(step_i / (steps + 1) * 100, 3)
            end_pct = round((step_i + 1) / (steps + 1) * 100, 3)
            x = slot * slot_width
            fill = f"var(--anim-array-{kind})" if kind != "idle" else "var(--anim-array-idle)"
            pct_stops.append(
                f"{start_pct}% {{ transform: translateX({x}px); --bar-fill: {fill}; }}"
            )
            pct_stops.append(
                f"{end_pct}% {{ transform: translateX({x}px); --bar-fill: {fill}; }}"
            )
        keyframes.append(f"@keyframes {name} {{ {' '.join(pct_stops)} }}")
        groups.append(
            f'<g class="anim__array-bar" '
            f'style="animation-name: {name}; animation-duration: {cycle}s;">'
            f'<rect x="0" y="{y}" width="{_BAR_WIDTH}" height="{height}"></rect>'
            f'<text class="anim__array-label" x="{_BAR_WIDTH / 2:g}" '
            f'y="{_BAR_MAX_HEIGHT + 16}">{html.escape(str(value))}</text>'
            "</g>"
        )
    style_tag = f"<style>{' '.join(keyframes)}</style>" if keyframes else ""
    # Reduced-motion/print static fallback (same dual-render precedent as
    # state-toggle): the animated <svg> is hidden and this plain step list shown
    # instead, rather than trying to freeze an infinitely-looping animation
    # mid-cycle (animation-play-state: paused has no defined "which lap" to stop
    # on for an `infinite` animation, so it can't reliably show the final result).
    op_lines = "".join(
        f"<li>{html.escape(verb)} index {a}"
        + (f" and {b}" if b is not None else "")
        + "</li>"
        for verb, a, b in anim.ops
    )
    static_fallback = f'<ol class="anim__array-steps-static">{op_lines}</ol>'
    return (
        f'<div class="anim anim--array-ops"><svg class="anim__array" '
        f'viewBox="0 0 {width} {_BAR_MAX_HEIGHT + 20}">{style_tag}{"".join(groups)}</svg>'
        f"{static_fallback}</div>"
    )


def _path_trace_html(anim: Animate) -> str:
    xs = [x for x, _ in anim.points]
    ys = [y for _, y in anim.points]
    data_min_x, data_max_x = min(xs), max(xs)
    data_min_y, data_max_y = min(ys), max(ys)
    min_x, max_x = data_min_x - _PATH_PADDING, data_max_x + _PATH_PADDING
    min_y, max_y = data_min_y - _PATH_PADDING, data_max_y + _PATH_PADDING
    points_attr = " ".join(f"{x:g},{y:g}" for x, y in anim.points)
    path_d = "M " + " L ".join(f"{x:g},{y:g}" for x, y in anim.points)
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
    return (
        '<div class="anim anim--path-trace">'
        f'<svg class="anim__path" dir="ltr" '
        f'viewBox="{min_x:g} {min_y:g} {max_x - min_x:g} {max_y - min_y:g}">'
        f"{axis}{labels}"
        f'<polyline class="anim__path-line" points="{points_attr}"></polyline>'
        f'<circle class="anim__path-marker" r="4" '
        f"style=\"offset-path: path('{path_d}')\"></circle>"
        "</svg>"
        f'<p class="anim__path-caption">{html.escape(anim.caption)}</p>'
        "</div>"
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
