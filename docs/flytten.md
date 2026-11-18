# Flytten från gamla TrainCatalog

Så flyttas fordonen, bilderna, taggarna och kopplingshistoriken från gamla TrainCatalog till TrainMeet Catalog, steg för steg (ärende 57, CAT-204–CAT-207, beslut C33).

**Gamla TrainCatalog står kvar tills nya Catalog är provad.** Den gamla tjänsten stängs inte och den gamla adressen skickas inte vidare förrän flytten är kontrollerad och de som använder Catalog har provat den (CAT-206). Under tiden kan flytten köras om: den flyttar aldrig något två gånger och lägger bara till det som är nytt.

## Vad som flyttas

- **Fordonen**, med samma id som förut. Kärnfälten (slag, littera, nummer, bolag, epok, skala, tillverkare, artikelnummer, anteckning och DCC-adress för lok) får källan *import*. Numret står kvar som det är målat, med sin kontrollsiffra.
- **De gamla fälten.** Allt annat som har ett värde sparas med fordonet under fältets svenska namn från gamla TrainCatalog, till exempel *L ö b* eller *Inventarienummer* (CAT-205). Det syns under *Från gamla TrainCatalog* på kortet och följer med i kontoexporten, men aldrig i minikortet eller uppslaget. Ett fordon som var sparat men saknar både littera och nummer blir ett utkast.
- **Bilderna**, genom Catalogs vanliga uppladdning: högst 15 MB och 40 megapixel, metadata borttagen, högst 10 per fordon och inom den fria lagringen på 100 MB per person. Huvudbilden blir densamma som förut. Originalet följer med där det sparades.
- **Taggarna**, med samma uid, så att en tagg eller QR-kod som bär `/t/<uid>` fortsätter att fungera. Kopplingarna och händelserna följer med med sina datum.
- **Ägarna.** Varje gammal ägare med en verifierad e-postadress får en *väntande vagnpark*. Catalog sparar inte adressen, bara en nyckelad hash av den. När personen loggar in i Catalog med TrainMeet ID med samma verifierade adress blir vagnparken hens.

Följer inte med (CAT-25 och definitionen §11): förebildskatalogen, värdet och annonssökningen, referensbanken, inbjudningarna och delningarna, utskriftsinställningarna och logotyperna, Gratis och Plus, AI-avläsningarna och omgångarna. Ett konto utan verifierad e-postadress kan inte kopplas till ID, så inget av det flyttas.

## Det här behöver Casper ordna före dagen

1. **En kopia av gamla databasen.** Ta en säkerhetskopia av databasen TrainCatalog-db i Render (pg_dump i underhållsprocessen, eller Renders egen export). Skriptet läser den bara.
2. **Bilderna.** Mappen `/data/private-media` från gamla tjänstens disk i Render, som en tar-fil.
3. **Pepparn.** En ny hemlighet på minst 32 tecken, till exempel från `python3 -c "import secrets; print(secrets.token_urlsafe(48))"`. Spara den som hemligheten `CATALOG_FLYTT_PEPPER` i GitHub (Settings › Secrets and variables › Actions › New repository secret). Samma värde används av skriptet och av Catalog, och den skrivs aldrig ut. Byts eller förloras den kan de väntande vagnparkerna inte längre tas över.
4. **Catalog får pepparn av sig själv.** Nästa utläggning skriver hemligheten till `catalog-flytt.env` på servern, som bara Catalog läser (`deploy/testmiljo/compose.yaml`). När Catalog startar med den står det *Vagnparker från TrainCatalog tas över när ägaren loggar in med ID* i loggen.

Kopian och bilderna innehåller personuppgifter. De läggs bara på servern, och tas bort när flytten är kontrollerad.

## På dagen

Kommandona körs på servern i `/srv/trainmeet`, där Catalog kör. Läs först in inställningarna:

```sh
cd /srv/trainmeet
set -a; . ./.env; set +a
```

Lägg kopian i en egen databas bredvid Catalogs, och bilderna i en egen mapp. Kopian här är i pg_dumps eget format (`-Fc`); en kopia som vanlig SQL läses in med `psql` i stället för `pg_restore`.

```sh
docker compose exec -T catalog-db createdb -U catalog traincatalog_gammal
docker compose exec -T catalog-db pg_restore -U catalog -d traincatalog_gammal \
  --no-owner --no-privileges < /srv/flytten/traincatalog.dump
mkdir -p /srv/flytten/bilder && tar -xf /srv/flytten/private-media.tar -C /srv/flytten/bilder
```

Skriptet körs i Catalogs egen bild, med samma lagring för bilderna som Catalog. Det läser Catalogs databas från `CATALOG_DATABASE_URL`:

```sh
flytten() {
  docker compose run --rm --no-deps -e CATALOG_FLYTT_PEPPER \
    -v /srv/flytten/bilder:/flytten/bilder:ro catalog \
    python -m catalog.flytten \
    --gammal "postgresql://catalog:${CATALOG_DB_PASSWORD}@catalog-db:5432/traincatalog_gammal" \
    --bilder /flytten/bilder "$@"
}
```

### 1. Provkörning

```sh
flytten --provkorning
```

Inget skrivs. Rapporten säger hur många konton, fordon, bilder, taggar, kopplingar och händelser som skulle flyttas, hur många ägare som inte har loggat in i Catalog med TrainMeet ID än, och under *Flyttas inte* vad som inte kan flyttas och varför. Den innehåller bara antal, aldrig namn eller e-postadresser.

Gå igenom *Flyttas inte* innan körningen. Vanligast är bilder som saknas i bildmappen, bilder som inte får plats i den fria lagringen och konton utan verifierad e-postadress. En tagg som redan är kopplad till någon annans fordon i nya Catalog hoppas över och står i rapporten.

### 2. Körningen

Säkerhetskopiera Catalogs databas först, och kör sedan flytten:

```sh
sh catalog-backup.sh fore-migrering
flytten
```

Rapporten ska vara densamma som provkörningens. Stannar körningen, till exempel för att databasen inte svarar, körs den igen: det som redan är flyttat flyttas inte igen.

### 3. Kontroll

- Kör `flytten --provkorning` igen. Allt ska stå som *flyttade förut*, och inget som nytt.
- Logga in i Catalog med TrainMeet ID med en gammal ägares e-postadress, till exempel Caspers egen. Vagnparken ska synas med bilder och taggar, och kortet ska visa *Från gamla TrainCatalog*.
- Blippa en gammal tagg, eller öppna `https://<Catalogs adress>/t/<uid>`. Kortet ska öppnas för ägaren och minikortet för andra.
- Catalogs logg visar när en vagnpark tas över, med antal fordon och utan adress: `docker compose logs catalog | grep TrainCatalog`.

Gamla TrainCatalog är fortfarande igång. Läggs något nytt in där under provtiden tar nästa körning med det.

### 4. Den gamla adressen skickas vidare (görs på dagen, inte nu)

Först när nya Catalog är provad och Casper säger ja:

1. Stäng gamla TrainCatalog för ändringar i Render (stäng av tjänsten, men ta inte bort den eller databasen).
2. Kör steg 1–3 en sista gång, så att det sista som lades in följer med.
3. Peka DNS-raden för `traincatalog.goodstuff.se` mot servern, och ta bort domänen från tjänsten i Render. Det gör Casper hos den som har domänen goodstuff.se.
4. Lägg till ett block i `deploy/testmiljo/Caddyfile`, i ett eget PR, som skickar allt vidare för alltid med hela sökvägen:

   ```
   traincatalog.goodstuff.se {
   	redir https://{$CATALOG_DOMAIN}{uri} permanent
   }
   ```

   Catalog tar sedan emot de gamla sökvägarna och skickar dem vidare för alltid (301) till de nya: `/t/<uid>` i alla gamla former till taggens adress, `/fordon/<id>/redigera` till `/fordon/<id>/andra`, `/nytt` och `/nytt/flera` till `/fordon/nytt` och `/fordon/nytt/flera`, `/konto` till fordonen och de gamla inloggningssidorna under `/accounts/` till `/logga-in`. `/fordon/<id>` är samma sida som förut, eftersom fordonet har kvar sitt id.
5. Prova: `curl -sI https://traincatalog.goodstuff.se/t/<uid>` ska svara 301 till Catalog, och en gammal tagg ska öppna kortet.
6. Ta bort kopian och bilderna från servern:

   ```sh
   docker compose exec -T catalog-db dropdb -U catalog traincatalog_gammal
   rm -rf /srv/flytten
   ```

### 5. Repot arkiveras (efter att flytten är provad)

När flytten är provad arkiveras repot `beahead-ab/traincatalog` (CAT-207). Det raderas inte. Casper gör det på GitHub: öppna repot, välj **Settings**, rulla ner till **Danger Zone**, välj **Archive this repository** och skriv repots namn för att bekräfta. Repot går att läsa som förut, men ingen kan ändra i det.
