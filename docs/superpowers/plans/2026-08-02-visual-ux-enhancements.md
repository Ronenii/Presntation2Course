# Six Visual/UX Enhancements Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add two new bounded `animate` patterns, center the reading column, add an
off-canvas mobile nav drawer, fix a glossary popover layout-reflow bug, surface an
end-of-course Sources section, and make quizzes collapsible via `<details>`.

**Architecture:** All six changes extend the existing deterministic-rendering
pipeline (`scripts/p2c/*.py` produces HTML from structured/markdown input; themes
in `assets/` are static CSS/JS/HTML strings substituted into a template). No new
runtime dependencies, no new agent dispatches, no JS framework, no pixel/visual
testing — every new behavior is verified the same way the existing suite verifies
everything: dataclass equality, literal HTML/CSS/JS substring assertions, and
whole-file golden snapshots.

**Tech Stack:** Python 3.12 (stdlib `re`/`dataclasses`/`html` only), vanilla CSS
(logical properties throughout), vanilla JS (no framework), `pytest`.

## Global Constraints

- No new pip packages, no new JS libraries, no network requests at view time.
- CSS: logical properties only (`margin-inline`, `border-inline-start`,
  `inset-inline-start`, etc.) — never `left`/`right`/physical `margin-left` etc.
  Two precedented exceptions exist for content that's inherently direction-agnostic
  (`.mermaid { direction: ltr }`, printed URL suffixes) — any new one must be
  justified the same way, not invented ad hoc.
- HTML generation stays 100% deterministic Python (`html.escape` everywhere user
  content is interpolated) — course-writer/agents supply data, never markup.
- Test philosophy: dataclass equality, `pytest.raises(..., match=...)` exact
  substrings, literal HTML/CSS/JS substring assertions, and golden whole-file
  snapshots (`tests/golden/course.html`, `tests/golden/course-he.html`,
  regenerated via `P2C_UPDATE_GOLDEN=1 .venv/bin/pytest tests/test_build.py -k golden`).
  No pixel/screenshot/headless-browser testing anywhere.
- Every new CSS selector referenced by Python-generated HTML must appear in
  `assets/base/layout.css`'s selector-coverage test
  (`tests/test_assets.py::test_layout_css_styles_every_component_the_renderers_emit`).
- Every new `var(--...)` reference in `layout.css` must resolve to something in
  `p2c.theme.REQUIRED_TOKENS` or start with `--space`/`--radius`/`--measure`
  (`test_layout_css_only_uses_tokens_the_themes_define`) — new non-color custom
  properties (z-index scale, drawer transform) must be added to that allowed-prefix
  set in the same task that introduces them.
- Golden fixtures are regenerated **exactly once**, in the final task, after every
  other task's asset edits have landed — not per task. Do not run
  `P2C_UPDATE_GOLDEN=1` in any task before the last one.

---

### Task 1: `array-ops` animate pattern — parsing

**Files:**
- Modify: `scripts/p2c/mdrender.py:92-157` (constants, `Animate` dataclass, `parse_animate`)
- Test: `tests/test_mdrender.py`

**Interfaces:**
- Consumes: existing `Animate` dataclass, `_ANIMATE_KEY`/`_ANIMATE_STEP` regexes,
  `AnimateError`, `parse_animate` (all in `scripts/p2c/mdrender.py`).
- Produces: `Animate.array: list[int]`, `Animate.ops: list[tuple[str, int, int | None]]`
  fields; `parse_animate` accepts `pattern: array-ops`. Later tasks (Task 3 for
  rendering, Task 9 for docs) rely on these exact field names and the op-tuple shape
  `(verb, a, b)` where `b` is `None` for `highlight`.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_mdrender.py` (near the existing `test_parse_animate_*` tests):

```python
def test_parse_animate_array_ops():
    anim = parse_animate(
        "pattern: array-ops\narray:\n  - 5\n  - 3\n  - 8\n  - 1\n"
        "ops:\n  - compare 0 1\n  - swap 0 1\n  - highlight 2"
    )
    assert anim == Animate(
        pattern="array-ops",
        array=[5, 3, 8, 1],
        ops=[("compare", 0, 1), ("swap", 0, 1), ("highlight", 2, None)],
    )


def test_parse_animate_array_ops_rejects_too_few_values():
    with pytest.raises(AnimateError, match="at least 2 array values"):
        parse_animate("pattern: array-ops\narray:\n  - 5\nops:\n  - highlight 0")


def test_parse_animate_array_ops_rejects_a_non_integer_value():
    with pytest.raises(AnimateError, match="array item 'five' is not an integer"):
        parse_animate(
            "pattern: array-ops\narray:\n  - five\n  - 3\nops:\n  - highlight 0"
        )


def test_parse_animate_array_ops_rejects_no_ops():
    with pytest.raises(AnimateError, match="at least one op"):
        parse_animate("pattern: array-ops\narray:\n  - 1\n  - 2\nops:")


def test_parse_animate_array_ops_rejects_a_malformed_op():
    with pytest.raises(AnimateError, match="invalid array-ops operation: 'flip 0'"):
        parse_animate(
            "pattern: array-ops\narray:\n  - 1\n  - 2\nops:\n  - flip 0"
        )


def test_parse_animate_array_ops_rejects_compare_with_one_index():
    with pytest.raises(AnimateError, match="invalid array-ops operation: 'compare 0'"):
        parse_animate(
            "pattern: array-ops\narray:\n  - 1\n  - 2\nops:\n  - compare 0"
        )


def test_parse_animate_array_ops_rejects_highlight_with_two_indices():
    with pytest.raises(AnimateError, match="invalid array-ops operation: 'highlight 0 1'"):
        parse_animate(
            "pattern: array-ops\narray:\n  - 1\n  - 2\nops:\n  - highlight 0 1"
        )


def test_parse_animate_array_ops_rejects_an_out_of_range_index():
    with pytest.raises(AnimateError, match=r"index 2 out of range for array of length 2"):
        parse_animate(
            "pattern: array-ops\narray:\n  - 1\n  - 2\nops:\n  - highlight 2"
        )


def test_parse_animate_array_ops_rejects_before_after():
    with pytest.raises(AnimateError, match="array-ops does not use 'before:'/'after:'"):
        parse_animate(
            "pattern: array-ops\narray:\n  - 1\n  - 2\nops:\n  - highlight 0\nbefore: x"
        )
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /home/roneng/Presntation2Course && .venv/bin/pytest tests/test_mdrender.py -k array_ops -v`
Expected: FAIL (`Animate.__init__() got an unexpected keyword argument 'array'` or similar).

- [ ] **Step 3: Implement**

In `scripts/p2c/mdrender.py`, replace the constants/dataclass/parser block
(currently lines 92-157) with:

```python
STEP_SECONDS = 2

_ANIMATE_KEY = re.compile(r"^(?P<key>pattern|before|after|caption):\s*(?P<value>.*)$")
_ANIMATE_STEP = re.compile(r"^\s*-\s*(?P<text>.+)$")
_ARRAY_OP = re.compile(
    r"^(?P<verb>compare|swap|highlight)\s+(?P<a>\d+)(?:\s+(?P<b>\d+))?$"
)


class AnimateError(ValueError):
    """An animate block that does not satisfy the grammar."""


@dataclass
class Animate:
    pattern: str
    steps: list[str] = field(default_factory=list)
    before: str = ""
    after: str = ""
    array: list[int] = field(default_factory=list)
    ops: list[tuple[str, int, int | None]] = field(default_factory=list)
    points: list[tuple[float, float]] = field(default_factory=list)
    caption: str = ""


_LIST_HEADERS = {"steps:": "steps", "array:": "array", "ops:": "ops", "points:": "points"}


def parse_animate(body: str) -> Animate:
    pattern: str | None = None
    steps: list[str] = []
    before: str | None = None
    after: str | None = None
    array_raw: list[str] = []
    ops_raw: list[str] = []
    points_raw: list[str] = []
    caption: str | None = None
    section: str | None = None

    lists = {"steps": steps, "array": array_raw, "ops": ops_raw, "points": points_raw}

    for raw in body.split("\n"):
        line = raw.rstrip()
        if not line.strip():
            continue
        item = _ANIMATE_STEP.match(line) if section else None
        if item:
            lists[section].append(item.group("text").strip())
            continue
        key = _ANIMATE_KEY.match(line)
        if key:
            name, value = key.group("key"), key.group("value").strip()
            section = None
            if name == "pattern":
                if pattern is not None:
                    raise AnimateError("animate has more than one 'pattern:' line")
                pattern = value
            elif name == "before":
                before = value
            elif name == "after":
                after = value
            else:
                caption = value
            continue
        if line.strip() in _LIST_HEADERS:
            section = _LIST_HEADERS[line.strip()]
            continue
        raise AnimateError(f"unrecognised line in animate block: {line.strip()!r}")

    if pattern not in ("step-reveal", "state-toggle", "array-ops", "path-trace"):
        raise AnimateError(
            "animate pattern must be 'step-reveal', 'state-toggle', 'array-ops', "
            f"or 'path-trace', got {pattern!r}"
        )

    if pattern == "step-reveal":
        if len(steps) < 2:
            raise AnimateError("step-reveal needs at least 2 steps")
        if before or after or array_raw or ops_raw or points_raw or caption:
            raise AnimateError("step-reveal does not use 'before:'/'after:'")
    elif pattern == "state-toggle":
        if not before or not after:
            raise AnimateError("state-toggle needs both 'before:' and 'after:'")
        if steps or array_raw or ops_raw or points_raw or caption:
            raise AnimateError("state-toggle does not use 'steps:'")
    elif pattern == "array-ops":
        if before or after or steps or points_raw or caption:
            raise AnimateError("array-ops does not use 'before:'/'after:'")
        if len(array_raw) < 2:
            raise AnimateError("array-ops needs at least 2 array values")
        array: list[int] = []
        for item in array_raw:
            try:
                array.append(int(item))
            except ValueError:
                raise AnimateError(f"array item {item!r} is not an integer") from None
        if not ops_raw:
            raise AnimateError("array-ops needs at least one op")
        ops: list[tuple[str, int, int | None]] = []
        for line in ops_raw:
            match = _ARRAY_OP.match(line)
            if not match:
                raise AnimateError(f"invalid array-ops operation: {line!r}")
            verb, a, b = match.group("verb"), int(match.group("a")), match.group("b")
            if verb == "highlight":
                if b is not None:
                    raise AnimateError(f"invalid array-ops operation: {line!r}")
                b_val = None
            else:
                if b is None:
                    raise AnimateError(f"invalid array-ops operation: {line!r}")
                b_val = int(b)
            for idx in (a, b_val):
                if idx is not None and idx >= len(array):
                    raise AnimateError(
                        f"array-ops index {idx} out of range for array of length {len(array)}"
                    )
            ops.append((verb, a, b_val))
        return Animate(pattern=pattern, array=array, ops=ops)
    else:  # path-trace
        if before or after or steps or array_raw or ops_raw:
            raise AnimateError("path-trace does not use 'before:'/'after:'")
        if len(points_raw) < 2:
            raise AnimateError("path-trace needs at least 2 points")
        points: list[tuple[float, float]] = []
        for item in points_raw:
            match = re.match(r"^(-?\d+(?:\.\d+)?)\s*,\s*(-?\d+(?:\.\d+)?)$", item)
            if not match:
                raise AnimateError(f"invalid path-trace point: {item!r}")
            points.append((float(match.group(1)), float(match.group(2))))
        if not caption:
            raise AnimateError("path-trace needs 'caption:'")
        return Animate(pattern=pattern, points=points, caption=caption)

    return Animate(pattern=pattern, steps=steps, before=before or "", after=after or "")
```

Note: the `array-ops`/`path-trace` branches `return` directly (each builds its own
`Animate`); `step-reveal`/`state-toggle` fall through to the shared `return` at the
bottom, preserving today's exact behavior/object shape for those two.

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_mdrender.py -v`
Expected: PASS (all existing + new tests, including the untouched `step-reveal`/
`state-toggle` tests — confirms no regression).

- [ ] **Step 5: Commit**

```bash
git add scripts/p2c/mdrender.py tests/test_mdrender.py
git commit -m "feat: parse array-ops animate blocks"
```

---

### Task 2: `path-trace` animate pattern — parsing

**Files:**
- Modify: `scripts/p2c/mdrender.py` (already extended in Task 1 — this task adds tests only, since the parser branch was written in Task 1 for both patterns together)
- Test: `tests/test_mdrender.py`

**Interfaces:**
- Consumes: `Animate.points: list[tuple[float, float]]`, `Animate.caption: str`
  (added in Task 1).
- Produces: confirms the `path-trace` parser contract for Task 3's renderer.

- [ ] **Step 1: Write the failing tests**

```python
def test_parse_animate_path_trace():
    anim = parse_animate(
        "pattern: path-trace\npoints:\n  - 0, 10\n  - 5, 2\n  - 10, 8\n  - 15, 0\n"
        "caption: Gradient descent converging toward the minimum"
    )
    assert anim == Animate(
        pattern="path-trace",
        points=[(0.0, 10.0), (5.0, 2.0), (10.0, 8.0), (15.0, 0.0)],
        caption="Gradient descent converging toward the minimum",
    )


def test_parse_animate_path_trace_rejects_one_point():
    with pytest.raises(AnimateError, match="at least 2 points"):
        parse_animate("pattern: path-trace\npoints:\n  - 0, 0\ncaption: c")


def test_parse_animate_path_trace_rejects_a_malformed_point():
    with pytest.raises(AnimateError, match=r"invalid path-trace point: 'not-a-point'"):
        parse_animate(
            "pattern: path-trace\npoints:\n  - 0, 0\n  - not-a-point\ncaption: c"
        )


def test_parse_animate_path_trace_rejects_missing_caption():
    with pytest.raises(AnimateError, match="path-trace needs 'caption:'"):
        parse_animate("pattern: path-trace\npoints:\n  - 0, 0\n  - 1, 1")


def test_parse_animate_path_trace_rejects_steps():
    with pytest.raises(AnimateError, match="path-trace does not use 'before:'/'after:'"):
        parse_animate(
            "pattern: path-trace\npoints:\n  - 0, 0\n  - 1, 1\ncaption: c\nbefore: x"
        )
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_mdrender.py -k path_trace -v`
Expected: since Task 1 already implemented the parser branch, this may already
PASS. If it does, that's fine — this task exists to lock the contract down with
tests; if any assertion fails, fix the Task 1 parser branch to match (the parser
code is the same one Task 1 wrote).

- [ ] **Step 3: Run full mdrender test file to confirm no regression**

Run: `.venv/bin/pytest tests/test_mdrender.py -v`
Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add tests/test_mdrender.py
git commit -m "test: lock down path-trace animate parsing contract"
```

---

### Task 3: Render `array-ops` and `path-trace` to HTML

**Files:**
- Modify: `scripts/p2c/mdrender.py` (`_animate_html`)
- Test: `tests/test_mdrender.py`

**Interfaces:**
- Consumes: `Animate` dataclass from Tasks 1-2 (`array`, `ops`, `points`, `caption` fields).
- Produces: `_animate_html(anim)` handles all four patterns. HTML/CSS contract that
  Task 4 (CSS) and Task 9 (docs) depend on:
  - `array-ops` renders `<div class="anim anim--array-ops"><svg class="anim__array" viewBox="0 0 {W} {H}">...<rect class="anim__array-bar" style="--bar-x: {x}; --bar-w: {w}; --bar-h: {h}; --op-a: {a}; --op-b: {b}; --op-kind: {kind}; animation-delay: {delay}s">...</rect>...</svg></div>` — see exact code below.
  - `path-trace` renders `<div class="anim anim--path-trace"><svg class="anim__path" viewBox="{minx} {miny} {w} {h}" dir="ltr"><polyline class="anim__path-line" points="{pts}"></polyline><circle class="anim__path-marker" style="offset-path: path('{d}')"></circle></svg><p class="anim__path-caption">{caption}</p></div>`.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_mdrender.py`, following the `course(...)` fixture helper already
used by `test_step_reveal_renders_with_staggered_negative_delays` etc.:

```python
def test_array_ops_renders_bars_and_ops():
    md = course(
        '<!-- topic: tlb -->\n### The TLB\n\n'
        '```animate\npattern: array-ops\narray:\n  - 5\n  - 3\n  - 8\n'
        'ops:\n  - compare 0 1\n  - swap 0 1\n```\n\n'
        '```quiz\nq: q\n- [ ] a\n- [x] b\n- [ ] c\nwhy: because\n```\n\n'
        '```glossary\nTLB: definition\n```\n'
    )
    rendered = render_course(md)
    assert rendered.errors == []
    assert '<div class="anim anim--array-ops">' in rendered.html_body
    assert 'class="anim__array"' in rendered.html_body
    assert rendered.html_body.count('class="anim__array-bar"') == 3
    assert "--op-kind: compare" in rendered.html_body
    assert "--op-kind: swap" in rendered.html_body


def test_path_trace_renders_polyline_and_marker():
    md = course(
        '<!-- topic: tlb -->\n### The TLB\n\n'
        '```animate\npattern: path-trace\npoints:\n  - 0, 10\n  - 5, 2\n  - 10, 8\n'
        'caption: Converging toward the minimum\n```\n\n'
        '```quiz\nq: q\n- [ ] a\n- [x] b\n- [ ] c\nwhy: because\n```\n\n'
        '```glossary\nTLB: definition\n```\n'
    )
    rendered = render_course(md)
    assert rendered.errors == []
    assert '<div class="anim anim--path-trace">' in rendered.html_body
    assert 'class="anim__path"' in rendered.html_body
    assert 'dir="ltr"' in rendered.html_body
    assert 'points="0,10 5,2 10,8"' in rendered.html_body
    assert 'class="anim__path-marker"' in rendered.html_body
    assert '<p class="anim__path-caption">Converging toward the minimum</p>' in rendered.html_body


def test_a_broken_array_ops_block_becomes_an_error_not_a_crash():
    md = course(
        '<!-- topic: tlb -->\n### The TLB\n\n'
        '```animate\npattern: array-ops\narray:\n  - 1\nops:\n  - highlight 0\n```\n\n'
        '```quiz\nq: q\n- [ ] a\n- [x] b\n- [ ] c\nwhy: because\n```\n\n'
        '```glossary\nTLB: definition\n```\n'
    )
    rendered = render_course(md)
    assert any("array-ops" in e for e in rendered.errors)


def test_a_broken_path_trace_block_becomes_an_error_not_a_crash():
    md = course(
        '<!-- topic: tlb -->\n### The TLB\n\n'
        '```animate\npattern: path-trace\npoints:\n  - 0, 0\ncaption: c\n```\n\n'
        '```quiz\nq: q\n- [ ] a\n- [x] b\n- [ ] c\nwhy: because\n```\n\n'
        '```glossary\nTLB: definition\n```\n'
    )
    rendered = render_course(md)
    assert any("path-trace" in e for e in rendered.errors)


def test_an_array_ops_block_also_counts_as_a_visual():
    md = course(
        '<!-- topic: bare -->\n### Bare topic\n\n'
        '```animate\npattern: array-ops\narray:\n  - 1\n  - 2\nops:\n  - highlight 0\n```\n\n'
        '```quiz\nq: q\n- [ ] a\n- [x] b\n- [ ] c\nwhy: because\n```\n'
    )
    rendered = render_course(md)
    assert rendered.topics_missing_visual == []


def test_a_path_trace_block_also_counts_as_a_visual():
    md = course(
        '<!-- topic: bare -->\n### Bare topic\n\n'
        '```animate\npattern: path-trace\npoints:\n  - 0, 0\n  - 1, 1\ncaption: c\n```\n\n'
        '```quiz\nq: q\n- [ ] a\n- [x] b\n- [ ] c\nwhy: because\n```\n'
    )
    rendered = render_course(md)
    assert rendered.topics_missing_visual == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_mdrender.py -k "array_ops_renders or path_trace_renders or broken_array_ops or broken_path_trace or also_counts_as_a_visual" -v`
Expected: FAIL (`_animate_html` doesn't yet branch on the new patterns — will
raise/return wrong content for `array-ops`/`path-trace`).

- [ ] **Step 3: Implement**

Replace `_animate_html` (currently `mdrender.py:160-181`) with:

```python
_BAR_WIDTH = 32
_BAR_GAP = 12
_BAR_MAX_HEIGHT = 120
_PATH_PADDING = 10


def _animate_html(anim: Animate) -> str:
    if anim.pattern == "step-reveal":
        cycle = len(anim.steps) * STEP_SECONDS
        items = "".join(
            f'<li class="anim__step" style="animation-duration: {cycle}s; '
            f'animation-delay: {-(i * STEP_SECONDS)}s">{html.escape(step)}</li>'
            for i, step in enumerate(anim.steps)
        )
        return f'<div class="anim anim--step-reveal"><ol class="anim__steps">{items}</ol></div>'
    if anim.pattern == "state-toggle":
        # "Before"/"After" are literal English UI chrome -- like the "Analogy" callout
        # label, added by the render layer rather than the course-writer, so they stay
        # legible regardless of course language (including RTL). They are hidden during
        # normal animated playback and shown only in the print/reduced-motion static
        # presentation; see .anim__state-label in layout.css/print.css.
        return (
            '<div class="anim anim--state-toggle">'
            '<div class="anim__state anim__state--before">'
            f'<span class="anim__state-label">Before</span>{html.escape(anim.before)}</div>'
            '<div class="anim__state anim__state--after">'
            f'<span class="anim__state-label">After</span>{html.escape(anim.after)}</div>'
            '</div>'
        )
    if anim.pattern == "array-ops":
        max_value = max(anim.array) or 1
        width = len(anim.array) * (_BAR_WIDTH + _BAR_GAP)
        bars = []
        for i, value in enumerate(anim.array):
            x = i * (_BAR_WIDTH + _BAR_GAP)
            h = round((value / max_value) * _BAR_MAX_HEIGHT, 1)
            y = _BAR_MAX_HEIGHT - h
            bars.append((x, y, h))
        cycle = len(anim.ops) * STEP_SECONDS
        rects = []
        for i, (verb, a, b) in enumerate(anim.ops):
            x, y, h = bars[a]
            delay = -(i * STEP_SECONDS)
            b_attr = b if b is not None else a
            rects.append(
                f'<rect class="anim__array-bar" x="{x}" y="{y}" '
                f'width="{_BAR_WIDTH}" height="{h}" '
                f'style="--op-a: {a}; --op-b: {b_attr}; --op-kind: {verb}; '
                f'animation-duration: {cycle}s; animation-delay: {delay}s"></rect>'
            )
        # Every bar not touched by any op still needs to render (a static rect),
        # so draw the full static set first, then the animated/highlighted ones
        # on top -- op indices reference the same x/y/h computed above.
        static_bars = "".join(
            f'<rect class="anim__array-bar" x="{x}" y="{y}" width="{_BAR_WIDTH}" height="{h}"></rect>'
            for x, y, h in bars
        )
        return (
            f'<div class="anim anim--array-ops"><svg class="anim__array" '
            f'viewBox="0 0 {width} {_BAR_MAX_HEIGHT}">{static_bars}{"".join(rects)}</svg></div>'
        )
    # path-trace
    xs = [x for x, _ in anim.points]
    ys = [y for _, y in anim.points]
    min_x, max_x = min(xs) - _PATH_PADDING, max(xs) + _PATH_PADDING
    min_y, max_y = min(ys) - _PATH_PADDING, max(ys) + _PATH_PADDING
    points_attr = " ".join(f"{x:g},{y:g}" for x, y in anim.points)
    path_d = "M " + " L ".join(f"{x:g},{y:g}" for x, y in anim.points)
    return (
        '<div class="anim anim--path-trace">'
        f'<svg class="anim__path" dir="ltr" '
        f'viewBox="{min_x:g} {min_y:g} {max_x - min_x:g} {max_y - min_y:g}">'
        f'<polyline class="anim__path-line" points="{points_attr}"></polyline>'
        f'<circle class="anim__path-marker" r="4" '
        f"style=\"offset-path: path('{path_d}')\"></circle>"
        "</svg>"
        f'<p class="anim__path-caption">{html.escape(anim.caption)}</p>'
        "</div>"
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_mdrender.py -v`
Expected: PASS (all tests, including pre-existing `step-reveal`/`state-toggle` ones).

- [ ] **Step 5: Commit**

```bash
git add scripts/p2c/mdrender.py tests/test_mdrender.py
git commit -m "feat: render array-ops and path-trace animate blocks to SVG"
```

---

### Task 4: CSS for `array-ops` and `path-trace`

**Files:**
- Modify: `assets/base/layout.css` (append after the existing `.anim` block, currently ending at line 216)
- Modify: `assets/print.css` (append near the existing `.anim` print rules, lines 14-21)
- Test: `tests/test_assets.py`

**Interfaces:**
- Consumes: the exact class names from Task 3 (`.anim--array-ops`, `.anim__array`,
  `.anim__array-bar`, `.anim--path-trace`, `.anim__path`, `.anim__path-line`,
  `.anim__path-marker`, `.anim__path-caption`) and the inline custom properties
  (`--op-a`, `--op-b`, `--op-kind`).
- Produces: visual styling + reduced-motion/print static fallback for both patterns.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_assets.py`, extending the existing selector-coverage test:

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
        ".diagram-fallback",
        ".anim--array-ops",
        ".anim__array",
        ".anim__array-bar",
        ".anim--path-trace",
        ".anim__path",
        ".anim__path-line",
        ".anim__path-marker",
        ".anim__path-caption",
    ):
        assert selector in css, selector
```

(This replaces the existing test body — same function, extended tuple.)

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_assets.py::test_layout_css_styles_every_component_the_renderers_emit -v`
Expected: FAIL (new selectors not yet in `layout.css`).

- [ ] **Step 3: Implement — append to `assets/base/layout.css`**

Add after line 216 (the end of the existing reduced-motion block):

```css

.anim__array { width: 100%; height: auto; }
.anim__array-bar {
  fill: var(--color-accent);
  opacity: 0.55;
}
.anim__array-bar[style*="--op-kind: compare"],
.anim__array-bar[style*="--op-kind: swap"],
.anim__array-bar[style*="--op-kind: highlight"] {
  animation-name: anim-array-highlight;
  animation-timing-function: ease-in-out;
  animation-iteration-count: infinite;
}
@keyframes anim-array-highlight {
  0%   { opacity: 1; }
  15%  { opacity: 1; }
  25%  { opacity: 0.55; }
  100% { opacity: 0.55; }
}

.anim--path-trace { text-align: center; }
.anim__path { width: 100%; height: auto; max-block-size: 16rem; }
.anim__path-line {
  fill: none;
  stroke: var(--color-border);
  stroke-width: 2;
}
.anim__path-marker {
  fill: var(--color-accent);
  offset-distance: 0%;
  animation-name: anim-path-travel;
  animation-duration: 4s;
  animation-timing-function: linear;
  animation-iteration-count: infinite;
}
@keyframes anim-path-travel {
  from { offset-distance: 0%; }
  to   { offset-distance: 100%; }
}
.anim__path-caption { margin-block-start: var(--space-2); color: var(--color-muted); font-size: 0.9rem; }

@media (prefers-reduced-motion: reduce) {
  .anim__array-bar { animation: none; opacity: 1; }
  .anim__path-marker { animation: none; offset-distance: 100%; }
}
```

Note: this final `@media (prefers-reduced-motion: reduce)` block is a **second**
block in the file (the existing one at line 206 stays untouched — it's simpler and
lower-risk to append a second scoped block than to merge into the existing one and
risk disturbing its current content). Both blocks apply under the same media query;
CSS allows repeated `@media` blocks freely.

- [ ] **Step 4: Implement — append to `assets/print.css`**

Add after line 21 (after the existing `.anim__state-label` print rule):

```css
  .anim__array-bar { animation: none !important; opacity: 1 !important; }
  .anim__path-marker { animation: none !important; offset-distance: 100% !important; }
```

(Inside the existing `@media print { ... }` block — insert before its closing `}`.)

- [ ] **Step 5: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_assets.py -v`
Expected: PASS. In particular confirm
`test_layout_css_uses_logical_directional_properties_not_physical_ones`,
`test_layout_css_has_no_four_value_margin_or_padding_shorthand`, and
`test_layout_css_only_uses_tokens_the_themes_define` all still pass (the new CSS
above uses only `--color-accent`/`--color-border`/`--color-muted`/`--space-2`,
all already in the allowed set — no new custom properties introduced by this task).

- [ ] **Step 6: Commit**

```bash
git add assets/base/layout.css assets/print.css tests/test_assets.py
git commit -m "feat: style array-ops and path-trace animate patterns"
```

---

### Task 5: Document the two new animate patterns

**Files:**
- Modify: `references/quiz-format.md`
- Modify: `references/agents/course-writer.md`
- Test: `tests/test_references.py`

**Interfaces:**
- Consumes: nothing new (pure documentation task).
- Produces: the course-writer agent's authoring instructions for `array-ops`/`path-trace`.

- [ ] **Step 1: Read the current animate-block section of both files**

```bash
grep -n "step-reveal\|state-toggle\|Exactly two" /home/roneng/Presntation2Course/references/quiz-format.md
grep -n "animate" /home/roneng/Presntation2Course/references/agents/course-writer.md
```

- [ ] **Step 2: Write the failing test**

Add to `tests/test_references.py` (near the existing `HANDLED_KINDS`-in-prose check):

```python
def test_course_writer_prompt_documents_the_new_animate_patterns():
    prose = (REFERENCES / "agents" / "course-writer.md").read_text()
    assert "array-ops" in prose
    assert "path-trace" in prose


def test_quiz_format_documents_the_new_animate_patterns():
    prose = (REFERENCES / "quiz-format.md").read_text()
    assert "array-ops" in prose
    assert "path-trace" in prose
```

(Adjust `REFERENCES` to whatever path constant the file already uses — check the
top of `tests/test_references.py` for the existing `Path(...)` setup and reuse it.)

- [ ] **Step 3: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_references.py -k new_animate_patterns -v`
Expected: FAIL.

- [ ] **Step 4: Update `references/quiz-format.md`**

In the animate-block grammar section (where `step-reveal`/`state-toggle` are
documented with fenced examples, and the "Exactly two patterns exist" sentence),
add two more fenced examples matching the exact grammar from Tasks 1-2:

````markdown
`array-ops` visualizes an array operation sequence (e.g. one pass of a sort):

```animate
pattern: array-ops
array:
  - 5
  - 3
  - 8
  - 1
ops:
  - compare 0 1
  - swap 0 1
  - highlight 2
```

`array:` needs at least 2 integer values. `ops:` needs at least one line, each one
of `compare i j`, `swap i j`, or `highlight i` (indices into `array`, 0-based).

`path-trace` visualizes a point moving along a plotted line or curve (also usable
for a tree/graph edge being traced):

```animate
pattern: path-trace
points:
  - 0, 10
  - 5, 2
  - 10, 8
  - 15, 0
caption: Gradient descent converging toward the minimum
```

`points:` needs at least 2 `x, y` pairs (plain numbers, not a function
expression). `caption:` is required.

Four patterns exist: `step-reveal`, `state-toggle`, `array-ops`, `path-trace` — no
others. This is a deliberately bounded set, not a general animation authoring tool.
````

Update the sentence that currently says "Exactly two patterns exist" (or similar)
to reflect four.

- [ ] **Step 5: Update `references/agents/course-writer.md`**

In the animate-block guidance section (where step-reveal/state-toggle are
introduced with "when to use this" framing), add:

```markdown
Use `array-ops` when a topic is about an array/list transformation you can express
as a short sequence of compare/swap/highlight steps (e.g. one pass of a sort, a
partition step). Use `path-trace` when a topic is about a value moving along a
continuous path — a point sliding along a plotted curve, a traversal along a tree
or graph edge — and you can supply the path as literal (x, y) coordinate pairs
(never write a function expression; give the actual point list).
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_references.py -v`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add references/quiz-format.md references/agents/course-writer.md tests/test_references.py
git commit -m "docs: document array-ops and path-trace animate patterns"
```

---

### Task 6: Center the content column

**Files:**
- Modify: `assets/base/layout.css:85`
- Test: `tests/test_assets.py`

**Interfaces:**
- Consumes: nothing new.
- Produces: `.content` visually centers within its grid track.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_assets.py`:

```python
def test_content_column_is_centered_within_its_grid_track():
    css = (ASSETS / "base" / "layout.css").read_text()
    rule_start = css.index(".content {")
    rule = css[rule_start : css.index("}", rule_start)]
    assert "margin-inline: auto" in rule
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_assets.py::test_content_column_is_centered_within_its_grid_track -v`
Expected: FAIL.

- [ ] **Step 3: Implement**

In `assets/base/layout.css`, change line 85 from:
```css
.content { max-width: var(--measure); padding: var(--space-8) var(--space-6) var(--space-12); }
```
to:
```css
.content { max-width: var(--measure); margin-inline: auto; padding: var(--space-8) var(--space-6) var(--space-12); }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/test_assets.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add assets/base/layout.css tests/test_assets.py
git commit -m "fix: center the content column within its grid track"
```

---

### Task 7: Off-canvas mobile sidebar drawer — HTML + CSS

**Files:**
- Modify: `assets/base/template.html`
- Modify: `assets/base/layout.css`
- Modify: `assets/print.css`
- Test: `tests/test_assets.py`

**Interfaces:**
- Consumes: nothing new.
- Produces: `#sidebar-toggle` button, `#sidebar` id on the `<aside>`, `#sidebar-scrim`
  element; CSS custom properties `--z-scrim`, `--z-drawer`, `--z-popover` (defined
  here, reused by Task 8's popover fix) and `--drawer-closed-x`; `data-open`
  attribute contract on `.sidebar` that Task 8's JS (in the next task) will set.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_assets.py`:

```python
def test_template_has_a_sidebar_toggle_and_scrim():
    template = (ASSETS / "base" / "template.html").read_text()
    assert 'id="sidebar-toggle"' in template
    assert 'aria-controls="sidebar"' in template
    assert 'id="sidebar"' in template
    assert 'id="sidebar-scrim"' in template
    assert 'class="sidebar-scrim"' in template


def test_layout_css_styles_the_mobile_drawer():
    css = (ASSETS / "base" / "layout.css").read_text()
    for selector in (".sidebar-toggle", ".sidebar-scrim", "--z-scrim", "--z-drawer", "--z-popover"):
        assert selector in css, selector


def test_sidebar_drawer_transform_is_direction_aware():
    css = (ASSETS / "base" / "layout.css").read_text()
    assert "--drawer-closed-x: -100%" in css
    assert '[dir="rtl"]' in css
    assert "--drawer-closed-x: 100%" in css


def test_print_css_hides_the_sidebar_scrim():
    css = (ASSETS / "print.css").read_text()
    assert ".sidebar-scrim" in css
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_assets.py -k "sidebar_toggle_and_scrim or mobile_drawer or drawer_transform_is_direction_aware or hides_the_sidebar_scrim" -v`
Expected: FAIL.

- [ ] **Step 3: Implement — `assets/base/template.html`**

Change:
```html
<div class="shell">
  <aside class="sidebar">
```
to:
```html
<div class="shell">
  <button type="button" class="btn sidebar-toggle" id="sidebar-toggle" aria-expanded="false" aria-controls="sidebar">Menu</button>
  <aside class="sidebar" id="sidebar" tabindex="-1">
```

And after the closing `</aside>` (before `<main class="content" ...>`), add:
```html
  <div class="sidebar-scrim" id="sidebar-scrim" hidden></div>
```

- [ ] **Step 4: Implement — `assets/base/layout.css`**

Add three custom properties to the existing `:root` block (lines 2-12):
```css
:root {
  --space-1: 0.25rem;
  --space-2: 0.5rem;
  --space-3: 0.75rem;
  --space-4: 1rem;
  --space-6: 1.5rem;
  --space-8: 2rem;
  --space-12: 3rem;
  --radius: 6px;
  --measure: 70ch;
  /* Stacking order for the project's first overlay UI (mobile drawer + glossary
     popover): scrim sits under the drawer, the popover sits above both so it's
     never hidden behind an open drawer if that ever becomes reachable. */
  --z-scrim: 10;
  --z-drawer: 20;
  --z-popover: 30;
  /* transform: translateX() has no logical-property equivalent (unlike every other
     directional value in this file) -- flip the sign here instead, under [dir="rtl"]
     below, so the drawer still closes toward its own start edge in both directions. */
  --drawer-closed-x: -100%;
}
[dir="rtl"] { --drawer-closed-x: 100%; }
```

Add near the sidebar rules (after the existing `.sidebar { ... }` block, currently
lines 47-53):
```css
.sidebar-toggle { display: none; }
.sidebar-scrim {
  position: fixed; inset: 0;
  background: rgba(0, 0, 0, 0.4);
  z-index: var(--z-scrim);
}
.sidebar-scrim[hidden] { display: none; }
```

Replace the existing `860px` breakpoint block (lines 154-159):
```css
@media (max-width: 860px) {
  .shell { grid-template-columns: 1fr; gap: 0; }
  .sidebar {
    position: fixed; inset-block: 0; inset-inline-start: 0;
    inline-size: min(300px, 85vw); height: 100vh;
    border-inline-end: 1px solid var(--color-border);
    box-shadow: 0 0 12px rgba(0, 0, 0, 0.2);
    z-index: var(--z-drawer);
    transform: translateX(var(--drawer-closed-x));
    transition: transform 0.25s ease;
  }
  .sidebar[data-open="true"] { transform: translateX(0); }
  .sidebar-toggle { display: inline-flex; }
  .content { padding: var(--space-6) var(--space-4); }
  .glossary { grid-template-columns: 1fr; }
}

@media (max-width: 860px) and (prefers-reduced-motion: reduce) {
  .sidebar { transition: none; }
}
```

- [ ] **Step 5: Implement — `assets/print.css`**

Add to the existing chrome-hiding line (currently `.sidebar, .skip-link, .btn,
.footer { display: none !important; }` at line 7):
```css
  .sidebar, .skip-link, .btn, .footer, .sidebar-scrim { display: none !important; }
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_assets.py -v`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add assets/base/template.html assets/base/layout.css assets/print.css tests/test_assets.py
git commit -m "feat: add off-canvas mobile sidebar drawer markup and CSS"
```

---

### Task 8: Off-canvas mobile sidebar drawer — JS wiring

**Files:**
- Modify: `assets/base/course.js`
- Test: `tests/test_assets.py`

**Interfaces:**
- Consumes: `#sidebar-toggle`, `#sidebar` (with `id="sidebar"` and `tabindex="-1"`
  from Task 7), `#sidebar-scrim` from Task 7; `data-open` attribute contract and
  `.sidebar[data-open="true"]` CSS from Task 7.
- Produces: `wireSidebarToggle()` function, called from `start()`.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_assets.py`:

```python
def test_course_js_wires_the_sidebar_drawer():
    js = (ASSETS / "base" / "course.js").read_text()
    for hook in ("sidebar-toggle", "sidebar-scrim", "data-open", "wireSidebarToggle"):
        assert hook in js, hook
    assert "localStorage" not in js  # drawer state stays non-persistent, same as today
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_assets.py::test_course_js_wires_the_sidebar_drawer -v`
Expected: FAIL.

- [ ] **Step 3: Implement**

In `assets/base/course.js`, add a new function after `wireTerms` (before `wireToc`):

```javascript
  /* --- mobile sidebar drawer: off-canvas, toggle/scrim/Escape to close ----- */
  function wireSidebarToggle() {
    var toggle = document.getElementById("sidebar-toggle");
    var sidebar = document.getElementById("sidebar");
    var scrim = document.getElementById("sidebar-scrim");
    if (!toggle || !sidebar || !scrim) { return; }

    function isOpen() { return sidebar.getAttribute("data-open") === "true"; }

    function close() {
      sidebar.removeAttribute("data-open");
      scrim.hidden = true;
      toggle.setAttribute("aria-expanded", "false");
      toggle.focus();
    }

    function open() {
      sidebar.setAttribute("data-open", "true");
      scrim.hidden = false;
      toggle.setAttribute("aria-expanded", "true");
      sidebar.focus();
    }

    toggle.addEventListener("click", function () {
      if (isOpen()) { close(); } else { open(); }
    });
    scrim.addEventListener("click", close);
    document.addEventListener("keydown", function (event) {
      if (event.key === "Escape" && isOpen()) { close(); }
    });
    sidebar.querySelectorAll(".toc a").forEach(function (link) {
      link.addEventListener("click", function () {
        if (isOpen()) { close(); }
      });
    });
  }
```

Add `wireSidebarToggle();` to the `start()` function (currently lines 134-140),
alongside the existing four calls:
```javascript
  function start() {
    wireQuizzes();
    wireTerms();
    wireSidebarToggle();
    wireToc();
    wireChrome();
    renderDiagrams();
  }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_assets.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add assets/base/course.js tests/test_assets.py
git commit -m "feat: wire the mobile sidebar drawer toggle/scrim/Escape"
```

---

### Task 9: Fix the glossary "breaks layout" bug

**Files:**
- Modify: `assets/base/layout.css` (`.term-wrap`/`.term__def`, lines 104-116)
- Modify: `assets/print.css` (line 28's `.term__def` rule)
- Modify: `assets/base/course.js` (`wireTerms`, lines 30-41)
- Test: `tests/test_assets.py`

**Interfaces:**
- Consumes: `--z-popover` custom property (defined in Task 7's `:root` block).
- Produces: `.term__def` becomes a positioned popover; `wireTerms()` gains mutual
  exclusion and click-outside/Escape-to-close.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_assets.py`:

```python
def test_term_def_is_positioned_out_of_flow_not_a_block_sibling():
    css = (ASSETS / "base" / "layout.css").read_text()
    rule_start = css.index(".term__def {")
    rule = css[rule_start : css.index("}", rule_start)]
    assert "position: absolute" in rule
    assert "max-inline-size:" in rule


def test_print_css_returns_the_term_definition_to_normal_flow():
    css = (ASSETS / "print.css").read_text()
    rule_start = css.index(".term__def {")
    rule = css[rule_start : css.index("}", rule_start)]
    assert "position: static !important" in rule


def test_course_js_closes_other_open_terms_and_supports_escape():
    js = (ASSETS / "base" / "course.js").read_text()
    assert "Escape" in js
    # wireTerms must reference more than one .term__def when opening one, i.e. it
    # iterates all defs to close siblings -- lock in the query used for that.
    assert js.count('querySelectorAll(".term__def")') >= 1 or js.count('querySelectorAll(".term")') >= 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_assets.py -k "term_def_is_positioned or returns_the_term_definition or closes_other_open_terms" -v`
Expected: FAIL.

- [ ] **Step 3: Implement — `assets/base/layout.css`**

Replace the `.term-wrap`/`.term__def` block (lines 104-116):
```css
.term-wrap { position: relative; }
.term {
  font: inherit; cursor: help; padding: 0; background: none; border: none;
  color: inherit; border-bottom: 1px dotted var(--color-accent);
}
.term:hover { border-bottom-style: solid; }
.term__def {
  position: absolute;
  top: 100%;
  inset-inline-start: 0;
  z-index: var(--z-popover);
  margin-block-start: var(--space-2);
  padding: var(--space-3);
  max-inline-size: min(24rem, calc(100vw - 2 * var(--space-4)));
  border: 1px solid var(--color-border); border-inline-start: 3px solid var(--color-accent);
  border-radius: var(--radius); background: var(--color-surface);
  font-size: 0.92rem; color: var(--color-fg);
}
.term__def[hidden] { display: none; }

@media (max-width: 860px) {
  .term__def {
    inset-inline-start: 50%;
    transform: translateX(-50%);
    max-inline-size: calc(100vw - 2 * var(--space-4));
  }
}
```

(The mobile override is added as a new rule inside the *existing* `860px`
breakpoint block from Task 7 — append it there rather than creating a third
breakpoint block, to keep all responsive rules for that width in one place.)

- [ ] **Step 4: Implement — `assets/print.css`**

Change line 28 from:
```css
  .term__def { display: block !important; }
```
to:
```css
  .term__def {
    position: static !important; display: block !important;
    inset-inline-start: auto !important; top: auto !important;
    max-inline-size: none !important; transform: none !important;
  }
```

- [ ] **Step 5: Implement — `assets/base/course.js`**

Replace `wireTerms` (lines 30-41):
```javascript
  /* --- glossary terms: click to reveal, one at a time --------------------- */
  function wireTerms() {
    var terms = document.querySelectorAll(".term");
    function closeAll(except) {
      terms.forEach(function (term) {
        if (term === except) { return; }
        var id = term.getAttribute("aria-controls");
        var def = id ? document.getElementById(id) : null;
        if (def && !def.hidden) {
          def.hidden = true;
          term.setAttribute("aria-expanded", "false");
        }
      });
    }
    terms.forEach(function (term) {
      term.addEventListener("click", function (event) {
        event.stopPropagation();
        var id = term.getAttribute("aria-controls");
        var def = id ? document.getElementById(id) : term.parentNode.querySelector(".term__def");
        if (!def) { return; }
        var open = def.hidden;
        closeAll(term);
        def.hidden = !open;
        term.setAttribute("aria-expanded", open ? "true" : "false");
      });
    });
    document.addEventListener("click", function () { closeAll(null); });
    document.addEventListener("keydown", function (event) {
      if (event.key === "Escape") { closeAll(null); }
    });
  }
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_assets.py -v`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add assets/base/layout.css assets/print.css assets/base/course.js tests/test_assets.py
git commit -m "fix: convert glossary definitions into a floating popover, closing the layout-reflow bug"
```

---

### Task 10: Sources parsing module

**Files:**
- Create: `scripts/p2c/sources.py`
- Test: `tests/test_sources.py` (new)

**Interfaces:**
- Consumes: nothing new (pure string parsing).
- Produces: `Source(title: str, url: str)` dataclass, `SourceError`,
  `parse_research_sources(markdown_text: str) -> list[Source]`,
  `sources_html_by_topic(topic_sources: dict[str, list[Source]], topic_titles: dict[str, str]) -> str`.
  Task 11 (`assemble.py`) and Task 12 (`build.py`) depend on these exact names/signatures.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_sources.py`:

```python
import pytest

from p2c.sources import Source, SourceError, parse_research_sources, sources_html_by_topic

RESEARCH_FILE = """---
topic: tlb
unverified: false
---

## Notes

The TLB caches virtual-to-physical mappings.

## Sources
- Operating Systems: Three Easy Pieces: https://pages.cs.wisc.edu/~remzi/OSTEP/
- Intel SDM Vol 3A: https://intel.com/sdm
"""


def test_parses_a_valid_sources_section():
    sources = parse_research_sources(RESEARCH_FILE)
    assert sources == [
        Source("Operating Systems: Three Easy Pieces", "https://pages.cs.wisc.edu/~remzi/OSTEP/"),
        Source("Intel SDM Vol 3A", "https://intel.com/sdm"),
    ]


def test_returns_empty_list_when_no_sources_heading():
    assert parse_research_sources("---\ntopic: x\n---\n\n## Notes\nJust prose.\n") == []


def test_rejects_a_line_missing_a_colon():
    with pytest.raises(SourceError, match="expected 'Title: url'"):
        parse_research_sources("## Sources\n- not a valid line\n")


def test_rejects_a_non_http_url():
    with pytest.raises(SourceError, match="must start with http"):
        parse_research_sources("## Sources\n- Some Title: ftp://example.com/x\n")


def test_stops_reading_sources_at_the_next_heading():
    text = "## Sources\n- A: https://a.example\n\n## Something Else\n- B: https://b.example\n"
    assert parse_research_sources(text) == [Source("A", "https://a.example")]


def test_sources_html_escapes_content():
    html_out = sources_html_by_topic(
        {"tlb": [Source("A < B", "https://a.example?x=1&y=2")]},
        {"tlb": "The TLB"},
    )
    assert "&lt; B" in html_out
    assert "&amp;y=2" in html_out
    assert "https://a.example?x=1&amp;y=2" in html_out


def test_sources_html_groups_by_topic_with_a_heading():
    html_out = sources_html_by_topic(
        {"tlb": [Source("A", "https://a.example")], "sched": [Source("B", "https://b.example")]},
        {"tlb": "The TLB", "sched": "Scheduling"},
    )
    assert '<h3>The TLB</h3>' in html_out
    assert '<h3>Scheduling</h3>' in html_out
    assert html_out.index("The TLB") < html_out.index("Scheduling")


def test_sources_html_skips_topics_with_no_sources():
    html_out = sources_html_by_topic({"tlb": []}, {"tlb": "The TLB"})
    assert html_out == ""


def test_sources_html_empty_dict_returns_empty_string():
    assert sources_html_by_topic({}, {}) == ""
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /home/roneng/Presntation2Course && .venv/bin/pytest tests/test_sources.py -v`
Expected: FAIL (`ModuleNotFoundError: No module named 'p2c.sources'`).

- [ ] **Step 3: Implement**

Create `scripts/p2c/sources.py`:

```python
"""Parses citation URLs out of the researcher agent's per-topic notes file.

Kept strict on purpose, same rationale as quiz.py's grammar: a malformed source
line is a build-time signal, not something to silently swallow or guess at.
"""

import html
import re
from dataclasses import dataclass

_SOURCES_HEADING = re.compile(r"^##\s+Sources\s*$")
_HEADING = re.compile(r"^#{1,6}\s")
_ENTRY = re.compile(r"^-\s*(?P<title>[^:]+):\s*(?P<url>\S+)$")


class SourceError(ValueError):
    """A '## Sources' section that does not satisfy the grammar."""


@dataclass
class Source:
    title: str
    url: str


def parse_research_sources(markdown_text: str) -> list[Source]:
    lines = markdown_text.split("\n")
    in_sources = False
    sources: list[Source] = []
    for raw in lines:
        line = raw.rstrip()
        if _SOURCES_HEADING.match(line):
            in_sources = True
            continue
        if not in_sources:
            continue
        if _HEADING.match(line):
            break
        if not line.strip():
            continue
        match = _ENTRY.match(line.strip())
        if not match:
            raise SourceError(f"expected 'Title: url', got {line.strip()!r}")
        title, url = match.group("title").strip(), match.group("url").strip()
        if not url.startswith(("http://", "https://")):
            raise SourceError(f"source url must start with http:// or https://, got {url!r}")
        sources.append(Source(title=title, url=url))
    return sources


def sources_html_by_topic(
    topic_sources: dict[str, list[Source]], topic_titles: dict[str, str]
) -> str:
    groups = []
    for topic_id, sources in topic_sources.items():
        if not sources:
            continue
        title = html.escape(topic_titles.get(topic_id, topic_id))
        items = "".join(
            f'<li><a href="{html.escape(s.url, quote=True)}">{html.escape(s.title)}</a></li>'
            for s in sources
        )
        groups.append(
            f'<div class="sources-group"><h3>{title}</h3><ol class="sources">{items}</ol></div>'
        )
    return "".join(groups)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_sources.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add scripts/p2c/sources.py tests/test_sources.py
git commit -m "feat: parse and render per-topic Sources sections"
```

---

### Task 11: Aggregate sources during assemble/build

**Files:**
- Modify: `scripts/p2c/assemble.py` (new `collect_sources` function)
- Modify: `scripts/p2c/build.py` (`fill_template`, `build`)
- Modify: `scripts/p2c/theme.py` (`TEMPLATE_PLACEHOLDERS`)
- Modify: `assets/base/template.html` (new Sources appendix section)
- Test: `tests/test_assemble.py`, `tests/test_assets.py`

**Interfaces:**
- Consumes: `parse_research_sources`/`Source`/`sources_html_by_topic` from Task 10;
  `p2c.outline.iter_topics`/`topic_ids` (existing).
- Produces: `collect_sources(research_dir: Path, outline: dict) -> dict[str, list[Source]]`;
  `build()` threads a `{{SOURCES}}` substitution through `fill_template`.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_assemble.py`:

```python
def test_collect_sources_reads_every_topic_research_file(tmp_path):
    from p2c.assemble import collect_sources
    from p2c.sources import Source

    research_dir = tmp_path / "research"
    research_dir.mkdir()
    (research_dir / "tlb.md").write_text("## Sources\n- A: https://a.example\n")
    (research_dir / "sched.md").write_text("## Sources\n- B: https://b.example\n")

    outline = {
        "modules": [
            {"topics": [{"id": "tlb"}, {"id": "sched"}]},
        ]
    }
    result = collect_sources(research_dir, outline)
    assert result == {
        "tlb": [Source("A", "https://a.example")],
        "sched": [Source("B", "https://b.example")],
    }


def test_collect_sources_tolerates_a_missing_research_file(tmp_path):
    from p2c.assemble import collect_sources

    research_dir = tmp_path / "research"
    research_dir.mkdir()
    outline = {"modules": [{"topics": [{"id": "tlb"}]}]}
    assert collect_sources(research_dir, outline) == {"tlb": []}


def test_collect_sources_tolerates_a_missing_research_directory(tmp_path):
    from p2c.assemble import collect_sources

    outline = {"modules": [{"topics": [{"id": "tlb"}]}]}
    assert collect_sources(tmp_path / "does-not-exist", outline) == {"tlb": []}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_assemble.py -k collect_sources -v`
Expected: FAIL (`ImportError` / `AttributeError`).

- [ ] **Step 3: Implement — `scripts/p2c/assemble.py`**

Add near the top imports:
```python
from p2c.outline import topic_ids
from p2c.sources import Source, SourceError, parse_research_sources
```

Add a new function (anywhere after `assemble`, e.g. at the end of the file):
```python
def collect_sources(research_dir: Path, outline: dict) -> dict[str, list[Source]]:
    """Reads each topic's already-written researcher notes file, if present.

    A missing file (research phase skipped, or this topic had none) is zero
    sources, not an error -- research files are several build phases upstream
    of this step and a punctuation slip shouldn't block a build.
    """
    research_dir = Path(research_dir)
    result: dict[str, list[Source]] = {}
    for topic_id in topic_ids(outline):
        path = research_dir / f"{topic_id}.md"
        if not path.is_file():
            result[topic_id] = []
            continue
        try:
            result[topic_id] = parse_research_sources(path.read_text(encoding="utf-8"))
        except SourceError:
            result[topic_id] = []
    return result
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_assemble.py -v`
Expected: PASS.

- [ ] **Step 5: Write the failing build-level test**

Add to `tests/test_build.py` (near other `fill_template`/`build` tests — check the
existing `built` fixture setup at the top of the file for the exact tmp_path
structure convention used, and match it):

```python
def test_build_writes_a_sources_section(built):
    result, out_dir = built  # or however the existing fixture exposes these -- match convention
    course_html = result.course_html.read_text()
    assert '<section class="appendix">' in course_html
    assert '<h2 id="sources">Sources</h2>' in course_html
```

(If no research files were seeded for the fixture topics, this should still assert
the empty-state fallback renders, e.g. `"No external sources were cited."` appears
— write whichever of the two matches what the `built` fixture actually seeds; check
`tests/test_build.py`'s fixture definition first and adjust this test to whatever
research files, if any, that fixture already provides before writing this step.)

- [ ] **Step 6: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_build.py::test_build_writes_a_sources_section -v`
Expected: FAIL (`{{SOURCES}}` not yet substituted / section not in template).

- [ ] **Step 7: Implement — `scripts/p2c/theme.py`**

Add `"{{SOURCES}}"` to the `TEMPLATE_PLACEHOLDERS` tuple (line 52-66):
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
    "{{COURSE_JS}}",
    "{{LANG}}",
    "{{DIR}}",
)
```

- [ ] **Step 8: Implement — `assets/base/template.html`**

Add a new appendix section after the existing Glossary one (after line 33's
closing `</section>`, before the `<footer>`):
```html
    <section class="appendix">
      <h2 id="sources">Sources</h2>
      {{SOURCES}}
    </section>
```

- [ ] **Step 9: Implement — `scripts/p2c/build.py`**

Add imports:
```python
from p2c.assemble import assemble, collect_sources
from p2c.outline import iter_topics
from p2c.sources import sources_html_by_topic
```
(merge with the existing `from p2c.assemble import assemble` line rather than
duplicating it.)

Extend `fill_template`'s signature and body:
```python
def fill_template(
    theme: Theme,
    rendered: Rendered,
    *,
    title: str,
    source_decks: list[str],
    inline_mermaid: bool,
    language: dict,
    sources_html: str = "",
) -> str:
    decks = ", ".join(source_decks) if source_decks else "the source deck"
    substitutions = {
        "{{TITLE}}": html.escape(title),
        "{{THEME_NAME}}": theme.name,
        "{{THEME_CSS}}": theme.theme_css,
        "{{LAYOUT_CSS}}": theme.layout_css,
        "{{PRINT_CSS}}": theme.print_css,
        "{{TOC}}": rendered.toc_html,
        "{{CONTENT}}": rendered.html_body,
        "{{GLOSSARY}}": rendered.glossary_html or "<p>No jargon was recorded.</p>",
        "{{SOURCES}}": sources_html or "<p>No external sources were cited.</p>",
        "{{SOURCE_DECKS}}": html.escape(decks),
        "{{MERMAID_JS}}": theme.mermaid_js if (inline_mermaid and theme.mermaid_js) else "",
        "{{COURSE_JS}}": theme.course_js,
        "{{LANG}}": html.escape(language["code"]),
        "{{DIR}}": "rtl" if is_rtl(language["code"]) else "ltr",
    }
    return _PLACEHOLDER_RE.sub(
        lambda m: substitutions.get(m.group(0), m.group(0)), theme.template
    )
```

In `build()`, after `rendered = render_course(course_md_text)`, compute the sources
HTML once and pass it to both `fill_template` call sites:
```python
    topic_titles = {topic["id"]: topic["title"] for _, topic in iter_topics(outline)}
    topic_sources = collect_sources(out_dir / ".p2c" / "research", outline)
    sources_html = sources_html_by_topic(topic_sources, topic_titles)
```

Then add `sources_html=sources_html,` as a keyword argument to **both** existing
`fill_template(...)` calls inside `build()` (the real render at line ~124-134 and
the validation-copy render at line ~148-158).

- [ ] **Step 10: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_build.py tests/test_assets.py -v`
Expected: PASS. (The golden-snapshot tests will now fail because `template.html`
changed — this is expected per the Global Constraints; do NOT regenerate yet, that
happens in the final task. Confirm the *non-golden* tests in these two files pass.)

- [ ] **Step 11: Commit**

```bash
git add scripts/p2c/assemble.py scripts/p2c/build.py scripts/p2c/theme.py assets/base/template.html tests/test_assemble.py tests/test_build.py
git commit -m "feat: aggregate and render an end-of-course Sources section"
```

---

### Task 12: Tighten the researcher's Sources grammar

**Files:**
- Modify: `references/agents/researcher.md`
- Test: `tests/test_references.py`

**Interfaces:**
- Consumes: nothing new (documentation change).
- Produces: the researcher agent's `## Sources` output now matches
  `parse_research_sources`'s strict `- Title: url` grammar from Task 10.

- [ ] **Step 1: Read the current Sources section**

```bash
grep -n -A5 "## Sources" /home/roneng/Presntation2Course/references/agents/researcher.md
```

- [ ] **Step 2: Write the failing test**

Add to `tests/test_references.py`:

```python
def test_researcher_prompt_uses_the_strict_sources_grammar():
    prose = (REFERENCES / "agents" / "researcher.md").read_text()
    assert "- Title: url" in prose or "Title: url" in prose
    assert "https://example.com/page" not in prose  # old em-dash example replaced
```

(Match `REFERENCES` to whatever path constant the file already defines.)

- [ ] **Step 3: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_references.py::test_researcher_prompt_uses_the_strict_sources_grammar -v`
Expected: FAIL.

- [ ] **Step 4: Implement**

In `references/agents/researcher.md`, change the `## Sources` example from:
```markdown
## Sources
- Title — https://example.com/page
```
to:
```markdown
## Sources
- Title: https://example.com/page
```

And update the accompanying rule text to be explicit about the grammar, e.g.:
```markdown
Each source line must be `- Title: url`, one per line, `url` starting with
`http://` or `https://`. No other punctuation in the separator — this file is
parsed by a script, not just read by other agents.
```

- [ ] **Step 5: Run test to verify it passes**

Run: `.venv/bin/pytest tests/test_references.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add references/agents/researcher.md tests/test_references.py
git commit -m "docs: tighten the researcher's Sources grammar for reliable parsing"
```

---

### Task 13: Collapsible quizzes via `<details>/<summary>`

**Files:**
- Modify: `scripts/p2c/quiz.py` (`quiz_to_html`)
- Modify: `assets/base/layout.css` (`.quiz__q`)
- Modify: `assets/print.css`
- Test: `tests/test_quiz.py`, `tests/test_mdrender.py`

**Interfaces:**
- Consumes: existing `Quiz` dataclass, `parse_quiz` (unchanged).
- Produces: `quiz_to_html` now emits `<details class="quiz" ... open>` /
  `<summary class="quiz__q">` instead of `<div>`/`<p>`. `course.js`'s `wireQuizzes`
  selectors are unaffected (class-based, tag-agnostic) — confirmed, no JS change
  needed in this task.

- [ ] **Step 1: Write the failing tests**

Update the existing assertion in `tests/test_quiz.py`
(`test_html_wires_ids_and_hides_the_answer_until_clicked`, currently asserting
`'<div class="quiz" data-quiz="m01-t02-q1">' in out`) to:
```python
def test_html_wires_ids_and_hides_the_answer_until_clicked():
    out = quiz_to_html(parse_quiz(VALID), "m01-t02-q1")
    assert '<details class="quiz" data-quiz="m01-t02-q1" open>' in out
    assert 'id="m01-t02-q1-why"' in out
    assert 'aria-describedby="m01-t02-q1-why"' in out
    assert '<p class="quiz__answer" hidden>' in out
    assert '<p class="quiz__why" id="m01-t02-q1-why" hidden>' in out
```

Add a new test:
```python
def test_html_uses_details_summary_for_collapsibility():
    out = quiz_to_html(parse_quiz(VALID), "q1")
    assert out.startswith('<details class="quiz" data-quiz="q1" open>')
    assert '<summary class="quiz__q">What does a TLB actually cache?</summary>' in out
    assert out.rstrip().endswith("</details>")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_quiz.py -v`
Expected: FAIL on the two updated/new tests (current output still uses `<div>`/`<p>`).

- [ ] **Step 3: Implement — `scripts/p2c/quiz.py`**

Replace `quiz_to_html` (lines 85-105):
```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_quiz.py -v`
Expected: PASS.

- [ ] **Step 5: Search for and fix any other test pinning the old `<div class="quiz"` shape**

```bash
grep -rn '<div class="quiz"' /home/roneng/Presntation2Course/tests/
```

For any hit in `tests/test_mdrender.py` (or elsewhere), update it to
`<details class="quiz"` following the same substitution as Step 3 above.

- [ ] **Step 6: Implement — `assets/base/layout.css`**

Change `.quiz__q` (line 123) from:
```css
.quiz__q { font-weight: 600; margin: var(--space-2) 0 var(--space-4); }
```
to:
```css
.quiz__q { font-weight: 600; margin: var(--space-2) 0 var(--space-4); cursor: pointer; }
```

- [ ] **Step 7: Implement — `assets/print.css`**

Add near the existing quiz print rules (after line 25's
`.quiz__option { border: 1px solid #999 !important; }`):
```css
  .quiz > :not(summary) { display: block !important; }
```

- [ ] **Step 8: Run the full non-golden suite to verify no regression**

Run: `.venv/bin/pytest tests/ -v --deselect tests/test_build.py::test_matches_the_golden_snapshot --deselect tests/test_build.py::test_the_hebrew_course_matches_its_golden_snapshot`

(Adjust the exact `--deselect` node ids to match whatever the golden tests are
actually named — check with `.venv/bin/pytest tests/test_build.py --collect-only -q | grep -i golden` first.)

Expected: PASS (golden tests are expected to fail until the final task regenerates them).

- [ ] **Step 9: Commit**

```bash
git add scripts/p2c/quiz.py assets/base/layout.css assets/print.css tests/test_quiz.py tests/test_mdrender.py
git commit -m "feat: render quizzes as collapsible <details>/<summary>, expanded by default"
```

---

### Task 14: Seed fixtures, regenerate golden snapshots, full verification

**Files:**
- Modify: `tests/fixtures/mini-course/modules/02-scheduling.md` (add one `array-ops` and one `path-trace` block)
- Modify: `tests/fixtures/mini-course-he/modules/01-section.md` (add one `array-ops` and one `path-trace` block, to exercise `dir="ltr"` inside RTL prose)
- Create fixture research files for the Sources feature (both English and Hebrew fixture builds, wherever `tests/test_build.py`'s `built`/Hebrew-equivalent fixture reads `.p2c/research/` from — check that fixture's setup first)
- Regenerate: `tests/golden/course.html`, `tests/golden/course-he.html`
- Test: full suite

**Interfaces:**
- Consumes: every prior task's code (this task touches no `scripts/p2c/*.py` logic,
  only fixtures and generated golden output).
- Produces: passing golden-snapshot tests reflecting all nine prior tasks' asset changes.

- [ ] **Step 1: Read the current `test_build.py` fixture setup**

```bash
grep -n "def built\|def test_matches_the_golden\|def test_the_hebrew\|P2C_UPDATE_GOLDEN\|research" /home/roneng/Presntation2Course/tests/test_build.py
```
Understand exactly how the `built`/Hebrew-fixture pytest fixtures construct their
`tmp_path` tree (in particular whether `.p2c/research/` is already seeded with
anything) before adding new files, so the new research fixtures land in the right
directory relative to what `collect_sources` (Task 11) expects
(`out_dir / ".p2c" / "research" / f"{topic_id}.md"`).

- [ ] **Step 2: Add one `array-ops` and one `path-trace` block to the English fixture**

In `tests/fixtures/mini-course/modules/02-scheduling.md`, after the existing
`step-reveal` block under the `round-robin` topic, add:
```markdown
```animate
pattern: array-ops
array:
  - 5
  - 3
  - 8
  - 1
ops:
  - compare 0 1
  - swap 0 1
  - highlight 2
```
```
And under the `thrashing` topic (which currently has a `<!-- no-visual: ... -->`
comment) — since that comment exists specifically because the topic has no visual,
do NOT add an animate block there (it would make the `no-visual` comment
misleading). Instead add the `path-trace` block to the `tlb` topic, after its
existing `figure` block:
```markdown
```animate
pattern: path-trace
points:
  - 0, 10
  - 5, 2
  - 10, 8
  - 15, 0
caption: TLB hit rate rising as the working set warms up
```
```

- [ ] **Step 3: Add the same two blocks to the Hebrew fixture**

In `tests/fixtures/mini-course-he/modules/01-section.md`, add one `array-ops` and
one `path-trace` block to existing topics there (read the file first to find
topics without a `no-visual` comment, matching the same placement logic as Step 2).

- [ ] **Step 4: Seed research files with Sources for the fixture topics**

Create research files under whatever path Step 1 determined the `built` fixture
uses (e.g. `tests/fixtures/mini-course/.p2c/research/tlb.md` if fixtures are read
directly from the repo, or inline in the fixture-construction code in
`test_build.py` if it builds a `tmp_path` tree programmatically — follow whichever
pattern Step 1 found). Content:
```markdown
## Sources
- Operating Systems: Three Easy Pieces: https://pages.cs.wisc.edu/~remzi/OSTEP/
```
Seed at least one topic per fixture (English and Hebrew) this way; leave at least
one other topic with no research file at all, to exercise the "tolerates a missing
file" path from Task 11 in a real build, not just its unit test.

- [ ] **Step 5: Run the non-golden suite first**

Run: `.venv/bin/pytest tests/ -v -k "not golden"`
Expected: PASS. This confirms every prior task's code is correct before golden
regeneration mixes in cosmetic diffs.

- [ ] **Step 6: Regenerate golden snapshots**

Run:
```bash
cd /home/roneng/Presntation2Course
P2C_UPDATE_GOLDEN=1 .venv/bin/pytest tests/test_build.py -k golden -v
```

- [ ] **Step 7: Manually review the golden diff**

```bash
git diff tests/golden/course.html tests/golden/course-he.html
```
Confirm the diff contains exactly the expected changes: the new Sources appendix
section, the new `array-ops`/`path-trace` markup, the `<details>`/`<summary>` quiz
wrapper, the sidebar-toggle/scrim markup, the centered-content CSS, the
glossary-popover CSS, and the mobile-drawer CSS — and nothing unexpected. If
anything looks wrong, fix the responsible task's code (not the golden file
directly) and re-run Step 6.

- [ ] **Step 8: Run the full suite**

Run: `.venv/bin/pytest`
Expected: PASS, with the same 3 pre-existing skips (soffice/Chromium/`P2C_COURSE_DIR`
unavailable in this dev environment) and no others.

- [ ] **Step 9: Run the invariants checker against a real build**

```bash
cd /home/roneng/Presntation2Course
mkdir -p /tmp/p2c-verify/.p2c/research
PYTHONPATH=scripts .venv/bin/python -c "
from pathlib import Path
from p2c.build import build
result = build(
    Path('tests/fixtures/mini-course/outline.json'),
    Path('tests/fixtures/mini-course/modules'),
    Path('/tmp/p2c-verify'),
    Path('assets'),
)
print(result.course_html)
print('blocking findings:', [f for f in result.findings if f.blocking])
"
PYTHONPATH=scripts .venv/bin/python -m p2c.invariants /tmp/p2c-verify
```
(Adjust the outline/modules paths if `tests/fixtures/mini-course/outline.json`
isn't the exact fixture path — check `tests/test_build.py`'s fixture setup from
Step 1 for the real path.) Expected: no blocking findings, `p2c.invariants` reports
clean.

- [ ] **Step 10: Manual browser smoke-test**

Use the `run` skill to serve/open `/tmp/p2c-verify/course.html` (or the built
`course.html` from Step 9) in a real browser and check, per the plan's
Verification section:
- Mobile drawer: resize below 860px, click the toggle, confirm it slides in from
  the side with a scrim, closes on Escape and on scrim click, and focus returns to
  the toggle button on close.
- Glossary popover: click a term, confirm the popover appears below/near it
  without shifting any surrounding text, closes on outside click and Escape, and
  stays within the viewport at a narrow width.
- Quiz collapse: confirm each quiz shows expanded by default with a native
  disclosure triangle, and collapses/expands on clicking the question.
- Sources section: confirm it appears at the end of the course, grouped by topic.
- The two new animate patterns render and animate (or show their static
  print/reduced-motion fallback if you have reduced motion enabled).

- [ ] **Step 11: Commit**

```bash
git add tests/fixtures tests/golden
git commit -m "test: add array-ops/path-trace/sources fixtures and regenerate golden snapshots"
```

---

## Post-plan verification checklist

- [ ] `.venv/bin/pytest` — full suite passes (3 pre-existing skips only).
- [ ] `git diff tests/golden/` reviewed and matches expectations (Task 14, Step 7).
- [ ] Manual browser smoke-test completed (Task 14, Step 10) for the mobile drawer
      and glossary popover specifically, since no automated test in this repo can
      verify actual rendered motion/positioning.
- [ ] `p2c.invariants` reports no blocking findings on a freshly built course
      exercising all six features.
