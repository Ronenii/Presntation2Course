# Animation Coverage Floor and Domain-General Patterns Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add three domain-general `animate` patterns (`pipeline`, `layer-stack`, `transform`) and a blocking 25% animation-coverage floor, so generated courses stop coming out with zero animations.

**Architecture:** `parse_animate` in `scripts/p2c/mdrender.py` is already a key/list-section parser; the three new patterns extend its `_LIST_HEADERS`/`lists` maps and pattern whitelist, each gaining an `_*_html` renderer that emits SVG plus a JSON timeline island. The existing `course.js` timeline interpreter has a generic step path (`targets`/`props`/`duration`/`ease`/`position`) that already handles `stroke-dashoffset`, so **no JavaScript changes are required**. `Rendered` gains a per-topic animate tally, which `validate.py` uses for the floor check.

**Tech Stack:** Python 3 (stdlib only — `re`, `dataclasses`, `html`, `math`), pytest, anime.js v4 (already vendored), CSS custom properties.

## Global Constraints

- **Spec:** `docs/superpowers/specs/2026-08-12-animation-coverage-and-vocabulary-design.md`.
- **Additive only.** The four existing patterns (`state-machine`, `state-toggle`, `array-ops`, `path-trace`) keep their current grammar, rendering, and geometry. Do not re-lay-out them.
- **No new dependencies.** Python stdlib only; no new vendored JS.
- **New layout constants divisible by 4** (box widths, heights, gaps, margins). Derived values — text baselines, centers, midpoints — are exempt.
- **No shadows. Border radius ≤10px.** Orthogonal connectors only; no diagonals.
- **Accent discipline:** exactly one element carries `--color-accent` at a time.
- **Every new SVG root carries `dir="ltr"`** so RTL/Hebrew courses keep left-to-right geometry.
- **Reduced-motion and print render fully static**, with *every* stage/layer/step visible at once — never a single frozen frame.
- **anime.js gotchas** (from `.claude/skills/animejs/references/api-reference.md`):
  1. Base positions live in plain attributes (`x`/`y`/`cx`/`cy`), never `transform="translate(...)"` — anime.js sets a CSS `transform` that replaces the SVG attribute.
  2. Every looping timeline ends with explicit `{"kind": "set", ...}` steps snapping animated properties back to baseline, or values compound across laps.
- **Run the full suite before every commit:** `python -m pytest tests/ -q`.

---

## File Structure

| File | Responsibility | Tasks |
|---|---|---|
| `scripts/p2c/mdrender.py` | Parser extension, three renderers, per-topic animate tally | 1–5 |
| `scripts/p2c/validate.py` | 25% floor + linear-chain mermaid detector | 6–7 |
| `assets/base/layout.css` | Tokens and animated presentation for the three patterns | 8 |
| `assets/base/print.css` | Print static fallbacks | 8 |
| `references/quiz-format.md` | Author-facing grammar | 9 |
| `references/agents/course-writer.md` | Selection guidance + 25% requirement | 9 |

---

### Task 1: Parse the `pipeline` pattern

**Files:**
- Modify: `scripts/p2c/mdrender.py:96` (`_ANIMATE_KEY`), `:108-124` (`Animate`, `_LIST_HEADERS`), `:139-142` (`lists`), `:172-176` (whitelist), `:269` (add branch before `else: # path-trace`)
- Test: `tests/test_mdrender.py`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces: `Animate.stages: list[tuple[str, str]]` — ordered `(name, change)` pairs. Pattern string is `"pipeline"`. Raises `AnimateError` on violations.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_mdrender.py`:

```python
def test_pipeline_parses_stages_into_name_change_pairs():
    anim = parse_animate(
        "pattern: pipeline\n"
        "stages:\n"
        "  - Raw image: single RGB frame\n"
        "  - Encoder: compresses into a feature map\n"
    )
    assert anim.pattern == "pipeline"
    assert anim.stages == [
        ("Raw image", "single RGB frame"),
        ("Encoder", "compresses into a feature map"),
    ]


def test_pipeline_rejects_fewer_than_two_stages():
    with pytest.raises(AnimateError, match="at least 2 stages"):
        parse_animate("pattern: pipeline\nstages:\n  - Only one: does nothing\n")


def test_pipeline_rejects_more_than_six_stages():
    body = "pattern: pipeline\nstages:\n" + "".join(
        f"  - Stage {i}: does thing {i}\n" for i in range(7)
    )
    with pytest.raises(AnimateError, match="at most 6 stages"):
        parse_animate(body)


def test_pipeline_rejects_stage_without_a_change_description():
    with pytest.raises(AnimateError, match="must be written as"):
        parse_animate("pattern: pipeline\nstages:\n  - Encoder\n  - Decoder: expands\n")


def test_pipeline_rejects_keys_from_other_patterns():
    with pytest.raises(AnimateError, match="does not use"):
        parse_animate(
            "pattern: pipeline\nstages:\n  - A: does a\n  - B: does b\n"
            "points:\n  - 0, 1\n"
        )
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_mdrender.py -k pipeline -q`
Expected: FAIL — `AnimateError: animate pattern must be 'state-machine', ...` (the whitelist rejects `pipeline`).

- [ ] **Step 3: Implement the parser changes**

In `scripts/p2c/mdrender.py`, add the stage-splitting regex next to `_TRANSITION` (`:101`):

```python
_STAGE = re.compile(r"^(?P<name>.+?):\s*(?P<change>.+)$")
```

Add to the `Animate` dataclass (after `transitions`, `:118`):

```python
    stages: list[tuple[str, str]] = field(default_factory=list)
```

Add to `_LIST_HEADERS` (`:121-124`):

```python
    "stages:": "stages",
```

In `parse_animate`, add the accumulator beside `states_raw` (`:134`):

```python
    stages_raw: list[str] = []
```

and register it in the `lists` dict (`:139-142`):

```python
        "stages": stages_raw,
```

Widen the pattern whitelist (`:172-176`) to:

```python
    if pattern not in (
        "state-machine", "state-toggle", "array-ops", "path-trace", "pipeline",
    ):
        raise AnimateError(
            "animate pattern must be 'state-machine', 'state-toggle', 'array-ops', "
            f"'path-trace', or 'pipeline', got {pattern!r}"
        )
```

Add the branch immediately before `else:  # path-trace` (`:269`):

```python
    elif pattern == "pipeline":
        if before or after or states_raw or transitions_raw or array_raw or ops_raw or points_raw:
            raise AnimateError(
                "pipeline does not use 'before:'/'after:'/'states:'/'transitions:'/"
                "'array:'/'ops:'/'points:'"
            )
        if len(stages_raw) < 2:
            raise AnimateError("pipeline needs at least 2 stages")
        if len(stages_raw) > 6:
            raise AnimateError("pipeline takes at most 6 stages")
        stages: list[tuple[str, str]] = []
        for line in stages_raw:
            match = _STAGE.match(line)
            if not match:
                raise AnimateError(
                    f"pipeline stage {line!r} must be written as '<name>: <what changes>'"
                )
            stages.append((match.group("name").strip(), match.group("change").strip()))
        return Animate(pattern=pattern, stages=stages, caption=caption or "")
```

Note: `caption:` is optional for `pipeline` and is therefore excluded from the
rejected-keys check above.

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_mdrender.py -k pipeline -q`
Expected: PASS (5 tests).

- [ ] **Step 5: Run the full suite**

Run: `python -m pytest tests/ -q`
Expected: PASS — the four existing patterns are untouched.

- [ ] **Step 6: Commit**

```bash
git add scripts/p2c/mdrender.py tests/test_mdrender.py
git commit -m "feat: parse the pipeline animate pattern"
```

---

### Task 2: Render `pipeline` as an animated SVG

**Files:**
- Modify: `scripts/p2c/mdrender.py` — geometry constants near `:304`, new `_pipeline_html`, dispatch in `_animate_html` (`:342-350`)
- Test: `tests/test_mdrender.py`

**Interfaces:**
- Consumes: `Animate.stages` from Task 1.
- Produces: `_pipeline_html(anim: Animate, token: str) -> str`. Emits `<div class="anim anim--pipeline">` containing an `<svg class="anim__pipeline" dir="ltr">`, a `<script type="application/json" class="anim__timeline">` island, and an `<ol class="anim__pipeline-static">` fallback.

**Geometry rationale:** stages are laid out left-to-right, each a rounded rect (`rx="8"`, ≤10 per constraints). Connectors between stages are straight horizontal lines (endpoints share a `y`, so the orthogonal rule is satisfied without elbows) that draw themselves via `stroke-dashoffset`. Because each connector is a straight horizontal line, its path length is exactly `_PIPE_GAP` — computed in Python, no `getTotalLength()` needed.

- [ ] **Step 1: Write the failing tests**

```python
def _pipeline_anim():
    return parse_animate(
        "pattern: pipeline\n"
        "stages:\n"
        "  - Raw image: single RGB frame\n"
        "  - Encoder: compresses into a feature map\n"
        "  - Depth map: one distance per pixel\n"
    )


def test_pipeline_html_pins_ltr_and_lists_every_stage_statically():
    out = _pipeline_html(_pipeline_anim(), "ANIMTOKEN3")
    assert 'dir="ltr"' in out
    assert 'class="anim anim--pipeline"' in out
    # Static fallback carries every stage, so print/reduced-motion shows them all.
    for name in ("Raw image", "Encoder", "Depth map"):
        assert name in out
    assert out.count("<li>") == 3


def test_pipeline_html_draws_connectors_with_dashoffset():
    out = _pipeline_html(_pipeline_anim(), "ANIMTOKEN3")
    data = json.loads(
        re.search(
            r'<script type="application/json" class="anim__timeline">(.*?)</script>',
            out, re.S,
        ).group(1)
    )
    dash_steps = [
        s for s in data["steps"]
        if "strokeDashoffset" in (s.get("props") or {}) and s.get("kind") != "set"
    ]
    # One drawing animation per connector: N stages => N-1 connectors.
    assert len(dash_steps) == 2


def test_pipeline_timeline_resets_every_animated_property_for_the_loop():
    out = _pipeline_html(_pipeline_anim(), "ANIMTOKEN3")
    data = json.loads(
        re.search(
            r'<script type="application/json" class="anim__timeline">(.*?)</script>',
            out, re.S,
        ).group(1)
    )
    assert data["loop"] is True
    animated = {
        prop
        for step in data["steps"] if step.get("kind") != "set"
        for prop in (step.get("props") or {})
    }
    reset = {
        prop
        for step in data["steps"] if step.get("kind") == "set"
        for prop in (step.get("props") or {})
    }
    # Gotcha 2: absolute values compound across laps unless every one is reset.
    assert animated <= reset


def test_pipeline_layout_constants_are_divisible_by_four():
    for value in (_PIPE_BOX_WIDTH, _PIPE_BOX_HEIGHT, _PIPE_GAP, _PIPE_TOP_MARGIN):
        assert value % 4 == 0
```

Ensure `tests/test_mdrender.py` imports what these need (`json`, `re`, and the new
names `_pipeline_html`, `_PIPE_BOX_WIDTH`, `_PIPE_BOX_HEIGHT`, `_PIPE_GAP`,
`_PIPE_TOP_MARGIN` from `p2c.mdrender`).

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_mdrender.py -k pipeline -q`
Expected: FAIL — `ImportError`/`AttributeError`: `_pipeline_html` does not exist.

- [ ] **Step 3: Implement the renderer**

Add constants next to `_STATE_BOX_WIDTH` (`:304`):

```python
_PIPE_BOX_WIDTH = 140
_PIPE_BOX_HEIGHT = 64
_PIPE_GAP = 56  # horizontal gap between stage boxes; also each connector's length
_PIPE_TOP_MARGIN = 24
```

Add the renderer (place it after `_state_toggle_html`):

```python
def _pipeline_html(anim: Animate, token: str) -> str:
    """Stages light up left-to-right; each connector draws itself between them.

    Only one stage carries the accent at a time (diagram-design's focal rule):
    the arriving stage goes accent, and the previous one is returned to idle in
    the same step, so the reader's eye always has exactly one target.
    """
    token_seed = re.sub(r"\D", "", token) or "0"
    rect_ids = [f"anim-pipe-rect-{token_seed}-{i}" for i in range(len(anim.stages))]
    line_ids = [f"anim-pipe-line-{token_seed}-{i}" for i in range(len(anim.stages) - 1)]

    box_center_y = _PIPE_TOP_MARGIN + _PIPE_BOX_HEIGHT / 2
    total_width = len(anim.stages) * _PIPE_BOX_WIDTH + (len(anim.stages) - 1) * _PIPE_GAP
    total_height = _PIPE_TOP_MARGIN * 2 + _PIPE_BOX_HEIGHT

    def box_x(i: int) -> float:
        return i * (_PIPE_BOX_WIDTH + _PIPE_GAP)

    # Connectors are emitted BEFORE the boxes so z-order puts lines behind nodes
    # (diagram-design: "Draw arrows before boxes"), and each box's opaque rect
    # then covers the connector's ends.
    lines_html = []
    for i in range(len(anim.stages) - 1):
        x1 = box_x(i) + _PIPE_BOX_WIDTH
        x2 = box_x(i + 1)
        lines_html.append(
            f'<line class="anim__pipe-line" id="{line_ids[i]}" '
            f'x1="{x1:g}" y1="{box_center_y:g}" x2="{x2:g}" y2="{box_center_y:g}" '
            # The connector starts fully "undrawn": a dash as long as the line
            # itself, pushed entirely out of view. The timeline animates the
            # offset to 0, which walks the stroke into existence.
            f'stroke-dasharray="{_PIPE_GAP}" stroke-dashoffset="{_PIPE_GAP}"></line>'
        )

    boxes_html = []
    for i, (name, change) in enumerate(anim.stages):
        x = box_x(i)
        center_x = x + _PIPE_BOX_WIDTH / 2
        boxes_html.append(
            f'<g class="anim__pipe-stage">'
            f'<rect class="anim__pipe-box" id="{rect_ids[i]}" x="{x:g}" '
            f'y="{_PIPE_TOP_MARGIN}" width="{_PIPE_BOX_WIDTH}" '
            f'height="{_PIPE_BOX_HEIGHT}" rx="8" '
            f'fill="var(--anim-pipe-idle)"></rect>'
            f'<text class="anim__pipe-name" x="{center_x:g}" '
            f'y="{box_center_y - 4:g}" text-anchor="middle">{html.escape(name)}</text>'
            f'<text class="anim__pipe-change" x="{center_x:g}" '
            f'y="{box_center_y + 14:g}" text-anchor="middle">'
            f'{html.escape(change)}</text>'
            f'</g>'
        )

    steps_json: list[dict] = []
    for i in range(len(anim.stages)):
        steps_json.append({
            "targets": [f"#{rect_ids[i]}"],
            "props": {"fill": "var(--anim-pipe-active)"},
            "duration": 400,
            "ease": "outQuad",
        })
        if i > 0:
            steps_json.append({
                "targets": [f"#{rect_ids[i - 1]}"],
                "props": {"fill": "var(--anim-pipe-idle)"},
                "duration": 400,
                "ease": "outQuad",
                "position": "<",
            })
        if i < len(anim.stages) - 1:
            steps_json.append({
                "targets": [f"#{line_ids[i]}"],
                "props": {"strokeDashoffset": [_PIPE_GAP, 0]},
                "duration": STEP_SECONDS * 1000 // 2,
                "ease": "inOutQuad",
            })

    # Gotcha 2: snap every animated property back to baseline before the loop
    # restarts, or lap two starts from lap one's end state.
    steps_json.append({
        "kind": "set", "targets": [f"#{r}" for r in rect_ids],
        "props": {"fill": "var(--anim-pipe-idle)"},
    })
    steps_json.append({
        "kind": "set", "targets": [f"#{l}" for l in line_ids],
        "props": {"strokeDashoffset": _PIPE_GAP},
    })

    timeline_json = _timeline_island_json(
        {"loop": True, "loopDelay": 800, "steps": steps_json}
    )
    static_lines = "".join(
        f"<li>{html.escape(n)} — {html.escape(c)}</li>" for n, c in anim.stages
    )
    return (
        '<div class="anim anim--pipeline">'
        f'<svg class="anim__pipeline" dir="ltr" '
        f'viewBox="0 0 {total_width:g} {total_height:g}">'
        f"{''.join(lines_html)}{''.join(boxes_html)}</svg>"
        f'<script type="application/json" class="anim__timeline">{timeline_json}</script>'
        f'<ol class="anim__pipeline-static">{static_lines}</ol></div>'
    )
```

Add the dispatch in `_animate_html` (`:342-350`), before the final `path-trace` return:

```python
    if anim.pattern == "pipeline":
        return _pipeline_html(anim, token)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_mdrender.py -k pipeline -q`
Expected: PASS (10 tests total across Tasks 1–2).

- [ ] **Step 5: Run the full suite**

Run: `python -m pytest tests/ -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add scripts/p2c/mdrender.py tests/test_mdrender.py
git commit -m "feat: render the pipeline animate pattern"
```

---

### Task 3: Parse and render `layer-stack`

**Files:**
- Modify: `scripts/p2c/mdrender.py` — `_ANIMATE_KEY` (`:96`), `Animate`, `_LIST_HEADERS`, `lists`, whitelist, new branch, new constants, `_layer_stack_html`, `_animate_html` dispatch
- Test: `tests/test_mdrender.py`

**Interfaces:**
- Consumes: `_STAGE` regex from Task 1.
- Produces: `Animate.layers: list[tuple[str, str]]` (ordered bottom-up), `Animate.direction: str` (`"up"` or `"down"`, default `"up"`); `_layer_stack_html(anim: Animate, token: str) -> str`.

**Note:** `direction` is a scalar key, so `_ANIMATE_KEY` must accept it. Its current alternation is `pattern|before|after|caption`; any key not matching falls into the `else: caption = value` branch at `:164-165`, so **without widening the regex a `direction:` line would silently become the caption.**

- [ ] **Step 1: Write the failing tests**

```python
def test_layer_stack_parses_layers_bottom_up_and_defaults_direction_up():
    anim = parse_animate(
        "pattern: layer-stack\n"
        "layers:\n"
        "  - Pixels: raw sensor values\n"
        "  - Edges: local intensity changes\n"
        "  - Objects: assembled shapes\n"
    )
    assert anim.pattern == "layer-stack"
    assert anim.layers[0] == ("Pixels", "raw sensor values")
    assert anim.direction == "up"


def test_layer_stack_accepts_explicit_down_direction():
    anim = parse_animate(
        "pattern: layer-stack\ndirection: down\n"
        "layers:\n  - Top: starts here\n  - Bottom: ends here\n"
    )
    assert anim.direction == "down"


def test_layer_stack_rejects_an_unknown_direction():
    with pytest.raises(AnimateError, match="direction"):
        parse_animate(
            "pattern: layer-stack\ndirection: sideways\n"
            "layers:\n  - A: does a\n  - B: does b\n"
        )


def test_layer_stack_rejects_bad_layer_counts():
    with pytest.raises(AnimateError, match="at least 2 layers"):
        parse_animate("pattern: layer-stack\nlayers:\n  - Only: one\n")
    body = "pattern: layer-stack\nlayers:\n" + "".join(
        f"  - L{i}: does {i}\n" for i in range(7)
    )
    with pytest.raises(AnimateError, match="at most 6 layers"):
        parse_animate(body)


def test_layer_stack_html_is_ltr_and_static_lists_every_layer():
    anim = parse_animate(
        "pattern: layer-stack\n"
        "layers:\n  - Pixels: raw values\n  - Edges: gradients\n  - Objects: shapes\n"
    )
    out = _layer_stack_html(anim, "ANIMTOKEN4")
    assert 'dir="ltr"' in out
    assert out.count("<li>") == 3
    assert "Pixels" in out and "Objects" in out


def test_layer_stack_timeline_resets_animated_properties():
    anim = parse_animate(
        "pattern: layer-stack\n"
        "layers:\n  - Pixels: raw values\n  - Edges: gradients\n"
    )
    out = _layer_stack_html(anim, "ANIMTOKEN4")
    data = json.loads(
        re.search(
            r'<script type="application/json" class="anim__timeline">(.*?)</script>',
            out, re.S,
        ).group(1)
    )
    animated = {
        p for s in data["steps"] if s.get("kind") != "set" for p in (s.get("props") or {})
    }
    reset = {
        p for s in data["steps"] if s.get("kind") == "set" for p in (s.get("props") or {})
    }
    assert animated <= reset


def test_layer_stack_constants_are_divisible_by_four():
    for value in (_LAYER_WIDTH, _LAYER_HEIGHT, _LAYER_GAP, _LAYER_TOP_MARGIN):
        assert value % 4 == 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_mdrender.py -k layer_stack -q`
Expected: FAIL — pattern not in whitelist; `_layer_stack_html` undefined.

- [ ] **Step 3: Implement parser and renderer**

Widen `_ANIMATE_KEY` (`:96`) so `direction:` is a real key rather than falling through to `caption`:

```python
_ANIMATE_KEY = re.compile(
    r"^(?P<key>pattern|before|after|caption|direction|from|to):\s*(?P<value>.*)$"
)
```

(`from`/`to` are added here for Task 4; adding them now avoids touching this line twice.)

In `parse_animate`, extend the key dispatch (`:156-166`) so the new scalars land in
their own variables instead of `caption`:

```python
            elif name == "direction":
                direction = value
            elif name == "from":
                from_value = value
            elif name == "to":
                to_value = value
```

and declare them beside `caption` (`:136`):

```python
    direction: str | None = None
    from_value: str | None = None
    to_value: str | None = None
```

Add to the `Animate` dataclass:

```python
    layers: list[tuple[str, str]] = field(default_factory=list)
    direction: str = "up"
```

Add to `_LIST_HEADERS`:

```python
    "layers:": "layers",
```

Add `layers_raw: list[str] = []` and register `"layers": layers_raw` in `lists`.

Extend the whitelist tuple and message to include `"layer-stack"`.

Add the branch (before `else:  # path-trace`):

```python
    elif pattern == "layer-stack":
        if before or after or states_raw or transitions_raw or array_raw or ops_raw or points_raw or stages_raw:
            raise AnimateError(
                "layer-stack does not use 'before:'/'after:'/'states:'/'transitions:'/"
                "'array:'/'ops:'/'points:'/'stages:'"
            )
        if direction is not None and direction not in ("up", "down"):
            raise AnimateError(
                f"layer-stack direction must be 'up' or 'down', got {direction!r}"
            )
        if len(layers_raw) < 2:
            raise AnimateError("layer-stack needs at least 2 layers")
        if len(layers_raw) > 6:
            raise AnimateError("layer-stack takes at most 6 layers")
        layers: list[tuple[str, str]] = []
        for line in layers_raw:
            match = _STAGE.match(line)
            if not match:
                raise AnimateError(
                    f"layer-stack layer {line!r} must be written as '<name>: <what it adds>'"
                )
            layers.append((match.group("name").strip(), match.group("change").strip()))
        return Animate(
            pattern=pattern, layers=layers, direction=direction or "up",
            caption=caption or "",
        )
```

Add constants:

```python
_LAYER_WIDTH = 260
_LAYER_HEIGHT = 44
_LAYER_GAP = 12
_LAYER_TOP_MARGIN = 20
```

Add the renderer:

```python
def _layer_stack_html(anim: Animate, token: str) -> str:
    """Tiers appear one at a time, bottom-up by default.

    `layers` is authored bottom-up, so index 0 is drawn at the LARGEST y (the
    bottom of the SVG). A `direction: down` block reverses only the reveal
    ORDER, never the drawn positions -- the stack's geometry is the same
    picture either way, which is what makes the static fallback correct for both.
    """
    token_seed = re.sub(r"\D", "", token) or "0"
    count = len(anim.layers)
    rect_ids = [f"anim-layer-rect-{token_seed}-{i}" for i in range(count)]
    total_height = _LAYER_TOP_MARGIN * 2 + count * _LAYER_HEIGHT + (count - 1) * _LAYER_GAP
    total_width = _LAYER_WIDTH + _LAYER_TOP_MARGIN * 2

    def layer_y(i: int) -> float:
        # i == 0 is the bottom layer: count it down from the stack's base.
        from_top = count - 1 - i
        return _LAYER_TOP_MARGIN + from_top * (_LAYER_HEIGHT + _LAYER_GAP)

    rows_html = []
    for i, (name, adds) in enumerate(anim.layers):
        y = layer_y(i)
        rows_html.append(
            f'<g class="anim__layer-row">'
            f'<rect class="anim__layer-box" id="{rect_ids[i]}" '
            f'x="{_LAYER_TOP_MARGIN}" y="{y:g}" width="{_LAYER_WIDTH}" '
            f'height="{_LAYER_HEIGHT}" rx="6" fill="var(--anim-layer-idle)" '
            f'opacity="0"></rect>'
            f'<text class="anim__layer-name" x="{_LAYER_TOP_MARGIN + 12}" '
            f'y="{y + _LAYER_HEIGHT / 2 + 4:g}">{html.escape(name)}</text>'
            f'<text class="anim__layer-adds" '
            f'x="{_LAYER_TOP_MARGIN + _LAYER_WIDTH - 12}" '
            f'y="{y + _LAYER_HEIGHT / 2 + 4:g}" text-anchor="end">'
            f'{html.escape(adds)}</text>'
            f'</g>'
        )

    order = range(count) if anim.direction == "up" else range(count - 1, -1, -1)
    steps_json: list[dict] = []
    for position, i in enumerate(order):
        steps_json.append({
            "targets": [f"#{rect_ids[i]}"],
            "props": {"opacity": [0, 1], "fill": "var(--anim-layer-active)"},
            "duration": 500,
            "ease": "outQuad",
        })
        if position > 0:
            previous = list(order)[position - 1]
            steps_json.append({
                "targets": [f"#{rect_ids[previous]}"],
                "props": {"fill": "var(--anim-layer-idle)"},
                "duration": 500,
                "ease": "outQuad",
                "position": "<",
            })

    steps_json.append({
        "kind": "set", "targets": [f"#{r}" for r in rect_ids],
        "props": {"opacity": 0, "fill": "var(--anim-layer-idle)"},
    })

    timeline_json = _timeline_island_json(
        {"loop": True, "loopDelay": 900, "steps": steps_json}
    )
    static_lines = "".join(
        f"<li>{html.escape(n)} — {html.escape(a)}</li>" for n, a in anim.layers
    )
    return (
        '<div class="anim anim--layer-stack">'
        f'<svg class="anim__layer-stack" dir="ltr" '
        f'viewBox="0 0 {total_width:g} {total_height:g}">'
        f"{''.join(rows_html)}</svg>"
        f'<script type="application/json" class="anim__timeline">{timeline_json}</script>'
        f'<ol class="anim__layer-static">{static_lines}</ol></div>'
    )
```

Add the dispatch in `_animate_html`:

```python
    if anim.pattern == "layer-stack":
        return _layer_stack_html(anim, token)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_mdrender.py -k layer_stack -q`
Expected: PASS (7 tests).

- [ ] **Step 5: Run the full suite**

Run: `python -m pytest tests/ -q`
Expected: PASS. In particular the existing `path-trace` caption tests must still pass — confirming the widened `_ANIMATE_KEY` did not change how `caption:` is handled.

- [ ] **Step 6: Commit**

```bash
git add scripts/p2c/mdrender.py tests/test_mdrender.py
git commit -m "feat: add the layer-stack animate pattern"
```

---

### Task 4: Parse and render `transform`

**Files:**
- Modify: `scripts/p2c/mdrender.py` — `Animate`, `_LIST_HEADERS`, `lists`, whitelist, new branch, constants, `_transform_html`, `_animate_html` dispatch
- Test: `tests/test_mdrender.py`

**Interfaces:**
- Consumes: `from_value`/`to_value` parse variables and the widened `_ANIMATE_KEY` from Task 3.
- Produces: `Animate.from_entity: str`, `Animate.to_entity: str`, `Animate.steps: list[str]`; `_transform_html(anim: Animate, token: str) -> str`.

**Naming note:** the dataclass fields are `from_entity`/`to_entity` because `from` is a Python keyword and cannot be an attribute name written as `anim.from`.

- [ ] **Step 1: Write the failing tests**

```python
def test_transform_parses_endpoints_and_steps():
    anim = parse_animate(
        "pattern: transform\n"
        "from: Disparity map\n"
        "to: Metric depth map\n"
        "steps:\n"
        "  - Invert each disparity value\n"
        "  - Scale by the focal-length constant\n"
    )
    assert anim.from_entity == "Disparity map"
    assert anim.to_entity == "Metric depth map"
    assert anim.steps == [
        "Invert each disparity value",
        "Scale by the focal-length constant",
    ]


def test_transform_requires_both_endpoints():
    with pytest.raises(AnimateError, match="needs both 'from:' and 'to:'"):
        parse_animate("pattern: transform\nfrom: Only a start\nsteps:\n  - Does a thing\n")


def test_transform_rejects_bad_step_counts():
    with pytest.raises(AnimateError, match="at least 1 step"):
        parse_animate("pattern: transform\nfrom: A\nto: B\n")
    body = "pattern: transform\nfrom: A\nto: B\nsteps:\n" + "".join(
        f"  - Step {i}\n" for i in range(5)
    )
    with pytest.raises(AnimateError, match="at most 4 steps"):
        parse_animate(body)


def test_transform_html_is_ltr_and_shows_both_endpoints_statically():
    anim = parse_animate(
        "pattern: transform\nfrom: Disparity map\nto: Metric depth map\n"
        "steps:\n  - Invert each value\n"
    )
    out = _transform_html(anim, "ANIMTOKEN5")
    assert 'dir="ltr"' in out
    assert "Disparity map" in out and "Metric depth map" in out
    assert "Invert each value" in out


def test_transform_timeline_resets_animated_properties():
    anim = parse_animate(
        "pattern: transform\nfrom: A thing\nto: Another thing\n"
        "steps:\n  - Change it\n  - Change it again\n"
    )
    out = _transform_html(anim, "ANIMTOKEN5")
    data = json.loads(
        re.search(
            r'<script type="application/json" class="anim__timeline">(.*?)</script>',
            out, re.S,
        ).group(1)
    )
    animated = {
        p for s in data["steps"] if s.get("kind") != "set" for p in (s.get("props") or {})
    }
    reset = {
        p for s in data["steps"] if s.get("kind") == "set" for p in (s.get("props") or {})
    }
    assert animated <= reset


def test_transform_constants_are_divisible_by_four():
    for value in (_XFORM_BOX_WIDTH, _XFORM_BOX_HEIGHT, _XFORM_GAP, _XFORM_TOP_MARGIN):
        assert value % 4 == 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_mdrender.py -k transform -q`
Expected: FAIL — pattern not in whitelist; `_transform_html` undefined.

- [ ] **Step 3: Implement parser and renderer**

Add to `Animate`:

```python
    from_entity: str = ""
    to_entity: str = ""
    steps: list[str] = field(default_factory=list)
```

Add to `_LIST_HEADERS`:

```python
    "steps:": "steps",
```

Add `steps_raw: list[str] = []` and register `"steps": steps_raw` in `lists`.

Extend the whitelist tuple and message to include `"transform"`.

Add the branch (before `else:  # path-trace`):

```python
    elif pattern == "transform":
        if before or after or states_raw or transitions_raw or array_raw or ops_raw or points_raw or stages_raw or layers_raw:
            raise AnimateError(
                "transform does not use 'before:'/'after:'/'states:'/'transitions:'/"
                "'array:'/'ops:'/'points:'/'stages:'/'layers:'"
            )
        if not from_value or not to_value:
            raise AnimateError("transform needs both 'from:' and 'to:'")
        if not steps_raw:
            raise AnimateError("transform needs at least 1 step")
        if len(steps_raw) > 4:
            raise AnimateError("transform takes at most 4 steps")
        return Animate(
            pattern=pattern, from_entity=from_value, to_entity=to_value,
            steps=list(steps_raw), caption=caption or "",
        )
```

Add constants:

```python
_XFORM_BOX_WIDTH = 180
_XFORM_BOX_HEIGHT = 60
_XFORM_GAP = 120  # room between the two endpoint boxes for the step labels
_XFORM_TOP_MARGIN = 24
```

Add the renderer:

```python
def _transform_html(anim: Animate, token: str) -> str:
    """One entity becomes another; each step's label appears over the connector.

    The two endpoint boxes are permanent structure. What animates is the
    connector drawing itself and the step labels appearing in order over it,
    with the destination box taking the accent only once the last step lands.
    """
    token_seed = re.sub(r"\D", "", token) or "0"
    from_id = f"anim-xform-from-{token_seed}"
    to_id = f"anim-xform-to-{token_seed}"
    line_id = f"anim-xform-line-{token_seed}"
    step_ids = [f"anim-xform-step-{token_seed}-{i}" for i in range(len(anim.steps))]

    box_center_y = _XFORM_TOP_MARGIN + _XFORM_BOX_HEIGHT / 2
    total_width = _XFORM_BOX_WIDTH * 2 + _XFORM_GAP
    total_height = _XFORM_TOP_MARGIN * 2 + _XFORM_BOX_HEIGHT
    line_x1 = _XFORM_BOX_WIDTH
    line_x2 = _XFORM_BOX_WIDTH + _XFORM_GAP
    label_center_x = line_x1 + _XFORM_GAP / 2

    def endpoint(box_id: str, x: float, label: str) -> str:
        return (
            f'<g class="anim__xform-endpoint">'
            f'<rect class="anim__xform-box" id="{box_id}" x="{x:g}" '
            f'y="{_XFORM_TOP_MARGIN}" width="{_XFORM_BOX_WIDTH}" '
            f'height="{_XFORM_BOX_HEIGHT}" rx="8" '
            f'fill="var(--anim-xform-idle)"></rect>'
            f'<text class="anim__xform-label" x="{x + _XFORM_BOX_WIDTH / 2:g}" '
            f'y="{box_center_y + 4:g}" text-anchor="middle">{html.escape(label)}</text>'
            f'</g>'
        )

    # Step labels sit ABOVE the connector with a visible gap (diagram-design
    # rule 2: never let a label sit on its line), each over its own opaque mask
    # rect so the connector cannot bleed through the text.
    labels_html = []
    for i, text in enumerate(anim.steps):
        labels_html.append(
            f'<g class="anim__xform-step" id="{step_ids[i]}" opacity="0">'
            f'<rect class="anim__xform-step-bg" x="{label_center_x - 56:g}" '
            f'y="{box_center_y - 26:g}" width="112" height="18" rx="2"></rect>'
            f'<text class="anim__xform-step-text" x="{label_center_x:g}" '
            f'y="{box_center_y - 13:g}" text-anchor="middle">'
            f'{html.escape(text)}</text>'
            f'</g>'
        )

    steps_json: list[dict] = [
        {
            "targets": [f"#{line_id}"],
            "props": {"strokeDashoffset": [_XFORM_GAP, 0]},
            "duration": STEP_SECONDS * 1000,
            "ease": "inOutQuad",
        }
    ]
    for i, step_id in enumerate(step_ids):
        steps_json.append({
            "targets": [f"#{step_id}"],
            "props": {"opacity": [0, 1]},
            "duration": 400,
            "ease": "outQuad",
        })
        if i > 0:
            steps_json.append({
                "targets": [f"#{step_ids[i - 1]}"],
                "props": {"opacity": 0},
                "duration": 400,
                "ease": "outQuad",
                "position": "<",
            })
    steps_json.append({
        "targets": [f"#{to_id}"],
        "props": {"fill": "var(--anim-xform-active)"},
        "duration": 500,
        "ease": "outQuad",
    })

    steps_json.append({
        "kind": "set", "targets": [f"#{s}" for s in step_ids], "props": {"opacity": 0},
    })
    steps_json.append({
        "kind": "set", "targets": [f"#{line_id}"],
        "props": {"strokeDashoffset": _XFORM_GAP},
    })
    steps_json.append({
        "kind": "set", "targets": [f"#{to_id}"],
        "props": {"fill": "var(--anim-xform-idle)"},
    })

    timeline_json = _timeline_island_json(
        {"loop": True, "loopDelay": 900, "steps": steps_json}
    )
    static_steps = "".join(f"<li>{html.escape(s)}</li>" for s in anim.steps)
    return (
        '<div class="anim anim--transform">'
        f'<svg class="anim__transform" dir="ltr" '
        f'viewBox="0 0 {total_width:g} {total_height:g}">'
        f'<line class="anim__xform-line" id="{line_id}" x1="{line_x1:g}" '
        f'y1="{box_center_y:g}" x2="{line_x2:g}" y2="{box_center_y:g}" '
        f'stroke-dasharray="{_XFORM_GAP}" stroke-dashoffset="{_XFORM_GAP}"></line>'
        f'{endpoint(from_id, 0, anim.from_entity)}'
        f'{endpoint(to_id, _XFORM_BOX_WIDTH + _XFORM_GAP, anim.to_entity)}'
        f"{''.join(labels_html)}</svg>"
        f'<script type="application/json" class="anim__timeline">{timeline_json}</script>'
        f'<ol class="anim__xform-static">{static_steps}</ol></div>'
    )
```

Add the dispatch in `_animate_html`:

```python
    if anim.pattern == "transform":
        return _transform_html(anim, token)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_mdrender.py -k transform -q`
Expected: PASS (6 tests).

- [ ] **Step 5: Run the full suite**

Run: `python -m pytest tests/ -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add scripts/p2c/mdrender.py tests/test_mdrender.py
git commit -m "feat: add the transform animate pattern"
```

---

### Task 5: Count animate blocks per topic

**Files:**
- Modify: `scripts/p2c/mdrender.py:1074-1088` (`Rendered`), `:1215-1216`, `:1260-1268`, `:1289-1301`
- Test: `tests/test_mdrender.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `Rendered.animations_per_topic: dict[str, int]` — animate-block count keyed by topic id, with an entry of `0` for every topic that has none (mirroring how `quizzes_per_topic` is backfilled at `:1276-1277`). Task 6 consumes this.

**Why:** `Rendered` currently exposes only `uses_animate: bool`, which cannot measure a coverage ratio.

- [ ] **Step 1: Write the failing test**

```python
def test_animations_per_topic_counts_blocks_and_backfills_zeros():
    md = (
        "# Course\n\n"
        "## Module one\n\n"
        "### Topic A\n\n"
        "<!-- topic: topic-a -->\n\n"
        "```animate\n"
        "pattern: pipeline\n"
        "stages:\n"
        "  - Raw: unprocessed\n"
        "  - Done: processed\n"
        "```\n\n"
        "### Topic B\n\n"
        "<!-- topic: topic-b -->\n\n"
        "Prose only.\n"
    )
    rendered = render_markdown(md)
    assert rendered.animations_per_topic["topic-a"] == 1
    # Backfilled, not absent: the floor check divides over every topic.
    assert rendered.animations_per_topic["topic-b"] == 0
```

Match the topic-marker syntax and `render_markdown` signature used by the
neighbouring tests in `tests/test_mdrender.py`; if topics are marked differently
there, mirror that form rather than the placeholder comment above.

- [ ] **Step 2: Run the test to verify it fails**

Run: `python -m pytest tests/test_mdrender.py -k animations_per_topic -q`
Expected: FAIL — `AttributeError: 'Rendered' object has no attribute 'animations_per_topic'`.

- [ ] **Step 3: Implement the tally**

Add to `Rendered` (after `uses_animate`, `:1085`):

```python
    animations_per_topic: dict[str, int] = field(default_factory=dict)
```

Beside `uses_animate = False` (`:1216`):

```python
    animations_per_topic: dict[str, int] = {}
```

In the `animate` branch, immediately after `uses_animate = True` (`:1267`):

```python
            if topic_id:
                animations_per_topic[topic_id] = animations_per_topic.get(topic_id, 0) + 1
```

Beside the existing quiz backfill (`:1276-1277`):

```python
    for topic_id in (s.topic_id for s in sections if s.topic_id):
        animations_per_topic.setdefault(topic_id, 0)
```

Pass it through the constructor (`:1289-1301`):

```python
        animations_per_topic=animations_per_topic,
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `python -m pytest tests/test_mdrender.py -k animations_per_topic -q`
Expected: PASS.

- [ ] **Step 5: Run the full suite**

Run: `python -m pytest tests/ -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add scripts/p2c/mdrender.py tests/test_mdrender.py
git commit -m "feat: tally animate blocks per topic in Rendered"
```

---

### Task 6: Detect linear no-fan-out mermaid chains

**Files:**
- Modify: `scripts/p2c/mdrender.py` (`Rendered`, render loop), `scripts/p2c/validate.py`
- Test: `tests/test_validate.py`

**Interfaces:**
- Consumes: nothing from Task 5.
- Produces: `Rendered.linear_mermaid_topics: list[str]` — topic ids whose mermaid blocks are all linear chains. Task 7 uses this to name conversion candidates.

**Definition (from the spec):** a mermaid block is a *linear chain* when no node is the source of more than one edge. This is the rule that identified the 17 misclassified diagrams in unit 2.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_validate.py`:

```python
from p2c.mdrender import is_linear_mermaid


def test_linear_chain_is_detected():
    assert is_linear_mermaid("flowchart LR\n  A --> B\n  B --> C\n")


def test_branching_diagram_is_not_linear():
    # A is the source of two edges: that fan-out is what mermaid draws well.
    assert not is_linear_mermaid("flowchart LR\n  A --> B\n  A --> C\n")


def test_single_edge_counts_as_linear():
    assert is_linear_mermaid("flowchart LR\n  A --> B\n")


def test_diagram_with_no_edges_is_not_linear():
    assert not is_linear_mermaid("flowchart LR\n  A\n")


def test_labelled_edges_are_still_linear():
    assert is_linear_mermaid("flowchart LR\n  A -->|yes| B\n  B -->|next| C\n")


def test_node_labels_do_not_break_source_identity():
    # Regression: real diagrams write the label on first mention only, so `M["x"]`
    # and a later bare `M` are the SAME source. A regex that folds the label into
    # the id scores this fan-out as linear.
    assert not is_linear_mermaid(
        'flowchart LR\n  M["camera"] -->|"a"| A["roof"]\n  M -->|"b"| B["ground"]\n'
    )


def test_bracketed_nodes_on_a_straight_chain_are_linear():
    assert is_linear_mermaid(
        'flowchart LR\n  A["Start"] --> B["Middle"]\n  B --> C["End"]\n'
    )
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_validate.py -k linear -q`
Expected: FAIL — `ImportError: cannot import name 'is_linear_mermaid'`.

- [ ] **Step 3: Implement the detector and wire it into `Rendered`**

In `scripts/p2c/mdrender.py`, add near the other module-level regexes:

```python
# Matches "A --> B", "A -->|label| B", "A --- B", "A -.-> B", "A ==> B",
# with or without a node label: real course diagrams are written
# `M["מצלמה"] -->|"depth"| A["roof"]`, so the optional bracket/paren/brace
# label after the node id MUST be skipped -- otherwise the same node reads as
# two different sources depending on whether that occurrence carried a label,
# and a fan-out is silently scored as linear. Verified against
# unit2_lecture_tutorial-course: 17 of 42 blocks are linear chains.
_MERMAID_EDGE = re.compile(
    r"(?P<from>[A-Za-z0-9_-]+)\s*"
    r"(?:\[[^\]]*\]|\([^)]*\)|\{[^}]*\})?\s*"
    r"(?:-{2,3}>|-{3}|-\.-+>|={2,}>)"
    r"(?:\|[^|]*\|)?\s*"
    r"(?P<to>[A-Za-z0-9_-]+)"
)


def is_linear_mermaid(body: str) -> bool:
    """True when no node is the source of more than one edge.

    That shape -- a straight line of boxes -- is what `references/agents/
    course-writer.md` already calls a sequence rather than a flowchart. A
    diagram with no edges at all is not a chain and returns False.
    """
    sources: dict[str, int] = {}
    edges = 0
    for match in _MERMAID_EDGE.finditer(body):
        source = match.group("from")
        sources[source] = sources.get(source, 0) + 1
        edges += 1
    if edges == 0:
        return False
    return max(sources.values()) == 1
```

Add to `Rendered` (after `animations_per_topic`):

```python
    linear_mermaid_topics: list[str] = field(default_factory=list)
```

In the render loop, declare a tracker beside `uses_mermaid = False` (`:1215`):

```python
    mermaid_linearity: dict[str, list[bool]] = {}
```

In the successful-mermaid branch, right after `uses_mermaid = True` (`:1246`):

```python
                if topic_id:
                    mermaid_linearity.setdefault(topic_id, []).append(
                        is_linear_mermaid(fence.body)
                    )
```

Compute the list beside `topics_missing_visual` (`:1279-1282`):

```python
    # A topic qualifies only when EVERY mermaid block it has is linear: a topic
    # that also carries a genuinely branching diagram is not a mis-classification.
    linear_mermaid_topics = [
        tid for tid, flags in mermaid_linearity.items() if flags and all(flags)
    ]
```

Pass it through the constructor:

```python
        linear_mermaid_topics=linear_mermaid_topics,
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_validate.py -k linear -q`
Expected: PASS (5 tests).

- [ ] **Step 5: Run the full suite**

Run: `python -m pytest tests/ -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add scripts/p2c/mdrender.py tests/test_validate.py
git commit -m "feat: detect linear no-fan-out mermaid chains"
```

---

### Task 7: Enforce the 25% animation floor

**Files:**
- Modify: `scripts/p2c/validate.py:13-26` (`ROUTE_FOR_CODE`), and the check body near the existing visual check
- Test: `tests/test_validate.py`

**Interfaces:**
- Consumes: `Rendered.animations_per_topic` (Task 5), `Rendered.linear_mermaid_topics` (Task 6), `Rendered.topics_missing_visual` (existing).
- Produces: a `Finding` with `code="animation_floor"`, `blocking=True`, `route="writer"`.

**Rules (from the spec):**
- Denominator = topics that **owe a visual** = every topic *not* justified by a `no-visual` comment. This reuses the existing definition rather than introducing a second one, and `depth` is deliberately not consulted (the build is not `depth`-aware).
- Required = `ceil(0.25 * denominator)`.
- Skipped entirely when the denominator is 0.
- The message names the linear-chain topics as conversion candidates.

- [ ] **Step 1: Write the failing tests**

```python
import math
from p2c.validate import ROUTE_FOR_CODE, animation_floor_findings


class _FakeRendered:
    def __init__(self, animations_per_topic, linear_mermaid_topics, justified=()):
        self.animations_per_topic = animations_per_topic
        self.linear_mermaid_topics = list(linear_mermaid_topics)
        self._justified = set(justified)

    @property
    def topic_ids(self):
        return list(self.animations_per_topic)


def test_floor_is_met_when_a_quarter_of_topics_animate():
    rendered = _FakeRendered({"t1": 1, "t2": 0, "t3": 0, "t4": 0}, [])
    assert animation_floor_findings(rendered, justified_topics=set()) == []


def test_floor_is_blocking_when_under_and_names_conversion_candidates():
    rendered = _FakeRendered(
        {"t1": 0, "t2": 0, "t3": 0, "t4": 0}, ["t2", "t3"]
    )
    findings = animation_floor_findings(rendered, justified_topics=set())
    assert len(findings) == 1
    assert findings[0].code == "animation_floor"
    assert findings[0].blocking is True
    assert findings[0].route == "writer"
    # The writer is told WHICH diagrams are misclassified, not just the count.
    assert "t2" in findings[0].message and "t3" in findings[0].message


def test_requirement_rounds_up():
    # 3 owing topics * 0.25 = 0.75 -> still requires 1.
    rendered = _FakeRendered({"t1": 0, "t2": 0, "t3": 0}, [])
    assert animation_floor_findings(rendered, justified_topics=set())
    rendered_ok = _FakeRendered({"t1": 1, "t2": 0, "t3": 0}, [])
    assert animation_floor_findings(rendered_ok, justified_topics=set()) == []


def test_no_visual_justified_topics_leave_the_denominator():
    # 4 topics but 2 are justified brief ones => denominator 2 => requires 1.
    rendered = _FakeRendered({"t1": 1, "t2": 0, "t3": 0, "t4": 0}, [])
    assert animation_floor_findings(
        rendered, justified_topics={"t3", "t4"}
    ) == []


def test_check_is_skipped_when_no_topic_owes_a_visual():
    rendered = _FakeRendered({"t1": 0, "t2": 0}, [])
    assert animation_floor_findings(
        rendered, justified_topics={"t1", "t2"}
    ) == []


def test_all_branching_course_still_fails_without_naming_candidates():
    rendered = _FakeRendered({"t1": 0, "t2": 0, "t3": 0, "t4": 0}, [])
    findings = animation_floor_findings(rendered, justified_topics=set())
    assert len(findings) == 1
    assert "no linear" in findings[0].message.lower()


def test_animation_floor_routes_to_the_writer():
    assert ROUTE_FOR_CODE["animation_floor"] == "writer"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_validate.py -k floor -q`
Expected: FAIL — `ImportError: cannot import name 'animation_floor_findings'`.

- [ ] **Step 3: Implement the check**

In `scripts/p2c/validate.py`, add `import math` beside `import re` (`:7`), and add
to `ROUTE_FOR_CODE` (`:13-26`):

```python
    "animation_floor": "writer",
```

Add the function:

```python
ANIMATION_FLOOR = 0.25


def animation_floor_findings(rendered, justified_topics: set[str]) -> list[Finding]:
    """At least a quarter of the topics that owe a visual must animate.

    The denominator deliberately reuses "owes a visual" (every topic without a
    `no-visual` justification) rather than the outline's `depth` field: the
    build is not depth-aware, and one definition is better than two that can
    drift apart. `brief` topics carry `no-visual` by rule, so they drop out.
    """
    owing = [t for t in rendered.topic_ids if t not in justified_topics]
    if not owing:
        return []
    required = math.ceil(ANIMATION_FLOOR * len(owing))
    animated = sum(
        1 for t in owing if rendered.animations_per_topic.get(t, 0) > 0
    )
    if animated >= required:
        return []

    candidates = [t for t in rendered.linear_mermaid_topics if t in owing]
    if candidates:
        advice = (
            "convert these topics' mermaid diagrams to `animate` blocks — each is a "
            "linear chain with no fan-out, which is a sequence rather than a "
            f"structure: {', '.join(sorted(candidates))}"
        )
    else:
        advice = (
            "no linear mermaid chains were found to convert, so add `animate` blocks "
            "(pipeline, layer-stack, transform, state-machine, state-toggle) to the "
            "topics whose content is a sequence rather than a structure"
        )
    return [
        Finding(
            code="animation_floor",
            message=(
                f"only {animated} of {len(owing)} topics that need a visual use an "
                f"`animate` block ({required} required, {int(ANIMATION_FLOOR * 100)}%); "
                f"{advice}"
            ),
            blocking=True,
            route="writer",
        )
    ]
```

Call it from the module's existing validation entry point, alongside the
`topics_missing_visual` loop (`:180-186`), passing the set of topics that carry a
`no-visual` justification. That set is `set(rendered.topic_ids) - set(rendered.topics_missing_visual)`
minus the topics that actually have a visual; the entry point already distinguishes
these, so derive `justified_topics` there and extend the returned findings list with
`animation_floor_findings(rendered, justified_topics)`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_validate.py -k floor -q`
Expected: PASS (7 tests).

- [ ] **Step 5: Run the full suite**

Run: `python -m pytest tests/ -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add scripts/p2c/validate.py tests/test_validate.py
git commit -m "feat: enforce a 25% animation coverage floor"
```

---

### Task 8: Style the three patterns, with print and reduced-motion fallbacks

**Files:**
- Modify: `assets/base/layout.css` (tokens near `:259`, `:347`; new rules), `assets/base/print.css`
- Test: `tests/test_assets.py`

**Interfaces:**
- Consumes: class names and CSS custom properties emitted by Tasks 2–4: `--anim-pipe-idle`, `--anim-pipe-active`, `--anim-layer-idle`, `--anim-layer-active`, `--anim-xform-idle`, `--anim-xform-active`; classes `anim--pipeline`, `anim--layer-stack`, `anim--transform` and their children.
- Produces: no Python interface.

**Critical:** every SVG element the timeline animates starts hidden/undrawn via an inline attribute (`opacity="0"`, `stroke-dashoffset`). Under reduced-motion and print the timeline never runs, so **CSS must override those inline values** to reveal everything — otherwise the animated markup renders blank. This is why each pattern ships an `<ol>` static fallback *and* a reveal override, matching the existing `.anim--array-ops` precedent.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_assets.py`:

```python
def test_new_animate_patterns_define_their_tokens_and_static_fallbacks():
    css = (ASSETS / "base" / "layout.css").read_text(encoding="utf-8")
    for token in (
        "--anim-pipe-idle", "--anim-pipe-active",
        "--anim-layer-idle", "--anim-layer-active",
        "--anim-xform-idle", "--anim-xform-active",
    ):
        assert token in css, f"{token} is not defined"
    # Reduced motion must reveal the markup the timeline would have animated.
    reduced = css.split("@media (prefers-reduced-motion: reduce)")
    assert len(reduced) > 1
    tail = "".join(reduced[1:])
    for selector in ("anim--pipeline", "anim--layer-stack", "anim--transform"):
        assert selector in tail, f"{selector} has no reduced-motion fallback"
```

Use whatever constant `tests/test_assets.py` already uses for the assets directory
in place of `ASSETS` if it differs.

- [ ] **Step 2: Run the test to verify it fails**

Run: `python -m pytest tests/test_assets.py -k new_animate_patterns -q`
Expected: FAIL — `--anim-pipe-idle is not defined`.

- [ ] **Step 3: Implement the styles**

In `assets/base/layout.css`, add tokens beside the existing `--anim-state-*` block (`:259`):

```css
  --anim-pipe-idle: var(--color-surface);
  --anim-pipe-active: var(--color-accent);
  --anim-layer-idle: var(--color-surface);
  --anim-layer-active: var(--color-accent);
  --anim-xform-idle: var(--color-surface);
  --anim-xform-active: var(--color-accent);
```

Add presentation rules (no shadows; hairline borders; radius already set per-element):

```css
.anim__pipeline,
.anim__layer-stack,
.anim__transform {
  width: 100%;
  height: auto;
}

.anim__pipe-box,
.anim__layer-box,
.anim__xform-box {
  stroke: var(--color-border);
  stroke-width: 1;
}

.anim__pipe-line,
.anim__xform-line {
  stroke: var(--color-muted);
  stroke-width: 2;
  fill: none;
}

.anim__pipe-name,
.anim__layer-name,
.anim__xform-label {
  font-family: var(--font-body);
  font-size: 13px;
  font-weight: 600;
  fill: var(--color-fg);
}

.anim__pipe-change,
.anim__layer-adds,
.anim__xform-step-text {
  font-family: var(--font-body);
  font-size: 11px;
  fill: var(--color-muted);
}

.anim__xform-step-bg {
  fill: var(--color-bg);
}

/* The static <ol> lists are the print/reduced-motion presentation only; during
   normal animated playback the SVG carries the meaning. Same toggle-pair
   pattern as .anim--array-ops. */
.anim__pipeline-static,
.anim__layer-static,
.anim__xform-static {
  display: none;
}
```

Add the reveal overrides inside the existing `@media (prefers-reduced-motion: reduce)` block (`:314` / `:414`):

```css
  /* The timeline never runs here, so every element it would have revealed must
     be forced visible -- inline opacity="0" and stroke-dashoffset would
     otherwise leave these diagrams blank. Every stage/layer/step shows at once. */
  .anim--pipeline .anim__pipe-line,
  .anim--transform .anim__xform-line {
    stroke-dashoffset: 0 !important;
  }

  .anim--layer-stack .anim__layer-box,
  .anim--transform .anim__xform-step {
    opacity: 1 !important;
  }

  .anim--pipeline .anim__pipeline-static,
  .anim--layer-stack .anim__layer-static,
  .anim--transform .anim__xform-static {
    display: block;
  }
```

Mirror the same three overrides in `assets/base/print.css`, following how that file
already handles `.anim--array-ops` and `.anim--state-machine`.

- [ ] **Step 4: Run the test to verify it passes**

Run: `python -m pytest tests/test_assets.py -k new_animate_patterns -q`
Expected: PASS.

- [ ] **Step 5: Run the full suite**

Run: `python -m pytest tests/ -q`
Expected: PASS. If golden-file tests (`tests/golden/course.html`) now differ, inspect
the diff to confirm it contains only the new patterns' markup, then regenerate the
goldens using the project's existing regeneration command.

- [ ] **Step 6: Commit**

```bash
git add assets/base/layout.css assets/base/print.css tests/test_assets.py
git commit -m "feat: style the pipeline, layer-stack, and transform patterns"
```

---

### Task 9: Document the patterns and the 25% requirement

**Files:**
- Modify: `references/quiz-format.md` (the `animate` section), `references/agents/course-writer.md:119-192` (the "Visual per topic" section)
- Test: none — documentation only; correctness is verified by the writer using it.

**Interfaces:**
- Consumes: the exact grammar implemented in Tasks 1, 3, 4. Every example here **must** parse; the four-pattern sentence in both files is now wrong and must be updated to seven.

- [ ] **Step 1: Update the grammar reference**

In `references/quiz-format.md`, add after the `path-trace` description and **replace**
the sentence "Four patterns exist: `state-machine`, `state-toggle`, `array-ops`,
`path-trace` — no others." with the seven-pattern equivalent:

````markdown
`pipeline` visualizes an input flowing through named stages, each transforming it:

```animate
pattern: pipeline
stages:
  - Raw image: single RGB frame, no depth information
  - Encoder: compresses the frame into a feature map
  - Decoder: expands features back to per-pixel values
  - Depth map: one distance estimate per pixel
```

`stages:` needs 2–6 entries, each written `<name>: <what changes>`. Both halves are
required — a stage with no transformation described is a static flowchart, not a
sequence.

`layer-stack` visualizes abstraction tiers building up, or a signal passing down:

```animate
pattern: layer-stack
direction: up
layers:
  - Pixels: raw sensor values
  - Edges: local intensity changes
  - Objects: assembled shapes
```

`layers:` needs 2–6 entries listed **bottom-up**. `direction:` is optional
(`up` or `down`, default `up`) and reverses only the reveal order, not the drawing.

`transform` visualizes one entity becoming another through labeled steps:

```animate
pattern: transform
from: Disparity map
to: Metric depth map
steps:
  - Invert each disparity value
  - Scale by the focal-length/baseline constant
```

`from:` and `to:` are both required; `steps:` needs 1–4 entries. Use this instead of
`state-toggle` when the change has intermediate steps worth naming.

Seven patterns exist: `state-machine`, `state-toggle`, `array-ops`, `path-trace`,
`pipeline`, `layer-stack`, `transform` — no others. This is a deliberately bounded
set, not a general animation authoring tool.
````

- [ ] **Step 2: Update the writer's selection guidance**

In `references/agents/course-writer.md`, extend the "prefer `animate` when the topic is"
list (`:137-152`) with the three new shapes:

```markdown
- An input flowing through named stages that each change it (`pipeline`) — a
  processing chain, an encode/decode path, a request being progressively enriched.
  This is the most common sequence shape; reach for it before `state-machine`
  when each step *transforms* something rather than merely moving between states.
- Abstraction tiers that build on each other (`layer-stack`) — a protocol stack,
  levels of representation, a hierarchy of features.
- One entity becoming another through named intermediate steps (`transform`) —
  a conversion, a normalization, a change of units or representation. Use it
  instead of `state-toggle` whenever the middles are worth naming.
```

Then add the coverage requirement to that section:

```markdown
**At least 25% of the topics that need a visual must use an `animate` block.**
The build fails below that floor and tells you which diagrams to convert. The
usual cause of falling short is drawing a sequence as a `flowchart`: if your
mermaid diagram is a straight line of boxes with no branching, it is a
`pipeline` or a `state-machine`, and it belongs in an `animate` block. Aim
higher than 25% where the material genuinely is sequential — the floor is a
minimum, not a target.
```

- [ ] **Step 3: Verify every documented example parses**

Run:

```bash
python -c "
from scripts.p2c.mdrender import parse_animate
parse_animate('''pattern: pipeline
stages:
  - Raw image: single RGB frame, no depth information
  - Encoder: compresses the frame into a feature map
  - Decoder: expands features back to per-pixel values
  - Depth map: one distance estimate per pixel''')
parse_animate('''pattern: layer-stack
direction: up
layers:
  - Pixels: raw sensor values
  - Edges: local intensity changes
  - Objects: assembled shapes''')
parse_animate('''pattern: transform
from: Disparity map
to: Metric depth map
steps:
  - Invert each disparity value
  - Scale by the focal-length/baseline constant''')
print('all documented examples parse')
"
```

Expected: `all documented examples parse`.

- [ ] **Step 4: Run the full suite**

Run: `python -m pytest tests/ -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add references/quiz-format.md references/agents/course-writer.md
git commit -m "docs: document the three new animate patterns and the 25% floor"
```

---

### Task 10: End-to-end verification on a real course

**Files:**
- Test: `tests/test_build.py`

**Interfaces:**
- Consumes: everything from Tasks 1–9.

**Why:** Tasks 1–9 are unit-tested in isolation. This confirms a full markdown document containing all three new patterns builds, validates, and renders — and that a course under the floor actually fails the build.

- [ ] **Step 1: Write the failing end-to-end tests**

```python
def test_course_with_new_patterns_builds_and_validates():
    md = (
        "# Course\n\n## Module\n\n"
        "### Topic A\n\n<!-- topic: topic-a -->\n\n"
        "```animate\npattern: pipeline\nstages:\n"
        "  - Raw: unprocessed input\n  - Done: processed output\n```\n\n"
        "### Topic B\n\n<!-- topic: topic-b -->\n\n"
        "```animate\npattern: layer-stack\nlayers:\n"
        "  - Base: raw values\n  - Top: assembled shapes\n```\n\n"
        "### Topic C\n\n<!-- topic: topic-c -->\n\n"
        "```animate\npattern: transform\nfrom: A form\nto: B form\n"
        "steps:\n  - Convert it\n```\n\n"
        "### Topic D\n\n<!-- topic: topic-d -->\n\n"
        "<!-- no-visual: administrative topic -->\n\nProse.\n"
    )
    rendered = render_markdown(md)
    assert rendered.errors == []
    assert rendered.uses_animate is True
    # 3 of 3 owing topics animate; topic-d is justified and out of the denominator.
    assert rendered.animations_per_topic["topic-a"] == 1
    for pattern_class in ("anim--pipeline", "anim--layer-stack", "anim--transform"):
        assert pattern_class in rendered.html_body


def test_course_of_linear_flowcharts_fails_the_animation_floor():
    topics = "".join(
        f"### Topic {i}\n\n<!-- topic: topic-{i} -->\n\n"
        "```mermaid\nflowchart LR\n  A --> B\n  B --> C\n```\n\n"
        for i in range(4)
    )
    rendered = render_markdown("# Course\n\n## Module\n\n" + topics)
    findings = validate_rendered(rendered)
    floor = [f for f in findings if f.code == "animation_floor"]
    assert len(floor) == 1
    assert floor[0].blocking is True
    # Every topic is a conversion candidate: all four are linear chains.
    assert "topic-0" in floor[0].message
```

Match the actual import names and helper signatures used elsewhere in
`tests/test_build.py` (`render_markdown`, and whatever the module's validation entry
point is called) rather than inventing new ones.

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_build.py -k "new_patterns or animation_floor" -q`
Expected: FAIL if any wiring is incomplete; PASS only once Tasks 1–9 are all landed.

- [ ] **Step 3: Fix any integration gaps**

No new production code should be required. If a test fails, the cause is a wiring gap
in Tasks 1–9 (a missing dispatch line, a constructor argument not passed through, a
validation entry point not calling `animation_floor_findings`). Fix at the source task's
file rather than adding compensating code here.

- [ ] **Step 4: Run the full suite**

Run: `python -m pytest tests/ -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add tests/test_build.py
git commit -m "test: end-to-end coverage for the new patterns and the floor"
```

---

## Self-Review

**1. Spec coverage**

| Spec requirement | Task |
|---|---|
| `pipeline` pattern (2–6 stages, `name: change`) | 1, 2 |
| `layer-stack` pattern (2–6 layers, `direction`) | 3 |
| `transform` pattern (`from`/`to`, 1–4 steps) | 4 |
| Stroke drawing via `stroke-dashoffset`, lengths computed in Python | 2, 4 |
| Staggered entry / one-accent-at-a-time focal discipline | 2, 3, 4 |
| Layout constants divisible by 4 | 2, 3, 4 (asserted) |
| `dir="ltr"` on every new SVG root | 2, 3, 4 (asserted) |
| Reduced-motion + print show every stage at once | 8 |
| anime.js gotcha 1 (base position in plain attributes) | 2, 3, 4 (no `transform=` emitted) |
| anime.js gotcha 2 (reset before loop) | 2, 3, 4 (asserted) |
| Per-topic animate tally | 5 |
| Linear-chain mermaid detector | 6 |
| 25% floor, blocking, routed to writer | 7 |
| Denominator = topics owing a visual; rounds up; skipped at 0 | 7 (asserted) |
| Finding names conversion candidates | 7 (asserted) |
| Author docs for all three patterns | 9 |
| Existing four patterns untouched | full-suite run in every task |

No gaps.

**2. Placeholder scan**

No "TBD", "TODO", "implement later", "add appropriate error handling", or "similar to
Task N". Every code step carries real code. Three steps deliberately defer to existing
project conventions rather than inventing them (the topic-marker syntax in Task 5, the
assets-dir constant in Task 8, the golden regeneration command in Task 8); each says so
explicitly and names what to match, which is a fact about the repo the implementer must
read, not an unspecified decision.

**3. Type consistency**

- `Animate.stages: list[tuple[str, str]]` — produced in Task 1, consumed in Task 2. ✓
- `Animate.layers` / `.direction` — Task 3 only. ✓
- `Animate.from_entity` / `.to_entity` / `.steps` — Task 4 only; named `from_entity`
  because `from` is a reserved word. ✓
- `_STAGE` regex — defined Task 1, reused Task 3. ✓
- `_ANIMATE_KEY` widened once in Task 3 for `direction`/`from`/`to`, flagged there as
  serving Task 4 so it is not edited twice. ✓
- `is_linear_mermaid(body: str) -> bool` — defined and consumed in Task 6, used by
  Task 7 via `Rendered.linear_mermaid_topics`. ✓
- `animations_per_topic: dict[str, int]` — Task 5 → Task 7. ✓
- `animation_floor_findings(rendered, justified_topics: set[str]) -> list[Finding]` —
  Task 7, signature identical in tests and implementation. ✓
- CSS custom properties emitted in Tasks 2–4 (`--anim-pipe-*`, `--anim-layer-*`,
  `--anim-xform-*`) match exactly the tokens defined in Task 8. ✓
- Class names emitted in Tasks 2–4 match the selectors in Task 8 and the assertions in
  Task 10. ✓

One consistency risk worth stating: Task 3 widens `_ANIMATE_KEY` to include `from|to`,
which changes how a `from:` line inside *any* pattern is handled — previously it fell
through to `caption`. No existing pattern documents a `from:` key, and `path-trace`'s
caption tests in the full suite guard the regression.
