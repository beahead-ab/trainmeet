# Skisser: synken och förarnas API

De här två kontrakten skrivs färdigt i de steg som bygger dem. Här står det som redan är bestämt, så att ingen annan del bygger emot något annat.

## Synkprotokollet, `trainmeet.sync/1` (steg 5)

Ett protokoll för Pi:n mot molnet och för hubb mot hubb (5.6).

- **Följaren ringer alltid ut** till den den följer. Ingen port öppnas på träffen (regel 4).
- **Versioner:** följaren frågar efter senaste version med long-poll och hämtar paket den saknar. Kontrollsumman (`contracts.checksum`) avgör om paketet är helt. Bilagorna har egna kontrollsummor.
- **Under träffen** skickar ledaren sina drifthändelser (`trainmeet.drift/1`, `DriftEvent`) i ordning till följaren. Följaren kvitterar det senaste `seq` den tagit emot, och efter ett avbrott fortsätter ledaren från kvittensen.
- **Epoken:** varje meddelande bär träffens epok. En hubb som ser en högre epok än sin egen slutar fatta beslut och blir följare. *Ta över* höjer epoken och görs bara för hand (4.5).
- **Förslag** från Drift (driftändringar) går samma väg till Planering (4.4).
- **Träffens hem** flyttas med en knapp, till Pi:n före träffen och tillbaka efter (H35).
- **Stationspaketen** lagras som ägarens privata versioner. En sparning ovanpå en äldre version nekas (TKL25).
- **Reläet:** telefoner och molnets TKL ansluter till molnet, som skickar vidare till Pi:n på den förbindelse Pi:n redan har öppen. Push till iPhone och Watch, med *Ge klart* och *Neka* i notisen, går samma väg (F20).
- **Versionsnummer:** protokollet har versionsnummer, så att en Pi och molnet i olika programversioner fortfarande förstår varandra.

## Förarnas API, `trainmeet.driver/1` (steg 7)

För Lokföraren (5.5).

- **Min tjänst:** köruppdraget ur träffpaketet (`duties`) som föraren kör. Drift äger bara vilken tjänst en förare kör.
- **Körplanen** med NU-linjen: tågbesöken i tjänsten med planerad och verklig tid.
- **Incheckning:** föraren checkar in på sin tjänst och sitt tåg.
- **Klockan och tågens läge:** samma klocka som stationsprotokollet, och var förarens tåg står.
- **Inloggning:** med TrainMeet ID, eller med QR eller kod på träffen.
- **Senare:** vad utfartssignalen visar (`signal.exit` i stationsprotokollet).

Köruppdragen planeras och importeras i Planering och Integrationer. Den gamla förar-PDF:en på 600 sidor ersätts av körplanen.
