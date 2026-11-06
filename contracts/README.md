# Kontrakten

Den enda vägen mellan TrainMeets delar. Ingen del använder en annan dels inre kod; alla läser kontrakten här.

| Kontrakt | Modell | Vad |
| --- | --- | --- |
| Träffpaketet, `trainmeet.meet/1` | `meet.py` | Allt som behövs för att köra en träff. Exempel: `examples/provbanan.meet.json`. |
| Stationens utsida, `trainmeet.station-outside/1` | `station_outside.py` | Det TKL Studio publicerar om en station. Exempel: `examples/asen.station-outside.json`. |
| Stationsprotokollet, `trainmeet.station/1` | `station.py` | För klienter som ritar sin egen skärm: TKL, TMBox iPhone och trafikledningens vyer. Anslutning och godkännande med nyckel, kommandon, ögonblicksbilden och händelserna. |
| Terminalprotokollet, 16×2-profilen | `terminal.py` | För TMBoxar: Drift ritar bilden och boxen skickar knapptryck. Exakt gamla Servers profil, över MQTT för fysiska boxar och HTTP för TMBox web. |
| Driftens API, `trainmeet.drift/1` | `drift.py` | För trafikledningen och skärmarna: starta, klockan, godkänna och tilldela klienter, och händelseloggen. |
| Skälen | `reasons.py` | Varför Drift sa nej, med texten för varje skäl. |
| Synken och förarnas API | `SKISSER.md` | Skisser. Skrivs färdigt i steg 5 och 7. |

Varje modul börjar med sina adresser och sina regler. JSON-schemana i `schemas/` skapas ur modellerna, ett per meddelande.

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
