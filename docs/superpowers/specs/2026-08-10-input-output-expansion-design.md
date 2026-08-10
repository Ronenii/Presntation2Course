# v1.3.0 — Input/output expansion (languages + non-slide sources) — Design

**Date:** 2026-08-10
**Status:** Approved

## Context

Two of the three features deferred from the v1.3.0-bugfixes batch (shipped as
v1.2.4) are grouped here because both are, at root, "accept more kinds of
input / produce more kinds of output" — extending what the pipeline can
render and what it can read, without touching the pipeline's shape.

1. **More source/target languages.** Today's only language-specific
   mechanism is `theme.is_rtl()` — a single boolean driving text direction.
   `outline.py`'s validator already accepts any bare two-letter ISO 639-1
   code with no allowlist, so Chinese (`zh`), Hindi (`hi`), etc. already pass
   validation and already flow through the summarizer/researcher/writer
   agents (which read pages visually and write prose in whatever language
   they're told — nothing language-specific in those prompts). The actual
   gap is purely in **rendering**: every theme's font stack
   (`--font-body`/`--font-heading`/`--font-mono`) lists only Latin-script
   fonts, and no CSS anywhere accounts for scripts with no inter-word
   spacing (CJK).
2. **Non-slide sources.** `normalize` (Phase 0) only accepts `.pdf`/`.pptx`,
   and the summarizer reads pages **visually, in batches of 20 images** —
   deliberately never by text extraction, so a diagram or table is never
   silently dropped. An article, essay, or research paper has no "slides,"
   but it does have pages, so the fix is to make more input formats
   *become* a PDF of pages, not to change how those pages get read.

Scope for this pass, per discussion: language support is **broad/unbounded**
(any language the user names, not a fixed target list), covering both source
deck language and output language (output matters more, since the
vision-based agents are already largely source-language-agnostic). Font
handling is **system-font fallbacks only** — no bundled webfonts, keeping
every course self-contained with zero added asset weight. Non-slide sources
extend to `.docx` (via the existing LibreOffice conversion path) and plain
`.txt`/`.md` (via a new render-to-PDF step). The summarizer stays completely
source-format-agnostic — no branch, no hint, no different instructions for
"this came from a paper" vs. "this came from a deck."

## Feature A: multi-language rendering

**No changes to `theme.py`'s direction logic, `outline.py`'s validation, or
any agent prompt.** This is additive CSS only.

### Font stacks

Every theme's `--font-body`/`--font-heading` gains a common tail of named
system-font fallbacks after its existing Latin-script fonts, covering the
major non-Latin script families likely to appear given an unbounded language
list:

```css
--font-body: ui-sans-serif, "Segoe UI", Roboto, Helvetica, Arial,
  "Noto Sans SC", "Noto Sans TC", "Noto Sans JP", "Noto Sans KR",
  "Noto Sans Devanagari", "Noto Naskh Arabic", "Noto Sans Hebrew",
  sans-serif;
```

The same tail is appended to all three themes' `--font-heading`/
`--font-body` (parchment's serif stack keeps its own serif fonts first, same
tail appended after). `--font-mono` is left untouched — code blocks are
always Latin/ASCII by nature (identifiers, syntax), regardless of course
language.

These are **fallback names only**: if the reader's OS has a matching font
installed, it renders correctly; if not, the browser falls through to the
final generic (`sans-serif`/`serif`), same as today. No asset is bundled, no
network request is made, nothing changes about the "self-contained HTML"
guarantee.

### CJK-safe wrapping

CJK scripts have no inter-word spaces, so default line-breaking can produce
either no wrapping at all (a huge glossary term overflowing its popup) or,
conversely, awkward breaks if a rule written for Latin text (e.g.
`overflow-wrap: normal` relying on spaces) is applied blindly. Add
`overflow-wrap: anywhere` (a safe superset that wraps at word boundaries when
they exist and falls back to breaking anywhere when they don't — correct for
both Latin and CJK) to the same fixed-width containers RTL work already
touched:

- `.term__def` (glossary popup — already has `min-inline-size` from the
  v1.2.4 fix; this closes the other direction, overflow, without re-opening
  that fix)
- `.quiz__option` / quiz option list items
- `.sidebar__title`, `.toc__topics` entries

No change to `.anim__state-transition-label`/other animate-pattern text —
those already size their background chip from the actual rendered text
length (`_STATE_LABEL_CHAR_WIDTH`), so they're not at risk of overflow the
same way, and reworking their sizing math for multi-byte character widths is
real, separate scope, deferred until a real generated CJK course exhibits an
actual problem there (same "fix real bugs from a real course, not
speculative ones" discipline as the v1.2.4 batch).

## Feature B: non-slide sources

### `normalize` accepts two new extensions

**`.docx`** — identical code path to `.pptx` today: `_convert_pptx`'s
`soffice --headless --convert-to pdf` mechanism is generalized (renamed, not
duplicated) to accept any LibreOffice-convertible input extension. Same
`SofficeMissing`/exit-4 failure mode, same install-hint message, no new exit
code.

**`.txt`/`.md`** — no native page layout, so `normalize` renders one first:

1. Read the file as UTF-8 text.
2. If `.md`, render to HTML via the `markdown` library `mdrender.py` already
   depends on (plain rendering — no course-specific extensions, no
   `animate`/`quiz`/`glossary` fence handling, since this is a generic
   external document, not course-authored markdown).
3. Wrap the HTML in a minimal standalone template (no course CSS/JS — just
   body text at a readable size/line-length, so the summarizer's visual
   reading sees normal paginated prose, not a wall of unstyled text).
4. Print to PDF via the same Chromium/`print-to-pdf` mechanism
   `p2c.exportpdf` already uses for course output.
5. Feed the resulting PDF through the same page-counting path every other
   normalized PDF already goes through.

### New failure mode

Chromium is currently a **soft** dependency — `export-pdf` skips cleanly
(exit 6) if it's absent, and the HTML course still ships with a working
in-page print button. For `.txt`/`.md` *input*, Chromium is the only way to
produce the page images the vision-based summarizer needs, so its absence
must be a **hard fail** for this input type specifically — the run cannot
proceed without page images to read. New exit code (**exit 7**,
`ChromiumMissing`), reusing the existing "print the install hint" pattern
(exit 4's `INSTALL_HINT` message, adapted for Chromium). This does not change
the *existing* exit-6 soft-skip behavior for PDF export — the two are
unrelated dependencies at unrelated phases, and a run with `.pdf`/`.pptx`/
`.docx` input is completely unaffected either way.

### Summarizer, researcher, writer: unchanged

All three stay exactly as they are. The summarizer reads whatever page
images `normalize` produced, the same way regardless of whether the source
was a deck or a converted paper — no source-type signal is threaded through,
per the decision to keep it fully source-agnostic. Topic/module segmentation
for a long prose document is left to the summarizer's own judgment (it
already infers topic boundaries within a single slide today; a
heading-less essay is the same kind of inference, just over more pages). The
existing `planned_agent_count` report (already printed before Phase 2 spends
anything) is the only guard against a runaway or badly uneven segmentation —
no new validation code, since that gate already exists for exactly this
purpose and already requires the orchestrator to look before it dispatches.

## Testing

- `test_normalize.py`: new cases for `.docx` conversion (mocking `soffice`,
  same style as existing PPTX tests) and `.txt`/`.md` → PDF rendering (real
  Chromium if available in the test environment, `pytest.mark.skipif`
  otherwise — matching the project's existing skip pattern for
  Chromium/soffice-dependent tests). A case asserting exit 7 when Chromium is
  absent and input is `.txt`/`.md`, and a case confirming exit 6's existing
  PDF-export behavior is unchanged.
- New CSS assertions (in whichever test file already checks theme token
  presence) for the font-stack fallback tail and the new `overflow-wrap`
  rules on the three containers listed above.
- `tests/fixtures/`: a small `.md` source fixture (a short multi-heading
  document) exercised through `test_build.py`, producing a normal course
  build — this is the first fixture in the suite whose *input* is not a
  deck, so it's worth keeping deliberately small and separate rather than
  folding into the existing mini-course PDF fixture.
- Golden snapshots: no expected change to `course.html`/`course-he.html`
  (this feature touches `normalize` and theme CSS, not `mdrender.py`'s
  output shape) — but regenerate and review per standing project discipline
  if the CSS diff actually lands inside a golden-covered file
  (`assets/base/layout.css` is inlined into every built course).

## Out of scope

- The caching/token-cost feature — separate design (see companion spec,
  same date).
- A fixed target-language allowlist, RTL-language-list expansion, or any
  change to `RTL_LANGUAGES`/`is_rtl()` — direction logic is unaffected;
  this is purely about non-RTL script rendering.
- Bundled webfonts, script detection from `language.code`, or any
  conditional asset-loading mechanism — explicitly rejected in favor of
  system-font fallbacks, per the "self-contained, no added weight"
  decision.
- A source-type signal/hint threaded into the summarizer's prompt —
  explicitly rejected; it stays source-agnostic.
- A structural (heading-based) segmentation mode for prose sources, or any
  new outline-validation code bounding topic/module count — the existing
  `planned_agent_count` gate is judged sufficient; a code-level bound can be
  revisited if a real run demonstrates it isn't.
- CJK-aware resizing of animate-pattern label chips (`_STATE_LABEL_CHAR_WIDTH`
  and friends) — deferred until a real generated course shows an actual
  overflow, per the project's "real bugs, not speculative ones" discipline.
- `.doc`/`.rtf`/`.odt`/other legacy formats — not requested; `.docx` was the
  only additional office format named.
