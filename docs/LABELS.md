# PR Labels Reference

PR labels are the engine of our release process. They do **two** things
automatically, both driven by
[`.github/release-drafter.yml`](../.github/release-drafter.yml):

1. **Group the change** under a heading in the draft GitHub Release (the changelog).
2. **Resolve the next version bump** (major / minor / patch).

Label every PR with exactly one primary label from the table below. Milestones do
**not** affect the version — only labels do.

## The labels

| Label | Changelog section | Version bump | Use for |
| --- | --- | --- | --- |
| `breaking` | Breaking changes | **major** (`vX.0.0`) | Backward-incompatible change: removed/renamed API or URL, data-model change needing migration, runtime jump that alters behaviour. |
| `feature` | Added | **minor** (`vX.Y.0`) | A new user-facing capability. |
| `enhancement` | Added | **minor** (`vX.Y.0`) | An improvement to an existing capability. |
| `fix` | Fixed | **patch** (`vX.Y.Z`) | A bug fix. |
| `bug` | Fixed | **patch** | A bug fix (alias of `fix`). |
| `hotfix` | Fixed | **patch** | An urgent out-of-band production fix (see [HOTFIX.md](./HOTFIX.md)). |
| `changed` | Changed | **patch** (default) | A behaviour change that is not breaking. |
| `refactor` | Changed | **patch** (default) | Internal restructuring with no behaviour change. |
| `chore` | Maintenance & Ops | **patch** | Miscellaneous maintenance. |
| `ci` | Maintenance & Ops | **patch** | CI / workflow changes. |
| `infra` | Maintenance & Ops | **patch** | Infrastructure / deployment config. |
| `docs` | Maintenance & Ops | **patch** | Documentation only. |
| `dependencies` | Maintenance & Ops | **patch** | Dependency bumps. |
| `skip-changelog` | _(excluded)_ | — | Omit the PR from the release notes entirely. |

## How the version is resolved

Release-drafter computes the next version from **all** PRs merged since the last
published release, taking the **highest** bump present:

- any `breaking` → the whole next release is **major**;
- otherwise any `feature`/`enhancement` → **minor**;
- otherwise → **patch** (this is also the `default` when no label resolves a bump).

So a single `breaking` PR turns an otherwise-minor cycle into a major release. Pick
labels with that precedence in mind.

## Which runbook each label points to

| Intent | Label | Runbook |
| --- | --- | --- |
| New feature / improvement | `feature` / `enhancement` | [RELEASE-MINOR.md](./RELEASE-MINOR.md) |
| Backward-incompatible change | `breaking` | [RELEASE-MAJOR.md](./RELEASE-MAJOR.md) |
| Urgent production fix | `hotfix` / `fix` | [HOTFIX.md](./HOTFIX.md) |

> Keep these labels in sync with `.github/release-drafter.yml`. If you add a label
> there, add a row here too — this table is the human-readable mirror of that
> config.
