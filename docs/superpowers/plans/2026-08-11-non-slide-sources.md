# Non-Slide Sources Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let `normalize` (Phase 0) accept `.docx`, `.txt`, and `.md` source
files — not just `.pdf`/`.pptx` — by converting each into a page-image-ready
PDF, so the vision-based summarizer can read an article, essay, or research
paper exactly the way it reads a slide deck today, with no changes to any
agent prompt.

**Architecture:** Two independent additions inside `scripts/p2c/normalize.py`.
(1) `.docx` reuses the exact `soffice --headless --convert-to pdf` mechanism
`.pptx` already uses — the existing PPTX-conversion function is generalized
to a format-agnostic office-document converter, not duplicated. (2) `.txt`/
`.md` have no native page layout, so they are rendered to a minimal standalone
HTML page (Markdown via the `markdown` library's plain `extra`/`sane_lists`
extensions — no P2C-specific fence handling, since this is a generic external
document, not course-authored content) and printed to PDF via headless
Chromium, reusing the browser-discovery logic `p2c.exportpdf` already has
(moved to `p2c.normalize` so `exportpdf` can import it instead of the reverse,
avoiding a circular import). Chromium absence is a new **hard failure** for
this one input type (exit 7) — unlike the existing *soft* skip for PDF export,
there is no fallback: without Chromium there is no way to produce the page
images the summarizer needs from plain text.

**Tech Stack:** Python stdlib + `markdown` (already a dependency) + headless
Chromium (already a soft dependency via `p2c.exportpdf`) + `soffice`/
LibreOffice (already a dependency for `.pptx`). No new dependency is added.

## Global Constraints

- `SUPPORTED` in `scripts/p2c/normalize.py` gains exactly four extensions:
  `.docx`, `.txt`, `.md` (plus the existing `.pdf`/`.pptx`). No `.doc`/`.rtf`/
  `.odt` or any other legacy format — not requested, out of scope.
- `.docx` conversion must use the *same* `SofficeMissing`/exit-4 failure mode
  as `.pptx` today — no new exit code for this path.
- `.md` rendering must use `markdown.Markdown(extensions=["extra", "sane_lists"])`
  directly — the same extension list `p2c.mdrender._md()` uses — but **never**
  call `p2c.mdrender._md()` or `p2c.blocks.extract_fences()` themselves. Those
  are course-authoring-pipeline functions (they understand `quiz`/`glossary`/
  `animate` fences); a generic external article is not course content and
  must not be interpreted as if it were.
- A new exit code, **7**, for "Chromium missing, needed to render a `.txt`/
  `.md` source." This is a *new*, *different* failure from `export-pdf`'s
  existing exit 6 (`export-pdf` skips softly; `normalize` for a text source
  must hard-fail, since there is no other way to produce page images).
- No change to `references/agents/summarizer.md`, `researcher.md`, or
  `course-writer.md` — the summarizer stays completely source-format-agnostic,
  per the design spec's explicit decision.
- No new outline-validation code, no structural/heading-based segmentation
  mode — the existing `planned_agent_count` report (in `SKILL.md`'s Phase 1
  section) is the only guard against runaway segmentation, unchanged.
- Golden snapshots (`tests/golden/course.html`, `tests/golden/course-he.html`)
  are **not expected to change** by this plan — nothing here touches
  `mdrender.py`'s output shape or any theme/layout CSS. Do not regenerate
  them unless a test unexpectedly requires it; if that happens, stop and
  investigate before proceeding, since it would indicate this plan touched
  something it shouldn't have.
- **Correction to the design spec's testing note**: the spec
  (`docs/superpowers/specs/2026-08-10-input-output-expansion-design.md`)
  says a new `.md` fixture should be "exercised through `test_build.py`,
  producing a normal course build." This is not achievable as literally
  stated: `test_build.py`'s `built`/`built_he` fixtures call
  `p2c.build.build()` directly against pre-authored `outline.json` +
  `modules/` markdown files — they never invoke `normalize()` at all, and a
  full course build requires the summarizer/researcher/course-writer, which
  are real AI subagents, not something a unit test can invoke. The correct,
  achievable equivalent — and what this plan actually does — is a
  `test_normalize.py`-level test: a small `.md`/`.txt` fixture run through
  `normalize()` directly, asserting it produces a valid multi-page PDF with
  the expected page count and that the PDF's text content includes the
  source's own headings/paragraphs. `test_build.py` is not touched by this
  plan.

---

### Task 1: Generalize PPTX conversion to any LibreOffice-convertible format, add `.docx`

**Files:**
- Modify: `scripts/p2c/normalize.py:15` (`SUPPORTED`), `:83-102`
  (`collect_inputs`'s error message), `:114-135` (`_convert_pptx` →
  generalized), `:138-165` (`normalize()`'s office-conversion branch)
- Test: `tests/test_normalize.py`

**Interfaces:**
- Consumes: nothing new.
- Produces: `SUPPORTED` now includes `.docx` (consumed by Task 2, which adds
  `.txt`/`.md` to the same set). The renamed converter function
  `_convert_office_doc(src: Path, out_dir: Path, soffice: str, target: Path) -> Path`
  (same signature as the old `_convert_pptx`, just renamed) is not consumed
  by any later task directly, but Task 2 follows the same "one dedicated
  private converter function per new format" pattern.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_normalize.py`, near the existing
`test_normalize_dedupes_colliding_pptx_stems_without_clobbering` (which
already defines `_FAKE_SOFFICE` — reuse it verbatim, do not redefine):

```python
def test_normalize_converts_docx_via_soffice(tmp_path):
    fake_soffice = tmp_path / "fake_soffice.py"
    fake_soffice.write_text(_FAKE_SOFFICE)
    fake_soffice.chmod(0o755)
    src_dir = tmp_path / "src"
    src_dir.mkdir()
    (src_dir / "essay.docx").write_bytes(b"not a real docx, soffice is faked")
    out = tmp_path / "out"
    result = normalize([src_dir / "essay.docx"], out, str(fake_soffice))
    assert [p.name for p in result.pdfs] == ["essay.pdf"]
    assert [p.name for p in result.converted] == ["essay.pdf"]
    assert result.pages == {"essay.pdf": 1}


def test_normalize_hard_fails_on_docx_without_soffice(tmp_path):
    (tmp_path / "essay.docx").write_bytes(b"not a real docx")
    with pytest.raises(SofficeMissing):
        normalize([tmp_path / "essay.docx"], tmp_path / "out", soffice=None)


def test_collect_inputs_error_message_lists_all_supported_formats(tmp_path):
    odd = tmp_path / "deck.key"
    odd.write_text("nope")
    with pytest.raises(BadDeck, match=r"PDF, PPTX, or DOCX"):
        collect_inputs([odd])
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_normalize.py -v -k "docx or error_message"`
Expected: FAIL — `.docx` is not yet in `SUPPORTED`, so `collect_inputs`
raises "unsupported input (expected .pdf or .pptx)" instead of converting,
and the error-message test fails because the message doesn't yet mention
DOCX.

- [ ] **Step 3: Update `scripts/p2c/normalize.py`**

Change line 15 from:

```python
SUPPORTED = {".pdf", ".pptx"}
```

to:

```python
SUPPORTED = {".pdf", ".pptx", ".docx"}
```

Change `collect_inputs`'s two "unsupported"/"no PDF or PPTX" messages (lines
92 and 96) from:

```python
            if not decks:
                raise BadDeck(f"{path}: no PDF or PPTX files found")
            found.extend(decks)
        elif path.is_file():
            if path.suffix.lower() not in SUPPORTED:
                raise BadDeck(f"{path}: unsupported input (expected .pdf or .pptx)")
```

to:

```python
            if not decks:
                raise BadDeck(f"{path}: no PDF, PPTX, or DOCX files found")
            found.extend(decks)
        elif path.is_file():
            if path.suffix.lower() not in SUPPORTED:
                raise BadDeck(f"{path}: unsupported input (expected PDF, PPTX, or DOCX)")
```

Rename `_convert_pptx` to `_convert_office_doc` (identical body — this is a
pure rename, the function already takes `src`/`out_dir`/`soffice`/`target`
generically and doesn't hardcode anything PPTX-specific beyond its name and
docstring wording):

```python
def _convert_office_doc(src: Path, out_dir: Path, soffice: str, target: Path) -> Path:
    """Convert src (.pptx or .docx) to PDF in a private scratch dir, then place it
    at target.

    LibreOffice always names its output "<stem>.pdf" and has no notion of
    normalize()'s stem-collision dedup. Converting straight into the shared
    out_dir would let a second same-stemmed source's conversion silently
    clobber the first's output on disk before it's ever moved to its
    (distinct) deduplicated target name. A private temp directory per
    conversion makes that collision impossible regardless of ordering.
    """
    with tempfile.TemporaryDirectory(dir=out_dir) as scratch:
        proc = subprocess.run(
            [soffice, "--headless", "--convert-to", "pdf", "--outdir", scratch, str(src)],
            capture_output=True,
            text=True,
            timeout=300,
        )
        produced = Path(scratch) / f"{src.stem}.pdf"
        if proc.returncode != 0 or not produced.exists():
            raise BadDeck(f"{src}: LibreOffice conversion failed\n{proc.stdout}\n{proc.stderr}")
        produced.replace(target)
    return target
```

In `normalize()`, change the soffice-missing guard (line 142) from:

```python
    if any(d.suffix.lower() == ".pptx" for d in decks) and (
        soffice is None or shutil.which(soffice) is None
    ):
        raise SofficeMissing(INSTALL_HINT)
```

to:

```python
    if any(d.suffix.lower() in (".pptx", ".docx") for d in decks) and (
        soffice is None or shutil.which(soffice) is None
    ):
        raise SofficeMissing(INSTALL_HINT)
```

And change the per-deck branch (lines 152-162) from:

```python
        if deck.suffix.lower() == ".pdf":
            data = deck.read_bytes()
            try:
                pages = pdf_page_count(data)
            except BadDeck as exc:
                raise BadDeck(f"{deck}: {exc}") from exc
            target.write_bytes(data)
        else:
            produced = _convert_pptx(deck, out_dir, soffice, target)  # type: ignore[arg-type]
            pages = pdf_page_count(produced.read_bytes())
            result.converted.append(produced)
```

to:

```python
        if deck.suffix.lower() == ".pdf":
            data = deck.read_bytes()
            try:
                pages = pdf_page_count(data)
            except BadDeck as exc:
                raise BadDeck(f"{deck}: {exc}") from exc
            target.write_bytes(data)
        elif deck.suffix.lower() in (".pptx", ".docx"):
            produced = _convert_office_doc(deck, out_dir, soffice, target)  # type: ignore[arg-type]
            pages = pdf_page_count(produced.read_bytes())
            result.converted.append(produced)
        else:
            # .txt/.md land here in Task 2 -- unreachable until then, since
            # SUPPORTED doesn't include them yet.
            raise BadDeck(f"{deck}: unsupported input (expected PDF, PPTX, or DOCX)")
```

(The trailing `else` branch is a defensive placeholder that Task 2 replaces
with real `.txt`/`.md` handling — with only `.pdf`/`.pptx`/`.docx` in
`SUPPORTED` after this task, `collect_inputs` already rejects anything else
before `normalize()`'s loop ever reaches it, so this branch is unreachable
dead code until Task 2, by design, matching this codebase's existing
"structural completeness over cleverness" style for exhaustive-looking
branches.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_normalize.py -v`
Expected: all tests pass, including the three new ones and every
pre-existing PPTX test (unaffected by the rename, since only the private
function's name changed, not its behavior or the public `normalize()`
API).

- [ ] **Step 5: Run the full test suite**

Run: `.venv/bin/pytest tests/ -v`
Expected: all tests pass (no golden-snapshot impact — this task only
touches `normalize.py`).

- [ ] **Step 6: Commit**

```bash
git add scripts/p2c/normalize.py tests/test_normalize.py
git commit -m "feat: accept .docx input via the existing LibreOffice conversion path"
```

---

### Task 2: Move Chromium discovery into `normalize.py`; render `.txt`/`.md` to PDF

**Files:**
- Modify: `scripts/p2c/normalize.py` (add `find_chromium`, `CHROMIUM_CANDIDATES`,
  a new `ChromiumMissing` exception, `.txt`/`.md` rendering)
- Modify: `scripts/p2c/exportpdf.py:17-31` (import `find_chromium`/
  `CHROMIUM_CANDIDATES` from `p2c.normalize` instead of defining them; remove
  the now-duplicate definitions)
- Test: `tests/test_normalize.py`, `tests/test_export_pdf.py`

**Interfaces:**
- Consumes: `SUPPORTED` from Task 1 (this task adds `.txt`/`.md` to it).
- Produces: `find_chromium(explicit: str | None = None) -> str | None` and
  `CHROMIUM_CANDIDATES: tuple[str, ...]`, now defined in `p2c.normalize` —
  `p2c.exportpdf` re-imports both under the same names, so nothing outside
  `normalize.py`/`exportpdf.py` needs to know they moved. `ChromiumMissing`
  is a new `NormalizeError` subclass with `exit_code = 7`, consumed by
  Task 3's CLI-level test.

- [ ] **Step 1: Write the failing test for the Chromium-discovery move**

Add to `tests/test_normalize.py`:

```python
def test_find_chromium_is_available_from_normalize(monkeypatch, tmp_path):
    # find_chromium moved here from p2c.exportpdf so normalize.py can use it
    # without importing exportpdf.py (which itself imports from normalize.py
    # -- importing the other way would be circular).
    from p2c.normalize import find_chromium

    fake = tmp_path / "fake-chromium"
    fake.write_text("#!/bin/sh\necho fake\n")
    fake.chmod(0o755)
    assert find_chromium(str(fake)) == str(fake)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_normalize.py::test_find_chromium_is_available_from_normalize -v`
Expected: FAIL — `ImportError: cannot import name 'find_chromium' from 'p2c.normalize'`.

- [ ] **Step 3: Move `find_chromium`/`CHROMIUM_CANDIDATES` into `normalize.py`**

Add near the top of `scripts/p2c/normalize.py`, after the existing
`INSTALL_HINT` constant (around line 20):

```python
CHROMIUM_CANDIDATES = (
    "chromium",
    "chromium-browser",
    "google-chrome",
    "google-chrome-stable",
    "chrome",
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Chromium.app/Contents/MacOS/Chromium",
)


def find_chromium(explicit: str | None = None) -> str | None:
    """An explicitly requested browser is honoured or refused, never substituted."""
    requested = explicit or os.environ.get("P2C_CHROMIUM")
    if requested:
        if Path(requested).is_file() or shutil.which(requested):
            return requested
        return None
    for candidate in CHROMIUM_CANDIDATES:
        if Path(candidate).is_file():
            return candidate
        found = shutil.which(candidate)
        if found:
            return found
    return None
```

Add `import os` to `normalize.py`'s existing import block (it currently has
`json`, `re`, `shutil`, `subprocess`, `tempfile` — add `os` alphabetically
among the stdlib imports).

Add a new exception class next to the existing ones:

```python
class ChromiumMissing(NormalizeError):
    exit_code = 7
```

- [ ] **Step 4: Update `scripts/p2c/exportpdf.py` to import instead of define**

Change lines 17-31 from:

```python
from p2c.normalize import BadDeck, pdf_page_count

CHROMIUM_CANDIDATES = (
    "chromium",
    "chromium-browser",
    "google-chrome",
    "google-chrome-stable",
    "chrome",
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Chromium.app/Contents/MacOS/Chromium",
)
SKIP_REASON = (
    "headless Chromium was not found, so the PDF was not written. "
    "Open the course HTML and use the Download PDF button instead."
)
VIRTUAL_TIME_BUDGET_MS = 20000


class ExportError(Exception):
    """Chromium was available but the export failed."""
```

to:

```python
from p2c.normalize import BadDeck, CHROMIUM_CANDIDATES, find_chromium, pdf_page_count

SKIP_REASON = (
    "headless Chromium was not found, so the PDF was not written. "
    "Open the course HTML and use the Download PDF button instead."
)
VIRTUAL_TIME_BUDGET_MS = 20000


class ExportError(Exception):
    """Chromium was available but the export failed."""
```

Delete the now-duplicate `find_chromium` function definition further down in
`exportpdf.py` (the one immediately after this block, currently at
lines 47-58) — it now comes from the import instead. Leave every call site
(`find_chromium(chromium)` inside `export_pdf()`) exactly as-is; it resolves
to the imported function.

- [ ] **Step 5: Run test to verify the move works and nothing broke**

Run: `.venv/bin/pytest tests/test_normalize.py::test_find_chromium_is_available_from_normalize tests/test_export_pdf.py -v`
Expected: all pass, including every pre-existing `test_export_pdf.py` test
(`test_find_chromium_prefers_an_explicit_path`,
`test_find_chromium_honours_the_env_var`,
`test_find_chromium_returns_none_when_nothing_is_installed`, and the
`monkeypatch.setattr("p2c.exportpdf.find_chromium", ...)` one) — these still
import `find_chromium` from `p2c.exportpdf` and monkeypatch that same
module-level name; re-exporting via `from p2c.normalize import find_chromium`
keeps `p2c.exportpdf.find_chromium` a valid, patchable attribute.

- [ ] **Step 6: Write the failing test for `.md` → PDF rendering**

Add to `tests/test_normalize.py`:

```python
def _fake_chromium_writing_pdf(tmp_path, pages=1):
    """Same stand-in pattern as tests/test_export_pdf.py's fake_chromium --
    writes a real minimal PDF to whatever --print-to-pdf= path it's given."""
    script = tmp_path / "fake-chromium-normalize"
    data = make_pdf([["rendered"]] * pages)
    body = (
        "import sys, pathlib\n"
        "out = [a.split('=', 1)[1] for a in sys.argv if a.startswith('--print-to-pdf=')][0]\n"
        f"pathlib.Path(out).write_bytes({data!r})\n"
    )
    script.write_text(f"#!{sys.executable}\n{body}")
    script.chmod(0o755)
    return str(script)


def test_normalize_renders_markdown_to_pdf_via_chromium(tmp_path, monkeypatch):
    monkeypatch.setenv("P2C_CHROMIUM", _fake_chromium_writing_pdf(tmp_path, pages=2))
    src_dir = tmp_path / "src"
    src_dir.mkdir()
    (src_dir / "essay.md").write_text("# Title\n\nSome prose.\n\n## Section 2\n\nMore.\n")
    out = tmp_path / "out"
    result = normalize([src_dir / "essay.md"], out, soffice=None)
    assert [p.name for p in result.pdfs] == ["essay.pdf"]
    assert [p.name for p in result.converted] == ["essay.pdf"]
    assert result.pages == {"essay.pdf": 2}


def test_normalize_renders_plain_text_to_pdf_via_chromium(tmp_path, monkeypatch):
    monkeypatch.setenv("P2C_CHROMIUM", _fake_chromium_writing_pdf(tmp_path, pages=1))
    src_dir = tmp_path / "src"
    src_dir.mkdir()
    (src_dir / "notes.txt").write_text("Just plain text, no markdown syntax.\n")
    out = tmp_path / "out"
    result = normalize([src_dir / "notes.txt"], out, soffice=None)
    assert [p.name for p in result.pdfs] == ["notes.pdf"]
    assert result.pages == {"notes.pdf": 1}


def test_normalize_hard_fails_on_markdown_without_chromium(tmp_path, monkeypatch):
    monkeypatch.delenv("P2C_CHROMIUM", raising=False)
    monkeypatch.setattr("p2c.normalize.find_chromium", lambda explicit=None: None)
    (tmp_path / "essay.md").write_text("# Title\n")
    with pytest.raises(ChromiumMissing):
        normalize([tmp_path / "essay.md"], tmp_path / "out", soffice=None)


def test_export_pdf_exit_6_is_unaffected_by_the_new_exit_7(tmp_path, monkeypatch):
    # Regression guard: a .pdf/.pptx/.docx run must never raise ChromiumMissing
    # even when Chromium is completely absent -- exit 7 is scoped to .txt/.md
    # input only, and export-pdf's own separate exit-6 soft-skip is untouched.
    monkeypatch.delenv("P2C_CHROMIUM", raising=False)
    monkeypatch.setattr("p2c.normalize.find_chromium", lambda explicit=None: None)
    result = normalize([FIXTURES / "terse.pdf"], tmp_path / "out", soffice=None)
    assert result.pages == {"terse.pdf": 3}


@pytest.mark.skipif(
    all(shutil.which(name) is None for name in
        ("chromium", "chromium-browser", "google-chrome", "google-chrome-stable")),
    reason="no Chromium installed",
)
def test_real_chromium_renders_markdown_to_a_readable_pdf(tmp_path):
    # Mirrors tests/test_export_pdf.py's test_real_chromium_produces_a_pdf --
    # same opt-in-when-available pattern, but exercised through normalize()'s
    # .md path instead of exportpdf's course-HTML path.
    src_dir = tmp_path / "src"
    src_dir.mkdir()
    (src_dir / "essay.md").write_text(
        "# A Real Heading\n\nSome real prose the vision-based summarizer must "
        "be able to read as an actual page of text, not a blank page.\n"
    )
    result = normalize([src_dir / "essay.md"], tmp_path / "out", soffice=None)
    assert result.pages == {"essay.pdf": 1}
    produced_pdf = (tmp_path / "out" / "essay.pdf").read_bytes()
    assert produced_pdf.startswith(b"%PDF-")
```

`shutil` is already imported at the top of `tests/test_normalize.py`
(confirm this — it's used by the existing
`test_pptx_converts_when_soffice_is_present`'s `skipif` guard, which follows
the identical pattern this new test reuses).

`make_pdf` and `sys` are already imported at the top of
`tests/test_normalize.py` (confirm this — both are used by the existing
PPTX fake-script tests already). Add `ChromiumMissing` to the existing
`from p2c.normalize import (...)` block, which currently reads:

```python
from p2c.normalize import (
    BadDeck,
    NormalizeResult,
    SofficeMissing,
    collect_inputs,
    normalize,
    pdf_page_count,
)
```

Change it to:

```python
from p2c.normalize import (
    BadDeck,
    ChromiumMissing,
    NormalizeResult,
    SofficeMissing,
    collect_inputs,
    normalize,
    pdf_page_count,
)
```

- [ ] **Step 7: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_normalize.py -v -k "markdown or plain_text or exit_6"`
Expected: FAIL — `.md`/`.txt` are not yet in `SUPPORTED`, so these raise
`BadDeck` ("unsupported input") instead of rendering; `ChromiumMissing`
doesn't exist as an importable name yet.

- [ ] **Step 8: Implement `.txt`/`.md` rendering in `normalize.py`**

Add `.txt` and `.md` to `SUPPORTED` (from Task 1's `{".pdf", ".pptx", ".docx"}`):

```python
SUPPORTED = {".pdf", ".pptx", ".docx", ".txt", ".md"}
```

Add `import markdown` to the top-level imports (alongside the existing
`json`, `os`, `re`, `shutil`, `subprocess`, `tempfile`).

Add a minimal standalone HTML template and a rendering function, placed
after `_convert_office_doc`:

```python
_TEXT_SOURCE_TEMPLATE = """<!doctype html>
<html><head><meta charset="utf-8">
<style>
  body {{ font-family: serif; font-size: 14px; line-height: 1.5;
          max-width: 40rem; margin: 2rem auto; }}
  h1, h2, h3 {{ font-family: sans-serif; }}
</style>
</head><body>
{body}
</body></html>
"""

# Plain "extra"/"sane_lists" only -- the same extension list p2c.mdrender._md()
# uses, but this is never routed through mdrender._md() or
# p2c.blocks.extract_fences() itself. Those two understand P2C's own
# quiz/glossary/animate fence grammar; a generic external article is not
# course-authored content and must not be interpreted through that lens.
_TEXT_SOURCE_MD_EXTENSIONS = ["extra", "sane_lists"]


def _render_text_source_to_pdf(src: Path, chromium: str, target: Path) -> Path:
    """Render a .txt/.md file to a one-shot standalone HTML page, then print
    that to PDF via headless Chromium -- the same print-to-pdf mechanism
    p2c.exportpdf uses for course output, reused here via find_chromium
    (see module-level docstring for why this lives in normalize.py, not
    exportpdf.py)."""
    text = src.read_text(encoding="utf-8")
    if src.suffix.lower() == ".md":
        body_html = markdown.Markdown(extensions=_TEXT_SOURCE_MD_EXTENSIONS).convert(text)
    else:
        import html as _html
        body_html = f"<pre>{_html.escape(text)}</pre>"
    page_html = _TEXT_SOURCE_TEMPLATE.format(body=body_html)

    with tempfile.TemporaryDirectory() as scratch:
        html_path = Path(scratch) / f"{src.stem}.html"
        html_path.write_text(page_html, encoding="utf-8")
        with tempfile.TemporaryDirectory() as profile:
            command = [
                chromium,
                "--headless=new",
                "--disable-gpu",
                "--no-sandbox",
                "--no-first-run",
                "--no-pdf-header-footer",
                f"--user-data-dir={profile}",
                "--virtual-time-budget=20000",
                f"--print-to-pdf={target}",
                html_path.resolve().as_uri(),
            ]
            proc = subprocess.run(command, capture_output=True, text=True, timeout=180)
        if proc.returncode != 0 or not target.exists():
            raise BadDeck(
                f"{src}: Chromium print-to-pdf failed\n{proc.stdout}\n{proc.stderr}"
            )
    return target
```

In `normalize()`, replace the Task 1 placeholder `else` branch:

```python
        else:
            # .txt/.md land here in Task 2 -- unreachable until then, since
            # SUPPORTED doesn't include them yet.
            raise BadDeck(f"{deck}: unsupported input (expected PDF, PPTX, or DOCX)")
```

with:

```python
        elif deck.suffix.lower() in (".txt", ".md"):
            if chromium_bin is None:
                raise ChromiumMissing(CHROMIUM_INSTALL_HINT)
            produced = _render_text_source_to_pdf(deck, chromium_bin, target)
            pages = pdf_page_count(produced.read_bytes())
            result.converted.append(produced)
        else:
            raise BadDeck(f"{deck}: unsupported input (expected PDF, PPTX, or DOCX, TXT, or MD)")
```

Add `chromium_bin = find_chromium()` once, near the top of `normalize()`
(right after the existing `soffice`-missing guard), and a new
`CHROMIUM_INSTALL_HINT` constant next to `INSTALL_HINT`:

```python
CHROMIUM_INSTALL_HINT = (
    "TXT/MD input requires headless Chromium to render page images. Install it "
    "and re-run:\n"
    "  sudo apt install chromium         # Debian/Ubuntu\n"
    "  brew install --cask chromium      # macOS"
)
```

and, in `normalize()`, right after the existing soffice guard:

```python
    chromium_bin = find_chromium()
```

Also update the two now-stale "expected PDF, PPTX, or DOCX" messages from
Task 1 (both `collect_inputs` occurrences) to include TXT/MD:

```python
            if not decks:
                raise BadDeck(f"{path}: no PDF, PPTX, DOCX, TXT, or MD files found")
            found.extend(decks)
        elif path.is_file():
            if path.suffix.lower() not in SUPPORTED:
                raise BadDeck(f"{path}: unsupported input (expected PDF, PPTX, DOCX, TXT, or MD)")
```

(This supersedes Task 1's "PDF, PPTX, or DOCX" wording — Task 1's own test
`test_collect_inputs_error_message_lists_all_supported_formats` must be
updated in this task to match the new message; see Step 9.)

- [ ] **Step 9: Update Task 1's error-message test for the new wording**

In `tests/test_normalize.py`, update
`test_collect_inputs_error_message_lists_all_supported_formats` (added in
Task 1) to match the final message:

```python
def test_collect_inputs_error_message_lists_all_supported_formats(tmp_path):
    odd = tmp_path / "deck.key"
    odd.write_text("nope")
    with pytest.raises(BadDeck, match=r"PDF, PPTX, DOCX, TXT, or MD"):
        collect_inputs([odd])
```

- [ ] **Step 10: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_normalize.py tests/test_export_pdf.py -v`
Expected: all pass.

- [ ] **Step 11: Run the full test suite**

Run: `.venv/bin/pytest tests/ -v`
Expected: all pass, no golden-snapshot impact.

- [ ] **Step 12: Commit**

```bash
git add scripts/p2c/normalize.py scripts/p2c/exportpdf.py tests/test_normalize.py
git commit -m "feat: render .txt/.md sources to PDF via headless Chromium"
```

---

### Task 3: CLI wrapper docstring, exit-code table, and a real-Chromium integration test

**Files:**
- Modify: `scripts/normalize:2` (docstring exit-code comment)
- Test: `tests/test_normalize.py`

**Interfaces:**
- Consumes: `ChromiumMissing` (exit_code 7) from Task 2.
- Produces: nothing consumed by later tasks.

- [ ] **Step 1: Update the CLI wrapper's docstring**

`scripts/normalize`'s exit codes are documented generically via each
`NormalizeError` subclass's own `exit_code` attribute — no code change is
needed there (confirmed: the wrapper's `except NormalizeError` branch reads
`exc.exit_code` dynamically, so `ChromiumMissing`'s `exit_code = 7` already
propagates correctly with zero wrapper changes). Only its docstring comment
needs updating.

Change line 2 of `scripts/normalize` from:

```python
"""CLI wrapper. Exit codes: 0 ok, 2 usage, 4 soffice missing, 5 bad deck."""
```

to:

```python
"""CLI wrapper. Exit codes: 0 ok, 2 usage, 4 soffice missing, 5 bad deck, 7 chromium missing."""
```

- [ ] **Step 2: Write a CLI-level test for exit 7**

Add to `tests/test_normalize.py`, near the existing `test_cli_exit_4_on_pptx_without_soffice`:

```python
def test_cli_exit_7_on_markdown_without_chromium(tmp_path, monkeypatch):
    (tmp_path / "essay.md").write_text("# Title\n")
    env = dict(**__import__("os").environ, P2C_CHROMIUM="definitely-not-a-browser")
    proc = subprocess.run(
        [sys.executable, str(REPO / "scripts" / "normalize"),
         str(tmp_path / "essay.md"), "--out", str(tmp_path / "out")],
        capture_output=True, text=True, env=env,
    )
    assert proc.returncode == 7
    assert "chromium" in proc.stderr.lower() or "Chromium" in proc.stderr
```

Check the existing CLI tests in this file (e.g.
`test_cli_exit_4_on_pptx_without_soffice`) for the exact subprocess-invocation
helper already in use — if one exists (a `_run_cli` helper or similar), use
it instead of duplicating the `subprocess.run(...)` call above.

- [ ] **Step 3: Run test to verify it fails, then passes**

Run: `.venv/bin/pytest tests/test_normalize.py::test_cli_exit_7_on_markdown_without_chromium -v`
Expected: FAIL before Task 2's work is visible via the CLI (it shouldn't be —
Task 2 is already committed, so this should actually PASS immediately if
Task 2 was done correctly; if it fails, that means Task 2's `ChromiumMissing`
wiring has a bug reachable only through the CLI path — investigate rather
than assuming the test itself is wrong).

- [ ] **Step 4: Run the full test suite**

Run: `.venv/bin/pytest tests/ -v`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add scripts/normalize tests/test_normalize.py
git commit -m "docs: document exit 7 in the normalize CLI wrapper"
```

---

### Task 4: Update `SKILL.md` and course-writer-facing docs for the new input formats

**Files:**
- Modify: `SKILL.md:3` (frontmatter description), `:88` (failure-handling
  table, exit-4 row context), and the failure-handling table near the end
  (add exit-7 row)

**Interfaces:**
- Consumes: exit code 7 and the new accepted extensions from Tasks 1-3.
- Produces: nothing (this is the final task; pure documentation).

- [ ] **Step 1: Update the frontmatter description**

Change `SKILL.md` line 3 from:

```
description: Use when the user wants a lecture slide deck (PDF or PPTX), or a folder of decks, turned into a course they can actually study from — "turn this deck into a course", "make a course from these lectures", "I can't revise from these slides". Produces a self-contained <course-title>.html with analogies, diagrams, a glossary and per-topic quizzes, plus a matching <course-title>.pdf.
```

to:

```
description: Use when the user wants a lecture slide deck (PDF or PPTX), an article/essay/research paper (PDF, DOCX, TXT, or MD), or a folder of any of these, turned into a course they can actually study from — "turn this deck into a course", "make a course from these lectures", "turn this paper into a course", "I can't revise from these slides". Produces a self-contained <course-title>.html with analogies, diagrams, a glossary and per-topic quizzes, plus a matching <course-title>.pdf.
```

- [ ] **Step 2: Update the exit-4 failure-handling paragraph in Phase 0**

Find this paragraph (currently right after the `normalize` invocation in
Phase 0):

```
- **exit 4** — PPTX input with no LibreOffice. **Stop the run.** Print the install command
  from stderr verbatim. Do not fall back to text extraction: it would silently discard
  every diagram, and the diagram is usually the most valuable thing on the slide.
- **exit 5** — an unreadable or zero-page deck. **Stop the run**, printing the offending
  file from stderr.
```

Replace with:

```
- **exit 4** — PPTX or DOCX input with no LibreOffice. **Stop the run.** Print the install
  command from stderr verbatim. Do not fall back to text extraction: it would silently
  discard every diagram, and the diagram is usually the most valuable thing on the slide.
- **exit 5** — an unreadable or zero-page deck. **Stop the run**, printing the offending
  file from stderr.
- **exit 7** — TXT or MD input with no headless Chromium available. **Stop the run.** Print
  the install command from stderr verbatim. Unlike PDF export's own Chromium dependency
  (which skips softly, since the HTML course still has a working print button), there is no
  fallback here: without Chromium there is no way to turn plain text into the page images
  the summarizer reads.
```

- [ ] **Step 3: Update the final failure-handling table**

Find this table row near the end of `SKILL.md`:

```
| `soffice` missing, PPTX input | Hard fail (`normalize` exit 4), print the install command |
| Chromium missing | Skip `<basename>.pdf` (`export-pdf` exit 6), note it, HTML print button still works |
```

Replace with:

```
| `soffice` missing, PPTX or DOCX input | Hard fail (`normalize` exit 4), print the install command |
| Chromium missing, PDF export | Skip `<basename>.pdf` (`export-pdf` exit 6), note it, HTML print button still works |
| Chromium missing, TXT/MD input | Hard fail (`normalize` exit 7), print the install command — no fallback exists for this input type |
```

- [ ] **Step 4: Run the full test suite one final time**

Run: `.venv/bin/pytest tests/ -v`
Expected: all pass (this task is documentation-only, no test impact
expected — this step exists to confirm the branch is still green before the
final commit).

- [ ] **Step 5: Commit**

```bash
git add SKILL.md
git commit -m "docs: document .docx/.txt/.md input support and exit 7 in SKILL.md"
```

---

## Out of scope (carried from the design spec)

- The multi-language rendering feature (Feature A) — already implemented
  and merged separately.
- The caching design (cross-run cache, shared source cache) — separate
  plan/spec entirely.
- `.doc`/`.rtf`/`.odt`/other legacy office formats.
- Any change to `references/agents/summarizer.md`, `researcher.md`, or
  `course-writer.md` — the summarizer stays fully source-format-agnostic.
- A structural (heading-based) segmentation mode, or new outline-validation
  code bounding topic/module count for prose sources — the existing
  `planned_agent_count` gate is judged sufficient.
- A full end-to-end `test_build.py`-driven course build from a `.md` source
  — not achievable without invoking real AI agents; see the Global
  Constraints section's correction to the design spec's testing note.
