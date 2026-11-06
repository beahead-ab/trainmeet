# TrainMeet

TrainMeet är programvaran för modelltågsträffar med trafikspel: stationer som klarerar tåg mellan sig, en gemensam träffklocka, tidtabell, handboxar (TMBox) och ställverk (TKL).

Det här repot är nästa generation. All ny kod ligger här, med en mapp per del. Den ersätter TrainMeet Server, TrainMeet Cloud och de gamla TKL-repona, som ligger kvar som referens tills den nya generationen är klar och provad.

## Delarna

| Mapp | Del | Körs |
| --- | --- | --- |
| `contracts/` | Kontrakten: paketformatet, terminal- och stationsprotokollet, förarnas och driftens API och synken mellan hubbar. De andra delarna pratar bara med varandra genom dem. | – |
| `core/`, `drift/`, `planering/`, `synk/`, `integrationer/` | TrainMeet Hub, kärnan som kör träffen. Det enda man installerar. | Raspberry Pi på träffen och i molnet |
| `hub/` | Hubbens startprogram: drar igång delarna och visar startsidan med version och vilken ändring som körs | Raspberry Pi på träffen och i molnet |
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

## Licens

GNU Affero General Public License, version 3 (AGPL-3.0). Se [LICENSE](LICENSE).

© 2026 Beahead AB
