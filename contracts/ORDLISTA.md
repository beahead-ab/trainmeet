# Ordlista

Ett namn per begrepp, i specen, i gränssnittet och i kontrakten. Kontrakten skriver fältnamnen på engelska; gränssnittet och specen säger det svenska ordet.

| Svenska | I kontrakten | Betyder |
| --- | --- | --- |
| Träffpaket | `trainmeet.meet/1`, `MeetPackage` | Allt som behövs för att köra en träff, i ett paket. |
| Version | – | En publicering av träffpaketet. Fryst, ändras aldrig och raderas aldrig. Synk lagrar den med kontrollsumman. |
| Kontrollsumma | `checksum` | SHA-256 av paketets kanoniska JSON, räknad på byten som publicerades och aldrig på ett paket som lästs och skrivits om (A11). Avgör om ett paket är helt. |
| Lägsta Hubbversion | `requires_hub` | Den äldsta Hubb som kan köra paketet (GRUND-18). En äldre hubb startar inte versionen och säger vilken version som krävs. Tomt: alla. |
| Träffens hem | `sync.Home`, `HomeBundle`, `/home/take`, `/home/back`, `/home/reclaim` | Hubben där träffen planeras och versionerna publiceras (H35). Flyttas med en knapp till Pi:n före träffen och tillbaka efter, med utkastet, underlagen och förslagen. Den andra hubben tittar och ändrar inget. Varje flytt räknar upp generationen, så det aldrig blir två version 5 (SYNK-16). |
| Reläet | `/relay/{hub}/api/station/1/...`, `RelayCall`, `RelayAnswer`, `ConnectReply.relay` | Vägen till träffens hubb utanför träffens nät (SYNK-11). Telefoner och molnets TKL gör samma anrop till molnhubben, med samma nyckel. Molnet ställer anropet i kö och hubben hämtar det på sin egen förbindelse, så ingen port öppnas på träffen (SYNK-13). Molnet sparar ingenting av trafiken, och nyckeln går bara som sin hash mellan molnet och hubben. |
| Push | `PushToken`, `Notice`, `sync.Push`, `PUT /api/station/1/push` | Notiser till telefonen (F20): begäran hit med Ge klart och Neka i notisen, påminnelsen, klart eller nekat, och tåg på väg. Till den som är godkänd för platsen och har gett hubben telefonens adress. Hubben som leder skickar; en Pi skickar genom molnet, som har nyckeln till Apples tjänst. Telefonens adress skrivs aldrig ut. |
| Låtsad push | `FakePush`, `/api/hub/push` | Där notiserna hamnar när hubben saknar nyckeln till Apples tjänst. Visar de senaste, med bara slutet av telefonens adress. |
| Glömd PIN | `python -m hub.pin`, `trainmeet-ny-pin.txt` | En ny PIN-kod med fysisk åtkomst till hubben, också utan internet (H46): ett kommando på Pi:n, eller en fil på ett USB-minne med den nya koden på första raden. Filen tas bort och alla inloggningar slutar gälla. |
| Ta över i molnet | `leader.taken`, `TakeOver`, `/api/drift/1/takeover` | Molnhubben leder träffen när Pi:n har tystnat (H8, H9, TRAFIK-08). Bara för hand, med träffens namn skrivet. Epoken räknas upp och klockan stannar där Pi:n senast var. Kommer Pi:n tillbaka följer den molnet, och det den gjorde under tiden sätts åt sidan. |
| Driftplats | `place` | En plats i planen: bemannad, fjärrstyrd, obemannad, skuggbangård eller industri/hållplats. Sträckor, tågbesök och protokoll pekar på driftplatsen. |
| Platstyp | `place.kind` | `manned` bemannad, `remote` fjärrstyrd, `unmanned` obemannad, `shadow_yard` skuggbangård, `halt` industri/hållplats. |
| Signatur | `place.code` | Driftplatsens förkortning, till exempel Nby. |
| Leknummer | `place.phone`, `PlacePhone` | Driftplatsens telefonnummer i trafikspelet. Inga personuppgifter. Trafikledningen kan ändra det under träffen (drifthändelsen `place.phone`). |
| Station | `station` | Det som skapas i TKL Studio och kopplas till en driftplats, i förväg eller när den ansluter. |
| Utsida | `trainmeet.station-outside/1` | Det träffen vet om en station: id, namn, stationsspår, utfarter och sidor. |
| Insida | – | Spårplan, signaler och adresser. Stannar alltid hos TKL. |
| Utfart | `exit` | Där ett spår lämnar stationen, med fast id och sida. Kopplas till en sträcka per träff. |
| Sida | `side` | `left` eller `right`, som boxen visar en sträcka eller utfart. En box kan tilldelas en sida (`both` är förval) och ser då bara tågen på sträckorna åt det hållet. |
| Boxspråk | `language` | TMBoxens språk: `sv`, `en`, `da`, `nb` eller `de`. Trafikledningen väljer per box; träffens land ger förvalet. Platsnamn, koder, tågnummer och spår översätts aldrig. |
| Displaystorlek | `display` | 16×2 eller 20×4, som boxen säger när den ansluter. Allt annat räknas som 16×2. |
| Planspår | `place.tracks[].name` | Spårets namn i planen. Tågbesöket behåller det. |
| Spårtabell | `station.track_map` | Översätter planens spårnamn till stationens spår-id. |
| Sträcka | `section` | Planens klareringssträcka mellan två driftplatser, från infartssignal till infartssignal. Tåget får klart en gång för hela sträckan. |
| Grafens linje | `display.graph_pages` | Ett blad i tågdiagrammet: platserna i ordning längs linjen, med avstånd, nummer och färg ur planen. |
| Delsträcka | `section.parts` | Den fysiska biten mellan två platser längs en sträcka. Används för karta, graf och detektering. |
| Klareringsläge | `clearance_mode` | Bara `requested` (begärd) eller `direct` (direkt). Träffen har ett grundläge, och en sträcka kan ha det andra. |
| Tåg | `train` | Ett tågnummer med sina tågbesök. Numret är för inmatning och visning, aldrig en nyckel. |
| Tågbesök | `call` | Ett tågs besök på en driftplats, med spår och tider. Det är det Drift håller reda på. |
| Tågslag | `train_type` | Till exempel persontåg eller godståg. |
| Ej uppehåll | `call.stops = false` | Tåget passerar utan att stanna. |
| Inget utbyte | `call.exchange = false` | Tåget står, men varken lastar eller släpper av. Ett vanligt uppehåll i tidtabellen. |
| Manuellt tåg | `train.manual` | Ett tåg utan tid, sträcka eller med omöjlig gångtid. Körs för hand, och automatiken rör det inte. |
| Trafikdag | `train.days`, `Weekday` | Tidtabellens veckodag. |
| Speldygn | `traffic_week` | Dag 1…N på träffen. Inte samma sak som trafikdag: en åttadagarsträff har två måndagar. |
| Tidshopp | `clock.jump`, `TimeJumped` | Klockan ställs till en annan tid samma speldygn. Öppna klareringar stängs och tågen ställs där tidtabellen har dem: framme där de senast skulle ha kommit, och kvar på avgångsstationen om de enligt tidtabellen är ute på linjen. En drifthändelse; inget raderas. |
| Ångra hoppet | `clock.jump_undone`, `TimeJumpUndone` | Läget före det senaste tidshoppet läggs tillbaka, med klockan som den var. Händelserna emellan står kvar i loggen. |
| Dygnsskifte | `day.changed`, `DayChanged` | Nästa speldygn börjar, med nästa veckodag som trafikdag: en timme före den dagens första tåg, aldrig före midnatt, eller vid en tid trafikledningen satt. Natten hör till dygnet före fram till dess. Tågen ställs strax före dagens första avgång. Manuellt är förval, automatiskt ett val (`DaySettings`). |
| Starta ny dag | `POST /api/drift/1/day`, `NewDay` | Trafikledningen startar nästa speldygn. Nekas medan dagens tåg är ute eller har en öppen klarering. |
| Driftändring | `DriftChange`, `change.made` | En ändring som trafikledningen gör i Nu under träffen, ovanpå versionen som körs. Tio slag: ställa in tåg, extratåg, ändrade tider, ändrade driftplatser och sträckor, ändrat planerat spår, enkel eller dubbel sträcka, ändrade trafikdagar, byte av tågnummer, ej uppehåll och anmärkning (DRIFT-41). Gäller direkt och blir ett förslag till nästa version. |
| Extratåg | `ExtraTrain` | Ett tåg som trafikledningen sätter in: en kopia av ett tåg med nytt nummer och ny tid, eller från–till med avgångstid, där Drift fyller i driftplatserna emellan (H12). |
| Väntar | `ChangeStatus.waiting` | En driftändring mot ett tåg som är ute eller har öppen klarering gäller först när tåget är framme (H38). |
| Tvinga igenom | `force`, `change.applied` | Trafikledningen låter en väntande driftändring gälla direkt, med en varning. Det som inte längre körs stängs (H38). |
| Släpp | `change.dropped` | En driftändring gäller inte längre; versionen körs som den är. |
| Förslag | `Proposal` | En driftändring som förslag till nästa version (4.4). Planeraren tar med den i utkastet eller avslår den i Versioner, och Drift ser svaret. Släpps den i Drift innan svaret är den återtagen. |
| Ta med | `take`, `Draft.taken` | Förslaget läggs på utkastet, på samma sätt som Drift gjorde, och står kvar när underlaget läses om. |
| Avslå | `reject` | Nästa version görs utan förslaget. |
| Versionsbyte | `version.switched`, `SwitchVersion` | Drift går över till en ny version under träffen, när trafikledningen säger till. Klockan, tågens lägen och de öppna klareringarna följer med. Varje driftändring behålls om den inte släpps; en som planeraren tagit med i den nya versionen faller bort (H4, H66). Mot ett tåg som är ute väntar bytet, om det inte tvingas igenom (H38). |
| Påbörjat och klart | `transition.begun`, `transition.done` | Ett versionsbyte, ett tidshopp, Ångra och ett dygnsskifte skrivs mellan två drifthändelser. Startar Drift med ett påbörjat utan klart är den spärrad tills trafikledningen låser upp (DRIFT-47). |
| Modelltid | `TimeOfDay` | Tiden på träffklockan, som TT:MM. |
| Provkörning | `trainmeet.drift-1.preview` | En egen körning av Provbanan för en webbläsare. Sparas ett dygn, och boxar och TKL ansluter till den med dess kod. |
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
| Automatiken | `drift.AutomationSettings`, `actor.kind = automation` | Sköter de driftplatser som ingen box eller TKL arbetar med: ger klart när spåret är ledigt, skickar sina tåg och tar emot dem. Gör det genom samma stationskommandon som en box (F14). |
| Bemannad | `place.manned` | Den första box eller TKL som arbetar med en driftplats gör den bemannad. Inte samma sak som platstypen `manned` i planen. |
| Kontakt saknas | `PlaceMode.no_contact` | En bemannad driftplats som inte hörts av på 45 sekunder. Automatiken tar över efter den tid trafikledningen valt, förval aldrig. |
| Lämna till automatiken | `place.left`, `place.leave` | Boxen, TKL eller trafikledningen lämnar driftplatsen åt automatiken, tills någon tar tillbaka den. |
| Ta tillbaka | `place.taken_back`, `place.take_back` | En ansluten box eller TKL arbetar med driftplatsen igen. |
| Störningar | `AutomationSettings.disturbance` | Påhittade förseningar som automatiken lägger in: av, normal eller störd trafik (F15). |
| På väg hit, har lämnat | `on_the_way`, `have_left` | Tåg på sträckan, från avgången hos grannen till ankomsten här, och tvärtom. Drift räknar fram båda. |
| Bild | `terminal.Frame` | Det en TMBox visar. Drift ritar den; boxen skickar bara knapptryck. |
| Drifthändelse | `drift.DriftEvent` | Allt som händer i en körande träff, i ordning. Det som läses tillbaka vid omstart och skickas till molnet. |
| Epok | `epoch` | Ledarskapets nummer. *Ta över* höjer det, och en hubb som ser en högre epok slutar fatta beslut. |
| Nivå | – | Bara i TKL: hur mycket av ställverket en station har (0–3). |
| Underlagsnivå | `source.level` | Bara i importen: hur bra underlaget är (1–4). |
| Underlag | `source` | En fil som lagts till träffen, till exempel Tellurians planeringsfil. Sparas som den kom. |
| Utkast | `trainmeet.planning/1`, `Draft` | Det Planering arbetar med tills det publiceras som en version. |
| Faktum | `fact` | Det utkastet vet om en sak, med ursprung och säkerhet. |
| Ursprung | `origin` | Var i vilket underlag ett faktum står, eller `planner` för en ändring i Planering. |
| Säkerhet | `certainty` | `sure` säker, `likely` trolig, `unsure` osäker, `confirmed` bekräftad. |
| Regelbok | `rulebook` | Tågslagen och förkortningarna som alla underlag läses med. Saknas en regel blir det en fråga. |
| Fråga | `question` | Ställs bara där en regel saknas eller två lika tunga underlag säger olika. |
| Importrapport | `ImportReport` | Nivån, vad underlaget gav, vad reglerna bestämde och vad som inte lästes in. |
| Stationslistor | `SourceKind.STATION_LISTS` | Planeringsprogrammets lista per station (ODT, ZIP med ODT, Excel eller CSV). Prövas mot planeringsfilen och ändrar inte utkastet (IMPORT-27). Vad listan säger om fordonen i tåget läses aldrig in. |
| Banbild | `SourceKind.TRACK_PICTURE` | Sidan Topologi i Tellurians PDF: driftplatserna med signatur och läge, linjerna mellan dem och dubbelspår där två linjer går bredvid varandra. Underlagsnivå 2, och kartan i Bana. |
| Banbilden i Bana | `TrackPicture`, `PictureLink`, `/meets/{meet}/picture` | Banbildens signaturer och linjer, i kartans enheter, som bakgrund i Bana (PLAN-02). Ett foto av banan skrivs av med egen AI (`?transcribe=picture`, 4c2) och ligger självt under kartan (`TrackPicture.photo`, `/picture/photo`, IMPORT-17). |
| Graf som bild | `SourceKind.GRAPH_PICTURE`, `?transcribe=graph` | En bild av grafen, skriven av med egen AI (4c2). Bara axlarna läses: linjerna med stationerna i ordning och avstånden. Linjerna blir Graf, och sträckor mellan grannar på en linje blir säkra. Bygger vidare på stationslistorna, underlagsnivå 3. Tågen i grafen läses inte. |
| Stationens utsida som underlag | `SourceKind.STATION_OUTSIDE`, `Draft.stations`, `StationVersion` | Utsidan TKL Studio skriver, trainmeet.station-outside/1, lagd till under Lägg till underlag (IMPORT-10). Samma utsida igen ändrar inget (IMPORT-31); en ny för samma station får nästa nummer. |
| Koppla station | `StationChange`, `Place.station`, `CoupledStation` | En station kopplad till driftplatsen i förväg (PLAN-05). Planens spår som heter som stationens tas direkt; de som skiljer sig blir frågor (IMPORT-18). Nästa version bär utsidan, pinnad (PLAN-11). |
| Avskrift | `AiPages`, `?transcribe=lists`, `picture` eller `graph` | En skannad sida som hubbens egna AI har skrivit av (4c2). Sidorna räknas innan något skickas (IMPORT-05), och varje sidas avskrift sparas, så samma fil aldrig kostar två gånger (IMPORT-15). Det AI har skrivit av är osäkert tills det bekräftas. |
| Egen AI | `AiService`, `AiServiceChange`, `AiFormat`, `/api/hub/ai` | AI-tjänsten hubben skriver av skannade sidor och bilder med, inställd under Den här hubben → AI (H58). Det vanliga chatt-API:t eller Claudes eget (H59). Nyckeln stannar i hubben och visas aldrig igen. |
| Bekräfta | `ConfirmChange` | Planeraren godkänner det ett underlag gav, som det är: en osäker eller trolig uppgift blir bekräftad (IMPORT-04). |
| Dom | `ListVerdict`, `ImportReport.verdicts`, `ImportResult.checks_only` | En stationslistas prövning mot planen: hur många tågbesök som stämmer och var det skiljer. |
| Program | `about.program` | Träffens program, som fasta tider. |

## TrainMeet Catalog

| Svenska | I kontrakten | Betyder |
| --- | --- | --- |
| Catalogs API | `trainmeet.catalog/1`, `contracts/catalog.py` | Det webbappen och andra läser av Catalog. Beskrivs i `catalog.openapi.json`, med TypeScript-typerna i `catalog.d.ts`. |
| Konto | `Account` | Den som är inloggad, med id från inloggningen, namn och initialer. |
| Inloggning | `Session`, `LoginKind` | Vem som är inloggad, och hur man loggar in här: `trial` eller `id`. |
| Inloggning med ID | `LoginKind.ID`, `/api/catalog/1/id/login`, `Session.logout_url` | Webbläsaren går till TrainMeet ID och kommer tillbaka inloggad, med samma konto i alla appar. Kontot i Catalog skapas första gången (CAT-42). Vid utloggning säger Catalog vart webbläsaren går för att logga ut ur ID också. |
| Provinloggning | `LoginKind.TRIAL`, `TrialLogin` | Inloggningen i testmiljön tills TrainMeet ID finns, med fasta provkonton utan personuppgifter (CAT-214). |
| Vagnpark | `VehicleList` | En ägares alla fordon. |
| Vagnparksval | `FleetChoice`, `FleetRight`, `?fleet=` | Vagnparkerna man kan arbeta i: den egna först, sedan de som är delade med en, med rätten `owner`, `edit` eller `view` (CAT-50, #49). Rätten avgörs på ett ställe, `catalog/access.py` (CAT-49). |
| Har en tagg | `Vehicle.tagged` | Det den som vagnparken är delad med ser: att fordonet har en tagg, aldrig taggen (CAT-47). |
| Fordon | `Vehicle` | Ett fysiskt exemplar med ett permanent id (CAT-52). |
| Kärnfält | `VehicleFields` | De få fält ett fordon har: slag, littera, nummer, bolag, epok, skala, modell, anteckning, och för lok DCC-adress och funktioner (CAT-53). |
| Slag | `kind` | `locomotive` lok, `freight_wagon` godsvagn, `passenger_coach` personvagn, `multiple_unit` motorvagn eller tågsätt, `other` övrigt. |
| Nummer | `number` | Text precis som det står på fordonet. EVN räknas fram ur det och skrivs aldrig tillbaka (CAT-55, CAT-58). |
| EVN | `EvnParts` | Interoperabilitetskod, landnummer, löpnummer och kontrollsiffra, framräknade ur numret. |
| Utkast, klart | `status`: `draft`, `ready` | Klart kräver slag och littera eller nummer (CAT-62). |
| Läge | `state` | `home` hemma, `packed` packat, `at_meet` på träffen, `lent` utlånat (CAT-70). |
| Plats | `Place` | En namngiven plats hemma, till exempel Låda 1 eller Hyllan (CAT-71). |
| Lån | `Lending`, `Lend` | Vem som har fordonet: ägarens egen anteckning (CAT-74, CAT-75). |
| Händelse | `VehicleEvent` | Ett byte av läge eller plats, med tid (CAT-77). |
| Källa | `field_sources`, `FieldSource` | Var ett kärnfälts värde kom ifrån: ägaren, AI:n, förebilden eller en import (CAT-64). |
| Besked | `Problem`, `ProblemCode` | Varför Catalog sa nej, med en kod som webbappen har text för. |
| Ägare | – | Den som äger en vagnpark: en person, och senare en klubb. Varje skrivning låser ägarens rad först (CAT-40). |
| Tagg | `Tag`, `TagKind` | En NFC-tagg under fordonet, en QR-etikett eller en simulerad tagg, med ägare och namn (CAT-78). |
| Identifierare | `uid` | Det som står efter /t/ i adressen: NFC-taggens serienummer i hex, QR-etikettens id eller den simulerade taggens UUID. Unikt i hela Catalog. |
| Koppling | `VehicleTag.assignment` | En tagg på ett fordon, med start och slut. Ett byte eller en bortkoppling bär den koppling man såg (CAT-89). |
| Blippa | – | Att hålla telefonen mot taggen eller skanna QR-koden. Öppnar /t/<uid>. |
| Uppslag | `Lookup` | Det /t/<uid> svarar: `mine`, `shared`, `private`, `fleet` eller `unknown`, vart och ett med en egen vitlista (CAT-98). |
| Minikort | `MiniCard` | Det en annan än ägaren ser: littera och nummer, slag, bolag, skala och miniatyr (CAT-100). |
| Väntande koppling | `PendingLink` | Koppla tagg på kortet: fordonet väntar på nästa tagg i 10 minuter (CAT-94). |
| Säg till ägaren | `Tell`, `Notice` | Den som är inloggad och blippar någon annans fordon skriver var det står. Ägaren ser beskedet utan avsändare (CAT-113). |
| Visa mitt namn | `OwnerSettings.show_name` | Ägarens namn på minikortet, för den som är inloggad. Av från början (CAT-101). |

## TrainMeet ID

| Svenska | I kontrakten | Betyder |
| --- | --- | --- |
| ID:s API | `trainmeet.id/1`, `contracts/id.py` | Det ID äger utöver kontona i Keycloak: klubbar, medlemmar, rollerna per resurs och inbjudningarna (KONTO-08). Beskrivs i `id.openapi.json`, med TypeScript-typerna i `id.d.ts`. |
| Klubb | `Club`, `ClubPage` | En klubb med medlemmar. Den som skapar den blir administratör (KONTO-35). Klubbar är skilda åt (KONTO-17). |
| Klubbroll | `ClubRole` | `admin` administratör eller `member` medlem. |
| Resurs | `Resource`, `ResourceKind` | Det en roll gäller: en klubb, en vagnpark, en träff, en station, en modul, en hubb eller Catalog (KONTO-03). ID har bara referensen. |
| Roll | `Role`, `Grant` | En persons roll till en resurs (KONTO-28), utdelad av resursens ägare eller klubbens administratör (KONTO-36). |
| Inbjudan | `Invitation` | Till en klubb eller en delad vagnpark. Ger ingenting förrän den som den skickades till har svarat ja (KONTO-29, KONTO-35). |
| Delning | `FleetPage`, `FleetInvite`, `FleetRole` | Ägaren delar hela vagnparken med en person, att titta (`viewer`) eller redigera (`editor`) (CAT-44). |
| Träff i ID | `Meet`, `NewMeet`, `MeetPage` | En referens till en träff med namn, datum och klubb (ID10). Själva träffen ägs av Hubben (KONTO-09), som kopplar sin träff hit i ärende 78. |
| Roll på träffen | `MeetRole`, `MeetGrant` | `organizer` arrangör, `dispatcher` trafikledare, `loco_lead` lokledare och `remote_clearer` fjärrtågklarerare. Går till klubbens medlemmar; arrangören delar ut trafikledare och lokledare, klubbens administratör alla (KONTO-36). |
| App | `AppKey` | En av TrainMeets appar: `hub`, `tkl`, `cad`, `catalog`, `driver` (Lokföraren) och `id`. |
| Appväxlaren | `Switcher`, `Session.apps` | Apparna personen har något i (KONTO-38, ID11): Catalog och ID för alla, Hubben med en roll på en träff eller som klubbens administratör, Lokföraren som lokledare. |
| Hjälp och fel | `HelpRequest`, `HelpKind` | Hjälp (`help`) eller fel (`fault`) från kontomenyn i alla appar, som ett mejl till supportadressen med appen, sidan och versionen (KONTO-06, ID9, ID12). |
| Klubbroll ändras | `ClubRoleChange` | Administratören gör en medlem till administratör eller tillbaka. En klubb har alltid en administratör (KONTO-02). |
| Ta bort kontot | `RemovalPlan`, `RemoveAccount` | Kontot tas bort i Catalog, Keycloak och ID (KONTO-31, ID7). En klubb där personen är ensam tas bort med kontot; en klubb där personen är enda administratören bland andra stoppar tills någon annan har rollen (ID13). |
| Uppgifterna som fil | `AccountExport`, `CatalogExport` | Allt TrainMeet har om personen, från ID och Catalog, i en fil före borttagningen (KONTO-31). |
| Ägare borttagna | `OwnersRemoved` | ID säger till Catalog vilka ägare som är borta, och Catalog tar bort deras vagnparker (CAT-193). Bara ID:s egen klient får anropa. |
| Apparnas fråga | `Access`, `FleetAccess` | Vilka roller en person har till en resurs nu, och vilka vagnparker som är delade med personen. Appen frågar vid varje anrop (KONTO-34). |
