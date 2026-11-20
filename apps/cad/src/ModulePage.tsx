// Modulens sida (CAD-05): Översikt, Ritning, Foto, Landskap and Historik, with the gables, who
// sees the module, where it is used, and Godkänn. As the view Modul-klar.
import { linkClick, type Navigate } from "@trainmeet/design";
import type { ClubChoice, Module, ModuleEvent, PhotoConsent, PhotoStart, StorageUse, Visibility } from "./api";
import { bendText, dayText, NORM_NAMES, stampText, status, VISIBILITY } from "./common";
import { ModuleDrawing, ProfileBar } from "./Drawing";
import { PhotoTab } from "./Foto";
import { LandskapTab } from "./Landskap";
import { metres } from "./geometry";
import { drawingPath, editPath, exportPath, modulePath, PATHS, type Tab } from "./routes";

const TABS: [Tab, string][] = [
  ["oversikt", "Översikt"],
  ["ritning", "Ritning"],
  ["foto", "Foto"],
  ["landskap", "Landskap"],
  ["historik", "Historik"],
];

type Props = {
  module: Module;
  history: ModuleEvent[];
  tab: Tab;
  clubs: ClubChoice[];
  navigate?: Navigate;
  onApprove?: () => void;
  onVisibility?: (visibility: Visibility, club: string | null) => void;
  onRemove?: () => void;
  error?: string | null;
  /** The Foto tab (part c1). */
  consent?: PhotoConsent | null;
  storage?: StorageUse | null;
  busy?: boolean;
  now?: Date;
  onUpload?: (start: PhotoStart, files: File[]) => void;
  onPhotoSettings?: (change: { keep_original?: boolean; training?: boolean }) => void;
  onRecompute?: (job: string) => void;
  /** Landskapet (part d1) saved a new version: the module and its history again. */
  onChanged?: () => void;
};

function Facts({ module }: { module: Module }) {
  const [a, b] = module.gables;
  const shape = module.shape;
  const size =
    shape.kind === "straight"
      ? `${Math.round(shape.length)} × ${Math.round(shape.width)} mm`
      : shape.kind === "trapezoid"
        ? `${Math.round(shape.length)} × ${Math.round(shape.width_a)}/${Math.round(shape.width_b)} mm`
        : `${bendText(shape.radius, shape.angle)} · bredd ${Math.round(shape.width)} mm`;
  const width = shape.kind === "trapezoid" ? Math.max(shape.width_a, shape.width_b) : shape.width;
  return (
    <div className="cad-kort cad-fakta">
      <h2 className="cad-overrubrik">Modulen</h2>
      <dl>
        <dt>Mått</dt>
        <dd className="tm-mono">{size}</dd>
        <dt>Längd</dt>
        <dd>
          {module.photo ? (
            <>
              ur fotot <span className="cad-tagg forslag">mätbild</span>
            </>
          ) : (
            <>
              ur måtten <span className="cad-status matt">inget foto</span>
            </>
          )}
        </dd>
        <dt>Skala</dt>
        <dd>{module.scale}</dd>
        <dt>Form</dt>
        <dd>{shape.kind === "straight" ? "Rak" : shape.kind === "curve" ? "Kurva" : "Trapets"}</dd>
      </dl>
      {[a, b].map((g) =>
        g ? (
          <div className="cad-gavelrad" key={g.end}>
            <h3>
              Gavel {g.end} · {g.label}
              {g.norm ? <span className="cad-dampad"> · {normName(g.norm)}</span> : null}
            </h3>
            <ProfileBar width={width} positions={g.tracks} />
            <p className="tm-mono cad-lagen">{g.tracks.map((t) => Math.round(t)).join(" ") || "inga spår"}</p>
          </div>
        ) : null,
      )}
    </div>
  );
}

function sizeText(module: Module): string {
  const shape = module.shape;
  if (shape.kind === "curve") return bendText(shape.radius, shape.angle);
  if (shape.kind === "trapezoid") return `${Math.round(shape.length)} × ${Math.round(shape.width_a)}/${Math.round(shape.width_b)}`;
  return `${Math.round(shape.length)} × ${Math.round(shape.width)}`;
}

function normName(norm: string): string {
  return NORM_NAMES[norm] ?? norm;
}

function Who({ module, clubs, onVisibility }: { module: Module; clubs: ClubChoice[]; onVisibility?: Props["onVisibility"] }) {
  const clubOwned = module.owner.kind === "club";
  const choices: Visibility[] = ["me", "club", "all"];
  const noClub = !clubOwned && clubs.length === 0;
  return (
    <fieldset className="cad-kort cad-vem" disabled={!module.may_edit}>
      <legend className="cad-overrubrik">Vem ser modulen</legend>
      {choices.map((choice) => (
        <label key={choice} className="cad-radio">
          <input
            type="radio"
            name="synlighet"
            value={choice}
            checked={module.visibility === choice}
            disabled={choice === "club" && noClub}
            onChange={() => onVisibility?.(choice, choice === "club" ? (module.club ?? clubs[0]?.id ?? null) : null)}
          />
          {choice === "club" && clubOwned ? `Klubben · ${module.owner.name}` : VISIBILITY[choice]}
          {choice === "club" && module.visibility === "club" && module.club_name && !clubOwned ? (
            <span className="cad-dampad"> · {module.club_name}</span>
          ) : null}
        </label>
      ))}
      {module.visibility === "club" && !clubOwned && clubs.length > 1 ? (
        <label className="cad-falt">
          <span>Klubben</span>
          <select value={module.club ?? ""} onChange={(event) => onVisibility?.("club", event.currentTarget.value)}>
            {clubs.map((club) => (
              <option key={club.id} value={club.id}>
                {club.name}
              </option>
            ))}
          </select>
        </label>
      ) : null}
      <p className="cad-dampad">
        Ägare: {clubOwned ? `klubben ${module.owner.name}` : module.may_edit ? "du, med TrainMeet ID" : module.owner.name}.{" "}
        {noClub ? "Du är inte med i någon klubb i TrainMeet ID än. " : ""}Den som ser modulen får använda den; bara ägaren och de med
        rollen redigera ändrar den.
      </p>
    </fieldset>
  );
}

function Used({ module, navigate }: { module: Module; navigate?: Navigate }) {
  const assemblies = (module.used_in ?? []).filter((u) => u.kind === "assembly");
  const stations = (module.used_in ?? []).filter((u) => u.kind === "station");
  const meets = (module.used_in ?? []).filter((u) => u.kind === "meet");
  const names = (found: typeof assemblies) => [...new Set(found.map((u) => u.name))].join(", ") || "ingen än";
  return (
    <div className="cad-kort cad-anvands">
      <h2 className="cad-overrubrik">Används i</h2>
      <dl>
        <dt>Anläggningar</dt>
        <dd>{names(assemblies)}</dd>
        <dt>Stationer i TKL</dt>
        <dd>{names(stations)}</dd>
        <dt>Träffar</dt>
        <dd>{names(meets)}</dd>
      </dl>
      <div className="cad-knapprad">
        <a className="tm-knapp" href={PATHS.assemblies} onClick={linkClick(navigate, PATHS.assemblies)}>
          + Lägg i anläggning
        </a>
      </div>
      {module.status === "approved" && module.owner.kind === "person" && module.may_edit ? (
        <p className="cad-dampad">Godkänd och din: den finns också ensam i TKL Studio › Rita › Från CAD.</p>
      ) : null}
    </div>
  );
}

function History({ module, history, navigate }: { module: Module; history: ModuleEvent[]; navigate?: Navigate }) {
  return (
    <div className="cad-kort cad-historik">
      <h2 className="cad-overrubrik">Historik</h2>
      <ol>
        {history.map((event, i) => {
          const href = modulePath(module.id, "oversikt", event.version);
          return (
            <li key={`${event.at}-${i}`}>
              <time className="tm-mono" dateTime={event.at}>
                {stampText(event.at)}
              </time>
              <span>
                {event.text} <span className="cad-dampad">· {event.by}</span>
              </span>
              {event.kind === "saved" || event.kind === "created" ? (
                <a href={href} onClick={linkClick(navigate, href)} className="cad-dampad">
                  Visa version {event.version}
                </a>
              ) : null}
            </li>
          );
        })}
      </ol>
    </div>
  );
}

export function ModulePage(props: Props) {
  const { module, history, tab, clubs, navigate, onApprove, onVisibility, onRemove, error } = props;
  const s = status(module);
  const old = module.version !== module.latest;
  const tracks: [number[], number[]] = [module.gables[0]?.tracks ?? [], module.gables[1]?.tracks ?? []];
  const atA = tracks[0].length;
  const atB = tracks[1].length;
  const drawing = (
    <ModuleDrawing shape={module.shape} tracks={tracks} graph={module.graph} gables={module.gables} title={`${module.name} ovanifrån`} />
  );
  return (
    <section className="cad-sida" aria-labelledby="rubrik">
      <nav className="cad-brodsmulor" aria-label="Var du är">
        <a href={PATHS.library} onClick={linkClick(navigate, PATHS.library)}>
          Moduler
        </a>{" "}
        › <span aria-current="page">{module.name}</span>
      </nav>
      <div className="cad-rubrikrad">
        <h1 id="rubrik">{module.name}</h1>
        <span className="cad-pill tm-mono">{module.number}</span>
        <span className={`cad-status ${s.kind}`}>
          {s.kind === "godkand" && module.approved_at ? `✓ Godkänd ${dayText(module.approved_at)}` : s.text}
        </span>
        <span className="cad-pill">Version {module.version}</span>
        <span className="cad-fyll" />
        <a className="tm-knapp" href={exportPath(module.id, old ? module.version : undefined)} onClick={linkClick(navigate, exportPath(module.id, old ? module.version : undefined))}>
          Exportera
        </a>
        {module.may_edit && !old ? (
          <a className="tm-knapp" href={editPath(module.id)} onClick={linkClick(navigate, editPath(module.id))}>
            Ändra måtten
          </a>
        ) : null}
        {module.may_edit && !old && module.status !== "approved" ? (
          <button type="button" className="tm-knapp primar" onClick={() => onApprove?.()}>
            Godkänn
          </button>
        ) : null}
      </div>
      {old ? (
        <p className="cad-ruta" role="status">
          Du ser version {module.version} av {module.latest}.{" "}
          <a href={modulePath(module.id)} onClick={linkClick(navigate, modulePath(module.id))}>
            Till den senaste
          </a>
        </p>
      ) : null}
      {error ? (
        <p className="cad-fel" role="alert">
          {error}
        </p>
      ) : null}
      <nav className="cad-flikar" aria-label="Modulens flikar">
        {TABS.map(([key, label]) => {
          // The Ritning tab opens Ritningen for those who may change the module (CAD-03, CAD-21).
          const href = key === "ritning" && module.may_edit && !old ? drawingPath(module.id) : modulePath(module.id, key, old ? module.version : undefined);
          return (
            <a key={key} href={href} aria-current={tab === key ? "page" : undefined} onClick={linkClick(navigate, href)}>
              {label}
            </a>
          );
        })}
      </nav>
      {tab === "oversikt" ? (
        <>
          <div className="cad-oversikt">
            <div className="cad-kort cad-ritkort">
              {drawing}
              <ul className="cad-siffror">
                <li>
                  <b>{(module.graph.switches ?? []).length}</b> växlar
                </li>
                <li>
                  <b>{metres(module.track_length)}</b> spår
                </li>
                <li>
                  <b>
                    {atA} + {atB}
                  </b>{" "}
                  spår vid gavel A och B
                </li>
                <li>
                  <b>{sizeText(module)}</b> {module.shape.kind === "curve" ? "radie och vinkel" : "mm"}
                </li>
              </ul>
            </div>
            <div className="cad-sidokolumn">
              <Facts module={module} />
              <Who module={module} clubs={clubs} onVisibility={onVisibility} />
              <Used module={module} navigate={navigate} />
            </div>
          </div>
          <History module={module} history={history} navigate={navigate} />
        </>
      ) : null}
      {tab === "ritning" ? (
        <div className="cad-kort cad-ritkort stor">
          <div className="cad-kortrubrik">
            <h2>Ritningen</h2>
            <span className="cad-dampad">
              {module.graph.complete ? "Spårgrafen ur måtten" : "Spåren mellan gavlarna är okända tills modulen är fotad"} ·{" "}
              {(module.graph.pieces ?? []).length} spårbitar · {(module.graph.nodes ?? []).length} noder
            </span>
          </div>
          {drawing}
          {(module.checks ?? []).some((c) => !c.answer) ? (
            <p className="cad-dampad">{(module.checks ?? []).filter((c) => !c.answer).length} saker att kolla innan spårplanen godkänns.</p>
          ) : null}
          <p className="cad-dampad">
            {module.may_edit && !old ? (
              <a href={drawingPath(module.id)} onClick={linkClick(navigate, drawingPath(module.id))}>
                Öppna Ritningen
              </a>
            ) : (
              "Bara ägaren och de med rollen redigera ändrar ritningen."
            )}
          </p>
        </div>
      ) : null}
      {tab === "foto" ? (
        <PhotoTab
          module={module}
          consent={props.consent ?? null}
          storage={props.storage}
          busy={props.busy}
          navigate={navigate}
          now={props.now}
          onUpload={props.onUpload}
          onPhotoSettings={props.onPhotoSettings}
          onRecompute={props.onRecompute}
        />
      ) : null}
      {tab === "landskap" ? <LandskapTab module={module} onChanged={props.onChanged} /> : null}
      {tab === "historik" ? <History module={module} history={history} navigate={navigate} /> : null}
      {module.may_edit && !old ? (
        <p className="cad-tabort">
          <button type="button" className="cad-lank fara" onClick={() => onRemove?.()}>
            Ta bort modulen
          </button>
        </p>
      ) : null}
    </section>
  );
}
