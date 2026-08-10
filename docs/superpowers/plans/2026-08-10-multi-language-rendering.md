# Multi-Language Rendering Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make every theme render readably for any language/script the
course-writer is asked to produce output in, by widening font-family
fallbacks and adding safe line-wrapping to fixed-width containers — without
touching direction logic, language validation, or any agent prompt.

**Architecture:** Two additive CSS changes. (1) Append a common tail of
named system-font fallbacks to `--font-body`/`--font-heading` in all three
theme files, after each theme's existing Latin-script fonts.
`--font-mono` is untouched. (2) Add `overflow-wrap: anywhere` to four
existing selectors in the shared layout stylesheet so long unbroken runs of
text (as CJK scripts produce, having no inter-word spaces) wrap inside their
fixed-width containers instead of overflowing. No new files, no Python
changes, no schema changes.

**Tech Stack:** Plain CSS (custom properties / `:root` tokens), pytest for
assertions against the raw asset files (this project's established pattern
for CSS-level testing — see `tests/test_assets.py`).

## Global Constraints

- No bundled webfonts and no `@font-face` — `tests/test_assets.py::test_themes_use_system_font_stacks_only`
  already enforces `"@font-face" not in css` for every theme; this plan must
  not violate it. Only named font-family fallbacks are added.
- No network calls from any asset — `tests/test_assets.py::test_no_asset_reaches_the_network`
  already enforces this for every file this plan touches; nothing added
  here introduces a URL, `@import`, `fetch(`, or `XMLHttpRequest`.
- `--font-mono` must not change in any theme — code blocks stay
  Latin/ASCII-only regardless of course language (existing project
  convention, stated in the design spec).
- No change to `scripts/p2c/theme.py`'s `is_rtl()`/`RTL_LANGUAGES`, no change
  to `scripts/p2c/outline.py`'s language-code validation, no change to any
  file under `references/agents/`. This plan is CSS-only.
- Golden snapshots (`tests/golden/course.html`, `tests/golden/course-he.html`)
  must be regenerated via `P2C_UPDATE_GOLDEN=1 .venv/bin/pytest tests/test_build.py`
  once all CSS changes land, and the diff reviewed line-by-line before
  committing — both fixtures use `subject_domain: "systems"`, which maps to
  the `slate` theme, so both golden files will show the `slate` theme.css
  diff plus the shared `layout.css` diff (the CSS is inlined into every
  built course).
- Run the full suite (`.venv/bin/pytest tests/`) before each commit; only
  the golden-snapshot test is expected to fail until its final
  regeneration task.

---

### Task 1: Add system-font fallback tail to the `slate` theme

**Files:**
- Modify: `assets/themes/slate/theme.css:2-3`
- Test: `tests/test_assets.py`

**Interfaces:**
- Consumes: nothing new.
- Produces: nothing consumed by later tasks in this plan — each theme file
  is edited independently in its own task, and the shared test added here
  is extended (not replaced) by Tasks 2 and 3.

- [ ] **Step 1: Write the failing test**

Add this test to `tests/test_assets.py` (place it near
`test_themes_use_system_font_stacks_only`, around line 80):

```python
_MULTILINGUAL_FONT_TAIL = (
    "Noto Sans SC", "Noto Sans TC", "Noto Sans JP", "Noto Sans KR",
    "Noto Sans Devanagari", "Noto Naskh Arabic", "Noto Sans Hebrew",
)


@pytest.mark.parametrize("name", sorted(set(THEME_FOR_DOMAIN.values())))
def test_theme_fonts_include_a_multilingual_fallback_tail(name):
    """--font-mono stays Latin/ASCII-only (code is always English/symbols);
    --font-body/--font-heading gain a common tail of named system fonts so an
    unbounded target language (CJK, Devanagari, Arabic, Hebrew, ...) still
    renders with a matching system font instead of falling through to the
    browser's generic serif/sans-serif, which most OSes pair with a
    Latin-only face."""
    css = (ASSETS / "themes" / name / "theme.css").read_text()
    body_line = next(line for line in css.splitlines() if "--font-body:" in line)
    heading_line = next(line for line in css.splitlines() if "--font-heading:" in line)
    mono_line = next(line for line in css.splitlines() if "--font-mono:" in line)
    for font in _MULTILINGUAL_FONT_TAIL:
        assert font in body_line, f"{font} missing from {name} --font-body"
        assert font in heading_line, f"{font} missing from {name} --font-heading"
        assert font not in mono_line, f"{font} unexpectedly in {name} --font-mono"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_assets.py::test_theme_fonts_include_a_multilingual_fallback_tail -v`
Expected: FAIL for all three themes (`slate`, `parchment`, `clinical`) —
`StopIteration` or an assertion error, since none of the theme files
contain the new font names yet.

- [ ] **Step 3: Update `assets/themes/slate/theme.css`**

Change lines 2-3 from:

```css
  --font-heading: ui-sans-serif, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
  --font-body: ui-sans-serif, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
```

to:

```css
  --font-heading: ui-sans-serif, "Segoe UI", Roboto, Helvetica, Arial, "Noto Sans SC", "Noto Sans TC", "Noto Sans JP", "Noto Sans KR", "Noto Sans Devanagari", "Noto Naskh Arabic", "Noto Sans Hebrew", sans-serif;
  --font-body: ui-sans-serif, "Segoe UI", Roboto, Helvetica, Arial, "Noto Sans SC", "Noto Sans TC", "Noto Sans JP", "Noto Sans KR", "Noto Sans Devanagari", "Noto Naskh Arabic", "Noto Sans Hebrew", sans-serif;
```

Line 4 (`--font-mono`) is unchanged.

- [ ] **Step 4: Run test to verify the `slate` case passes**

Run: `.venv/bin/pytest tests/test_assets.py::test_theme_fonts_include_a_multilingual_fallback_tail -v`
Expected: the `slate` parametrization passes; `parchment` and `clinical`
still fail (they're done in Tasks 2 and 3).

- [ ] **Step 5: Run the full test suite**

Run: `.venv/bin/pytest tests/ -v`
Expected: only the two not-yet-done font-tail parametrizations
(`parchment`, `clinical`) fail. No other test regresses.

- [ ] **Step 6: Commit**

```bash
git add assets/themes/slate/theme.css tests/test_assets.py
git commit -m "feat: add multilingual system-font fallbacks to the slate theme"
```

---

### Task 2: Add system-font fallback tail to the `parchment` theme

**Files:**
- Modify: `assets/themes/parchment/theme.css:2-3`

**Interfaces:**
- Consumes: `_MULTILINGUAL_FONT_TAIL` and
  `test_theme_fonts_include_a_multilingual_fallback_tail` from Task 1
  (already parametrized over every theme — no test changes needed in this
  task, only the CSS fix that makes the existing `parchment` case pass).
- Produces: nothing new.

- [ ] **Step 1: Confirm the `parchment` case currently fails**

Run: `.venv/bin/pytest "tests/test_assets.py::test_theme_fonts_include_a_multilingual_fallback_tail[parchment]" -v`
Expected: FAIL (same reason as Task 1 Step 2 — the fonts aren't in the CSS
yet).

- [ ] **Step 2: Update `assets/themes/parchment/theme.css`**

Change lines 2-3 from:

```css
  --font-heading: ui-serif, Georgia, "Iowan Old Style", "Times New Roman", serif;
  --font-body: ui-serif, Georgia, "Iowan Old Style", "Times New Roman", serif;
```

to:

```css
  --font-heading: ui-serif, Georgia, "Iowan Old Style", "Times New Roman", "Noto Sans SC", "Noto Sans TC", "Noto Sans JP", "Noto Sans KR", "Noto Sans Devanagari", "Noto Naskh Arabic", "Noto Sans Hebrew", serif;
  --font-body: ui-serif, Georgia, "Iowan Old Style", "Times New Roman", "Noto Sans SC", "Noto Sans TC", "Noto Sans JP", "Noto Sans KR", "Noto Sans Devanagari", "Noto Naskh Arabic", "Noto Sans Hebrew", serif;
```

Line 4 (`--font-mono`) is unchanged. (`parchment`'s existing serif fonts —
`ui-serif`, `Georgia`, `"Iowan Old Style"`, `"Times New Roman"` — stay first;
the multilingual tail is appended after them, same as `slate`'s sans-serif
fonts stayed first in Task 1.)

- [ ] **Step 3: Run test to verify the `parchment` case passes**

Run: `.venv/bin/pytest "tests/test_assets.py::test_theme_fonts_include_a_multilingual_fallback_tail[parchment]" -v`
Expected: PASS.

- [ ] **Step 4: Run the full test suite**

Run: `.venv/bin/pytest tests/ -v`
Expected: only the `clinical` font-tail parametrization still fails (done
in Task 3). No other test regresses.

- [ ] **Step 5: Commit**

```bash
git add assets/themes/parchment/theme.css
git commit -m "feat: add multilingual system-font fallbacks to the parchment theme"
```

---

### Task 3: Add system-font fallback tail to the `clinical` theme

**Files:**
- Modify: `assets/themes/clinical/theme.css:2-3`

**Interfaces:**
- Consumes: same test from Task 1, `clinical` parametrization.
- Produces: nothing new.

- [ ] **Step 1: Confirm the `clinical` case currently fails**

Run: `.venv/bin/pytest "tests/test_assets.py::test_theme_fonts_include_a_multilingual_fallback_tail[clinical]" -v`
Expected: FAIL.

- [ ] **Step 2: Update `assets/themes/clinical/theme.css`**

Change lines 2-3 from:

```css
  --font-heading: ui-sans-serif, "Helvetica Neue", Helvetica, Arial, sans-serif;
  --font-body: ui-sans-serif, "Helvetica Neue", Helvetica, Arial, sans-serif;
```

to:

```css
  --font-heading: ui-sans-serif, "Helvetica Neue", Helvetica, Arial, "Noto Sans SC", "Noto Sans TC", "Noto Sans JP", "Noto Sans KR", "Noto Sans Devanagari", "Noto Naskh Arabic", "Noto Sans Hebrew", sans-serif;
  --font-body: ui-sans-serif, "Helvetica Neue", Helvetica, Arial, "Noto Sans SC", "Noto Sans TC", "Noto Sans JP", "Noto Sans KR", "Noto Sans Devanagari", "Noto Naskh Arabic", "Noto Sans Hebrew", sans-serif;
```

Line 4 (`--font-mono`) is unchanged.

- [ ] **Step 3: Run test to verify the `clinical` case passes**

Run: `.venv/bin/pytest "tests/test_assets.py::test_theme_fonts_include_a_multilingual_fallback_tail[clinical]" -v`
Expected: PASS.

- [ ] **Step 4: Run the full test suite**

Run: `.venv/bin/pytest tests/ -v`
Expected: all three font-tail parametrizations pass. No other test
regresses (golden-snapshot test is expected to still be passing at this
point — the CSS changes so far are in `theme.css`, but the golden fixtures'
inlined CSS comes from the actual built output, so this will in fact now
be failing; see the note in Task 5 Step 1 for confirmation of exactly when
it starts failing).

- [ ] **Step 5: Commit**

```bash
git add assets/themes/clinical/theme.css
git commit -m "feat: add multilingual system-font fallbacks to the clinical theme"
```

---

### Task 4: CJK-safe wrapping on fixed-width containers

**Files:**
- Modify: `assets/base/layout.css:82` (`.sidebar__title`), `:94`
  (`.toc__topics`), `:134-147` (`.term__def`), `:157-162` (`.quiz__option`)
- Test: `tests/test_assets.py`

**Interfaces:**
- Consumes: nothing from Tasks 1-3 (this task is independent CSS in a
  different file).
- Produces: nothing consumed by later tasks.

- [ ] **Step 1: Write the failing test**

Add this test to `tests/test_assets.py` (place it near
`test_term_def_popup_has_a_minimum_width`, around line 209):

```python
def test_fixed_width_containers_wrap_cjk_text_safely():
    """CJK scripts have no inter-word spaces, so default line-breaking can
    let a long unbroken run of characters overflow a fixed-width container
    instead of wrapping. overflow-wrap: anywhere wraps at word boundaries
    when they exist (Latin text is unaffected) and falls back to breaking
    anywhere when they don't (CJK), so these four containers -- the
    glossary popup, quiz options, sidebar title, and TOC topic entries --
    stay inside their bounds regardless of script."""
    css = (ASSETS / "base" / "layout.css").read_text()
    for selector in (".term__def", ".quiz__option", ".sidebar__title", ".toc__topics"):
        start = css.index(f"{selector} {{")
        end = css.index("}", start)
        block = css[start:end]
        assert "overflow-wrap: anywhere" in block, selector
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_assets.py::test_fixed_width_containers_wrap_cjk_text_safely -v`
Expected: FAIL — `overflow-wrap: anywhere` is not present in any of the
four selector blocks yet.

- [ ] **Step 3: Update `assets/base/layout.css`**

Change line 82 (`.sidebar__title`) from:

```css
.sidebar__title { margin: var(--space-1) 0 var(--space-4); font-family: var(--font-heading); font-weight: 600; }
```

to:

```css
.sidebar__title { margin: var(--space-1) 0 var(--space-4); font-family: var(--font-heading); font-weight: 600; overflow-wrap: anywhere; }
```

Change line 94 (`.toc__topics`) from:

```css
.toc__topics { margin-block: var(--space-1) var(--space-4); margin-inline: var(--space-3) 0; }
```

to:

```css
.toc__topics { margin-block: var(--space-1) var(--space-4); margin-inline: var(--space-3) 0; overflow-wrap: anywhere; }
```

Change the `.term__def` block (lines 134-147) from:

```css
.term__def {
  display: block;
  position: absolute;
  top: 100%;
  inset-inline-start: 0;
  z-index: var(--z-popover);
  margin-block-start: var(--space-2);
  padding: var(--space-3);
  min-inline-size: min(16rem, calc(100vw - 2 * var(--space-4)));
  max-inline-size: min(24rem, calc(100vw - 2 * var(--space-4)));
  border: 1px solid var(--color-border); border-inline-start: 3px solid var(--color-accent);
  border-radius: var(--radius); background: var(--color-surface);
  font-size: 0.92rem; color: var(--color-fg);
}
```

to:

```css
.term__def {
  display: block;
  position: absolute;
  top: 100%;
  inset-inline-start: 0;
  z-index: var(--z-popover);
  margin-block-start: var(--space-2);
  padding: var(--space-3);
  min-inline-size: min(16rem, calc(100vw - 2 * var(--space-4)));
  max-inline-size: min(24rem, calc(100vw - 2 * var(--space-4)));
  border: 1px solid var(--color-border); border-inline-start: 3px solid var(--color-accent);
  border-radius: var(--radius); background: var(--color-surface);
  font-size: 0.92rem; color: var(--color-fg);
  overflow-wrap: anywhere;
}
```

Change the `.quiz__option` block (lines 157-162) from:

```css
.quiz__option {
  font: inherit; text-align: start; width: 100%; cursor: pointer;
  padding: var(--space-3) var(--space-4);
  background: var(--color-bg); color: var(--color-fg);
  border: 1px solid var(--color-border); border-radius: var(--radius);
}
```

to:

```css
.quiz__option {
  font: inherit; text-align: start; width: 100%; cursor: pointer;
  padding: var(--space-3) var(--space-4);
  background: var(--color-bg); color: var(--color-fg);
  border: 1px solid var(--color-border); border-radius: var(--radius);
  overflow-wrap: anywhere;
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/test_assets.py::test_fixed_width_containers_wrap_cjk_text_safely -v`
Expected: PASS.

- [ ] **Step 5: Run the full test suite**

Run: `.venv/bin/pytest tests/ -v`
Expected: every test passes except the golden-snapshot test in
`tests/test_build.py` (`test_matches_the_golden_snapshot` or equivalent),
which is now expected to fail because `layout.css`/`theme.css` are inlined
into every built course and the golden files haven't been regenerated yet.
Confirm the failure is specifically the golden-snapshot comparison and
nothing else — if any other test fails, stop and investigate before
proceeding to Task 5.

- [ ] **Step 6: Commit**

```bash
git add assets/base/layout.css tests/test_assets.py
git commit -m "feat: wrap CJK text safely in glossary, quiz, sidebar, and TOC containers"
```

---

### Task 5: Regenerate and review golden snapshots

**Files:**
- Modify: `tests/golden/course.html`, `tests/golden/course-he.html`
  (regenerated, not hand-edited)

**Interfaces:**
- Consumes: the CSS changes from Tasks 1-4 (all must be committed first —
  this task assumes a clean tree with every CSS change already in place).
- Produces: nothing consumed by later tasks (this is the final task).

- [ ] **Step 1: Confirm the golden-snapshot test currently fails**

Run: `.venv/bin/pytest tests/test_build.py -v`
Expected: the golden-snapshot comparison test fails (as predicted in Task 4
Step 5) with a diff showing the new font names in `--font-body`/
`--font-heading` and the new `overflow-wrap: anywhere` declarations,
embedded in the inlined `<style>` block of both `course.html` and
`course-he.html`'s built output. No other test fails.

- [ ] **Step 2: Regenerate the golden snapshots**

Run: `P2C_UPDATE_GOLDEN=1 .venv/bin/pytest tests/test_build.py -v`
Expected: all tests pass; `tests/golden/course.html` and
`tests/golden/course-he.html` are rewritten in place.

- [ ] **Step 3: Review the diff line-by-line**

Run: `git diff tests/golden/course.html tests/golden/course-he.html`

Confirm, for **both** files:
- The `--font-body`/`--font-heading` lines inside the inlined `<style>`
  block now contain the seven new font names from Tasks 1-3, in the same
  position (appended after the existing Latin fonts, before the final
  generic `sans-serif`/`serif`) — both fixtures use `subject_domain:
  "systems"`, which maps to the `slate` theme, so the diff should exactly
  match `slate`'s Task 1 edit in both files.
- `--font-mono` is byte-for-byte unchanged.
- `overflow-wrap: anywhere;` now appears in the `.term__def`, `.quiz__option`,
  `.sidebar__title`, and `.toc__topics` rules inside the inlined stylesheet,
  and nowhere else changed.
- No other line differs — if anything outside the font-stack/overflow-wrap
  lines changed, stop and investigate before continuing; that would
  indicate an unrelated regression, not this plan's intended change.

- [ ] **Step 4: Run the full test suite**

Run: `.venv/bin/pytest tests/ -v`
Expected: every test passes, including the now-regenerated golden-snapshot
comparison.

- [ ] **Step 5: Commit**

```bash
git add tests/golden/course.html tests/golden/course-he.html
git commit -m "test: regenerate golden snapshots for multilingual font/wrap CSS"
```

---

## Out of scope (carried from the design spec)

- Non-slide source formats (`.docx`/`.txt`/`.md` input) — separate plan.
- The caching design (cross-run cache, shared source cache) — separate
  plan/spec entirely.
- Any change to `RTL_LANGUAGES`/`is_rtl()`, or a fixed target-language
  allowlist.
- Bundled webfonts or any conditional/script-detection-based asset loading.
- CJK-aware resizing of animate-pattern label chips
  (`_STATE_LABEL_CHAR_WIDTH` in `scripts/p2c/mdrender.py`) — deferred until
  a real generated CJK course demonstrates an actual overflow.
- Any change to `references/agents/*.md` — no agent prompt needs to know
  about this change.
