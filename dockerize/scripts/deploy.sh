#!/usr/bin/env bash
#
# Deploy a pinned, versioned release of the QGIS Plugins Website to production.
#
# One git tag == one release: it provides BOTH the application image
# (qgis/qgis-plugins-uwsgi:<version>, baked from qgis-app/) AND the matching
# dockerize/ deployment config (compose, nginx, scripts). See docs/RELEASING.md.
#
# Usage:
#   dockerize/scripts/deploy.sh v3.3.0
#
# Rollback:
#   dockerize/scripts/deploy.sh <previous-version>
#
set -euo pipefail

PROJECT_ID="qgis-plugins"
IMAGE_REPO="qgis/qgis-plugins-uwsgi"

VERSION="${1:-}"
if [[ -z "$VERSION" ]]; then
  echo "Usage: $0 <version>   (e.g. $0 v3.3.0)" >&2
  exit 1
fi

# Resolve repo root and the dockerize directory regardless of where we're called.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DOCKERIZE_DIR="$(dirname "$SCRIPT_DIR")"
REPO_ROOT="$(dirname "$DOCKERIZE_DIR")"
ENV_FILE="$DOCKERIZE_DIR/.env"

cd "$REPO_ROOT"

echo "==> Fetching tags"
git fetch --tags --prune origin

if ! git rev-parse -q --verify "refs/tags/${VERSION}" >/dev/null; then
  echo "Tag ${VERSION} does not exist. Available recent tags:" >&2
  git tag -l | tail -n 10 >&2
  exit 1
fi

# Record the currently deployed image for easy rollback.
if [[ -f "$ENV_FILE" ]]; then
  PREVIOUS="$(grep -E '^UWSGI_DOCKER_IMAGE=' "$ENV_FILE" | cut -d'=' -f2- | tr -d "'\"" || true)"
  echo "==> Currently deployed: ${PREVIOUS:-unknown}"
fi

echo "==> Checking out deployment config at ${VERSION}"
git checkout --quiet "tags/${VERSION}"

# Pin the application image for this release in the env file consumed by compose.
echo "==> Pinning UWSGI_DOCKER_IMAGE=${IMAGE_REPO}:${VERSION}"
if grep -qE '^UWSGI_DOCKER_IMAGE=' "$ENV_FILE"; then
  sed -i.bak -E "s|^UWSGI_DOCKER_IMAGE=.*|UWSGI_DOCKER_IMAGE='${IMAGE_REPO}:${VERSION}'|" "$ENV_FILE"
else
  echo "UWSGI_DOCKER_IMAGE='${IMAGE_REPO}:${VERSION}'" >>"$ENV_FILE"
fi

cd "$DOCKERIZE_DIR"

echo "==> Pulling image ${IMAGE_REPO}:${VERSION}"
docker compose -p "$PROJECT_ID" pull uwsgi

# Bring up the app container on the new image first so migrations run against
# the new code. Static assets are copied from the baked image on container start.
echo "==> Recreating uwsgi on the new image"
docker compose -p "$PROJECT_ID" up -d --no-deps uwsgi

echo "==> Running database migrations (auth first)"
make migrate

echo "==> Recreating remaining application services"
docker compose -p "$PROJECT_ID" up -d --scale uwsgi=2 web worker beat dbbackups

echo
echo "==> Deployed ${VERSION}."
echo "    Rollback with: $0 ${PREVIOUS:-<previous-version>}"
