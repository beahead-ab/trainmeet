# TrainMeet TKL

TKL är stationens eget ställverk: en liten server i `tkl/` och webbappen i `apps/tkl`. Hur TKL startas och provas står i repots README under *TKL på egen dator*. Här står det som gäller TKL särskilt.

## Stream Deck över USB

En lokal TKL sköter sina Stream Deck själv över USB (SD50). Decket fungerar då utan att någon flik är öppen, och i alla webbläsare. TKL letar efter deck var tredje sekund, så ett deck kan kopplas in och ur när som helst. Varje deck känns igen på sitt serienummer och får förvalet för sin modell. I Ställverket står det *Decket sköts av TKL över USB* i rutan Stream Deck.

TKL i molnet öppnar aldrig USB. Där kopplas ett deck in i Chrome eller Edge med knappen *Anslut Stream Deck* i rutan Stream Deck (WebHID). Bilderna på knapparna ritas av TKL i båda fallen, så decket ser likadant ut.

Ingen modell är provad med ett riktigt deck än, så alla står som *Inte provad* (SD58). Stäng Elgatos eget program om det är igång; det håller annars decket.

### Från källkoden

```
npm ci && npm run build -w apps/tkl
uv sync
uv run python -m tkl
```

Öppna http://localhost:8090, lås upp och koppla in decket.

TKL pratar med decket genom systemets libhidapi:

- **Linux** (också Raspberry Pi OS): `sudo apt install libhidapi-libusb0`, och regeln för Elgato nedan.
- **macOS**: ingen regel behövs, men libhidapi kommer från Homebrew: `brew install hidapi`.
- **Windows**: `hidapi.dll` från hidapi-projektet bredvid Python eller i `PATH`.

Saknas libhidapi går TKL ändå, och skriver en gång i loggen att USB inte nås.

### Regeln för Elgato på Linux

Utan regeln får bara root öppna decket. Regeln ger den som är inloggad och gruppen `plugdev` rätt till Elgatos deck (tillverkare 0fd9):

```
sudo tee /etc/udev/rules.d/70-streamdeck.rules > /dev/null <<'EOF'
SUBSYSTEM=="usb", ATTRS{idVendor}=="0fd9", MODE="0660", GROUP="plugdev", TAG+="uaccess"
KERNEL=="hidraw*", ATTRS{idVendor}=="0fd9", MODE="0660", GROUP="plugdev", TAG+="uaccess"
EOF
sudo udevadm control --reload-rules && sudo udevadm trigger
```

Kör TKL som en tjänst utan inloggning, till exempel på en Pi, läggs tjänstens användare i gruppen: `sudo usermod -aG plugdev <användare>`. Koppla sedan ur decket och in igen.

### I Docker

Bilden har libhidapi. Kör den lokalt med `TKL_MODE=local` och ge containern USB-bussen. Bilden kör TKL som en egen användare, så den får också gruppen `plugdev` från regeln ovan:

```
docker build -f tkl/Dockerfile -t trainmeet-tkl .
docker run -d --name tkl -p 8090:8090 -e TKL_MODE=local -v tkl-data:/data \
  --device /dev/bus/usb --group-add "$(getent group plugdev | cut -d: -f3)" \
  trainmeet-tkl
```

`--device` ger bara de deck som är inkopplade när containern startar. Ska deck kunna kopplas in efteråt, ge hela bussen och rätten till USB-enheterna i stället:

```
docker run -d --name tkl -p 8090:8090 -e TKL_MODE=local -v tkl-data:/data \
  -v /dev/bus/usb:/dev/bus/usb --device-cgroup-rule='c 189:* rmw' \
  --group-add "$(getent group plugdev | cut -d: -f3)" \
  trainmeet-tkl
```

På macOS och Windows når Docker inte USB på det här sättet; där körs TKL från källkoden.
