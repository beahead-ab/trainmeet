// Swedish and English from the start (ST10). Every text has both; the type makes a missing
// English text a compile error. Product names are never translated.

const sv = {
  product: "TrainMeet ID",
  skip: "Hoppa till innehållet",
  mainNav: "Huvudmeny",
  phoneNav: "Snabbmeny",
  account: "Konto",
  clubs: "Klubbar",
  meets: "Träffar",
  tokens: "Tokens",
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
  logIn: "Logga in",
  logOut: "Logga ut",
  loginIntro: "Ett konto för hela TrainMeet: Hubben, TKL, CAD, Catalog och TMBox. Du loggar in med en kod till din e-post.",
  loginFailed: "Det gick inte att logga in. Försök igen.",
  offline: "Det går inte att nå TrainMeet ID just nu. Försök igen om en stund.",
  myAccount: "Mitt konto",
  verified: "verifierad",
  myClubs: "Mina klubbar",
  noClubs: "Du är inte med i någon klubb än.",
  admin: "Administratör",
  member: "Medlem",
  viewer: "Titta",
  editor: "Redigera",
  invitations: "Inbjudningar",
  noInvitations: "Inga inbjudningar väntar på dig.",
  invitedBy: "från {name}",
  yes: "Ja, gå med",
  no: "Nej tack",
  toClub: "Klubb",
  toFleet: "Vagnpark",
  asRole: "som {role}",
  tokensTitle: "TrainMeet tokens",
  tokensLater: "Saldot och köpen av tokens kommer med Tokens.",
  meetsLater: "Träffarna och deras roller kommer här: Arrangör, Trafikledare och de andra rollerna per träff.",
  newClub: "Ny klubb",
  clubName: "Klubbens namn",
  create: "Skapa",
  club: "Klubb",
  members: "Medlemmar · {count}",
  invite: "Bjud in",
  email: "E-post",
  send: "Skicka inbjudan",
  invitedAt: "inbjuden {date} · väntar",
  memberSince: "medlem sedan {date}",
  remove: "Ta bort",
  removeNamed: "Ta bort {name}",
  leave: "Gå ur klubben",
  withdraw: "Ta tillbaka",
  withdrawNamed: "Ta tillbaka inbjudan till {address}",
  invited: "Inbjuden",
  separateTitle: "Klubbar är skilda åt",
  separateText: "En klubb ser bara sina egna träffar, medlemmar och saldo. Roller ges per klubb och per träff.",
  notFound: "Sidan finns inte.",
  toAccount: "Till kontot",
  fleetTitle: "Dela vagnparken",
  fleetIntro: "Dela hela vagnparken med en person, att titta på eller att redigera. Delningen gäller när hen har svarat ja, och du kan sluta dela när du vill.",
  sharedWith: "Delad med",
  notShared: "Vagnparken är inte delad med någon.",
  right: "Rätt",
  share: "Dela",
  stopSharing: "Sluta dela",
  stopSharingNamed: "Sluta dela med {name}",
  sentTo: "Inbjudan till {address}",
  problem_login: "Logga in först.",
  problem_not_found: "Det finns inte, eller så får du inte se det.",
  problem_forbidden: "Det får du inte göra här.",
  problem_invalid: "Kontrollera det du skrev.",
  problem_conflict: "Det går inte just nu.",
  problem_unavailable: "Inbjudan gick inte att skicka. Försök igen om en stund.",
  otherLanguage: "English",
  otherLanguageLabel: "Change the language to English",
};

export type TextKey = keyof typeof sv;
type Texts = Record<TextKey, string>;

const en: Texts = {
  product: "TrainMeet ID",
  skip: "Skip to the content",
  mainNav: "Main menu",
  phoneNav: "Quick menu",
  account: "Account",
  clubs: "Clubs",
  meets: "Meets",
  tokens: "Tokens",
  switcher: "App switcher",
  switcherButton: "App switcher",
  sameAccount: "same account",
  coming: "Coming later",
  appHub: "The meets",
  appTkl: "The stations",
  appCad: "The modules",
  appCatalog: "The vehicles",
  appTmbox: "Clearances",
  appDriver: "Drive trains",
  appId: "The account",
  accountButton: "Account menu, {name}",
  logIn: "Log in",
  logOut: "Log out",
  loginIntro: "One account for all of TrainMeet: the Hub, TKL, CAD, Catalog and TMBox. You log in with a code sent to your e-mail.",
  loginFailed: "Could not log in. Please try again.",
  offline: "TrainMeet ID cannot be reached right now. Please try again in a moment.",
  myAccount: "My account",
  verified: "verified",
  myClubs: "My clubs",
  noClubs: "You are not in a club yet.",
  admin: "Administrator",
  member: "Member",
  viewer: "View",
  editor: "Edit",
  invitations: "Invitations",
  noInvitations: "No invitations are waiting for you.",
  invitedBy: "from {name}",
  yes: "Yes, join",
  no: "No thanks",
  toClub: "Club",
  toFleet: "Fleet",
  asRole: "as {role}",
  tokensTitle: "TrainMeet tokens",
  tokensLater: "The balance and buying tokens come with Tokens.",
  meetsLater: "The meets and their roles will be here: organizer, dispatcher and the other roles per meet.",
  newClub: "New club",
  clubName: "The club's name",
  create: "Create",
  club: "Club",
  members: "Members · {count}",
  invite: "Invite",
  email: "E-mail",
  send: "Send the invitation",
  invitedAt: "invited {date} · waiting",
  memberSince: "member since {date}",
  remove: "Remove",
  removeNamed: "Remove {name}",
  leave: "Leave the club",
  withdraw: "Take back",
  withdrawNamed: "Take back the invitation to {address}",
  invited: "Invited",
  separateTitle: "Clubs are kept apart",
  separateText: "A club only sees its own meets, members and balance. Roles are given per club and per meet.",
  notFound: "The page does not exist.",
  toAccount: "To the account",
  fleetTitle: "Share the fleet",
  fleetIntro: "Share the whole fleet with one person, to look at or to edit. The sharing applies once they have said yes, and you can stop sharing at any time.",
  sharedWith: "Shared with",
  notShared: "The fleet is not shared with anyone.",
  right: "Right",
  share: "Share",
  stopSharing: "Stop sharing",
  stopSharingNamed: "Stop sharing with {name}",
  sentTo: "Invitation to {address}",
  problem_login: "Log in first.",
  problem_not_found: "It does not exist, or you may not see it.",
  problem_forbidden: "You may not do that here.",
  problem_invalid: "Check what you typed.",
  problem_conflict: "That is not possible right now.",
  problem_unavailable: "The invitation could not be sent. Please try again in a moment.",
  otherLanguage: "Svenska",
  otherLanguageLabel: "Byt språk till svenska",
};

export type Language = "sv" | "en";
export const TEXTS: Record<Language, Texts> = { sv, en };
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
