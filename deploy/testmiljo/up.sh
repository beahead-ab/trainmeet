#!/bin/sh
# Körs på servern av jobbet "Testmiljön", efter att bilderna trainmeet-hub:$1,
# trainmeet-catalog:$1, trainmeet-id:$1, trainmeet-idapi:$1, trainmeet-tkl:$1 och trainmeet-cad:$1
# har laddats in och catalog.env, id.env, cad.env, id-vault/, catalog-backup.sh och cad-backup.sh
# har lagts dit.
# Startar de nya versionerna, provar dem och städar bort gamla versioner (de tre senaste blir
# kvar). Catalogs databas säkerhetskopieras och provas före migreringen (CAT-39).
set -eu

TAG="$1"
DOMAIN="$2"
CATALOG_DOMAIN="$3"
ID_DOMAIN="$4"
# The tags' address (C38): trainmeet.app answers /t/ once its DNS row points here, and the job
# passes https://trainmeet.app/t/ as the tags' base then; until that, Catalog's own address.
TAGS_DOMAIN="${5:-trainmeet.app}"
TAG_BASE="${6:-https://$CATALOG_DOMAIN/t/}"
# Låtsas-Pi (#73): the same hub as a Pi runs it, following the test hub.
PI_DOMAIN="${7:-test.pi.trainmeet.app}"
# TKL i molnet (#76): trainmeet-tkl:$1 too.
TKL_DOMAIN="${8:-test.tkl.trainmeet.app}"
# TrainMeet CAD (#89): trainmeet-cad:$1, with its secrets in cad.env.
CAD_DOMAIN="${9:-test.cad.trainmeet.app}"
cd /srv/trainmeet

umask 077
test -s catalog.env || { echo "catalog.env saknas på servern." >&2; exit 1; }
test -s id.env || { echo "id.env saknas på servern." >&2; exit 1; }
test -s cad.env || { echo "cad.env saknas på servern." >&2; exit 1; }
mkdir -p id-vault catalog-vault
# Catalogs bilder (#51) on the server's disk when there is no bucket; Catalog runs as this user.
mkdir -p catalog-pictures
# CAD (#89): its three secrets come from deploy/testmiljo.py in cad.env, as Catalog's, and the
# profile cad starts it. A cad.env without them stops the deploy instead of leaving CAD off.
for name in CAD_DB_PASSWORD CAD_BACKUP_KEY ID_CAD_SECRET; do
  grep -q "^$name=." cad.env || { echo "cad.env saknar $name." >&2; exit 1; }
done
# Also in .env below, for compose run by cron (cad-backup.sh reads .env).
export COMPOSE_PROFILES=cad
mkdir -p cad-backup && chmod 700 cad-backup
# CAD:s modulfoton (#89 del c1), as Catalog's pictures (#51): CAD's own bucket, whose key
# deploy/testmiljo.py sends in cad.env. It goes to cad-vault, which only the deploy user reads,
# and never into .env. Without a bucket the photos lie on the server's disk, in cad-photos.
mkdir -p cad-vault cad-photos
if grep -q '^CAD_PHOTOS_S3_SECRET_KEY=.' cad.env; then
  {
    sed -n 's/^CAD_PHOTOS_S3_ACCESS_KEY=//p' cad.env
    sed -n 's/^CAD_PHOTOS_S3_SECRET_KEY=//p' cad.env
  } > cad-vault/trainmeet_photos-key
fi
# Catalog logs in with TrainMeet ID once ID can send its codes, and with the trial login until
# then (CAT-214, #66).
TRIAL=on
if [ -s id-vault/trainmeet_smtp-password ]; then TRIAL=off; fi
{
  printf 'HUB_TAG=%s\nHUB_DOMAIN=%s\nPI_DOMAIN=%s\nTKL_DOMAIN=%s\n' "$TAG" "$DOMAIN" "$PI_DOMAIN" "$TKL_DOMAIN"
  printf 'CATALOG_TRIAL_LOGIN=%s\n' "$TRIAL"
  printf 'CATALOG_TAG=%s\nCATALOG_DOMAIN=%s\n' "$TAG" "$CATALOG_DOMAIN"
  printf 'TAGS_DOMAIN=%s\nCATALOG_TAG_BASE=%s\n' "$TAGS_DOMAIN" "$TAG_BASE"
  printf 'ID_TAG=%s\nID_DOMAIN=%s\nHOST_UID=%s\n' "$TAG" "$ID_DOMAIN" "$(id -u)"
  printf 'CAD_TAG=%s\nCAD_DOMAIN=%s\nCAD_TRIAL_LOGIN=%s\n' "$TAG" "$CAD_DOMAIN" "$TRIAL"
  printf 'COMPOSE_PROFILES=cad\n'
  cat catalog.env id.env
  grep -v -e '^CAD_PHOTOS_S3_ACCESS_KEY=' -e '^CAD_PHOTOS_S3_SECRET_KEY=' cad.env
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

# CAD (#89), as Catalog: the database first, then the backup, then the migrations.
docker compose up -d cad-db
i=0
until docker compose exec -T cad-db pg_isready -U cad -d cad >/dev/null 2>&1; do
  i=$((i + 1))
  if [ "$i" -ge 60 ]; then
    echo "CAD:s databas startar inte." >&2
    docker compose logs --tail 50 cad-db >&2
    exit 1
  fi
  sleep 1
done
sh ./cad-backup.sh fore-migrering
docker compose run --rm --no-deps cad python -m cad.migrate

# ID's API has a database of its own, idapi, beside Keycloak's in ID's PostgreSQL (#67).
docker compose up -d id-db
i=0
until docker compose exec -T id-db pg_isready -U keycloak -d keycloak >/dev/null 2>&1; do
  i=$((i + 1))
  if [ "$i" -ge 60 ]; then
    echo "ID:s databas startar inte." >&2
    docker compose logs --tail 50 id-db >&2
    exit 1
  fi
  sleep 1
done
if ! docker compose exec -T id-db psql -U keycloak -d keycloak -tAc \
  "SELECT 1 FROM pg_database WHERE datname = 'idapi'" | grep -q 1; then
  docker compose exec -T id-db createdb -U keycloak idapi
fi

docker compose up -d --remove-orphans

# Caddy runs without its admin API, so a changed Caddyfile needs a restart.
sha256sum Caddyfile .env > .sums.new
if ! cmp -s .sums.new .sums; then
  docker compose restart caddy
fi
mv .sums.new .sums

# Every night at 03:17 UTC: a backup of Catalog's database (CAT-39), and at 03:37 CAD's (#89).
NIGHT="17 3 * * * sh /srv/trainmeet/catalog-backup.sh natt >> /srv/trainmeet/catalog-backup/logg.txt 2>&1"
CAD_NIGHT="37 3 * * * sh /srv/trainmeet/cad-backup.sh natt >> /srv/trainmeet/cad-backup/logg.txt 2>&1"
if command -v crontab >/dev/null 2>&1; then
  {
    crontab -l 2>/dev/null | grep -v -e 'catalog-backup.sh' -e 'cad-backup.sh' || true
    echo "$NIGHT"
    echo "$CAD_NIGHT"
  } | crontab -
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
else
  # The codes go out with SMTP to Transactional Email (#66). Scaleway blocks SMTP out of a new
  # server, and refuses a key without TransactionalEmailEmailSmtpCreate at the login; both make
  # ID say that the code could not be sent (22 November). Logging in from the server tells which,
  # and sends nothing: NOOP instead of a mail. The key goes to curl on stdin, never as an argument.
  SMTP_USER=$(sed -n 's/^TEM_PROJECT_ID=//p' id.env)
  SMTP=0
  printf 'user = "%s:%s"\n' "$SMTP_USER" "$(cat id-vault/trainmeet_smtp-password)" |
    curl -sS --connect-timeout 10 --max-time 30 --url smtps://smtp.tem.scaleway.com:465 \
      -X NOOP -K - -o /dev/null 2>/dev/null || SMTP=$?
  case "$SMTP" in
    0) echo "Mejlen: inloggningen hos Transactional Email går igenom." ;;
    7 | 28) echo "::warning::Servern når inte Scaleways mejlserver (smtp.tem.scaleway.com, port 465), så TrainMeet ID kan inte skicka koder. Scaleway spärrar SMTP ut från nya servrar: slå på Enable SMTP för säkerhetsgruppen trainmeet-testhub (CPU & GPU Instances, Security groups)." ;;
    67) echo "::warning::Scaleway tar inte emot mejlnyckeln (TEM_SECRET_KEY), så TrainMeet ID kan inte skicka koder. Applikationen trainmeet-mejl behöver TransactionalEmailEmailSmtpCreate i projektet trainmeet, och nyckeln ska vara dess Secret Key." ;;
    *) echo "::warning::Inloggningen hos Scaleways mejlserver gick inte (curl $SMTP), så TrainMeet ID kan troligen inte skicka koder." ;;
  esac
fi

# The new versions must answer on the server itself, with the right commit.
for service in hub:8080 pi:8084 tkl:8085 catalog:8081 id-api:8083 cad:8086; do
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

for image in trainmeet-hub trainmeet-catalog trainmeet-id trainmeet-idapi trainmeet-tkl trainmeet-cad; do
  docker images "$image" --format '{{.CreatedAt}}\t{{.Tag}}' | sort -r | tail -n +4 | cut -f2 |
    while read -r old; do
      [ "$old" = "$TAG" ] || docker image rm "$image:$old" >/dev/null 2>&1 || true
    done
done
docker image prune -f >/dev/null
