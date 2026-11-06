# Kontrakten

Den enda vägen mellan TrainMeets delar. Ingen del använder en annan dels inre kod; alla läser kontrakten här.

| Kontrakt | Modell | Schema | Exempel |
| --- | --- | --- | --- |
| Träffpaketet, `trainmeet.meet/1` | `meet.py` | `schemas/trainmeet.meet-1.schema.json` | `examples/provbanan.meet.json` |
| Stationens utsida, `trainmeet.station-outside/1` | `station_outside.py` | `schemas/trainmeet.station-outside-1.schema.json` | `examples/asen.station-outside.json` |

Stationsprotokollet, terminalprotokollet och driftens API kommer i nästa del, med synken och förarnas API som skisser.

Orden står i [ORDLISTA.md](ORDLISTA.md).

## Reglerna

- **Modellerna är källan.** JSON-schemana skapas ur dem med `uv run python -m contracts.generate`. Testerna blir röda om ett schema inte stämmer med sin modell.
- **Okända fält sparas och ignoreras**, så att en äldre läsare aldrig går sönder på en nyare skrivare.
- **Nya fält läggs till utan nytt nummer.** Tas ett fält bort, eller ändras vad det betyder, får formatet nytt nummer (`trainmeet.meet/2`).
- **Id:n är stabila mellan versioner.** En driftplats, sträcka, ett tåg och ett tågbesök behåller sitt id.
- **Strukturfel stoppar publicering.** Ett paket där något pekar på något som inte finns går inte att läsa in. Trafikkontrollens konflikter och iakttagelser står i `findings` och stoppar inte.
- **Ändras ett kontrakt ändras alla som använder det i samma PR.**

## Provbanan

Exemplet är den påhittade provbanan för steg 2. Den har fyra driftplatser i rad (Norrby, Åsen, Mellanå, Sjövik) med var sitt leknummer och hållplatsen Lövhult på dubbelspåret mellan Åsen och Mellanå. Mellanå–Sjövik har direktklarering. Tio tåg går en måndag, fem åt varje håll. Åsens station är kopplad i förväg med sin utsida.
