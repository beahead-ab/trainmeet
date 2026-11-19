// Studio › Inställningar › Stream Deck (#86 del c, SD38): where the owner adapts the decks, with
// the tabs Sidor, Deck and Prova.
//
// Sidor (SD41–SD45): the size and the mode's pages; the list Knappar from the station model to
// the left, the deck in the right size in the middle, drawn as the deck on the screen draws it,
// with drag and drop from the list and between the cells, and the chosen key's properties to the
// right: its text, the line under, what a press and a hold do from the fixed list, and what it
// shows. Never its colours, symbols or what a gesture means (SD3, SD43): TKL's server refuses
// those with the reason. Above the deck a miniature of the track plan shows the chosen key's
// route, and a click on a start and a goal there makes a new snabbväg (SD42). Under it the
// checks (SD44) and Att kolla (SD40), each clickable, Föreslå (SD45), Återställ for a page or the
// whole size, and Spara: the changes are kept with the station's model and versioned with it.
//
// Deck (SD46, SD58, SD35, SD36): the decks on this computer, how each is connected and whether
// its model is tried with a real deck, Koppla in with WebHID, and per deck Blinka, ljusstyrka,
// hålltid, släckning, lås, the start page and the workplace. Glöm deck forgets one.
//
// Prova (SD47): Prova alla knappar presses every key against an empty interlocking in the
// background, with the progress, and says per key what it did.
//
// Roll (#87 del d): Sidor and Prova show the tågklarerare's deck or a part's, the shunter's deck
// Bangård, with its own changes per size; under Deck each deck gets its role.
import { FjarrStudio } from "./FjarrStudio";
import { useCallback, useEffect, useRef, useState, type DragEvent, type ReactNode } from "react";
import {
  api,
  Problem,
  type DeckButton,
  type DeckChange,
  type DeckDeviation,
  type DeckFavourites,
  type DeckKey,
  type DeckMode,
  type DeckModelId,
  type DeckPage,
  type DeckProblem,
  type DeckProva,
  type DeckRole,
  type Decks,
  type DeckStatus,
  type DeckStudio,
  type DeckSuggestion,
  type Panel,
  type Route,
} from "./api";
import { DeckKey as DeckKeyFace, hidApi } from "./Deck";
import { REMOTE_ROLE } from "./deck";
import { connect, hasHid, NOT_HERE, OWNED, type HidDeck } from "./deckhid";
import { PanelView } from "./Sparplan";
import {
  ACTION_NAMES,
  bare,
  changesText,
  checkText,
  connectionText,
  deckChange,
  DEFAULT_GESTURE,
  dropped,
  edited,
  freeCell,
  fullKey,
  GROUPS,
  HOLD,
  HOLDS,
  keyId,
  keyWords,
  MODE_NAMES,
  NOT_ON_A_PEDAL,
  PEDAL_ACTIONS,
  pageAdded,
  pageMoved,
  pageRemoved,
  pageReset,
  pedalChosen,
  pedalKey,
  pedalValue,
  PRESS,
  refOf,
  removed,
  routeKey,
  sizeOfModel,
  SLEEPS,
  SUGGESTIONS,
  TYPE_NAMES,
  whereToCheck,
  type Dragged,
  type Look,
  type Tab,
} from "./streamdeck";
import "./streamdeck.css";

const KEY = 64;
const POLL_MS = 400;
const DECKS_MS = 3000;
const SHOWN_PROBLEMS = 20;

export const TABS: [Tab, string][] = [
  ["sidor", "Sidor"],
  ["deck", "Deck"],
  ["prova", "Prova"],
];

const message = (error: unknown, fallback: string) => (error instanceof Error ? error.message : fallback);

// --- Sidor ---------------------------------------------------------------------------------

export type SidorProps = {
  studio: DeckStudio;
  mode: DeckMode | null;
  page: number;
  chosen: number | null;
  listed: number | null;
  filter: string;
  panel: Panel | null;
  start: string | null;
  lit: Route | null;
  busy: boolean;
  said: string;
  problems: string[];
  newPage: string;
  onSize: (size: DeckModelId) => void;
  onRole?: (part: string | null) => void;
  onMode: (mode: DeckMode) => void;
  onPage: (page: number) => void;
  onChoose: (cell: number | null) => void;
  onChooseButton: (index: number | null) => void;
  onFilter: (text: string) => void;
  onDrop: (cell: number, dragged: Dragged) => void;
  onEdit: (change: Partial<Look>) => void;
  onRemove: () => void;
  onSignal: (name: string) => void;
  onSuggest: (rule: DeckSuggestion) => void;
  onResetPage: () => void;
  onResetSize: () => void;
  onSave: () => void;
  onUndo: () => void;
  onNewPage: (name: string) => void;
  onAddPage: () => void;
  onRemovePage: () => void;
  onMovePage: (step: -1 | 1) => void;
  onPedal: (pedal: number, value: string) => void;
  onForgetChange: (deviation: number) => void;
  onGo: (page: number, cell: number | null) => void;
  onProblem: (problem: DeckProblem) => void;
};

/** The pages of the mode, in order: the listed ones and a part's pages after its parts. */
export function pagesOf(studio: DeckStudio, mode: DeckMode | null): number[] {
  return (studio.profile.pages ?? []).flatMap((p, i) => (p.mode === mode ? [i] : []));
}

export function SidorView(props: SidorProps) {
  const { studio } = props;
  const profile = studio.profile;
  const pedal = (profile.grid.pedals ?? 0) > 0 && profile.grid.columns * profile.grid.rows === 0;
  return (
    <div className="sds-sidor">
      <div className="sds-val">
        {(studio.roles ?? []).length > 1 ? (
          <>
            <span className="sds-etikett">Roll</span>
            <RoleChoice roles={studio.roles ?? []} part={studio.part ?? null} onRole={props.onRole} />
          </>
        ) : null}
        <span className="sds-etikett">Storlek</span>
        <div className="sds-segment" role="group" aria-label="Storlek">
          {(studio.sizes ?? []).map((s) => (
            <button key={s.size} type="button" aria-pressed={s.size === studio.size} onClick={() => props.onSize(s.size)} title={s.decks ? `${s.decks} deck här` : undefined}>
              {s.name}
              {s.deviations ? <span className="sds-prick" aria-hidden="true" title={`${s.deviations} egna ändringar`} /> : null}
              {s.to_check || s.problems ? <span className="sds-varning-prick" aria-hidden="true" title={`${(s.to_check ?? 0) + (s.problems ?? 0)} att kolla`} /> : null}
            </button>
          ))}
        </div>
        {!pedal ? (
          <>
            <span className="sds-etikett">Läge</span>
            <div className="sds-segment" role="group" aria-label="Läge">
              {(profile.modes ?? []).map((m) => (
                <button key={m} type="button" aria-pressed={m === props.mode} onClick={() => props.onMode(m)}>
                  {MODE_NAMES[m]}
                </button>
              ))}
            </div>
          </>
        ) : null}
      </div>
      {pedal ? <PedalView {...props} /> : <PagesView {...props} />}
      <Footer {...props} pedal={pedal} />
    </div>
  );
}

/** Roll (#87 del d): the tågklarerare's deck, or a part's, the shunter's deck Bangård. */
export function RoleChoice({ roles, part, onRole, label = "Roll" }: { roles: DeckRole[]; part: string | null; onRole?: (part: string | null) => void; label?: string }) {
  return (
    <div className="sds-segment" role="group" aria-label={label}>
      {roles.map((r) => (
        <button key={r.part ?? ""} type="button" aria-pressed={(r.part ?? null) === part} onClick={() => onRole?.(r.part ?? null)}>
          {r.name}
        </button>
      ))}
    </div>
  );
}

function PagesView(props: SidorProps) {
  const { studio, page: at } = props;
  const shownPage = studio.profile.pages?.[at];
  return (
    <div className="sds-tre">
      <Knappar {...props} />
      <section className="sds-mitt ruta" aria-label="Decket">
        <PageTabs {...props} />
        <Miniature {...props} />
        {shownPage ? <DeckEditor {...props} /> : <p className="tom">Läget har inga sidor i den här storleken.</p>}
        {shownPage ? <p className="liten sds-fast">{fixedText(studio)}</p> : null}
        <Checks {...props} />
      </section>
      <Properties {...props} />
    </div>
  );
}

function fixedText(studio: DeckStudio): string {
  const style = studio.profile.style;
  if (style === "next") return "Sista knappen är fast: ▶ och håll in för Läge.";
  if (style === "last") return "Sista knappen är fast: Läge.";
  if (style === "column") return "Högra kolumnen är fast: samma knappar på alla sidor.";
  return "Nedersta raden är fast: samma knappar på alla sidor.";
}

function PageTabs(props: SidorProps) {
  const { studio, mode, page } = props;
  const pages = studio.profile.pages ?? [];
  const current = pages[page];
  const listed = !!current && (current.listed ?? true) && current.kind !== "del";
  return (
    <div className="sds-flikar">
      <div className="sds-sidflikar" role="tablist" aria-label="Sidorna">
        {pagesOf(studio, mode).map((i) => {
          const p = pages[i] as DeckPage;
          const changed = studio.pages?.[i]?.changed;
          return (
            <button key={i} type="button" role="tab" aria-selected={i === page} className={(p.listed ?? true) ? "" : "del"} data-changed={changed ? "ja" : undefined} title={changed ? "Sidan har egna ändringar" : undefined} onClick={() => props.onPage(i)}>
              {p.name}
              {changed ? <span className="sds-prick" aria-hidden="true" /> : null}
            </button>
          );
        })}
      </div>
      <div className="sds-sidval">
        <input aria-label="Ny sida, namn" placeholder="Ny sida" value={props.newPage} maxLength={40} onChange={(e) => props.onNewPage(e.target.value)} />
        <button type="button" disabled={!props.newPage.trim() || props.busy} onClick={props.onAddPage}>
          + Sida
        </button>
        <button type="button" disabled={!listed || props.busy} onClick={() => props.onMovePage(-1)} aria-label="Flytta sidan bakåt">
          ◀
        </button>
        <button type="button" disabled={!listed || props.busy} onClick={() => props.onMovePage(1)} aria-label="Flytta sidan framåt">
          ▶
        </button>
        <button type="button" className="lank" disabled={!listed || props.busy} onClick={props.onRemovePage}>
          Ta bort sidan
        </button>
      </div>
    </div>
  );
}

/** The miniature of the track plan (SD42): the chosen key's route, and a start and a goal
 * clicked there make a snabbväg. */
function Miniature({ panel, lit, start, onSignal, studio, page, chosen }: SidorProps) {
  if (!panel) return <p className="liten">Spårplanen kommer …</p>;
  const key = chosen !== null ? studio.profile.pages?.[page]?.keys[chosen] : null;
  const words = key?.route ? `Knappen lägger ${key.route.kind === "train" ? "tågvägen" : "växlingsvägen"} ${key.route.start} → ${key.route.end}.` : lit ? `Vägen ${lit.start} → ${lit.end}.` : "";
  return (
    <div className="sds-miniatyr">
      <PanelView panel={panel} form="schematic" route={lit} onSignal={onSignal} marked={start ? [start] : []} />
      <p className="liten">
        {words} {start ? `Start ${start}: klicka målet.` : "Klicka start och mål i bilden för att göra en ny knapp."}
      </p>
    </div>
  );
}

/** A key's size in Studio: the deck on the screen's, smaller for the wide decks. */
export function keySize(columns: number): number {
  return columns > 12 ? 40 : columns > 7 ? 52 : KEY;
}

function dragData(event: DragEvent): Dragged | null {
  try {
    const found = JSON.parse(event.dataTransfer.getData("text/plain")) as Dragged;
    return found && (found.from === "list" || found.from === "cell") ? found : null;
  } catch {
    return null;
  }
}

/** The deck in the right size, as the deck on the screen draws it, with drag and drop (SD41). */
function DeckEditor({ studio, page, chosen, listed, onChoose, onDrop, ...rest }: SidorProps) {
  const profile = studio.profile;
  const faces = studio.pages?.[page]?.faces ?? [];
  const keys = profile.pages?.[page]?.keys ?? [];
  const fixed = profile.fixed ?? [];
  const columns = profile.grid.columns;
  // The wide decks get smaller keys, so that the whole deck stands between the list and the key.
  const size = keySize(columns);
  return (
    <div className="sds-deck" data-size={studio.size}>
      <div className="sds-grid" style={{ gridTemplateColumns: `repeat(${columns}, ${size}px)` }} role="group" aria-label="Knapparna på sidan">
        {faces.map((face, i) => {
          const key = keys[i];
          const isFixed = fixed.includes(i);
          const label = key ? face.label || face.text || TYPE_NAMES[key.type] : listed !== null ? "Släpp här" : `Tom knapp ${i + 1}`;
          return (
            <button
              key={i}
              type="button"
              className={`sds-ruta${i === chosen ? " vald" : ""}${!key && listed !== null && !isFixed ? " slapp" : ""}`}
              style={{ width: size, height: size }}
              data-cell={i}
              data-fixed={isFixed ? "ja" : undefined}
              aria-label={`${label}${isFixed ? " (fast)" : ""}`}
              aria-pressed={i === chosen}
              draggable={!!key && !isFixed}
              onDragStart={(e) => e.dataTransfer.setData("text/plain", JSON.stringify({ from: "cell", cell: i } satisfies Dragged))}
              onDragOver={(e) => {
                if (!isFixed) e.preventDefault();
              }}
              onDrop={(e) => {
                e.preventDefault();
                const found = dragData(e);
                if (found && !isFixed) onDrop(i, found);
              }}
              onClick={() => {
                if (listed !== null && !isFixed) onDrop(i, { from: "list", index: listed });
                else onChoose(key ? i : null);
              }}
            >
              {key ? <DeckKeyFace face={face} now={0} plan={null} size={size - 4} /> : <span className="sds-tom">{listed !== null && !isFixed ? "Släpp här" : ""}</span>}
            </button>
          );
        })}
      </div>
      {rest.busy ? <p className="liten">Räknar …</p> : null}
    </div>
  );
}

function Knappar({ studio, filter, listed, onFilter, onChooseButton }: SidorProps) {
  const wanted = filter.trim().toLowerCase();
  const buttons = studio.buttons ?? [];
  return (
    <section className="sds-knappar ruta" aria-label="Knappar">
      <h2>Knappar</h2>
      <input aria-label="Sök bland stationens vägar och funktioner" placeholder="21, spår 3, lös ut" value={filter} onChange={(e) => onFilter(e.target.value)} />
      <p className="liten">Dra en knapp till decket, eller välj den och klicka en ruta.</p>
      {GROUPS.map(([group, title]) => {
        const rows = buttons.map((b, i) => [b, i] as const).filter(([b]) => b.group === group && (!wanted || `${b.text} ${b.where}`.toLowerCase().includes(wanted)));
        if (!rows.length) return null;
        return (
          <div key={group} className="sds-grupp">
            <h3>
              {title} · {rows.length}
            </h3>
            <ul>
              {rows.map(([b, i]) => (
                <li key={i}>
                  <button
                    type="button"
                    className={`sds-rad${listed === i ? " vald" : ""}${b.missing ? " saknas" : ""}`}
                    draggable
                    aria-pressed={listed === i}
                    onDragStart={(e) => e.dataTransfer.setData("text/plain", JSON.stringify({ from: "list", index: i } satisfies Dragged))}
                    onClick={() => onChooseButton(listed === i ? null : i)}
                  >
                    <span className="sds-handtag" aria-hidden="true">
                      ⠿
                    </span>
                    <span className="sds-radtext">{b.text}</span>
                    <span className="liten sds-var">{b.missing ? "nås inte" : b.where}</span>
                  </button>
                </li>
              ))}
            </ul>
          </div>
        );
      })}
    </section>
  );
}

/** The chosen key's properties: what the owner may change (SD43), and what is locked (SD3). */
function Properties({ studio, page, chosen, busy, onEdit, onRemove }: SidorProps) {
  const key = chosen !== null ? studio.profile.pages?.[page]?.keys[chosen] : null;
  const fixed = chosen !== null && (studio.profile.fixed ?? []).includes(chosen);
  if (!key || chosen === null) {
    return (
      <section className="sds-knappen ruta" aria-label="Knappen">
        <h2>Knappen</h2>
        <p className="liten">Välj en knapp på decket för att se och ändra den.</p>
      </section>
    );
  }
  const press = fixed ? undefined : PRESS[key.type];
  const hold = fixed ? undefined : HOLD[key.type];
  const locked = busy || fixed;
  const gesture = DEFAULT_GESTURE[key.type];
  const choice = (title: string, value: string | null | undefined, allowed: typeof press, fallback: string | undefined, field: "press" | "hold") => (
    <label>
      {title}
      {allowed ? (
        <select aria-label={title} value={value ?? ""} disabled={busy} onChange={(e) => onEdit({ [field]: e.target.value || null })}>
          <option value="">{`Som katalogen: ${fallback ?? ""}`}</option>
          {allowed.map((a) => (
            <option key={a} value={a}>
              {ACTION_NAMES[a]}
            </option>
          ))}
        </select>
      ) : (
        <span className="liten">{fixed ? "Låst: den fasta raden är densamma på alla sidor (SD27)." : `Låst: ${TYPE_NAMES[key.type].toLowerCase()} gör det katalogen säger, lika på alla stationer (SD3).`}</span>
      )}
    </label>
  );
  return (
    <section className="sds-knappen ruta" aria-label="Knappen">
      <h2>Knappen</h2>
      <dl>
        <dt>Typ</dt>
        <dd>{TYPE_NAMES[key.type]}</dd>
        <dt>Gör</dt>
        <dd>{keyWords(key)}</dd>
      </dl>
      <p className="liten">Färgerna och symbolerna följer standarden och går inte att ändra (SD3).</p>
      <div className="sds-text">
        <label>
          Text
          <input key={`t-${keyId(key)}-${key.text ?? ""}`} aria-label="Text" defaultValue={key.text ?? ""} maxLength={60} disabled={locked} onBlur={(e) => e.target.value !== (key.text ?? "") && onEdit({ text: e.target.value })} />
        </label>
        <label>
          Undertext
          <input key={`u-${keyId(key)}-${key.under ?? ""}`} aria-label="Undertext" defaultValue={key.under ?? ""} maxLength={60} disabled={locked} onBlur={(e) => e.target.value !== (key.under ?? "") && onEdit({ under: e.target.value })} />
        </label>
      </div>
      {choice("Tryck", key.press, press, gesture?.[0], "press")}
      {choice("Håll in", key.hold, hold, gesture?.[1], "hold")}
      {key.type === "route" ? (
        <>
          <label className="kryss">
            <input type="checkbox" checked={key.number !== false} disabled={locked} onChange={(e) => onEdit({ number: e.target.checked })} /> Visa tågnumret på målspåret
          </label>
          <label className="kryss">
            <input type="checkbox" checked={key.dim !== false} disabled={locked} onChange={(e) => onEdit({ dim: e.target.checked })} /> Tona ned när vägen är hindrad
          </label>
        </>
      ) : null}
      <label className="kryss">
        <input type="checkbox" checked={!!key.confirm} disabled={locked} onChange={(e) => onEdit({ confirm: e.target.checked })} /> Fråga en gång till före trycket
      </label>
      <button type="button" disabled={fixed || busy} onClick={onRemove}>
        Ta bort från sidan
      </button>
      {fixed ? <p className="liten">Den fasta raden är densamma på alla sidor (SD27).</p> : null}
    </section>
  );
}

/** Studio's checks (SD44) and Att kolla (SD40), each clickable. */
function Checks({ studio, onGo, onProblem, onForgetChange }: SidorProps) {
  const checked = checkText(studio.checks);
  const problems = studio.checks.problems ?? [];
  const toCheck = studio.to_check ?? [];
  return (
    <div className="sds-kontroller">
      <div className="sds-chips">
        <span className={`tm-chip ${checked.ok ? "gron" : "rod"}`}>{checked.text}</span>
        <span className="tm-chip gul">{changesText((studio.deviations ?? []).length)}</span>
        {toCheck.length ? <span className="tm-chip gul">{toCheck.length} att kolla</span> : null}
      </div>
      {toCheck.length ? (
        <ul className="sds-attkolla" aria-label="Att kolla">
          {toCheck.map((c) => {
            const where = whereToCheck(studio.profile, c);
            return (
              <li key={c.deviation} className="varning">
                <span>
                  <b>Att kolla.</b> {c.text}
                </span>
                {where ? (
                  <button type="button" className="lank" onClick={() => onGo(where.page, where.cell)}>
                    Visa
                  </button>
                ) : null}
                <button type="button" onClick={() => onForgetChange(c.deviation)}>
                  Ta bort ändringen
                </button>
              </li>
            );
          })}
        </ul>
      ) : null}
      {problems.length ? (
        <ul className="sds-problem" aria-label="Kontrollerna">
          {problems.slice(0, SHOWN_PROBLEMS).map((p, i) => (
            <li key={i}>
              <button type="button" className="lank" onClick={() => onProblem(p)}>
                {p.text}
              </button>
            </li>
          ))}
          {problems.length > SHOWN_PROBLEMS ? <li className="liten">och {problems.length - SHOWN_PROBLEMS} till</li> : null}
        </ul>
      ) : null}
    </div>
  );
}

function Footer(props: SidorProps & { pedal: boolean }) {
  const { studio, busy } = props;
  return (
    <div className="fot rad sds-fot">
      {!props.pedal ? (
        <>
          <button type="button" disabled={busy} onClick={props.onResetPage}>
            Återställ sidan
          </button>
          <span className="sds-foresla">
            Föreslå sidan:
            {SUGGESTIONS.map(([rule, name]) => (
              <button key={rule} type="button" disabled={busy} onClick={() => props.onSuggest(rule)}>
                {name}
              </button>
            ))}
          </span>
        </>
      ) : null}
      <button type="button" className="lank" disabled={busy || !(studio.deviations ?? []).length} onClick={props.onResetSize}>
        Återställ hela storleken
      </button>
      <span className="tm-fyll" />
      {props.said ? (
        <span className={props.problems.length ? "liten fel-text" : "liten"} role="status">
          {props.said}
        </span>
      ) : null}
      {!studio.saved ? (
        <button type="button" className="lank" disabled={busy} onClick={props.onUndo}>
          Ångra
        </button>
      ) : null}
      <button type="button" className="primar" disabled={busy || !!studio.saved} onClick={props.onSave}>
        Spara
      </button>
      {props.problems.length ? (
        <ul className="problem">
          {props.problems.map((p) => (
            <li key={p}>{p}</li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}

/** The pedal (SD55): three pedals, nothing until the owner chooses a function for each. */
function PedalView({ studio, busy, onPedal }: SidorProps) {
  const pedals = studio.profile.pedals ?? [];
  const buttons = studio.buttons ?? [];
  const routes = buttons.filter((b) => b.key.type === "route");
  const panels = buttons.filter((b) => b.key.type === "panel");
  return (
    <section className="ruta sds-pedal" aria-label="Pedalerna">
      <h2>Pedalerna</h2>
      <p className="liten">Pedalen har ingen skärm och inget förval: den gör ingenting förrän en funktion är vald. Lös ut alla, Noll och Nödutlösning går inte att lägga på en pedal (SD55).</p>
      <div className="sds-pedaler">
        {pedals.map((key, i) => (
          <label key={i}>
            {["Vänster", "Mitten", "Höger"][i] ?? `Pedal ${i + 1}`}
            <select aria-label={`Pedal ${i + 1}`} value={pedalValue(key)} disabled={busy} onChange={(e) => onPedal(i, e.target.value)}>
              <option value="">Ingenting</option>
              <optgroup label="Funktioner">
                {PEDAL_ACTIONS.filter((a) => !NOT_ON_A_PEDAL.includes(a)).map((a) => (
                  <option key={a} value={`action:${a}`}>
                    {ACTION_NAMES[a]}
                  </option>
                ))}
                {panels.map((b) => (
                  <option key={b.text} value={pedalValue(b.key)}>
                    {b.text}
                  </option>
                ))}
              </optgroup>
              <optgroup label="Snabbvägar">
                {routes.map((b) => (
                  <option key={pedalValue(b.key)} value={pedalValue(b.key)}>
                    {b.text}
                  </option>
                ))}
              </optgroup>
            </select>
          </label>
        ))}
      </div>
    </section>
  );
}

// --- Deck ----------------------------------------------------------------------------------

export type DeckTabProps = {
  decks: Decks | null;
  chosen: string | null;
  pages: string[];
  hid: boolean;
  said: string[];
  busy: boolean;
  onChoose: (serial: string) => void;
  onConnect: () => void;
  onBlink: (serial: string) => void;
  onChange: (serial: string, change: Partial<DeckChange>) => void;
  onForget: (serial: string) => void;
};

export function deckName(deck: DeckStatus): string {
  return deck.settings?.name || deck.name;
}

export function DeckTab(props: DeckTabProps) {
  const { decks, chosen } = props;
  const listed = decks?.decks ?? [];
  const deck = listed.find((d) => d.serial === chosen) ?? null;
  return (
    <div className="sds-decktab">
      <section className="ruta sds-decklista" aria-label="Deck på den här datorn">
        <div className="rad">
          <div>
            <h2>Deck på den här datorn</h2>
            <p className="liten">Gäller den här datorn. Ett deck känns igen på sitt serienummer (SD35).</p>
          </div>
          <span className="tm-fyll" />
          {props.hid ? (
            <button type="button" className="primar" onClick={props.onConnect}>
              Koppla in ett deck
            </button>
          ) : null}
        </div>
        {decks?.usb ? <p className="liten">TKL sköter deck över USB på den här datorn. Ett deck som sitter i USB kopplas in av sig självt.</p> : null}
        {decks?.usb_problem ? <p className="fel-text liten">{decks.usb_problem}</p> : null}
        {!props.hid && !decks?.usb ? <p className="liten">{NOT_HERE}</p> : null}
        {props.said.map((line, i) => (
          <p key={i} className="liten" role="status">
            {line}
          </p>
        ))}
        {decks === null ? (
          <p className="tom">Hämtar decken …</p>
        ) : listed.length ? (
          <table className="sds-tabell">
            <thead>
              <tr>
                <th>Namn</th>
                <th>Modell</th>
                <th>Serienummer</th>
                <th>Status</th>
                <th>Hitta</th>
              </tr>
            </thead>
            <tbody>
              {listed.map((d) => {
                const how = connectionText(d);
                return (
                  <tr key={d.serial} className={d.serial === chosen ? "vald" : ""} data-serial={d.serial}>
                    <td>
                      <button type="button" className="lank" onClick={() => props.onChoose(d.serial)}>
                        {deckName(d)}
                      </button>
                    </td>
                    <td>{d.name}</td>
                    <td className="tm-mono liten">{d.serial}</td>
                    <td>
                      <span className={`tm-chip ${how.on ? "gron" : "gul"}`}>{how.text}</span>{" "}
                      {d.connection === "usb" ? <span className="liten">{OWNED}</span> : null}
                      {!d.tried ? <span className="tm-chip gul">Inte provad</span> : null}
                    </td>
                    <td>
                      <button type="button" disabled={!d.connection || props.busy} onClick={() => props.onBlink(d.serial)}>
                        {d.blinking ? "Blinkar …" : "Blinka"}
                      </button>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        ) : (
          <p className="tom">Inga deck än. Öppna Stream Deck i Ställverket, eller koppla in ett.</p>
        )}
        <p className="liten">Deck på samma arbetsplats delar vald start: tryck start på ett deck och mål på ett annat (SD36).</p>
      </section>
      {deck ? <DeckSettingsView {...props} deck={deck} /> : null}
    </div>
  );
}

function DeckSettingsView({ deck, decks, pages, busy, onChange, onForget }: DeckTabProps & { deck: DeckStatus }) {
  const s = deck.settings;
  const roles = decks?.roles ?? [];
  const set = (change: Partial<DeckChange>) => onChange(deck.serial, change);
  return (
    <section className="ruta sds-deckval" aria-label={`Decket ${deckName(deck)}`}>
      <h2>{deckName(deck)}</h2>
      <p className="liten">
        {deck.name} · {deck.serial}
        {deck.tried ? "" : " · Inte provad med ett riktigt deck (SD58)"}
      </p>
      <label>
        Namn
        <input key={`n-${deck.serial}-${s?.name ?? ""}`} aria-label="Namn" defaultValue={s?.name ?? ""} maxLength={40} disabled={busy} onBlur={(e) => e.target.value !== (s?.name ?? "") && set({ name: e.target.value })} />
      </label>
      {roles.length > 1 ? (
        <label>
          Roll
          <select aria-label="Roll" value={s?.role ?? ""} disabled={busy} onChange={(e) => set({ role: e.target.value })}>
            {roles.map((r) => (
              <option key={r.part ?? ""} value={r.part ?? ""}>
                {r.name}
              </option>
            ))}
          </select>
        </label>
      ) : null}
      {s?.role === REMOTE_ROLE ? (
        <p className="liten">Decket öppnar i Fjärr, fjärrtågklarerarens deck: en sida per station TKL fjärrstyr, räknad ur stationernas fjärrkataloger. En tågväg blinkar tills trycket upprepas (SD37).</p>
      ) : s?.role ? (
        <p className="liten">Decket öppnar i Bangård, rangerarens deck, och når bara delens lägen (#87).</p>
      ) : null}
      <label>
        Ljusstyrka
        <input type="range" aria-label="Ljusstyrka" min={0} max={100} step={5} value={s?.brightness ?? 70} disabled={busy} onChange={(e) => set({ brightness: Number(e.target.value) })} />
      </label>
      <label>
        Håll in räknas efter
        <select aria-label="Hålltid" value={s?.hold ?? "normal"} disabled={busy} onChange={(e) => set({ hold: e.target.value as DeckChange["hold"] })}>
          {HOLDS.map(([value, name]) => (
            <option key={value} value={value}>
              {name}
            </option>
          ))}
        </select>
      </label>
      <label>
        Släck decket
        <select aria-label="Släckning" value={s?.sleep ?? 0} disabled={busy} onChange={(e) => set({ sleep: Number(e.target.value) })}>
          {SLEEPS.map(([value, name]) => (
            <option key={value} value={value}>
              {name}
            </option>
          ))}
        </select>
      </label>
      <label className="kryss">
        <input type="checkbox" checked={s?.lock_key ?? true} disabled={busy} onChange={(e) => set({ lock_key: e.target.checked })} /> Lås (Fika) på sidan Läge
      </label>
      <p className="liten">Decket låses alltid när TKL låses och visar då bara klockan (SD30).</p>
      <label>
        Öppnar på sidan
        <select aria-label="Startsida" value={s?.opens_on ?? ""} disabled={busy} onChange={(e) => set({ opens_on: e.target.value })}>
          <option value="">Lägets första sida</option>
          {pages.map((name) => (
            <option key={name} value={name}>
              {name}
            </option>
          ))}
        </select>
      </label>
      <label>
        Arbetsplats
        <input key={`w-${deck.serial}-${s?.workplace ?? "1"}`} aria-label="Arbetsplats" defaultValue={s?.workplace ?? "1"} maxLength={40} disabled={busy} onBlur={(e) => e.target.value.trim() && e.target.value !== (s?.workplace ?? "1") && set({ workplace: e.target.value.trim() })} />
      </label>
      <p className="liten">Vad knapparna gör ändras under Sidor och följer stationspaketet. Här ändras bara decket, på den här datorn.</p>
      <button type="button" className="fara" disabled={busy} onClick={() => onForget(deck.serial)}>
        Glöm decket
      </button>
    </section>
  );
}

// --- Prova ---------------------------------------------------------------------------------

export type ProvaTabProps = {
  roles?: DeckRole[];
  part?: string | null;
  onRole?: (part: string | null) => void;
  size: DeckModelId;
  sizes: { size: DeckModelId; name: string }[];
  prova: DeckProva | null;
  pages: number;
  favourites: DeckFavourites | null;
  onSize: (size: DeckModelId) => void;
  onStart: () => void;
  onStop: () => void;
  onGo: (page: number, cell: number) => void;
};

export const RESULT: Record<string, string> = { gick: "Gick", nej: "Nej", inget: "Inget" };

export function ProvaTab({ roles = [], part = null, onRole, size, sizes, prova, pages, favourites, onSize, onStart, onStop, onGo }: ProvaTabProps) {
  const running = !!prova?.running;
  const keys = prova?.keys ?? [];
  const most = (favourites?.counted ?? []).slice(0, 6);
  const top = Math.max(1, ...most.map((c) => c.count));
  return (
    <div className="sds-provatab">
      <section className="ruta" aria-label="Prova alla knappar">
        <div className="rad">
          <div>
            <h2>Prova alla knappar</h2>
            <p className="liten">Studio trycker på varje knapp mot ett tomt ställverk, en kopia och aldrig det riktiga (SD47).</p>
          </div>
          <span className="tm-fyll" />
          {roles.length > 1 ? <RoleChoice roles={roles} part={part} onRole={running ? undefined : onRole} label="Roll att prova" /> : null}
          <label>
            Storlek{" "}
            <select aria-label="Storlek att prova" value={size} disabled={running} onChange={(e) => onSize(e.target.value as DeckModelId)}>
              {sizes.map((s) => (
                <option key={s.size} value={s.size}>
                  {s.name}
                </option>
              ))}
            </select>
          </label>
          {running ? (
            <button type="button" onClick={onStop}>
              Stoppa
            </button>
          ) : (
            <button type="button" className="primar" onClick={onStart}>
              {prova?.total ? "Prova igen" : "Prova alla knappar"}
            </button>
          )}
        </div>
        {running ? <progress max={prova?.total || 1} value={prova?.done ?? 0} aria-label="Förloppet" /> : null}
        {prova?.message ? (
          <p className="liten" role="status">
            {prova.message}
          </p>
        ) : null}
        {prova?.total ? (
          <div className="sds-rutor">
            <div>
              <b>{prova.total}</b>
              <span>knappar på {pages} sidor</span>
            </div>
            <div className="gron">
              <b>{prova.did ?? 0}</b>
              <span>gick</span>
            </div>
            <div className="rod">
              <b>{prova.refused ?? 0}</b>
              <span>fick nej</span>
            </div>
            <div className="gul">
              <b>{prova.nothing ?? 0}</b>
              <span>gjorde inget</span>
            </div>
          </div>
        ) : null}
        {keys.length ? (
          <table className="sds-tabell sds-resultat">
            <thead>
              <tr>
                <th>Sida</th>
                <th>Knapp</th>
                <th>Resultat</th>
                <th>Ställverket sa</th>
              </tr>
            </thead>
            <tbody>
              {keys.map((k, i) => (
                <tr key={i} data-result={k.result}>
                  <td>{k.page_name}</td>
                  <td>
                    <button type="button" className="lank" onClick={() => onGo(k.page, k.cell)}>
                      {k.label}
                    </button>
                  </td>
                  <td>{RESULT[k.result] ?? k.result}</td>
                  <td className="liten">{k.said}</td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : null}
      </section>
      <section className="ruta sds-mest" aria-label="Mest använda vägar">
        <h2>Mest använda vägar</h2>
        <p className="liten">Ställverket räknar hur ofta varje väg läggs. Bara vägar, inga personer (SD24). Föreslå Mest använda under Sidor gör en sida av dem.</p>
        {most.length ? (
          <ul>
            {most.map((c) => (
              <li key={`${c.kind}${c.start}${c.end}`}>
                <span className="tm-mono">
                  {c.start}→{c.end}
                </span>
                <span className="sds-stapel" style={{ width: `${Math.round((100 * c.count) / top)}%` }} />
                <span>{c.count}</span>
              </li>
            ))}
          </ul>
        ) : (
          <p className="tom">Inga vägar räknade än.</p>
        )}
      </section>
    </div>
  );
}

// --- the page ------------------------------------------------------------------------------

type Calls = typeof api;

/** The Studio page with its three tabs, talking to TKL's server. */
export function StreamDeckStudio({ calls = api }: { calls?: Calls }) {
  const [tab, setTab] = useState<Tab>("sidor");
  const [size, setSize] = useState<DeckModelId>("15");
  const [role, setRole] = useState<string | null>(null);
  const [studio, setStudio] = useState<DeckStudio | null>(null);
  const [mode, setMode] = useState<DeckMode | null>(null);
  const [page, setPage] = useState(0);
  const [chosen, setChosen] = useState<number | null>(null);
  const [listed, setListed] = useState<number | null>(null);
  const [filter, setFilter] = useState("");
  const [panel, setPanel] = useState<Panel | null>(null);
  const [start, setStart] = useState<string | null>(null);
  const [lit, setLit] = useState<Route | null>(null);
  const [busy, setBusy] = useState(false);
  const [said, setSaid] = useState("");
  const [problems, setProblems] = useState<string[]>([]);
  const [newPage, setNewPage] = useState("");
  const [decks, setDecks] = useState<Decks | null>(null);
  const [deck, setDeck] = useState<string | null>(null);
  const [deckPages, setDeckPages] = useState<string[]>([]);
  const [hidSaid, setHidSaid] = useState<string[]>([]);
  const [prova, setProva] = useState<DeckProva | null>(null);
  const [favourites, setFavourites] = useState<DeckFavourites | null>(null);
  const sizeRef = useRef(size);
  sizeRef.current = size;
  const roleRef = useRef(role);
  roleRef.current = role;

  const shown = useCallback((found: DeckStudio, keep = true) => {
    setStudio(found);
    const pages = found.profile.pages ?? [];
    const modes = found.profile.modes ?? [];
    setMode((before) => (keep && before && modes.includes(before) ? before : (modes.find((m) => m === "platser") ?? modes[0] ?? null)));
    setPage((before) => (keep && before < pages.length ? before : Math.max(0, pages.findIndex((p) => p.mode === (modes.includes("platser") ? "platser" : modes[0])))));
  }, []);

  const failed = (error: unknown, fallback: string) => {
    setSaid(message(error, fallback));
    setProblems(error instanceof Problem ? error.problems : []);
  };

  useEffect(() => {
    let gone = false;
    setSaid("");
    calls
      .streamDeck(size, role)
      .then((found) => {
        if (gone) return;
        shown(found, false);
        setChosen(null);
      })
      .catch((error: unknown) => failed(error, "TKL svarar inte."));
    return () => {
      gone = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [size, role, calls, shown]);

  useEffect(() => {
    void calls
      .stationModel()
      .then((plan) => setPanel(plan?.panel ?? null))
      .catch(() => setPanel(null));
  }, [calls]);

  const edit = async (deviations: DeckDeviation[], done?: (found: DeckStudio) => void) => {
    setBusy(true);
    setSaid("");
    setProblems([]);
    try {
      const found = await calls.streamDeckDraft({ size, deviations, part: role });
      shown(found);
      done?.(found);
    } catch (error) {
      failed(error, "Ändringen gick inte att göra.");
    } finally {
      setBusy(false);
    }
  };

  const profile = studio?.profile;
  const current = profile?.pages?.[page];
  const fixed = profile?.fixed ?? [];
  const deviations = studio?.deviations ?? [];
  const buttons: DeckButton[] = studio?.buttons ?? [];

  const routeOf = (key: DeckKey | null | undefined): Route | null => {
    if (!key?.route) return null;
    const found = buttons.find((b) => keyId(b.key) === keyId(bare(key)));
    return { kind: key.route.kind, start: key.route.start, end: key.route.end, pieces: found?.pieces ?? [], positions: {}, turntable: null };
  };

  const choose = (cell: number | null) => {
    setChosen(cell);
    setListed(null);
    const key = cell !== null ? current?.keys[cell] : null;
    setLit(routeOf(key));
  };

  const drop = (cell: number, dragged: Dragged) => {
    if (!current) return;
    let key: DeckKey | null | undefined;
    if (dragged.from === "list") {
      key = buttons[dragged.index]?.key;
      if (key && (key.type === "train" || key.type === "line" || key.type === "daily" || key.type === "favourite")) {
        // A new key of a numbered kind takes the next number on the page.
        const used = current.keys.filter((k) => k?.type === key?.type).map((k) => k?.slot ?? 0);
        key = { ...key, slot: Math.max(0, ...used) + 1 };
      }
    } else {
      key = current.keys[dragged.cell];
    }
    if (!key) return;
    setListed(null);
    void edit(dropped(deviations, current, fixed, key, cell), () => setChosen(cell));
  };

  const signal = (name: string) => {
    if (!start || start === name) {
      setStart(start === name ? null : name);
      return;
    }
    setStart(null);
    const key = routeKey(buttons, start, name);
    if (!key || !current) {
      setSaid(`Ingen väg går från ${start} till ${name}.`);
      return;
    }
    const cell = freeCell(current, fixed);
    if (cell === null) {
      setSaid(`Sidan ${current.name} är full. Ta bort en knapp eller välj en annan sida.`);
      return;
    }
    void edit(dropped(deviations, current, fixed, key, cell), () => {
      setChosen(cell);
      setLit(routeOf(key));
    });
  };

  const save = async () => {
    setBusy(true);
    setProblems([]);
    try {
      const found = await calls.saveStreamDeck({ size, deviations, part: role });
      shown(found);
      setSaid(found.message ?? "Sparat.");
    } catch (error) {
      failed(error, "Det gick inte att spara.");
    } finally {
      setBusy(false);
    }
  };

  const suggest = async (rule: DeckSuggestion) => {
    if (!current) return;
    setBusy(true);
    setProblems([]);
    try {
      shown(await calls.streamDeckSuggest({ size, deviations, page: refOf(current), rule, part: role }));
      setSaid(`Sidan ${current.name} är föreslagen. Spara om den ska gälla.`);
    } catch (error) {
      failed(error, "Föreslå gick inte.");
    } finally {
      setBusy(false);
    }
  };

  const go = (target: number, cell: number | null) => {
    const p = profile?.pages?.[target];
    if (!p) return;
    setTab("sidor");
    setMode(p.mode);
    setPage(target);
    setChosen(cell);
    setLit(routeOf(cell !== null ? p.keys[cell] : null));
  };

  // --- Deck ---
  const readDecks = useCallback(() => {
    void calls
      .decks()
      .then(setDecks)
      .catch(() => {});
  }, [calls]);
  useEffect(() => {
    if (tab !== "deck") return;
    readDecks();
    const every = setInterval(readDecks, DECKS_MS);
    return () => clearInterval(every);
  }, [tab, readDecks]);
  const chosenDeck = decks?.decks?.find((d) => d.serial === deck) ?? null;
  const deckSize = sizeOfModel(chosenDeck?.model);
  const deckRole = chosenDeck?.settings?.role ?? null;
  useEffect(() => {
    if (!deckSize || (deckRole && deckSize === "pedal")) return setDeckPages([]);
    void calls
      .streamDeck(deckSize, deckRole)
      .then((found) => setDeckPages((found.profile.pages ?? []).filter((p) => p.listed ?? true).map((p) => p.name)))
      .catch(() => setDeckPages([]));
  }, [deckSize, deckRole, calls]);
  const deckWork = async (work: () => Promise<unknown>) => {
    setBusy(true);
    try {
      await work();
    } catch (error) {
      setHidSaid([message(error, "Det gick inte.")]);
    } finally {
      readDecks();
      setBusy(false);
    }
  };
  const connectHid = async () => {
    try {
      const library = await import("@elgato-stream-deck/webhid");
      const found = await library.requestStreamDecks();
      if (found.length) setHidSaid(await connect(found as HidDeck[], hidApi, readDecks));
      readDecks();
    } catch (error) {
      setHidSaid([`Stream Deck gick inte att koppla in: ${message(error, "")}. Stäng Elgatos eget program om det håller decket.`]);
    }
  };

  // --- Prova ---
  const running = !!prova?.running;
  useEffect(() => {
    if (tab !== "prova") return;
    void calls
      .streamDeckProva(size, role)
      .then(setProva)
      .catch(() => {});
    void calls
      .deckFavourites()
      .then(setFavourites)
      .catch(() => setFavourites(null));
  }, [tab, size, role, calls]);
  useEffect(() => {
    if (!running) return;
    const every = setInterval(() => {
      void calls
        .streamDeckProva(sizeRef.current, roleRef.current)
        .then(setProva)
        .catch(() => {});
    }, POLL_MS);
    return () => clearInterval(every);
  }, [running, calls]);

  let body: ReactNode = <p className="tom">{said || "Hämtar decket …"}</p>;
  if (tab === "sidor" && studio) {
    body = (
      <SidorView
        studio={studio}
        mode={mode}
        page={page}
        chosen={chosen}
        listed={listed}
        filter={filter}
        panel={panel}
        start={start}
        lit={lit}
        busy={busy}
        said={said}
        problems={problems}
        newPage={newPage}
        onSize={(next) => {
          setSize(next);
          setChosen(null);
        }}
        onRole={(next) => {
          // A part's deck has no pedal (TKL122): the 15 instead.
          if (next && size === "pedal") setSize("15");
          setRole(next);
          setChosen(null);
        }}
        onMode={(next) => {
          setMode(next);
          setPage(Math.max(0, (studio.profile.pages ?? []).findIndex((p) => p.mode === next)));
          setChosen(null);
        }}
        onPage={(next) => {
          setPage(next);
          setChosen(null);
        }}
        onChoose={choose}
        onChooseButton={(index) => {
          setListed(index);
          setChosen(null);
          const key = index !== null ? buttons[index]?.key : null;
          setLit(routeOf(key));
        }}
        onFilter={setFilter}
        onDrop={drop}
        onEdit={(change) => {
          const key = chosen !== null ? current?.keys[chosen] : null;
          if (current && key) void edit(edited(deviations, current, key, change));
        }}
        onRemove={() => {
          const key = chosen !== null ? current?.keys[chosen] : null;
          if (current && key) void edit(removed(deviations, current, key), () => setChosen(null));
        }}
        onSignal={signal}
        onSuggest={(rule) => void suggest(rule)}
        onResetPage={() => current && void edit(pageReset(deviations, refOf(current)))}
        onResetSize={() => void edit([])}
        onSave={() => void save()}
        onUndo={() => {
          void calls.streamDeck(size, role).then((found) => shown(found));
          setSaid("");
          setProblems([]);
        }}
        onNewPage={setNewPage}
        onAddPage={() => {
          const name = newPage.trim();
          if (!name || !mode) return;
          void edit(pageAdded(deviations, name, mode), (found) => {
            setNewPage("");
            const at = (found.profile.pages ?? []).findIndex((p) => p.kind === "egen" && p.name === name);
            if (at >= 0) setPage(at);
          });
        }}
        onRemovePage={() => current && void edit(pageRemoved(deviations, current), () => setPage(0))}
        onMovePage={(step) => {
          if (!current || !profile) return;
          const ref = refOf(current);
          void edit(pageMoved(deviations, profile, current, step), (found) => {
            const at = (found.profile.pages ?? []).findIndex((p) => p.kind === ref.kind && p.name === ref.name);
            if (at >= 0) setPage(at);
          });
        }}
        onPedal={(pedal, value) => void edit(pedalChosen(deviations, pedal, pedalKey(value)))}
        onForgetChange={(n) => void edit(deviations.filter((_, i) => i !== n))}
        onGo={go}
        onProblem={(problem) => {
          if (problem.page !== null && problem.page !== undefined) go(problem.page, problem.cell ?? null);
          else if (problem.route) setLit({ ...problem.route, pieces: buttons.find((b) => b.key.route && keyId(b.key) === keyId(fullKey({ type: "route", route: problem.route })))?.pieces ?? [], positions: {}, turntable: null });
        }}
      />
    );
  } else if (tab === "deck") {
    body = (
      <DeckTab
        decks={decks}
        chosen={deck}
        pages={deckPages}
        hid={hasHid()}
        said={hidSaid}
        busy={busy}
        onChoose={setDeck}
        onConnect={() => void connectHid()}
        onBlink={(serial) => void deckWork(() => calls.deckBlink(serial))}
        onChange={(serial, change) => void deckWork(() => calls.deckSettings(serial, deckChange(change)))}
        onForget={(serial) =>
          void deckWork(async () => {
            await calls.deckForget(serial);
            setDeck(null);
          })
        }
      />
    );
  } else if (tab === "prova") {
    body = (
      <ProvaTab
        roles={studio?.roles ?? []}
        part={role}
        onRole={(next) => {
          if (next && size === "pedal") setSize("15");
          setRole(next);
        }}
        size={size}
        sizes={(studio?.sizes ?? []).filter((s) => s.size !== "pedal" || (s.deviations ?? 0) > 0)}
        prova={prova}
        pages={new Set((prova?.keys ?? []).map((k) => k.page)).size || (profile?.pages ?? []).length}
        favourites={favourites}
        onSize={setSize}
        onStart={() =>
          void calls
            .streamDeckProvaStart(size, role)
            .then(setProva)
            .catch((error: unknown) => setProva({ message: message(error, "Provet startade inte.") } as DeckProva))
        }
        onStop={() =>
          void calls
            .streamDeckProvaStop()
            .then(setProva)
            .catch(() => {})
        }
        onGo={(target, cell) => go(target, cell)}
      />
    );
  }

  return (
    <div className="sds">
      <div className="sidrubrik">
        <h1>Stream Deck</h1>
        <p className="liten">Profilerna följer stationspaketet. Decket gör inget som panelen inte kan. Förvalet räknas fram ur stationen, och ändringarna här läggs på det (SD39, SD40).</p>
      </div>
      <nav className="sds-flikrad" role="tablist" aria-label="Stream Deck">
        {TABS.map(([key, name]) => (
          <button key={key} type="button" role="tab" aria-selected={tab === key} onClick={() => setTab(key)}>
            {name}
          </button>
        ))}
      </nav>
      {body}
    </div>
  );
}

/** Studio › Inställningar: the settings that belong to the station, beside its drawing. */
/** Studio › Inställningar: Stream Deck (#86 del c) and Fjärrstyrning (#36 del b). */
export type StudioPart = "stream-deck" | "fjarrstyrning";

export function StudioInstallningar({ calls, part = "stream-deck", onPart }: { calls?: Calls; part?: StudioPart; onPart?: (part: StudioPart) => void }) {
  return (
    <div className="installningar sds-ram">
      <nav className="sidomeny" aria-label="Inställningar i Studio">
        <button type="button" aria-current={part === "stream-deck" ? "page" : undefined} onClick={() => onPart?.("stream-deck")}>
          Stream Deck
        </button>
        <button type="button" aria-current={part === "fjarrstyrning" ? "page" : undefined} onClick={() => onPart?.("fjarrstyrning")}>
          Fjärrstyrning
        </button>
        <p className="liten">Manöver ställs in under Spårplan.</p>
      </nav>
      <div className="innehall">{part === "fjarrstyrning" ? <FjarrStudio /> : <StreamDeckStudio calls={calls} />}</div>
    </div>
  );
}
