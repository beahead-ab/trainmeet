// Swedish and English from the start (ST10, CAT-199). Every text has both; the type makes
// a missing English text a compile error. Product names are never translated.

const sv = {
  product: "TrainMeet Catalog",
  skip: "Hoppa till innehållet",
  mainNav: "Huvudmeny",
  phoneNav: "Snabbmeny",
  vehicles: "Fordon",
  meets: "Träffar",
  prototypes: "Förebilder",
  tap: "Blippa",
  switcher: "Appväxlaren",
  switcherButton: "Appväxlaren",
  sameAccount: "samma konto",
  coming: "Kommer senare",
  appHub: "Träffarna",
  appTkl: "Stationerna",
  appCad: "Modulerna",
  appCatalog: "Fordonen",
  appTmbox: "Klarera",
  appDriver: "Köra tåg",
  appId: "Kontot",
  accountButton: "Kontomenyn, {name}",
  trialDetail: "Provinloggning i testmiljön",
  idDetail: "TrainMeet ID",
  help: "Hjälp och fel",
  logIn: "Logga in",
  logOut: "Logga ut",
  fleetOf: "Vagnparken · {name}",
  fleetEmpty: "Vagnparken är tom.",
  fleetEmptyDetail: "Här kommer dina fordon att stå.",
  fleetLoggedOut: "Logga in för att se din vagnpark.",
  meetsEmpty: "Inga träffar än.",
  meetsEmptyDetail: "Packlistorna och resan till träffen kommer att stå här.",
  prototypesEmpty: "Förebildskatalogen är tom.",
  prototypesEmptyDetail: "De granskade förebilderna kommer att stå här.",
  tapTitle: "Blippa",
  tapNotYet: "Blippa är inte i gång än.",
  tapDetail: "Här håller du telefonen mot taggen under ett fordon.",
  loginTrialIntro:
    "Provinloggning i testmiljön. Välj ett provkonto. Allt här är testdata och kan tas bort när som helst.",
  loginIdComing: "Inloggningen med TrainMeet ID kommer snart.",
  loginFailed: "Det gick inte att logga in. Försök igen.",
  loggedInAs: "Du är inloggad som {name}.",
  helpText:
    "Hjälp och fel kommer med TrainMeet ID. Under provet säger du till den som bad dig prova.",
  notFound: "Sidan finns inte.",
  toVehicles: "Till Fordon",
  loading: "Laddar …",
  offline: "Catalog svarar inte. Försök igen om en stund.",
  version: "Version {version}",
  change: "ändring #{pr}",
  localBuild: "lokalt bygge",
  otherLanguage: "English",
  otherLanguageLabel: "Change the language to English",
} as const;

export type TextKey = keyof typeof sv;
type Texts = { readonly [K in TextKey]: string };

const en: Texts = {
  product: "TrainMeet Catalog",
  skip: "Skip to content",
  mainNav: "Main menu",
  phoneNav: "Quick menu",
  vehicles: "Vehicles",
  meets: "Meets",
  prototypes: "Prototypes",
  tap: "Tap",
  switcher: "Apps",
  switcherButton: "Switch app",
  sameAccount: "same account",
  coming: "Coming later",
  appHub: "Meets",
  appTkl: "Stations",
  appCad: "Modules",
  appCatalog: "Rolling stock",
  appTmbox: "Clear trains",
  appDriver: "Drive trains",
  appId: "Account",
  accountButton: "Account menu, {name}",
  trialDetail: "Trial login in the test environment",
  idDetail: "TrainMeet ID",
  help: "Help and errors",
  logIn: "Log in",
  logOut: "Log out",
  fleetOf: "Fleet · {name}",
  fleetEmpty: "Your fleet is empty.",
  fleetEmptyDetail: "Your vehicles will be listed here.",
  fleetLoggedOut: "Log in to see your fleet.",
  meetsEmpty: "No meets yet.",
  meetsEmptyDetail: "Packing lists and the trip to the meet will be listed here.",
  prototypesEmpty: "The prototype catalog is empty.",
  prototypesEmptyDetail: "The reviewed prototypes will be listed here.",
  tapTitle: "Tap",
  tapNotYet: "Tapping is not available yet.",
  tapDetail: "This is where you hold the phone to the tag under a vehicle.",
  loginTrialIntro:
    "Trial login in the test environment. Choose a trial account. Everything here is test data and may be removed at any time.",
  loginIdComing: "Logging in with TrainMeet ID is coming soon.",
  loginFailed: "Could not log in. Please try again.",
  loggedInAs: "You are logged in as {name}.",
  helpText:
    "Help and errors comes with TrainMeet ID. During the trial, tell the person who asked you to try Catalog.",
  notFound: "This page does not exist.",
  toVehicles: "Go to Vehicles",
  loading: "Loading …",
  offline: "Catalog is not answering. Please try again in a moment.",
  version: "Version {version}",
  change: "change #{pr}",
  localBuild: "local build",
  otherLanguage: "Svenska",
  otherLanguageLabel: "Byt språk till svenska",
};

export const TEXTS: Record<Language, Texts> = { sv, en };
export type Language = "sv" | "en";
export const LANGUAGES: readonly Language[] = ["sv", "en"];
const STORED = "trainmeet.language";

/** The text in a language, with {name} and the like filled in. */
export function text(language: Language, key: TextKey, vars: Record<string, string | number> = {}): string {
  return TEXTS[language][key].replace(/\{(\w+)\}/g, (whole, name: string) =>
    name in vars ? String(vars[name]) : whole,
  );
}

/** The language chosen before, or the browser's: Swedish for sv, otherwise English. */
export function startLanguage(stored: string | null, browser: readonly string[]): Language {
  if (stored === "sv" || stored === "en") return stored;
  return browser.some((tag) => tag.toLowerCase().startsWith("sv")) ? "sv" : "en";
}

export function readLanguage(): Language {
  let stored: string | null = null;
  try {
    stored = window.localStorage.getItem(STORED);
  } catch {
    stored = null;
  }
  return startLanguage(stored, navigator.languages ?? [navigator.language]);
}

export function storeLanguage(language: Language): void {
  try {
    window.localStorage.setItem(STORED, language);
  } catch {
    // Private mode: the choice lasts as long as the page.
  }
}
