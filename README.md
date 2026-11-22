# TrainMeet

TrainMeet är programvaran för modelltågsträffar med trafikspel: stationer som klarerar tåg mellan sig, en gemensam träffklocka, tidtabell, handboxar (TMBox) och ställverk (TKL).

Det här repot är nästa generation. All ny kod ligger här, med en mapp per del. Den ersätter TrainMeet Server, TrainMeet Cloud och de gamla TKL-repona, som ligger kvar som referens tills den nya generationen är klar och provad.

## Delarna

| Mapp | Del | Körs |
| --- | --- | --- |
| `contracts/` | Kontrakten: paketformatet, terminal- och stationsprotokollet, förarnas och driftens API och synken mellan hubbar. De andra delarna pratar bara med varandra genom dem. | – |
| `core/`, `drift/`, `planering/`, `synk/`, `integrationer/` | TrainMeet Hub, kärnan som kör träffen. Det enda man installerar. | Raspberry Pi på träffen och i molnet |
| `hub/` | Hubbens startprogram: drar igång delarna, första start och inloggning, API:erna och webbapparna under `apps/` | Raspberry Pi på träffen och i molnet |
| `id/` | TrainMeet ID, en inloggning för allt | I molnet |
| `tkl/` | TrainMeet TKL, ställverket och Studio | Stationens dator eller i molnet |
| `cad/` | TrainMeet CAD, modulbiblioteket: moduler med versioner, gavlar och gavelprofiler, och spårgrafen till Studio. En egen tjänst med egen PostgreSQL; använder bara `contracts/` | I molnet |
| `catalog/` | TrainMeet Catalog: fordonen, taggarna och resan till träffen. En egen tjänst med egen PostgreSQL; använder bara `contracts/` | I molnet |
| `apps/` | Webbapparna i TypeScript, React och Vite: designsystemet (`apps/design`), Catalogs (`apps/catalog`), CAD:s (`apps/cad`), ID:s (`apps/id`) och Hubbens (H62): trafikledningen (`apps/trafikledning`), Planering (`apps/planering`), träffens skärmar (`apps/skarmar`), TMBox web (`apps/tmbox-webb`) och Lokföraren i telefonen (`apps/lokforaren`), med Hubbens sidhuvud i `apps/hubben` | – |

Mapparna kommer till i den ordning delarna byggs. Först kommer Grunden (kontrakten, de automatiska testerna och testmiljön), sedan Drift.

TMBox-firmwaren och TMBox-appen för iPhone utvecklas i sina egna repon. TrainMeet Catalog skrivs om som en egen del i det här repot, `catalog/` (beslut C14 och C16 i specen); gamla TrainCatalog ligger kvar i sitt eget repo som facit.

## Arbetssätt

Allt går via pull requests mot `main`, och testerna körs på varje PR. Specen, TrainMeet Platform, bestämmer hur delarna ska fungera.

Delarna pratar bara med varandra genom `contracts/`. Det kontrolleras av testerna: en del som importerar en annan dels kod gör testerna röda.

### Köra på egen dator

Det behövs bara [uv](https://docs.astral.sh/uv/). Det hämtar rätt Python (3.12) själv.

```sh
uv sync                                  # installerar allt
uv run pytest -n 4 --dist loadfile       # testerna, i fyra processer som "Tester"
uv run ruff check . && uv run mypy       # kodstil och typer
uv run uvicorn hub.app:app --reload      # hubben på http://127.0.0.1:8000
```

Hubbens bild byggs med `docker build -f hub/Dockerfile -t trainmeet-hub .` från repots rot.

### Catalog på egen dator

Catalog behöver en PostgreSQL och [Node 22](https://nodejs.org/) för webbappen.

```sh
npm ci && npm run build -w apps/catalog       # webbappen, till apps/catalog/dist
npm run build -w apps/skarmar                  # Hubbens skärmar, som hubben serverar på /skarm
npm run build -w apps/tmbox-webb               # TMBox web, som hubben serverar på /box och /provbanan/box
npm run build -w apps/trafikledning            # startsidan, Provbanan, Inställningar och Drift (/, /drift)
npm run build -w apps/planering                # Planering, på /planering
npm run build -w apps/lokforaren               # Lokföraren, där QR-koden leder: /lokforaren
CATALOG_DATABASE_URL=postgresql:///catalog CATALOG_MIGRATE=auto CATALOG_TRIAL_LOGIN=on \
  uv run uvicorn catalog.app:app --port 8001  # Catalog på http://127.0.0.1:8001
npm run dev -w apps/catalog                   # eller webbappen med omladdning, mot port 8001
CATALOG_TEST_DATABASE_URL=postgresql:///postgres uv run pytest catalog
```

Catalogs bild byggs med `docker build -f catalog/Dockerfile -t trainmeet-catalog .`. Webbappens typer och tester körs när bilden byggs.

Webbläsarprovet (CAT-154) går igenom Lägg till med foto och Lägg till flera i Chrome, mot Catalog med sin riktiga kö och databas och en låtsad TrainMeet ID och AI (`catalog/prov_webblasare.py`). Inget anropar en AI-leverantör. Kontrollen *Catalogs bild* kör det med en egen PostgreSQL.

```sh
npm run build -w apps/catalog
uv run python -m catalog.prov_webblasare --databas postgresql://postgres@127.0.0.1:5432/postgres --ny   # port 8090, en egen databas
CHROME_PATH=/usr/bin/google-chrome node apps/catalog/e2e/omgang.mjs   # PROV_BILDER=<mapp> sparar skärmbilderna
```

Med `CATALOG_ID_ISSUER`, `CATALOG_ID_SECRET` och `CATALOG_PUBLIC_URL` loggar Catalog in med TrainMeet ID i stället för provinloggningen (#66), och med `CATALOG_ID_API` frågar Catalog ID:s API om delade vagnparker vid varje anrop (#49); se `catalog/settings.py`. Mot ett ID på egen dator, som nedan: `CATALOG_ID_ISSUER=http://127.0.0.1:8080/realms/trainmeet CATALOG_PUBLIC_URL=http://localhost:8001` och klienthemligheten som ID startades med.

Fordonens bilder sparas på egen dator i `.catalog/pictures` (`CATALOG_PICTURES_DIR`) och hämtas genom Catalog med signerade länkar. Med `CATALOG_PICTURES_S3_ENDPOINT`, `CATALOG_PICTURES_S3_BUCKET`, `CATALOG_PICTURES_S3_REGION` och `CATALOG_PICTURES_S3_KEY_FILE` ligger de i stället privat i Object Storage (CAT-130); se `catalog/settings.py`. I bilden behövs Object Storage eller en skrivbar `CATALOG_PICTURES_DIR`.

Friläggningen (CAT-127–CAT-129) körs i Catalog med modellen U2NetP, som `catalog/Dockerfile` hämtar och kontrollerar med SHA-256 när bilden byggs. På egen dator saknas modellen, och då går bara bakgrunden Original att välja. För att prova den: hämta `https://github.com/danielgatis/rembg/releases/download/v0.0.0/u2netp.onnx` utanför repot och peka ut den med `CATALOG_BACKGROUND_MODEL`; samma variabel låter testerna prova den riktiga modellen.

### CAD på egen dator

TrainMeet CAD är modulbiblioteket (#89): moduler ur bara mått, raka, kurvor och trapetser, med gavlar, gavelprofiler, synlighet, versioner och historik, och Ritningen där spårplanen ritas, med växelinspektören, Att kolla, utjämning och Lås mått (del b, `cad/editor.py`). Tjänsten i `cad/` har en egen PostgreSQL och webbappen i `apps/cad`, och använder bara `contracts/` (`contracts/cad.py`, `contracts/cad.openapi.json`).

```sh
npm ci && npm run build -w apps/cad            # webbappen, till apps/cad/dist
CAD_DATABASE_URL=postgresql:///cad CAD_MIGRATE=auto CAD_TRIAL_LOGIN=on \
  uv run uvicorn cad.app:app --port 8004       # CAD på http://127.0.0.1:8004
npm run dev -w apps/cad                        # eller webbappen med omladdning, mot port 8004
CAD_TEST_DATABASE_URL=postgresql:///postgres uv run pytest cad
```

Med `CAD_ID_ISSUER`, `CAD_ID_SECRET` och `CAD_PUBLIC_URL` loggar CAD in med TrainMeet ID som klienten `cad`, och med `CAD_ID_API` frågar CAD ID:s API om klubbarna och rollerna vid varje anrop; se `cad/settings.py`. Webbläsarprovet går igenom provinloggningen, en rak modul, en kurvmodul, Godkänn och biblioteket i Chrome, och sedan Ritningen med ett spår, en växel, Att kolla och Lås mått på en MMM-trapets (`apps/cad/e2e/ritningen.mjs`, som `bibliotek.mjs` kör), mot en låtsad TrainMeet ID (`cad/prov_webblasare.py`):

```sh
uv run python -m cad.prov_webblasare --databas postgresql://postgres@127.0.0.1:5432/postgres --ny   # port 8095
CHROME_PATH=/usr/bin/google-chrome node apps/cad/e2e/bibliotek.mjs   # PROV_BILDER=<mapp> sparar skärmbilderna
```

Bilden byggs med `docker build -f cad/Dockerfile -t trainmeet-cad .`; webbappens typer och tester körs när bilden byggs.

### TKL på egen dator

TrainMeet TKL är stationens eget program (KLAR-22). På nivå 0 är det bara klarering: spår och utfarter som en lista i Studio, och ställverket med Tåg · Klarering · Händelser mot hubbens stationsprotokoll. TKL har en egen liten server som håller stationen, PIN-koden och nyckeln från godkännandet, och en webbapp i `apps/tkl`. Servern använder bara `contracts/`.

```sh
npm ci && npm run build -w apps/tkl     # webbappen, till apps/tkl/dist
uv run python -m tkl                    # TKL på http://localhost:8090, nås också från plattor på samma nät
npm run dev -w apps/tkl                 # eller webbappen med omladdning, mot port 8090
```

På träffens nät hittar TKL hubben själv med DNS-SD (`_tmbox._tcp`, samma som boxarna) och ansluter utan kod. Över internet behövs hubbens adress och koden från trafikledningen. `TKL_DATA_DIR` säger var stationen sparas (förval `~/.trainmeet-tkl`), `TKL_PORT` vilken port den svarar på. I molnet körs TKL med `TKL_MODE=cloud` och bara de hubbar som står i `TKL_HUBBAR`. Med TrainMeet ID (`TKL_ID_ISSUER`) hör stationen till kontot och ligger i Hubbens Synk; se *TKL i molnet* i `tkl/README.md`. Utan ID har varje webbläsare en egen station, som före #88. Bilden byggs med `docker build -f tkl/Dockerfile -t trainmeet-tkl .`; webbappens typer och tester körs när bilden byggs.

### TrainMeet ID på egen dator

TrainMeet ID är [Keycloak](https://www.keycloak.org/) med ett eget tillägg i `id/email-code`: inloggning och nytt konto med en kod till e-posten, utan lösenord, passkey som tillval, och inloggningssidorna i TrainMeets utseende på svenska och engelska (#66). Realmen ligger i `id/realm/trainmeet.json` och läses in första gången Keycloak startar; den har inga hemligheter, bara platshållare som fylls från miljön. Lösenordet till mejlservern läses ur Keycloaks valv, en fil.

Keycloak läser realmfilen bara när realmen inte finns. Ändras filen läggs därför också en numrerad uppdatering i `id/email-code/src/main/java/app/trainmeet/id/RealmUpdates.java`, och numret i filens `trainmeetVersion` höjs. Uppdateringen körs en gång när Keycloak startar mot en realm som redan finns, som i testmiljön. Testerna i `id/tests` ser till att filen och uppdateringen säger samma sak.

```sh
docker build -f id/Dockerfile -t trainmeet-id .   # tilläggets tester körs när bilden byggs
uvx --from aiosmtpd python id/postlada.py /tmp/mejl.txt 2525   # en låtsad mejlserver
uv run python -m id.prov_inloggning http://127.0.0.1:8080 /tmp/mejl.txt <klienthemlighet> http://localhost:8001
```

Kontrollen *ID:s bild* startar bilden med en PostgreSQL och den låtsade mejlservern och kör provet av inloggningen; se jobbet `id` i `.github/workflows/tester.yml` för vilka inställningar Keycloak behöver.

Bredvid Keycloak, på samma adress, finns ID:s eget API (#67): klubbarna och medlemmarna, rollerna per resurs och inbjudningarna, och frågan apparna ställer om vilken roll en person har (KONTO-34). Kontraktet står i `contracts/id.py` och `contracts/id.openapi.json`. Det körs med `uv run uvicorn id.app:app --port 8002` och inställningarna i `id/settings.py`, med en egen databas; bilden byggs med `docker build -f id/api.Dockerfile -t trainmeet-idapi .`. ID:s webbapp ligger i `apps/id` (React, med flikarna Konto, Klubbar, Träffar och Tokens) och byggs in i samma bild: `npm run build -w apps/id`, eller `npm run dev -w apps/id` mot ett API på port 8002. Testerna behöver en PostgreSQL i `ID_TEST_DATABASE_URL` eller `CATALOG_TEST_DATABASE_URL`.

## Testmiljön

https://test.hub.trainmeet.app, https://test.tkl.trainmeet.app, https://test.catalog.trainmeet.app, https://test.cad.trainmeet.app och https://test.id.trainmeet.app visar alltid det som ligger på `main`. När en PR slås ihop och kontrollerna är gröna lägger jobbet *Testmiljön* ut hubben av sig själv. Det tar några minuter.

[Öppna Provbanan](https://test.hub.trainmeet.app/provbanan) och starta en provkörning. Prova tåg 101 från Norrby för begärd klarering och tåg 102 från Sjövik för direktklarering. Du kan starta och stoppa klockan, svara från nästa driftplats och följa tåget till ankomst. Provkörningen är separat för varje webbläsare och sparas i ett dygn.

Hubben kör också en riktig träff (steg 3). Den som först öppnade testhubben valde dess namn och PIN-kod och är lokal administratör. Inloggad startar man träffen under [Nu](https://test.hub.trainmeet.app/drift), ansluter boxar, TKL och skärmar med koden under *Anslut* och tilldelar dem under *Klienter*. Utan inloggning kan man titta på Nu. Träffen och hubbens inställningar ligger i egna filer bredvid Provbanans, och står kvar när hubben startas om; klockan står då still tills någon startar den.

[Catalog](https://test.catalog.trainmeet.app) loggar in med TrainMeet ID, med en kod till e-posten och samma konto som i de andra apparna (#66). Tills ID kan skicka sina koder har Catalog en provinloggning i stället (C21): välj ett av provkontona under *Logga in*. Under *Fordon* lägger man in fordon för hand, söker och flyttar dem mellan platserna, och lånar ut dem (#50). Under *Blippa* skapar man en simulerad tagg och kopplar den till ett fordon; taggarna i testmiljön har adressen test.catalog.trainmeet.app/t/, och riktiga taggar får trainmeet.app/t/ (#54). Med Chrome på en Android-telefon blippar man riktiga NFC-taggar under *Blippa*, och Catalog skriver adressen på taggen när den kopplas. Provkontona är gemensamma för alla som provar, och allt där är testdata. Catalog har en egen PostgreSQL i en container på samma server. Före varje migrering och varje natt tas en krypterad säkerhetskopia, som provas genom att läsas in i en tom databas (CAT-39); de 14 senaste av varje slag ligger i `/srv/trainmeet/catalog-backup`. Lösenordet till databasen och nyckeln till säkerhetskopiorna skapas av `deploy/testmiljo.py` och ligger i Scaleways Secret Manager.

TrainMeet ID ligger på samma server med en egen PostgreSQL, där ID:s API har databasen `idapi` bredvid Keycloaks. Lösenorden till databasen och administratören och Catalogs klienthemlighet skapas av `deploy/testmiljo.py` och ligger i Scaleways Secret Manager. Mejlen med koderna skickas med Scaleways Transactional Email från konto@trainmeet.se; nyckeln ligger i GitHub som `TEM_SECRET_KEY` och skrivs till ID:s valv på servern. Utan nyckeln startar ID ändå, men inga koder kommer fram, och Catalog har kvar provinloggningen. Med nyckeln loggar Catalog in med ID. Administrationen av Keycloak går inte att nå utifrån.

[TKL](https://test.tkl.trainmeet.app) är TKL i molnet (#76, #88). Logga in med TrainMeet ID; ingen första start och ingen PIN. Under *Dina stationer* skapar du en station, som sparas i testhubbens Synk direkt, eller öppnar en du redan har. Skriv spår och utfarter i *Studio* och tryck *Spara i molnet* i raden överst. Under *Inställningar › Anslutning* står träffarna i dina klubbar enligt TrainMeet ID, var och en direkt till testhubben eller genom dess relä till Låtsas-Pi:n när den leder träffen, och Provbanan med koden från din provkörning, märkt PROV. Godkänn TKL under klienterna; sedan klarerar TKL tåg mot de andra driftplatserna. Stationen hör till kontot: öppna den i en annan webbläsare så finns den där. Har den ändrats någon annanstans sedan du öppnade den får du välja *Läs in den nya* eller *Spara ändå ovanpå*.

[CAD](https://test.cad.trainmeet.app) är modulbiblioteket (#89). Logga in med TrainMeet ID, välj *Ny modul* och *Bara mått*, och gör en rak modul eller en kurvmodul: snöret och pilhöjden ger radien och vinkeln. Modulens sida visar gavlarna, vem som ser modulen och historiken, och *Godkänn*. Under *Gavelprofiler* finns normerna per skala och de egna gavlarna. CAD har en egen PostgreSQL i en container, som säkerhetskopieras före varje migrering och varje natt, som Catalogs; de 14 senaste av varje slag ligger i `/srv/trainmeet/cad-backup`. Lösenordet till CAD:s databas, nyckeln till säkerhetskopiorna och hemligheten som CAD loggar in i ID med (klienten `cad`) skapas av `deploy/testmiljo.py` och ligger i Scaleways Secret Manager, som Catalogs; ingen behöver lägga in något för hand.

Under [Planering](https://test.hub.trainmeet.app/planering) skapar man en träff, lägger till Tellurians planeringsfil (JSON, nivå 4), läser importrapporten, rättar telefon och klareringsläge under *Data* och publicerar en version under *Versioner* (steg 4a). Drift kör sedan versionen: välj den under *Byt träff*. Värnamos planeringsfil finns som testdata i `integrationer/tests/fixtures/varnamo.json.gz`.

- **Var:** en server hos Scaleway i Amsterdam, zon `nl-ams-1` (DEV1-S, Ubuntu 24.04), med en fast IPv4-adress. Caddy framför hubben hämtar certifikatet från Let's Encrypt. Ungefär 9–11 € i månaden före moms.
- **Hur:** `deploy/testmiljo.py` skapar servern, adressen, säkerhetsgruppen och SSH-nycklarna första gången och återanvänder dem sedan. Nycklarna ligger i Scaleways Secret Manager, aldrig i repot. Filerna som hamnar på servern ligger i `deploy/testmiljo/`.
- **Inställningar** (valfria, under *Settings → Secrets and variables → Actions → Variables*): `TESTHUB_DOMAIN` (förval test.hub.trainmeet.app), `TESTCATALOG_DOMAIN` (förval test.catalog.trainmeet.app), `TESTID_DOMAIN` (förval test.id.trainmeet.app), `TESTPI_DOMAIN` (förval test.pi.trainmeet.app), `TESTTKL_DOMAIN` (förval test.tkl.trainmeet.app), `TESTCAD_DOMAIN` (förval test.cad.trainmeet.app), `TESTTAGS_DOMAIN` (förval trainmeet.app, taggarnas adress) och `TESTMILJO_TYPE` (förval DEV1-S; STARDUST1-S är billigast).
- **Kvoten:** Scaleway låter ett konto skapa servrar först när betalsättet är verifierat, och fler typer när identiteten är verifierad. Säger jobbet att kvoten är slut, listar det vilka servertyper kontot får skapa (om applikationen har behörigheten `IAMReadOnly`), annars se *Organization → Quotas* i Scaleways konsol.

### Engångsuppsättningen

1. **En API-nyckel hos Scaleway**, bara för det här repot:
   - I Scaleways konsol: *IAM → Applications → Create application*, med namnet `trainmeet-github`.
   - *IAM → Policies → Create policy* för applikationen, med tillgång till projektet `trainmeet` och behörigheterna `InstancesFullAccess` och `SecretManagerFullAccess`.
   - *IAM → API keys → Generate API key* för applikationen, med `trainmeet` som standardprojekt. Spara *Secret Key* direkt; den visas bara en gång.
2. **Fyra secrets i GitHub** (*Settings → Secrets and variables → Actions → New repository secret*): `SCW_ACCESS_KEY`, `SCW_SECRET_KEY`, `SCW_DEFAULT_PROJECT_ID` (projektets id under projektets *Settings*) och `SCW_DEFAULT_ORGANIZATION_ID` (under *Organization settings*).
3. **Kör jobbet:** *Actions → Tester → Run workflow* på `main`. Första gången skapas servern. Sammanfattningen av körningen visar serverns adress.
4. **DNS-raderna i Cloudflare**, zonen `trainmeet.app`: typ **A**, namn **test.hub**, innehåll serverns adress, proxy **av** (grått moln). För Catalog typ **CNAME**, namn **test.catalog**, mål **test.hub.trainmeet.app**, proxy **av**, och likadant för ID med namnet **test.id** och för CAD med namnet **test.cad**. För taggarnas adress (C38), i zonen `trainmeet.app`: typ **CNAME**, namn **@**, mål **test.hub.trainmeet.app**, proxy **av**. Då går trainmeet.app/t/ vidare till Catalog i testmiljön, och nya taggar får den adressen från nästa utläggning. Kör jobbet en gång till.
5. **Nyckeln till mejlen** (#66): i Scaleways konsol *IAM → Applications → Create application* med namnet `trainmeet-mejl`, en policy med behörigheten `TransactionalEmailFullAccess` i projektet `trainmeet`, och en API-nyckel för applikationen. Lägg *Secret Key* som secret `TEM_SECRET_KEY` i GitHub. Domänen trainmeet.se ska vara verifierad under *Transactional Email*. Då hämtar Caddy certifikaten, och sidorna är ute.
6. **Nyckeln till TrainMeets AI** (#79, TK14, CAD19), när Casper har sagt ja: en egen IAM-användare hos AWS med en åtkomstnyckel och en policy som bara tillåter `bedrock:InvokeModel` på EU-profilerna `eu.anthropic.claude-sonnet-5-5` (bildläsningen) och `eu.anthropic.claude-opus-5-5` (CAD:s svåra följdfrågor) i `eu-north-1`, och på modellerna `anthropic.claude-sonnet-5-5` och `anthropic.claude-opus-5-5` i de EU-regioner som profilen skickar anropen vidare till: `eu-central-1`, `eu-north-1`, `eu-south-1`, `eu-south-2`, `eu-west-1` och `eu-west-3`. Saknas en region i policyn nekas de anrop som hamnar där. Lägg nyckelns id som secret `BEDROCK_KEY_ID` och hemligheten som `BEDROCK_SECRET_KEY` i GitHub; jobbet skriver dem till ID:s valv. Utan nyckeln säger mätaren att TrainMeets AI inte är inkopplad.

Utan nyckeln hoppar jobbet över utläggningen och säger det, så att `main` ändå blir grön.

## Licens

GNU Affero General Public License, version 3 (AGPL-3.0). Se [LICENSE](LICENSE).

© 2026 Beahead AB
