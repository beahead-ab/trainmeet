# TrainMeet

TrainMeet är programvaran för modelltågsträffar med trafikspel: stationer som klarerar tåg mellan sig, en gemensam träffklocka, tidtabell, handboxar (TMBox) och ställverk (TKL).

Det här repot är nästa generation. All ny kod ligger här, med en mapp per del. Den ersätter TrainMeet Server, TrainMeet Cloud och de gamla TKL-repona, som ligger kvar som referens tills den nya generationen är klar och provad.

## Delarna

| Mapp | Del | Körs |
| --- | --- | --- |
| `contracts/` | Kontrakten: paketformatet, terminal- och stationsprotokollet, förarnas och driftens API och synken mellan hubbar. De andra delarna pratar bara med varandra genom dem. | – |
| `core/`, `drift/`, `planering/`, `synk/`, `integrationer/` | TrainMeet Hub, kärnan som kör träffen. Det enda man installerar. | Raspberry Pi på träffen och i molnet |
| `hub/` | Hubbens startprogram: drar igång delarna, första start och inloggning, trafikledningens sidor (Nu, Klienter, Logg), TMBox i webbläsaren och klockskärmen | Raspberry Pi på träffen och i molnet |
| `apps/` | Trafikledningen, Lokföraren, TMBox i webbläsaren, skärmarna och Planering | Levereras av Hubben |
| `id/` | TrainMeet ID, en inloggning för allt | I molnet |
| `tkl/` | TrainMeet TKL, ställverket och Studio | Stationens dator eller i molnet |
| `cad/` | TrainMeet CAD, modulbiblioteket | I molnet |

Mapparna kommer till i den ordning delarna byggs. Först kommer Grunden (kontrakten, de automatiska testerna och testmiljön), sedan Drift.

TrainCatalog, TMBox-firmwaren och TMBox-appen för iPhone utvecklas i sina egna repon.

## Arbetssätt

Allt går via pull requests mot `main`, och testerna körs på varje PR. Specen, TrainMeet Platform, bestämmer hur delarna ska fungera.

Delarna pratar bara med varandra genom `contracts/`. Det kontrolleras av testerna: en del som importerar en annan dels kod gör testerna röda.

### Köra på egen dator

Det behövs bara [uv](https://docs.astral.sh/uv/). Det hämtar rätt Python (3.12) själv.

```sh
uv sync                                  # installerar allt
uv run pytest                            # testerna
uv run ruff check . && uv run mypy       # kodstil och typer
uv run uvicorn hub.app:app --reload      # hubben på http://127.0.0.1:8000
```

Hubbens bild byggs med `docker build -f hub/Dockerfile -t trainmeet-hub .` från repots rot.

## Testmiljön

https://test.hub.trainmeet.app visar alltid det som ligger på `main`. När en PR slås ihop och kontrollerna är gröna lägger jobbet *Testmiljön* ut hubben av sig själv. Det tar några minuter.

[Öppna Provbanan](https://test.hub.trainmeet.app/provbanan) och starta en provkörning. Prova tåg 101 från Norrby för begärd klarering och tåg 102 från Sjövik för direktklarering. Du kan starta och stoppa klockan, svara från nästa driftplats och följa tåget till ankomst. Provkörningen är separat för varje webbläsare och sparas i ett dygn.

Hubben kör också en riktig träff (steg 3). Den som först öppnade testhubben valde dess namn och PIN-kod och är lokal administratör. Inloggad startar man träffen under [Nu](https://test.hub.trainmeet.app/drift), ansluter boxar, TKL och skärmar med koden under *Anslut* och tilldelar dem under *Klienter*. Utan inloggning kan man titta på Nu. Träffen och hubbens inställningar ligger i egna filer bredvid Provbanans, och står kvar när hubben startas om; klockan står då still tills någon startar den.

Under [Planering](https://test.hub.trainmeet.app/planering) skapar man en träff, lägger till Stefans planeringsfil (JSON, nivå 4), läser importrapporten, rättar telefon och klareringsläge under *Data* och publicerar en version under *Versioner* (steg 4a). Drift kör sedan versionen: välj den under *Byt träff*. Värnamos planeringsfil finns som testdata i `integrationer/tests/fixtures/varnamo.json.gz`.

- **Var:** en server hos Scaleway i Amsterdam, zon `nl-ams-1` (DEV1-S, Ubuntu 24.04), med en fast IPv4-adress. Caddy framför hubben hämtar certifikatet från Let's Encrypt. Ungefär 9–11 € i månaden före moms.
- **Hur:** `deploy/testmiljo.py` skapar servern, adressen, säkerhetsgruppen och SSH-nycklarna första gången och återanvänder dem sedan. Nycklarna ligger i Scaleways Secret Manager, aldrig i repot. Filerna som hamnar på servern ligger i `deploy/testmiljo/`.
- **Inställningar** (valfria, under *Settings → Secrets and variables → Actions → Variables*): `TESTHUB_DOMAIN` (förval test.hub.trainmeet.app) och `TESTMILJO_TYPE` (förval DEV1-S; STARDUST1-S är billigast).
- **Kvoten:** Scaleway låter ett konto skapa servrar först när betalsättet är verifierat, och fler typer när identiteten är verifierad. Säger jobbet att kvoten är slut, listar det vilka servertyper kontot får skapa (om applikationen har behörigheten `IAMReadOnly`), annars se *Organization → Quotas* i Scaleways konsol.

### Engångsuppsättningen

1. **En API-nyckel hos Scaleway**, bara för det här repot:
   - I Scaleways konsol: *IAM → Applications → Create application*, med namnet `trainmeet-github`.
   - *IAM → Policies → Create policy* för applikationen, med tillgång till projektet `trainmeet` och behörigheterna `InstancesFullAccess` och `SecretManagerFullAccess`.
   - *IAM → API keys → Generate API key* för applikationen, med `trainmeet` som standardprojekt. Spara *Secret Key* direkt; den visas bara en gång.
2. **Fyra secrets i GitHub** (*Settings → Secrets and variables → Actions → New repository secret*): `SCW_ACCESS_KEY`, `SCW_SECRET_KEY`, `SCW_DEFAULT_PROJECT_ID` (projektets id under projektets *Settings*) och `SCW_DEFAULT_ORGANIZATION_ID` (under *Organization settings*).
3. **Kör jobbet:** *Actions → Tester → Run workflow* på `main`. Första gången skapas servern. Sammanfattningen av körningen visar serverns adress.
4. **DNS-raden i Cloudflare**, zonen `trainmeet.app`: typ **A**, namn **test.hub**, innehåll serverns adress, proxy **av** (grått moln). Kör jobbet en gång till. Då hämtar Caddy certifikatet, och sidan är ute.

Utan nyckeln hoppar jobbet över utläggningen och säger det, så att `main` ändå blir grön.

## Licens

GNU Affero General Public License, version 3 (AGPL-3.0). Se [LICENSE](LICENSE).

© 2026 Beahead AB
