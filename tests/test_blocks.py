from p2c.blocks import Fence, extract_fences, protect_inline_code, restore

QUIZ = """Intro text.

```quiz
q: What?
- [x] This
```

Trailing text.
"""


def test_extract_fences_replaces_block_with_token():
    md, fences = extract_fences(QUIZ)
    assert len(fences) == 1
    assert fences[0].kind == "quiz"
    assert fences[0].body == "q: What?\n- [x] This"
    assert fences[0].token in md
    assert "```" not in md
    assert "Intro text." in md and "Trailing text." in md


def test_extract_fences_filters_by_kind():
    md = "```mermaid\ngraph TD\n```\n\n```python\nx = 1\n```\n"
    stripped, fences = extract_fences(md, kinds=("mermaid",))
    assert [f.kind for f in fences] == ["mermaid"]
    assert "```python" in stripped


def test_extract_fences_handles_multiple_and_numbers_tokens():
    md = "```quiz\na\n```\n\n```quiz\nb\n```\n"
    _, fences = extract_fences(md)
    assert [f.token for f in fences] == ["P2CBLOCK0ENDBLOCK", "P2CBLOCK1ENDBLOCK"]
    assert [f.body for f in fences] == ["a", "b"]


def test_extract_fences_keeps_blank_lines_inside_body():
    _, fences = extract_fences("```quiz\na\n\nb\n```\n")
    assert fences[0].body == "a\n\nb"


def test_adjacent_blocks_are_separated_by_blank_lines():
    md, fences = extract_fences("```quiz\na\n```\n```glossary\nT: d\n```\n")
    tokens = [f.token for f in fences]
    between = md.split(tokens[0])[1].split(tokens[1])[0]
    assert between.strip() == ""
    assert between.count("\n") >= 2


def test_extract_fences_leaves_unterminated_fence_alone():
    md = "```quiz\nq: never closed\n"
    stripped, fences = extract_fences(md)
    assert fences == []
    assert stripped == md


def test_extract_fences_accepts_bare_fence_as_empty_kind():
    _, fences = extract_fences("```\nplain\n```\n")
    assert fences[0].kind == ""


def test_protect_inline_code_and_restore_round_trip():
    md = "The `TLB` caches `mappings`."
    protected, mapping = protect_inline_code(md)
    assert "`" not in protected
    assert len(mapping) == 2
    assert restore(protected, mapping) == md


def test_restore_unwraps_paragraph_wrapped_tokens():
    html = "<p>P2CBLOCK0ENDBLOCK</p>\n<p>after</p>"
    assert restore(html, {"P2CBLOCK0ENDBLOCK": "<div>q</div>"}) == (
        "<div>q</div>\n<p>after</p>"
    )


def test_restore_is_a_noop_for_unknown_tokens():
    assert restore("<p>plain</p>", {}) == "<p>plain</p>"


def test_fence_is_a_dataclass_with_the_documented_fields():
    f = Fence(kind="quiz", body="b", token="t")
    assert (f.kind, f.body, f.token) == ("quiz", "b", "t")
