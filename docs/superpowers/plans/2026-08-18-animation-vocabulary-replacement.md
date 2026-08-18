# Animation Vocabulary Replacement Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace P2C's animation vocabulary with a domain-general set of eight patterns, redesigning the two weakest renderers and deleting the two that only fit computer science.

**Architecture:** `parse_animate` in `scripts/p2c/mdrender.py` keeps its key/list-section design. `array-ops` and `path-trace` are removed entirely (parser branches, renderers, CSS, tests, fixtures). `state-machine` and `transform` are re-rendered from scratch against a new visual direction. Three new patterns (`build-up`, `compare`, `split-merge`) are added. A shared contrast rule fixes a real, shipped accessibility defect affecting every accent-filled box.

**Tech Stack:** Python 3 (stdlib only), pytest, anime.js v4 (vendored), CSS custom properties.

**Reference:** the approved visual direction is the published artifact
`https://claude.ai/code/artifact/45599c46-3d4f-449a-87aa-202e6e070a4b`. Its
motion, geometry, and timing are the spec for Tasks 3–7.

## Global Constraints

- **Baseline:** `main` at `c8f3d8d` (PR #12, released as `v1.3.1`), suite `573 passed, 4 skipped`. Work happens on `feature/animation-vocabulary-replacement`.
- **`array-ops` and `path-trace` shipped in `v1.3.1`, so removing them is a user-facing breaking change.** This is accepted deliberately: the patterns never worked well. Remove them outright — no deprecation shim, no compatibility alias, no migration warning.
- **Interpreter:** `/home/roneng/Presntation2Course/.venv/bin/python`. `python` is NOT on PATH.
- **Final vocabulary is exactly eight patterns:** `state-machine`, `state-toggle`, `pipeline`, `layer-stack`, `transform`, `build-up`, `compare`, `split-merge`. No others parse.
- **New layout constants divisible by 4.** Derived values (baselines, centres, midpoints) exempt.
- **`dir="ltr"` on every SVG root** so RTL/Hebrew courses keep left-to-right geometry.
- **No shadows. Border radius ≤10px.**
- **Text on a solid-accent fill MUST use `--color-accent-contrast`.** Measured on the slate palette: `--color-muted` on accent scores **1.21:1** (light) and **1.04:1** (dark) — invisible. `--color-fg` scores 3.33:1 / 2.00:1 — also failing. `--color-accent-contrast` scores 4.86:1 / 7.97:1. A faint accent wash (`fill-opacity` .12 light / .18 dark) measures 4.99:1 / 4.74:1 and needs no inversion.
- **SVG paint order is document order — there is no `z-index`.** Emit `connectors → travelling marker → boxes → labels`, so a marker passes *behind* cards while authored labels stay legible on top.
- **anime.js gotchas** (`.claude/skills/animejs/references/api-reference.md`):
  1. Base positions live in plain attributes (`x`/`y`/`cx`/`cy`), never `transform="translate(...)"`.
  2. Every looping timeline ends with `{"kind": "set", ...}` steps resetting **every** animated property, or values compound across laps.
- **Run the full suite before every commit:** `/home/roneng/Presntation2Course/.venv/bin/python -m pytest tests/`

---

## File Structure

| File | Responsibility | Tasks |
|---|---|---|
| `scripts/p2c/mdrender.py` | Parser branches, renderers, geometry constants | 1–7 |
| `assets/base/layout.css` | Tokens, presentation, reduced-motion reveals | 1, 3–8 |
| `assets/print.css` | Print static fallbacks | 1, 8 |
| `tests/fixtures/mini-course/`, `mini-course-he/` | Course fixtures using removed patterns | 1 |
| `references/quiz-format.md`, `references/agents/course-writer.md` | Author-facing grammar and selection rules | 9 |
| `tests/golden/course.html`, `course-he.html` | Regenerated, never hand-edited | 1, 8 |

---

### Task 1: Remove `array-ops` and `path-trace`

**Files:**
- Modify: `scripts/p2c/mdrender.py` (whitelist, two parse branches, `_animate_html` dispatch, `_array_ops_html` ~164 lines, `_path_trace_html` ~248 lines, their geometry constants)
- Modify: `assets/base/layout.css`, `assets/print.css` (their tokens, rules, reduced-motion/print blocks)
- Modify: `tests/fixtures/mini-course/modules/01-virtual-memory.md:24`, `02-scheduling.md:30`, `tests/fixtures/mini-course-he/modules/01-section.md:31,78`
- Modify: `tests/test_mdrender.py` (41 `array-ops` refs, 25 `path-trace` refs), `tests/test_validate.py`, `tests/test_build.py`
- Regenerate: `tests/golden/course.html`, `course-he.html` (39 references each)

**Interfaces:**
- Consumes: nothing.
- Produces: a five-pattern whitelist (`state-machine`, `state-toggle`, `pipeline`, `layer-stack`, `transform`). Tasks 5–7 extend it back to eight.

**Why these two go:** both are CS-theory-only. They occupy 2 of 7 vocabulary slots for a
tool that generates courses in maths, philosophy, language, and cinema, and a writer with
no fitting pattern falls back to mermaid — the exact failure that produced a 55-topic
course with zero animations.

**This is a breaking change.** Any existing course markdown using these patterns will fail
to build. That is accepted: the alternative is carrying dead vocabulary forever.

- [ ] **Step 1: Write the failing test**

In `tests/test_mdrender.py`:

```python
def test_removed_patterns_are_rejected():
    for pattern in ("array-ops", "path-trace"):
        with pytest.raises(AnimateError, match="animate pattern must be"):
            parse_animate(f"pattern: {pattern}\narray:\n  - 1\n  - 2\nops:\n  - swap 0 1\n")
```

- [ ] **Step 2: Run it to confirm it fails**

Run: `/home/roneng/Presntation2Course/.venv/bin/python -m pytest tests/test_mdrender.py -k removed_patterns -v`
Expected: FAIL — `array-ops` currently parses, so no exception is raised.

- [ ] **Step 3: Remove both patterns**

1. Drop `"array-ops"` and `"path-trace"` from the whitelist tuple in `parse_animate`, and update its error message to name the five remaining patterns.
2. Delete the `elif pattern == "array-ops":` branch and the `else:  # path-trace` branch. The final `else` must now raise for any unrecognised pattern rather than falling through to `path-trace`.
3. Delete `_array_ops_html` and `_path_trace_html` entirely, plus their dispatch lines in `_animate_html`.
4. Delete their geometry constants: `_BAR_WIDTH`, `_BAR_GAP`, `_BAR_MAX_HEIGHT`, `_BAR_HEADROOM`, `_BAR_BASELINE_Y`, `_PATH_PADDING`, `_PATH_MS_PER_UNIT`, `_PATH_MIN_SEGMENT_MS`, `_ARRAY_VERB_LABEL`, and the `_ARRAY_OP` regex.
5. Remove `array`, `ops`, `points` from `_LIST_HEADERS` and the `lists` dict, and their `_raw` accumulators. Remove `array`, `ops`, `points` fields from the `Animate` dataclass.
6. Every remaining pattern's guard clause names the keys it rejects — remove `array`/`ops`/`points` from those messages so they stay accurate.
7. Delete the `.anim--array-ops` / `.anim--path-trace` rules, their `--anim-array-*` tokens, and their reduced-motion and print blocks from `assets/base/layout.css` and `assets/print.css`.

- [ ] **Step 4: Rewrite the four fixtures**

Each fixture's `animate` block must be replaced with a pattern that survives, keeping the
topic's meaning intact. The Hebrew fixture is the RTL regression guard — it must keep an
`animate` block, not lose one.

`tests/fixtures/mini-course/modules/01-virtual-memory.md:24` — replace the `path-trace`:

```
```animate
pattern: transform
from: A virtual address
to: A physical address
steps:
  - Split into page number and offset
  - Look the page number up in the TLB
```
```

`tests/fixtures/mini-course/modules/02-scheduling.md:30` — replace the `array-ops`:

```
```animate
pattern: compare
left: First-come, first-served
right: Round robin
steps:
  - A long job blocks everything behind it | Each job gets a fixed slice
  - Short jobs wait for the whole queue | Short jobs finish early
```
```

`tests/fixtures/mini-course-he/modules/01-section.md:31` — replace the `path-trace`,
keeping the Hebrew:

```
```animate
pattern: build-up
whole: היררכיית הזיכרון
parts:
  - אוגרים: הגישה המהירה ביותר
  - מטמון: מאוזן בין מהירות לגודל
  - זיכרון ראשי: איטי אבל גדול
```
```

`tests/fixtures/mini-course-he/modules/01-section.md:78` — replace the `array-ops`:

```
```animate
pattern: split-merge
source: בקשת קלט/פלט
branches:
  - נתיב מהיר: הנתון כבר במטמון
  - נתיב איטי: קריאה מהדיסק
merged: הנתון מוחזר לתהליך
```
```

Note these fixtures use patterns built in Tasks 5–7. **Sequencing:** do Task 1's code
removal now, but land the fixture rewrites in the task that introduces the pattern each
one needs (`compare` → Task 6, `build-up` → Task 5, `split-merge` → Task 7). Until then,
use a surviving pattern as a temporary stand-in so the suite stays green.

⚠️ **Do NOT mark the stand-ins with a `TODO` comment in the fixture markdown.** Validator
rule 7 scans the rendered body for `\bTODO\b` and raises a blocking `placeholder` finding,
so an HTML comment inside a fixture fails the build. Track the stand-ins here instead:

| Fixture | Stand-in used | Becomes | Task |
|---|---|---|---|
| `mini-course/modules/02-scheduling.md` | `state-toggle` | `compare` | 6 |
| `mini-course-he/modules/01-section.md` (first) | `state-toggle` | `build-up` | 5 |
| `mini-course-he/modules/01-section.md` (second) | `pipeline` | `split-merge` | 7 |

**Task 7 must verify all three are resolved** by checking this table against the fixtures,
since there is no in-tree marker to grep for.

- [ ] **Step 5: Update every affected test**

Delete the `array-ops` and `path-trace` parser/renderer tests (66 references). Any test
asserting the whitelist message must expect the new five-pattern wording.

- [ ] **Step 6: Run the suite and regenerate goldens**

Run: `/home/roneng/Presntation2Course/.venv/bin/python -m pytest tests/`
The goldens will differ (39 references each). Inspect the diff first and confirm it only
removes the deleted patterns' markup, then regenerate:
`P2C_UPDATE_GOLDEN=1 /home/roneng/Presntation2Course/.venv/bin/python -m pytest tests/test_build.py -k golden -q`

- [ ] **Step 7: Commit**

```bash
git add -A
git commit -m "refactor: remove the array-ops and path-trace animate patterns"
```

---

### Task 2: Shared contrast rule for accent-filled boxes

**Files:**
- Modify: `assets/base/layout.css`
- Test: `tests/test_assets.py`

**Interfaces:**
- Consumes: nothing.
- Produces: the convention every later task follows — text on a solid-accent fill uses `--color-accent-contrast`.

**This fixes a real, shipped defect.** `.anim__state-box text` is `--color-fg` on a rect
that animates to `--color-accent`: **3.33:1** in light, **2.00:1** in dark, both below the
4.5:1 floor for body text. The label is briefly unreadable every time a state activates.
Nobody reported it because the flash is short, but it is the same defect the review found
in the artifact.

- [ ] **Step 1: Write the failing test**

```python
def test_text_on_accent_fill_uses_the_contrast_token():
    css = (ASSETS / "base" / "layout.css").read_text(encoding="utf-8")
    # Every rule that paints text sitting on a box the timeline fills with the
    # accent must name the contrast token; --color-fg on --color-accent measures
    # 3.33:1 (light) and 2.00:1 (dark), both below the 4.5:1 floor.
    assert "--color-accent-contrast" in css
    assert css.count("--color-accent-contrast") >= 3
```

- [ ] **Step 2: Run it to confirm it fails**

Run: `/home/roneng/Presntation2Course/.venv/bin/python -m pytest tests/test_assets.py -k contrast_token -v`
Expected: FAIL — the token appears twice today, both outside the animation rules.

- [ ] **Step 3: Add the shared rule**

```css
/* Text sitting on a box the timeline fills with --color-accent must invert to the
   accent's own contrast colour, in step with the fill. Measured on the slate
   palette: --color-muted on accent is 1.21:1 (light) / 1.04:1 (dark) and
   --color-fg is 3.33:1 / 2.00:1 -- both fail the 4.5:1 floor, and the muted case
   is effectively invisible. --color-accent-contrast scores 4.86:1 / 7.97:1.
   A box that settles to the faint accent wash instead measures 4.99:1 / 4.74:1
   and must NOT invert. */
.anim__text-on-accent { fill: var(--color-accent-contrast); }
```

Define the visited tint alongside the existing animation tokens. **Do not use
`color-mix`** — it appears nowhere in this codebase, the project sets no browser-target
config, and generated courses are standalone HTML a student may open in any browser. Use a
low-opacity accent over the surface instead, which is universally supported and matches how
the stylesheet already handles transparency:

```css
/* A visited state holds a faint accent wash rather than reverting to idle, so the
   path travelled so far stays readable. Kept light on purpose: measured at ~12%
   the label still scores about 5:1, whereas a solid accent fill drops --color-fg
   to 3.33:1 and forces the inversion rule above. */
.anim__visited { fill: var(--color-accent); fill-opacity: .12; }
```

and inside the dark-theme block, where the accent is lighter and needs slightly more
presence to read as "visited":

```css
  .anim__visited { fill-opacity: .18; }
```

Because this animates `fill-opacity` rather than `fill`, the timeline steps that mark a
state visited animate **`fillOpacity`**, and the trailing reset must restore it to `0`
(gotcha 2). Renderers must emit the base `fill="var(--color-accent)"` with
`fill-opacity="0"` so the box starts idle.

- [ ] **Step 4: Fix the shipped `state-machine` defect**

The existing renderer's box label must invert while its rect holds the accent. In
`_state_machine_html`'s timeline, every step that animates a rect's `fill` to
`var(--anim-state-current)` gains a paired step animating that box's `<text>` `fill` to
`var(--color-accent-contrast)`, and the trailing `{"kind": "set", ...}` reset restores it
to `var(--color-fg)` — otherwise the inverted colour compounds across laps (gotcha 2).

- [ ] **Step 5: Run the tests**

Run: `/home/roneng/Presntation2Course/.venv/bin/python -m pytest tests/`
Regenerate goldens if the CSS diff is clean.

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "fix: invert text on accent-filled boxes to meet contrast floor"
```

---

### Task 3: Redesign `state-machine` as a closed track

**Files:**
- Modify: `scripts/p2c/mdrender.py` (`_state_machine_html`, ~293 lines, rewritten), geometry constants
- Modify: `assets/base/layout.css`
- Test: `tests/test_mdrender.py`

**Interfaces:**
- Consumes: the contrast convention from Task 2.
- Produces: `_state_machine_html(anim, token) -> str`, unchanged signature. **The grammar does not change** — every existing `state-machine` block must still parse and render.

**What is wrong with the current one:** states sit in a straight horizontal row with fixed
130px boxes, so a 5-state chain runs ~1100px wide and its text shrinks to illegibility. A
cycle is bolted on as a special-cased arc above the row. Visited states flash to accent and
back to blank, so the path travelled so far is invisible. All transition labels are
permanently visible grey chips competing for attention.

**The redesign** (see the artifact):

1. **Nodes sit on a closed track** the marker rides — a cycle is then the natural shape, not an exception. For N states, place them at equal angles on a rounded path; the marker follows the path itself.
2. **Visited states hold the faint accent wash** (`.anim__visited`, a `fill-opacity` animation) rather than reverting to idle, so the path so far reads at a glance.
3. **Only the in-progress transition label is visible.** Each label shows during exactly its own segment of the lap and is hidden otherwise.
4. **Box width derives from its label's text length**, reusing `_STATE_LABEL_CHAR_WIDTH` and `_STATE_LABEL_CHIP_PAD_X`, so long state names are not clipped.
5. **Paint order: track → marker → boxes → labels.** The marker must pass *behind* each box.

**Label timing is the subtle part.** Each label's visible window must cover its own travel
segment and no other. With N transitions over one lap, transition `i` travels roughly
`(i/N)` to `((i+1)/N)` of the lap; its label shows across that window with a small lead-in
and lead-out, and is at `opacity: 0` for the rest. Getting this wrong produces labels that
blink out of phase — the exact bug caught in the artifact review.

- [ ] **Step 1: Write the failing tests**

```python
def _sm():
    return parse_animate(
        "pattern: state-machine\n"
        "states:\n  - Thesis\n  - Antithesis\n  - Synthesis\n"
        "transitions:\n"
        "  - Thesis -> Antithesis: provokes\n"
        "  - Antithesis -> Synthesis: resolves\n"
        "  - Synthesis -> Thesis: becomes the next thesis\n"
    )


def test_state_machine_paints_marker_behind_boxes():
    out = _state_machine_html(_sm(), "ANIMTOKEN1")
    svg = out[out.index("<svg"):out.index("</svg>")]
    marker = svg.index("anim__state-marker")
    first_box = svg.index("anim__state-rect")
    first_label = svg.index("anim__state-transition-label")
    # SVG has no z-index: document order is paint order.
    assert marker < first_box < first_label


def test_state_machine_box_width_grows_with_its_label():
    short = parse_animate(
        "pattern: state-machine\nstates:\n  - A\n  - B\n"
        "transitions:\n  - A -> B: x\n"
    )
    long = parse_animate(
        "pattern: state-machine\n"
        "states:\n  - A state with a considerably longer name\n  - B\n"
        "transitions:\n  - A state with a considerably longer name -> B: x\n"
    )
    import re
    def widest(html):
        return max(float(w) for w in re.findall(r'anim__state-rect[^>]*width="([\d.]+)"', html))
    assert widest(_state_machine_html(long, "ANIMTOKEN2")) > widest(
        _state_machine_html(short, "ANIMTOKEN3")
    )


def test_state_machine_visited_states_hold_their_tint():
    out = _state_machine_html(_sm(), "ANIMTOKEN1")
    data = json.loads(
        re.search(r'class="anim__timeline">(.*?)</script>', out, re.S).group(1)
    )
    assert any("fillOpacity" in str(k) for st in data["steps"]
               for k in (st.get("props") or {}))


def test_state_machine_label_windows_do_not_overlap():
    out = _state_machine_html(_sm(), "ANIMTOKEN1")
    data = json.loads(
        re.search(r'class="anim__timeline">(.*?)</script>', out, re.S).group(1)
    )
    # Each transition label must be hidden again before the next one shows,
    # or every passed label keeps blinking over the current one.
    shows = [s for s in data["steps"]
             if "opacity" in (s.get("props") or {}) and "label" in str(s.get("targets"))]
    assert len(shows) >= 2 * len(_sm().transitions)


def test_state_machine_resets_every_animated_property():
    out = _state_machine_html(_sm(), "ANIMTOKEN1")
    data = json.loads(
        re.search(r'class="anim__timeline">(.*?)</script>', out, re.S).group(1)
    )
    animated = {p for s in data["steps"] if s.get("kind") != "set"
                for p in (s.get("props") or {})}
    reset = {p for s in data["steps"] if s.get("kind") == "set"
             for p in (s.get("props") or {})}
    assert animated <= reset
```

- [ ] **Step 2: Run them to confirm they fail**

Run: `/home/roneng/Presntation2Course/.venv/bin/python -m pytest tests/test_mdrender.py -k state_machine -v`
Expected: the paint-order, width, and visited-tint tests FAIL against the current renderer.

- [ ] **Step 3: Rewrite `_state_machine_html`**

Follow the artifact's geometry. Emit, in this order: the track path, the marker group, one
`<g>` per state (opaque rect + centred label), then one `<g>` per transition label (opaque
chip + text). Compute box widths from text length. Build the timeline so each state takes
the accent as the marker arrives, holds a faint accent wash after, and each transition label
shows only across its own segment. End with `{"kind": "set", ...}` steps resetting fill,
opacity, and any offset back to baseline.

Keep every existing behaviour the grammar guarantees: at most one trailing back-edge, only
authored transitions drawn, `dir="ltr"` on the root, `html.escape` on all authored text.

- [ ] **Step 4: Run the tests**

Run: `/home/roneng/Presntation2Course/.venv/bin/python -m pytest tests/test_mdrender.py -k state_machine -v`
Expected: PASS, including every pre-existing `state-machine` test.

- [ ] **Step 5: Full suite and goldens**

Run: `/home/roneng/Presntation2Course/.venv/bin/python -m pytest tests/`
Regenerate goldens after inspecting the diff.

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "feat: redesign state-machine as a closed track with held state"
```

---

### Task 4: Redesign `transform` as an accumulating spine

**Files:**
- Modify: `scripts/p2c/mdrender.py` (`_transform_html`, ~126 lines, rewritten), `_XFORM_*` constants
- Modify: `assets/base/layout.css`
- Test: `tests/test_mdrender.py`

**Interfaces:**
- Consumes: Task 2's contrast convention.
- Produces: `_transform_html(anim, token) -> str`, unchanged signature and grammar.

**What is wrong with the current one:** the steps flash on and off **in the same position**
over a horizontal connector, so only one is ever visible. The sequence — which is the
entire teaching point — can never be seen. At the end the reader has watched three things
appear and vanish and cannot reconstruct the derivation.

**The redesign:** a vertical spine from the `from:` box to the `to:` box. Each step lands as
a **rung on that spine and stays**. When the animation ends the whole derivation is
readable at once. The `to:` box takes the accent only after every rung is present, and its
text inverts per Task 2.

- [ ] **Step 1: Write the failing tests**

```python
def _xf():
    return parse_animate(
        "pattern: transform\nfrom: Latin aqua\nto: French eau\n"
        "steps:\n  - Intervocalic weakening\n  - Loss of the final vowel\n  - Vowel fronting\n"
    )


def test_transform_steps_accumulate_rather_than_replace():
    out = _transform_html(_xf(), "ANIMTOKEN1")
    data = json.loads(
        re.search(r'class="anim__timeline">(.*?)</script>', out, re.S).group(1)
    )
    # No non-`set` step may animate a step group's opacity back DOWN to 0:
    # that is the "flash and vanish" behaviour this redesign removes.
    fades = [
        s for s in data["steps"]
        if s.get("kind") != "set"
        and "step" in str(s.get("targets"))
        and (s.get("props") or {}).get("opacity") == 0
    ]
    assert fades == []


def test_transform_every_step_has_its_own_position():
    out = _transform_html(_xf(), "ANIMTOKEN1")
    ys = re.findall(r'anim__xform-step[^>]*\bcy="([\d.]+)"', out)
    assert len(set(ys)) == 3, "each rung must sit at its own height on the spine"


def test_transform_result_text_inverts_on_accent():
    out = _transform_html(_xf(), "ANIMTOKEN1")
    data = json.loads(
        re.search(r'class="anim__timeline">(.*?)</script>', out, re.S).group(1)
    )
    inverts = [
        s for s in data["steps"]
        if "accent-contrast" in str((s.get("props") or {}).get("fill", ""))
    ]
    assert inverts, "the result box fills with accent, so its text must invert"


def test_transform_resets_every_animated_property():
    out = _transform_html(_xf(), "ANIMTOKEN1")
    data = json.loads(
        re.search(r'class="anim__timeline">(.*?)</script>', out, re.S).group(1)
    )
    animated = {p for s in data["steps"] if s.get("kind") != "set"
                for p in (s.get("props") or {})}
    reset = {p for s in data["steps"] if s.get("kind") == "set"
             for p in (s.get("props") or {})}
    assert animated <= reset
```

- [ ] **Step 2: Run to confirm failure**

Run: `/home/roneng/Presntation2Course/.venv/bin/python -m pytest tests/test_mdrender.py -k transform -v`
Expected: the accumulation and per-rung-position tests FAIL — today all steps share one position and each fades out.

- [ ] **Step 3: Rewrite `_transform_html`**

Vertical layout. Constants (all divisible by 4): `_XFORM_BOX_WIDTH = 200`,
`_XFORM_BOX_HEIGHT = 40`, `_XFORM_RUNG_GAP = 32`, `_XFORM_TOP_MARGIN = 12`. Height derives
from the step count, so 1 and 4 steps both fit. Box widths derive from text length.
Emit spine → endpoint boxes → rungs, each rung a dot on the spine plus left-aligned text.

- [ ] **Step 4: Run the tests**

Run: `/home/roneng/Presntation2Course/.venv/bin/python -m pytest tests/test_mdrender.py -k transform -v`

- [ ] **Step 5: Full suite and goldens**

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "feat: redesign transform as an accumulating spine"
```

---

### Task 5: Add `build-up`

**Files:**
- Modify: `scripts/p2c/mdrender.py` (parser branch, `_build_up_html`, constants, dispatch)
- Modify: `assets/base/layout.css`, `assets/print.css`
- Modify: `tests/fixtures/mini-course-he/modules/01-section.md` (replace the Task 1 stand-in)
- Test: `tests/test_mdrender.py`

**Interfaces:**
- Consumes: `_STAGE` regex, Task 2's tokens.
- Produces: `Animate.whole: str`, `Animate.parts: list[tuple[str, str]]`; `_build_up_html(anim, token) -> str`.

**Grammar:** required `whole:`; `parts:` 2–6 entries, each `<name>: <what it contributes>`.
Rejects every key it does not use, including `caption:`.

**Shape:** a whole assembling from its parts. Each part fades in, takes the accent briefly,
then **settles to the faint accent wash and stays**, so the structure accumulates.

- [ ] **Step 1: Write the failing tests**

```python
def test_build_up_parses_whole_and_parts():
    anim = parse_animate(
        "pattern: build-up\nwhole: A valid syllogism\n"
        "parts:\n  - Major premise: all men are mortal\n"
        "  - Minor premise: Socrates is a man\n"
        "  - Conclusion: Socrates is mortal\n"
    )
    assert anim.whole == "A valid syllogism"
    assert anim.parts[0] == ("Major premise", "all men are mortal")
    assert len(anim.parts) == 3


def test_build_up_rejects_bad_part_counts():
    with pytest.raises(AnimateError, match="at least 2 parts"):
        parse_animate("pattern: build-up\nwhole: W\nparts:\n  - Only: one\n")
    body = "pattern: build-up\nwhole: W\nparts:\n" + "".join(
        f"  - P{i}: does {i}\n" for i in range(7)
    )
    with pytest.raises(AnimateError, match="at most 6 parts"):
        parse_animate(body)


def test_build_up_requires_whole():
    with pytest.raises(AnimateError, match="needs 'whole:'"):
        parse_animate("pattern: build-up\nparts:\n  - A: a\n  - B: b\n")


def test_build_up_rejects_keys_it_does_not_use():
    for stray in ("caption: c", "direction: up", "from: X"):
        with pytest.raises(AnimateError, match="does not use"):
            parse_animate(
                f"pattern: build-up\nwhole: W\nparts:\n  - A: a\n  - B: b\n{stray}\n"
            )


def test_build_up_parts_settle_and_stay():
    anim = parse_animate(
        "pattern: build-up\nwhole: W\nparts:\n  - A: a\n  - B: b\n  - C: c\n"
    )
    out = _build_up_html(anim, "ANIMTOKEN1")
    assert 'dir="ltr"' in out
    data = json.loads(
        re.search(r'class="anim__timeline">(.*?)</script>', out, re.S).group(1)
    )
    assert any("fillOpacity" in str(k) for s in data["steps"]
               for k in (s.get("props") or {}))
    animated = {p for s in data["steps"] if s.get("kind") != "set"
                for p in (s.get("props") or {})}
    reset = {p for s in data["steps"] if s.get("kind") == "set"
             for p in (s.get("props") or {})}
    assert animated <= reset
```

- [ ] **Step 2: Run to confirm failure** (`pattern must be` — not in the whitelist)

- [ ] **Step 3: Widen `_ANIMATE_KEY` once, for all three new patterns**

⚠️ **This is the highest-risk edit in Tasks 5–7, and it is shared.** `_ANIMATE_KEY` is
currently:

```python
_ANIMATE_KEY = re.compile(
    r"^(?P<key>pattern|before|after|caption|direction|from|to):\s*(?P<value>.*)$"
)
```

Any key **not** matching this regex falls through the parser's key-dispatch chain into the
final `else:`, which assigns the value to `caption`. So a `whole:` line today silently
becomes the caption instead of raising. Widen it **once, here**, for every scalar the three
new patterns need — `whole`, `left`, `right`, `source`, `merged` — so this line is not
edited three times:

```python
_ANIMATE_KEY = re.compile(
    r"^(?P<key>pattern|before|after|caption|direction|from|to"
    r"|whole|left|right|source|merged):\s*(?P<value>.*)$"
)
```

**Widening alone is not enough.** Each new key also needs its own branch in the dispatch
chain storing it in its own variable; without that it still lands in `caption`, silently.
Add all five now (Tasks 6 and 7 consume `left`/`right` and `source`/`merged`).

Then extend **every existing pattern's guard** to reject the five new keys, so a stray
`whole:` on a `pipeline` fails loudly. This is the same bug class that required a follow-up
fix when `from`/`to` were added — do not repeat it.

`path-trace` used to be the only pattern accepting `caption:` and it is now deleted, so
**no surviving pattern accepts `caption:`** — every guard should reject it.

- [ ] **Step 4: Implement the `build-up` parser branch and renderer**

Add `whole`/`parts` to `Animate`, `"parts:"` to `_LIST_HEADERS` and the `lists` dict, plus
the guard. Constants divisible by 4: `_BUILD_ROW_HEIGHT = 40`, `_BUILD_ROW_GAP = 8`,
`_BUILD_MARGIN = 12`. Row width derives from the longer of name and contribution.

- [ ] **Step 5: Replace the Hebrew fixture's stand-in** with the `build-up` block from Task 1, Step 4. Confirm `tests/golden/course-he.html` regenerates cleanly and the block renders RTL-safe.

- [ ] **Step 6: Run the tests, then the full suite**

- [ ] **Step 7: Commit**

```bash
git add -A
git commit -m "feat: add the build-up animate pattern"
```

---

### Task 6: Add `compare`

**Files:**
- Modify: `scripts/p2c/mdrender.py`, `assets/base/layout.css`, `assets/print.css`
- Modify: `tests/fixtures/mini-course/modules/02-scheduling.md` (replace the stand-in)
- Test: `tests/test_mdrender.py`

**Interfaces:**
- Produces: `Animate.left: str`, `Animate.right: str`, `Animate.rows: list[tuple[str, str]]`; `_compare_html(anim, token) -> str`.

**Grammar:** required `left:` and `right:`; `steps:` 1–5 entries, each `<left text> | <right text>`
split on the first unescaped `|`. Both halves required — a row with one side is a
`build-up`, not a comparison.

**Shape:** two columns advancing in lockstep so the contrast lands row by row. Text inverts
on the accent flash per Task 2 — this pattern is where the invisible-text bug was first
seen.

- [ ] **Step 1: Write the failing tests**

```python
def test_compare_parses_two_tracks():
    anim = parse_animate(
        "pattern: compare\nleft: First-come\nright: Round robin\n"
        "steps:\n  - A long job blocks the queue | Each job gets a slice\n"
        "  - Short jobs wait | Short jobs finish early\n"
    )
    assert anim.left == "First-come"
    assert anim.right == "Round robin"
    assert anim.rows[0] == ("A long job blocks the queue", "Each job gets a slice")


def test_compare_requires_both_sides_of_every_row():
    with pytest.raises(AnimateError, match="must be written as"):
        parse_animate(
            "pattern: compare\nleft: L\nright: R\nsteps:\n  - only one side\n"
        )


def test_compare_requires_both_headers():
    with pytest.raises(AnimateError, match="needs both 'left:' and 'right:'"):
        parse_animate("pattern: compare\nleft: L\nsteps:\n  - a | b\n")


def test_compare_rejects_bad_row_counts():
    with pytest.raises(AnimateError, match="at least 1 step"):
        parse_animate("pattern: compare\nleft: L\nright: R\n")
    body = "pattern: compare\nleft: L\nright: R\nsteps:\n" + "".join(
        f"  - l{i} | r{i}\n" for i in range(6)
    )
    with pytest.raises(AnimateError, match="at most 5 steps"):
        parse_animate(body)


def test_compare_inverts_text_on_the_accent_flash():
    anim = parse_animate(
        "pattern: compare\nleft: L\nright: R\nsteps:\n  - a | b\n  - c | d\n"
    )
    out = _compare_html(anim, "ANIMTOKEN1")
    assert 'dir="ltr"' in out
    data = json.loads(
        re.search(r'class="anim__timeline">(.*?)</script>', out, re.S).group(1)
    )
    assert any("accent-contrast" in str((s.get("props") or {}).get("fill", ""))
               for s in data["steps"])
```

- [ ] **Step 2: Run to confirm failure**

- [ ] **Step 3: Implement**

Constants divisible by 4: `_CMP_COL_WIDTH` derived from text, `_CMP_ROW_HEIGHT = 52`,
`_CMP_GUTTER = 28`, `_CMP_MARGIN = 12`. A dashed centre rule separates the columns. Both
columns' rects flash together per row; their text inverts on the same clock.

- [ ] **Step 4: Replace the scheduling fixture's stand-in** with the `compare` block from Task 1, Step 4.

- [ ] **Step 5: Run the tests, then the full suite**

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "feat: add the compare animate pattern"
```

---

### Task 7: Add `split-merge`

**Files:**
- Modify: `scripts/p2c/mdrender.py`, `assets/base/layout.css`, `assets/print.css`
- Modify: `tests/fixtures/mini-course-he/modules/01-section.md` (replace the last stand-in)
- Test: `tests/test_mdrender.py`

**Interfaces:**
- Produces: `Animate.source: str`, `Animate.branches: list[tuple[str, str]]`, `Animate.merged: str`; `_split_merge_html(anim, token) -> str`.

**Grammar:** required `source:` and `merged:`; `branches:` 2–4 entries, each
`<name>: <what it does>`.

**Shape:** one thing dividing into parallel branches, then recombining. This is the only
proposed pattern covering *branching* — `state-machine` explicitly rejects a state with two
outgoing transitions, so this shape has no animated form today and always falls back to
mermaid.

- [ ] **Step 1: Write the failing tests**

```python
def _sm2():
    return parse_animate(
        "pattern: split-merge\nsource: Proof by cases\n"
        "branches:\n  - Case n even: divide by two\n  - Case n odd: apply 3n + 1\n"
        "merged: Both cases reach 1\n"
    )


def test_split_merge_parses_source_branches_and_merge():
    anim = _sm2()
    assert anim.source == "Proof by cases"
    assert anim.merged == "Both cases reach 1"
    assert anim.branches[0] == ("Case n even", "divide by two")


def test_split_merge_requires_source_and_merged():
    with pytest.raises(AnimateError, match="needs both 'source:' and 'merged:'"):
        parse_animate(
            "pattern: split-merge\nsource: S\nbranches:\n  - A: a\n  - B: b\n"
        )


def test_split_merge_rejects_bad_branch_counts():
    with pytest.raises(AnimateError, match="at least 2 branches"):
        parse_animate(
            "pattern: split-merge\nsource: S\nmerged: M\nbranches:\n  - A: a\n"
        )
    body = ("pattern: split-merge\nsource: S\nmerged: M\nbranches:\n"
            + "".join(f"  - B{i}: does {i}\n" for i in range(5)))
    with pytest.raises(AnimateError, match="at most 4 branches"):
        parse_animate(body)


def test_split_merge_renders_and_resets():
    out = _split_merge_html(_sm2(), "ANIMTOKEN1")
    assert 'dir="ltr"' in out
    data = json.loads(
        re.search(r'class="anim__timeline">(.*?)</script>', out, re.S).group(1)
    )
    animated = {p for s in data["steps"] if s.get("kind") != "set"
                for p in (s.get("props") or {})}
    reset = {p for s in data["steps"] if s.get("kind") == "set"
             for p in (s.get("props") or {})}
    assert animated <= reset
    # the merged box goes solid accent, so its label must invert
    assert any("accent-contrast" in str((s.get("props") or {}).get("fill", ""))
               for s in data["steps"])
```

- [ ] **Step 2: Run to confirm failure**

- [ ] **Step 3: Implement**

Fan-out and fan-in connectors are cubic Béziers whose path lengths are computed in Python
for the `stroke-dashoffset` draw (no runtime `getTotalLength()`). Constants divisible by 4.
Branch boxes settle to the faint accent wash; the merged box takes solid accent with inverted text.

- [ ] **Step 4: Replace the final Hebrew stand-in** with the `split-merge` block from Task 1, Step 4. **Then check the stand-in table in Task 1, Step 4 against the fixture tree and confirm all three rows are resolved** — there is no `TODO` marker to grep for, because validator rule 7 rejects one.

- [ ] **Step 5: Run the tests, then the full suite**

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "feat: add the split-merge animate pattern"
```

---

### Task 8: Styling, print, and reduced-motion for the new patterns

**Files:**
- Modify: `assets/base/layout.css`, `assets/print.css`
- Test: `tests/test_assets.py`

**Interfaces:**
- Consumes: class names and tokens emitted by Tasks 3–7.

**Critical:** every element the timeline reveals starts hidden via an inline attribute
(`opacity="0"`, full `stroke-dashoffset`). Under `prefers-reduced-motion` and in print the
timeline never runs, so **CSS must force them visible or the diagram renders blank** — a
silent failure no Python test catches. Each pattern also ships an `<ol>` static fallback
listing every step, shown only in those two contexts.

- [ ] **Step 1: Write the failing test**

```python
def test_new_patterns_reveal_under_reduced_motion_and_print():
    layout = (ASSETS / "base" / "layout.css").read_text(encoding="utf-8")
    printcss = (ASSETS / "print.css").read_text(encoding="utf-8")
    reduced = "".join(layout.split("@media (prefers-reduced-motion: reduce)")[1:])
    for pattern in ("build-up", "compare", "split-merge"):
        assert f"anim--{pattern}" in reduced, f"{pattern} has no reduced-motion reveal"
        assert f"anim--{pattern}" in printcss, f"{pattern} has no print reveal"
```

- [ ] **Step 2: Run to confirm failure**

- [ ] **Step 3: Add the rules**

Tokens from the theme only — never a hardcoded hex, since a theme that omits a token fails
to load. Mirror the reveal pattern the existing animations use: force `stroke-dashoffset: 0`
and `opacity: 1` with `!important` (they must beat inline presentation attributes), and
switch each `<ol>` fallback to `display: block` with the list styling the other patterns set.

- [ ] **Step 4: Verify no diagram renders blank**

Enumerate, from real rendered output, every class that starts hidden, and confirm each is
covered in BOTH `layout.css` and `print.css`:

```bash
/home/roneng/Presntation2Course/.venv/bin/python - <<'PY'
import sys, re; sys.path.insert(0, 'scripts')
from p2c.mdrender import parse_animate, _animate_html
blocks = {
 'build-up': 'pattern: build-up\nwhole: W\nparts:\n  - A: a\n  - B: b\n',
 'compare': 'pattern: compare\nleft: L\nright: R\nsteps:\n  - a | b\n',
 'split-merge': 'pattern: split-merge\nsource: S\nmerged: M\nbranches:\n  - A: a\n  - B: b\n',
}
for name, src in blocks.items():
    html = _animate_html(parse_animate(src), 'ANIMTOKEN1')
    hidden = set(re.findall(r'class="([\w-]+)"[^>]*opacity="0"', html))
    hidden |= set(re.findall(r'class="([\w-]+)"[^>]*stroke-dashoffset="[\d.]+"', html))
    print(name, '->', sorted(hidden))
PY
```

Every class printed must appear in both stylesheets' reveal blocks.

- [ ] **Step 5: Full suite and goldens**

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "feat: style the new patterns with print and reduced-motion fallbacks"
```

---

### Task 9: Rewrite the author-facing documentation

**Files:**
- Modify: `references/quiz-format.md`, `references/agents/course-writer.md`

**Interfaces:**
- Consumes: the exact grammar from Tasks 1, 3–7.

**The stale-count trap:** both files state how many patterns exist and enumerate them. After
this change the answer is **eight**, and `array-ops`/`path-trace` must disappear from every
list. A stale enumeration actively teaches the writer that valid patterns are invalid — and
that a deleted one is available.

- [ ] **Step 1: Grep for every enumeration**

```bash
grep -rn "array-ops\|path-trace\|Seven patterns\|seven patterns\|Four patterns" \
  references/ SKILL.md
```

Every hit in `references/` and `SKILL.md` must be updated. Hits inside
`docs/superpowers/` are historical records — leave them.

- [ ] **Step 2: Update `references/quiz-format.md`**

Remove the `array-ops` and `path-trace` grammar sections. Add `build-up`, `compare`, and
`split-merge` in the established format: a fenced example, then a sentence stating bounds
and required keys. Update the closing enumeration to name all eight.

- [ ] **Step 3: Update `references/agents/course-writer.md`**

Extend the "prefer `animate` when the topic is" list with the three new shapes, phrased **by
shape, never by domain** — "one entity dividing into parallel branches", not "multi-head
attention". Domain-flavoured rules are what made the old vocabulary read as CS-only.

Add explicit guidance for the two closest pairs, since ambiguity here produces bad picks:
- `pipeline` vs `transform`: a pipeline's stages each *do something to* what passes through; a transform's steps *change one thing into another*. If the endpoints matter more than the stages, use `transform`.
- `build-up` vs `layer-stack`: a layer stack's tiers *rest on* each other (a hierarchy); a build-up's parts *combine into* a whole (a composition).

- [ ] **Step 4: Verify every documented example parses**

```bash
/home/roneng/Presntation2Course/.venv/bin/python - <<'PY'
import sys, re; sys.path.insert(0, 'scripts')
from p2c.mdrender import parse_animate, AnimateError
ok = fail = 0
for path in ('references/quiz-format.md', 'references/agents/course-writer.md'):
    src = open(path, encoding='utf-8').read()
    for body in re.findall(r'```animate\n(.*?)```', src, re.S):
        try:
            parse_animate(body); ok += 1
        except AnimateError as e:
            fail += 1; print('FAIL', path, e)
print(f'{ok} parse, {fail} fail')
PY
```

Expected: `0 fail`. A documented example the parser rejects is worse than none — the writer
copies it and the build fails.

- [ ] **Step 5: Confirm no stale references survive**

Re-run the Step 1 grep. Expected: no hits outside `docs/superpowers/`.

- [ ] **Step 6: Full suite, then commit**

```bash
git add -A
git commit -m "docs: document the eight-pattern animate vocabulary"
```

---

### Task 10: End-to-end verification

**Files:**
- Test: `tests/test_build.py`

- [ ] **Step 1: Write the failing tests**

```python
def test_course_using_every_pattern_builds_clean():
    blocks = {
        "state-machine": "states:\n  - A\n  - B\ntransitions:\n  - A -> B: goes\n",
        "state-toggle": "before: Cold cache\nafter: Warm cache\n",
        "pipeline": "stages:\n  - Raw: unprocessed\n  - Done: processed\n",
        "layer-stack": "layers:\n  - Base: raw values\n  - Top: shapes\n",
        "transform": "from: A form\nto: B form\nsteps:\n  - Convert it\n",
        "build-up": "whole: A whole\nparts:\n  - A: first\n  - B: second\n",
        "compare": "left: L\nright: R\nsteps:\n  - a | b\n",
        "split-merge": "source: S\nmerged: M\nbranches:\n  - A: a\n  - B: b\n",
    }
    body = "".join(
        f"\n<!-- topic: t{i} -->\n### Topic {i}\n\n"
        f"```animate\npattern: {name}\n{src}```\n"
        for i, (name, src) in enumerate(blocks.items())
    )
    rendered = render_course(course(body))
    assert rendered.errors == []
    assert len(rendered.animations_per_topic) == len(blocks)
    for name in blocks:
        assert f"anim--{name}" in rendered.html_body


def test_removed_patterns_fail_the_build():
    body = (
        "\n<!-- topic: t0 -->\n### Topic\n\n"
        "```animate\npattern: array-ops\narray:\n  - 1\n  - 2\nops:\n  - swap 0 1\n```\n"
    )
    rendered = render_course(course(body))
    assert any("animate" in e for e in rendered.errors)
```

Match the real helper names in `tests/test_build.py` (`render_course`, and the `course()`
helper that prepends front matter) rather than inventing new ones.

- [ ] **Step 2: Run to confirm failure**

- [ ] **Step 3: Fix any integration gap at its source task's file**, not with compensating code here.

- [ ] **Step 4: Confirm the animation floor still works**

The 25% coverage check counts `animate` blocks per topic. Removing two patterns shrinks the
vocabulary, so confirm the floor's behaviour is unchanged:

```bash
/home/roneng/Presntation2Course/.venv/bin/python -m pytest tests/test_validate.py -k floor -v
```

- [ ] **Step 5: Full suite, then commit**

```bash
git add -A
git commit -m "test: end-to-end coverage for the eight-pattern vocabulary"
```

---

## Self-Review

**1. Spec coverage**

| Requirement | Task |
|---|---|
| Delete `array-ops`, `path-trace` (parser, renderer, CSS, tests, fixtures, goldens) | 1 |
| Contrast fix for text on accent fills, incl. the shipped `state-machine` defect | 2 |
| `state-machine` redesigned: track, held tint, non-overlapping labels, text-derived width | 3 |
| `transform` redesigned: accumulating spine | 4 |
| `build-up` | 5 |
| `compare` | 6 |
| `split-merge` | 7 |
| Print + reduced-motion reveals; no blank diagrams | 8 |
| Docs rewritten; stale enumerations purged; every example parses | 9 |
| End-to-end proof of all eight; removed patterns rejected | 10 |
| Paint order (`marker → boxes → labels`) | 3, global constraint |
| anime.js loop-reset invariant | 3–7 (asserted) |
| `dir="ltr"` on every root | 3–7 (asserted) |

No gaps.

**2. Placeholder scan**

No "TBD", "TODO", or "similar to Task N" in the delivered work. Task 1 deliberately
introduces temporary `# TODO(task-N)` stand-ins in fixtures — these are scheduled, each
named with its resolving task, and Task 7 Step 4 verifies none survive.

**3. Type consistency**

- `Animate.whole: str` / `.parts: list[tuple[str, str]]` — Task 5 only. ✓
- `Animate.left` / `.right` / `.rows: list[tuple[str, str]]` — Task 6 only. ✓
- `Animate.source` / `.merged` / `.branches: list[tuple[str, str]]` — Task 7 only. ✓
- `_build_up_html`, `_compare_html`, `_split_merge_html` — signatures identical in tests and implementation. ✓
- `.anim__visited` (a `fill-opacity` wash, not `color-mix`) — defined Task 2, consumed Tasks 3, 5, 7. ✓
- `.anim__text-on-accent` / `--color-accent-contrast` — defined Task 2, consumed Tasks 3, 4, 6, 7. ✓
- `_state_machine_html` / `_transform_html` keep their existing signatures, so `_animate_html`'s dispatch is unchanged for them. ✓

**One risk worth stating:** Task 1 removes patterns that Tasks 5–7's fixtures will replace,
so the fixture tree passes through a temporary state using stand-in patterns. If execution
stops between Tasks 1 and 7, the fixtures are valid but semantically odd. Task 7 Step 4 is
the gate that closes this.
