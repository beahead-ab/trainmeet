# Ordlista

Ett namn per begrepp, i specen, i gränssnittet och i kontrakten. Kontrakten skriver fältnamnen på engelska; gränssnittet och specen säger det svenska ordet.

| Svenska | I kontrakten | Betyder |
| --- | --- | --- |
| Träffpaket | `trainmeet.meet/1`, `MeetPackage` | Allt som behövs för att köra en träff, i ett paket. |
| Version | – | En publicering av träffpaketet. Fryst, ändras aldrig och raderas aldrig. Synk lagrar den med kontrollsumman. |
| Kontrollsumma | `checksum` | SHA-256 av paketets kanoniska JSON. Avgör om ett paket är helt. |
| Driftplats | `place` | En plats i planen: bemannad, fjärrstyrd, obemannad, skuggbangård eller industri/hållplats. Sträckor, tågbesök och protokoll pekar på driftplatsen. |
| Platstyp | `place.kind` | `manned` bemannad, `remote` fjärrstyrd, `unmanned` obemannad, `shadow_yard` skuggbangård, `halt` industri/hållplats. |
| Signatur | `place.code` | Driftplatsens förkortning, till exempel Nby. |
| Leknummer | `place.phone` | Driftplatsens telefonnummer i trafikspelet. Inga personuppgifter. |
| Station | `station` | Det som skapas i TKL Studio och kopplas till en driftplats, i förväg eller när den ansluter. |
| Utsida | `trainmeet.station-outside/1` | Det träffen vet om en station: id, namn, stationsspår, utfarter och sidor. |
| Insida | – | Spårplan, signaler och adresser. Stannar alltid hos TKL. |
| Utfart | `exit` | Där ett spår lämnar stationen, med fast id och sida. Kopplas till en sträcka per träff. |
| Sida | `side` | `left` eller `right`, som boxen visar en sträcka eller utfart. |
| Planspår | `place.tracks[].name` | Spårets namn i planen. Tågbesöket behåller det. |
| Spårtabell | `station.track_map` | Översätter planens spårnamn till stationens spår-id. |
| Sträcka | `section` | Planens klareringssträcka mellan två driftplatser, från infartssignal till infartssignal. Tåget får klart en gång för hela sträckan. |
| Delsträcka | `section.parts` | Den fysiska biten mellan två platser längs en sträcka. Används för karta, graf och detektering. |
| Klareringsläge | `clearance_mode` | Bara `requested` (begärd) eller `direct` (direkt). Träffen har ett grundläge, och en sträcka kan ha det andra. |
| Tåg | `train` | Ett tågnummer med sina tågbesök. Numret är för inmatning och visning, aldrig en nyckel. |
| Tågbesök | `call` | Ett tågs besök på en driftplats, med spår och tider. Det är det Drift håller reda på. |
| Tågslag | `train_type` | Till exempel persontåg eller godståg. |
| Ej uppehåll | `call.stops = false` | Tåget passerar utan att stanna. |
| Manuellt tåg | `train.manual` | Ett tåg utan tid, sträcka eller med omöjlig gångtid. Körs för hand, och automatiken rör det inte. |
| Trafikdag | `train.days`, `Weekday` | Tidtabellens veckodag. |
| Speldygn | `traffic_week` | Dag 1…N på träffen. Inte samma sak som trafikdag: en åttadagarsträff har två måndagar. |
| Modelltid | `TimeOfDay` | Tiden på träffklockan, som TT:MM. |
| Köruppdrag | `duty` | En förares tjänst. |
| Omlopp | `turn` | Tågen som samma fordon kör, i ordning. |
| Växlingsuppdrag | `shunting` | Växling på en driftplats. |
| Fynd | `finding` | Trafikkontrollens konflikter och iakttagelser. Stoppar inte publicering. |
| Bilaga | `attachment` | En fil som paketet bär, till exempel en urtavla. |
| Godkännande | `station.ConnectReply` | Trafikledningen godkänner en TKL eller app i Klienter. Ger en nyckel för träffen och driftplatsen. |
| Nyckel | `Authorization: Bearer` | Klientens nyckel från godkännandet. Krävs för alla stationskommandon, klarar omstarter och kan återkallas. Skickas i huvudet, aldrig i kroppen. |
| Ögonblicksbild | `station.Snapshot` | Allt en klient behöver om en driftplats, ersatt i sin helhet varje gång. Den är sanningen; händelserna säger bara att den ändrats. |
| Skäl | `Reason` | Varför Drift sa nej, med texten för varje skäl. |
| Ankomstspår | `train.arrived.track` | Spåret tåget faktiskt kom in på. Planspåret står kvar; boxen väljer ett annat med B. |
| Flytta hit | `train.moved_here` | Ett tåg ingen skickat tas in här ändå, så spelet går vidare (FLYTTA HIT). |
| Genomgående tåg | `Leg.previous` | Ett tåg som kommer in och går vidare med samma nummer. Nästa sträcka kan begäras innan det kommit, och tåget hoppar hit när det skickas vidare. |
| Ställa undan | `train.set_aside` | Ett tåg som slutat här ställs undan, och spåret blir fritt. |
| På väg hit, har lämnat | `on_the_way`, `have_left` | Tåg på sträckan, från avgången hos grannen till ankomsten här, och tvärtom. Drift räknar fram båda. |
| Bild | `terminal.Frame` | Det en TMBox visar. Drift ritar den; boxen skickar bara knapptryck. |
| Drifthändelse | `drift.DriftEvent` | Allt som händer i en körande träff, i ordning. Det som läses tillbaka vid omstart och skickas till molnet. |
| Epok | `epoch` | Ledarskapets nummer. *Ta över* höjer det, och en hubb som ser en högre epok slutar fatta beslut. |
| Nivå | – | Bara i TKL: hur mycket av ställverket en station har (0–3). |
| Underlagsnivå | – | Bara i importen: hur bra underlaget är (1–4). |
