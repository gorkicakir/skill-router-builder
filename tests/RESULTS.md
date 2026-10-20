# Test results

## Unit tests

`python -m unittest discover -s tests -v` runs 23 tests on small synthetic skill sets (no network, no real skills needed). They cover:

| Area | What is checked |
|---|---|
| Discovery | all skills found, nested copies ignored, duplicate names reported, folded YAML descriptions parsed |
| Grouping | related skills form routers, unrelated skills are never forced together, file-linked skills stay together, `standalone` respected, works without `networkx` |
| Output | valid name/description in every SKILL.md, every member listed and bundled, ZIP layout, config anchors and extra triggers, long descriptions trimmed, description overrides, token report |
| Updates | a new skill joins the right router without reshuffling others, only changed outputs are flagged for re-upload, removed skills are reported |
| Upload limits | exactly one SKILL.md per bundle, oversized routers split under the file limit, unsplittable bundles fail with advice, dev-only and excluded files left out |

Two bugs were found and fixed by these tests: small clusters being split into fragments that were too small to become routers, and router descriptions changing between identical runs.

## Benchmark on a real collection

A collection of 78 public skills: a marketing pack, an agent-systems pack, a design pack and a few single skills.

**Context cost**

| | Before (78 skills) | After (6 skills) |
|---|---|---|
| Skill text loaded in every conversation | ~14,700 tokens | ~1,200 tokens (-92%) |
| Conversation that uses a marketing router | ~14,700 | ~3,800 |
| Conversation that uses the agent-systems router | ~14,700 | ~3,000 |

Token counts are estimated from character counts. The host's own plugin report gave ~13,300 always-on tokens for the same packs before routing, so the estimate is in the right range.

**Routing accuracy**

70 requests in two languages across marketing, design and agent-system tasks, plus requests that should not trigger any skill. The same model picked a skill from the flat list of 78 and, separately, from the routers (top level first, then the router map). Two router layouts were tested: one marketing router of 52 skills, and the upload-ready layout where the 200-file limit splits marketing in two.

| | Flat list | 5 routers | 6 routers (upload-ready) |
|---|---|---|---|
| Correct skill | 69 / 70 | 70 / 70 | 69 / 70 |
| Skill triggered when none should | 0 | 0 | 0 |

Each layout missed at most one request, and each miss was a near-neighbour skill, so accuracy is effectively unchanged while the always-loaded text drops by more than 90%.

**Generality**

| Scenario | Result |
|---|---|
| 3 new skills added to an existing build | existing layout unchanged; the related one joined the matching router, unrelated ones stayed standalone |
| A different collection of 19 unrelated skills | nothing grouped (correct: no shared topic) |
| Both collections together (97 skills) | 24 top-level skills, -79% always-loaded text |
