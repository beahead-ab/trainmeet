import { useEffect, useState } from "react";
import { api, Problem, type Client, type DriftEvent, type Now, type Package, type Refusal } from "./api";
import { actorName, csv, describe, eventRows, logFile, placeName, refusalRows, shown as inLogg, trainId, trainNumber } from "./drift";
import { Chip, Chips, LoginFirst } from "./ui";

// Logg (TRAFIK-07, B15): what happened in the meet, newest first, and what the clients were
// told no to. Filters per place and train. Read again every five seconds. Only for the
// administrator. What is shown can be exported as CSV or JSON (TRAFIK-20, F27).

/** Hand the browser a file to save. */
function save(name: string, type: string, text: string) {
  const url = URL.createObjectURL(new Blob([text], { type }));
  const link = document.createElement("a");
  link.href = url;
  link.download = name;
  document.body.append(link);
  link.click();
  link.remove();
  window.setTimeout(() => URL.revokeObjectURL(url), 1000);
}

export type LogRows = { kind: "events"; events: DriftEvent[] } | { kind: "refusals"; refusals: Refusal[] };

export type LoggProps = {
  admin: boolean;
  now: Now | null;
  /** The package Drift goes by, for the words of the driftändringar. */
  pkg?: Package | null;
  clients: Client[];
  navigate: (href: string) => void;
  onMessage?: (text: string) => void;
  /** For tests: the rows to show, without asking the hub. */
  rows?: LogRows;
};

export function LoggPage({ admin, now, pkg = null, clients, navigate, onMessage, rows: given }: LoggProps) {
  const [kind, setKind] = useState<LogRows["kind"]>(given?.kind ?? "events");
  const [place, setPlace] = useState<string | null>(null);
  const [train, setTrain] = useState("");
  const [rows, setRows] = useState<LogRows | null>(given ?? null);

  useEffect(() => {
    if (!admin || given) return;
    let live = true;
    const read = async () => {
      try {
        const next: LogRows =
          kind === "events"
            ? { kind, events: (await api.log(place, train.trim() ? trainId(now, train.trim()) : null)).filter(inLogg) }
            : { kind, refusals: (await api.refusals()).filter((refusal) => !place || refusal.place === place) };
        if (live) {
          setRows(next);
          onMessage?.("");
        }
      } catch (error) {
        if (live && error instanceof Problem) onMessage?.(error.message);
      }
    };
    void read();
    const timer = window.setInterval(() => void read(), 5000);
    return () => {
      live = false;
      window.clearInterval(timer);
    };
    // The meet's trains are looked up when the filter changes, not each time Nu comes.
  }, [admin, kind, place, train, given]);

  if (!admin) {
    return (
      <>
        <LoginFirst navigate={navigate} />
      </>
    );
  }
  const shown = rows?.kind === kind ? rows : null;
  return (
    <>
      <div className="sidrubrik">
        <h1>Logg</h1>
        <p className="liten">Det som hänt i träffen, nyast först, och det som klienterna fått nej till.</p>
      </div>
      <div className="rad">
        <Chips label="Visa">
          <Chip label="Händelser" pressed={kind === "events"} onClick={() => setKind("events")} />
          <Chip label="Nekade" pressed={kind === "refusals"} onClick={() => setKind("refusals")} />
        </Chips>
        <label>
          Tåg <input id="log-train" inputMode="numeric" size={6} autoComplete="off" value={train} onChange={(event) => setTrain(event.target.value)} />
        </label>
        <span className="rad export">
          <button
            id="export-csv"
            type="button"
            disabled={!shown}
            onClick={() => shown && save(logFile(now, shown.kind === "events" ? "logg" : "nekade", "csv"), "text/csv;charset=utf-8", csv(shown.kind === "events" ? eventRows(shown.events, now, clients, pkg) : refusalRows(shown.refusals, now)))}
          >
            Exportera CSV
          </button>
          <button
            id="export-json"
            type="button"
            disabled={!shown}
            onClick={() => shown && save(logFile(now, shown.kind === "events" ? "logg" : "nekade", "json"), "application/json", JSON.stringify(shown.kind === "events" ? shown.events : shown.refusals, null, 2))}
          >
            Exportera JSON
          </button>
        </span>
      </div>
      <p className="liten">Exporten tar med det som visas, med filtren, äldst först.</p>
      <Chips label="Driftplats">
        <Chip label="Alla driftplatser" pressed={place === null} onClick={() => setPlace(null)} />
        {(now?.places ?? []).map((option) => (
          <Chip key={option.place} label={option.name} pressed={place === option.place} onClick={() => setPlace(option.place)} />
        ))}
      </Chips>
      <div className="ram">
        <table className="tabell">
          <thead>
            <tr>
              <th>Tid</th>
              <th>Händelse</th>
              <th>Tåg</th>
              <th>Driftplats</th>
              <th>Vem</th>
            </tr>
          </thead>
          <tbody id="log">
            {shown?.kind === "events" &&
              (shown.events.length ? (
                shown.events.map((event) => (
                  <tr key={event.seq}>
                    <td>{event.model_time}</td>
                    <td>{describe(event, pkg)}</td>
                    <td className="tag">{trainNumber(now, event.train)}</td>
                    <td>{event.place ? placeName(now, event.place) : ""}</td>
                    <td>{actorName(event.actor, clients)}</td>
                  </tr>
                ))
              ) : (
                <Empty text="Inget har hänt här än." />
              ))}
            {shown?.kind === "refusals" &&
              (shown.refusals.length ? (
                shown.refusals.map((refusal, index) => (
                  <tr key={`${refusal.wall_time}-${index}`}>
                    <td>{refusal.model_time}</td>
                    <td>{`${refusal.what}: ${refusal.message}`}</td>
                    <td />
                    <td>{refusal.place ? placeName(now, refusal.place) : ""}</td>
                    <td className="tm-mono">{refusal.client_id}</td>
                  </tr>
                ))
              ) : (
                <Empty text="Ingen har fått nej." />
              ))}
          </tbody>
        </table>
      </div>
    </>
  );
}

function Empty({ text }: { text: string }) {
  return (
    <tr>
      <td colSpan={5} className="tom">
        {text}
      </td>
    </tr>
  );
}
