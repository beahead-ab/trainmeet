# Hemmaprovet (ärende 77)

Första hårdvarudagen (H64): en Pi och två stationer hemma, med boxar, en TKL och TMBox-appen, i en timme utan internet. Casper och Claude gör provet tillsammans. Varje steg säger vad som ska hända; det som inte händer skrivs i ärende 77.

## Före provet

- En Raspberry Pi 4 eller 5 med hubben installerad (`README.md` i den här mappen) och en träff publicerad i molnhubben, som Pi:n har kopplats till och följer (SYNK-08).
- Två TMBoxar: en med ESP8266 och en med ESP32 (BOX-24).
- En dator med TKL (`uv run python -m tkl`) och en telefon med TMBox-appen.
- En dator med det här repot för belastningsprovet.

## Provet

1. **Utan internet.** Dra ur internet till Pi:n. Starta träffen under Nu och klockan.
2. **Boxarna** hittar Pi:n själva och hamnar under Väntar i Klienter. Ge dem var sin driftplats (BOX-04, BOX-10).
3. **TKL** hittar Pi:n under Inställningar › Anslutning och ansluter utan kod. Godkänn den i Klienter. Svara på Hubbens fråga om utfarterna om den kommer (KLAR-13, H26).
4. **Klarera** ett tåg från en box till TKL: TKL ger klart, boxen avgår, TKL trycker Ankommit (KLAR-26).
5. **Telefonen** ansluter med appen och godkänns. Begär klart till telefonens plats och ge klart från notisen på låsskärmen, först på träffens nät och sedan med internet påslaget, genom reläet (BOXIOS-18).
6. **Dra ur nätet på den ena boxen.** Den andra fortsätter utan att vänta (BOX-24, H73).
7. **Starta om Pi:n mitt i.** Träffen står kvar, klockan står still tills den startas, och boxarna, TKL och telefonen kommer tillbaka av sig själva (SYNK-25).
8. **Belastningen** (SYNK-29): kör samtidigt i en timme från datorn på träffens nät:

   ```sh
   uv run python -m deploy.belastning --hub http://trainmeet.local --pin <PIN> \
       --clients 30 --boxes 40 --phones 100 --seconds 3600 --report-every 300 --strict
   ```

   Läget skrivs var femte minut. Inget fel, och 99 av 100 svar inom en sekund. De simulerade klienterna godkänns under Klienter som riktiga, så kör provet på en provträff.

## Efteråt

- Sätt i internet igen och se att molnhubben följer det Pi:n gjorde (SYNK-14).
- Skriv resultatet i ärende 77, med belastningsprovets sista läge.
