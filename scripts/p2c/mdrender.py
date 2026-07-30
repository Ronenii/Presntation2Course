"""course.md -> HTML body, TOC, glossary appendix.

Fenced blocks are extracted to tokens before python-markdown runs and restored as HTML
afterwards. Anchors, quiz ids and glossary term ids are all allocated here so nothing
downstream has to guess them.
"""

import html
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

_ANIMATE_KEY = re.compile(r"^(?P<key>pattern|before|after):\s*(?P<value>.*)$")
_ANIMATE_STEP = re.compile(r"^\s*-\s*(?P<text>.+)$")


class AnimateError(ValueError):
    """An animate block that does not satisfy the grammar."""


@dataclass
class Animate:
    pattern: str
    steps: list[str] = field(default_factory=list)
    before: str = ""
    after: str = ""


def parse_animate(body: str) -> Animate:
    pattern: str | None = None
    steps: list[str] = []
    before: str | None = None
    after: str | None = None
    in_steps = False

    for raw in body.split("\n"):
        line = raw.rstrip()
        if not line.strip():
            continue
        step = _ANIMATE_STEP.match(line) if in_steps else None
        if step:
            steps.append(step.group("text").strip())
            continue
        key = _ANIMATE_KEY.match(line)
        if key:
            name, value = key.group("key"), key.group("value").strip()
            in_steps = False
            if name == "pattern":
                if pattern is not None:
                    raise AnimateError("animate has more than one 'pattern:' line")
                pattern = value
            elif name == "before":
                before = value
            else:
                after = value
            continue
        if line.strip() == "steps:":
            in_steps = True
            continue
        raise AnimateError(f"unrecognised line in animate block: {line.strip()!r}")

    if pattern not in ("step-reveal", "state-toggle"):
        raise AnimateError(
            f"animate pattern must be 'step-reveal' or 'state-toggle', got {pattern!r}"
        )
    if pattern == "step-reveal":
        if len(steps) < 2:
            raise AnimateError("step-reveal needs at least 2 steps")
        if before or after:
            raise AnimateError("step-reveal does not use 'before:'/'after:'")
    else:
        if not before or not after:
            raise AnimateError("state-toggle needs both 'before:' and 'after:'")
        if steps:
            raise AnimateError("state-toggle does not use 'steps:'")
    return Animate(pattern=pattern, steps=steps, before=before or "", after=after or "")


def _animate_html(anim: Animate) -> str:
    if anim.pattern == "step-reveal":
        cycle = len(anim.steps) * STEP_SECONDS
        items = "".join(
            f'<li class="anim__step" style="animation-duration: {cycle}s; '
            f'animation-delay: {-(i * STEP_SECONDS)}s">{html.escape(step)}</li>'
            for i, step in enumerate(anim.steps)
        )
        return f'<div class="anim anim--step-reveal"><ol class="anim__steps">{items}</ol></div>'
    return (
        '<div class="anim anim--state-toggle">'
        f'<div class="anim__state anim__state--before">{html.escape(anim.before)}</div>'
        f'<div class="anim__state anim__state--after">{html.escape(anim.after)}</div>'
        '</div>'
    )


_TOPIC_MARKER = re.compile(r"^\s*<!--\s*topic:\s*(?P<id>[^\s>]+)\s*-->\s*$")
_HEADING = re.compile(r"^(?P<hashes>#{1,6})\s+(?P<text>.+?)\s*$")
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
        buffer.append(line)
    flush()

    replacements: dict[str, str] = {}
    quizzes_per_topic: dict[str, int] = {}
    quiz_numbers: dict[str, int] = {}
    quiz_count = 0
    uses_mermaid = False

    for fence in fences:
        anchor, topic_id = token_owner.get(fence.token, ("course", None))
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
            replacements[fence.token] = _animate_html(anim)
        else:
            replacements[fence.token] = _callout_html(fence.kind, fence.body)

    html_body = _md("\n".join(out))
    html_body = restore(html_body, replacements)
    html_body = restore(html_body, injector.replacements)

    for topic_id in (s.topic_id for s in sections if s.topic_id):
        quizzes_per_topic.setdefault(topic_id, 0)

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
        errors=errors,
    )
