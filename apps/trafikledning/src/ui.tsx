import type { ReactNode } from "react";

/** A filter chip: pressed or not, with a count when there is one (TRAFIK-32). */
export function Chip({ label, pressed, onClick, count }: { label: string; pressed: boolean; onClick?: () => void; count?: number }) {
  return (
    <button type="button" className="chip" aria-pressed={pressed} onClick={onClick}>
      {label}
      {count !== undefined && <span className="antal">{count}</span>}
    </button>
  );
}

export function Chips({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="chips" role="group" aria-label={label}>
      {children}
    </div>
  );
}

/** A select from pairs of value and text. */
export function Select({ label, options, value, onChange }: { label: string; options: [string, string][]; value: string; onChange: (value: string) => void }) {
  return (
    <select aria-label={label} value={value} onChange={(event) => onChange(event.target.value)}>
      {options.map(([key, text]) => (
        <option key={key} value={key}>
          {text}
        </option>
      ))}
    </select>
  );
}

/** For a page that shows who is connected and what they did: only for the administrator. */
export function LoginFirst({ navigate }: { navigate: (href: string) => void }) {
  return (
    <section className="kort">
      <h1>Logga in</h1>
      <p className="ingress">Den här sidan visar vem som är ansluten och vad de gjort. Logga in med hubbens PIN-kod för att se den.</p>
      <p>
        <a
          href="/"
          onClick={(event) => {
            event.preventDefault();
            navigate("/");
          }}
        >
          Till inloggningen →
        </a>
      </p>
    </section>
  );
}
