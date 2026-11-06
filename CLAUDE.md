# Arbetsregler för Claude i trainmeet

Gäller alla chattar som arbetar i repot: Hub, ID, TKL och CAD.

## Specen är facit

- Specen TrainMeet Platform ligger i repot `beahead-ab/trainmeet-spec` (privat) och visas på platform.trainmeet.app bakom en läskod.
- Besluten står i beslutsregistret, `src/data.py`. Underlagen står i `docs/`. Läs först `docs/trainmeet-stacken.md` och `docs/trainmeet-hub-definition.md`.
- Säger koden och specen olika saker: fråga Casper, eller föreslå en ändring i specen i ett PR i trainmeet-spec. Gissa aldrig.
- Byggstatusen i specen (`BUILD` i `src/data.py`) uppdateras när en del går från Ej påbörjad till Pågår eller Klar.

## Casper

- Casper är produktägare och arbetar på systemnivå, inte på kodrader. Skriv till honom på svenska, kort och utan kod i chatten.
- Han är ny på git. Förklara vad han ska göra steg för steg när något behöver göras på GitHub.

## Grenar och pull requests

- En gren per uppgift och ett PR mot `main`. Casper slår ihop själv. Ingen pushar direkt till `main`.
- Varje PR säger på svenska vad som ändras och hur det är provat.

## Kontrakten först

- `contracts/` är den enda vägen mellan delarna. Ingen del importerar en annan dels inre kod.
- Ändras ett kontrakt ändras alla som använder det i samma PR.

## Tester

- Testerna körs på varje PR.
- Gamla Servers tester är facit. Ett beteende som portas tar med sitt test.

## Hemligheter och personuppgifter

- Repot ska vara publikt med AGPL-3.0 (beslut ST6 och ST7). Inga nycklar, koder, lösenord, personuppgifter eller interna adresser i koden, i loggar eller i ärenden.
- Hemligheter läggs i GitHub eller hos Scaleway och läses från miljön. De skrivs aldrig ut.

## Gamla repon

trainmeet-server, trainmeet-cloud, cda-tkl och tk-tkl är referens. Logiken portas därifrån, men koden kopieras inte rakt av. De arkiveras när den nya generationen är klar och provad (ST8).
