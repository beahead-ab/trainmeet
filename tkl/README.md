# TrainMeet TKL

TKL är stationens eget ställverk: en liten server i `tkl/` och webbappen i `apps/tkl`. Hur TKL startas och provas står i repots README under *TKL på egen dator*. Här står det som gäller TKL särskilt.

## TKL i molnet

TKL i molnet (`TKL_MODE=cloud` med `TKL_ID_ISSUER` och `TKL_KONTO=on`) har inget eget lager (TKL5, TKLMOLN-05, TKLMOLN-07). Stationen hör till kontot i TrainMeet ID och ligger som stationspaket i Hubbens Synk, i molnhubben (`TKL_MOLNHUBB`, annars den första i `TKL_HUBBAR`).

- **Inloggningen** kommer i stället för första start och PIN: en inloggning för allt (TKLMOLN-10). *Lås* låser som förut, och man låser upp genom att logga in igen.
- **Dina stationer** visar kontots stationspaket i Synk, med version och när det sparades. *Öppna* läser in den senaste versionen, utsidan och insidan, som webbläsarens arbetskopia. *Ny station* sparar version 1 i Synk direkt.
- **Spara i molnet**, i raden överst, sparar arbetskopian som nästa version. Har någon sparat en nyare version sedan, på en annan dator eller i en annan flik, nekas sparningen, och man väljer *Läs in den nya* eller *Spara ändå ovanpå* (H71, TKLMOLN-09). Samma station kan alltså vara öppen på två ställen.
- **Anslutning** visar träffarna i kontots klubbar enligt rollerna i ID (#78 del b) och Provbanan. En träff som molnhubben kör ansluts direkt; en träff som en Pi leder ansluts genom molnhubbens relä, `/relay/{hubb}/api/station/1`, som Pi:n svarar på genom den förbindelse den redan har öppen (TKLMOLN-03, TKLMOLN-06). TKL i molnet når bara sina egna hubbar och deras reläer.
- **PROV**: en provkörning i Provbanan är skild från den riktiga träffen i hubben, och TKL märker den PROV i sidhuvudet och i Ställverket (TKLMOLN-11).

TKL:s egen fil (`tkl.sqlite3`) håller i molnet bara det som behövs medan någon arbetar: inloggningen per webbläsare (personens id och namn och ID:s token, aldrig adressen), sessionerna, arbetskopian som en cache av en version i Synk med de ändringar som inte är sparade än och versionen den bygger på, och TKL:s driftdata för arbetskopian (ställverkets läge, anslutningen till träffen med nyckeln, de senaste ögonblicksbilderna, decken och Provas resultat). Arbetskopian försvinner vid utloggning, när en annan person loggar in i samma webbläsare, när en annan station öppnas och efter en månad utan användning. Inget som ägaren behöver finns bara där.

LocoNet, nivå 3, finns bara i en lokal TKL (TKLMOLN-08). En lokal TKL har kvar sin egen station, PIN och *Spara i molnet* under Inställningar, och kan köra samtidigt (TKLMOLN-04). Utan `TKL_ID_ISSUER`, eller utan `TKL_KONTO=on`, har TKL i molnet en station per webbläsare, som före #88. Testmiljön slår på `TKL_KONTO` när TrainMeet ID går att nå där, så att ingen blir utelåst medan ID:s adress och mejlnyckel saknas.

## Ladda upp ritning

I Studio › Rita är *Ladda upp ritning* den andra vägen in (STUDIO-01, STUDIO-03). Ägaren väljer stationens signalplan, panelritning eller spårplan som PDF, SVG eller bild, ser priset, läser den och svarar på frågorna, teckenförklaringen först. TKL:s server skickar ritningen till TrainMeet CAD:s bildkedja med personens egen token från TrainMeet ID (CAD6), och Studio gör ett förslag av CAD:s ritningsavläsning: Ritas utkast med allt gult och panelen som motorn lägger ut. *Använd ritningen* väntar tills ägaren har bekräftat förslaget, en sak i taget eller med *Bekräfta förslaget* (TKL27).

Vägen in kräver `TKL_CAD`, CAD:s adress, och inloggning med TrainMeet ID. Utan dem är den grå och säger varför, och Rita fungerar som vanligt: en lokal TKL utan internet kan bara Rita. Webbläsarprovet `apps/tkl/e2e/ladda-upp.mjs` kör en låtsad ID och en låtsad CAD själv:

```
PROV_TKL=http://127.0.0.1:8096 PROV_LATSAS=8097 CHROME_PATH=/usr/bin/google-chrome \
  node apps/tkl/e2e/ladda-upp.mjs
```

med TKL startad med `TKL_ID_ISSUER=http://127.0.0.1:8097/realms/trainmeet`, `TKL_PUBLIC_URL=http://127.0.0.1:8096` och `TKL_CAD=http://127.0.0.1:8097`.

## Från CAD

Den tredje vägen in (STUDIO-01, STUDIO-03, #89 del d2) går till samma TrainMeet CAD på samma sätt. *Från CAD* listar personens anläggningar och egna godkända moduler, och *Gör förslaget i Rita* gör Ritas utkast av spårgrafen CAD skickar (tkl/studio/fran_cad.py): spåren med sin verkliga form, så att stationen får skalet Foto, växlarna, ett spår vid en fri gavel som linjeutfart och ett som slutar i en modul som stoppbock, allt gult tills ägaren bekräftar det. CAD skapar aldrig en station (CAD-15): när ägaren använder ritningen säger TKL till CAD vilken station som använder anläggningen, och CAD visar den under *Används i*.

*Läs in igen* lägger CAD:s nya spårgraf över det stationen har, efter CAD:s id, som aldrig byts (CAD-20), och visar skillnaden: nya spår, borta och flyttade, gula igen. Ägarens signaler, blockstreck, växelnummer, utfartsnamn och stationsspår på spår med samma id står kvar; det som hängde på ett spår som är borta följer inte med och står i listan. Webbläsarprovet ovan kör Från CAD efter Ladda upp ritning, med en syntetisk anläggning som CAD:s egen kod gör (`python -m cad.assembly_example`).

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

### Fjärrtågklarerarens Stream Deck

Fjärrbilden har en ruta **Stream Deck** som i Ställverket. Decket har rollen Fjärrtågklareraren och läget Fjärr (SD37): en sida per station man styr, en knapp per tågväg i stationens fjärrkatalog, Erbjudande, Avbryt, klockan, ▶ och Läge. Ett tryck väljer en tågväg och den blinkar; ett tryck till skickar den. Knappen blir gul när vägen väntar på stationen, grön när stationens ställverk har låst den, och röd med skälet i tre sekunder vid ett nej. Håll in en väg man lagt för att ta bort den. Erbjudande tar emot en station med ett tryck och avböjer med ett håll. Ett fjärrställverks deck har alltid den rollen, också över USB och med WebHID; i en stations TKL väljs rollen under Studio › Stream Deck › Deck.

### Delarna när stationen fjärrstyrs

En station med delställverk skickar delarnas begäran och listan Klara att skicka vidare till den som fjärrstyr (FR50, FR51). Begäran står under *Väntar på dig* med Godkänn och Neka, och listan under *Klara att skicka* per station, i planens ordning, med ▲ ▼ och Skickat. Stationens eget ställverk gör det precis som tågklarerarens svar i rutan. Medan stationen fjärrstyrs visar stationens egen ruta bara, och säger varför.

### Webbläsarprovet

`apps/tkl/e2e/fjarr.mjs` provar fjärrstyrningen mot en hubb med Provbanan, en riktig station och TKL som fjärrställverk. Station A är Åsen med referensstationen Gårdsjö, som väljer sin fjärrkatalog i Studio och lämnar över i sitt eget Ställverk. Provet går igenom erbjudande, Ta emot, en tågväg som låses och blir grön, en väg som krockar och nekas med stationens skäl utan att bilden ändras, Ta bort, Tåg och klarering, en tågväg från fjärrtågklarerarens Stream Deck, och att stationen tas tillbaka. Sist byter A till Charlottendal: Rangerbangårdens begäran godkänns hos fjärrställverket, och ett tåg i Klara att skicka skickas därifrån.

```
PROV_HUBB=http://127.0.0.1:8080 PROV_TKL_STATION=http://127.0.0.1:8095 \
  PROV_TKL_FJARR=http://127.0.0.1:8093 PROV_TKL_GRANNE=http://127.0.0.1:8094 \
  CHROME_PATH=/usr/bin/google-chrome node apps/tkl/e2e/fjarr.mjs
```

Med `PROV_TKL_GRANNE`, en tredje nystartad TKL, provas också grannen: Norrbys egen TKL får fliken Fjärr när Åsen erbjuds den, tar emot och lägger en tågväg med samma fjärrbild (FR3).

Hubben kör Provbanans fasta utsida för Åsen. Dess fjärrkatalog och översikt har Gårdsjös id:n, så vägarna fjärrställverket begär är desamma som stationens egna.

## Fjärrstyrning, stationens sida

I Studio › Inställningar › Fjärrstyrning väljer ägaren vilka av stationens tågvägar in och ut som får begäras från fjärr, ställer in stationsautomaterna (A3, A2, A1, AN och AU, och lokalfrigivningen) och säger vem som får ta emot stationen. Valet sparas med stationsmodellen och följer med nästa version av utsidan, med en översikt för fjärrbilden. En station på nivå 0 har ingen fjärrkatalog.

I Ställverket visar en rad driftformen: Bemannad, Erbjuden, Fjärrstyrs från …, Kontakt saknas eller Automatik, med Lämna till … och Ta tillbaka. Medan stationen fjärrstyrs lägger dess egen panel inget, utom i ett lokalt område som den som fjärrstyr har gett. TKL svarar själv på tågvägarna som begärs från fjärr, kopplar automaterna och rapporterar läget till Hubben några gånger i minuten, så länge den är ansluten.
