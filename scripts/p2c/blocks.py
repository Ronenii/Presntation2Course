"""Pull fenced blocks and inline code out of markdown, and put HTML back.

python-markdown renders ```quiz as a code block, and glossary injection must never
touch code. Both problems are solved by extracting to alphanumeric tokens first.
"""

import re
from dataclasses import dataclass

_OPEN = re.compile(r"^\s{0,3}```\s*(?P<info>[A-Za-z0-9_-]*)\s*$")
_CLOSE = re.compile(r"^\s{0,3}```\s*$")
_INLINE_CODE = re.compile(r"`[^`\n]+`")

BLOCK_TOKEN = "P2CBLOCK{}ENDBLOCK"
CODE_TOKEN = "P2CCODE{}ENDCODE"


@dataclass
class Fence:
    kind: str
    body: str
    token: str


def extract_fences(
    md: str, kinds: tuple[str, ...] | None = None
) -> tuple[str, list[Fence]]:
    """Replace each matching fenced block with a token line.

    kinds=None extracts every fence. An unterminated fence is left untouched.
    """
    lines = md.split("\n")
    out: list[str] = []
    fences: list[Fence] = []
    i = 0
    while i < len(lines):
        opening = _OPEN.match(lines[i])
        kind = opening.group("info").lower() if opening else None
        if opening and (kinds is None or kind in kinds):
            close = next(
                (j for j in range(i + 1, len(lines)) if _CLOSE.match(lines[j])), None
            )
            if close is not None:
                token = BLOCK_TOKEN.format(len(fences))
                fences.append(
                    Fence(kind=kind or "", body="\n".join(lines[i + 1 : close]), token=token)
                )
                # Blank lines around the token, so two adjacent blocks cannot be merged
                # into one paragraph and end up as block HTML nested inside a <p>.
                out.extend(["", token, ""])
                i = close + 1
                continue
        out.append(lines[i])
        i += 1
    return "\n".join(out), fences


def protect_inline_code(md: str) -> tuple[str, dict[str, str]]:
    """Swap `code` spans for tokens so term injection cannot reach inside them."""
    mapping: dict[str, str] = {}

    def swap(match: re.Match[str]) -> str:
        token = CODE_TOKEN.format(len(mapping))
        mapping[token] = match.group(0)
        return token

    return _INLINE_CODE.sub(swap, md), mapping


def restore(text: str, replacements: dict[str, str]) -> str:
    """Put content back, unwrapping the <p> python-markdown may have added."""
    for token, value in replacements.items():
        text = text.replace(f"<p>{token}</p>", value).replace(token, value)
    return text
