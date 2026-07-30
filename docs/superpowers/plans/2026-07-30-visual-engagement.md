# Visual Engagement Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give Presentation2Course three new tools for visual engagement — deterministic coverage enforcement, reuse of the deck's own slide images, and a small bounded animation-pattern library — as a follow-up to the just-completed multi-language feature on this same branch.

**Architecture:** Two new fenced block kinds (`figure`, `animate`) join the existing six (`quiz`, `mermaid`, `glossary`, `analogy`, `prereq`, `unverified`). `figure` is resolved to a real embedded image at build time from a page the summarizer flagged; `animate` renders directly from the writer's own block, no build-time resolution needed. A new deterministic build-time check (in `p2c.validate`, the same mechanism that already catches `topic_without_quiz`) fails the build if any topic has neither a visual nor an explicit justification comment.

**Tech Stack:** Python 3.12, `markdown`, new: `pypdfium2` (PDF page rasterization, pure pip install, no system tool) and `Pillow` (PNG encoding — `pypdfium2`'s own bitmap-to-image conversion needs it).

## Global Constraints

- Only the summarizer ever views slide pixels (unchanged). Researcher and course-writer work from outline text only, so `reusable_image` is a whole page, flagged by the summarizer, never cropped or picked by the writer.
- `reusable_image` outline field: `"<deck>#<page>"`, one per topic max, same shape as existing `slide_refs` entries (`^.+#\d+$`).
- `figure` block body carries only `source:`/`caption:` — the writer restates the exact `reusable_image` value it was handed, never re-derives it.
- `animate` block supports exactly two patterns: `step-reveal` (≥2 ordered stages) and `state-toggle` (`before:`/`after:`). No other pattern name is valid.
- All new CSS uses only logical properties (`margin-inline-start`, `inset-inline-start`, `text-align: start`, ...), never physical `left`/`right`/`margin-left` — this repo already has two grep-based tests (`test_layout_css_uses_logical_directional_properties_not_physical_ones`, `test_print_css_has_no_physical_directional_properties`) in `tests/test_assets.py` that scan the *whole* file; append new rules to the *existing* `assets/base/layout.css` and `assets/print.css` files (do not create a separate CSS file) so those tests cover the new rules automatically, with no new test needed for that property.
- All animation must respect `prefers-reduced-motion: reduce` (existing query at the end of `layout.css`) and render fully static (not a frozen mid-cycle frame) under `@media print`.
- A slide image or a slide's diagram that cannot be resolved at build time (missing deck, out-of-range page, corrupt PDF) is a hard build failure naming the offending topic id and source ref — never a silent fallback to no image. This matches the existing fail-fast style: `scripts/build`'s CLI wrapper already catches a fixed tuple of domain exceptions and maps them to exit 1.
- This work lands as more commits on the already-open `worktree-p2c-implementation` branch/PR, exactly like the multi-language feature before it.
- A note on one design-doc-to-plan correction: `docs/superpowers/specs/2026-07-30-visual-engagement-design.md` describes the coverage check as living in `p2c.invariants`. While reading the actual pipeline to write this plan, it turned out `p2c.invariants` is a standalone grading tool `SKILL.md` never invokes during a real run (confirmed: no `invariants` reference anywhere in `SKILL.md`) — a check placed only there would never actually gate course generation. The check therefore lives in `p2c.validate.validate_course()` instead (Task 5), the same function that already produces `topic_without_quiz` and routes it back to the responsible writer during Phase 4/5. `p2c.invariants.check_course()` already calls `blocking(validate_course(...))` and folds its findings into `problems`, so it inherits the new check for free — no invariants.py code change is needed at all. This is an implementation-detail correction, not a scope or decision change; every Decision in the design doc still holds.

---

### Task 1: `reusable_image` outline field

**Files:**
- Modify: `references/outline-schema.json`
- Modify: `scripts/p2c/outline.py`
- Test: `tests/test_outline.py`

**Interfaces:**
- Produces: `outline.json` topics may carry an optional `reusable_image: str` matching `^.+#\d+$` (same shape as `slide_refs` entries). Validated by `validate_outline()`; invalid shape is a problem string, same convention as every other check in that function.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_outline.py` (find the existing `outline()` test-fixture helper near the top of the file and the tests near the `slide_refs` validation tests; add these new tests alongside them):

```python
def test_reusable_image_is_optional():
    obj = outline()
    assert "reusable_image" not in obj["modules"][0]["topics"][0]
    assert validate_outline(obj) == []


def test_reusable_image_accepts_a_valid_slide_ref():
    obj = outline()
    obj["modules"][0]["topics"][0]["reusable_image"] = "week1.pdf#12"
    assert validate_outline(obj) == []


def test_reusable_image_rejects_a_malformed_ref():
    obj = outline()
    obj["modules"][0]["topics"][0]["reusable_image"] = "week1.pdf"
    problems = validate_outline(obj)
    assert any("reusable_image" in p for p in problems)
```

(If the existing `outline()` helper builds its dict inline per-test rather than as a shared fixture, adapt these three tests to whatever construction pattern the file already uses for a minimal valid outline — the assertions above are what matters.)

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd .venv-or-project-root && PYTHONPATH=scripts pytest tests/test_outline.py -k reusable_image -v`
Expected: FAIL — `reusable_image` accepted today with no validation either way is fine for the "optional" test, but the "rejects a malformed ref" test fails because nothing currently checks the field at all, so `validate_outline` returns `[]` instead of a non-empty list.

- [ ] **Step 3: Implement the validation**

In `scripts/p2c/outline.py`, the existing `_SLIDE_REF = re.compile(r"^.+#\d+$")` already matches the shape `reusable_image` needs — reuse it rather than adding a second identical regex. Add the check inside the per-topic loop in `validate_outline`, right after the existing `slide_refs` check block:

```python
            refs = topic.get("slide_refs")
            if isinstance(refs, list):
                for ref in refs:
                    if isinstance(ref, str) and not _SLIDE_REF.match(ref):
                        problems.append(
                            f"{twhere}.slide_refs entry {ref!r} must look like 'deck.pdf#12'"
                        )
            if "reusable_image" in topic:
                image_ref = topic["reusable_image"]
                if not isinstance(image_ref, str) or not _SLIDE_REF.match(image_ref):
                    problems.append(
                        f"{twhere}.reusable_image must look like 'deck.pdf#12', "
                        f"got {image_ref!r}"
                    )
```

`reusable_image` is deliberately **not** added to `REQUIRED_TOPIC` — it stays optional, only checked when present.

In `references/outline-schema.json`, find the topic object's `"properties"` block (it has `id`, `title`, `slide_refs`, `jargon`, `diagrams`, `gaps`) and add a new optional property (do not add it to that object's `"required"` array):

```json
        "reusable_image": {
          "type": "string",
          "pattern": "^.+#[0-9]+$",
          "description": "Optional. Set only when a slide's own diagram or photo is worth reusing verbatim instead of being redrawn. At most one per topic."
        },
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `PYTHONPATH=scripts pytest tests/test_outline.py -v`
Expected: PASS, all tests including the three new ones.

- [ ] **Step 5: Commit**

```bash
git add references/outline-schema.json scripts/p2c/outline.py tests/test_outline.py
git commit -m "feat: add optional reusable_image outline field for slide-image reuse"
```

---

### Task 2: `p2c.imagery` — whole-page PDF-to-PNG extraction

**Files:**
- Create: `scripts/p2c/imagery.py`
- Test: `tests/test_imagery.py`
- Modify: `requirements.txt`

**Interfaces:**
- Produces: `extract_page_png(pdf_path: Path, page_number: int, dpi: int = 96) -> bytes` — `page_number` is 1-based, matching `slide_refs`/`reusable_image`'s convention. Raises `ImageryError` (importable as `p2c.imagery.ImageryError`) on a missing file, an out-of-range page, or a corrupt/unreadable PDF.
- Consumes: `tests/fixtures/terse.pdf`, the existing 3-page fixture already checked into this repo (used by `test_normalize.py`) — a real, valid, minimal PDF, unlike the synthetic byte-strings `tests/fixtures/make_fixtures.py`'s `make_pdf()` produces for regex-level tests. It's exactly what's needed here since `pypdfium2` actually rasterizes it.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_imagery.py`:

```python
from pathlib import Path

import pytest

from p2c.imagery import ImageryError, extract_page_png

FIXTURES = Path(__file__).parent / "fixtures"
TERSE = FIXTURES / "terse.pdf"


def test_extracts_a_valid_page_as_png_bytes():
    png = extract_page_png(TERSE, 1)
    assert png.startswith(b"\x89PNG\r\n\x1a\n")


def test_extracts_a_later_page_too():
    png = extract_page_png(TERSE, 3)
    assert png.startswith(b"\x89PNG\r\n\x1a\n")


def test_rejects_an_out_of_range_page():
    with pytest.raises(ImageryError, match=r"page 5 out of range \(1-3\)"):
        extract_page_png(TERSE, 5)


def test_rejects_page_zero():
    with pytest.raises(ImageryError, match=r"out of range"):
        extract_page_png(TERSE, 0)


def test_rejects_a_missing_file(tmp_path):
    with pytest.raises(ImageryError, match="no such file"):
        extract_page_png(tmp_path / "missing.pdf", 1)


def test_rejects_a_corrupt_pdf(tmp_path):
    bad = tmp_path / "broken.pdf"
    bad.write_bytes(b"not really a pdf")
    with pytest.raises(ImageryError, match="not a readable PDF"):
        extract_page_png(bad, 1)


def test_higher_dpi_produces_a_larger_image():
    small = extract_page_png(TERSE, 1, dpi=72)
    large = extract_page_png(TERSE, 1, dpi=200)
    assert len(large) > len(small)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `PYTHONPATH=scripts pytest tests/test_imagery.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'p2c.imagery'`.

- [ ] **Step 3: Add the dependencies**

Add to `requirements.txt` (currently just `markdown>=3.5`):

```
markdown>=3.5
pypdfium2>=4
Pillow>=10
```

Install them: `python3 -m pip install --user -r requirements.txt` (or into the project's `.venv` if one is active — match whatever the existing dev setup uses).

- [ ] **Step 4: Write the implementation**

Create `scripts/p2c/imagery.py`:

```python
"""Whole-page PDF-to-PNG extraction for reused slide images.

Whole pages, not agent-cropped regions: the only agent that ever views slide
pixels is the summarizer, and asking it to name a precise bounding box for a
page it may not even be the one rendering later would be an unverifiable
guess. Extraction happens here, at build time, from a page ref an agent only
ever *names* (``deck.pdf#12``).

pypdfium2 because it is a pure pip install with its own bundled binary -- no
system poppler or headless Chromium required for a feature meant to work by
default.
"""

import io
from pathlib import Path

import pypdfium2 as pdfium


class ImageryError(Exception):
    """A page could not be extracted from the given PDF."""


def extract_page_png(pdf_path: Path, page_number: int, dpi: int = 96) -> bytes:
    """page_number is 1-based, matching outline.json's slide_refs convention."""
    pdf_path = Path(pdf_path)
    if not pdf_path.is_file():
        raise ImageryError(f"{pdf_path}: no such file")

    try:
        pdf = pdfium.PdfDocument(str(pdf_path))
    except Exception as exc:
        raise ImageryError(f"{pdf_path}: not a readable PDF ({exc})") from exc

    try:
        page_count = len(pdf)
        if not 1 <= page_number <= page_count:
            raise ImageryError(
                f"{pdf_path}: page {page_number} out of range (1-{page_count})"
            )
        try:
            page = pdf[page_number - 1]
            bitmap = page.render(scale=dpi / 72)
            pil_image = bitmap.to_pil()
        except Exception as exc:
            raise ImageryError(
                f"{pdf_path}: page {page_number} could not be rendered ({exc})"
            ) from exc
        buf = io.BytesIO()
        pil_image.save(buf, format="PNG")
        return buf.getvalue()
    finally:
        pdf.close()
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `PYTHONPATH=scripts pytest tests/test_imagery.py -v`
Expected: PASS, all 7 tests.

- [ ] **Step 6: Commit**

```bash
git add scripts/p2c/imagery.py tests/test_imagery.py requirements.txt
git commit -m "feat: add p2c.imagery for whole-page PDF-to-PNG extraction"
```

---

### Task 3: `figure` fence block — parse, render, resolve

**Files:**
- Modify: `scripts/p2c/mdrender.py`
- Modify: `scripts/p2c/build.py`
- Modify: `scripts/build` (CLI wrapper)
- Modify: `references/agents/course-writer.md`
- Modify: `references/quiz-format.md`
- Test: `tests/test_mdrender.py`
- Test: `tests/test_build.py`
- Test: `tests/test_references.py` (an existing test there breaks otherwise — see Step 10)

**Interfaces:**
- Consumes: `p2c.imagery.extract_page_png(pdf_path, page_number) -> bytes`, `p2c.imagery.ImageryError` (Task 2).
- Produces: `mdrender.HANDLED_KINDS` gains `"figure"`; `mdrender.FigureError(ValueError)`; `mdrender.parse_figure(body: str) -> tuple[str, str]` (source, caption); a `figure` fence renders to `<figure class="figure" data-p2c-image-pending="...">` with the image `src` left unset, for `build.py` to resolve. `build.build()`'s public signature and `BuildResult` shape are unchanged — resolution happens internally between rendering and writing `course.html`.

- [ ] **Step 1: Write the failing mdrender tests**

Add to `tests/test_mdrender.py` (near the existing callout/mermaid tests):

```python
from p2c.mdrender import FigureError, parse_figure


def test_parse_figure_extracts_source_and_caption():
    source, caption = parse_figure("source: week1.pdf#12\ncaption: The TLB lookup path.")
    assert source == "week1.pdf#12"
    assert caption == "The TLB lookup path."


def test_parse_figure_rejects_a_missing_source():
    with pytest.raises(FigureError, match="missing a 'source:'"):
        parse_figure("caption: Only a caption.")


def test_parse_figure_rejects_a_missing_caption():
    with pytest.raises(FigureError, match="missing a 'caption:'"):
        parse_figure("source: week1.pdf#12")


def test_parse_figure_rejects_a_malformed_source_ref():
    with pytest.raises(FigureError, match="must look like 'deck.pdf#12'"):
        parse_figure("source: week1.pdf\ncaption: Missing the page number.")


def test_figure_block_renders_a_pending_placeholder():
    md = course(
        '<!-- topic: tlb -->\n### The TLB\n\n'
        '```figure\nsource: week1.pdf#12\ncaption: The lookup path.\n```\n\n'
        '```quiz\nq: q\n- [ ] a\n- [x] b\n- [ ] c\nwhy: because\n```\n\n'
        '```glossary\nTLB: definition\n```\n'
    )
    rendered = render_course(md)
    assert rendered.errors == []
    assert 'data-p2c-image-pending="week1.pdf#12"' in rendered.html_body
    assert 'data-p2c-topic="tlb"' in rendered.html_body
    assert '<figcaption>The lookup path.</figcaption>' in rendered.html_body
    assert '<img alt="The lookup path.">' in rendered.html_body


def test_a_broken_figure_block_becomes_an_error_not_a_crash():
    md = course(
        '<!-- topic: tlb -->\n### The TLB\n\n'
        '```figure\ncaption: No source at all.\n```\n\n'
        '```quiz\nq: q\n- [ ] a\n- [x] b\n- [ ] c\nwhy: because\n```\n\n'
        '```glossary\nTLB: definition\n```\n'
    )
    rendered = render_course(md)
    assert any("figure" in e for e in rendered.errors)
```

(`course()` and the `MODULE`/front-matter helpers already exist at the top of `tests/test_mdrender.py` — reuse them exactly as the existing mermaid/callout tests do, per the file's own convention.)

- [ ] **Step 2: Run tests to verify they fail**

Run: `PYTHONPATH=scripts pytest tests/test_mdrender.py -k figure -v`
Expected: FAIL — `ImportError: cannot import name 'FigureError'`.

- [ ] **Step 3: Implement figure parsing and rendering in mdrender.py**

Add `"figure"` to `HANDLED_KINDS`:

```python
HANDLED_KINDS = ("quiz", "mermaid", "glossary", "analogy", "prereq", "unverified", "figure", "animate")
```

(Adding `"animate"` here too, ahead of Task 4, is harmless — an unhandled kind string in `HANDLED_KINDS` with no matching `elif` branch would currently fall through to the generic `_callout_html` branch and crash on an unknown `CALLOUT_LABELS` key. To avoid that intermediate broken state, add `"animate"` to `HANDLED_KINDS` only in Task 4 together with its own branch. For this task, add only `"figure"`:)

```python
HANDLED_KINDS = ("quiz", "mermaid", "glossary", "analogy", "prereq", "unverified", "figure")
```

Add near the top of the file, after the existing `MERMAID_KEYWORDS`/`CALLOUT_LABELS` constants:

```python
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
```

In `render_course`'s fence-processing loop, add a new branch (alongside the existing `elif fence.kind == "glossary":` branch — order doesn't matter, but put it right after that one for readability):

```python
        elif fence.kind == "figure":
            try:
                source, caption = parse_figure(fence.body)
            except FigureError as exc:
                errors.append(f"{anchor}: figure {exc}")
                replacements[fence.token] = ""
                continue
            replacements[fence.token] = _figure_html(source, caption, topic_id)
```

- [ ] **Step 4: Run mdrender tests to verify they pass**

Run: `PYTHONPATH=scripts pytest tests/test_mdrender.py -k figure -v`
Expected: PASS, all 6 new tests.

- [ ] **Step 5: Write the failing build test**

Add to `tests/test_build.py`, near the other mermaid/figure-adjacent tests:

```python
def test_a_figure_block_resolves_to_an_embedded_base64_image(tmp_path):
    modules = tmp_path / "modules"
    modules.mkdir()
    for name in ("01-virtual-memory.md", "02-scheduling.md"):
        modules.joinpath(name).write_text((MINI / "modules" / name).read_text())
    with modules.joinpath("01-virtual-memory.md").open("a") as handle:
        handle.write(
            "\n```figure\nsource: terse.pdf#1\ncaption: The original slide.\n```\n"
        )
    out = tmp_path / "out"
    normalized = out / ".p2c" / "normalized"
    normalized.mkdir(parents=True)
    (normalized / "terse.pdf").write_bytes(
        (REPO / "tests" / "fixtures" / "terse.pdf").read_bytes()
    )
    result = build(MINI / "outline.json", modules, out, ASSETS)
    html = result.course_html.read_text()
    assert "data-p2c-image-pending" not in html
    assert 'src="data:image/png;base64,' in html
    assert [f.code for f in result.findings] == []


def test_an_unresolvable_figure_source_fails_the_build_naming_topic_and_source(tmp_path):
    modules = tmp_path / "modules"
    modules.mkdir()
    for name in ("01-virtual-memory.md", "02-scheduling.md"):
        modules.joinpath(name).write_text((MINI / "modules" / name).read_text())
    with modules.joinpath("01-virtual-memory.md").open("a") as handle:
        handle.write(
            "\n```figure\nsource: terse.pdf#99\ncaption: Out of range.\n```\n"
        )
    out = tmp_path / "out"
    normalized = out / ".p2c" / "normalized"
    normalized.mkdir(parents=True)
    (normalized / "terse.pdf").write_bytes(
        (REPO / "tests" / "fixtures" / "terse.pdf").read_bytes()
    )
    with pytest.raises(ImageryError, match=r"topic 'tlb'.*terse\.pdf#99"):
        build(MINI / "outline.json", modules, out, ASSETS)
```

Add the import at the top of `tests/test_build.py`:

```python
from p2c.imagery import ImageryError
```

- [ ] **Step 6: Run the build tests to verify they fail**

Run: `PYTHONPATH=scripts pytest tests/test_build.py -k figure -v`
Expected: FAIL — the `figure` block currently renders but the `data-p2c-image-pending` placeholder is never resolved, so `src="data:image/png;base64,` is never present, and no `ImageryError` is ever raised.

- [ ] **Step 7: Implement resolution in build.py**

At the top of `scripts/p2c/build.py`, add imports:

```python
import base64
import re
```

(`re` is already imported — do not duplicate the import line, just note it's already there.)

```python
from p2c.imagery import ImageryError, extract_page_png
```

Add near the other module-level constants (after `_PLACEHOLDER_RE`):

```python
_FIGURE_PENDING = re.compile(
    r'<figure class="figure" data-p2c-image-pending="(?P<source>[^"]*)" '
    r'data-p2c-topic="(?P<topic>[^"]*)"><img alt="(?P<alt>[^"]*)">'
)


def _resolve_figures(html_text: str, out_dir: Path) -> str:
    def replace(match: re.Match) -> str:
        source = html.unescape(match.group("source"))
        topic = html.unescape(match.group("topic")) or None
        deck, _, page_str = source.rpartition("#")
        pdf_path = out_dir / ".p2c" / "normalized" / deck
        try:
            png_bytes = extract_page_png(pdf_path, int(page_str))
        except (ImageryError, ValueError) as exc:
            where = f"topic {topic!r}: " if topic else ""
            raise ImageryError(
                f"{where}figure source {source!r} could not be resolved: {exc}"
            ) from exc
        b64 = base64.b64encode(png_bytes).decode("ascii")
        return (
            f'<figure class="figure" data-p2c-image-pending="{match.group("source")}" '
            f'data-p2c-topic="{match.group("topic")}">'
            f'<img alt="{match.group("alt")}" src="data:image/png;base64,{b64}">'
        )

    return _FIGURE_PENDING.sub(replace, html_text)
```

In `build()`, both places that currently do:

```python
    html_text = fill_template(
        loaded,
        rendered,
        title=outline["title"],
        source_decks=rendered.front_matter.source_decks,
        inline_mermaid=rendered.uses_mermaid,
        language=outline["language"],
    )
    course_html = out_dir / "course.html"
    course_html.write_text(html_text, encoding="utf-8")
```

becomes:

```python
    html_text = _resolve_figures(
        fill_template(
            loaded,
            rendered,
            title=outline["title"],
            source_decks=rendered.front_matter.source_decks,
            inline_mermaid=rendered.uses_mermaid,
            language=outline["language"],
        ),
        out_dir,
    )
    course_html = out_dir / "course.html"
    course_html.write_text(html_text, encoding="utf-8")
```

and the second call (the `validation_html` one, used only for `validate_course`) becomes:

```python
    validation_html = _resolve_figures(
        fill_template(
            loaded,
            rendered,
            title=outline["title"],
            source_decks=rendered.front_matter.source_decks,
            inline_mermaid=False,
            language=outline["language"],
        ),
        out_dir,
    )
```

- [ ] **Step 8: Wire the exception into the CLI wrapper**

In `scripts/build`, add the import and extend the caught tuple:

```python
from p2c.imagery import ImageryError  # noqa: E402
```

```python
    except (AssembleError, OutlineError, ThemeError, ImageryError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)
```

- [ ] **Step 9: Run the build tests to verify they pass**

Run: `PYTHONPATH=scripts pytest tests/test_build.py -k figure -v`
Expected: PASS, both new tests.

Run the full existing build suite too, since this touches a function every other `test_build.py` test depends on: `PYTHONPATH=scripts pytest tests/test_build.py -v`
Expected: PASS, no regressions (no other existing fixture uses a `figure` block, so `_resolve_figures` is a no-op on their HTML).

- [ ] **Step 10: Document `figure` minimally now — required, not optional, for this task**

`tests/test_references.py` already has `test_course_writer_prompt_states_every_mechanical_requirement`, which loops over every entry in `mdrender.HANDLED_KINDS` (excluding `"prereq"`) and asserts it appears as a substring in `references/agents/course-writer.md`. Since this task adds `"figure"` to `HANDLED_KINDS`, that existing test now fails unless `course-writer.md` mentions `figure` too — run `PYTHONPATH=scripts pytest tests/test_references.py -v` right now to see it fail before making this fix.

Add this section to `references/agents/course-writer.md`, right after the existing "Mechanical requirements" list:

```markdown
## Visual per topic

Every topic needs one of: a `mermaid` diagram, an inline `<svg>`, or a
`figure` block. If your dispatch tells you a topic already has a
`reusable_image` (a real slide image the summarizer flagged as worth
reusing), do not author your own visual for that topic — write a `figure`
block instead, restating the exact value you were given:

```figure
source: week1.pdf#12
caption: The lookup path, as drawn in the lecture.
```

Write only the caption yourself; the `source:` value must be copied exactly
from your dispatch, never invented or re-derived. See
`references/quiz-format.md` for the full grammar.
```

(Task 4 extends this same section with `animate` and the `no-visual` escape
hatch — do not duplicate that content now, just get `figure` documented so
the existing test passes again.)

Add a `## \`figure\`` section to `references/quiz-format.md`, right after the
existing `## \`mermaid\` — a diagram` section:

````markdown
## `figure` — a reused slide image

````
```figure
source: week1.pdf#12
caption: The lookup path, as drawn in the lecture.
```
````

Exactly one `source:` (a `deck.pdf#page` ref, copied verbatim from the value
the orchestrator gave you when a topic has a `reusable_image`) and one
`caption:`, which may wrap onto indented continuation lines. The build
resolves `source:` to the real slide image at the referenced page — the
writer never supplies image bytes, only these two lines. An unresolvable
source (missing deck, out-of-range page) is a hard build failure naming the
topic and the source.
````

Run `PYTHONPATH=scripts pytest tests/test_references.py -v` again to confirm it passes now.

- [ ] **Step 11: Commit**

```bash
git add scripts/p2c/mdrender.py scripts/p2c/build.py scripts/build tests/test_mdrender.py tests/test_build.py references/agents/course-writer.md references/quiz-format.md
git commit -m "feat: add figure block, resolved to an embedded slide image at build time"
```

---

### Task 4: `animate` fence block — step-reveal and state-toggle

**Files:**
- Modify: `scripts/p2c/mdrender.py`
- Modify: `assets/base/layout.css`
- Modify: `assets/print.css`
- Modify: `references/agents/course-writer.md`
- Modify: `references/quiz-format.md`
- Test: `tests/test_mdrender.py`
- Test: `tests/test_build.py`
- Test: `tests/test_references.py` (an existing test there breaks otherwise — see Step 9)

**Interfaces:**
- Produces: `mdrender.HANDLED_KINDS` gains `"animate"`; `mdrender.AnimateError(ValueError)`; `mdrender.parse_animate(body: str) -> Animate` where `Animate` is a new dataclass with fields `pattern: str`, `steps: list[str]`, `before: str`, `after: str`. An `animate` fence renders fully inline (no build-time resolution, unlike `figure`).

- [ ] **Step 1: Write the failing mdrender tests**

Add to `tests/test_mdrender.py`:

```python
from p2c.mdrender import Animate, AnimateError, parse_animate


def test_parse_animate_step_reveal():
    anim = parse_animate(
        "pattern: step-reveal\nsteps:\n  - Request arrives\n  - TLB miss\n  - Entry cached"
    )
    assert anim == Animate(
        pattern="step-reveal",
        steps=["Request arrives", "TLB miss", "Entry cached"],
    )


def test_parse_animate_state_toggle():
    anim = parse_animate(
        "pattern: state-toggle\nbefore: Marked Shared\nafter: Marked Modified"
    )
    assert anim == Animate(pattern="state-toggle", before="Marked Shared", after="Marked Modified")


def test_parse_animate_rejects_an_unknown_pattern():
    with pytest.raises(AnimateError, match="must be 'step-reveal' or 'state-toggle'"):
        parse_animate("pattern: spin\nsteps:\n  - a\n  - b")


def test_parse_animate_rejects_a_step_reveal_with_one_step():
    with pytest.raises(AnimateError, match="at least 2 steps"):
        parse_animate("pattern: step-reveal\nsteps:\n  - only one")


def test_parse_animate_rejects_a_state_toggle_missing_after():
    with pytest.raises(AnimateError, match="needs both 'before:' and 'after:'"):
        parse_animate("pattern: state-toggle\nbefore: only before")


def test_step_reveal_renders_with_staggered_negative_delays():
    md = course(
        '<!-- topic: tlb -->\n### The TLB\n\n'
        '```animate\npattern: step-reveal\nsteps:\n  - First\n  - Second\n  - Third\n```\n\n'
        '```quiz\nq: q\n- [ ] a\n- [x] b\n- [ ] c\nwhy: because\n```\n\n'
        '```glossary\nTLB: definition\n```\n'
    )
    rendered = render_course(md)
    assert rendered.errors == []
    assert 'animation-duration: 6s; animation-delay: 0s">First</li>' in rendered.html_body
    assert 'animation-duration: 6s; animation-delay: -2s">Second</li>' in rendered.html_body
    assert 'animation-duration: 6s; animation-delay: -4s">Third</li>' in rendered.html_body


def test_state_toggle_renders_before_and_after():
    md = course(
        '<!-- topic: tlb -->\n### The TLB\n\n'
        '```animate\npattern: state-toggle\nbefore: Shared\nafter: Modified\n```\n\n'
        '```quiz\nq: q\n- [ ] a\n- [x] b\n- [ ] c\nwhy: because\n```\n\n'
        '```glossary\nTLB: definition\n```\n'
    )
    rendered = render_course(md)
    assert rendered.errors == []
    assert '<div class="anim__state anim__state--before">Shared</div>' in rendered.html_body
    assert '<div class="anim__state anim__state--after">Modified</div>' in rendered.html_body


def test_a_broken_animate_block_becomes_an_error_not_a_crash():
    md = course(
        '<!-- topic: tlb -->\n### The TLB\n\n'
        '```animate\npattern: nonsense\n```\n\n'
        '```quiz\nq: q\n- [ ] a\n- [x] b\n- [ ] c\nwhy: because\n```\n\n'
        '```glossary\nTLB: definition\n```\n'
    )
    rendered = render_course(md)
    assert any("animate" in e for e in rendered.errors)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `PYTHONPATH=scripts pytest tests/test_mdrender.py -k animate -v`
Expected: FAIL — `ImportError: cannot import name 'Animate'`.

- [ ] **Step 3: Implement animate parsing and rendering in mdrender.py**

Update `HANDLED_KINDS` (from Task 3's `"figure"`-only version):

```python
HANDLED_KINDS = ("quiz", "mermaid", "glossary", "analogy", "prereq", "unverified", "figure", "animate")
```

Add near the `_FIGURE_KEY`/`FigureError` block:

```python
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
```

In `render_course`'s fence-processing loop, add a branch alongside the `figure` one from Task 3:

```python
        elif fence.kind == "animate":
            try:
                anim = parse_animate(fence.body)
            except AnimateError as exc:
                errors.append(f"{anchor}: animate {exc}")
                replacements[fence.token] = ""
                continue
            replacements[fence.token] = _animate_html(anim)
```

- [ ] **Step 4: Run mdrender tests to verify they pass**

Run: `PYTHONPATH=scripts pytest tests/test_mdrender.py -k animate -v`
Expected: PASS, all 7 new tests.

- [ ] **Step 5: Add the CSS**

In `assets/base/layout.css`, add this block right before the existing final line (`@media (prefers-reduced-motion: reduce) { html { scroll-behavior: auto; } }`):

```css
.figure { margin: var(--space-6) 0; text-align: center; }
.figure img { max-width: 100%; height: auto; border-radius: var(--radius); }
.figure figcaption { margin-block-start: var(--space-2); color: var(--color-muted); font-size: 0.9rem; }

.anim { margin: var(--space-6) 0; }
.anim__steps {
  list-style: decimal; padding-inline-start: var(--space-6); margin: 0;
  display: grid; gap: var(--space-2);
}
.anim__step {
  opacity: 0.35; font-weight: 400;
  animation-name: anim-step-pulse; animation-timing-function: ease-in-out;
  animation-iteration-count: infinite;
}
@keyframes anim-step-pulse {
  0%   { opacity: 1;    font-weight: 600; }
  15%  { opacity: 1;    font-weight: 600; }
  25%  { opacity: 0.35; font-weight: 400; }
  100% { opacity: 0.35; font-weight: 400; }
}
.anim--state-toggle { position: relative; min-block-size: 3em; }
.anim__state {
  position: absolute; inset-block-start: 0; inset-inline-start: 0;
  animation-name: anim-state-crossfade; animation-duration: 4s;
  animation-timing-function: ease-in-out; animation-iteration-count: infinite;
}
.anim__state--before { animation-delay: 0s; }
.anim__state--after { animation-delay: -2s; }
@keyframes anim-state-crossfade {
  0%   { opacity: 1; }
  45%  { opacity: 1; }
  55%  { opacity: 0; }
  100% { opacity: 0; }
}
```

Then replace the existing final line with the same rule extended:

```css
@media (prefers-reduced-motion: reduce) {
  html { scroll-behavior: auto; }
  .anim__step, .anim__state {
    animation: none; opacity: 1; font-weight: 400; position: static;
  }
}
```

In `assets/print.css`, add inside the existing `@media print { ... }` block (add these lines right before the closing `}` of that block, alongside the existing `.quiz, .callout, .mermaid, table, pre { break-inside: avoid; ... }` line):

```css
  .figure, .anim { break-inside: avoid; page-break-inside: avoid; }
  .anim__step, .anim__state { animation: none !important; opacity: 1 !important; }
  .anim__step { font-weight: 400 !important; }
  .anim--state-toggle { display: grid !important; gap: 0.5em; }
  .anim__state { position: static !important; }
```

- [ ] **Step 6: Run the CSS regression tests**

Run: `PYTHONPATH=scripts pytest tests/test_assets.py -v`
Expected: PASS — `test_layout_css_uses_logical_directional_properties_not_physical_ones`, `test_layout_css_has_no_four_value_margin_or_padding_shorthand`, and `test_print_css_has_no_physical_directional_properties` all still pass, now also covering the new rules (no new test needed here per the Global Constraints note).

- [ ] **Step 7: Add a golden-adjacent build test locking in both patterns render inside a real build**

Add to `tests/test_build.py`:

```python
def test_animate_blocks_render_inside_a_built_course(tmp_path):
    modules = tmp_path / "modules"
    modules.mkdir()
    for name in ("01-virtual-memory.md", "02-scheduling.md"):
        modules.joinpath(name).write_text((MINI / "modules" / name).read_text())
    with modules.joinpath("02-scheduling.md").open("a") as handle:
        handle.write(
            "\n```animate\npattern: state-toggle\nbefore: Ready\nafter: Running\n```\n"
        )
    result = build(MINI / "outline.json", modules, tmp_path / "out", ASSETS)
    html = result.course_html.read_text()
    assert '<div class="anim__state anim__state--before">Ready</div>' in html
    assert [f.code for f in result.findings] == []
```

- [ ] **Step 8: Run it, and the full build suite, to verify no regressions**

Run: `PYTHONPATH=scripts pytest tests/test_build.py tests/test_assets.py -v`
Expected: PASS.

- [ ] **Step 9: Document `animate` minimally now, and the `no-visual` escape hatch — same reason as Task 3's `figure` documentation step**

This task adds `"animate"` to `HANDLED_KINDS`, so `test_course_writer_prompt_states_every_mechanical_requirement` (in `tests/test_references.py`) now also requires `animate` to appear in `course-writer.md`. Run `PYTHONPATH=scripts pytest tests/test_references.py -v` first to see it fail.

Task 5 (next) introduces the `<!-- no-visual: ... -->` comment as the enforcement mechanism's escape hatch — document it here too, since it belongs in the same "Visual per topic" section this task is extending, and Task 5 has no reason to touch `course-writer.md` on its own otherwise.

Replace the "Visual per topic" section Task 3 added in `course-writer.md` with this expanded version (same heading, more content — do not create a second "Visual per topic" heading):

```markdown
## Visual per topic

Every topic needs one of: a `mermaid` diagram, an inline `<svg>`, a `figure`
block, or an `animate` block. The build fails otherwise, unless you also
write an explicit `<!-- no-visual: <reason> -->` HTML comment for a topic
that is genuinely non-spatial — use that sparingly; it is an escape hatch,
not a way to skip the visual step because a diagram is inconvenient to write.

Pick the diagram type that matches the idea: `flowchart` for a process,
`sequenceDiagram` for an interaction between parties, `stateDiagram-v2` for a
lifecycle, `erDiagram`/`architecture-beta` for structure. Inline `<svg>` is
for a static structure a flow/sequence/state diagram cannot express (a memory
layout, a data structure). A second visual in one topic is rarely warranted —
only add one if the topic genuinely covers two separate spatial ideas.

If your dispatch tells you a topic already has a `reusable_image` (a real
slide image the summarizer flagged as worth reusing), do not author your own
visual for that topic at all — write a `figure` block instead, restating the
exact value you were given:

```figure
source: week1.pdf#12
caption: The lookup path, as drawn in the lecture.
```

Write only the caption yourself; the source value must be copied exactly
from your dispatch, never invented or re-derived.

When a topic is genuinely about a sequence or a before/after comparison, an
`animate` block is worth using instead of (or alongside) a mermaid diagram:

```animate
pattern: step-reveal
steps:
  - Request arrives at the TLB
  - TLB miss triggers a page-table walk
  - Page table entry is cached back into the TLB
```

```animate
pattern: state-toggle
before: Cache line marked Shared
after: Cache line marked Modified after a local write
```

`step-reveal` needs at least 2 steps; `state-toggle` needs both `before:` and
`after:`. See `references/quiz-format.md` for the full grammar.
```

Add a `## \`animate\`` section to `references/quiz-format.md`, right after the `## \`figure\`` section Task 3 added, and update the file's opening line from "Six fenced block kinds are meaningful to the build." to "Eight fenced block kinds are meaningful to the build.":

````markdown
## `animate` — a bounded animation pattern

````
```animate
pattern: step-reveal
steps:
  - Request arrives at the TLB
  - TLB miss triggers a page-table walk
  - Page table entry is cached back into the TLB
```
````

````
```animate
pattern: state-toggle
before: Cache line marked Shared
after: Cache line marked Modified after a local write
```
````

Exactly two patterns exist:

- `step-reveal` — `steps:` followed by 2 or more `- ` lines, highlighted in
  turn via a looping CSS animation. Use for an ordered sequence.
- `state-toggle` — `before:` and `after:`, both required, cross-fading via a
  looping CSS animation. Use for a two-state comparison.

Both respect `prefers-reduced-motion` and render fully static (every
step/state shown at once, not a single frozen frame) in print.
````

Run `PYTHONPATH=scripts pytest tests/test_references.py -v` again to confirm it passes.

- [ ] **Step 10: Commit**

```bash
git add scripts/p2c/mdrender.py assets/base/layout.css assets/print.css tests/test_mdrender.py tests/test_build.py references/agents/course-writer.md references/quiz-format.md
git commit -m "feat: add animate block (step-reveal, state-toggle), print- and reduced-motion-safe"
```

---

### Task 5: Deterministic visual-coverage enforcement

**Files:**
- Modify: `scripts/p2c/mdrender.py`
- Modify: `scripts/p2c/validate.py`
- Modify: `tests/test_validate.py` (already exists — do not create a new file)
- Test: `tests/test_mdrender.py`

**Interfaces:**
- Consumes: `mdrender.HANDLED_KINDS` including `"figure"`/`"animate"` (Tasks 3-4).
- Produces: `Rendered` gains `topics_missing_visual: list[str]` (topic ids, in outline order, with neither a qualifying visual nor a `<!-- no-visual: ... -->` justification). `p2c.validate.validate_course()` gains a new `Finding` code `topic_without_visual`, routed `"writer"`, for every entry in that list. `p2c.invariants.check_course()` needs **no code change** — it already calls `blocking(validate_course(...))` and folds the results in.

- [ ] **Step 1: Write the failing mdrender test**

First, check whether `tests/test_validate.py` exists (`ls tests/test_validate.py`) — if it does, add the validate.py-level tests there instead of inventing a new file; the exact location matters less than not duplicating an existing test module.

Add to `tests/test_mdrender.py`:

```python
def test_a_topic_with_a_mermaid_diagram_is_not_missing_a_visual():
    rendered = render_course(course(MODULE))  # MODULE already has a mermaid block for 'tlb'
    assert "tlb" not in rendered.topics_missing_visual


def test_a_topic_with_no_visual_and_no_justification_is_flagged():
    md = course(
        '<!-- topic: bare -->\n### Bare topic\n\nJust prose, no visual at all.\n\n'
        '```quiz\nq: q\n- [ ] a\n- [x] b\n- [ ] c\nwhy: because\n```\n'
    )
    rendered = render_course(md)
    assert rendered.topics_missing_visual == ["bare"]


def test_a_topic_with_an_inline_svg_is_not_missing_a_visual():
    md = course(
        '<!-- topic: bare -->\n### Bare topic\n\n<svg><circle r="1"/></svg>\n\n'
        '```quiz\nq: q\n- [ ] a\n- [x] b\n- [ ] c\nwhy: because\n```\n'
    )
    rendered = render_course(md)
    assert rendered.topics_missing_visual == []


def test_a_no_visual_comment_justifies_skipping_the_visual():
    md = course(
        '<!-- topic: bare -->\n### Bare topic\n\n'
        '<!-- no-visual: purely definitional, nothing spatial to draw -->\n\n'
        'Just prose.\n\n```quiz\nq: q\n- [ ] a\n- [x] b\n- [ ] c\nwhy: because\n```\n'
    )
    rendered = render_course(md)
    assert rendered.topics_missing_visual == []


def test_a_figure_or_animate_block_also_counts_as_a_visual():
    md = course(
        '<!-- topic: bare -->\n### Bare topic\n\n'
        '```figure\nsource: week1.pdf#1\ncaption: c\n```\n\n'
        '```quiz\nq: q\n- [ ] a\n- [x] b\n- [ ] c\nwhy: because\n```\n'
    )
    rendered = render_course(md)
    assert rendered.topics_missing_visual == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `PYTHONPATH=scripts pytest tests/test_mdrender.py -k missing_visual -v`
Expected: FAIL — `AttributeError: 'Rendered' object has no attribute 'topics_missing_visual'`.

- [ ] **Step 3: Implement the tracking in mdrender.py**

Add a regex near `_TOPIC_MARKER`/`_HEADING`:

```python
_NO_VISUAL = re.compile(r"^\s*<!--\s*no-visual:\s*.+-->\s*$")
_VISUAL_FENCE_KINDS = {"mermaid", "figure", "animate"}


def _note_visual(status: dict[str, str], topic_id: str | None, value: str) -> None:
    """'visual' always wins over 'justified', so a real visual is never
    downgraded by an incidental no-visual comment elsewhere in the same topic."""
    if not topic_id:
        return
    if value == "visual" or status.get(topic_id) != "visual":
        status[topic_id] = value
```

In `render_course`, initialize `topic_visual_status: dict[str, str] = {}` alongside the existing `anchors = AnchorAllocator()` / `sections: list[Section] = []` block.

In the per-line walk, right after the existing block:

```python
        if line.strip().startswith("P2CBLOCK"):
            token_owner[line.strip()] = current
        buffer.append(line)
```

add the new checks before `buffer.append(line)`:

```python
        if line.strip().startswith("P2CBLOCK"):
            token_owner[line.strip()] = current
        elif current[1]:
            if "<svg" in line:
                _note_visual(topic_visual_status, current[1], "visual")
            elif _NO_VISUAL.match(line):
                _note_visual(topic_visual_status, current[1], "justified")
        buffer.append(line)
```

In the fence-processing loop, right at the top of the `for fence in fences:` body (before the `if fence.kind == "quiz":` chain), add:

```python
    for fence in fences:
        anchor, topic_id = token_owner.get(fence.token, ("course", None))
        if fence.kind in _VISUAL_FENCE_KINDS:
            _note_visual(topic_visual_status, topic_id, "visual")
        if fence.kind == "quiz":
```

After the existing `for topic_id in (s.topic_id for s in sections if s.topic_id): quizzes_per_topic.setdefault(topic_id, 0)` loop, compute the final list:

```python
    topics_missing_visual = [
        tid for tid in dict.fromkeys(s.topic_id for s in sections if s.topic_id)
        if topic_visual_status.get(tid) not in ("visual", "justified")
    ]
```

Add the field to `Rendered` and pass it through the constructor call:

```python
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
    topics_missing_visual: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
```

```python
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
        topics_missing_visual=topics_missing_visual,
        errors=errors,
    )
```

- [ ] **Step 4: Run mdrender tests to verify they pass**

Run: `PYTHONPATH=scripts pytest tests/test_mdrender.py -v`
Expected: PASS, all tests (new and pre-existing — this touches a widely-used function, so run the whole file, not just `-k missing_visual`).

- [ ] **Step 5: Fix the existing `course()` test fixture, then write the failing test**

`tests/test_validate.py` already has exactly the fixture infrastructure this needs: a
`course(*, tlb_body=None, thrashing_body=None, glossary=...)` builder, a shared `OUTLINE`
dict (topics `tlb` and `thrashing`), a `check(course_md, html_text=..., outline=OUTLINE)`
helper, and a `codes(findings)` helper. Reuse these — do not build a parallel fixture.

Its default `tlb_body`/`thrashing_body` currently have **no visual at all** (just prose
and `GOOD_QUIZ`), which is about to become a real, correctly-flagged
`topic_without_visual` finding. Two existing exhaustive-equality tests will break the
moment the new check exists — `test_a_clean_course_produces_no_findings`
(`assert check(course()) == []`) and `test_glossary_matching_ignores_case`
(`assert check(course(glossary="tlb: a cache of mappings.")) == []`) — because neither
default body has a visual or a justification. Fix this at the fixture level, not by
weakening the new check: update `course()`'s defaults to include a `no-visual` comment
(both topics are genuinely non-spatial test prose, so this is an honest use of the escape
hatch, not a workaround):

```python
def course(*, tlb_body=None, thrashing_body=None, glossary="TLB: A cache of mappings."):
    tlb = tlb_body if tlb_body is not None else (
        "The TLB is fast.\n\n"
        "<!-- no-visual: test fixture prose, nothing spatial to draw -->\n\n"
        f"{GOOD_QUIZ}"
    )
    thrash = thrashing_body if thrashing_body is not None else (
        "Paging dominates.\n\n"
        "<!-- no-visual: test fixture prose, nothing spatial to draw -->\n\n"
        f"{GOOD_QUIZ}"
    )
    parts = [HEAD, "\n<!-- topic: tlb -->\n### The TLB\n\n", tlb, "\n"]
    if thrashing_body != "":
        parts += ["\n<!-- topic: thrashing -->\n### Thrashing\n\n", thrash, "\n"]
    if glossary:
        parts += ["\n```glossary\n", glossary, "\n```\n"]
    return "".join(parts)
```

Every other existing test that overrides `tlb_body`/`thrashing_body` explicitly (e.g.
`test_a_malformed_quiz_is_blocking_and_routes_to_the_writer`,
`test_a_broken_mermaid_block_is_blocking_and_routes_to_the_writer`, the `placeholders`
tests) will now also produce an *additional* `topic_without_visual` finding alongside
whatever they're checking for, since their override bodies have no visual either — but
none of them assert an exhaustive `== []` or `== [single finding]`, they all filter by
`.code ==` first, so they keep passing unchanged. Confirm this in Step 6 rather than
assuming it.

Now add the new test, alongside `test_a_topic_with_no_quiz_is_blocking_and_names_the_topic`:

```python
def test_a_topic_with_no_visual_and_no_justification_is_blocking():
    findings = check(course(tlb_body="The TLB is fast, with nothing spatial about it drawn."))
    missing = [f for f in findings if f.code == "topic_without_visual"]
    assert len(missing) == 1
    assert missing[0].topic == "tlb"
    assert missing[0].module == "m-memory"
    assert missing[0].blocking is True
    assert missing[0].route == "writer"


def test_a_figure_block_counts_as_a_visual_for_the_coverage_check():
    body = "The TLB is fast.\n\n```figure\nsource: week1.pdf#1\ncaption: c\n```\n\n" + GOOD_QUIZ
    findings = check(course(tlb_body=body))
    assert "topic_without_visual" not in codes(findings)
```

- [ ] **Step 6: Run it to verify it fails, and confirm the other tests still pass unaffected**

Run: `PYTHONPATH=scripts pytest tests/test_validate.py -v`
Expected: the two new tests FAIL (`topic_without_visual` isn't a recognised code yet); every
other test in the file still PASSES, confirming the fixture fix in Step 5 didn't disturb
anything else.

- [ ] **Step 7: Implement the check in validate.py**

Add to `ROUTE_FOR_CODE`:

```python
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
}
```

Update the error-partitioning block (item "1 & 2 & 3" in `validate_course`) to distinguish `figure`/`animate` errors from the `quiz_malformed` default, the same way `mermaid_unparseable` is already distinguished by its `"mermaid "` prefix (which mdrender.py's mermaid branch already writes; Tasks 3-4 wrote the matching `"figure "`/`"animate "` prefixes into their own `errors.append(...)` calls):

```python
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
```

Add the new coverage check right after the existing "5: every present topic has at least one quiz" block:

```python
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
```

- [ ] **Step 8: Run tests to verify they pass**

Run: `PYTHONPATH=scripts pytest tests/test_validate.py tests/test_mdrender.py tests/test_build.py -v`.
Expected: PASS across the board. Note: this new check means **the existing `MINI` fixture's own topics must already have a visual or a justification** for `test_the_mini_course_builds_clean` (`assert [f.code for f in built.findings] == []`) to keep passing — check `tests/fixtures/mini-course/modules/*.md`: `01-virtual-memory.md`'s `tlb` topic already has a `mermaid` block (per `MODULE` in the test file, which mirrors the real fixture), so it should already be covered; confirm `02-scheduling.md`'s topic the same way, and if any real fixture topic turns out to have no visual today, that is a pre-existing gap this check now correctly surfaces — fix it by adding a `no-visual` comment or a diagram to that fixture topic, whichever is actually true of its content, rather than weakening the check.

- [ ] **Step 9: Commit**

```bash
git add scripts/p2c/mdrender.py scripts/p2c/validate.py tests/test_mdrender.py tests/test_validate.py
git commit -m "feat: enforce visual-per-topic coverage as a blocking build finding"
```

(If any pre-existing fixture module needed a fix per Step 8's note, include that file in this commit too.)

---

### Task 6: Summarizer, rubric, SKILL.md, and README docs

**Files:**
- Modify: `references/agents/summarizer.md`
- Modify: `references/rubric.md`
- Modify: `SKILL.md`
- Modify: `README.md`
- Test: `tests/test_references.py`

**Note:** `course-writer.md` and `quiz-format.md` are **not** in this task's
scope — Tasks 3 and 4 already documented `figure` and `animate` there (each
in the same task that introduced the corresponding `HANDLED_KINDS` entry, so
the existing `test_course_writer_prompt_states_every_mechanical_requirement`
test in `tests/test_references.py` never goes stale mid-plan). This task
covers only the files that don't interact with that test.

**Interfaces:**
- Consumes: `reusable_image` (Task 1), the `topic_without_visual` finding code (Task 5).
- Produces: nothing new for later tasks to consume — this is documentation of what already works.

- [ ] **Step 1: Write the failing reference tests**

`tests/test_references.py` already defines `REFS = Path(__file__).resolve().parents[1] / "references"`. Add:

```python
def test_summarizer_documents_reusable_image():
    text = (REFS / "agents/summarizer.md").read_text()
    assert "reusable_image" in text


def test_rubric_notes_figure_and_animate_are_covered_by_existing_codes():
    text = (REFS / "rubric.md").read_text()
    assert "figure" in text
    assert "animate" in text
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `PYTHONPATH=scripts pytest tests/test_references.py -v`
Expected: FAIL on the two new assertions; every pre-existing test in the file (including the ones Tasks 3-4 already satisfied) still passes.

- [ ] **Step 3: Update summarizer.md**

In `references/agents/summarizer.md`, in the `## Rules` section, right after the existing `**diagrams` must be prose.` bullet, add:

```markdown
- **`reusable_image`** (optional, at most one per topic): set it to the same
  `deck.pdf#page` form as `slide_refs` when — and only when — that slide's own
  diagram or photo is worth reusing verbatim rather than being redrawn. You are
  the only agent who ever sees the slide, so this is your call alone; the
  course-writer will be told this value and will not re-derive it. Leave it
  unset for anything better explained as a fresh diagram than reused as a
  picture of the original slide.
```

- [ ] **Step 4: Update rubric.md**

In `references/rubric.md`, in the `## Noted findings` table, update the `missing_visual` row's description to note the new block types count too:

```markdown
| `missing_visual` | A diagram, reused figure, or animate block would help but its absence does not block understanding (the build's own `topic_without_visual` check already catches complete absence; this code is for "present but could be better"). |
```

Also update the `## Blocking findings` table's `render_failure` row description (currently "The page is structurally broken: a diagram did not render, a quiz has no options.") to:

```markdown
| `render_failure` | The page is structurally broken: a diagram, figure, or animate block did not render, or a quiz has no options. |
```

- [ ] **Step 5: Update SKILL.md**

In the Phase 3 section, right after the existing bullet "the resolved `<language>`, so its prose, analogies, and quizzes are written in it (jargon terms stay in their original form — see `course-writer.md`)," add:

```markdown
- each topic's `reusable_image`, if it set one, flows through automatically
  since topic objects are passed verbatim — no separate step needed here,
  but the writer must be told about it via the dispatch text, not left to
  notice it buried in the JSON.
```

- [ ] **Step 6: Update README.md**

In the Requirements table, replace the first row:

```markdown
| Python 3.12+ with `markdown>=3.5` | Required. `python3 -m pip install --user 'markdown>=3.5'`. The only runtime dependency. |
```

with:

```markdown
| Python 3.12+ with the packages in `requirements.txt` (`markdown`, `pypdfium2`, `Pillow`) | Required. `python3 -m pip install --user -r requirements.txt`. |
```

In "Design choices worth knowing", add a new paragraph:

```markdown
**Every topic gets a visual, enforced.** A `mermaid` diagram, an inline
`<svg>`, a reused slide image (`figure`), or a bounded animation pattern
(`animate`) — the build fails a topic that has none of these and no explicit
`<!-- no-visual: ... -->` justification. Reused images come from the deck
itself only: no web search, no generation, so there is never a licensing
question to answer.
```

- [ ] **Step 7: Run tests to verify they pass**

Run: `PYTHONPATH=scripts pytest tests/test_references.py -v`
Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add references/agents/summarizer.md references/rubric.md SKILL.md README.md tests/test_references.py
git commit -m "docs: document reusable_image, and note figure/animate in rubric, SKILL.md, README"
```

---

### Task 7: Golden fixture capstone — figure and animate in both languages

**Files:**
- Modify: `tests/fixtures/mini-course/outline.json`
- Modify: `tests/fixtures/mini-course/modules/01-virtual-memory.md`
- Modify: `tests/fixtures/mini-course-he/outline.json`
- Modify: `tests/fixtures/mini-course-he/modules/01-section.md`
- Modify: `tests/test_build.py` (the `built`/`built_he` fixtures)
- Modify: `tests/golden/course.html`, `tests/golden/course-he.html` (regenerated, not hand-edited)

**Interfaces:**
- Consumes: everything from Tasks 1-6. This task adds no new production code — it is fixture authoring plus regeneration, the same shape as the multi-language plan's Task 7.

- [ ] **Step 1: Give the `built`/`built_he` pytest fixtures a normalized PDF to resolve figures against**

Both fixtures currently call `build()` against a bare `tmp_path` with no `.p2c/normalized/` directory. Since Step 2 below adds a real `figure` block to both fixture courses, `build()` now needs `tmp_path/.p2c/normalized/terse.pdf` to exist every time these fixtures run. Update both in `tests/test_build.py`:

```python
@pytest.fixture
def built(tmp_path):
    normalized = tmp_path / ".p2c" / "normalized"
    normalized.mkdir(parents=True)
    (normalized / "terse.pdf").write_bytes((REPO / "tests" / "fixtures" / "terse.pdf").read_bytes())
    return build(MINI / "outline.json", MINI / "modules", tmp_path, ASSETS)


@pytest.fixture
def built_he(tmp_path):
    normalized = tmp_path / ".p2c" / "normalized"
    normalized.mkdir(parents=True)
    (normalized / "terse.pdf").write_bytes((REPO / "tests" / "fixtures" / "terse.pdf").read_bytes())
    return build(MINI_HE / "outline.json", MINI_HE / "modules", tmp_path, ASSETS)
```

This is purely additive setup — every existing test using these fixtures keeps working unchanged, since none of them assert anything about the *absence* of a `.p2c/normalized` directory.

- [ ] **Step 2: Add a figure and an animate block to the English fixture**

In `tests/fixtures/mini-course/outline.json`, add `"reusable_image": "terse.pdf#1"` to the `tlb` topic object (find it by its `"id": "tlb"` key).

In `tests/fixtures/mini-course/modules/01-virtual-memory.md`, add (right after the existing `mermaid` block for the `tlb` topic, before its worked example or quiz — follow the file's existing topic-rhythm ordering):

```markdown
```figure
source: terse.pdf#1
caption: The original slide this diagram is redrawn from.
```
```

In `tests/fixtures/mini-course/modules/02-scheduling.md`, add an `animate` block to its topic (after its own visual, as a second, deliberately-allowed illustration of a sequence):

```markdown
```animate
pattern: step-reveal
steps:
  - A process becomes ready to run
  - The scheduler picks it from the ready queue
  - It runs until it blocks, yields, or is preempted
```
```

- [ ] **Step 3: Add the same to the Hebrew fixture**

In `tests/fixtures/mini-course-he/outline.json`, add `"reusable_image": "terse.pdf#1"` to its topic object.

In `tests/fixtures/mini-course-he/modules/01-section.md`, add a `figure` block (caption in Hebrew, since captions are student-authored prose and this course's language is Hebrew — matching the existing rule that jargon stays original-form but everything else translates):

```markdown
```figure
source: terse.pdf#1
caption: השקופית המקורית שהתרשים הזה משוחזר ממנה.
```
```

And an `animate` block (also Hebrew labels):

```markdown
```animate
pattern: state-toggle
before: קבוצת העבודה בתוך הזיכרון הפיזי
after: קבוצת העבודה מוחלפת (thrashing)
```
```

- [ ] **Step 4: Run the existing build/golden tests to see the expected failure**

Run: `PYTHONPATH=scripts pytest tests/test_build.py -k golden -v`
Expected: FAIL — `test_matches_the_golden_snapshot` and `test_the_hebrew_course_matches_its_golden_snapshot` fail because the fixtures now render additional content the checked-in golden files don't have yet.

- [ ] **Step 5: Regenerate both golden snapshots deliberately**

Run: `P2C_UPDATE_GOLDEN=1 PYTHONPATH=scripts pytest tests/test_build.py -k golden -v`

Before committing, inspect the diff of both golden files (`git diff tests/golden/course.html tests/golden/course-he.html`) to confirm the *only* changes are the new `figure`/`animate` markup and, for the English file, the base64 image data — not an unrelated structural change. If either diff looks wrong, fix the fixture/CSS, not the golden file, and regenerate again.

- [ ] **Step 6: Run the full test suite**

Run: `PYTHONPATH=scripts pytest -v`
Expected: PASS, no regressions across the whole suite (this is the same full-suite check the two prior plans ran at their capstone task).

Specifically re-check `test_mermaid_is_not_inlined_when_the_course_has_no_diagrams` (`assert len(html) < 200_000`) still passes — the new `figure` block adds a small base64-encoded PNG (a near-blank single-page fixture at 96 dpi is only a few KB before base64 inflation), which should stay well under that threshold, but confirm rather than assume.

- [ ] **Step 7: Commit**

```bash
git add tests/fixtures/mini-course tests/fixtures/mini-course-he tests/test_build.py tests/golden/course.html tests/golden/course-he.html
git commit -m "test: add figure and animate blocks to both golden course fixtures"
```

---

## Self-Review Notes

- **Spec coverage:** every "In" scope item from the design doc has a task — coverage enforcement (Task 5), image reuse end-to-end (Tasks 1-3), animation patterns (Task 4), docs/README (Task 6), regression fixtures in both languages (Task 7).
- **Design-doc correction:** the coverage check lives in `p2c.validate`, not `p2c.invariants`, for the reason recorded in Global Constraints — this is the one place the plan intentionally diverges from the literal spec text, and it's called out rather than silently changed.
- **Type/name consistency checked:** `reusable_image` (Task 1) → `figure` block's `source:` (Task 3) → `_resolve_figures`'s regex groups (Task 3) → fixture usage (Task 7) all use the identical `deck.pdf#page` string shape and field name throughout. `Animate` dataclass fields (`pattern`, `steps`, `before`, `after`) are identical between `parse_animate` and `_animate_html` (Task 4). `topics_missing_visual` (Task 5) is the exact name used in both `mdrender.py` and referenced from `validate.py`.
- **No placeholders:** every step above has complete, exact code — no "add appropriate tests" or "similar to Task N" placeholders.
