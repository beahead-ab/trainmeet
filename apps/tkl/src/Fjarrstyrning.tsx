// Fjärrstyrning in the station's own Ställverket (#36 del b): the operating form in a small bar
// (FR5, FR36), Lämna till … with the offer and its time left (FR8), Ta tillbaka after a question
// (FR7), and the station row over the panel (FR43): the station automats A3, A2 and A1, G for
// genomgångstrafik (which comes later), the signature and the name, grey when remote-controlled
// and blue when manned (FR32), and under the name the local release automat, L1 or L01 (FR39).
// A switched-on automat is yellow (FR34). On the spot the codes switch the automats and the local
// area; while the station is remote-controlled the one who controls it switches them, and the
// people on site ask for the local area, for a while or all day, and give it back (FR20, FR44).
import "./fjarrstation.css";
import { useState } from "react";
import type { AutomatSpec, FjarrState, FunctionShown, Snapshot } from "./api";
import { controlled, modeSaid, receiverName, ROW_COLOURS, stationRow, type RowCode } from "./fjarrstation";
import type { Send } from "./Stallverket";

type BarProps = {
  snapshot: Snapshot | null;
  busy: boolean;
  onSend: Send;
};

/** The operating form, and handing the station over and taking it back (FR5–FR8). */
export function DriftformBar(props: BarProps) {
  const [to, setTo] = useState("");
  const [asking, setAsking] = useState(false);
  return <DriftformView {...props} to={to} asking={asking} onTo={setTo} onAsking={setAsking} />;
}

type BarView = BarProps & { to: string; asking: boolean; onTo: (to: string) => void; onAsking: (asking: boolean) => void };

/** The bar as it is drawn, without state of its own: for the tests, which press its buttons. */
export function DriftformView({ snapshot, busy, onSend, to, asking, onTo: setTo, onAsking: setAsking }: BarView) {
  if (!snapshot) return null;
  const said = modeSaid(snapshot);
  const remote = snapshot.remote;
  const receivers = remote?.receivers ?? [];
  const chosen = receivers.find((r) => r.client_id === to) ?? receivers[0] ?? null;
  const fromAfar = !!remote?.controller;
  const offered = !!remote?.offer;
  const canOffer = !fromAfar && !offered && said.mode === "manned" && !!remote?.controllable;
  return (
    <section className={`driftform lage-${said.mode}`} aria-label="Driftform">
      <span className="driftform-lage" data-mode={said.mode}>
        {said.title}
      </span>
      {said.detail ? <span className="liten">{said.detail}</span> : null}
      <span className="tm-fyll" />
      {canOffer && receivers.length ? (
        <span className="driftform-lamna">
          <label>
            Lämna till{" "}
            <select aria-label="Lämna till" value={chosen?.client_id ?? ""} onChange={(e) => setTo(e.target.value)}>
              {receivers.map((r) => (
                <option key={r.client_id} value={r.client_id}>
                  {receiverName(r)}
                </option>
              ))}
            </select>
          </label>{" "}
          <button type="button" disabled={busy || !chosen} onClick={() => chosen && onSend("place.offer", { to: chosen.client_id })}>
            Lämna
          </button>
        </span>
      ) : null}
      {canOffer && !receivers.length ? <span className="liten">Ingen kan ta emot stationen just nu.</span> : null}
      {!remote?.controllable && said.mode === "manned" ? <span className="liten">Stationen kan inte fjärrstyras: den har ingen fjärrkatalog.</span> : null}
      {offered ? (
        <button type="button" disabled={busy} onClick={() => onSend("place.take_back", {})}>
          Ta tillbaka erbjudandet
        </button>
      ) : null}
      {fromAfar || said.mode === "automatic" ? (
        asking ? (
          <span className="driftform-fraga" role="alertdialog" aria-label="Ta tillbaka stationen">
            <span>{fromAfar ? `Ta tillbaka stationen från ${remote?.controller?.name}? Den blir bemannad, och låsta vägar ligger kvar tills tåget har gått.` : "Ta tillbaka stationen från automatiken?"}</span>{" "}
            <button
              type="button"
              className="primar"
              disabled={busy}
              onClick={() => {
                setAsking(false);
                onSend("place.take_back", {});
              }}
            >
              Ja, ta tillbaka
            </button>{" "}
            <button type="button" onClick={() => setAsking(false)}>
              Avbryt
            </button>
          </span>
        ) : (
          <button type="button" disabled={busy} onClick={() => setAsking(true)}>
            Ta tillbaka
          </button>
        )
      ) : null}
    </section>
  );
}

type RowProps = {
  name: string;
  signature: string;
  specs: AutomatSpec[];
  state: FjarrState | null | undefined;
  functions: FunctionShown[];
  snapshot: Snapshot | null;
  working: boolean;
  /** On the spot: a station automat on or off (FR25). */
  onAutomat: (code: string, on: boolean) => void;
  /** The local area: switched on the spot, or given back while remote-controlled (FR44). */
  onLocal: (fn: string, on: boolean) => void;
  /** While remote-controlled: ask the one who controls the station for it (FR20). */
  onAsk: Send;
};

/** Stationsraden (FR43), mitt i panelens överkant. */
export function Stationsrad(props: RowProps) {
  const [allDay, setAllDay] = useState(false);
  return <StationsradView {...props} allDay={allDay} onAllDay={setAllDay} />;
}

/** The row as it is drawn, without state of its own. */
export function StationsradView({ name, signature, specs, state, functions, snapshot, working, onAutomat, onLocal, onAsk, allDay, onAllDay: setAllDay }: RowProps & { allDay: boolean; onAllDay: (allDay: boolean) => void }) {
  const remote = controlled(snapshot, state);
  const { automats, locals } = stationRow(specs, state, functions, snapshot);
  const titleOf = (c: RowCode) => {
    const by = c.by === "remote" ? " från fjärr" : c.by === "automat" ? " av sig själv" : c.by === "station" ? " på platsen" : "";
    const waits = c.magazine ? " · en väg i magasinet" : "";
    return `${c.code} ${c.on ? `inkopplad${by}` : "urkopplad"}${waits}${remote ? " · den som fjärrstyr kopplar in och ur" : ""}`;
  };
  return (
    <div className="stationsrad" role="group" aria-label="Stationsraden">
      <span className="stationsrad-automater">
        {automats.map((c) => (
          <button
            key={c.code}
            type="button"
            className={`kod${c.on ? " pa" : ""}${c.magazine ? " magasin" : ""}`}
            data-code={c.code}
            data-on={c.on ? "ja" : "nej"}
            style={{ color: c.colour }}
            aria-pressed={c.on}
            title={titleOf(c)}
            disabled={working || remote}
            onClick={() => onAutomat(c.code, !c.on)}
          >
            {c.code}
          </button>
        ))}
        <span className="kod" title="G för genomgångstrafik kommer senare" style={{ color: ROW_COLOURS.off, opacity: 0.6 }}>
          G
        </span>
      </span>
      <span className="stationsrad-namn" data-remote={remote ? "ja" : "nej"} style={{ color: remote ? ROW_COLOURS.remote : ROW_COLOURS.manned }}>
        <b className="tm-mono">{signature}</b> {name.toUpperCase()}
      </span>
      {locals.length ? (
        <span className="stationsrad-lokala">
          {locals.map((c) => {
            if (remote && !c.on) {
              return (
                <span key={c.code} className="lokal-begar">
                  <button
                    type="button"
                    className="kod"
                    data-code={c.code}
                    style={{ color: c.colour }}
                    disabled={working || c.asked}
                    title={c.asked ? `${c.code} begärd: väntar på svar` : `Begär det lokala området ${c.code} av den som fjärrstyr`}
                    onClick={() => onAsk("local_release.request", { code: c.code, all_day: allDay })}
                  >
                    {c.code}
                  </button>
                  {c.asked ? (
                    <span className="liten">begärd</span>
                  ) : (
                    <label className="liten">
                      <input type="checkbox" checked={allDay} onChange={(e) => setAllDay(e.target.checked)} /> hela dagen
                    </label>
                  )}
                </span>
              );
            }
            return (
              <button
                key={c.code}
                type="button"
                className={`kod${c.on ? " pa" : ""}`}
                data-code={c.code}
                style={{ color: c.colour }}
                aria-pressed={c.on}
                disabled={working || !c.fn}
                title={c.on ? `${c.code} inkopplad: lämna tillbaka området` : `${c.code} urkopplad`}
                onClick={() => c.fn && onLocal(c.fn, !c.on)}
              >
                {c.code}
              </button>
            );
          })}
        </span>
      ) : null}
    </div>
  );
}
