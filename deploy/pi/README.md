# TrainMeet Hub på en Raspberry Pi

Hubben på Pi:n körs som tjänster i systemd, utan containrar (DRIFT-20). Molnhubben körs i en container i testmiljön (`deploy/testmiljo`).

## Det här behövs

- En Raspberry Pi 4 eller 5 med Raspberry Pi OS (Trixie eller senare, 64-bit). Skrivbordet behövs inte.
- Internet vid installationen och vid en uppdatering. Under träffen behövs inget internet.

## Installera

1. Skriv Raspberry Pi OS på minneskortet med Raspberry Pi Imager. Välj ett namn på Pi:n, till exempel `trainmeet`, och ställ in Wi-Fi och SSH där.
2. Starta Pi:n och logga in med SSH.
3. Hämta installationen och kör den:

   ```sh
   curl -fsSLO https://github.com/beahead-ab/trainmeet/releases/download/pi-senaste/install.sh
   sudo sh install.sh
   ```

4. Öppna `http://trainmeet.local/` i webbläsaren. Byt `trainmeet` mot namnet du gav Pi:n. Välj hubbens namn och en PIN-kod.

## Vad installationen gör

- Den installerar `python3`, `python3-venv`, `curl` och `avahi-daemon` om de saknas. Den installerar `python3-dbus` om Pi:n kör NetworkManager. Den byter aldrig nätverksprogram.
- Den skapar användaren `trainmeet`. Träffarna, inställningarna och nycklarna hamnar i `/var/lib/trainmeet`, och dit går en uppdatering aldrig.
- Den hämtar Pi-paketet från utgåvan `pi-senaste` och kontrollerar kontrollsumman. Sedan installeras hubben och de låsta beroendena, med sina kontrollsummor, i `/opt/trainmeet/releases/<ändring>`. `/opt/trainmeet/current` pekar på den som körs.
- Den installerar tre tjänster:
  - `trainmeet-hub`, som är hubben på port 80 och körs som `trainmeet`;
  - `trainmeet-network`, som är Pi:ns nätverkstjänst för kortet Pi:ns nät och körs som root, utan TCP, med bara Unix-socket;
  - `trainmeet-update`, som är uppdateringen och startas från kugghjulet.
- Ett USB-minne med FAT eller exFAT monteras i `/media/trainmeet-usb`. Dit kopieras varje drifthändelse (DRIFT-21), och där läses en fil med en ny PIN-kod (H46).

## Uppdatera

Gå till Kugghjulet → Uppdatering → Sök och installera. Det går inte medan en träff pågår. Pi:n hämtar den senaste versionen och startar om hubben. Svarar hubben inte inom en minut går Pi:n tillbaka till versionen före. De tre senaste versionerna sparas.

## Glömd PIN-kod

Det finns två sätt att sätta en ny PIN-kod:

- med kommandot `sudo -u trainmeet /opt/trainmeet/current/venv/bin/python -m hub.pin` på Pi:n (läs in inställningarna först: `set -a; . /etc/trainmeet/hub.env; set +a`);
- med en fil som heter `trainmeet-ny-pin.txt` på ett USB-minne, med den nya PIN-koden på första raden. Sätt i minnet i Pi:n. Filen tas bort när den har lästs.

## Om något går fel

- Hubbens logg: `journalctl -u trainmeet-hub`
- Nätverkstjänsten: `journalctl -u trainmeet-network`
- Uppdateringen: `journalctl -u trainmeet-update`, och `/var/lib/trainmeet/update.json`
