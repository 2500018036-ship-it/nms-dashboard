#!/usr/bin/env bash
set -Eeuo pipefail
umask 077

state=/var/lib/nms-dashboard-deploy
project=/mnt/data/www/nms-dashboard
release_base=https://github.com/2500018036-ship-it/nms-dashboard/releases
install -d -m 700 "$state"
exec 9>"$state/lock"
flock -n 9 || exit 0
work=$(mktemp -d "$state/download.XXXXXX")
trap 'rm -rf -- "$work"' EXIT

curl --fail --silent --show-error --location --retry 2 --connect-timeout 10 --max-time 45 \
  "$release_base/latest/download/deployment.json" -o "$work/deployment.json"
revision=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["revision"])' "$work/deployment.json")
checksum=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["sha256"])' "$work/deployment.json")
backend=$(python3 -c 'import json,sys; print("true" if json.load(open(sys.argv[1])).get("backend") is True else "false")' "$work/deployment.json")
[[ $revision =~ ^[a-f0-9]{40}$ && $checksum =~ ^[a-f0-9]{64}$ ]] || { echo 'Invalid release manifest' >&2; exit 1; }
image="nms-dashboard:$revision"
current=$(cat "$state/current-revision" 2>/dev/null || true)
if [[ $current == "$revision" ]]; then
  exit 0
fi
if [[ -f "$state/blocked-revision" ]] && [[ $(cat "$state/blocked-revision") == "$revision" ]]; then
  echo "Release $revision previously failed; awaiting another revision or manual retry." >&2
  exit 1
fi

echo "Downloading tested release $revision"
curl --fail --silent --show-error --location --retry 2 --connect-timeout 10 --max-time 600 \
  "$release_base/download/deploy-$revision/nms-dashboard-image.tar.gz" -o "$work/image.tar.gz"
printf '%s  %s\n' "$checksum" "$work/image.tar.gz" | sha256sum --check --status
docker load --input "$work/image.tar.gz"
test "$(docker image inspect --format '{{index .Config.Labels "org.opencontainers.image.revision"}}' "$image")" = "$revision"
if [[ $backend == true ]]; then
  test "$(docker image inspect --format '{{index .Config.Labels "org.opencontainers.image.revision"}}' "nms-backend:$revision")" = "$revision"
fi

previous=$(cat "$state/release.env" 2>/dev/null || true)
printf 'NMS_DASHBOARD_IMAGE=%s\n' "$image" > "$state/release.env"
if [[ $backend == true ]]; then
  printf 'NMS_BACKEND_IMAGE=nms-backend:%s\n' "$revision" >> "$state/release.env"
elif [[ $previous == *NMS_BACKEND_IMAGE=* ]]; then
  printf '%s\n' "$previous" | sed -n '/^NMS_BACKEND_IMAGE=/p' >> "$state/release.env"
fi
compose=(docker compose --project-name nms-dashboard --env-file "$state/release.env" -f "$project/compose.yaml")
backend_compose=(docker compose --project-name nms-bot --project-directory /mnt/data/www/nms-bot --env-file "$state/release.env" -f /mnt/data/www/nms-bot/compose.yaml -f "$project/deploy/backend.compose.yaml")
rollout() {
  if [[ $backend == true ]]; then
    "${backend_compose[@]}" up -d --no-build --wait --wait-timeout 240 nms-bot || return 1
  fi
  "${compose[@]}" up -d --no-build --wait --wait-timeout 120 || return 1
  verify_api
}
verify_api() {
  test "$(curl --silent --max-time 15 --output /dev/null --write-out '%{http_code}' -H 'Host: nms.azrilachdi.web.id' http://127.0.0.1:18082/nms-api/api/auth/session)" = 401
}
if rollout; then
  printf '%s\n' "$revision" > "$state/current-revision"
  printf '%s\n' "$previous" > "$state/previous.env"
  cp "$work/deployment.json" "$state/current-manifest.json"
  echo "Deployed healthy revision $revision"
else
  printf '%s\n' "$revision" > "$state/blocked-revision"
  echo "Release $revision failed its health/API check; restoring previous image." >&2
  if [[ -n $previous ]]; then
    printf '%s\n' "$previous" > "$state/release.env"
    if [[ $backend == true && $previous == *NMS_BACKEND_IMAGE=* ]]; then
      "${backend_compose[@]}" up -d --no-build --wait --wait-timeout 240 nms-bot
    fi
    "${compose[@]}" up -d --no-build --wait --wait-timeout 120
    verify_api
    echo 'Previous healthy image restored.'
  fi
  exit 1
fi
