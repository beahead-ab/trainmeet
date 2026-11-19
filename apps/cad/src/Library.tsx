// Modulerna (the library) and Tomt bibliotek (the first time), as in the views Main and Tomt.
import { linkClick, type Navigate } from "@trainmeet/design";
import { useState } from "react";
import type { ModuleBrief, ModuleList } from "./api";
import { count, dateText, shapeText, status } from "./common";
import { ModuleDrawing } from "./Drawing";
import { metres } from "./geometry";
import { modulePath, PATHS } from "./routes";

type Filter = "alla" | "raka" | "kurvor" | "utkast" | "godkanda";

const FILTERS: { key: Filter; label: string; test: (m: ModuleBrief) => boolean }[] = [
  { key: "alla", label: "Alla", test: () => true },
  { key: "raka", label: "Raka", test: (m) => m.shape.kind !== "curve" },
  { key: "kurvor", label: "Kurvor", test: (m) => m.shape.kind === "curve" },
  { key: "utkast", label: "Utkast", test: (m) => m.status === "draft" },
  { key: "godkanda", label: "Godkända", test: (m) => m.status === "approved" },
];

type Props = {
  list: ModuleList;
  navigate?: Navigate;
  search?: string;
  onSearch?: (q: string) => void;
  now?: Date;
};

export function LibraryPage({ list, navigate, search = "", onSearch, now }: Props) {
  const [filter, setFilter] = useState<Filter>("alla");
  const [view, setView] = useState<"lista" | "ritningar">("lista");
  const modules = list.modules;
  if (!modules.length && !search && list.library.kind === "mine") return <EmptyLibrary navigate={navigate} />;
  const shown = modules.filter(FILTERS.find((f) => f.key === filter)?.test ?? (() => true));
  const length = modules.reduce((sum, m) => sum + m.track_length, 0);
  const gableCount = list.gables.reduce((sum, g) => sum + g.count, 0);
  const approved = modules.filter((m) => m.status === "approved").length;
  const drafts = modules.length - approved;
  return (
    <section className="cad-sida" aria-labelledby="rubrik">
      <div className="cad-rubrikrad">
        <h1 id="rubrik">Moduler</h1>
        <span className="cad-pill">
          {count(modules.length, "modul", "moduler")} · {metres(length)} spår
        </span>
        <span className="cad-fyll" />
        <button type="button" className="tm-knapp" disabled title="Exporten kommer med anläggningarna (del d)">
          Exportera
        </button>
        {list.library.may_add ? (
          <a className="tm-knapp primar" href={PATHS.new} onClick={linkClick(navigate, PATHS.new)}>
            + Ny modul
          </a>
        ) : null}
      </div>
      <div className="cad-kort cad-gavlar">
        <span className="cad-overrubrik">Gavlar i biblioteket</span>
        <ul>
          {list.gables.slice(0, 6).map((g) => (
            <li key={g.label}>
              <b>{g.count}</b> {g.label}
            </li>
          ))}
        </ul>
        <span className="cad-fyll" />
        <span className="cad-dampad">
          {count(gableCount, "gavel", "gavlar")} på {count(modules.length, "modul", "moduler")}
        </span>
      </div>
      <div className="cad-kort cad-tabellkort">
        <div className="cad-filterrad">
          <label className="cad-sok">
            <span className="cad-dold">Sök</span>
            <input
              type="search"
              placeholder="Sök modul, ID eller gavel"
              defaultValue={search}
              onChange={(event) => onSearch?.(event.currentTarget.value)}
            />
          </label>
          <div className="cad-chips" role="group" aria-label="Visa">
            {FILTERS.map((f) => (
              <button
                key={f.key}
                type="button"
                className="cad-chip"
                aria-pressed={filter === f.key}
                onClick={() => setFilter(f.key)}
              >
                {f.label} {modules.filter(f.test).length}
              </button>
            ))}
          </div>
          <span className="cad-fyll" />
          <div className="cad-vaxel" role="group" aria-label="Visa som">
            <button type="button" aria-pressed={view === "lista"} onClick={() => setView("lista")}>
              Lista
            </button>
            <button type="button" aria-pressed={view === "ritningar"} onClick={() => setView("ritningar")}>
              Ritningar
            </button>
          </div>
        </div>
        {view === "lista" ? (
          <table className="cad-tabell">
            <thead>
              <tr>
                <th scope="col">Ritning</th>
                <th scope="col">ID</th>
                <th scope="col">Namn</th>
                <th scope="col">Form och mått</th>
                <th scope="col">Gavel A</th>
                <th scope="col">Gavel B</th>
                <th scope="col">Skala</th>
                <th scope="col">Status</th>
                <th scope="col">Ändrad</th>
              </tr>
            </thead>
            <tbody>
              {shown.map((m) => {
                const s = status(m);
                const href = modulePath(m.id);
                return (
                  <tr key={m.id}>
                    <td className="cad-tumme">
                      <a href={href} onClick={linkClick(navigate, href)} tabIndex={-1} aria-hidden="true">
                        <ModuleDrawing
                          shape={m.shape}
                          tracks={[m.gables[0]?.tracks ?? [], m.gables[1]?.tracks ?? []]}
                          graph={m.graph}
                          small
                        />
                      </a>
                    </td>
                    <td className="tm-mono cad-nummer">{m.number}</td>
                    <td>
                      <a className="cad-namn" href={href} onClick={linkClick(navigate, href)}>
                        {m.name}
                      </a>
                    </td>
                    <td>{shapeText(m.shape)}</td>
                    <td>{m.gables[0]?.label}</td>
                    <td>{m.gables[1]?.label}</td>
                    <td>{m.scale}</td>
                    <td>
                      <span className={`cad-status ${s.kind}`}>{s.text}</span>
                    </td>
                    <td className="cad-dampad">{dateText(m.changed_at, now)}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        ) : (
          <ul className="cad-rutnat">
            {shown.map((m) => {
              const href = modulePath(m.id);
              return (
                <li key={m.id}>
                  <a href={href} onClick={linkClick(navigate, href)}>
                    <ModuleDrawing
                      shape={m.shape}
                      tracks={[m.gables[0]?.tracks ?? [], m.gables[1]?.tracks ?? []]}
                      graph={m.graph}
                      small
                    />
                    <span className="tm-mono">{m.number}</span> {m.name}
                  </a>
                </li>
              );
            })}
          </ul>
        )}
        <div className="cad-fotrad">
          <span>
            <b>{count(modules.length, "modul", "moduler")}</b> · {approved} godkända · {drafts} utkast
          </span>
          <span className="cad-dampad">Klicka på en modul för ritningen · streckat spår = okänt tills modulen är fotad</span>
        </div>
      </div>
    </section>
  );
}

/** Första gången: så går det till. */
export function EmptyLibrary({ navigate }: { navigate?: Navigate }) {
  return (
    <section className="cad-sida cad-tom" aria-labelledby="rubrik">
      <h1 id="rubrik">Bygg ditt modulbibliotek</h1>
      <p className="cad-ingress">
        Mät varje modul en gång. Sedan finns måtten, gavlarna och spårplanen när du ska planera en träff.
      </p>
      <ol className="cad-steg">
        <li className="cad-kort">
          <svg viewBox="0 0 320 150" aria-hidden="true">
            <rect x="40" y="40" width="210" height="80" className="cad-skiva" />
            <path d="M40 40H250" className="cad-kant1" strokeWidth="4" />
            <text x="45" y="30" fontSize="13">KANT 1</text>
            <path d="M40 135H250M268 40V120" className="cad-mattlinje" />
            <text x="130" y="150" fontSize="13">1500</text>
            <text x="275" y="85" fontSize="13">700</text>
          </svg>
          <span className="cad-stegnr">1</span>
          <h2>Mät modulen</h2>
          <p>Längd och bredd. Är den en kurva mäter du med ett snöre – radien räknas ut.</p>
        </li>
        <li className="cad-kort">
          <svg viewBox="0 0 320 150" aria-hidden="true">
            <rect x="40" y="70" width="240" height="50" className="cad-skiva" />
            <path d="M40 70V120" className="cad-kant1" strokeWidth="5" />
            <rect x="115" y="62" width="22" height="8" className="cad-sliper" />
            <rect x="160" y="62" width="22" height="8" className="cad-sliper" />
            <path d="M40 40H126M126 40H171" className="cad-mattlinje" />
            <text x="70" y="34" fontSize="13">245</text>
            <text x="138" y="34" fontSize="13">50</text>
            <text x="100" y="140" fontSize="11">GAVEL B · SEDD FRÅN SIDAN</text>
          </svg>
          <span className="cad-stegnr">2</span>
          <h2>Beskriv gavlarna</h2>
          <p>Välj FREMO, MMM, USMS, enkel- eller dubbelspår. Unik gavel? Mät från Kant 1 till varje spårs mitt.</p>
        </li>
        <li className="cad-kort cad-kommer">
          <svg viewBox="0 0 320 150" aria-hidden="true">
            <rect x="60" y="45" width="200" height="70" className="cad-skiva" />
            <path d="M60 75H260M60 95H140C180 95 190 75 230 75" className="cad-spar" strokeWidth="3" fill="none" />
          </svg>
          <span className="cad-stegnr">3</span>
          <h2>Fota uppifrån</h2>
          <p>Hela modulen i en bild. Spåren fungerar som linjal, så fotot kan mätas. Kommer i nästa steg.</p>
        </li>
        <li className="cad-kort cad-kommer">
          <svg viewBox="0 0 320 150" aria-hidden="true">
            <rect x="60" y="45" width="200" height="70" className="cad-skiva" />
            <path d="M60 75H260M60 95H140C180 95 190 75 230 75" className="cad-forslag" strokeWidth="3" fill="none" />
            <text x="95" y="140" fontSize="11" className="cad-forslag-text">FÖRSLAG TILLS DU GODKÄNT</text>
          </svg>
          <span className="cad-stegnr">4</span>
          <h2>AI ritar och kontrollerar</h2>
          <p>Spåren ritas in och dina mått jämförs med fotot. Du godkänner. Kommer i nästa steg.</p>
        </li>
      </ol>
      <div className="cad-tom-rad">
        <div className="cad-kort">
          <a className="tm-knapp primar" href={PATHS.new} onClick={linkClick(navigate, PATHS.new)}>
            + Lägg till första modulen
          </a>
          <p>
            FREMO, MMM, USMS, enkel- och dubbelspår finns redan som gavelprofiler.{" "}
            <a href={PATHS.profiles} onClick={linkClick(navigate, PATHS.profiles)}>
              Se gavelprofilerna
            </a>
          </p>
        </div>
        <div className="cad-kort cad-kommer">
          <h2>Mät vid modulen med mobilen</h2>
          <p>Mobilen leder dig genom måtten, gavlarna och fotot, och modulen dyker upp här direkt. Kommer med fotot och kontrollen.</p>
        </div>
      </div>
    </section>
  );
}
