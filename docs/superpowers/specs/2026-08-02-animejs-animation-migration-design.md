# Migrate `animate` blocks to anime.js

## Context

The `animate` fenced-block system (introduced by the visual-engagement plan, extended
with `array-ops`/`path-trace` in the multiple-visual-enhancements plan) renders every
pattern today as hand-authored CSS `@keyframes`, generated per-block in Python. Live
review of the built output found the two newest patterns (`array-ops`, `path-trace`)
visually unconvincing — bare SVG shapes with no real sense of motion, described as
"looks like image generation from a decade ago." Iterative browser-based prototyping
(via the brainstorming skill's visual companion, using a project-installed `animejs`
skill for API reference) confirmed real, professional-feeling motion is achievable with
anime.js v4 timelines, and surfaced two concrete, non-obvious bugs worth fixing at the
architecture level rather than working around per-block:

1. **SVG `transform` attribute vs. CSS `transform` property conflict**: animating any
   transform-family property (`translateX`, `scale`, ...) makes anime.js set a CSS
   `transform`, which fully replaces (does not compose with) an SVG `transform`
   *attribute* on the same element. Any element that needs both a fixed base position
   and an animated offset must carry the base position in plain attributes
   (`x`/`cx`/`y`/`cy`), never in a `transform="translate(...)"` attribute.
2. **Absolute keyframe values compound across `loop: true`**: a step that animates
   *to* a literal value (not a `[from, to]` pair) starts from wherever the timeline
   left the element after the previous lap, not from a fixed baseline — silently
   breaking after the first loop iteration. Fixed via an explicit `tl.set(...)` reset
   as the timeline's last step, snapping every animated property back to its starting
   value right before the loop restarts.

Both are now documented as permanent gotchas in
`.claude/skills/animejs/references/api-reference.md`.

The user separately confirmed: migrate **all four** existing patterns (`step-reveal`,
`state-toggle`, `array-ops`, `path-trace`) to anime.js — not just the two that were
broken — so the codebase has one animation mechanism, not two coexisting ones. No new
pattern types are in scope for this change.

## Architecture

**Vendoring.** `assets/vendor/anime.min.js` (anime.js v4 UMD/IIFE build, MIT license)
is added following the exact precedent of `assets/vendor/mermaid.min.js`: pinned by
SHA256 (`tests/test_assets.py::test_vendored_anime_matches_the_pin`, mirroring
`test_vendored_mermaid_matches_the_pin`), no separate license file (matching mermaid's
existing convention — none exists for it either).

`Theme` (`scripts/p2c/theme.py`) gains `anime_js: str | None`, loaded the same way
`mermaid_js` is: `_read(assets / "vendor" / "anime.min.js")` if the file exists.
`theme.py`'s `TEMPLATE_PLACEHOLDERS` gains `{{ANIME_JS}}`; `assets/base/template.html`
gains `<script>{{ANIME_JS}}</script>` alongside the existing Mermaid/course.js script
tags.

`build.py`'s `fill_template` gains an `inline_anime: bool` parameter (mirroring
`inline_mermaid` exactly), substituting `theme.anime_js` only when true, else `""`.
`build()` passes `inline_anime=rendered.uses_animate`. Both the real render and the
validation-copy render (which forces `inline_mermaid=False`) also force
`inline_anime=False` for the same reason mermaid's validation copy does: the vendored
bundle is vetted once at the asset level (SHA256 pin) and re-scanning ~118KB of bundled
library code for every course serves no purpose and would need the same
`external_request`-check exemption mermaid already has.

`mdrender.Rendered` gains `uses_animate: bool = False`, computed in `render_course`'s
existing fence-processing loop: set to `True` the moment any fence with
`kind == "animate"` is successfully parsed (mirroring exactly how `uses_mermaid` is set
in the `elif fence.kind == "mermaid":` branch, in the same loop, right where
`_animate_html` is currently called). A course with zero `animate` blocks pays zero
extra bytes, identical to how a course with no diagrams pays nothing for Mermaid.

**Rendering: Python emits data, not `@keyframes`.** For each of the four patterns,
`mdrender.py`'s `_animate_html` (and its four pattern-specific helper functions) change
from emitting inline `<style>` blocks with generated `@keyframes` to emitting:

1. Static, at-rest SVG/HTML markup for the "before playback" frame — geometry,
   labels, legend, gridlines/axis, all computed deterministically from the block's
   parsed data exactly as today (no change to the `Animate` dataclass, `parse_animate`,
   or any validation rule — this migration touches only *how* a parsed block becomes
   HTML, never the authoring grammar or its validation).
2. One `<script type="application/json" class="anim__timeline" data-anim="<pattern>">`
   data island per block, containing a plain JSON description of the timeline: an
   ordered list of steps, each with target element id(s) (scoped to the block via a
   per-block-unique id prefix — see Token-safety below), the property changes, easing,
   and duration. No JS logic lives in this JSON; it is pure data, exactly as
   deterministic and testable as today's computed bar heights/viewBox bounds.
3. The same reduced-motion/print static fallback content already established
   (`.anim__array-steps-static`-style plain-text list for array-ops; the existing
   before/after side-by-side for state-toggle; step-reveal's steps list; path-trace
   gains an equivalent plain-text step list of "from (x,y) to (x,y)" lines).

**Coordinator: one new function in `course.js`.** A single `wireAnimations()` function
(added to the existing `wireQuizzes`/`wireTerms`/... sibling list in `start()`) runs
once on page load:

- Finds every `.anim` block's `.anim__timeline` JSON island.
- Skips entirely (leaves the static fallback visible, never touches `window.anime`) if
  `matchMedia('(prefers-reduced-motion: reduce)').matches` is true — checked in JS
  rather than relying on CSS alone, since a JS-driven anime.js timeline is not
  suppressible by a CSS `animation: none` rule the way the old per-block `@keyframes`
  were.
- Otherwise parses the JSON and drives it via one generic interpreter: builds an
  `anime.createTimeline({ loop: true, loopDelay: <n> })`, walks the step list calling
  `tl.add(...)`/`tl.set(...)` per the JSON's declared shape, and wires any declared
  caption-text step to update a `.anim__caption` element's `textContent` via that
  step's `onBegin`.
- This is the **only** place JS logic for animation playback lives. Per-block output
  from Python stays 100% data (ids, numbers, strings) — no generated JS expressions,
  no `eval`, nothing for a course-writer agent or a build bug to accidentally turn into
  executable code. This keeps the project's "LLM/course-writer supplies data only,
  never markup or logic" invariant intact at the JS layer too, not just HTML/CSS.

**Token-safety.** Per-block-unique ids (needed so multiple `animate` blocks on one page
don't collide) are derived the same proven-safe way the current array-ops code already
does: `token_seed = re.sub(r"\D", "", fence.token) or "0"`, never the token's literal
text and never `id()`/randomness — preserving both the byte-reproducibility requirement
and the fix for `blocks.restore()`'s double-substitution hazard (documented at length
in `mdrender.py` today; this migration keeps that exact mechanism, just reuses it for
element ids in the JSON island instead of `@keyframes` names).

**Per-pattern step data** (what Python computes and emits as JSON, informed by the
verified mockups):

- **step-reveal**: one step per list item — reveal (opacity 0→1, font-weight 400→600),
  hold, then recede (font-weight 600→400) — looping through the full list; a caption is
  not needed (the item text itself is the content being revealed).
- **state-toggle**: two steps — crossfade before→after, hold, crossfade back — looping.
  No caption needed (before/after labels already carry this, as today).
- **array-ops**: one step per op (`compare`/`swap`/`highlight`) as verified in the
  mockup — color flash + scale-pulse together for compare/highlight, an eased
  `translateX` crossing for swap (landing on the real swapped position, not bouncing
  back), each step's `onBegin` updating a `.anim__caption` with "Step N of M —
  <verb-phrase>". A final `tl.set(...)` step resets every bar's transform/fill to idle
  immediately before the loop restarts, per the verified fix.
- **path-trace**: one step per point-to-point segment, duration proportional to that
  segment's real Euclidean length (constant visual speed across uneven segments, as
  verified in the mockup) with a fading trail (an SVG `<path>` whose `d` grows via
  `onUpdate`, reset to just the new point via `onComplete`), each step's `onBegin`
  updating a caption with "Moving from (x, y) to (x, y)".

**Chart chrome added to array-ops** (part of this migration since it was verified
together with the motion): baseline + dashed midline gridline, generous top headroom
(a tall bar plus its highlight-step scale-pulse must never approach the SVG's own
edge — verified needed 40 units of headroom for a 120-unit-tall bar at 1.15x scale),
larger fonts (15px vs. the old 11px), and a static color legend
(idle/compare/swap/highlight swatches + labels) rendered once, non-animated.

**RTL wrapper convention preserved.** Both array-ops's and path-trace's `<svg>` keep
the existing `dir="ltr"` attribute (matching the pre-migration behavior and the same
`.mermaid { direction: ltr }` precedent) — diagram/plot semantics (bar order, axis
direction) shouldn't mirror inside an RTL course. This migration does not change that
attribute or its rationale, only how the motion inside the SVG is driven.

## Data flow

```
parse_animate (unchanged)
        |
        v
_animate_html(anim, fence.token)
        |
        v
per-pattern helper (_step_reveal_html / _state_toggle_html / _array_ops_html /
_path_trace_html) -- all four now emit (static markup, JSON timeline island)
        |
        v
mdrender.render_course sets uses_animate=True if any animate fence parsed
        |
        v
build.py: inline_anime = rendered.uses_animate -> {{ANIME_JS}} substitution
        |
        v
course.html ships with: static SVG/HTML (always visible pre-JS and under
reduced-motion/print) + JSON timeline islands + vendored anime.js + course.js's
wireAnimations() coordinator
        |
        v
Browser, JS enabled, motion not reduced: wireAnimations() reads each island,
drives anime.createTimeline() generically, updates captions via onBegin
```

## Testing

Every existing test-philosophy constraint holds: dataclass equality, literal HTML/JSON
substring assertions, golden whole-file snapshots — no pixel/visual/screenshot testing
introduced.

- `tests/test_assets.py`: new `test_vendored_anime_matches_the_pin` (SHA256, mirrors
  mermaid's); extend the placeholder-completeness check with `{{ANIME_JS}}`; extend the
  DOM-contract test with `wireAnimations`/`.anim__timeline`/`data-anim`; extend the
  external-request exemption list for the vendored anime bundle exactly as mermaid's is
  exempted.
- `tests/test_mdrender.py`: rewrite the four patterns' rendering tests to assert exact
  JSON timeline content (parsed back via `json.loads` and compared as data, not fragile
  string matching) plus the exact static/at-rest markup, replacing the current
  `@keyframes`-substring assertions. Reduced-motion/print fallback content tests
  updated to match each pattern's new static list format (path-trace gains one, to
  match the other three).
- `tests/test_build.py`: extend the existing `test_animate_blocks_render_inside_a_built
_course`-style integration test to assert `{{ANIME_JS}}` was inlined when a course has
  an animate block, and NOT inlined (empty) when it doesn't — mirroring the existing
  mermaid inline/non-inline coverage.
- `tests/golden/course.html` / `course-he.html`: regenerated once via
  `P2C_UPDATE_GOLDEN=1`, at the end, after all four patterns' Python/CSS/JS changes
  land — same shared-regeneration discipline as the prior visual-enhancements plan.
- No new manual-smoke-test requirement beyond what's already standard for this repo's
  visual features (browser spot-check recommended before merge, not a new automated
  gate).

## Out of scope

- New animate pattern types (state-machine/flow, counter/meter, etc.) — user explicitly
  deferred these to a future request.
- Any change to the `animate` block authoring grammar, `Animate` dataclass, or
  `parse_animate` validation rules — this is a rendering-layer migration only.
- Any change to how courses without JS enabled behave — the static/at-rest and
  reduced-motion/print fallbacks remain the source of truth for those cases, unchanged
  in spirit from today.
