"""The review loop's terminating machinery.

Blocking findings cost another pass; noted findings never do. Without that split the loop
cannot terminate, because there is always something a reviewer could improve.
"""

import json
import re
from pathlib import Path

from p2c.validate import Finding

MAX_PASSES = 3
REVIEWERS = ("novice-simulator", "rubric-auditor")

# code -> (route, blocking)
REVIEW_CODES: dict[str, tuple[str, bool]] = {
    # Blocking: these trigger a re-run of exactly one unit.
    "jargon_undefined": ("writer", True),
    "topic_without_quiz": ("writer", True),
    "quiz_needs_outside_knowledge": ("writer", True),
    "analogy_misleading": ("writer", True),
    "unsupported_claim": ("researcher", True),
    "missing_background": ("researcher", True),
    "topic_missing": ("summarizer", True),
    "render_failure": ("build", True),
    # Noted: recorded, never looped.
    "verbosity": ("writer", False),
    "style": ("writer", False),
    "missing_visual": ("writer", False),
    "other": ("writer", False),
}

_REQUIRED_TOP = ("reviewer", "pass", "findings")
_REQUIRED_FINDING = ("code", "message")
_WHITESPACE = re.compile(r"\s+")


class ReviewError(ValueError):
    """A reviewer's output file is missing, unparseable, or off-contract."""


def validate_review(obj: object) -> list[str]:
    problems: list[str] = []
    if not isinstance(obj, dict):
        return ["review must be a JSON object"]
    for key in _REQUIRED_TOP:
        if key not in obj:
            problems.append(f"review is missing required key {key!r}")
    if obj.get("reviewer") not in REVIEWERS and "reviewer" in obj:
        problems.append(f"unknown reviewer {obj['reviewer']!r}; expected one of {list(REVIEWERS)}")
    if "pass" in obj:
        number = obj["pass"]
        if not isinstance(number, int) or not 1 <= number <= MAX_PASSES:
            problems.append(f"review pass must be between 1 and {MAX_PASSES}, got {number!r}")
    findings = obj.get("findings")
    if "findings" in obj and not isinstance(findings, list):
        problems.append("review findings must be a list")
        return problems
    for i, finding in enumerate(findings or []):
        where = f"review findings[{i}]"
        if not isinstance(finding, dict):
            problems.append(f"{where} must be an object")
            continue
        for key in _REQUIRED_FINDING:
            if key not in finding:
                problems.append(f"{where} is missing required key {key!r}")
        if "code" in finding and finding["code"] not in REVIEW_CODES:
            problems.append(
                f"{where}: unknown finding code {finding['code']!r}; "
                f"expected one of {sorted(REVIEW_CODES)}"
            )
        message = finding.get("message")
        if "message" in finding and (not isinstance(message, str) or not message.strip()):
            problems.append(f"{where}: message must be a non-empty string")
    return problems


def load_review(path: Path) -> dict:
    try:
        raw = Path(path).read_text(encoding="utf-8")
    except OSError as exc:
        raise ReviewError(f"{path}: cannot be read ({exc})") from exc
    try:
        obj = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ReviewError(f"{path} is not valid JSON: {exc}") from exc
    problems = validate_review(obj)
    if problems:
        raise ReviewError(f"{path} is invalid:\n  - " + "\n  - ".join(problems))
    return obj


def findings_from_review(obj: dict) -> list[Finding]:
    """Route and blocking come from the contract, never from the reviewer."""
    out: list[Finding] = []
    for raw in obj["findings"]:
        route, is_blocking = REVIEW_CODES[raw["code"]]
        out.append(
            Finding(
                code=raw["code"],
                message=raw["message"],
                blocking=is_blocking,
                route=route,
                module=raw.get("module"),
                topic=raw.get("topic"),
            )
        )
    return out


def finding_key(finding: Finding) -> str:
    """Identity for dedup and oscillation detection. Wording changes must not create a
    'new' finding, or the loop can never converge."""
    message = _WHITESPACE.sub(" ", finding.message).strip().lower()
    return "|".join([finding.code, finding.module or "-", finding.topic or "-", message])


def new_blocking(current: list[Finding], seen_keys: set[str]) -> list[Finding]:
    return [f for f in current if f.blocking and finding_key(f) not in seen_keys]


def oscillating(current: list[Finding], fixed_keys: set[str]) -> list[Finding]:
    """A finding that reappears after being marked fixed is recorded, not re-fixed."""
    return [f for f in current if finding_key(f) in fixed_keys]


def should_continue(pass_number: int, new_blocking_count: int) -> bool:
    if pass_number >= MAX_PASSES:
        return False
    return new_blocking_count > 0


def render_known_issues(findings: list[Finding], *, course_title: str) -> str:
    blocking = [f for f in findings if f.blocking]
    if not blocking:
        return ""
    lines = [
        f"# Known issues — {course_title}",
        "",
        "These problems survived three review passes and were not resolved. The course",
        "still ships, because you need to know which parts to distrust rather than",
        "discovering it yourself.",
        "",
    ]
    for finding in blocking:
        where = " / ".join(part for part in (finding.module, finding.topic) if part)
        lines.append(f"- **{finding.code}**{f' ({where})' if where else ''}: {finding.message}")
    lines += [
        "",
        f"Recorded after three review passes. {len(blocking)} unresolved blocking "
        "finding(s).",
        "",
    ]
    return "\n".join(lines)


def missed_expected(review_obj: dict, expected: dict) -> list[str]:
    """Grade a reviewer against a known-defect fixture.

    Each must_catch entry needs one finding with the right code whose message or evidence
    mentions every required word. Anything else counts as missed.
    """
    missed: list[str] = []
    for entry in expected["must_catch"]:
        words = [w.lower() for w in entry.get("must_mention", [])]
        hit = False
        for raw in review_obj.get("findings", []):
            if raw.get("code") != entry["code"]:
                continue
            haystack = f"{raw.get('message', '')} {raw.get('evidence', '')}".lower()
            if all(word in haystack for word in words):
                hit = True
                break
        if not hit:
            missed.append(
                f"{entry['code']}: no finding mentioning {entry.get('must_mention', [])}"
            )
    return missed


def main(argv: list[str]) -> int:
    import argparse

    parser = argparse.ArgumentParser(prog="p2c.review")
    sub = parser.add_subparsers(dest="command", required=True)

    check = sub.add_parser("check", help="validate a reviewer's JSON file")
    check.add_argument("path", type=Path)

    known = sub.add_parser("known-issues", help="render KNOWN-ISSUES.md from review files")
    known.add_argument("paths", nargs="+", type=Path)
    known.add_argument("--title", required=True)
    known.add_argument("--out", required=True, type=Path)

    args = parser.parse_args(argv)
    if args.command == "check":
        obj = load_review(args.path)
        print(json.dumps({"reviewer": obj["reviewer"], "pass": obj["pass"],
                          "findings": len(obj["findings"])}, indent=2))
        return 0

    findings: list[Finding] = []
    for path in args.paths:
        findings.extend(findings_from_review(load_review(path)))
    text = render_known_issues(findings, course_title=args.title)
    if text:
        args.out.write_text(text, encoding="utf-8")
        print(json.dumps({"written": str(args.out),
                          "blocking": len([f for f in findings if f.blocking])}, indent=2))
    else:
        print(json.dumps({"written": None, "blocking": 0}, indent=2))
    return 0


if __name__ == "__main__":
    import sys

    try:
        sys.exit(main(sys.argv[1:]))
    except ReviewError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)
