// The Ställverket page's own texts at level 1–2, in Swedish and English. The interlocking
// answers in Swedish (contracts/tkl.py, TklAnswer), and that reason is shown as it was given;
// these are the page's words around it. A missing English text is a compile error.
export type Language = "sv" | "en";
export const LANGUAGES: Language[] = ["sv", "en"];

const T = {
  level: { sv: "Nivå {n}", en: "Level {n}" },
  levelText: {
    sv: "Ställverket på nivå 1–2: klicka på startsignalen och målet. Tågnumret följer knapparna.",
    en: "The interlocking at level 1–2: click the start signal and the goal. The train number follows the buttons.",
  },
  loading: { sv: "Hämtar ställverket …", en: "Fetching the interlocking …" },
  panel: { sv: "Ställverkets panel", en: "The interlocking's panel" },
  screen: { sv: "Skärm {n}", en: "Screen {n}" },
  shows: { sv: "Visar", en: "Shows" },
  viewAll: { sv: "Ställverket", en: "Interlocking" },
  viewPanel: { sv: "Spårplanen", en: "Track plan" },
  viewRow: { sv: "Tåg · Klarering · Händelser", en: "Trains · Clearance · Events" },
  skin: { sv: "Skal", en: "Skin" },
  coming: { sv: "kommer", en: "coming" },
  proportion: { sv: "Proportion", en: "Proportion" },
  newScreen: { sv: "Ny skärm ›", en: "New screen ›" },
  otherLanguage: { sv: "In English", en: "På svenska" },
  screenNote: {
    sv: "Skal, proportion och vy sparas per skärm i webbläsaren. Ett byte skickar aldrig några order.",
    en: "Skin, proportion and view are kept per screen in this browser. A change never sends an order.",
  },
  // The choice of a route (STV-01, STV-03, STV-24)
  chooseStart: {
    sv: "Klicka på en startsignal. Klicka på en växel för att lägga spaken.",
    en: "Click a start signal. Click a switch to lay its lever.",
  },
  chooseTrain: {
    sv: "Tågväg från {start}: klicka på målet. Klicka på {start} igen för växlingsväg. Esc avbryter.",
    en: "Train route from {start}: click the goal. Click {start} again for a shunting route. Esc cancels.",
  },
  chooseTrainOnly: {
    sv: "Tågväg från {start}: klicka på målet. Esc avbryter.",
    en: "Train route from {start}: click the goal. Esc cancels.",
  },
  chooseShunting: {
    sv: "Växlingsväg från {start}: klicka på målet. Klicka på {start} igen för att avbryta.",
    en: "Shunting route from {start}: click the goal. Click {start} again to cancel.",
  },
  noTargets: { sv: "Inga vägar börjar vid {start}.", en: "No routes start at {start}." },
  targetsCount: { sv: "{n} mål", en: "{n} goals" },
  cancelled: { sv: "Valet avbrutet.", en: "Choice cancelled." },
  // A set route and its buttons (STV-01, STV-06, STV-16)
  routes: { sv: "Lagda vägar", en: "Set routes" },
  noRoutes: { sv: "Inga vägar lagda.", en: "No routes set." },
  trainRoute: { sv: "Tågväg", en: "Train route" },
  shuntingRoute: { sv: "Växlingsväg", en: "Shunting route" },
  step: { sv: "Kör", en: "Run" },
  arrive: { sv: "Ankommit", en: "Arrived" },
  depart: { sv: "Avgått", en: "Departed" },
  release: { sv: "Lös ut", en: "Release" },
  emergency: { sv: "Nödutlös", en: "Emergency release" },
  confirmEmergency: { sv: "Bekräfta nödutlösningen av {route}", en: "Confirm the emergency release of {route}" },
  cancel: { sv: "Avbryt", en: "Cancel" },
  reset: { sv: "Nollställ ställverket", en: "Reset the interlocking" },
  confirmReset: { sv: "Bekräfta nollställningen", en: "Confirm the reset" },
  chosenRoute: { sv: "Vald väg", en: "Chosen route" },
  noTrainYet: { sv: "inget tåg än", en: "no train yet" },
  // Trains (STV-07, STV-10, STV-15)
  trains: { sv: "Tåg", en: "Trains" },
  trainsSub: { sv: "i ställverket och från Hubben", en: "in the interlocking and from the hub" },
  inInterlocking: { sv: "I ställverket", en: "In the interlocking" },
  noTrains: { sv: "Inga tågnummer i ställverket.", en: "No train numbers in the interlocking." },
  onTheLine: { sv: "på linjen vid {exit}", en: "on the line at {exit}" },
  onSection: { sv: "i {section}", en: "on {section}" },
  remove: { sv: "Ta bort", en: "Remove" },
  comingHere: { sv: "På väg hit", en: "On their way here" },
  noneComing: { sv: "Inga tåg på väg hit.", en: "No trains on their way here." },
  from: { sv: "från {place}", en: "from {place}" },
  putAtEntry: { sv: "Sätt ut vid infarten", en: "Put at the entry" },
  alreadyIn: { sv: "står i ställverket", en: "is in the interlocking" },
  putTrain: { sv: "Sätt ut ett tågnummer", en: "Put a train number" },
  trainNumber: { sv: "Tågnummer", en: "Train number" },
  where: { sv: "Var", en: "Where" },
  put: { sv: "Sätt ut", en: "Put" },
  track: { sv: "Spår {track}", en: "Track {track}" },
  lineAt: { sv: "Linjen vid {exit}", en: "The line at {exit}" },
  atStation: { sv: "På stationen", en: "At the station" },
  noneAtStation: { sv: "Inga tåg på stationen.", en: "No trains at the station." },
  towards: { sv: "mot {place}", en: "towards {place}" },
  endsHere: { sv: "slutstation", en: "ends here" },
  trainsNote: {
    sv: "Utan detektering följer tågnumret knapparna: Kör flyttar det en sektion i taget, och Ankommit och Avgått går till Hubben.",
    en: "Without detection the train number follows the buttons: Run moves it one section at a time, and Arrived and Departed go to the hub.",
  },
  notConnected: { sv: "TKL är inte ansluten till en träff.", en: "TKL is not connected to a meet." },
  clearance: { sv: "Klarering", en: "Clearance" },
  // Händelser
  events: { sv: "Händelser", en: "Events" },
  eventsSub: { sv: "senaste först", en: "latest first" },
  noEvents: { sv: "Inget har hänt i ställverket än.", en: "Nothing has happened in the interlocking yet." },
  refused: { sv: "Nej", en: "No" },
  fromHub: { sv: "Från Hubben", en: "From the hub" },
  // The panel's own words
  signal: { sv: "Signal {name}", en: "Signal {name}" },
  switchLabel: { sv: "Växel {name}", en: "Switch {name}" },
  point: { sv: "Mål {name}", en: "Goal {name}" },
  locked: { sv: "låst i väg {routes}", en: "locked in route {routes}" },
  protection: { sv: "låst som skydd", en: "locked as protection" },
  notLaid: { sv: "läggs inte av TKL", en: "not laid by TKL" },
  estimated: { sv: "uppskattad position", en: "estimated position" },
  legendFree: { sv: "Ledigt", en: "Free" },
  legendTrain: { sv: "Tågväg", en: "Train route" },
  legendShunting: { sv: "Växlingsväg", en: "Shunting route" },
  legendOccupied: { sv: "Belagt", en: "Occupied" },
  legendGap: { sv: "Glapp vid växeln = benet som inte ligger", en: "Gap at the switch = the leg it does not lie in" },
  legendProtection: { sv: "Kort gult vid knuten = växel låst som skydd", en: "Short yellow at the switch = locked as protection" },
  legendSignals: {
    sv: "Huvudsignal triangel, dvärgsignal fylld pil, rött = slutpunkt",
    en: "Main signal triangle, dwarf signal filled arrow, red = end point",
  },
  legendNumbers: {
    sv: "Tågnummer: rött där tåget är, grönt i vägens sista sektion, ram = uppskattad position",
    en: "Train number: red where the train is, green in the route's last section, frame = estimated position",
  },
  skinName85: { sv: "85 · efter Trafikverkets TDOK 2014:0693", en: "85 · after Trafikverket's TDOK 2014:0693" },
} satisfies Record<string, Record<Language, string>>;

export type TextKey = keyof typeof T;
export type Say = (key: TextKey, vars?: Record<string, string | number>) => string;

/** A text in the language, with {name} filled in from vars. */
export function text(language: Language, key: TextKey, vars: Record<string, string | number> = {}): string {
  return T[key][language].replace(/\{(\w+)\}/g, (whole, name: string) => (name in vars ? String(vars[name]) : whole));
}

export const TEXTS = T;

const STORED = "tkl.sprak";

/** The page's language: the one chosen in this browser, else Swedish, TKL's own. */
export function readLanguage(storage: Pick<Storage, "getItem"> | null): Language {
  const found = storage?.getItem(STORED);
  return found === "en" ? "en" : "sv";
}

export function saveLanguage(language: Language, storage: Pick<Storage, "setItem"> | null): void {
  storage?.setItem(STORED, language);
}
