#!/bin/sh
# Säkerhetskopierar CAD:s databas i testmiljön (#89), som catalog-backup.sh gör för Catalog
# (CAT-39). Körs av up.sh före varje migrering och av cron varje natt:
#
#     sh cad-backup.sh fore-migrering
#     sh cad-backup.sh natt
#
# Kopian krypteras med CAD_BACKUP_KEY (AES-256, nyckeln ligger i Scaleways Secret Manager
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

# CAD runs in the profile cad; while its database is not running there is nothing to copy.
if [ -z "$(docker compose ps --status running --quiet cad-db 2>/dev/null)" ]; then
  echo "CAD:s databas kör inte; ingen säkerhetskopia behövs än."
  exit 0
fi
: "${CAD_BACKUP_KEY:?CAD_BACKUP_KEY saknas i .env}"

DIR="$(pwd)/cad-backup"
mkdir -p "$DIR"
chmod 700 "$DIR"
umask 077

db() { docker compose exec -T cad-db "$@"; }
version() {
  db psql -U cad -d "$1" -Atc \
    "SELECT coalesce(max(version), 0) FROM cad_migration" 2>/dev/null || echo 0
}
CIPHER="-aes-256-cbc -pbkdf2 -iter 200000"

STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
OUT="$DIR/cad-$STAMP-$KIND.dump.enc"
TMP="$OUT.tmp"
trap 'rm -f "$TMP"; db dropdb -U cad --if-exists cad_verify >/dev/null 2>&1 || true' EXIT

# shellcheck disable=SC2086 # CIPHER is several words on purpose.
db pg_dump -U cad -d cad --format=custom | openssl enc $CIPHER -salt -pass env:CAD_BACKUP_KEY -out "$TMP"

# Provet: dekryptera, läs in i en tom databas och jämför migrationen.
db dropdb -U cad --if-exists cad_verify
db createdb -U cad cad_verify
# shellcheck disable=SC2086
openssl enc -d $CIPHER -pass env:CAD_BACKUP_KEY -in "$TMP" |
  db pg_restore -U cad -d cad_verify --no-owner --exit-on-error
LIVE="$(version cad)"
COPY="$(version cad_verify)"
if [ "$LIVE" != "$COPY" ]; then
  echo "Säkerhetskopian stämmer inte: databasen har migration $LIVE, kopian $COPY." >&2
  exit 1
fi
db dropdb -U cad cad_verify

mv "$TMP" "$OUT"
trap - EXIT
ls -1t "$DIR"/cad-*-"$KIND".dump.enc | tail -n +15 | while read -r old; do rm -f "$old"; done
echo "Säkerhetskopian är tagen, krypterad och provad: $(basename "$OUT") (migration $LIVE)."
