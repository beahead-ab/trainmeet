// Gavelprofiler (CAD-07, CAD-22): the norms per scale, the general and own gables, and how many
// use them. As the view Gavelprofiler.
import { useState } from "react";
import type { ClubChoice, GableProfile, NewProfile, ProfileList } from "./api";
import { count } from "./common";
import { ProfileBar } from "./Drawing";

type Filter = "alla" | "normer" | "egna";

const KIND: Record<GableProfile["kind"], string> = { norm: "Norm", general: "Allmän", own: "Egen" };

function positions(profile: GableProfile): (number | null)[] {
  const found: (number | null)[] = [profile.first ?? null];
  for (const spacing of profile.spacings ?? []) {
    const before = found[found.length - 1];
    found.push(before != null && spacing != null ? before + spacing : null);
  }
  return found;
}

function ProfileCard({ profile }: { profile: GableProfile }) {
  const at = positions(profile);
  const known = at.filter((p): p is number => p != null);
  return (
    <article className="cad-kort cad-profil">
      <header>
        <h2>{profile.name}</h2>
        <span className={`cad-bricka ${profile.kind}`}>{KIND[profile.kind]}</span>
      </header>
      <ProfileBar width={Math.max(500, ...known.map((p) => p + 60))} positions={at} />
      <p className="tm-mono cad-lagen">{known.length ? known.map((p) => Math.round(p)).join(" ") : "läget per modul"}</p>
      <footer>
        <span className="cad-dampad">{profile.owner ? `${profile.owner.name}` : profile.note}</span>
        <span>{count(profile.uses, "gavel", "gavlar")}</span>
      </footer>
    </article>
  );
}

type FormProps = { list: ProfileList; clubs: ClubChoice[]; onCreate?: (body: NewProfile) => Promise<void> };

function NewProfileForm({ list, clubs, onCreate }: FormProps) {
  const [name, setName] = useState("");
  const [norm, setNorm] = useState("");
  const [owner, setOwner] = useState("");
  const [tracks, setTracks] = useState("");
  const [error, setError] = useState<string | null>(null);
  const admin = clubs.filter((c) => c.admin);
  const norms = list.norms.filter((n) => n.norm !== "club" || owner);
  return (
    <form
      className="cad-kort cad-formular cad-nyprofil"
      onSubmit={(event) => {
        event.preventDefault();
        const values = tracks
          .split(/[\s;/]+/)
          .map((t) => Number(t.replace(",", ".")))
          .filter((t) => t > 0);
        setError(null);
        onCreate?.({ name: name.trim(), scale: list.scale, norm: (norm || null) as NewProfile["norm"], owner: owner || null, tracks: values }).catch(
          (failure: unknown) => setError(failure instanceof Error ? failure.message : "Det gick inte att spara."),
        );
      }}
    >
      <h2>Ny gavelprofil i {list.scale}</h2>
      <label className="cad-falt">
        <span>Namn</span>
        <input name="profilnamn" required maxLength={80} value={name} onChange={(e) => setName(e.currentTarget.value)} />
      </label>
      {admin.length ? (
        <label className="cad-falt">
          <span>Ägare</span>
          <select value={owner} onChange={(e) => setOwner(e.currentTarget.value)}>
            <option value="">Jag</option>
            {admin.map((c) => (
              <option key={c.id} value={c.id}>
                {c.name}
              </option>
            ))}
          </select>
        </label>
      ) : null}
      {norms.length ? (
        <label className="cad-falt">
          <span>Norm</span>
          <select value={norm} onChange={(e) => setNorm(e.currentTarget.value)}>
            <option value="">Ingen norm</option>
            {norms.map((n) => (
              <option key={n.norm} value={n.norm}>
                {n.name}
              </option>
            ))}
          </select>
        </label>
      ) : null}
      <label className="cad-falt">
        <span>Spårens lägen från Kant 1, i mm</span>
        <input name="lagen" required placeholder="53 134 184 236" value={tracks} onChange={(e) => setTracks(e.currentTarget.value)} />
      </label>
      {error ? (
        <p className="cad-fel" role="alert">
          {error}
        </p>
      ) : null}
      <button type="submit" className="tm-knapp primar">
        Spara gavelprofilen
      </button>
    </form>
  );
}

export function ProfilesPage({ list, clubs, onCreate }: { list: ProfileList; clubs: ClubChoice[]; onCreate?: FormProps["onCreate"] }) {
  const [filter, setFilter] = useState<Filter>("alla");
  const [adding, setAdding] = useState(false);
  const shown = list.profiles.filter((p) => filter === "alla" || (filter === "normer" ? p.kind !== "own" : p.kind === "own"));
  return (
    <section className="cad-sida" aria-labelledby="rubrik">
      <div className="cad-rubrikrad">
        <div>
          <h1 id="rubrik">Gavelprofiler</h1>
          <p className="cad-ingress">
            En gavelprofil säger var spåren går ut genom gaveln, mätt från Kant 1. Moduler med samma profil passar ihop. Normerna finns
            färdiga; egna gavlar sparas när du mäter dem.
          </p>
        </div>
        <span className="cad-fyll" />
        <div className="cad-vaxel" role="group" aria-label="Visa">
          {(
            [
              ["alla", "Alla"],
              ["normer", "Normer"],
              ["egna", "Egna"],
            ] as [Filter, string][]
          ).map(([key, label]) => (
            <button key={key} type="button" aria-pressed={filter === key} onClick={() => setFilter(key)}>
              {label}
            </button>
          ))}
        </div>
        <button type="button" className="tm-knapp primar" onClick={() => setAdding((v) => !v)}>
          + Ny gavelprofil
        </button>
      </div>
      <p className="cad-dampad">
        Normerna i skala {list.scale}: {list.norms.length ? list.norms.map((n) => n.name).join(", ") : "specen namnger ingen norm än"}.
      </p>
      {adding ? (
        <NewProfileForm
          list={list}
          clubs={clubs}
          onCreate={async (body) => {
            await onCreate?.(body);
            setAdding(false);
          }}
        />
      ) : null}
      <div className="cad-profiler">
        {shown.map((profile) => (
          <ProfileCard key={profile.id} profile={profile} />
        ))}
      </div>
      <p className="cad-dampad">
        Heldragen prick: spårets läge i profilen. Ofylld prick: läget anges per modul. Normernas exakta mått läses in från FREMO, MMM och
        USMS innan lansering.
      </p>
    </section>
  );
}
