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

## Fjärrstyrning

TKL kan startas som **Fjärrställverk (ingen egen station)** för rollen fjärrtågklarerare (FR1). Vid första start väljer man det bredvid stationens ställverk och skriver ett namn, planens fjärrområde eller driftplatserna i ordning längs linjen, och en PIN. Under Inställningar ansluter fjärrställverket till hubben; där kan man också välja bland planens fjärrområden. Trafikledningen godkänner det i Klienter för varje driftplats, och det ger bara rätt att ta emot (FR4).

Sidorna är **Fjärrbild** och **Tåg och klarering**. Fjärrbilden ritar fjärrområdet och grannarna i skalet 95, bara det stationerna rapporterar (FR13, FR31–FR38, FR47, FR48). En station som erbjuds står under *Väntar på dig* med Ta emot och Avböj. En tågväg väljs med ett tryck på startsignalen och ett på målet; den blinkar tills *Lägg tågvägen* skickar den, och stationens ställverk låser den eller säger nej med skäl. *Ta bort* tar bort en väg man lagt. Under Tåg och klarering klarerar man för hela stationen, en flik per station (FR17).

Fjärrbild på en skärm och Tåg och klarering på en annan, som skärm 1 och 3 i specen: öppna TKL med `?skarm=3` på den andra skärmen och välj Tåg och klarering. Skärm 2, stationens egen bild i detalj, finns bara i stationens TKL: insidan lämnar aldrig stationen. Varje skärm minns sitt val, *Allt på en skärm* eller *Bara fjärrbilden*.

En stations egen TKL får fliken **Fjärr** med samma sidor när den styr en granne eller en granne erbjuds den (FR3).

### Webbläsarprovet

`apps/tkl/e2e/fjarr.mjs` provar fjärrstyrningen mot en hubb med Provbanan och TKL som fjärrställverk: erbjudande, Ta emot, en tågväg som låses och blir grön, en väg som krockar och nekas med skäl utan att bilden ändras, Ta bort, Tåg och klarering, och att stationen tas tillbaka.

```
PROV_HUBB=http://127.0.0.1:8080 PROV_TKL_FJARR=http://127.0.0.1:8093 PROV_TKL_GRANNE=http://127.0.0.1:8094 \
  CHROME_PATH=/usr/bin/google-chrome node apps/tkl/e2e/fjarr.mjs
```

Med `PROV_TKL_GRANNE`, en andra nystartad TKL, provas också grannen: Norrbys egen TKL får fliken Fjärr när Åsen erbjuds den, tar emot och lägger en tågväg med samma fjärrbild (FR3).

Station A (Åsen i Provbanan) är tills vidare ett låtsat ställverk i provet, `stationA` i skriptet: en klient på stationsprotokollet som TKL på nivå 2, med en fjärrkatalog och en översikt i Gårdsjös form, som svarar på `route.request` som stationen ska. När Studio tar fram fjärrkatalogen och översikten och ställverket svarar på begärda vägar (#36 del b) byts det mot en andra TKL med Gårdsjö som stationsmodell, som erbjuder och tar tillbaka stationen i sitt eget Ställverk.
