"""The build's validations, and the routing that keeps re-runs small.

Only the affected unit re-runs. Anything not attributable to a single module or topic
routes to "build", which re-renders with no agent involved at all.
"""

import math
import re
from dataclasses import asdict, dataclass

from p2c.mdrender import ANIMATE_PATTERNS, Rendered
from p2c.outline import iter_topics, topic_ids

ROUTE_FOR_CODE = {
    "quiz_malformed": "writer",
    "topic_without_quiz": "writer",
    "topic_without_visual": "writer",
    "mermaid_unparseable": "writer",
    "figure_malformed": "writer",
    "animate_malformed": "writer",
    "glossary_malformed": "build",
    "jargon_without_glossary": "writer",
    "placeholder": "writer",
    "topic_missing": "summarizer",
    "topic_unknown": "writer",
    "external_request": "build",
    "animation_floor": "writer",
    "animate_pattern_monoculture": "writer",
}

ANIMATION_FLOOR = 0.25

# Above this share of a course's animate blocks, one pattern has stopped being a
# choice and become a default. Seven patterns exist; `pipeline` is the most
# generic-sounding of them ("input flows through stages"), so almost any topic
# can be narrated to fit it -- which is exactly how a course ends up with 18 of
# 61 blocks identical and none carrying the specific relationship it teaches.
# The threshold is deliberately loose: a course legitimately leaning on two or
# three patterns stays well under it, and only a genuine monoculture trips it.
_PATTERN_SHARE_CEILING = 0.5
_PATTERN_MONOCULTURE_MIN_BLOCKS = 6  # below this, a high share is just a small n

PLACEHOLDER_PATTERNS = (
    r"\bTODO\b",
    r"\bTBD\b",
    r"\bFIXME\b",
    r"\bXXX\b",
    r"\blorem ipsum\b",
    r"\[insert\b",
    r"<placeholder",
)
_PLACEHOLDER = re.compile("|".join(PLACEHOLDER_PATTERNS), re.IGNORECASE)

_RESOURCE_TAG = re.compile(
    r"<(?:script|img|link|iframe|video|audio|source|embed|object|track)\b[^>]*?"
    r"\b(?:src|href|data)\s*=\s*[\"'](?P<url>[^\"']+)[\"']",
    re.IGNORECASE,
)
_CSS_URL = re.compile(r"url\(\s*[\"']?(?P<url>[^)\"']+)", re.IGNORECASE)
_NETWORK_API = re.compile(r"\bfetch\s*\(|\bXMLHttpRequest\b|\bsendBeacon\b|\bEventSource\b")
_ABSOLUTE = re.compile(r"^(?:[a-z][a-z0-9+.-]*:)?//", re.IGNORECASE)


@dataclass
class Finding:
    code: str
    message: str
    blocking: bool = True
    route: str = "writer"
    module: str | None = None
    topic: str | None = None


def blocking(findings: list[Finding]) -> list[Finding]:
    return [f for f in findings if f.blocking]


def findings_to_json(findings: list[Finding]) -> list[dict]:
    return [asdict(f) for f in findings]


def _finding(code: str, message: str, *, is_blocking: bool = True, **kw) -> Finding:
    return Finding(
        code=code, message=message, blocking=is_blocking, route=ROUTE_FOR_CODE[code], **kw
    )


def anchor_to_module(rendered: Rendered, outline: dict) -> dict[str, str]:
    """Attribute every section anchor to a module id by ordinal position."""
    module_ids = [m["id"] for m in outline["modules"]]
    mapping: dict[str, str] = {}
    current: str | None = None
    seen = 0
    for section in rendered.sections:
        if section.level == 2:
            current = module_ids[seen] if seen < len(module_ids) else None
            seen += 1
        if current:
            mapping[section.id] = current
    return mapping


def _topic_of_anchor(rendered: Rendered) -> dict[str, str]:
    return {s.id: s.topic_id for s in rendered.sections if s.topic_id}


def _external_requests(html_text: str) -> list[str]:
    hits: list[str] = []
    for match in _RESOURCE_TAG.finditer(html_text):
        url = match.group("url")
        if _ABSOLUTE.match(url):
            hits.append(url)
    for match in _CSS_URL.finditer(html_text):
        url = match.group("url").strip()
        if _ABSOLUTE.match(url):
            hits.append(url)
    for match in re.finditer(r"@import\s+[\"'](?P<url>[^\"']+)", html_text, re.IGNORECASE):
        if _ABSOLUTE.match(match.group("url")):
            hits.append(match.group("url"))
    for match in _NETWORK_API.finditer(html_text):
        hits.append(match.group(0))
    return hits


def animation_floor_findings(rendered, justified_topics: set[str]) -> list[Finding]:
    """At least a quarter of the topics that owe a visual must animate.

    The denominator deliberately reuses "owes a visual" (every topic without a
    `no-visual` justification) rather than the outline's `depth` field: the
    build is not depth-aware, and one definition is better than two that can
    drift apart. `brief` topics carry `no-visual` by rule, so they drop out.
    """
    owing = [t for t in dict.fromkeys(rendered.topic_ids) if t not in justified_topics]
    if not owing:
        return []
    required = math.ceil(ANIMATION_FLOOR * len(owing))
    animated = sum(
        1 for t in owing if rendered.animations_per_topic.get(t, 0) > 0
    )
    if animated >= required:
        return []

    candidates = [t for t in rendered.linear_mermaid_topics if t in owing]
    if candidates:
        advice = (
            "convert these topics' mermaid diagrams to `animate` blocks — each is a "
            "linear chain with no fan-out, which is a sequence rather than a "
            f"structure: {', '.join(sorted(candidates))}"
        )
    else:
        advice = (
            "no linear mermaid chains were found to convert, so add `animate` blocks "
            "(pipeline, layer-stack, transform, state-machine, state-toggle) to the "
            "topics whose content is a sequence rather than a structure"
        )
    return [
        _finding(
            "animation_floor",
            f"only {animated} of {len(owing)} topics that need a visual use an "
            f"`animate` block ({required} required, {int(ANIMATION_FLOOR * 100)}%); "
            f"{advice}",
        )
    ]


def animate_pattern_findings(rendered) -> list[Finding]:
    """No single animate pattern may dominate the course's animations.

    A non-blocking finding: an over-used pattern makes for a monotonous course,
    but it is a quality problem, not a broken build -- unlike a malformed block.
    It is reported so the writer re-picks per topic instead of defaulting, which
    is what `references/quiz-format.md`'s selection table exists to prevent.
    """
    counts = rendered.animate_pattern_counts
    total = sum(counts.values())
    if total < _PATTERN_MONOCULTURE_MIN_BLOCKS:
        return []
    pattern, count = max(counts.items(), key=lambda kv: kv[1])
    if count / total <= _PATTERN_SHARE_CEILING:
        return []
    unused = sorted(set(ANIMATE_PATTERNS) - set(counts))
    advice = "re-pick per topic from the selection table in references/quiz-format.md"
    if unused:
        advice += f" — these patterns went entirely unused: {', '.join(unused)}"
    return [
        _finding(
            "animate_pattern_monoculture",
            f"{count} of {total} animate blocks use `{pattern}` "
            f"({round(100 * count / total)}%, ceiling "
            f"{int(_PATTERN_SHARE_CEILING * 100)}%); {advice}",
            is_blocking=False,
        )
    ]


def validate_course(rendered: Rendered, outline: dict, html_text: str) -> list[Finding]:
    findings: list[Finding] = []
    modules = anchor_to_module(rendered, outline)
    topics = _topic_of_anchor(rendered)

    # 1 & 2 & 3: structural problems mdrender already found, re-attributed.
    for error in rendered.errors:
        anchor, _, message = error.partition(": ")
        if anchor == "glossary block":
            findings.append(_finding("glossary_malformed", message))
            continue
        if message.startswith("mermaid "):
            code = "mermaid_unparseable"
        elif message.startswith("figure "):
            code = "figure_malformed"
        elif message.startswith("animate "):
            code = "animate_malformed"
        else:
            code = "quiz_malformed"
        findings.append(
            _finding(
                code,
                f"{anchor}: {message}",
                module=modules.get(anchor),
                topic=topics.get(anchor),
            )
        )

    # 4: every outline topic present, and nothing invented.
    expected = topic_ids(outline)
    present = set(rendered.topic_ids)
    module_of_topic = {
        topic["id"]: module["id"]
        for module in outline["modules"]
        for topic in module["topics"]
    }
    for topic_id in expected:
        if topic_id not in present:
            findings.append(
                _finding(
                    "topic_missing",
                    f"outline topic {topic_id!r} does not appear in the course",
                    topic=topic_id,
                    module=module_of_topic[topic_id],
                )
            )
    for topic_id in rendered.topic_ids:
        if topic_id not in set(expected):
            findings.append(
                _finding(
                    "topic_unknown",
                    f"course contains topic {topic_id!r}, which is not in outline.json",
                    is_blocking=False,
                    topic=topic_id,
                )
            )

    # 5: every present topic has a quiz, or an explicit non-quizzable justification.
    anchor_of_topic = {v: k for k, v in topics.items()}
    for topic_id in rendered.topics_missing_quiz:
        findings.append(
            _finding(
                "topic_without_quiz",
                f"topic {topic_id!r} has no valid quiz and no "
                "<!-- no-quiz: ... --> justification",
                topic=topic_id,
                module=modules.get(anchor_of_topic.get(topic_id, "")),
            )
        )

    # 5b: every present topic has a visual, or an explicit non-spatial justification.
    for topic_id in rendered.topics_missing_visual:
        findings.append(
            _finding(
                "topic_without_visual",
                f"topic {topic_id!r} has no visual (mermaid, figure, animate, or inline "
                "<svg>) and no <!-- no-visual: ... --> justification",
                topic=topic_id,
                module=modules.get(anchor_of_topic.get(topic_id, "")),
            )
        )

    # 5c: at least a quarter of the topics that owe a visual must animate, or a
    # generated course can satisfy "has a visual" entirely with mermaid and ship
    # with zero motion. See animation_floor_findings for the exact rule.
    findings.extend(
        animation_floor_findings(rendered, set(rendered.topics_visual_justified))
    )
    findings.extend(animate_pattern_findings(rendered))

    # 6: every jargon term has a glossary entry. Reported per topic (rather than
    # pooled across the whole outline) so each finding is attributable to one writer.
    defined = {term.lower() for term in rendered.glossary}
    for module, topic in iter_topics(outline):
        undefined = sorted(t for t in topic["jargon"] if t.lower() not in defined)
        if undefined:
            findings.append(
                _finding(
                    "jargon_without_glossary",
                    "jargon with no glossary entry: " + ", ".join(undefined),
                    module=module["id"],
                    topic=topic["id"],
                )
            )

    # 7: no unresolved placeholders anywhere in the rendered body.
    for match in _PLACEHOLDER.finditer(rendered.html_body):
        findings.append(
            _finding("placeholder", f"unresolved placeholder {match.group(0)!r}")
        )

    # 8: no external requests in the shipped HTML.
    for url in _external_requests(html_text):
        findings.append(
            _finding("external_request", f"HTML would reach the network: {url}")
        )

    return findings
