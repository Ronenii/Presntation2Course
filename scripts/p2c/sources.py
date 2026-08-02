"""Parses citation URLs out of the researcher agent's per-topic notes file.

Kept strict on purpose, same rationale as quiz.py's grammar: a malformed source
line is a build-time signal, not something to silently swallow or guess at.
"""

import html
import re
from dataclasses import dataclass

_SOURCES_HEADING = re.compile(r"^##\s+Sources\s*$")
_HEADING = re.compile(r"^#{1,6}\s")
_ENTRY = re.compile(r"^-\s*(?P<title>.+):\s*(?P<url>https?://\S+)$")
_ENTRY_ANY_SCHEME = re.compile(r"^-\s*(?P<title>.+):\s*(?P<url>\S+)$")


class SourceError(ValueError):
    """A '## Sources' section that does not satisfy the grammar."""


@dataclass
class Source:
    title: str
    url: str


def parse_research_sources(markdown_text: str) -> list[Source]:
    lines = markdown_text.split("\n")
    in_sources = False
    sources: list[Source] = []
    for raw in lines:
        line = raw.rstrip()
        if _SOURCES_HEADING.match(line):
            in_sources = True
            continue
        if not in_sources:
            continue
        if _HEADING.match(line):
            break
        if not line.strip():
            continue
        match = _ENTRY.match(line.strip())
        if not match:
            fallback = _ENTRY_ANY_SCHEME.match(line.strip())
            if fallback:
                raise SourceError(
                    f"source url must start with http:// or https://, "
                    f"got {fallback.group('url')!r}"
                )
            raise SourceError(f"expected 'Title: url', got {line.strip()!r}")
        title, url = match.group("title").strip(), match.group("url").strip()
        sources.append(Source(title=title, url=url))
    return sources


def sources_html_by_topic(
    topic_sources: dict[str, list[Source]], topic_titles: dict[str, str]
) -> str:
    groups = []
    for topic_id, sources in topic_sources.items():
        if not sources:
            continue
        title = html.escape(topic_titles.get(topic_id, topic_id))
        items = "".join(
            f'<li><a href="{html.escape(s.url, quote=True)}">{html.escape(s.title)}</a></li>'
            for s in sources
        )
        groups.append(
            f'<div class="sources-group"><h3>{title}</h3><ol class="sources">{items}</ol></div>'
        )
    return "".join(groups)
