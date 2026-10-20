# Changelog

All notable changes to this project are documented here.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses [Semantic Versioning](https://semver.org/).

## [1.2.0] - 2026-10-20

### Fixed
- **Router files changed when unrelated skills were added elsewhere.** The "easily confused" section of each router was computed from similarity scores over the whole collection, so adding any skill shifted the scores and produced cosmetic edits in every router. Each edit was reported as "re-upload needed", which meant needless uploads. Similarity is now computed within each router only, so a router changes only when its own members change.
- **Config `members` pins were ignored after the first build.** Incremental builds keep the previous layout, and that layout took priority over the configuration, so pinning skills into a router had no effect once a build existed. Explicit `groups[].members` and `standalone` entries now override the previous layout.

### Added
- `--version` flag.
- Tests for both fixes (25 tests in total).

## [1.1.0] - 2026-10-20

### Added
- **Upload-ready bundles.** Hosts that accept skill ZIP uploads were found to reject bundles containing more than one `SKILL.md` or more than 200 files. To meet those limits:
  - bundled sub-skills now keep their instructions in `INSTRUCTIONS.md`, and references between them are rewritten, so each bundle holds exactly one `SKILL.md`;
  - development-only files (`evals/`, `tests/`, `.github/`) are left out;
  - `--max-files` (default 200) splits any router that would exceed the limit into smaller routers along the same connection graph, then re-merges parts while they still fit, so as few routers as possible are created;
  - `--exclude` and the `exclude` config key remove further files, for example large font or asset folders;
  - a bundle that cannot be split because its skills share files fails with a message naming it and suggesting an `exclude` glob.
- Validation of the one-`SKILL.md` rule and the file limit for every output.
- When community detection cannot split an oversized router (for example without `networkx`), a greedy packing fallback keeps file-linked skills together and fills each part up to the limit.
- Tests for upload limits (23 tests in total).

### Fixed
- **Small clusters were split into fragments.** Community detection sometimes split a small, well-connected cluster into pieces that were each below `min_group`, so none of them became a router. Fragments are now attached to the community they are most strongly linked to.
- **Identical runs produced different router descriptions.** Ties between equally frequent words were broken by hash order, which varies between Python runs. Ties are now broken alphabetically, so output is deterministic.
- Files opened without being closed (resource warnings on Windows).

## [1.0.0] - 2026-10-20

### Added
- `build_routers.py`: discovers skills, builds a connection graph from file links, mentions and TF-IDF similarity, finds communities, writes router skills whose maps are generated from member descriptions, validates and zips the output, and reports token savings.
- Incremental builds with a manifest: existing skills keep their router, new skills join the most connected router or stay standalone, and the report lists changed outputs to re-upload.
- `sync_sources.py`: pulls skills from GitHub repositories listed in `sources.json`.
- Configuration for router names, anchors, pinned members, standalone skills, extra triggers, notes and description overrides.
- Unit tests and benchmark results.

[1.2.0]: https://github.com/gorkicakir/skill-router-builder/compare/v1.1.0...v1.2.0
[1.1.0]: https://github.com/gorkicakir/skill-router-builder/compare/v1.0.0...v1.1.0
[1.0.0]: https://github.com/gorkicakir/skill-router-builder/releases/tag/v1.0.0
