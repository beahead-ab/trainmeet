#!/bin/sh
# TrainMeet Hub på en Raspberry Pi (steg 5, DRIFT-20, SYNK-23, SYNK-26).
#
# Hubben och Pi:ns nätverkstjänst blir tjänster i systemd, utan containrar. Kör på Raspberry Pi
# OS (Trixie eller senare, 64-bit):
#
#   curl -fsSLO https://github.com/beahead-ab/trainmeet/releases/download/pi-senaste/install.sh
#   sudo sh install.sh
#
# eller med ett Pi-paket bredvid:  sudo sh install.sh trainmeet-hub-pi.tar.gz
#
# Samma skript uppdaterar (--update): det hämtar det senaste paketet, lägger det bredvid det
# gamla, startar om hubben och går tillbaka till det gamla om hubben inte svarar inom en minut.
# Träffarna och inställningarna ligger i /var/lib/trainmeet och rörs aldrig. Inga hemligheter
# skrivs ut.
set -eu

RELEASE=${TRAINMEET_RELEASE:-https://github.com/beahead-ab/trainmeet/releases/download/pi-senaste}
PACKAGE_NAME=trainmeet-hub-pi.tar.gz
ROOT=/opt/trainmeet
STATE=/var/lib/trainmeet
USB=/media/trainmeet-usb
STATUS="$STATE/update.json"
USER_NAME=trainmeet
KEEP=3

if [ "$(id -u)" -ne 0 ]; then
  echo "Kör installationen med sudo: sudo sh install.sh"
  exit 1
fi

status() {
  # Uppdateringens läge, som hubben visar under kugghjulet.
  printf '{"status":"%s","message":"%s","build":"%s","at":"%s"}\n' \
    "$1" "$2" "${3:-}" "$(date -u +%Y-%m-%dT%H:%M:%SZ)" > "$STATUS.tmp"
  chown "$USER_NAME:$USER_NAME" "$STATUS.tmp" 2>/dev/null || true
  chmod 0640 "$STATUS.tmp"
  mv "$STATUS.tmp" "$STATUS"
}

UPDATE=false
PACKAGE=""
for ARG in "$@"; do
  case "$ARG" in
    --update) UPDATE=true ;;
    *) PACKAGE=$ARG ;;
  esac
done

# --- Systemet: bara det som saknas, och aldrig ett annat nätverksprogram ----------------------

if [ "$UPDATE" = false ]; then
  echo "Installerar TrainMeet Hub …"
  export DEBIAN_FRONTEND=noninteractive
  WANTED="python3 python3-venv curl avahi-daemon"
  NETWORK=false
  # Pi:ns nätverkstjänst bara på en riktig Pi med NetworkManager igång; nätverket byts aldrig.
  if [ -r /proc/device-tree/model ] && grep -q 'Raspberry Pi' /proc/device-tree/model \
    && systemctl is-active --quiet NetworkManager.service; then
    NETWORK=true
    WANTED="$WANTED python3-dbus"
  fi
  MISSING=""
  for P in $WANTED; do
    dpkg-query -W -f '${Status}' "$P" 2>/dev/null | grep -q 'install ok installed' || MISSING="$MISSING $P"
  done
  if [ -n "$MISSING" ]; then
    echo "Installerar systempaket:$MISSING"
    apt-get -o DPkg::Lock::Timeout=120 update
    # shellcheck disable=SC2086
    apt-get -o DPkg::Lock::Timeout=120 install -y $MISSING
  fi
  if ! id "$USER_NAME" >/dev/null 2>&1; then
    useradd --system --home-dir "$STATE" --create-home --shell /usr/sbin/nologin "$USER_NAME"
  fi
  install -d -m 0750 -o "$USER_NAME" -g "$USER_NAME" "$STATE"
  install -d -m 0755 "$ROOT" "$ROOT/releases" /etc/trainmeet
  install -d -m 0770 -o "$USER_NAME" -g "$USER_NAME" "$USB"
fi

# --- Paketet: hämtat och kontrollerat, eller det som gavs ------------------------------------

WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT
CURRENT_BUILD=$(cat "$ROOT/current/BUILD" 2>/dev/null || true)

if [ -z "$PACKAGE" ]; then
  [ "$UPDATE" = true ] && status checking "Söker efter en nyare version" "$CURRENT_BUILD"
  if ! LATEST=$(curl -fsSL "$RELEASE/BUILD" 2>/dev/null); then
    [ "$UPDATE" = true ] && status failed "Kunde inte nå GitHub. Har Pi:n internet?" "$CURRENT_BUILD"
    echo "Kunde inte nå $RELEASE. Har Pi:n internet?"
    exit 1
  fi
  if [ "$UPDATE" = true ] && [ "$LATEST" = "$CURRENT_BUILD" ]; then
    status current "Hubben har redan den senaste versionen" "$CURRENT_BUILD"
    exit 0
  fi
  [ "$UPDATE" = true ] && status downloading "Hämtar den nya versionen" "$CURRENT_BUILD"
  curl -fsSL -o "$WORK/$PACKAGE_NAME" "$RELEASE/$PACKAGE_NAME"
  curl -fsSL -o "$WORK/$PACKAGE_NAME.sha256" "$RELEASE/$PACKAGE_NAME.sha256"
  if ! (cd "$WORK" && sha256sum -c "$PACKAGE_NAME.sha256" >/dev/null); then
    [ "$UPDATE" = true ] && status failed "Paketet kom inte helt. Ingenting ändrades." "$CURRENT_BUILD"
    echo "Paketets kontrollsumma stämmer inte. Ingenting ändrades."
    exit 1
  fi
  PACKAGE="$WORK/$PACKAGE_NAME"
fi

tar -xzf "$PACKAGE" -C "$WORK"
BUILD=$(cat "$WORK/package/BUILD")
TARGET="$ROOT/releases/$BUILD"
[ "$UPDATE" = true ] && status installing "Installerar version $BUILD" "$CURRENT_BUILD"
rm -rf "$TARGET"
mv "$WORK/package" "$TARGET"
# The system's python3-dbus is needed by the network service, so the venv sees system packages.
python3 -m venv --system-site-packages "$TARGET/venv"
"$TARGET/venv/bin/pip" install --disable-pip-version-check --quiet --require-hashes \
  -r "$TARGET/requirements.txt"
"$TARGET/venv/bin/pip" install --disable-pip-version-check --quiet --no-deps "$TARGET"/wheel/*.whl
chmod 0755 "$TARGET/pi/install.sh"

# --- Tjänsterna ---------------------------------------------------------------------------------

[ -f /etc/trainmeet/hub.env ] || install -m 0644 "$TARGET/pi/hub.env" /etc/trainmeet/hub.env
install -m 0644 "$TARGET/pi/trainmeet-hub.service" /etc/systemd/system/trainmeet-hub.service
install -m 0644 "$TARGET/pi/trainmeet-update.service" /etc/systemd/system/trainmeet-update.service
install -m 0644 "$TARGET/pi/50-trainmeet-update.rules" /etc/polkit-1/rules.d/50-trainmeet-update.rules 2>/dev/null || true
install -m 0644 "$TARGET/pi/90-trainmeet-usb.rules" /etc/udev/rules.d/90-trainmeet-usb.rules
if [ -r /proc/device-tree/model ] && grep -q 'Raspberry Pi' /proc/device-tree/model \
  && systemctl is-active --quiet NetworkManager.service; then
  install -m 0644 "$TARGET/pi/trainmeet-network.service" /etc/systemd/system/trainmeet-network.service
fi
udevadm control --reload-rules 2>/dev/null || true
systemctl daemon-reload

PREVIOUS=$(readlink "$ROOT/current" 2>/dev/null || true)
ln -sfn "$TARGET" "$ROOT/current.new"
mv -T "$ROOT/current.new" "$ROOT/current"
[ "$UPDATE" = true ] && status restarting "Startar om hubben" "$BUILD"
systemctl enable --quiet trainmeet-hub.service
systemctl restart trainmeet-hub.service
if [ -f /etc/systemd/system/trainmeet-network.service ]; then
  systemctl enable --quiet trainmeet-network.service
  systemctl restart trainmeet-network.service
fi

# --- Svarar den nya hubben? Annars tillbaka till den gamla ----------------------------------

ANSWERS=false
for _ in $(seq 1 60); do
  if curl -fsS --max-time 2 http://127.0.0.1/healthz >/dev/null 2>&1; then
    ANSWERS=true
    break
  fi
  sleep 1
done
if [ "$ANSWERS" = false ]; then
  if [ -n "$PREVIOUS" ] && [ -d "$PREVIOUS" ]; then
    ln -sfn "$PREVIOUS" "$ROOT/current.new"
    mv -T "$ROOT/current.new" "$ROOT/current"
    systemctl restart trainmeet-hub.service
    [ "$UPDATE" = true ] && status failed "Den nya versionen svarade inte. Hubben går tillbaka till den förra." "$CURRENT_BUILD"
  fi
  echo "Hubben svarade inte efter en minut. Se: journalctl -u trainmeet-hub"
  exit 1
fi

# Keep the last few versions, for going back by hand.
ls -1dt "$ROOT"/releases/* 2>/dev/null | tail -n +$((KEEP + 1)) | while read -r OLD; do
  [ "$OLD" = "$TARGET" ] || rm -rf "$OLD"
done
[ "$UPDATE" = true ] && status done "Hubben kör version $BUILD" "$BUILD"
echo "TrainMeet Hub $BUILD är igång: http://$(hostname).local/"
