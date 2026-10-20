# Test results

## Unit tests

`python -m unittest discover -s tests -v` runs 19 tests on small synthetic skill sets (no network, no real skills needed). They cover:

| Area | What is checked |
|---|---|
| Discovery | all skills found, nested copies ignored, duplicate names reported, folded YAML descriptions parsed |
| Grouping | related skills form routers, unrelated skills are never forced together, file-linked skills stay together, `standalone` respected, works without `networkx` |
| Output | valid name/description in every SKILL.md, every member listed and bundled, ZIP layout, config anchors and extra triggers, long descriptions trimmed, description overrides, token report |
| Updates | a new skill joins the right router without reshuffling others, only changed outputs are flagged for re-upload, removed skills are reported |

Two bugs were found and fixed by these tests: small clusters being split into fragments that were too small to become routers, and router descriptions changing between identical runs.

## Benchmark on a real collection

A collection of 78 public skills: a marketing pack, an agent-systems pack, a design pack and a few single skills.

**Context cost**

| | Before (78 skills) | After (5 skills) |
|---|---|---|
| Skill text loaded in every conversation | ~14,700 tokens | ~950 tokens (-94%) |
| Conversation that uses the marketing router | ~14,700 | ~4,900 |
| Conversation that uses the agent-systems router | ~14,700 | ~2,700 |

Token counts are estimated from character counts. The host's own plugin report gave ~13,300 always-on tokens for the same packs before routing, so the estimate is in the right range.

**Routing accuracy**

70 requests in two languages across marketing, design and agent-system tasks, plus requests that should not trigger any skill. The same model picked a skill from the flat list of 78 and, separately, from the 5 routers (top level first, then the router map).

| | Flat list | Routers |
|---|---|---|
| Correct skill | 69 / 70 | 70 / 70 |
| Skill triggered when none should | 0 | 0 |

**Generality**

| Scenario | Result |
|---|---|
| 3 new skills added to an existing build | existing layout unchanged; the related one joined the matching router, unrelated ones stayed standalone |
| A different collection of 19 unrelated skills | nothing grouped (correct: no shared topic) |
| Both collections together (97 skills) | 24 top-level skills, -79% always-loaded text |
