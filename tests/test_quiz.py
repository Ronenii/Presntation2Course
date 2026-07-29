import pytest

from p2c.quiz import Quiz, QuizError, parse_quiz, quiz_to_html

VALID = """q: What does a TLB actually cache?
- [ ] The contents of recently used pages
- [x] Virtual-to-physical page mappings
- [ ] The page table itself
why: It caches translations, not data. Confusing it with a data cache is
     the most common mistake here.
"""


def test_parses_a_valid_block():
    quiz = parse_quiz(VALID)
    assert isinstance(quiz, Quiz)
    assert quiz.question == "What does a TLB actually cache?"
    assert quiz.options == [
        "The contents of recently used pages",
        "Virtual-to-physical page mappings",
        "The page table itself",
    ]
    assert quiz.correct_index == 1
    assert quiz.why.startswith("It caches translations, not data.")
    assert "the most common mistake here." in quiz.why


def test_accepts_four_options_and_uppercase_marker():
    body = (
        "q: Pick one\n- [ ] a\n- [ ] b\n- [X] c\n- [ ] d\nwhy: because c\n"
    )
    quiz = parse_quiz(body)
    assert len(quiz.options) == 4
    assert quiz.correct_index == 2


def test_tolerates_blank_lines_and_trailing_whitespace():
    body = "\nq: Pick one  \n\n- [ ] a\n- [x] b\n- [ ] c\n\nwhy: b is right\n\n"
    assert parse_quiz(body).question == "Pick one"


@pytest.mark.parametrize(
    "body,message",
    [
        ("- [x] a\n- [ ] b\n- [ ] c\nwhy: w\n", "missing a 'q:' line"),
        ("q:   \n- [x] a\n- [ ] b\n- [ ] c\nwhy: w\n", "question is empty"),
        ("q: a\nq: b\n- [x] a\n- [ ] b\n- [ ] c\nwhy: w\n", "more than one 'q:'"),
        ("q: a\n- [ ] a\n- [ ] b\n- [ ] c\nwhy: w\n", "exactly one option"),
        ("q: a\n- [x] a\n- [x] b\n- [ ] c\nwhy: w\n", "exactly one option"),
        ("q: a\n- [x] a\n- [ ] b\nwhy: w\n", "3 or 4 options"),
        ("q: a\n- [x] a\n- [ ] b\n- [ ] c\n- [ ] d\n- [ ] e\nwhy: w\n", "3 or 4 options"),
        ("q: a\n- [x] a\n- [ ] b\n- [ ] c\n", "missing a 'why:' line"),
        ("q: a\n- [x] a\n- [ ] b\n- [ ] c\nwhy:   \n", "explanation is empty"),
        ("q: a\n- [x]   \n- [ ] b\n- [ ] c\nwhy: w\n", "option 1 is empty"),
        ("q: a\n- [x] a\n- [ ] b\n- [ ] c\nwhy: w\nstray line\n", "unrecognised line"),
        ("", "missing a 'q:' line"),
    ],
)
def test_rejects_malformed_blocks(body, message):
    with pytest.raises(QuizError, match=message):
        parse_quiz(body)


def test_html_marks_exactly_one_correct_option():
    quiz = parse_quiz(VALID)
    out = quiz_to_html(quiz, "m01-t02-q1")
    assert out.count('data-correct="true"') == 1
    assert out.count('data-correct="false"') == 2
    assert out.count("<button") == 3


def test_html_wires_ids_and_hides_the_answer_until_clicked():
    out = quiz_to_html(parse_quiz(VALID), "m01-t02-q1")
    assert '<div class="quiz" data-quiz="m01-t02-q1">' in out
    assert 'id="m01-t02-q1-why"' in out
    assert 'aria-describedby="m01-t02-q1-why"' in out
    assert '<p class="quiz__answer" hidden>' in out
    assert '<p class="quiz__why" id="m01-t02-q1-why" hidden>' in out


def test_html_escapes_content():
    quiz = Quiz(question="a < b?", options=["<x>", "y & z", "q"], correct_index=0, why="'why'")
    out = quiz_to_html(quiz, "q1")
    assert "a &lt; b?" in out
    assert "&lt;x&gt;" in out
    assert "y &amp; z" in out
    assert "<x>" not in out
