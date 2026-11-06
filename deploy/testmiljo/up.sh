#!/bin/sh
# Körs på servern av jobbet "Testmiljön", efter att bilden trainmeet-hub:$1 har laddats in.
# Startar den nya versionen, provar den och städar bort gamla versioner (de tre senaste blir kvar).
set -eu

TAG="$1"
DOMAIN="$2"
cd /srv/trainmeet

printf 'HUB_TAG=%s\nHUB_DOMAIN=%s\n' "$TAG" "$DOMAIN" > .env
docker compose up -d --remove-orphans

# Caddy runs without its admin API, so a changed Caddyfile needs a restart.
sha256sum Caddyfile .env > .sums.new
if ! cmp -s .sums.new .sums; then
  docker compose restart caddy
fi
mv .sums.new .sums

# The new version must answer on the server itself, with the right commit.
i=0
until curl -fsS http://127.0.0.1:8080/api/version 2>/dev/null | grep -q "\"commit\":\"$TAG\""; do
  i=$((i + 1))
  if [ "$i" -ge 30 ]; then
    echo "Den nya versionen svarar inte." >&2
    docker compose logs --tail 50 hub >&2
    exit 1
  fi
  sleep 1
done
echo "Hubben svarar med version $TAG."

docker images trainmeet-hub --format '{{.CreatedAt}}\t{{.Tag}}' | sort -r | tail -n +4 | cut -f2 |
  while read -r old; do
    [ "$old" = "$TAG" ] || docker image rm "trainmeet-hub:$old" >/dev/null 2>&1 || true
  done
docker image prune -f >/dev/null
