# Arbetsregler för Claude i trainmeet

Gäller alla chattar som arbetar i repot: Hub, ID, TKL, CAD och Catalog.

## Specen är facit

- Specen TrainMeet Platform ligger i repot `beahead-ab/trainmeet-spec` (privat) och visas öppet på platform.trainmeet.app, utan läskod men inte för sökmotorerna (W11, 9 november).
- Besluten står i beslutsregistret, `src/data.py`. Underlagen står i `docs/`. Läs först `docs/trainmeet-stacken.md` och `docs/trainmeet-hub-definition.md`.
- Säger koden och specen olika saker: fråga Casper, eller föreslå en ändring i specen i ett PR i trainmeet-spec. Gissa aldrig.
- Byggstatusen i specen (`BUILD` i `src/data.py`, kapitlet först i specen) har fyra steg: Design, Utvecklat, Testat och Klart. Testat betyder att testerna är gröna och att Casper eller en av vännerna har provat det i testmiljön. Går något nytt att prova läggs det i `TRY` i samma fil, med adressen i testmiljön och en kort instruktion, så att vännerna kan prova det. När ett PR här flyttar en modul följer ett PR i trainmeet-spec med nytt läge, en rad under Läget och nytt datum, i samma veva.

## Casper

- Casper är produktägare och arbetar på systemnivå, inte på kodrader. Skriv till honom på svenska, kort och utan kod i chatten.
- Han är ny på git. Förklara vad han ska göra steg för steg när något behöver göras på GitHub.

## Grenar och pull requests

- En gren per uppgift och ett PR mot `main`. Ingen pushar direkt till `main`.
- Claude slår ihop sitt eget PR när båda kontrollerna är gröna och ändringen är provad (Casper, 6 november). Casper behöver inte göra något på GitHub för att en ändring ska komma ut. Sammanslagningen lägger ut hubben i testmiljön; följ jobbet "Testmiljön" och säg till Casper om det blir rött.
- Varje PR säger på svenska vad som ändras och hur det är provat.

## Kontrakten först

- `contracts/` är den enda vägen mellan delarna. Ingen del importerar en annan dels inre kod.
- Ändras ett kontrakt ändras alla som använder det i samma PR.
- Modellerna i `contracts/` är källan. JSON-schemana skapas med `uv run python -m contracts.generate` och checkas in; testerna jämför dem. Orden står i `contracts/ORDLISTA.md`, ett namn per begrepp.
- Gränserna kontrolleras av `tests/test_boundaries.py`. Hubbens fyra delar (drift, planering, synk, integrationer) får använda `contracts` och `core` men aldrig varandra. ID, TKL och CAD får bara använda `contracts`. `hub/` är startprogrammet och får dra igång Hubbens delar.

## Tester

- Testerna körs på varje PR. Kontrollerna heter "Tester" (kodstil med ruff, typer med mypy, pytest) och "Hubbens bild" (bilden byggs och provas). Båda ska vara gröna.
- Gamla Servers tester är facit. Ett beteende som portas tar med sitt test.
- Kör samma sak lokalt: `uv sync`, `uv run ruff check .`, `uv run ruff format --check .`, `uv run mypy`, `uv run pytest`. Python 3.12, beroendena låsta i `uv.lock`.
- Ett nytt beroende läggs bara till om det är välkänt och behövs; nämn det i PR-texten.

## Hemligheter och personuppgifter

- Repot ska vara publikt med AGPL-3.0 (beslut ST6 och ST7). Inga nycklar, koder, lösenord, personuppgifter eller interna adresser i koden, i loggar eller i ärenden.
- Hemligheter läggs i GitHub eller hos Scaleway och läses från miljön. De skrivs aldrig ut.

## Testmiljön

- test.hub.trainmeet.app läggs ut av jobbet "Testmiljön" när en ändring kommer till `main`. Servern och SSH-nycklarna sköts av `deploy/testmiljo.py` (nycklarna i Scaleways Secret Manager); filerna på servern ligger i `deploy/testmiljo/`.
- Behöver hubben nya inställningar eller hemligheter i testmiljön läggs de i `deploy/testmiljo/compose.yaml` som variabler, aldrig som värden i koden.

## Gamla repon

trainmeet-server, trainmeet-cloud, cda-tkl och tk-tkl är referens. Logiken portas därifrån, men koden kopieras inte rakt av. De arkiveras när den nya generationen är klar och provad (ST8).
