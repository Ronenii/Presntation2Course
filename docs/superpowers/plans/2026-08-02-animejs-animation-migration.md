# Migrate `animate` blocks to anime.js — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the hand-rolled, per-block generated CSS `@keyframes` behind all four `animate` block patterns (`step-reveal`, `state-toggle`, `array-ops`, `path-trace`) with anime.js v4 timelines, vendored into the course exactly the way Mermaid already is, fixing the two newest patterns' unconvincing motion in the process.

**Architecture:** Python keeps computing all geometry/data deterministically (no change to the `Animate` dataclass or `parse_animate`), but instead of emitting `<style>@keyframes...</style>`, each pattern's renderer emits static at-rest markup plus a `<script type="application/json" class="anim__timeline">` data island describing the timeline as plain data. One new `wireAnimations()` function in `course.js` is the *only* place JS animation logic lives: it reads every island and drives it through a generic `anime.createTimeline()` interpreter, skipping entirely under `prefers-reduced-motion: reduce`.

**Tech Stack:** Python 3 (stdlib only, as today), anime.js v4 (vendored UMD/IIFE build, MIT), vanilla JS (`course.js`), pytest.

## Global Constraints

- No change to the `Animate` dataclass, `parse_animate`, or any authoring-grammar validation rule — this is a rendering-layer migration only.
- No new `animate` pattern types — only migrate the four that exist today.
- Byte-reproducible builds: any per-block-unique identifier must be derived via `re.sub(r"\D", "", fence.token) or "0"` (digits-only from the fence token) — never `id()`, never randomness. This also avoids `blocks.restore()`'s double-substitution hazard (a generated string that contains the literal token text gets spliced into the page twice).
- No pixel/visual/screenshot testing anywhere — every test is dataclass equality, literal substring assertion (including `json.loads`-parsed JSON compared as data), or a golden whole-file snapshot.
- CSS logical properties only (no `left`/`right`) in any new/changed CSS.
- `dir="ltr"` stays on both `.anim__array`/`.anim__path` SVGs (unchanged rationale: diagram semantics shouldn't mirror in RTL courses, same precedent as `.mermaid`).
- Golden snapshots (`tests/golden/course.html`, `tests/golden/course-he.html`) are regenerated via `P2C_UPDATE_GOLDEN=1` **exactly once**, in the final task, after every other change has landed — not per-task.
- Every task must leave the full test suite green (`.venv/bin/pytest -q`) before its commit, except the golden-snapshot tests, which are expected to fail from Task 2 onward until Task 11 regenerates them (call this out explicitly at each task's verification step).

---

## File Map

| File | Responsibility |
|---|---|
| `assets/vendor/anime.min.js` | New. Vendored anime.js v4 UMD/IIFE build (MIT). |
| `scripts/p2c/theme.py` | `Theme.anime_js` field, `{{ANIME_JS}}` placeholder, loading. |
| `assets/base/template.html` | New `<script>{{ANIME_JS}}</script>` tag. |
| `scripts/p2c/build.py` | `inline_anime` param on `fill_template`, wired from `rendered.uses_animate`. |
| `scripts/p2c/mdrender.py` | `Rendered.uses_animate` field; all four `_..._html` renderers rewritten to emit static markup + JSON timeline island instead of `@keyframes`. |
| `assets/base/course.js` | New `wireAnimations()` — the only JS animation-playback logic. |
| `assets/base/layout.css` | Replace `@keyframes`-driven rules with at-rest/idle styling; array-ops gains chart chrome (gridlines, headroom, legend, larger fonts); new `.anim__caption`/`.anim__path-trail` etc. |
| `assets/print.css` | Update static-fallback rules to match each pattern's new fallback markup. |
| `tests/test_assets.py` | New pin test for `anime.min.js`; updated placeholder/DOM-contract/CSS-selector/token-prefix assertions. |
| `tests/test_mdrender.py` | Rewrite all four patterns' rendering tests to assert new static markup + JSON timeline data. |
| `tests/test_build.py` | Update the animate-block integration test; add anime.js inline/non-inline coverage mirroring Mermaid's. |
| `tests/golden/course.html`, `tests/golden/course-he.html` | Regenerated once, in the final task. |

---

## Task 1: Vendor anime.js and wire it into `Theme`/the template

**Files:**
- Create: `assets/vendor/anime.min.js`
- Modify: `scripts/p2c/theme.py`
- Modify: `assets/base/template.html`
- Test: `tests/test_assets.py`

**Interfaces:**
- Produces: `Theme.anime_js: str | None` (mirrors `Theme.mermaid_js` exactly); `{{ANIME_JS}}` template placeholder; `ANIME_SHA256` constant in `tests/test_assets.py`.

- [ ] **Step 1: Download and vendor the anime.js v4 UMD build**

Run:
```bash
curl -sL "https://cdn.jsdelivr.net/npm/animejs@4/lib/anime.iife.min.js" -o /home/roneng/Presntation2Course/assets/vendor/anime.min.js
```

Confirm it downloaded correctly and record its hash for the pin test:
```bash
head -c 200 /home/roneng/Presntation2Course/assets/vendor/anime.min.js
sha256sum /home/roneng/Presntation2Course/assets/vendor/anime.min.js
```
Expected: the file starts with the anime.js IIFE banner comment (`/** * anime.js - IIFE ...`) and prints a 64-character hex digest. Copy that digest — it is used in Step 2 below (do not guess or reuse the value shown here; recompute it from the file you actually downloaded).

- [ ] **Step 2: Write the failing pin test**

In `tests/test_assets.py`, add near the existing `MERMAID_SHA256` constant (line 17):

```python
ANIME_SHA256 = "<paste the sha256sum output from Step 1 here>"
```

Add a new test near `test_vendored_mermaid_matches_the_pin` (after line 83):

```python
def test_vendored_anime_matches_the_pin():
    data = (ASSETS / "vendor" / "anime.min.js").read_bytes()
    assert hashlib.sha256(data).hexdigest() == ANIME_SHA256
    assert b"anime.js" in data[:200]
    assert b"Julian Garnier" in data[:200]
```

- [ ] **Step 3: Run the test to verify it passes (the file already exists from Step 1)**

Run: `.venv/bin/pytest tests/test_assets.py::test_vendored_anime_matches_the_pin -v`
Expected: PASS (the file and the pin were derived from the same download in Step 1)

- [ ] **Step 4: Add `anime_js` to `Theme` and load it**

In `scripts/p2c/theme.py`, modify the `Theme` dataclass (currently lines 74-82):

```python
@dataclass
class Theme:
    name: str
    theme_css: str
    layout_css: str
    print_css: str
    course_js: str
    template: str
    mermaid_js: str | None
    anime_js: str | None
```

Modify `load_theme` (currently lines 115-138) to load it, right next to the existing `mermaid` line:

```python
    mermaid = assets / "vendor" / "mermaid.min.js"
    anime = assets / "vendor" / "anime.min.js"
    return Theme(
        name=name,
        theme_css=theme_css,
        layout_css=_read(assets / "base" / "layout.css"),
        print_css=_read(assets / "print.css"),
        course_js=_read(assets / "base" / "course.js"),
        template=template,
        mermaid_js=mermaid.read_text(encoding="utf-8") if mermaid.is_file() else None,
        anime_js=anime.read_text(encoding="utf-8") if anime.is_file() else None,
    )
```

Add `"{{ANIME_JS}}"` to `TEMPLATE_PLACEHOLDERS` (currently lines 52-67), right after `"{{MERMAID_JS}}"`:

```python
TEMPLATE_PLACEHOLDERS = (
    "{{TITLE}}",
    "{{THEME_NAME}}",
    "{{THEME_CSS}}",
    "{{LAYOUT_CSS}}",
    "{{PRINT_CSS}}",
    "{{TOC}}",
    "{{CONTENT}}",
    "{{GLOSSARY}}",
    "{{SOURCES}}",
    "{{SOURCE_DECKS}}",
    "{{MERMAID_JS}}",
    "{{ANIME_JS}}",
    "{{COURSE_JS}}",
    "{{LANG}}",
    "{{DIR}}",
)
```

- [ ] **Step 5: Add the template placeholder**

In `assets/base/template.html`, change line 45-46 from:
```html
<script>{{MERMAID_JS}}</script>
<script>{{COURSE_JS}}</script>
```
to:
```html
<script>{{MERMAID_JS}}</script>
<script>{{ANIME_JS}}</script>
<script>{{COURSE_JS}}</script>
```

- [ ] **Step 6: Update the existing "every theme loads" test**

In `tests/test_assets.py`, modify `test_every_mapped_theme_loads` (lines 28-32) to also assert the new field loads:

```python
@pytest.mark.parametrize("name", sorted(set(THEME_FOR_DOMAIN.values())))
def test_every_mapped_theme_loads(name):
    theme = load_theme(ASSETS, name)
    assert theme.mermaid_js is not None
    assert theme.anime_js is not None
    assert theme.template and theme.layout_css and theme.print_css and theme.course_js
```

- [ ] **Step 7: Run the full asset test file**

Run: `.venv/bin/pytest tests/test_assets.py -v`
Expected: PASS — including `test_template_has_every_placeholder` and `test_template_placeholders_are_all_used_by_the_template`, which will now check for `{{ANIME_JS}}` too.

- [ ] **Step 8: Run the full suite to confirm nothing else broke**

Run: `.venv/bin/pytest -q`
Expected: all pass except the two golden-snapshot tests in `tests/test_build.py` (they will now fail because `template.html` changed — this is expected until Task 11; confirm the failures are ONLY the golden ones, e.g. `grep -c FAILED` output should show exactly the golden test names).

- [ ] **Step 9: Commit**

```bash
git add assets/vendor/anime.min.js scripts/p2c/theme.py assets/base/template.html tests/test_assets.py
git commit -m "feat: vendor anime.js and wire it into the theme/template"
```

---

## Task 2: Thread `inline_anime`/`uses_animate` through `build.py` and `mdrender.py`

**Files:**
- Modify: `scripts/p2c/mdrender.py`
- Modify: `scripts/p2c/build.py`
- Test: `tests/test_mdrender.py`
- Test: `tests/test_build.py`

**Interfaces:**
- Consumes: `Theme.anime_js` (Task 1).
- Produces: `Rendered.uses_animate: bool`; `fill_template(..., inline_anime: bool)`.

- [ ] **Step 1: Write the failing test for `uses_animate`**

In `tests/test_mdrender.py`, add near `test_mermaid_blocks_become_divs_and_set_the_flag` (line 155):

```python
def test_an_animate_block_sets_the_uses_animate_flag():
    md = course(
        '<!-- topic: tlb -->\n### The TLB\n\n'
        '```animate\npattern: state-toggle\nbefore: Ready\nafter: Running\n```\n\n'
        '```quiz\nq: q\n- [ ] a\n- [x] b\n- [ ] c\nwhy: because\n```\n\n'
        '```glossary\nTLB: definition\n```\n'
    )
    rendered = render_course(md)
    assert rendered.errors == []
    assert rendered.uses_animate is True


def test_uses_animate_is_false_with_no_animate_blocks():
    rendered = render_course(MODULE)  # MODULE has no animate block
    assert rendered.uses_animate is False
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/pytest tests/test_mdrender.py::test_an_animate_block_sets_the_uses_animate_flag -v`
Expected: FAIL with `AttributeError: 'Rendered' object has no attribute 'uses_animate'`

- [ ] **Step 3: Add the field and set it**

In `scripts/p2c/mdrender.py`, modify the `Rendered` dataclass (currently lines 505-518) to add the field right after `uses_mermaid`:

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
    uses_animate: bool = False
    topics_missing_visual: list[str] = field(default_factory=list)
    topics_missing_quiz: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
```

In `render_course` (currently around line 640), add `uses_animate = False` next to `uses_mermaid = False`:

```python
    uses_mermaid = False
    uses_animate = False
```

In the fence-processing loop's `elif fence.kind == "animate":` branch (currently lines 684-691), set the flag right after a successful parse:

```python
        elif fence.kind == "animate":
            try:
                anim = parse_animate(fence.body)
            except AnimateError as exc:
                errors.append(f"{anchor}: animate {exc}")
                replacements[fence.token] = ""
                continue
            uses_animate = True
            replacements[fence.token] = _animate_html(anim, fence.token)
```

In the final `return Rendered(...)` (currently lines 712-725), add the new argument:

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
        uses_animate=uses_animate,
        topics_missing_visual=topics_missing_visual,
        topics_missing_quiz=topics_missing_quiz,
        errors=errors,
    )
```

- [ ] **Step 4: Run to verify the mdrender tests pass**

Run: `.venv/bin/pytest tests/test_mdrender.py -v`
Expected: PASS

- [ ] **Step 5: Write the failing test for `inline_anime` in `build.py`**

In `tests/test_build.py`, add near `test_mermaid_is_not_inlined_when_the_course_has_no_diagrams` (line 113):

```python
def test_anime_is_not_inlined_when_the_course_has_no_animate_blocks(built):
    html = built.course_html.read_text()
    assert "Julian Garnier" not in html


def test_anime_is_inlined_once_when_an_animate_block_is_present(tmp_path):
    modules = tmp_path / "modules"
    modules.mkdir()
    for name in ("01-virtual-memory.md", "02-scheduling.md"):
        modules.joinpath(name).write_text((MINI / "modules" / name).read_text())
    with modules.joinpath("02-scheduling.md").open("a") as handle:
        handle.write(
            "\n```animate\npattern: state-toggle\nbefore: Ready\nafter: Running\n```\n"
        )
    out = tmp_path / "out"
    normalized = out / ".p2c" / "normalized"
    normalized.mkdir(parents=True)
    (normalized / "terse.pdf").write_bytes(
        (REPO / "tests" / "fixtures" / "terse.pdf").read_bytes()
    )
    result = build(MINI / "outline.json", modules, out, ASSETS)
    html = result.course_html.read_text()
    assert html.count("Julian Garnier") == 1
    assert [f.code for f in result.findings] == []
```

- [ ] **Step 6: Run to verify these fail**

Run: `.venv/bin/pytest tests/test_build.py::test_anime_is_not_inlined_when_the_course_has_no_animate_blocks tests/test_build.py::test_anime_is_inlined_once_when_an_animate_block_is_present -v`
Expected: the first FAILs only if `{{ANIME_JS}}` is currently substituted unconditionally (it isn't yet — `fill_template` doesn't know about it), so actually both should currently error/fail because `inline_anime` doesn't exist as a concept yet. Confirm both fail with an assertion error or the anime.js content appearing/not appearing incorrectly, not a Python exception unrelated to this feature — if you see an unrelated exception, stop and investigate before proceeding.

- [ ] **Step 7: Add `inline_anime` to `fill_template` and `build`**

In `scripts/p2c/build.py`, modify `fill_template`'s signature (currently lines 86-95):

```python
def fill_template(
    theme: Theme,
    rendered: Rendered,
    *,
    title: str,
    source_decks: list[str],
    inline_mermaid: bool,
    inline_anime: bool,
    language: dict,
    sources_html: str = "",
) -> str:
```

Add the substitution inside the `substitutions` dict (currently lines 97-112), right after `{{MERMAID_JS}}`:

```python
        "{{MERMAID_JS}}": theme.mermaid_js if (inline_mermaid and theme.mermaid_js) else "",
        "{{ANIME_JS}}": theme.anime_js if (inline_anime and theme.anime_js) else "",
```

In `build()`, both `fill_template` call sites (currently lines 144-152 for the real render, 169-177 for the validation copy) each gain `inline_anime=`:

Real render call:
```python
    html_text = _resolve_figures(
        fill_template(
            loaded,
            rendered,
            title=outline["title"],
            source_decks=rendered.front_matter.source_decks,
            inline_mermaid=rendered.uses_mermaid,
            inline_anime=rendered.uses_animate,
            language=outline["language"],
            sources_html=sources_html,
        ),
        out_dir,
    )
```

Validation-copy call:
```python
    validation_html = _resolve_figures(
        fill_template(
            loaded,
            rendered,
            title=outline["title"],
            source_decks=rendered.front_matter.source_decks,
            inline_mermaid=False,
            inline_anime=False,
            language=outline["language"],
            sources_html=sources_html,
        ),
        out_dir,
    )
```

- [ ] **Step 8: Run to verify both new build tests pass**

Run: `.venv/bin/pytest tests/test_build.py::test_anime_is_not_inlined_when_the_course_has_no_animate_blocks tests/test_build.py::test_anime_is_inlined_once_when_an_animate_block_is_present -v`
Expected: PASS

- [ ] **Step 9: Run the full suite**

Run: `.venv/bin/pytest -q`
Expected: all pass except the two golden-snapshot tests (still expected until Task 11).

- [ ] **Step 10: Commit**

```bash
git add scripts/p2c/mdrender.py scripts/p2c/build.py tests/test_mdrender.py tests/test_build.py
git commit -m "feat: thread uses_animate/inline_anime through render and build"
```

---

## Task 3: Add the `wireAnimations()` coordinator to `course.js` (generic interpreter, no patterns yet)

**Files:**
- Modify: `assets/base/course.js`
- Test: `tests/test_assets.py`

**Interfaces:**
- Consumes: nothing from earlier tasks (this is pure JS infrastructure; it will be exercised end-to-end once Task 4+ emit real `.anim__timeline` islands).
- Produces: `wireAnimations()` function; the JSON timeline island contract every pattern renderer will emit against:
  ```json
  {
    "loop": true,
    "loopDelay": 1200,
    "steps": [
      {
        "targets": ["#rect0", "#rect1"],
        "props": {"fill": ["#9ca3af", "#f59e0b", "#9ca3af"]},
        "duration": 700,
        "ease": "inOutQuad",
        "position": null,
        "caption": "Step 1 of 3 — comparing index 0 and 1"
      },
      {
        "targets": ["#bar0", "#bar1"],
        "props": {"scale": [1, 1.08, 1]},
        "duration": 700,
        "ease": "inOutQuad",
        "position": "<"
      },
      {
        "kind": "set",
        "targets": ["#bar0", "#bar1", "#bar2"],
        "props": {"translateX": 0, "scale": 1}
      }
    ]
  }
  ```
  Contract: each step object is either an animation step (default, or explicit `"kind": "add"`) or an instant reset (`"kind": "set"`). `position` is `null` (append normally), or one of the literal position-token strings documented in `.claude/skills/animejs/references/api-reference.md` (`"<"`, `">"`, `"+=N"`, `"-=N"`, `"<+=N"`, etc.) — passed straight through to `tl.add(targets, props, position)`. `caption`, when present on a step, is set as that step's `onBegin` callback body: `document.querySelector('.anim__caption[data-anim-id="<id>"]').textContent = <caption>`. Every id inside `targets` is expected to already be scoped/unique per block by the Python renderer (Task 4+); the coordinator does no scoping itself.

- [ ] **Step 1: Write the failing DOM-contract test**

In `tests/test_assets.py`, modify `test_course_js_drives_the_dom_contract_the_renderers_emit` (lines 86-102) to add the new hooks:

```python
def test_course_js_drives_the_dom_contract_the_renderers_emit():
    js = (ASSETS / "base" / "course.js").read_text()
    for hook in (
        ".quiz__option",
        "data-correct",
        ".quiz__answer",
        ".quiz__why",
        ".term",
        ".term__def",
        ".mermaid",
        "theme-toggle",
        "print-pdf",
        "data-mermaid-ready",
        "IntersectionObserver",
        ".anim__timeline",
        "wireAnimations",
        "prefers-reduced-motion",
        "createTimeline",
    ):
        assert hook in js, hook
    assert "localStorage" not in js  # stateless by design
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/pytest tests/test_assets.py::test_course_js_drives_the_dom_contract_the_renderers_emit -v`
Expected: FAIL — `wireAnimations` (and the other new hooks) not yet in `course.js`.

- [ ] **Step 3: Implement `wireAnimations()`**

In `assets/base/course.js`, add the new function before the closing `function start() {` block (currently line 189), following the file's existing style (IIFE, `"use strict"`, `document.querySelectorAll`):

```javascript
  /* --- animate blocks: JSON timeline data driven through anime.js -------- */
  function wireAnimations() {
    if (!window.anime) { return; }
    if (window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
      return; // static fallback markup (already in the page) stays as-is
    }
    document.querySelectorAll(".anim__timeline").forEach(function (island) {
      var data;
      try {
        data = JSON.parse(island.textContent);
      } catch (err) {
        return; // malformed data island: leave the static fallback visible
      }
      var animId = island.getAttribute("data-anim-id");
      var caption = animId
        ? document.querySelector('.anim__caption[data-anim-id="' + animId + '"]')
        : null;
      var tl = anime.createTimeline({ loop: !!data.loop, loopDelay: data.loopDelay || 0 });
      (data.steps || []).forEach(function (step) {
        var props = {};
        Object.keys(step.props || {}).forEach(function (key) { props[key] = step.props[key]; });
        if (step.caption && caption) {
          props.onBegin = function () { caption.textContent = step.caption; };
        }
        if (step.kind === "set") {
          tl.set(step.targets, props);
        } else if (step.position) {
          tl.add(step.targets, props, step.position);
        } else {
          tl.add(step.targets, props);
        }
      });
    });
  }
```

Add the call in `start()` (currently lines 189-196):

```javascript
  function start() {
    wireQuizzes();
    wireTerms();
    wireSidebarToggle();
    wireToc();
    wireChrome();
    renderDiagrams();
    wireAnimations();
  }
```

- [ ] **Step 4: Run to verify the DOM-contract test passes**

Run: `.venv/bin/pytest tests/test_assets.py::test_course_js_drives_the_dom_contract_the_renderers_emit -v`
Expected: PASS

- [ ] **Step 5: Run the full suite**

Run: `.venv/bin/pytest -q`
Expected: all pass except the two golden-snapshot tests (still expected).

- [ ] **Step 6: Commit**

```bash
git add assets/base/course.js tests/test_assets.py
git commit -m "feat: add wireAnimations() coordinator driving JSON timeline islands"
```

---

## Task 4: Migrate `step-reveal` to anime.js

**Files:**
- Modify: `scripts/p2c/mdrender.py`
- Modify: `assets/base/layout.css`
- Test: `tests/test_mdrender.py`

**Interfaces:**
- Consumes: the JSON timeline island contract from Task 3.
- Produces: `_step_reveal_html(anim: Animate, token: str) -> str` (new, extracted helper function — mirrors the existing `_array_ops_html`/`_path_trace_html` extraction pattern already used in this file).

- [ ] **Step 1: Write the failing rendering test**

In `tests/test_mdrender.py`, replace `test_step_reveal_renders_with_staggered_negative_delays` (lines 499-510) with:

```python
def test_step_reveal_renders_with_a_timeline_island():
    md = course(
        '<!-- topic: tlb -->\n### The TLB\n\n'
        '```animate\npattern: step-reveal\nsteps:\n  - First\n  - Second\n  - Third\n```\n\n'
        '```quiz\nq: q\n- [ ] a\n- [x] b\n- [ ] c\nwhy: because\n```\n\n'
        '```glossary\nTLB: definition\n```\n'
    )
    rendered = render_course(md)
    assert rendered.errors == []
    assert '<li class="anim__step">First</li>' in rendered.html_body
    assert '<li class="anim__step">Second</li>' in rendered.html_body
    assert '<li class="anim__step">Third</li>' in rendered.html_body
    match = re.search(
        r'<script type="application/json" class="anim__timeline"[^>]*>(.*?)</script>',
        rendered.html_body,
        re.DOTALL,
    )
    assert match, "no anim__timeline data island found"
    timeline = json.loads(match.group(1))
    assert timeline["loop"] is True
    assert len(timeline["steps"]) == 3
    first_step = timeline["steps"][0]
    assert first_step["props"]["opacity"] == [0.65, 1, 0.65]
```

Add `import json` and confirm `import re` are present at the top of `tests/test_mdrender.py` (check first; both are very likely already imported given the file's extensive regex/error-string testing — if not, add them).

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/pytest tests/test_mdrender.py::test_step_reveal_renders_with_a_timeline_island -v`
Expected: FAIL (old markup has no `anim__timeline` island, still has `animation-duration` inline styles).

- [ ] **Step 3: Extract and rewrite `_step_reveal_html`**

In `scripts/p2c/mdrender.py`, modify `_animate_html` (currently lines 235-261) to dispatch to a new helper for `step-reveal`, matching the existing dispatch style for `array-ops`/`path-trace`:

```python
def _animate_html(anim: Animate, token: str) -> str:
    if anim.pattern == "step-reveal":
        return _step_reveal_html(anim, token)
    if anim.pattern == "state-toggle":
        return _state_toggle_html(anim, token)
    if anim.pattern == "array-ops":
        return _array_ops_html(anim, token)
    # path-trace
    return _path_trace_html(anim, token)
```

Add the new `_step_reveal_html` function (replacing the old inline `step-reveal` branch entirely), placed before `_array_ops_html`:

```python
def _step_reveal_html(anim: Animate, token: str) -> str:
    token_seed = re.sub(r"\D", "", token) or "0"
    items = "".join(f'<li class="anim__step">{html.escape(step)}</li>' for step in anim.steps)
    n = len(anim.steps)
    cycle = n * STEP_SECONDS
    steps_json = []
    for i in range(n):
        steps_json.append({
            "targets": [f"#anim-step-{token_seed}-{i}"],
            "props": {"opacity": [0.65, 1, 0.65], "fontWeight": [400, 600, 400]},
            "duration": cycle * 1000 // n if n else 0,
            "ease": "linear",
            "position": None if i == 0 else "<",
        })
    timeline = {"loop": True, "loopDelay": 0, "steps": steps_json}
    timeline_json = html.escape(json.dumps(timeline), quote=False)
    return (
        f'<div class="anim anim--step-reveal"><ol class="anim__steps">{items}</ol>'
        f'<script type="application/json" class="anim__timeline">{timeline_json}</script>'
        "</div>"
    )
```

Note: this task intentionally leaves the `<li>` elements without per-item `id` attributes matching `#anim-step-{token_seed}-{i}` — that is a real gap you must close: add `id="anim-step-{token_seed}-{i}"` to each `<li>` in the `items` join above:

```python
    items = "".join(
        f'<li class="anim__step" id="anim-step-{token_seed}-{i}">{html.escape(step)}</li>'
        for i, step in enumerate(anim.steps)
    )
```

Add `import json` at the top of `scripts/p2c/mdrender.py` if not already present (check first — this file already does extensive string building, but confirm `json` specifically).

- [ ] **Step 4: Update `layout.css` — remove the old keyframes, keep at-rest styling**

In `assets/base/layout.css`, replace the `step-reveal` block (currently lines 213-231):

```css
.anim { margin: var(--space-6) 0; }
.anim__steps {
  list-style: decimal; padding-inline-start: var(--space-6); margin: 0;
  display: grid; gap: var(--space-2);
}
.anim__step {
  /* Idle/at-rest look before JS runs, and the permanent look under
     prefers-reduced-motion (wireAnimations() never touches the element in that
     case) or print. wireAnimations()'s timeline animates opacity/font-weight
     directly on top of this once JS runs. */
  opacity: 0.65; font-weight: 400;
}
```

- [ ] **Step 5: Run to verify the rendering test passes**

Run: `.venv/bin/pytest tests/test_mdrender.py::test_step_reveal_renders_with_a_timeline_island -v`
Expected: PASS

- [ ] **Step 6: Run the full mdrender test file to catch any other test still asserting old markup**

Run: `.venv/bin/pytest tests/test_mdrender.py -v`
Expected: PASS. If any other test (e.g. one asserting `animation-duration` substrings anywhere for step-reveal) fails, update it to match the new markup the same way Step 1 did.

- [ ] **Step 7: Run the full suite**

Run: `.venv/bin/pytest -q`
Expected: all pass except the two golden-snapshot tests (still expected).

- [ ] **Step 8: Commit**

```bash
git add scripts/p2c/mdrender.py assets/base/layout.css tests/test_mdrender.py
git commit -m "feat: migrate step-reveal animate pattern to anime.js"
```

---

## Task 5: Migrate `state-toggle` to anime.js

**Files:**
- Modify: `scripts/p2c/mdrender.py`
- Modify: `assets/base/layout.css`
- Modify: `assets/print.css`
- Test: `tests/test_mdrender.py`

**Interfaces:**
- Produces: `_state_toggle_html(anim: Animate, token: str) -> str`.

- [ ] **Step 1: Write the failing rendering test**

In `tests/test_mdrender.py`, replace `test_state_toggle_renders_before_and_after` (lines 513-529) with:

```python
def test_state_toggle_renders_before_and_after_with_a_timeline_island():
    md = course(
        '<!-- topic: tlb -->\n### The TLB\n\n'
        '```animate\npattern: state-toggle\nbefore: Shared\nafter: Modified\n```\n\n'
        '```quiz\nq: q\n- [ ] a\n- [x] b\n- [ ] c\nwhy: because\n```\n\n'
        '```glossary\nTLB: definition\n```\n'
    )
    rendered = render_course(md)
    assert rendered.errors == []
    assert (
        '<div class="anim__state anim__state--before">'
        '<span class="anim__state-label">Before</span>Shared</div>'
    ) in rendered.html_body
    assert (
        '<div class="anim__state anim__state--after">'
        '<span class="anim__state-label">After</span>Modified</div>'
    ) in rendered.html_body
    match = re.search(
        r'<script type="application/json" class="anim__timeline"[^>]*>(.*?)</script>',
        rendered.html_body,
        re.DOTALL,
    )
    assert match, "no anim__timeline data island found"
    timeline = json.loads(match.group(1))
    assert timeline["loop"] is True
    assert len(timeline["steps"]) == 2
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/pytest tests/test_mdrender.py::test_state_toggle_renders_before_and_after_with_a_timeline_island -v`
Expected: FAIL.

- [ ] **Step 3: Write `_state_toggle_html`**

In `scripts/p2c/mdrender.py`, remove the old inline `state-toggle` branch from `_animate_html` (already redirected to `_state_toggle_html` in Task 4 Step 3) and add:

```python
def _state_toggle_html(anim: Animate, token: str) -> str:
    token_seed = re.sub(r"\D", "", token) or "0"
    before_id = f"anim-state-before-{token_seed}"
    after_id = f"anim-state-after-{token_seed}"
    timeline = {
        "loop": True,
        "loopDelay": 0,
        "steps": [
            {"targets": [f"#{before_id}"], "props": {"opacity": [1, 0]}, "duration": 4000, "ease": "inOutQuad"},
            {"targets": [f"#{after_id}"], "props": {"opacity": [0, 1]}, "duration": 4000, "ease": "inOutQuad", "position": "<"},
            {"kind": "set", "targets": [f"#{before_id}"], "props": {"opacity": 1}},
            {"kind": "set", "targets": [f"#{after_id}"], "props": {"opacity": 0}},
        ],
    }
    timeline_json = html.escape(json.dumps(timeline), quote=False)
    return (
        '<div class="anim anim--state-toggle">'
        f'<div class="anim__state anim__state--before" id="{before_id}">'
        f'<span class="anim__state-label">Before</span>{html.escape(anim.before)}</div>'
        f'<div class="anim__state anim__state--after" id="{after_id}">'
        f'<span class="anim__state-label">After</span>{html.escape(anim.after)}</div>'
        f'<script type="application/json" class="anim__timeline">{timeline_json}</script>'
        "</div>"
    )
```

Note the trailing pair of `"kind": "set"` steps: exactly the loop-reset gotcha documented in `.claude/skills/animejs/references/api-reference.md` — `after`'s opacity ends the visible animation at `1` (fully shown) and must be snapped back to `0` before the loop restarts, and vice versa for `before`, or the second loop iteration starts from the wrong opacity.

- [ ] **Step 4: Update `layout.css`**

Replace the `state-toggle` block (currently lines 232-253 after Task 4's edits shift line numbers — locate by content, not line number):

```css
.anim--state-toggle { display: grid; min-block-size: 3em; }
.anim__state {
  grid-area: 1 / 1;
  opacity: 0; /* wireAnimations() drives visibility once JS runs; the "before"
                state is shown before JS via the reduced-motion/print override
                below, so this 0 is only the JS-enabled resting default */
}
.anim__state--before { opacity: 1; }
.anim__state-label { display: none; }
```

- [ ] **Step 5: Update the reduced-motion block in `layout.css`**

The existing `@media (prefers-reduced-motion: reduce)` block (locate by content — was lines 255-265) needs its `.anim__step, .anim__state { animation: none; ... }` rule updated since there's no `animation` property left to disable:

```css
@media (prefers-reduced-motion: reduce) {
  html { scroll-behavior: auto; }
  .anim__step { opacity: 1; font-weight: 400; }
  .anim__state { opacity: 1; }
  .anim--state-toggle { grid-template-columns: 1fr 1fr; gap: var(--space-4); }
  .anim__state { grid-area: auto; }
  .anim__state-label { display: block; font-weight: 600; margin-block-end: var(--space-1); }
}
```

- [ ] **Step 6: Update `print.css`**

Replace lines 15-21 of `assets/print.css`:

```css
  .anim__step { opacity: 1 !important; font-weight: 400 !important; }
  .anim__state { opacity: 1 !important; }
  /* Both states are shown at once in print (no animation on paper), labeled and
     side-by-side rather than sharing the animated view's stacked grid cell. */
  .anim--state-toggle { grid-template-columns: 1fr 1fr !important; gap: 0.5em; }
  .anim__state { grid-area: auto !important; }
  .anim__state-label { display: block !important; font-weight: 600; margin-block-end: 0.25em; }
```

- [ ] **Step 7: Run to verify the rendering test passes**

Run: `.venv/bin/pytest tests/test_mdrender.py::test_state_toggle_renders_before_and_after_with_a_timeline_island -v`
Expected: PASS

- [ ] **Step 8: Run the full mdrender test file**

Run: `.venv/bin/pytest tests/test_mdrender.py -v`
Expected: PASS (fix any other test still asserting old `animation-delay`/`animation-name` markup for state-toggle).

- [ ] **Step 9: Run the full suite**

Run: `.venv/bin/pytest -q`
Expected: all pass except the two golden-snapshot tests (still expected).

- [ ] **Step 10: Commit**

```bash
git add scripts/p2c/mdrender.py assets/base/layout.css assets/print.css tests/test_mdrender.py
git commit -m "feat: migrate state-toggle animate pattern to anime.js"
```

---

## Task 6: Migrate `array-ops` to anime.js (the redesign — chart chrome, legend, live caption, real motion)

**Files:**
- Modify: `scripts/p2c/mdrender.py`
- Modify: `assets/base/layout.css`
- Modify: `assets/print.css`
- Test: `tests/test_mdrender.py`

**Interfaces:**
- Produces: `_array_ops_html(anim: Animate, token: str) -> str` (rewritten, same signature as today).

This task encodes exactly the verified mockup: base position lives in plain `x`/`y` attributes (never a `transform="translate(...)"` attribute, per the SVG-transform gotcha), each bar has `style="transform-box: fill-box; transform-origin: center;"`, generous top headroom, a static legend, a `.anim__caption` element, and a final `"kind": "set"` reset step so the swap sticks visually but the loop still restarts clean.

- [ ] **Step 1: Write the failing rendering test**

In `tests/test_mdrender.py`, find the current array-ops rendering test (search for `anim__array-bar` or similar — there should be one from the prior redesign round; if none exists as a named test, search `test_a_broken_animate_block_becomes_an_error_not_a_crash` and its neighbors for the array-ops case). Replace it with:

```python
def test_array_ops_renders_bars_and_a_timeline_island():
    md = course(
        '<!-- topic: tlb -->\n### The TLB\n\n'
        '```animate\npattern: array-ops\narray:\n  - 5\n  - 3\n  - 8\n  - 1\n'
        'ops:\n  - compare 0 1\n  - swap 0 1\n  - highlight 2\n```\n\n'
        '```quiz\nq: q\n- [ ] a\n- [x] b\n- [ ] c\nwhy: because\n```\n\n'
        '```glossary\nTLB: definition\n```\n'
    )
    rendered = render_course(md)
    assert rendered.errors == []
    assert rendered.html_body.count('<g class="anim__array-bar"') == 4
    assert rendered.html_body.count('<text class="anim__array-label"') == 4
    assert '>5<' in rendered.html_body
    assert '>3<' in rendered.html_body
    assert '>8<' in rendered.html_body
    assert '>1<' in rendered.html_body
    assert 'class="anim__array-legend"' in rendered.html_body
    assert 'class="anim__caption"' in rendered.html_body
    assert 'transform-box: fill-box; transform-origin: center' in rendered.html_body
    assert 'transform="translate(' not in rendered.html_body  # the SVG-transform-attribute gotcha
    assert '<ol class="anim__array-steps-static">' in rendered.html_body
    assert '<li>compare index 0 and 1</li>' in rendered.html_body
    assert '<li>swap index 0 and 1</li>' in rendered.html_body
    assert '<li>highlight index 2</li>' in rendered.html_body

    match = re.search(
        r'<script type="application/json" class="anim__timeline"[^>]*>(.*?)</script>',
        rendered.html_body,
        re.DOTALL,
    )
    assert match, "no anim__timeline data island found"
    timeline = json.loads(match.group(1))
    assert timeline["loop"] is True
    kinds = [step.get("kind", "add") for step in timeline["steps"]]
    assert kinds[-1] == "set" and kinds[-2] == "set"  # the loop-reset pair, last in the list
    swap_steps = [s for s in timeline["steps"] if s.get("caption", "").startswith("Step 2")]
    assert len(swap_steps) >= 1
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/pytest tests/test_mdrender.py::test_array_ops_renders_bars_and_a_timeline_island -v`
Expected: FAIL (current implementation emits `@keyframes`, no `anim__timeline`, no legend, uses `transform="translate(...)"`).

- [ ] **Step 3: Rewrite `_array_ops_html`**

In `scripts/p2c/mdrender.py`, replace the entire current `_array_ops_html` function (and remove `_BAR_WIDTH`/`_BAR_GAP`/`_BAR_MAX_HEIGHT` constants if no longer used elsewhere — check with `grep -n "_BAR_WIDTH\|_BAR_GAP\|_BAR_MAX_HEIGHT" scripts/p2c/mdrender.py` before deleting) with:

```python
_BAR_WIDTH = 36
_BAR_GAP = 18
_BAR_MAX_HEIGHT = 120
_BAR_HEADROOM = 40  # verified in mockup: enough room above the tallest bar for a
                    # 1.15x highlight scale-pulse to never approach the SVG's own edge
_BAR_BASELINE_Y = _BAR_HEADROOM + _BAR_MAX_HEIGHT  # y-coordinate of the x-axis line

_ARRAY_COLORS = {
    "idle": "idle",
    "compare": "compare",
    "swap": "swap",
    "highlight": "highlight",
}
_ARRAY_VERB_LABEL = {"compare": "comparing", "swap": "swapping", "highlight": "highlighting"}


def _array_ops_html(anim: Animate, token: str) -> str:
    """Bars occupy fixed slot x-positions expressed as plain SVG attributes (never a
    transform="translate(...)" ATTRIBUTE): animating any transform-family property
    (translateX, scale) makes anime.js set a CSS transform, which fully replaces
    -- does not compose with -- an SVG transform attribute on the same element (see
    .claude/skills/animejs/references/api-reference.md's Gotchas section). Each
    bar's <g> also gets transform-box: fill-box; transform-origin: center so a
    scale-pulse grows from the bar's own visual center, not the SVG viewport's
    (0,0) origin.
    """
    max_value = max(anim.array) or 1
    n = len(anim.array)
    slot_width = _BAR_WIDTH + _BAR_GAP
    width = n * slot_width + _BAR_GAP
    token_seed = re.sub(r"\D", "", token) or "0"

    slot_of_bar = list(range(n))
    # timeline_ops[i] = (verb, a, b) for each op that touches bar i, in order, so
    # each bar's own step sequence (for building per-op color/scale JSON below) is
    # easy to walk without re-deriving slot positions from anim.ops repeatedly.
    bar_ids = [f"anim-bar-{token_seed}-{i}" for i in range(n)]
    rect_ids = [f"anim-rect-{token_seed}-{i}" for i in range(n)]
    caption_id = f"anim-caption-{token_seed}"

    bars_html = []
    for i in range(n):
        value = anim.array[i]
        height = round((value / max_value) * _BAR_MAX_HEIGHT, 1)
        x = _BAR_GAP + i * slot_width
        y = _BAR_BASELINE_Y - height
        bars_html.append(
            f'<g id="{bar_ids[i]}" style="transform-box: fill-box; transform-origin: center;">'
            f'<rect id="{rect_ids[i]}" x="{x}" y="{y}" width="{_BAR_WIDTH}" height="{height}" '
            f'rx="4" fill="var(--anim-array-idle)"></rect>'
            f'<text class="anim__array-label" x="{x + _BAR_WIDTH / 2:g}" '
            f'y="{_BAR_BASELINE_Y + 20}">{html.escape(str(value))}</text>'
            "</g>"
        )

    steps_json = []
    for verb, a, b in anim.ops:
        verb_phrase = _ARRAY_VERB_LABEL[verb]
        if verb == "highlight":
            caption = f"highlighting index {a}"
            steps_json.append({
                "targets": [f"#{rect_ids[a]}"],
                "props": {"fill": ["var(--anim-array-idle)", "var(--anim-array-highlight)", "var(--anim-array-highlight)"]},
                "duration": 900, "ease": "outQuad", "position": "+=300", "caption": caption,
            })
            steps_json.append({
                "targets": [f"#{bar_ids[a]}"],
                "props": {"scale": [1, 1.15, 1]},
                "duration": 900, "ease": "outElastic(1, .6)", "position": "<",
            })
        elif verb == "compare":
            caption = f"comparing index {a} and {b}"
            steps_json.append({
                "targets": [f"#{rect_ids[a]}", f"#{rect_ids[b]}"],
                "props": {"fill": ["var(--anim-array-idle)", "var(--anim-array-compare)", "var(--anim-array-idle)"]},
                "duration": 700, "ease": "inOutQuad", "position": None if not steps_json else "+=300",
                "caption": caption,
            })
            steps_json.append({
                "targets": [f"#{bar_ids[a]}", f"#{bar_ids[b]}"],
                "props": {"scale": [1, 1.08, 1]},
                "duration": 700, "ease": "inOutQuad", "position": "<",
            })
        else:  # swap
            slot_of_bar[a], slot_of_bar[b] = slot_of_bar[b], slot_of_bar[a]
            delta = (slot_of_bar[a] - a) * slot_width  # net displacement for bar a
            caption = f"swapping index {a} and {b}"
            steps_json.append({
                "targets": [f"#{rect_ids[a]}", f"#{rect_ids[b]}"],
                "props": {"fill": ["var(--anim-array-idle)", "var(--anim-array-swap)", "var(--anim-array-idle)"]},
                "duration": 750, "ease": "inOutQuad", "position": "+=300", "caption": caption,
            })
            steps_json.append({
                "targets": [f"#{bar_ids[a]}"], "props": {"translateX": delta},
                "duration": 650, "ease": "inOutBack", "position": "<",
            })
            steps_json.append({
                "targets": [f"#{bar_ids[b]}"], "props": {"translateX": -delta},
                "duration": 650, "ease": "inOutBack", "position": "<",
            })

    # Hold the final state on screen, then snap every bar's transform/fill back to
    # idle right before the loop restarts (the loop-state-drift gotcha) -- a swap
    # must look like a real, sticky reorder (the two Step-2 targets stay swapped
    # through the highlight step), never a bounce-back.
    steps_json.append({"kind": "hold", "duration": 900} if False else {
        "targets": [f"#{bar_ids[0]}"], "props": {}, "duration": 900,
    })
    steps_json.append({
        "kind": "set", "targets": [f"#{b}" for b in bar_ids], "props": {"translateX": 0, "scale": 1},
    })
    steps_json.append({
        "kind": "set", "targets": [f"#{r}" for r in rect_ids], "props": {"fill": "var(--anim-array-idle)"},
    })

    timeline = {"loop": True, "loopDelay": 1200, "steps": steps_json}
    timeline_json = html.escape(json.dumps(timeline), quote=False)

    legend_items = "".join(
        f'<span class="anim__array-legend-item"><span class="anim__array-legend-swatch '
        f'anim__array-legend-swatch--{kind}"></span>{kind}</span>'
        for kind in ("idle", "compare", "swap", "highlight")
    )

    axis_y = _BAR_BASELINE_Y
    mid_y = _BAR_HEADROOM + _BAR_MAX_HEIGHT / 2
    chrome = (
        f'<line class="anim__array-axis" x1="0" y1="{_BAR_HEADROOM - 4}" '
        f'x2="0" y2="{axis_y}"></line>'
        f'<line class="anim__array-axis" x1="0" y1="{axis_y}" x2="{width}" y2="{axis_y}"></line>'
        f'<line class="anim__array-gridline" x1="0" y1="{mid_y:g}" x2="{width}" y2="{mid_y:g}"></line>'
    )

    op_lines = "".join(
        f"<li>{html.escape(verb)} index {a}" + (f" and {b}" if b is not None else "") + "</li>"
        for verb, a, b in anim.ops
    )
    static_fallback = f'<ol class="anim__array-steps-static">{op_lines}</ol>'

    return (
        f'<div class="anim anim--array-ops">'
        f'<p class="anim__caption" id="{caption_id}" data-anim-id="{caption_id}">'
        f"Step 1 of {len(anim.ops)}</p>"
        f'<svg class="anim__array" dir="ltr" viewBox="0 0 {width} {_BAR_BASELINE_Y + 40}">'
        f"{chrome}{''.join(bars_html)}</svg>"
        f'<div class="anim__array-legend">{legend_items}</div>'
        f'<script type="application/json" class="anim__timeline" data-anim-id="{caption_id}">'
        f"{timeline_json}</script>"
        f"{static_fallback}</div>"
    )
```

Note the placeholder-looking `{"kind": "hold", ...} if False else {...}` line: this is a deliberate "hold" step expressed as a no-op animation (`props: {}`) on an already-idle target, giving the timeline 900ms of dwell time before the reset — remove the dead `if False` branch and just keep the dict literal on the right; it was left in to flag this exact spot for cleanup during implementation. Write it simply as:

```python
    steps_json.append({"targets": [f"#{bar_ids[0]}"], "props": {}, "duration": 900})
```

- [ ] **Step 4: Update `layout.css`**

Replace the entire array-ops block (locate by content — was around the old lines 267-298):

```css
.anim--array-ops { text-align: center; }
.anim__caption {
  text-align: center; font-weight: 600; font-size: 1rem; color: var(--color-fg);
  margin: 0 0 var(--space-3);
}
.anim__array {
  width: 100%; height: auto;
  --anim-array-idle: var(--color-border);
  --anim-array-compare: var(--color-warn);
  --anim-array-swap: var(--color-accent);
  --anim-array-highlight: var(--color-correct);
}
.anim__array-axis { stroke: var(--color-fg); stroke-width: 1.5; }
.anim__array-gridline { stroke: var(--color-border); stroke-width: 1; stroke-dasharray: 3,3; }
.anim__array-label {
  font-size: 15px;
  fill: var(--color-fg);
  text-anchor: middle;
}
.anim__array-legend {
  display: flex; gap: var(--space-4); justify-content: center;
  margin-block-start: var(--space-2); font-size: 0.75rem; color: var(--color-muted);
}
.anim__array-legend-swatch {
  display: inline-block; inline-size: 10px; block-size: 10px; border-radius: 2px;
  margin-inline-end: var(--space-1);
}
.anim__array-legend-swatch--idle { background: var(--color-border); }
.anim__array-legend-swatch--compare { background: var(--color-warn); }
.anim__array-legend-swatch--swap { background: var(--color-accent); }
.anim__array-legend-swatch--highlight { background: var(--color-correct); }
.anim__array-steps-static { display: none; }
```

- [ ] **Step 5: Extend `test_layout_css_styles_every_component_the_renderers_emit`**

In `tests/test_assets.py`, modify the selector tuple (lines 121-152) to add the new classes and remove any that no longer exist:

```python
def test_layout_css_styles_every_component_the_renderers_emit():
    css = (ASSETS / "base" / "layout.css").read_text()
    for selector in (
        ".toc",
        ".quiz",
        ".quiz__option",
        ".quiz__why",
        ".term",
        ".term__def",
        ".callout--analogy",
        ".callout--prereq",
        ".callout--unverified",
        ".mermaid",
        ".glossary",
        ".sources-group",
        ".sources",
        ".diagram-fallback",
        ".anim__caption",
        ".anim--array-ops",
        ".anim__array",
        ".anim__array-axis",
        ".anim__array-gridline",
        ".anim__array-label",
        ".anim__array-legend",
        ".anim__array-steps-static",
        ".anim--path-trace",
        ".anim__path",
        ".anim__path-axis",
        ".anim__path-tick",
        ".anim__path-line",
        ".anim__path-marker",
        ".anim__path-caption",
    ):
        assert selector in css, selector
```

(`.anim__path-*` selectors are addressed in Task 7 — leave them in this list now since Task 7 will make them true again; if Task 7 hasn't run yet in your working tree, this test will show those specific selectors failing, which is expected until Task 7 completes. Confirm at the end of Task 6 that only the `.anim__path-*` assertions fail here, nothing else.)

- [ ] **Step 6: Update `print.css`**

Replace lines 42-46 of `assets/print.css` (the current `.anim__array`/`.anim__array-steps-static` print rules):

```css
  .anim__array { display: none !important; }
  .anim__caption { display: none !important; }
  .anim__array-legend { display: none !important; }
  .anim__array-steps-static {
    display: block !important; list-style: decimal !important;
    padding-inline-start: 1.5em !important; margin: 0 !important;
  }
```

- [ ] **Step 7: Run to verify the array-ops rendering test passes**

Run: `.venv/bin/pytest tests/test_mdrender.py::test_array_ops_renders_bars_and_a_timeline_island -v`
Expected: PASS

- [ ] **Step 8: Run the full mdrender and assets test files**

Run: `.venv/bin/pytest tests/test_mdrender.py tests/test_assets.py -v`
Expected: PASS for everything except the `.anim__path-*` selector assertions inside `test_layout_css_styles_every_component_the_renderers_emit` (expected to fail until Task 7) — confirm no other unexpected failures.

- [ ] **Step 9: Run the full suite**

Run: `.venv/bin/pytest -q`
Expected: fails are exactly: the two golden-snapshot tests, plus `test_layout_css_styles_every_component_the_renderers_emit` (path-trace selectors only). Confirm nothing else is broken.

- [ ] **Step 10: Commit**

```bash
git add scripts/p2c/mdrender.py assets/base/layout.css assets/print.css tests/test_mdrender.py tests/test_assets.py
git commit -m "feat: migrate array-ops to anime.js with chart chrome and live captions"
```

---

## Task 7: Migrate `path-trace` to anime.js (gridlines, constant-speed marker, fading trail, live caption)

**Files:**
- Modify: `scripts/p2c/mdrender.py`
- Modify: `assets/base/layout.css`
- Modify: `assets/print.css`
- Test: `tests/test_mdrender.py`

**Interfaces:**
- Produces: `_path_trace_html(anim: Animate, token: str) -> str` (signature gains `token`, matching the other three patterns now — update the dispatch call in `_animate_html`, already done in Task 4 Step 3).

- [ ] **Step 1: Write the failing rendering test**

In `tests/test_mdrender.py`, find and replace the current path-trace rendering test with:

```python
def test_path_trace_renders_gridlines_trail_and_a_timeline_island():
    md = course(
        '<!-- topic: tlb -->\n### The TLB\n\n'
        '```animate\npattern: path-trace\npoints:\n  - 0, 10\n  - 5, 2\n  - 10, 8\n  - 15, 0\n'
        'caption: TLB hit rate rising\n```\n\n'
        '```quiz\nq: q\n- [ ] a\n- [x] b\n- [ ] c\nwhy: because\n```\n\n'
        '```glossary\nTLB: definition\n```\n'
    )
    rendered = render_course(md)
    assert rendered.errors == []
    assert '<line class="anim__path-axis"' in rendered.html_body
    assert '<text class="anim__path-tick"' in rendered.html_body
    assert '<polyline class="anim__path-line"' in rendered.html_body
    assert '<path class="anim__path-trail"' in rendered.html_body
    assert '<circle class="anim__path-marker"' in rendered.html_body
    assert 'class="anim__caption"' in rendered.html_body
    assert '<ol class="anim__path-steps-static">' in rendered.html_body
    assert '<li>from (0, 10) to (5, 2)</li>' in rendered.html_body
    assert '<li>from (5, 2) to (10, 8)</li>' in rendered.html_body
    assert '<li>from (10, 8) to (15, 0)</li>' in rendered.html_body

    match = re.search(
        r'<script type="application/json" class="anim__timeline"[^>]*>(.*?)</script>',
        rendered.html_body,
        re.DOTALL,
    )
    assert match, "no anim__timeline data island found"
    timeline = json.loads(match.group(1))
    assert timeline["loop"] is True
    assert len(timeline["steps"]) == 3  # one per segment (0->5->10->15), reset step(s) come after
    first_caption = [s for s in timeline["steps"] if s.get("caption")][0]["caption"]
    assert first_caption == "Moving from (0, 10) to (5, 2)"
    # Constant visual speed: a longer segment must get a proportionally longer duration.
    durations = [s["duration"] for s in timeline["steps"] if "duration" in s]
    assert durations[1] > durations[0]  # (5,2)->(10,8) is longer than (0,10)->(5,2)
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/pytest tests/test_mdrender.py::test_path_trace_renders_gridlines_trail_and_a_timeline_island -v`
Expected: FAIL (current implementation has no trail, no caption, uses `offset-path`/CSS `@keyframes` instead of a JSON island).

- [ ] **Step 3: Rewrite `_path_trace_html`**

In `scripts/p2c/mdrender.py`, replace the entire current `_path_trace_html` function:

```python
def _path_trace_html(anim: Animate, token: str) -> str:
    token_seed = re.sub(r"\D", "", token) or "0"
    marker_id = f"anim-marker-{token_seed}"
    trail_id = f"anim-trail-{token_seed}"
    caption_id = f"anim-caption-{token_seed}"

    xs = [x for x, _ in anim.points]
    ys = [y for _, y in anim.points]
    data_min_x, data_max_x = min(xs), max(xs)
    data_min_y, data_max_y = min(ys), max(ys)
    min_x, max_x = data_min_x - _PATH_PADDING, data_max_x + _PATH_PADDING
    min_y, max_y = data_min_y - _PATH_PADDING, data_max_y + _PATH_PADDING
    points_attr = " ".join(f"{x:g},{y:g}" for x, y in anim.points)

    axis = (
        f'<line class="anim__path-axis" x1="{min_x:g}" y1="{data_max_y:g}" '
        f'x2="{max_x:g}" y2="{data_max_y:g}"></line>'
        f'<line class="anim__path-axis" x1="{data_min_x:g}" y1="{min_y:g}" '
        f'x2="{data_min_x:g}" y2="{max_y:g}"></line>'
    )
    labels = (
        f'<text class="anim__path-tick" x="{data_min_x:g}" y="{data_max_y + 9:g}">'
        f"{data_min_x:g}</text>"
        f'<text class="anim__path-tick" x="{data_max_x:g}" y="{data_max_y + 9:g}">'
        f"{data_max_x:g}</text>"
        f'<text class="anim__path-tick" x="{data_min_x - 2:g}" y="{data_min_y:g}">'
        f"{data_min_y:g}</text>"
        f'<text class="anim__path-tick" x="{data_min_x - 2:g}" y="{data_max_y:g}">'
        f"{data_max_y:g}</text>"
    )

    x0, y0 = anim.points[0]
    steps_json = []
    for i in range(len(anim.points) - 1):
        fx, fy = anim.points[i]
        tx, ty = anim.points[i + 1]
        segment_length = math.hypot(tx - fx, ty - fy)
        duration = max(300, round(segment_length * _PATH_MS_PER_UNIT))
        steps_json.append({
            "kind": "path-segment",
            "marker": f"#{marker_id}",
            "trail": f"#{trail_id}",
            "from": [fx, fy],
            "to": [tx, ty],
            "duration": duration,
            "ease": "inOutSine",
            "position": None if i == 0 else "+=150",
            "caption": f"Moving from ({fx:g}, {fy:g}) to ({tx:g}, {ty:g})",
        })
    steps_json.append({
        "kind": "set", "targets": [f"#{marker_id}"],
        "props": {"cx": x0, "cy": y0},
    })
    steps_json.append({
        "kind": "set-attr", "targets": [f"#{trail_id}"],
        "props": {"d": f"M {x0:g},{y0:g}"},
    })

    timeline = {"loop": True, "loopDelay": 1200, "steps": steps_json}
    timeline_json = html.escape(json.dumps(timeline), quote=False)

    op_lines = "".join(
        f"<li>from ({fx:g}, {fy:g}) to ({tx:g}, {ty:g})</li>"
        for (fx, fy), (tx, ty) in zip(anim.points, anim.points[1:])
    )
    static_fallback = f'<ol class="anim__path-steps-static">{op_lines}</ol>'

    return (
        '<div class="anim anim--path-trace">'
        f'<p class="anim__caption" id="{caption_id}" data-anim-id="{caption_id}">'
        f"Moving from ({x0:g}, {y0:g})</p>"
        f'<svg class="anim__path" dir="ltr" '
        f'viewBox="{min_x:g} {min_y:g} {max_x - min_x:g} {max_y - min_y:g}">'
        f"{axis}{labels}"
        f'<polyline class="anim__path-line" points="{points_attr}"></polyline>'
        f'<path class="anim__path-trail" id="{trail_id}" d="M {x0:g},{y0:g}"></path>'
        f'<circle class="anim__path-marker" id="{marker_id}" r="1.2" cx="{x0:g}" cy="{y0:g}"></circle>'
        "</svg>"
        f'<script type="application/json" class="anim__timeline" data-anim-id="{caption_id}">'
        f"{timeline_json}</script>"
        f"{static_fallback}</div>"
    )
```

Add `_PATH_MS_PER_UNIT = 90` near the existing `_PATH_PADDING = 10` constant, and add `import math` at the top of the file if not already present (check first).

Note: the `"kind": "path-segment"` and `"kind": "set-attr"` step kinds introduced here are **new additions to the JSON timeline contract** beyond what Task 3 documented (which only covered `"add"`/`"set"` for CSS-transform-style properties). This is expected and necessary — `cx`/`cy`/`d` are SVG *attributes*, not CSS transform properties, so the coordinator needs a distinct code path. This is handled in Step 5 below.

- [ ] **Step 4: Update `layout.css`**

Replace the path-trace block (locate by content):

```css
.anim--path-trace { text-align: center; }
.anim__path { width: 100%; height: auto; max-block-size: 16rem; }
.anim__path-axis { stroke: var(--color-border); stroke-width: 1; }
.anim__path-tick { font-size: 6px; fill: var(--color-muted); }
.anim__path-line { fill: none; stroke: var(--color-border); stroke-width: 2; }
.anim__path-trail { fill: none; stroke: var(--color-accent); stroke-width: 1.2; stroke-linecap: round; opacity: 0.6; }
.anim__path-marker { fill: var(--color-accent); }
.anim__path-caption { margin-block-start: var(--space-2); color: var(--color-muted); font-size: 0.9rem; }
.anim__path-steps-static { display: none; }
```

Remove the now-dead `@keyframes anim-path-travel` rule and the `.anim__path-marker { animation-name: ...}` rule that referenced it (search for `anim-path-travel` to find and delete both).

Also remove the reduced-motion block's now-stale `.anim__path-marker { animation: none; offset-distance: 100%; }` line (in the `@media (prefers-reduced-motion: reduce)` block) — under the new architecture, `wireAnimations()` itself checks `prefers-reduced-motion` in JS and simply never runs, so there is no CSS animation left to disable; the marker just stays at its static starting position (`cx`/`cy` as rendered), which is an acceptable reduced-motion resting frame same as the static fallback list already provides full information.

- [ ] **Step 5: Extend `wireAnimations()` in `course.js` to handle `path-segment`/`set-attr` step kinds**

In `assets/base/course.js`, modify the `wireAnimations()` function added in Task 3 to add two more branches inside the `(data.steps || []).forEach` loop, alongside the existing `"set"` branch:

```javascript
      (data.steps || []).forEach(function (step) {
        if (step.kind === "path-segment") {
          var marker = document.querySelector(step.marker);
          var trail = document.querySelector(step.trail);
          var state = { x: step.from[0], y: step.from[1] };
          var stepCaption = step.caption;
          var addStep = {
            duration: step.duration,
            ease: step.ease,
            x: step.to[0],
            y: step.to[1],
            onBegin: function () {
              if (stepCaption && caption) { caption.textContent = stepCaption; }
            },
            onUpdate: function () {
              if (marker) { marker.setAttribute("cx", state.x); marker.setAttribute("cy", state.y); }
              if (trail) { trail.setAttribute("d", trail.getAttribute("d") + " L " + state.x + "," + state.y); }
            },
          };
          if (step.position) { tl.add(state, addStep, step.position); } else { tl.add(state, addStep); }
          return;
        }
        if (step.kind === "set-attr") {
          (step.targets || []).forEach(function (selector) {
            var el = document.querySelector(selector);
            if (!el) { return; }
            Object.keys(step.props || {}).forEach(function (attr) {
              el.setAttribute(attr, step.props[attr]);
            });
          });
          return;
        }
        var props = {};
        Object.keys(step.props || {}).forEach(function (key) { props[key] = step.props[key]; });
        if (step.caption && caption) {
          props.onBegin = function () { caption.textContent = step.caption; };
        }
        if (step.kind === "set") {
          tl.set(step.targets, props);
        } else if (step.position) {
          tl.add(step.targets, props, step.position);
        } else {
          tl.add(step.targets, props);
        }
      });
```

This replaces the single `(data.steps || []).forEach` block from Task 3 Step 3 — the `path-segment`/`set-attr` branches are checked first (they `return` early), falling through to the original `add`/`set` logic for every other step kind unchanged.

- [ ] **Step 6: Update the DOM-contract test for the new step kinds**

In `tests/test_assets.py`, extend `test_course_js_drives_the_dom_contract_the_renderers_emit`'s hook tuple with `"path-segment"` and `"set-attr"`.

- [ ] **Step 7: Update `print.css`**

Replace line 47 of `assets/print.css` (`.anim__path-marker { animation: none !important; offset-distance: 100% !important; }`) with:

```css
  .anim__path-trail { opacity: 1 !important; }
  .anim__path-steps-static {
    display: block !important; list-style: decimal !important;
    padding-inline-start: 1.5em !important; margin-block-start: 0.5em !important;
  }
```

(the marker/trail stay visible at their static resting position in print — same reasoning as reduced-motion — and the new static step list becomes the primary source of the sequence information on paper, same treatment as array-ops's static fallback.)

- [ ] **Step 8: Run to verify the path-trace rendering test passes**

Run: `.venv/bin/pytest tests/test_mdrender.py::test_path_trace_renders_gridlines_trail_and_a_timeline_island -v`
Expected: PASS

- [ ] **Step 9: Run the full mdrender and assets test files**

Run: `.venv/bin/pytest tests/test_mdrender.py tests/test_assets.py -v`
Expected: PASS — including `test_layout_css_styles_every_component_the_renderers_emit`, which should now be fully green (the `.anim__path-*` gap from Task 6 is closed).

- [ ] **Step 10: Run the full suite**

Run: `.venv/bin/pytest -q`
Expected: all pass except the two golden-snapshot tests (still expected — this is the last task before Task 11 regenerates them, but Tasks 8-10 come first).

- [ ] **Step 11: Commit**

```bash
git add scripts/p2c/mdrender.py assets/base/layout.css assets/print.css assets/base/course.js tests/test_mdrender.py tests/test_assets.py
git commit -m "feat: migrate path-trace to anime.js with fading trail and live caption"
```

---

## Task 8: Update the CSS custom-property token-prefix allowlist

**Files:**
- Modify: `tests/test_assets.py`

**Interfaces:**
- Consumes: the final `layout.css` custom-property usage from Tasks 4-7.

- [ ] **Step 1: Check current custom-property usage in `layout.css`**

Run:
```bash
grep -o 'var(--[a-z0-9-]*' /home/roneng/Presntation2Course/assets/base/layout.css | sort -u
```
Compare the output against `test_layout_css_only_uses_tokens_the_themes_define`'s `layout_owned` prefix set (currently includes `"--space", "--radius", "--measure", "--z-", "--drawer-closed-x", "--anim-array-", "--bar-fill"`). Since Task 6 removed `--bar-fill` (bars now use CSS variables `--anim-array-idle`/`compare`/`swap`/`highlight` directly as literal `fill="var(--anim-array-idle)"` SVG attribute values, not a separate custom property computed per-keyframe), confirm whether `--bar-fill` is still referenced anywhere.

- [ ] **Step 2: Update the allowlist if needed**

If `--bar-fill` no longer appears anywhere in `layout.css` (expected, since Task 6's rewrite sets `fill` directly to `var(--anim-array-idle)` etc. rather than through an intermediate `--bar-fill` custom property), remove it from `tests/test_assets.py`'s `layout_owned` set (currently lines 157-164):

```python
def test_layout_css_only_uses_tokens_the_themes_define():
    css = (ASSETS / "base" / "layout.css").read_text()
    used = set(re.findall(r"var\((--[a-z0-9-]+)", css))
    layout_owned = {
        t
        for t in used
        if t.startswith((
            "--space", "--radius", "--measure", "--z-", "--drawer-closed-x",
            "--anim-array-",
        ))
    }
    assert used - layout_owned <= set(REQUIRED_TOKENS)
```

If `--bar-fill` (or any other now-dead custom property) is still present in `layout.css` from a leftover rule, remove that dead CSS rule instead of keeping the token in the allowlist — a token with no real usage should not be preserved just to keep a test passing.

- [ ] **Step 3: Run the test**

Run: `.venv/bin/pytest tests/test_assets.py::test_layout_css_only_uses_tokens_the_themes_define -v`
Expected: PASS

- [ ] **Step 4: Run the full suite**

Run: `.venv/bin/pytest -q`
Expected: all pass except the two golden-snapshot tests (still expected).

- [ ] **Step 5: Commit**

```bash
git add tests/test_assets.py assets/base/layout.css
git commit -m "chore: drop the dead --bar-fill token from the layout allowlist"
```

---

## Task 9: Update `SKILL.md`/`references/agents/course-writer.md` if either references the old animation mechanism

**Files:**
- Modify: `SKILL.md` (only if it references `@keyframes`/CSS-animation specifics — check first)
- Modify: `references/agents/course-writer.md` (only if it references CSS-animation specifics — check first)

**Interfaces:**
- None — this is a documentation-accuracy task with no code interface.

- [ ] **Step 1: Search for stale references**

Run:
```bash
grep -n "keyframes\|@keyframes\|animation-name\|animation-duration" /home/roneng/Presntation2Course/SKILL.md /home/roneng/Presntation2Course/references/agents/course-writer.md /home/roneng/Presntation2Course/references/quiz-format.md
```

- [ ] **Step 2: Fix any hits**

The `animate` block authoring grammar itself (what a course-writer agent writes in a fenced block) is unchanged by this migration — only the rendering mechanism changed. If any of these files describe the *rendered output* in terms of CSS animation internals (as opposed to just the authoring grammar, which stays the same), update that prose to describe the new mechanism at a high level (anime.js timeline, JSON data island) without going into implementation depth these docs don't need. If nothing describes rendering internals (likely — these docs are typically scoped to the authoring grammar, not the renderer), no change is needed; state that explicitly rather than inventing an edit.

- [ ] **Step 3: If changes were made, run the doc test suite**

Run: `.venv/bin/pytest tests/test_skill.py -v`
Expected: PASS

- [ ] **Step 4: Commit (only if Step 2 made changes)**

```bash
git add SKILL.md references/agents/course-writer.md references/quiz-format.md
git commit -m "docs: describe the anime.js rendering mechanism where prose referenced the old one"
```

If Step 2 found nothing to change, skip this commit entirely — do not create an empty commit.

---

## Task 10: End-to-end manual verification in a real build

**Files:** none modified — this task is verification only.

- [ ] **Step 1: Build a real course exercising all four patterns**

Run (adjust paths if the repo's existing fixture/test course layout differs — check `tests/fixtures/` and `tests/golden/` for the exact mini-course fixture used elsewhere in this plan, e.g. `MINI` in `tests/test_build.py`):

```bash
cd /home/roneng/Presntation2Course
PYTHONPATH=scripts .venv/bin/python -c "
from pathlib import Path
from p2c.build import build
result = build(
    Path('tests/fixtures/mini/outline.json'),
    Path('tests/fixtures/mini/modules'),
    Path('/tmp/claude-1000/-home-roneng-Presntation2Course/56d939a6-83ea-40d4-8902-6a26a02ee792/scratchpad/anime-verify'),
    Path('assets'),
)
print(result.course_html)
"
```

(Locate the actual mini-fixture path first with `find /home/roneng/Presntation2Course/tests -iname "outline.json"` if the guessed path above doesn't exist — use whatever `MINI` resolves to in `tests/test_build.py`.)

- [ ] **Step 2: Confirm the invariants checker passes**

Run:
```bash
PYTHONPATH=scripts .venv/bin/python -m p2c.invariants /tmp/claude-1000/-home-roneng-Presntation2Course/56d939a6-83ea-40d4-8902-6a26a02ee792/scratchpad/anime-verify
```
Expected: no output (or explicit "no problems found" per however this script currently reports success — check `scripts/p2c/invariants.py`'s `main()` for its exact success-case output before running, so you know what "passing" looks like).

- [ ] **Step 3: Open the built HTML in a real browser and check all four patterns visually**

Use the `run` skill (or open the file directly) to load the built `course_html` path from Step 1 in an actual browser. Confirm for each pattern that appears in the fixture:
- `step-reveal`: list items fade/bold in and out in sequence, looping.
- `state-toggle`: before/after crossfade smoothly, looping.
- `array-ops` (if the fixture doesn't include one, add a temporary `animate` block with `pattern: array-ops` to a fixture module for this check, then revert the fixture change before committing anything — this is a manual check, not a permanent fixture edit): bars stay inside the frame throughout, the swap step's two bars physically end up in each other's slots and stay there through the highlight step, the caption updates through all 3 steps, and everything resets cleanly at the start of the next loop with no visible jump/flash.
- `path-trace`: the marker moves at a visually constant speed across the segments, leaves a visible fading trail, the caption names the current segment, and it resets cleanly between loops.
- With browser devtools' "prefers-reduced-motion: reduce" emulation turned on, reload and confirm every pattern shows its static fallback content instead (no motion at all, and the `anime.js` library's `window.anime` global should never even be invoked — you can confirm this by checking that no console errors appear and the static fallback lists are what's visible).

- [ ] **Step 4: Report findings**

If anything looks wrong, treat it as a bug in whichever Task (4-7) produced that pattern — go back and fix it there (re-running that task's tests), rather than patching around it here. This task does not modify code itself; it only verifies Tasks 1-9 actually produced correct, real-browser behavior matching the verified mockups.

---

## Task 11: Regenerate golden snapshots (final task)

**Files:**
- Modify: `tests/golden/course.html`
- Modify: `tests/golden/course-he.html`

**Interfaces:** none — this is a mechanical regeneration step.

- [ ] **Step 1: Confirm every other test is green first**

Run: `.venv/bin/pytest -q --deselect tests/test_build.py -k golden`

(Adjust the deselect expression to match however the golden tests are actually named/marked in `tests/test_build.py` — find them first with `grep -n "golden" tests/test_build.py`.)

Expected: everything else passes. If anything besides the golden tests is still failing at this point, stop and fix it before regenerating — regenerating golden snapshots over an otherwise-broken suite would bake bugs into the new baseline.

- [ ] **Step 2: Regenerate**

Run:
```bash
P2C_UPDATE_GOLDEN=1 .venv/bin/pytest tests/test_build.py -k golden -v
```

- [ ] **Step 3: Review the diff manually before trusting it**

Run:
```bash
git diff tests/golden/course.html tests/golden/course-he.html | head -300
```

Confirm the diff is entirely explained by this migration: `{{ANIME_JS}}` content now present, old `@keyframes`/`animation-*` inline styles gone, new `anim__timeline` JSON islands present, new array-ops/path-trace markup (legend, caption, gridlines, trail) present. If the diff contains anything unexplained by this plan (e.g. unrelated whitespace churn, a change to a part of the page this migration never touched), stop and investigate before proceeding — do not commit an unreviewed golden diff.

- [ ] **Step 4: Run the full suite one final time**

Run: `.venv/bin/pytest -q`
Expected: 100% pass, zero failures (only the pre-existing, unrelated skips for `soffice`/Chromium/`P2C_COURSE_DIR` should remain as skips, not failures).

- [ ] **Step 5: Commit**

```bash
git add tests/golden/course.html tests/golden/course-he.html
git commit -m "test: regenerate golden snapshots for the anime.js animation migration"
```

---

## Self-Review Notes

- **Spec coverage:** vendoring (Task 1) ✓, `uses_animate`/`inline_anime` threading (Task 2) ✓, JS coordinator (Task 3) ✓, all four patterns migrated (Tasks 4-7) ✓, array-ops chart chrome/legend/caption (Task 6) ✓, path-trace gridlines/trail/caption/constant-speed (Task 7) ✓, both documented gotchas applied in the actual array-ops implementation (Task 6: plain attributes not transform, `transform-box: fill-box`, final `set` reset pair) ✓, token-safety via digits-only `token_seed` (every pattern) ✓, `dir="ltr"` preserved (Tasks 6-7) ✓, CSS logical properties only (all CSS edits use `inset-inline-*`/`margin-block-*`/`inline-size`/`block-size`, no `left`/`right`) ✓, one-time golden regeneration at the end (Task 11) ✓, no new pattern types (confirmed — only the four existing ones appear anywhere in this plan) ✓.
- **Placeholder scan:** the one `if False else` construct in Task 6 Step 3 is intentionally flagged and immediately resolved in the same step with the exact final code to write — not a deferred TODO.
- **Type/name consistency:** `_step_reveal_html`, `_state_toggle_html`, `_array_ops_html`, `_path_trace_html` all take `(anim: Animate, token: str)` consistently from Task 4 onward; `wireAnimations()` is named identically everywhere it's referenced (Tasks 3, 7, tests); the JSON timeline contract's field names (`loop`, `loopDelay`, `steps`, `targets`, `props`, `duration`, `ease`, `position`, `caption`, `kind`) are used identically by every pattern's Python emitter and by `course.js`'s interpreter.
