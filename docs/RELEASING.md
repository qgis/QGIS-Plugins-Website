# Release & Deployment Process

This document describes how changes flow from development to production for the
QGIS Plugins Website, how we plan and communicate releases, and how to ship an
urgent hotfix without waiting for the next planned release.

## Goals

- A clean, predictable path from development to production.
- Planned releases that can be **communicated and scheduled** in advance.
- The ability to ship **urgent hotfixes immediately**, out of band.
- Reproducible, **immutable deploys** with easy rollback.

## Key concepts

### Versioning

We use [Semantic Versioning](https://semver.org/): `MAJOR.MINOR.PATCH`.

- **MAJOR** (`vX.0.0`) — breaking or large change; announced ahead of time.
- **MINOR** (`vX.Y.0`) — planned release with new features (a milestone).
- **PATCH** (`vX.Y.Z`) — hotfix / small fix shipped out of band.

The canonical version lives in [`qgis-app/.version`](../qgis-app/.version). It is
read by the `version_tag` template tag
([`qgis-app/plugins/templatetags/plugin_utils.py`](../qgis-app/plugins/templatetags/plugin_utils.py))
and shown in the site footer. **Bumping `.version` is the act of cutting a
release**, and the git tag is always `v` + the file content (e.g. `.version` =
`3.3.0` → tag `v3.3.0`). Existing tags `v1.0.0`…`v3.2.0` already follow this.

### What a tag delivers

A single tag `vX.Y.Z` defines a complete release in two parts:

| Part | Source | How it reaches production |
| --- | --- | --- |
| **Application** (`qgis-app/`, Python deps, `uwsgi.conf`) | baked into the Docker image at tag-build time (see [`Dockerfile`](../dockerize/docker/Dockerfile)) | `docker compose pull` of the pinned image |
| **Static assets** (webpack bundles, CSS, images) | built by `npm run build` + `collectstatic` inside the Dockerfile `prod` stage | copied from the image to the static volume on container start |
| **Deployment config** (compose, nginx `sites-enabled/*`, scripts, Makefile) | the repo at that tag | `git checkout vX.Y.Z` on the server |

This answers the common question *"what about code outside `qgis-app/`?"* — it is
**not** in the image, but it is still versioned by the same tag and applied by
checking that tag out on the server. So nothing is left ungoverned.

> Note: `dockerize/docker/REQUIREMENTS.txt`, `dockerize/docker/uwsgi.conf`, and all
> static assets (webpack bundles + Django statics) **are** baked into the image.
> Changing any of these produces a new image and therefore requires a new tag/release.

### Immutable deploys

Production runs the application **code baked into the image**, not a bind-mounted
checkout. The base [`docker-compose.yml`](../dockerize/docker-compose.yml)
deliberately does **not** mount `../qgis-app` into the app containers; the image
referenced by `UWSGI_DOCKER_IMAGE` is the source of truth. For local development,
`docker-compose.override.yml` (copied from
[`docker-compose.override.template.yml`](../dockerize/docker-compose.override.template.yml))
re-mounts `../qgis-app` so you still get live editing.

## Branch model

```mermaid
gitGraph
    commit id: "v3.2.0" tag: "v3.2.0"
    branch feature/x
    commit
    commit
    checkout main
    merge feature/x id: "PR merged"
    branch fix/y
    commit
    checkout main
    merge fix/y
    commit id: "v3.3.0" tag: "v3.3.0"
    branch hotfix/z
    commit id: "urgent fix"
    checkout main
    merge hotfix/z id: "back-merge"
    commit tag: "v3.3.1"
```

- **`master`** — protected trunk. Every change lands here via PR after CI passes.
  Always represents the *next* release. Never deployed directly.
- **`feature/*`, `fix/*`** — short-lived branches → PR → `master`.
- **`hotfix/*`** — branched from the **latest release tag** (not `master`), so an
  urgent fix does not drag along unreleased work.
- There is **no long-lived production branch**. Production is simply "the tag
  currently deployed". The old `deploy-prod` branch is retired once the first
  image-based deploy succeeds.

`master` should be protected in GitHub settings: require the `pr-test` workflow to
pass and at least one review before merge.

## End-to-end flow

```mermaid
flowchart TD
    A[feature/* or fix/* branch] -->|labelled PR<br/>tests + image build/scan green| B[master]
    B -->|release-drafter updates| C[Draft GitHub Release]
    B -->|milestone complete| D[Bump qgis-app/.version]
    C --> P[Publish GitHub Release vX.Y.0<br/>creates tag = release history]
    D --> P
    P --> F[docker.yml: build + SBOM + CVE scan<br/>push qgis/qgis-plugins-uwsgi:vX.Y.0 + latest]
    F --> H[deploy.sh vX.Y.0 on server]
    H --> I[(Production)]

    I -. urgent issue .-> J[hotfix/* from latest tag]
    J -->|labelled PR + CI green| K[Publish Release vX.Y.Z patch]
    K --> F
    J -->|back-merge| B
```

## Planned release (milestone-based)

**Step-by-step runbooks:** [RELEASE-MINOR.md](./RELEASE-MINOR.md) for an
enhancement/feature release (`vX.Y.0`) and [RELEASE-MAJOR.md](./RELEASE-MAJOR.md)
for a breaking release (`vX.0.0`).

1. **Plan**: create a GitHub **Milestone** named for the target version
   (e.g. `v3.3.0`) and assign the issues/PRs it will contain. This is where major
   changes are communicated and scheduled ahead of time. For a MAJOR release,
   also open a pinned "release plan" issue/discussion.
2. **Develop**: PRs merge into `master`. Label each PR (`feature`, `fix`,
   `breaking`, `chore`, …) so release notes and the version bump are derived
   automatically.
3. **Cut the release** when the milestone is done:
   1. Bump [`qgis-app/.version`](../qgis-app/.version) to the new version and
      merge that to `master` (e.g. `3.3.0`).
   2. Open the **draft GitHub Release** that release-drafter prepared, give it a
      final read (the entries come from your merged-PR labels/titles), set the
      target to `master`, and **publish** it as `v3.3.0`. Publishing creates the
      tag and is the single event that builds the deployable image.
   3. Publishing triggers [`docker.yml`](../.github/workflows/docker.yml):
      build the `prod` image → SBOM + CVE scan → push
      `qgis/qgis-plugins-uwsgi:v3.3.0` (+ `latest`), with the SBOM/scan attached
      to the release. The published release is also the project's changelog — see
      [Release notes](#release-notes-changelog) below.
4. **Deploy** once the image is pushed (see below).

## Hotfix (out of band)

Use this when production needs a fix before the next planned release.
**Full step-by-step runbook: [HOTFIX.md](./HOTFIX.md).**

```sh
# Branch from the live release tag, NOT master.
git checkout -b hotfix/fix-upload-crash v3.3.0
# ... make the fix, bump qgis-app/.version to 3.3.1 ...
git commit -am "Fix upload crash"
# Open a PR (label it `hotfix`/`fix`) for review + CI.
git push origin hotfix/fix-upload-crash
```

Once approved, **publish a GitHub Release `v3.3.1`** targeting the hotfix commit:
that builds, scans, and pushes the image just like any release. Then deploy
`v3.3.1`. **Always merge the hotfix back into `master`** so it is included in the
next release. See [HOTFIX.md](./HOTFIX.md) for the complete checklist, rollback,
and back-merge details.

## Deploying to production

Deploys are image-based and reproducible. On the server:

```sh
dockerize/scripts/deploy.sh v3.3.0
```

[`deploy.sh`](../dockerize/scripts/deploy.sh) will:

1. Fetch tags and check out the deployment config at `v3.3.0`.
2. Pin `UWSGI_DOCKER_IMAGE=qgis/qgis-plugins-uwsgi:v3.3.0` in `dockerize/.env`.
3. `docker compose pull` the image and recreate `uwsgi` on it.
4. On container start, `uwsgi` copies the baked static assets from the image into
   the static volume (nginx reads from there). No separate `collectstatic` step.
5. Run migrations (auth first).
6. Recreate the remaining app services (`web`, `worker`, `beat`, `dbbackups`).

### Rollback

Re-run the script with the previous version — the script prints it at the end of
every deploy:

```sh
dockerize/scripts/deploy.sh v3.2.0
```

Because images are immutable and pinned by tag, rollback is just deploying the
previous tag.

## Release notes (changelog)

There is **no `CHANGELOG.md` in the repo**. The
[GitHub Releases page](https://github.com/qgis/QGIS-Plugins-Website/releases) is
the single source of truth for the project's history — each tag has a release
with its notes.

Release notes are built from your PRs, so day to day:

- **Label your PRs** (`feature`, `enhancement`, `fix`, `bug`, `hotfix`,
  `breaking`, `chore`, `ci`, `infra`, `docs`, `dependencies`) and write a clear
  title. See [LABELS.md](./LABELS.md) for what each label does. As PRs merge into
  `master`,
  [`release-drafter.yml`](../.github/release-drafter.yml) keeps a **draft
  release** updated with grouped notes. Add `skip-changelog` to omit a PR.
- Labels also decide the next version bump: `breaking` → major,
  `feature`/`enhancement` → minor, otherwise patch.
- **Unreleased changes** are visible in that draft release.
- Cutting a release = bump `qgis-app/.version`, push the tag, then **publish** the
  draft release for that tag (see [Planned release](#planned-release-milestone-based)).

## CI/CD summary

| Workflow | Trigger | Purpose |
| --- | --- | --- |
| [`test.yaml`](../.github/workflows/test.yaml) | PR/push to `master` | lint + dockerized Django tests |
| [`release-drafter.yml`](../.github/workflows/release-drafter.yml) | push to `master`, PRs | keep a draft GitHub Release updated from PR labels |
| [`docker.yml`](../.github/workflows/docker.yml) | PR (build + SBOM/CVE scan, no push); release published (build, scan, **push** `:<tag>` + `:latest`, attach SBOM/scan) | verify the prod image early and publish it on release |

> The `docker.yml` scan is **report-only** today (`fail-build: false`) and uploads
> results to the repo's **Security → Code scanning** tab. Once the CVE baseline is
> clean, flip it to fail PRs above a severity cutoff.
