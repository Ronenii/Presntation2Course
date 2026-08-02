"""Parses citation URLs out of the researcher agent's per-topic notes file.

Kept strict on purpose, same rationale as quiz.py's grammar: a malformed source
line is a build-time signal, not something to silently swallow or guess at.
"""

import html
import re
from dataclasses import dataclass

_SOURCES_HEADING = re.compile(r"^##\s+Sources\s*$")
_HEADING = re.compile(r"^#{1,6}\s")
_ENTRY = re.compile(r"^-\s*(?P<title>.+):\s*(?P<url>\S+)$")


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
        stripped = line.strip()
        if not stripped.startswith("- "):
            raise SourceError(f"expected 'Title: url', got {stripped!r}")
        stripped = stripped[2:]  # Remove "- "

        # Look for any URL-like pattern (scheme://...)
        # First try to find http/https URLs
        http_pos = stripped.find("http://")
        https_pos = stripped.find("https://")
        url_start = None
        if http_pos != -1 and https_pos != -1:
            url_start = min(http_pos, https_pos)
        elif http_pos != -1:
            url_start = http_pos
        elif https_pos != -1:
            url_start = https_pos

        # If no http/https, try to find any scheme:// pattern to reject it properly
        if url_start is None:
            scheme_match = re.search(r"\w+://", stripped)
            if scheme_match:
                # Found a URL with a non-http scheme
                url_start = scheme_match.start()
                colon_pos = stripped.rfind(":", 0, url_start)
                if colon_pos == -1:
                    colon_pos = url_start - 1
                title = stripped[:colon_pos].strip() if colon_pos >= 0 else ""
                url = stripped[colon_pos + 1:].strip() if colon_pos >= 0 else stripped
                raise SourceError(f"source url must start with http:// or https://, got {url!r}")
            else:
                raise SourceError(f"expected 'Title: url', got {stripped!r}")

        # Find the colon right before the URL
        colon_pos = stripped.rfind(":", 0, url_start)
        if colon_pos == -1:
            raise SourceError(f"expected 'Title: url', got {stripped!r}")

        title = stripped[:colon_pos].strip()
        url = stripped[colon_pos + 1:].strip()

        if not url.startswith(("http://", "https://")):
            raise SourceError(f"source url must start with http:// or https://, got {url!r}")
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
