#!/bin/sh
# Säkerhetskopierar Catalogs databas i testmiljön (CAT-39). Körs av up.sh före varje
# migrering och av cron varje natt:
#
#     sh catalog-backup.sh fore-migrering
#     sh catalog-backup.sh natt
#
# Kopian krypteras med CATALOG_BACKUP_KEY (AES-256, nyckeln ligger i Scaleways Secret Manager
# och i .env på servern, aldrig i repot). Den provas innan den sparas: den dekrypteras och
# läses in i en tom databas, som ska ha samma migration som den riktiga. En kopia som inte
# går att läsa in stoppar utläggningen. De 14 senaste av varje slag sparas.
#
# Mappen är /srv/trainmeet, eller TESTMILJO_DIR (för provet i CI).
set -eu

KIND="${1:-natt}"
case "$KIND" in
  natt|fore-migrering) ;;
  *) echo "Okänt slag: $KIND (natt eller fore-migrering)" >&2; exit 2 ;;
esac

cd "${TESTMILJO_DIR:-/srv/trainmeet}"
set -a
. ./.env
set +a
: "${CATALOG_BACKUP_KEY:?CATALOG_BACKUP_KEY saknas i .env}"

DIR="$(pwd)/catalog-backup"
mkdir -p "$DIR"
chmod 700 "$DIR"
umask 077

if [ -z "$(docker compose ps --status running --quiet catalog-db 2>/dev/null)" ]; then
  echo "Catalogs databas kör inte; ingen säkerhetskopia behövs än."
  exit 0
fi

db() { docker compose exec -T catalog-db "$@"; }
version() {
  db psql -U catalog -d "$1" -Atc \
    "SELECT coalesce(max(version), 0) FROM catalog_migration" 2>/dev/null || echo 0
}
CIPHER="-aes-256-cbc -pbkdf2 -iter 200000"

STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
OUT="$DIR/catalog-$STAMP-$KIND.dump.enc"
TMP="$OUT.tmp"
trap 'rm -f "$TMP"; db dropdb -U catalog --if-exists catalog_verify >/dev/null 2>&1 || true' EXIT

# shellcheck disable=SC2086 # CIPHER is several words on purpose.
db pg_dump -U catalog -d catalog --format=custom | openssl enc $CIPHER -salt -pass env:CATALOG_BACKUP_KEY -out "$TMP"

# Provet: dekryptera, läs in i en tom databas och jämför migrationen.
db dropdb -U catalog --if-exists catalog_verify
db createdb -U catalog catalog_verify
# shellcheck disable=SC2086
openssl enc -d $CIPHER -pass env:CATALOG_BACKUP_KEY -in "$TMP" |
  db pg_restore -U catalog -d catalog_verify --no-owner --exit-on-error
LIVE="$(version catalog)"
COPY="$(version catalog_verify)"
if [ "$LIVE" != "$COPY" ]; then
  echo "Säkerhetskopian stämmer inte: databasen har migration $LIVE, kopian $COPY." >&2
  exit 1
fi
db dropdb -U catalog catalog_verify

mv "$TMP" "$OUT"
trap - EXIT
ls -1t "$DIR"/catalog-*-"$KIND".dump.enc | tail -n +15 | while read -r old; do rm -f "$old"; done
echo "Säkerhetskopian är tagen, krypterad och provad: $(basename "$OUT") (migration $LIVE)."
