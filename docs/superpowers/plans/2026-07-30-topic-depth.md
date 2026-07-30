# Topic Depth (brief vs. full topics) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stop shallow, administrative slides (course goals, agendas, "about this course") from being forced through the full analogy → visual → quiz rhythm, and add a token-cost disclaimer to the README.

**Architecture:** Add an optional `depth: "full" | "brief"` field to each topic in `outline.json` (default `"full"` when absent, so existing outlines and golden fixtures keep validating). The summarizer sets it. The course-writer renders `brief` topics as short plain prose only, closing with a new `<!-- no-quiz: ... -->` justification comment (mirroring the existing `<!-- no-visual: ... -->` escape hatch) instead of an analogy/visual/quiz. The build's `topic_without_quiz` check honors that comment exactly the way `topic_without_visual` already honors `no-visual` — no new build-level concept of "depth" is needed, keeping the build agnostic to why a topic skipped its quiz.

**Tech Stack:** Python (build/validation scripts, pytest), Markdown skill docs (SKILL.md, references/*.md, README.md).

## Global Constraints

- `depth` is optional on every topic object; absence means `"full"` (backward compatible with every existing outline, golden fixture, and test).
- Only two values are valid: `"full"` and `"brief"`. Anything else is an outline validation error.
- A `brief` topic still gets a `<!-- topic: id -->` marker and one `###` heading — it must still satisfy topic-coverage (`topic_missing`) checks exactly like a full topic.
- A `brief` topic must not have an `analogy` or a visual block; it uses `<!-- no-quiz: ... -->` in place of a quiz. `full` topics are completely unchanged — same rhythm, same requirements as today.
- The new `no-quiz` marker follows the exact regex/behavior shape of the existing `_NO_VISUAL` marker in `scripts/p2c/mdrender.py`.
- Do not touch `subject_domain`, `reusable_image`, or any other existing outline field's behavior.

---

### Task 1: Outline schema + validator accept `depth`

**Files:**
- Modify: `references/outline-schema.json`
- Modify: `scripts/p2c/outline.py`
- Test: `tests/test_outline.py`

**Interfaces:**
- Produces: topic objects may now carry `"depth": "full" | "brief"`, validated by `validate_outline()`. No new public function — this extends the existing per-topic checks around `scripts/p2c/outline.py:134-140` (the `reusable_image` block), which is the closest existing analog (optional field, own regex/enum check, own error message).

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_outline.py` (follow the existing style around `test_reusable_image_is_optional` / `test_reusable_image_rejects_a_malformed_ref`, using whatever base outline dict fixture that file already uses for a single valid topic):

```python
def test_depth_is_optional():
    outline = _valid_outline()
    # no depth key on any topic
    assert validate_outline(outline) == []


def test_depth_accepts_full_and_brief():
    for value in ("full", "brief"):
        outline = _valid_outline()
        outline["modules"][0]["topics"][0]["depth"] = value
        assert validate_outline(outline) == []


def test_depth_rejects_an_unknown_value():
    outline = _valid_outline()
    outline["modules"][0]["topics"][0]["depth"] = "medium"
    problems = validate_outline(outline)
    assert any("depth" in p for p in problems)
```

If `tests/test_outline.py` does not already have a `_valid_outline()` helper, use whatever helper/fixture the file uses to build a single-topic valid outline dict (check the top of the file for the pattern used by `test_a_well_formed_outline_validates`) and adapt the three tests above to call it instead.

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /home/roneng/Presntation2Course && .venv/bin/pytest tests/test_outline.py -k depth -v`
Expected: FAIL — `depth` accepted today with no validation means the "unknown value" test fails (no problem reported), and the two acceptance tests may pass already by accident since nothing currently rejects unknown keys. Confirm the rejection test is the one that fails.

- [ ] **Step 3: Implement**

In `scripts/p2c/outline.py`, add near the top:

```python
TOPIC_DEPTHS = ("full", "brief")
```

In `validate_outline`, inside the topic loop (right after the `reusable_image` block, i.e. after line 140's closing of that `if`), add:

```python
            if "depth" in topic and topic["depth"] not in TOPIC_DEPTHS:
                problems.append(
                    f"{twhere}.depth must be one of {list(TOPIC_DEPTHS)}, "
                    f"got {topic['depth']!r}"
                )
```

In `references/outline-schema.json`, add `"depth"` to the topic's `properties` (it is optional, so do NOT add it to the topic's `required` array):

```json
        "depth": {
          "enum": ["full", "brief"],
          "default": "full",
          "description": "Optional. 'brief' marks a topic as purely administrative/navigational (course goals, agenda, roadmap) with no mechanism or claim to teach or check -- the writer renders plain prose only, with no analogy, visual, or quiz. Defaults to 'full' when absent."
        }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /home/roneng/Presntation2Course && .venv/bin/pytest tests/test_outline.py -v`
Expected: PASS, including `test_published_schema_matches_the_validator` (check that test's logic — it compares `REQUIRED_TOPIC`/`REQUIRED_MODULE` against the schema's `required` arrays, so an optional field like `depth` must NOT be added to `REQUIRED_TOPIC` in `outline.py` or that test will fail on a mismatch).

- [ ] **Step 5: Commit**

```bash
git add references/outline-schema.json scripts/p2c/outline.py tests/test_outline.py
git commit -m "feat: add optional depth field to outline topics"
```

---

### Task 2: `no-quiz` justification comment in mdrender + validate

**Files:**
- Modify: `scripts/p2c/mdrender.py`
- Modify: `scripts/p2c/validate.py`
- Test: `tests/test_mdrender.py`
- Test: `tests/test_validate.py`

**Interfaces:**
- Consumes: nothing new from Task 1 (mdrender/validate operate on rendered markdown text and the outline dict; they don't need to read `depth` directly — see Global Constraints).
- Produces: a topic containing a line matching `<!-- no-quiz: <reason> -->` (anywhere in its body) is excluded from `topics_missing_quiz`-equivalent reporting, mirroring how `no-visual` already works for `topics_missing_visual`.

Currently there is no `topics_missing_quiz` list — `validate.py`'s check #5 iterates `rendered.quizzes_per_topic` directly and flags any topic with `count == 0`. This task adds a parallel `topic_quiz_status` tracking dict (mirroring `topic_visual_status`) so a `no-quiz`-justified topic with zero quizzes does not get flagged, without changing behavior for every other topic (zero quizzes and no justification is still `topic_without_quiz`; a quiz block always still counts, matching how a real visual always overrides `no-visual` in `_note_visual`).

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_mdrender.py`, next to the existing `no-visual` tests (near line 502):

```python
def test_a_no_quiz_comment_justifies_a_topic_with_zero_quizzes():
    md = course(
        '<!-- topic: goals -->\n### Course Goals\n\n'
        'This course covers the TLB and thrashing.\n\n'
        '<!-- no-quiz: brief administrative topic, nothing to check -->\n'
    )
    rendered = render_course(md)
    assert rendered.quizzes_per_topic["goals"] == 0
    assert "goals" not in rendered.topics_missing_quiz


def test_a_topic_with_zero_quizzes_and_no_justification_is_still_missing():
    md = course(
        '<!-- topic: goals -->\n### Course Goals\n\nJust prose, no quiz, no comment.\n'
    )
    rendered = render_course(md)
    assert "goals" in rendered.topics_missing_quiz


def test_a_real_quiz_is_never_downgraded_by_a_stray_no_quiz_comment():
    md = course(
        '<!-- topic: goals -->\n### Course Goals\n\n'
        '<!-- no-quiz: irrelevant leftover comment -->\n\n'
        '```quiz\nq: q\n- [ ] a\n- [x] b\n- [ ] c\nwhy: because\n```\n'
    )
    rendered = render_course(md)
    assert rendered.quizzes_per_topic["goals"] == 1
    assert "goals" not in rendered.topics_missing_quiz
```

Add to `tests/test_validate.py`, next to `test_a_topic_with_no_quiz_is_blocking_and_names_the_topic`:

```python
def test_a_no_quiz_comment_suppresses_topic_without_quiz():
    body = "Plain prose only.\n\n<!-- no-quiz: brief administrative topic, nothing to check -->"
    findings = check(course(tlb_body=body))
    assert "topic_without_quiz" not in codes(findings)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /home/roneng/Presntation2Course && .venv/bin/pytest tests/test_mdrender.py tests/test_validate.py -k no_quiz -v`
Expected: FAIL with `AttributeError: 'Rendered' object has no attribute 'topics_missing_quiz'` (or similar) for the mdrender tests, and the validate test failing because `topic_without_quiz` still fires.

- [ ] **Step 3: Implement**

In `scripts/p2c/mdrender.py`:

1. Add a new regex next to `_NO_VISUAL` (around line 186):

```python
_NO_QUIZ = re.compile(r"^\s*<!--\s*no-quiz:\s*.+-->\s*$")
```

2. In the line-walk loop where `_NO_VISUAL` is checked (around the block containing `elif current[1]:` / `if "<svg" in line:` / `elif _NO_VISUAL.match(line):`), add a sibling branch that records quiz-justification per topic in a new dict. Introduce `topic_quiz_status: dict[str, str] = {}` alongside the existing `topic_visual_status = {}` declaration (find it above the line-walk loop), and add:

```python
        elif _NO_QUIZ.match(line):
            topic_quiz_status[current[1]] = "justified"
```

   as an additional `elif` branch in that same chain (after the `_NO_VISUAL` check), still inside `elif current[1]:`.

3. In the fence-processing loop, where a `quiz` fence increments `quizzes_per_topic[topic_id]` (around line 427), also mark that topic's status as having a real quiz so a stray `no-quiz` comment never wins over an actual quiz:

```python
            if topic_id:
                quizzes_per_topic[topic_id] = quizzes_per_topic.get(topic_id, 0) + 1
                topic_quiz_status[topic_id] = "has_quiz"
```

4. After the existing `quizzes_per_topic.setdefault(topic_id, 0)` loop (around line 466) and before/alongside `topics_missing_visual` (around line 469), add:

```python
    topics_missing_quiz = [
        tid for tid in dict.fromkeys(s.topic_id for s in sections if s.topic_id)
        if quizzes_per_topic.get(tid, 0) == 0 and topic_quiz_status.get(tid) != "justified"
    ]
```

5. Add `topics_missing_quiz: list[str] = field(default_factory=list)` to the `Rendered` dataclass, next to `topics_missing_visual`, and pass `topics_missing_quiz=topics_missing_quiz` in the `Rendered(...)` construction at the end of `render_course`, next to `topics_missing_visual=topics_missing_visual`.

In `scripts/p2c/validate.py`, replace check #5 (the loop over `rendered.quizzes_per_topic` around line 167-174) to use the new list instead of a raw zero-count scan, matching the shape of check #5b right below it:

```python
    # 5: every present topic has a quiz, or an explicit non-quizzable justification.
    for topic_id in rendered.topics_missing_quiz:
        findings.append(
            _finding(
                "topic_without_quiz",
                f"topic {topic_id!r} has no valid quiz and no "
                "<!-- no-quiz: ... --> justification",
                topic=topic_id,
                module=modules.get(anchor_of_topic.get(topic_id, "")),
            )
        )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /home/roneng/Presntation2Course && .venv/bin/pytest tests/test_mdrender.py tests/test_validate.py -v`
Expected: PASS, including all pre-existing tests (`test_a_topic_with_no_quiz_is_recorded_as_zero`, `test_a_malformed_quiz_becomes_an_error_and_is_dropped`, `test_a_malformed_quiz_is_blocking_and_routes_to_the_writer`, `test_a_topic_with_no_quiz_is_blocking_and_names_the_topic` — none of these use `no-quiz`, so they must still see the same zero-count / blocking behavior as before).

- [ ] **Step 5: Run the full test suite**

Run: `cd /home/roneng/Presntation2Course && .venv/bin/pytest -x`
Expected: PASS. This confirms nothing in `test_broken_course.py`, `test_invariants.py`, or the golden `test_build.py` snapshot broke (none of them use `no-quiz`, so `topics_missing_quiz` should reproduce identical results to the old inline zero-count check for every existing fixture).

- [ ] **Step 6: Commit**

```bash
git add scripts/p2c/mdrender.py scripts/p2c/validate.py tests/test_mdrender.py tests/test_validate.py
git commit -m "feat: honor a no-quiz justification comment like no-visual"
```

---

### Task 3: Summarizer criteria for `depth: "brief"`

**Files:**
- Modify: `references/agents/summarizer.md`

**Interfaces:**
- Consumes: nothing (doc-only task).
- Produces: summarizer now writes `"depth": "brief"` on qualifying topics. Read by Task 4's course-writer instructions and by whatever passes the topic object through in Phase 3 of `SKILL.md` (already verbatim — no orchestrator change needed, since `SKILL.md`'s Phase 3 already says "its module object from outline.json... its topics in order" and topic objects are passed through unmodified).

- [ ] **Step 1: Edit `references/agents/summarizer.md`**

In the `## Output` section's example JSON block, add `"depth": "full"` to the example topic object (to make the field visible in the shape summarizers copy from), right after `"id": "tlb"`:

```json
    "topics": [{
      "id": "tlb",
      "title": "What a TLB caches",
      "depth": "full",
      "slide_refs": ["week1.pdf#12"],
```

In the `## Rules` section, add a new bullet immediately after the `reusable_image` bullet (which is the closest existing analog — an optional per-topic field the summarizer alone decides):

```markdown
- **`depth`** (optional; defaults to `"full"`): set to `"brief"` when a topic is purely
  administrative or navigational — a course-goals slide, an agenda, a "who this course is
  for" slide, a roadmap of what's coming — and has no mechanism, concept, or claim for a
  student to actually learn or be checked on. Everything else is `"full"`, including any
  topic with real content, however short. When in doubt, use `"full"`: this field exists
  to skip content that would make the analogy/quiz/visual rhythm look absurd (a quiz
  asking "what is the nature of this course?"), not to skip topics that are merely brief.
  A `brief` topic still gets its own `id`, `title`, and `<!-- topic: id -->` marker in the
  course — it is never dropped or folded into another topic.
```

- [ ] **Step 2: No automated test — this is agent-instruction prose.** Verify by re-reading the new bullet against the worked example ("course goals" slide) and confirming it would classify that as `brief` and a topic like "What a TLB caches" as `full`.

- [ ] **Step 3: Commit**

```bash
git add references/agents/summarizer.md
git commit -m "docs: teach the summarizer to mark administrative topics as brief"
```

---

### Task 4: Course-writer + style-guide rendering rules for `brief` topics

**Files:**
- Modify: `references/agents/course-writer.md`
- Modify: `references/style-guide.md`
- Modify: `SKILL.md`

**Interfaces:**
- Consumes: `topic.depth` from the outline (Task 1), the `<!-- no-quiz: ... -->` marker honored by the build (Task 2).
- Produces: course-writer output for `brief` topics — a topic section with only a heading and 1-2 short paragraphs of prose, a `<!-- no-quiz: ... -->` comment, and nothing else (no `analogy`, no visual block, no `quiz`).

- [ ] **Step 1: Edit `references/style-guide.md`**

Add a new section right after "## The topic rhythm — fixed, in this order" (before "## Tone"):

```markdown
## Brief topics — the exception to the rhythm

A topic marked `"depth": "brief"` in the outline skips the rhythm above entirely. Write
1–2 short plain-language paragraphs and stop: no `analogy` block, no visual, no worked
example, no `quiz`. Close the topic with **both** `<!-- no-quiz: brief administrative
topic -->` and `<!-- no-visual: brief administrative topic -->` (or a more specific
reason) instead of a quiz block or a diagram — those comments are what tell the build
this topic was deliberately left unchecked and undiagrammed, not that a quiz or a visual
was forgotten. The build has no awareness of `depth` itself; it only ever recognizes
these two justification comments, so both are required even though the topic is `brief`.

This is not a shortcut for content that is merely short — a two-sentence topic with a
real mechanism to check still gets the full rhythm, just briefly. `brief` is only for
topics the outline flagged as having nothing to teach or check in the first place (course
goals, an agenda, a roadmap slide).
```

**Correction (found during Task 7's execution):** the text below originally claimed a
`brief` topic needs *neither* a visual *nor* a `no-visual` comment. That was wrong — the
build's visual-coverage check (`topic_without_visual` in `scripts/p2c/validate.py`,
backed by `scripts/p2c/mdrender.py`) has no `depth`-awareness at all and is unconditional,
exactly like the quiz check before Task 2 added `no-quiz`. A brief topic that omits
`no-visual` fails the build. The corrected requirement — a `brief` topic needs **both**
`no-quiz` and `no-visual` — is reflected in the corrected section above and in the Step 2
edits below; if you are implementing this plan fresh (rather than fixing an
already-applied Task 4), use the corrected wording only and disregard this note.

- [ ] **Step 2: Edit `references/agents/course-writer.md`**

In the `## Input` section's bullet list, add after the `prerequisites, topics` bullet:

```markdown
- Each topic's `depth` (`"full"` or absent means the full rhythm below; `"brief"` means
  the exception in `references/style-guide.md`'s "Brief topics" section — plain prose
  only, no analogy, no visual, no quiz).
```

In the `## Output` section's example markdown block, add a second worked example showing a `brief` topic, right after the existing `tlb`/`thrashing` example and before the `glossary` block at the end:

````markdown
<!-- topic: course-goals -->
### Course Goals

This course walks you through virtual memory from first principles: how addresses get
translated, why caching translations matters, and what happens when memory pressure
forces the system to choose what to evict.

<!-- no-quiz: brief administrative topic, nothing to check -->
<!-- no-visual: brief administrative topic, nothing to check -->
````

Update the "Mechanical requirements" bullet that currently reads "**Every topic ends with at least one `quiz` block**...":

```markdown
- **Every `full`-depth topic ends with at least one `quiz` block**, 3–4 options, exactly
  one `[x]`, a non-empty `why:`, and nothing else inside the block. A `brief`-depth topic
  ends with `<!-- no-quiz: ... -->` instead — never both, never neither.
```

Update the "## Visual per topic" section's opening line to scope it to full-depth topics:

```markdown
Every `full`-depth topic needs one of: a `mermaid` diagram, an inline `<svg>`, a `figure`
block, or an `animate` block. The build fails otherwise, unless you also write an
explicit `<!-- no-visual: <reason> -->` HTML comment for a topic that is genuinely
non-spatial — use that sparingly; it is an escape hatch, not a way to skip the visual
step because a diagram is inconvenient to write. A `brief`-depth topic also has no visual
step, but the build's visual check is not `depth`-aware — it only ever recognizes the
`no-visual` comment itself — so a `brief` topic must still write
`<!-- no-visual: <reason> -->` alongside its `<!-- no-quiz: ... -->`, even though it has
nothing to draw.
```

- [ ] **Step 3: Edit `SKILL.md`**

In Phase 3's dispatch bullet list (the one already noting `reusable_image` flows through automatically), add a matching note since `depth` is the same kind of "verbatim topic field the writer must be told about explicitly":

```markdown
- each topic's `depth` also flows through automatically since topic objects are passed
  verbatim, but — same as `reusable_image` — the writer must be told what it means via
  the dispatch text (see `references/agents/course-writer.md` and
  `references/style-guide.md`'s "Brief topics" section), not left to infer it from the
  bare string.
```

- [ ] **Step 4: No automated test — agent-instruction prose.** Verify by checking that a course-writer given `{"id": "course-goals", "depth": "brief", ...}` and these instructions would produce output matching the worked example in Step 2, and that a topic with `depth` absent or `"full"` is completely unaffected (re-read the unmodified rhythm section to confirm nothing there was weakened).

- [ ] **Step 5: Commit**

```bash
git add references/agents/course-writer.md references/style-guide.md SKILL.md
git commit -m "docs: teach the course-writer to render brief topics as plain prose"
```

---

### Task 5: Rubric note for brief topics, and closing the novice-simulator blind spot

**Files:**
- Modify: `references/rubric.md`
- Modify: `references/agents/novice-simulator.md`

**Interfaces:**
- Consumes: nothing new.
- Produces: reviewer guidance so neither reviewer flags a `brief` topic's missing analogy/visual/quiz as a defect.

Reviewers currently see only the rendered `course.html` (novice-simulator) or the html plus outline/decks (rubric-auditor) — neither sees raw `depth` values directly as a labeled field, but the rubric-auditor does see `outline.json`, so it can cross-reference. Add a note so it does not mistake an intentional `brief` topic for a defect.

**The novice-simulator has no `outline.json` at all — by design (see `references/agents/novice-simulator.md`'s "Input — and nothing else" section) — and `<!-- no-quiz: ... -->`/`<!-- no-visual: ... -->` are HTML comments, invisible in the rendered `course.html` it reads.** Its current instruction, "Check that every topic ends with at least one check," has no exception, so without a fix it files a false-positive finding against every `brief` topic on every run — this was caught by Task 4's task-review, which flagged the unqualified "every topic" language in this file as a real (if out-of-scope-for-Task-4) gap. Fix chosen: add judgment-based guidance to the novice-simulator's own instructions (not a rendering change) — it already exercises judgment for `analogy_misleading` vs. `style`, so recognizing "this is clearly a short administrative note, not a broken topic" is the same kind of call, not a new capability.

- [ ] **Step 1: Edit `references/agents/novice-simulator.md`**

Replace the check-4 bullet in the `## What you do` numbered list:

```markdown
4. Check that every topic ends with at least one check, and that no diagram is empty or
   broken.
```

with:

```markdown
4. Check that every topic ends with at least one check, and that no diagram is empty or
   broken — **unless the topic is clearly a short administrative or navigational note**
   (a course-goals slide, an agenda, a "what's ahead" roadmap) with nothing in it to
   actually be quizzed on. A topic with any real mechanism, concept, or claim still needs
   its check, however short the topic is; don't extend this exception to a topic just
   because you personally found it easy.
```

- [ ] **Step 2: No automated test — agent-instruction prose.** Verify by re-reading the full `## What you do` list to confirm this exception reads consistently with check 2's "decisive instruction" framing (i.e., it doesn't weaken the outside-knowledge quiz check, only the topic-ends-without-any-check-at-all default).

- [ ] **Step 3: Edit `references/rubric.md`**

Add a note under "## Blocking findings", right after the table, before "## Noted findings":

```markdown
A topic whose outline entry has `"depth": "brief"` is exempt from `topic_without_quiz`,
`analogy_misleading` (it has no analogy to begin with), and the visual-related findings —
its `<!-- no-quiz: ... -->` comment and absence of an analogy/visual are intentional, not
defects. Still apply every other check normally: a `brief` topic must still exist in the
course (`topic_missing`), and any prose it does contain must not assert something
unsupported (`unsupported_claim`) or leave a jargon term undefined
(`jargon_undefined`).
```

- [ ] **Step 4: No automated test — agent-instruction prose.** Verify by re-reading `rubric-auditor.md` to confirm it is given `outline.json` (already true — no change needed there) so it can actually check a topic's `depth` before applying this exemption.

- [ ] **Step 5: Commit**

```bash
git add references/rubric.md references/agents/novice-simulator.md
git commit -m "docs: exempt brief topics from analogy/quiz/visual findings in review"
```

---

### Task 6: README token-cost disclaimer and a Quick Start section

**Files:**
- Modify: `README.md`

**Interfaces:**
- Consumes: nothing.
- Produces: a visible warning in the README about token cost and a recommendation to use an auto-accept mode, plus a new "Quick Start" section for someone installing from a downloaded release tarball rather than a git checkout.

- [ ] **Step 1: Edit `README.md`— token-cost callout**

Add a new callout right after the "## Usage" section's code block (after line 39, before the "**The target language is required...**" paragraph):

```markdown
> **Token cost.** A single run dispatches one agent per topic (research), one agent per
> module (writing), plus two review agents for up to three passes — a modest deck can
> mean dozens of agent calls. Running with an auto-accept/auto mode (so the run isn't
> paused for approval at every one of those dispatches and every script step) is strongly
> recommended; otherwise expect frequent permission prompts throughout a single course
> generation.
```

- [ ] **Step 2: Add a new "## Quick Start" section**

This is for someone who downloaded a release archive (e.g. from GitHub Releases — see Task 8) rather than cloning the repo, and just wants to run the skill without reading the rest of the README. Add it right after "## Requirements" (i.e. after the requirements table, before "## How it works"), so a reader hits the requirements immediately before the steps that depend on them:

```markdown
## Quick Start

For running this from a downloaded release rather than a git checkout:

1. **Install Claude Code** (see [claude.com/claude-code](https://claude.com/claude-code)) and confirm the requirements above (`python3` with the packages in `requirements.txt`; `soffice` only if you have PPTX input) are installed.
2. Create a project directory, then inside it create `.claude/skills/presentation2course/` and extract the release archive's contents into that folder.
3. Copy your lecture deck (PDF or PPTX) into the project directory alongside `.claude/`.
4. Start Claude Code in that project directory and ask it to turn your deck into a course, stating the target language, e.g.:
   ```
   Turn ./week3.pdf into a course, language: English
   ```
5. When the run finishes, open the generated `<stem>-course/course.html` — double-click it, or drag it into a browser tab. It is fully self-contained; no server or network access is needed to view it.
```

- [ ] **Step 3: No automated test — README prose.** Verify by reading both new sections back in place: the token-cost callout sits before the requirements table and reads clearly on its own; the Quick Start section sits after Requirements and before How It Works, and its step numbering and code fences render correctly as markdown (check the nested code fence inside step 4 uses a different fence length or is otherwise unambiguous — since the outer step list is not itself inside a code fence this is fine, but double check the rendered structure).

- [ ] **Step 4: Commit**

```bash
git add README.md
git commit -m "docs: add token-cost warning and a release-based Quick Start to the README"
```

---

### Task 7: End-to-end fixture check with a brief topic

**Files:**
- Modify: `tests/fixtures/` (whichever golden/course fixture is used by `test_build.py`'s golden snapshot — inspect `tests/test_build.py` and `tests/golden/` first to find the existing pattern used when e.g. `figure`/`animate` blocks were added, per the recent commit `f98bd91 test: add figure and animate blocks to both golden course fixtures`)
- Test: `tests/test_build.py`

**Interfaces:**
- Consumes: Tasks 1 and 2 (outline `depth` field, `no-quiz` marker) must both be complete and merged before this task, since it exercises the full outline→build path together.

- [ ] **Step 1: Inspect the existing golden fixture pattern**

Run: `cd /home/roneng/Presntation2Course && git show f98bd91 --stat` and read the diff to see exactly which fixture files (course.md source + outline.json + expected course.html) were touched to add `figure`/`animate` blocks. Read `tests/test_build.py`'s golden test to confirm how it locates and compares fixtures, and whether it's the kind of snapshot regenerated via `P2C_UPDATE_GOLDEN=1` (per `README.md`'s Development section) or a hand-maintained fixture.

- [ ] **Step 2: Add one `brief` topic to the golden course fixture**

Following the exact pattern found in Step 1, add one new topic with `"depth": "brief"` to the golden outline fixture (a plausible id like `course-goals`) and matching markdown in the golden `course.md`-equivalent input fixture, containing only prose and a `<!-- no-quiz: ... -->` comment, per Task 4's worked example. Do this for whichever of the two golden fixtures (`tests/test_build.py` uses, per the recent commit touching "both golden course fixtures") are appropriate.

- [ ] **Step 3: Regenerate or hand-write the expected golden output**

If the test suite supports `P2C_UPDATE_GOLDEN=1` (confirmed in Step 1), run:

Run: `cd /home/roneng/Presntation2Course && P2C_UPDATE_GOLDEN=1 .venv/bin/pytest tests/test_build.py -k golden`

Then inspect the diff to the regenerated golden output file with `git diff` and confirm the new topic renders as expected: heading present, no analogy/visual/quiz markup, no `topic_without_quiz`/`topic_without_visual` findings triggered. If the suite has no auto-regenerate mechanism, hand-edit the expected fixture to match what `render_course` + `build` actually produce for the new input (run the build once locally to see the real output, then copy the relevant section in).

- [ ] **Step 4: Run the full test suite**

Run: `cd /home/roneng/Presntation2Course && .venv/bin/pytest -x`
Expected: PASS, including `test_invariants.py` and `test_broken_course.py` (neither should be affected by an added brief topic, but confirm — `p2c.invariants` may have its own per-topic completeness checks worth a quick read if this fails).

- [ ] **Step 5: Commit**

```bash
git add tests/
git commit -m "test: add a brief topic to the golden course fixtures"
```

---

### Task 8: GitHub Actions release workflow

**Files:**
- Create: `.github/workflows/release.yml`

**Interfaces:**
- Consumes: nothing from earlier tasks — this is an independent addition (CI/release automation), unrelated to the `depth`/brief-topic feature in Tasks 1-7. It can run before, after, or interleaved with those tasks with no ordering dependency.
- Produces: a manually-triggered GitHub Actions workflow that creates a git tag, builds a release archive containing everything needed to run the skill, and publishes a GitHub Release with that archive attached — the artifact the README's new Quick Start section (Task 6) tells users to download and extract into `.claude/skills/presentation2course/`.

This project has no existing `.github/workflows/` directory. The archive must contain exactly what a from-scratch install needs to run the skill standalone: `SKILL.md`, `references/`, `assets/`, `scripts/`, `requirements.txt` — excluding `tests/`, `docs/`, `requirements-dev.txt`, `pyproject.toml`, and any VCS metadata. Checking out a tagged commit already excludes gitignored files (`__pycache__/`, `.venv/`, `.pytest_cache/`, `.superpowers/`), so no separate cleanup step is needed for those.

- [ ] **Step 1: Write `.github/workflows/release.yml`**

```yaml
name: Release

on:
  workflow_dispatch:
    inputs:
      version:
        description: 'Release version, e.g. v1.2.0'
        required: true
        type: string

permissions:
  contents: write

jobs:
  release:
    runs-on: ubuntu-latest
    steps:
      - name: Checkout
        uses: actions/checkout@v4

      - name: Validate version format
        run: |
          if [[ ! "${{ inputs.version }}" =~ ^v[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
            echo "::error::version must look like vX.Y.Z, got '${{ inputs.version }}'"
            exit 1
          fi

      - name: Create and push tag
        run: |
          git config user.name "github-actions[bot]"
          git config user.email "github-actions[bot]@users.noreply.github.com"
          git tag -a "${{ inputs.version }}" -m "Release ${{ inputs.version }}"
          git push origin "${{ inputs.version }}"

      - name: Build release archive
        run: |
          staging="presentation2course-${{ inputs.version }}"
          mkdir "$staging"
          cp -r SKILL.md references assets scripts requirements.txt "$staging/"
          tar -czf "${staging}.tar.gz" "$staging"

      - name: Create GitHub Release
        uses: softprops/action-gh-release@v2
        with:
          tag_name: ${{ inputs.version }}
          name: ${{ inputs.version }}
          files: presentation2course-${{ inputs.version }}.tar.gz
          generate_release_notes: true
```

- [ ] **Step 2: No automated test — CI workflow file.** This cannot be exercised by pytest. Verify by reading the YAML back for syntax sanity (correct indentation, `${{ }}` expressions balanced) and, if you have `actionlint` available, run it:

Run: `actionlint .github/workflows/release.yml 2>/dev/null || echo "actionlint not installed, skipping lint"`
Expected: no errors reported, or the tool is simply unavailable (not a failure — do not install new tooling for this).

Confirm the version regex `^v[0-9]+\.[0-9]+\.[0-9]+$` matches the existing repository tag style by checking `git tag -l` — the repo already has a `v1.0.0` tag, which matches this pattern.

- [ ] **Step 3: Commit**

```bash
git add .github/workflows/release.yml
git commit -m "ci: add manual-dispatch GitHub Actions release workflow"
```

---

## Self-review notes

- **Spec coverage:** Issue 1 (no forced analogy/quiz on shallow topics) → Tasks 1, 2, 3, 4. Issue 2 (no full chapter for admin content) → resolved by the "brief" rendering itself per the brainstorming decision (no separate module-folding task was requested). Issue 3 (README token disclaimer) → Task 6. Rubric/reviewer alignment → Task 5, amended during execution to also fix a novice-simulator blind spot: it never sees `outline.json`/`depth` and `<!-- no-quiz/no-visual -->` comments are invisible in rendered HTML, so its unqualified "every topic ends with a check" instruction would have false-positived on every `brief` topic — closed with a judgment-based exception in `references/agents/novice-simulator.md` itself, found by Task 4's task-review. End-to-end proof → Task 7. Mid-execution additions from the user, unrelated to the depth/brief-topic feature: a release-based Quick Start README section → folded into Task 6. A GitHub Actions release workflow (manual dispatch, user-supplied version, tag + archive + GitHub Release) → Task 8, independent of Tasks 1-7.
- **Backward compatibility:** every existing outline (no `depth` field) validates and builds identically, since `depth` is optional and defaults to `"full"` everywhere it's read; `topics_missing_quiz` reproduces the old zero-count check exactly for any topic with no `no-quiz` comment.
- **Type/name consistency checked:** `topics_missing_quiz` (mdrender) is the name used consistently in Task 2's test additions and Task 2's `validate.py` change; `TOPIC_DEPTHS` (outline.py) matches `depth`'s two allowed values `"full"`/`"brief"` used identically in Tasks 3 and 4's doc text and Task 7's fixture.
