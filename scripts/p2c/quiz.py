"""The quiz block grammar: one q:, 3-4 options, exactly one [x], a non-empty why:.

Kept strict on purpose. A malformed quiz is a blocking build finding routed back to
the module's writer, which is cheaper than shipping a broken comprehension check.
"""

import html
import re
from dataclasses import dataclass

_OPTION = re.compile(r"^\s*-\s*\[(?P<mark>[ xX])\]\s*(?P<text>.*)$")
_KEY = re.compile(r"^(?P<key>q|why):\s*(?P<value>.*)$")


class QuizError(ValueError):
    """A quiz block that does not satisfy the grammar."""


@dataclass
class Quiz:
    question: str
    options: list[str]
    correct_index: int
    why: str


def parse_quiz(body: str) -> Quiz:
    question: str | None = None
    why: str | None = None
    options: list[str] = []
    correct: list[int] = []
    current: str | None = None  # which key trailing continuation lines belong to

    for raw in body.split("\n"):
        line = raw.rstrip()
        if not line.strip():
            continue
        option = _OPTION.match(line)
        if option:
            current = None
            if option.group("mark").lower() == "x":
                correct.append(len(options))
            options.append(option.group("text").strip())
            continue
        key = _KEY.match(line)
        if key:
            name, value = key.group("key"), key.group("value").strip()
            if name == "q":
                if question is not None:
                    raise QuizError("quiz has more than one 'q:' line")
                question, current = value, "q"
            else:
                if why is not None:
                    raise QuizError("quiz has more than one 'why:' line")
                why, current = value, "why"
            continue
        if current == "q" and not options:
            question = f"{question} {line.strip()}".strip()
            continue
        if current == "why":
            if raw and raw[0].isspace():
                why = f"{why} {line.strip()}".strip()
                continue
        raise QuizError(f"unrecognised line in quiz block: {line.strip()!r}")

    if question is None:
        raise QuizError("quiz is missing a 'q:' line")
    if not question:
        raise QuizError("quiz question is empty")
    if not 3 <= len(options) <= 4:
        raise QuizError(f"quiz needs 3 or 4 options, found {len(options)}")
    for n, text in enumerate(options, start=1):
        if not text:
            raise QuizError(f"quiz option {n} is empty")
    if len(correct) != 1:
        raise QuizError(f"quiz needs exactly one option marked [x], found {len(correct)}")
    if why is None:
        raise QuizError("quiz is missing a 'why:' line")
    if not why:
        raise QuizError("quiz explanation is empty")

    return Quiz(question=question, options=options, correct_index=correct[0], why=why)


def quiz_to_html(quiz: Quiz, qid: str) -> str:
    """Ungraded, retryable, stateless. No scores means no storage to corrupt.

    Rendered as <details>/<summary> so each quiz is collapsible; expanded by
    default (the `open` attribute) to match the pre-existing always-visible
    behavior, with collapse now available to the student.
    """
    esc = html.escape
    parts = [f'<details class="quiz" data-quiz="{esc(qid)}" open>']
    parts.append(f'<summary class="quiz__q">{esc(quiz.question)}</summary>')
    parts.append('<ol class="quiz__options">')
    for n, text in enumerate(quiz.options):
        correct = "true" if n == quiz.correct_index else "false"
        parts.append(
            f'<li><button type="button" class="quiz__option" '
            f'data-correct="{correct}" aria-describedby="{esc(qid)}-why">'
            f"{esc(text)}</button></li>"
        )
    parts.append("</ol>")
    parts.append(
        f'<p class="quiz__answer" hidden>Correct answer: '
        f"<strong>{esc(quiz.options[quiz.correct_index])}</strong></p>"
    )
    parts.append(f'<p class="quiz__why" id="{esc(qid)}-why" hidden>{esc(quiz.why)}</p>')
    parts.append("</details>")
    return "\n".join(parts)
