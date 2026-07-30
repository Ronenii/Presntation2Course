# Reviewer regression fixture

A course with two defects that every mechanical validation accepts:

1. **Undefined jargon** — the prose uses *MESI* and *write-invalidate*. Neither is in the
   outline's `jargon` list, so the build's "every jargon term has a glossary entry" check
   passes, and neither is ever explained.
2. **A quiz needing outside knowledge** — the question asks how many states MESI defines.
   The grammar is valid and the marked answer is correct, but the course never says four.

`expected-findings.json` is the grading key. To run the regression:

```bash
.venv/bin/python scripts/build --outline tests/broken-course/outline.json \
  --modules tests/broken-course/modules --out /tmp/p2c-broken --assets assets
```

Then dispatch the novice-simulator (`references/agents/novice-simulator.md`) against
`/tmp/p2c-broken/course.html` only — not this directory, not the outline — and grade its
output file:

```bash
PYTHONPATH=scripts .venv/bin/python -c "
import json, sys
from p2c.review import load_review, missed_expected
missed = missed_expected(load_review(sys.argv[1]),
                         json.load(open('tests/broken-course/expected-findings.json')))
print('\n'.join(missed) or 'reviewer caught both defects')
sys.exit(1 if missed else 0)
" /tmp/p2c-broken/.p2c/review/pass-1.json
```

A miss means the reviewer prompt has regressed. Fix the prompt, not the fixture.
