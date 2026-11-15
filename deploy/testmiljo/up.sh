#!/bin/sh
# Körs på servern av jobbet "Testmiljön", efter att bilderna trainmeet-hub:$1,
# trainmeet-catalog:$1 och trainmeet-id:$1 har laddats in och catalog.env, id.env,
# id-vault/ och catalog-backup.sh har lagts dit.
# Startar de nya versionerna, provar dem och städar bort gamla versioner (de tre senaste blir
# kvar). Catalogs databas säkerhetskopieras och provas före migreringen (CAT-39).
set -eu

TAG="$1"
DOMAIN="$2"
CATALOG_DOMAIN="$3"
ID_DOMAIN="$4"
cd /srv/trainmeet

umask 077
test -s catalog.env || { echo "catalog.env saknas på servern." >&2; exit 1; }
test -s id.env || { echo "id.env saknas på servern." >&2; exit 1; }
mkdir -p id-vault
{
  printf 'HUB_TAG=%s\nHUB_DOMAIN=%s\n' "$TAG" "$DOMAIN"
  printf 'CATALOG_TAG=%s\nCATALOG_DOMAIN=%s\n' "$TAG" "$CATALOG_DOMAIN"
  printf 'ID_TAG=%s\nID_DOMAIN=%s\nHOST_UID=%s\n' "$TAG" "$ID_DOMAIN" "$(id -u)"
  cat catalog.env id.env
} > .env
umask 022

# Catalog: the database first, then the backup, then the migrations, then the new version.
docker compose up -d catalog-db
i=0
until docker compose exec -T catalog-db pg_isready -U catalog -d catalog >/dev/null 2>&1; do
  i=$((i + 1))
  if [ "$i" -ge 60 ]; then
    echo "Catalogs databas startar inte." >&2
    docker compose logs --tail 50 catalog-db >&2
    exit 1
  fi
  sleep 1
done
sh ./catalog-backup.sh fore-migrering
docker compose run --rm --no-deps catalog python -m catalog.migrate

docker compose up -d --remove-orphans

# Caddy runs without its admin API, so a changed Caddyfile needs a restart.
sha256sum Caddyfile .env > .sums.new
if ! cmp -s .sums.new .sums; then
  docker compose restart caddy
fi
mv .sums.new .sums

# Every night at 03:17 UTC: a backup of Catalog's database (CAT-39).
NIGHT="17 3 * * * sh /srv/trainmeet/catalog-backup.sh natt >> /srv/trainmeet/catalog-backup/logg.txt 2>&1"
if command -v crontab >/dev/null 2>&1; then
  { crontab -l 2>/dev/null | grep -v 'catalog-backup.sh' || true; echo "$NIGHT"; } | crontab -
else
  # Shown as a warning on the run in GitHub Actions.
  echo "::warning::cron saknas på servern, så nattens säkerhetskopia av Catalog är inte inlagd."
fi

# TrainMeet ID must be ready, and know the realm, before it counts as out.
i=0
until curl -fsS http://127.0.0.1:9082/health/ready >/dev/null 2>&1 &&
  curl -fsS http://127.0.0.1:8082/realms/trainmeet/.well-known/openid-configuration >/dev/null 2>&1; do
  i=$((i + 1))
  if [ "$i" -ge 120 ]; then
    echo "TrainMeet ID svarar inte." >&2
    docker compose logs --tail 80 id >&2
    exit 1
  fi
  sleep 2
done
REVISION=$(docker inspect --format '{{index .Config.Labels "org.opencontainers.image.revision"}}' "$(docker compose ps -q id)")
if [ "$REVISION" != "$TAG" ]; then
  echo "TrainMeet ID kör inte version $TAG." >&2
  exit 1
fi
echo "id svarar med version $TAG."
if [ ! -s id-vault/trainmeet_smtp-password ]; then
  # Shown as a warning on the run in GitHub Actions.
  echo "::warning::Mejlnyckeln saknas (TEM_SECRET_KEY), så TrainMeet ID kan inte skicka koder än."
fi

# The new versions must answer on the server itself, with the right commit.
for service in hub:8080 catalog:8081; do
  name="${service%%:*}"
  port="${service##*:}"
  i=0
  until curl -fsS "http://127.0.0.1:$port/api/version" 2>/dev/null | grep -q "\"commit\":\"$TAG\""; do
    i=$((i + 1))
    if [ "$i" -ge 30 ]; then
      echo "Den nya versionen av $name svarar inte." >&2
      docker compose logs --tail 50 "$name" >&2
      exit 1
    fi
    sleep 1
  done
  echo "$name svarar med version $TAG."
done

for image in trainmeet-hub trainmeet-catalog trainmeet-id; do
  docker images "$image" --format '{{.CreatedAt}}\t{{.Tag}}' | sort -r | tail -n +4 | cut -f2 |
    while read -r old; do
      [ "$old" = "$TAG" ] || docker image rm "$image:$old" >/dev/null 2>&1 || true
    done
done
docker image prune -f >/dev/null
