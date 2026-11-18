import { useEffect, useRef, type ReactNode } from "react";
import type { Driver } from "./api";
import type { ClockMode } from "./clock";
import { speedText, type Text } from "./text";

// The small parts every tab uses: the icons, a driver's icon, the clock's state, the sheets that
// come up from the bottom, and the word to the driver.

const stroke = { fill: "none", stroke: "currentColor", strokeWidth: 1.8, strokeLinecap: "round", strokeLinejoin: "round" } as const;

export const Icon = {
  korplan: (
    <svg viewBox="0 0 24 24" aria-hidden="true" focusable="false">
      <g {...stroke}>
        <path d="M6 3v18" />
        <circle cx="6" cy="7" r="2" />
        <circle cx="6" cy="16" r="2" />
        <path d="M11 7h9M11 11h6M11 16h9" />
      </g>
    </svg>
  ),
  tag: (
    <svg viewBox="0 0 24 24" aria-hidden="true" focusable="false">
      <g {...stroke}>
        <rect x="5" y="3.5" width="14" height="14" rx="3" />
        <path d="M5 10h14M8.5 14h.01M15.5 14h.01M8 21l2-3.5M16 21l-2-3.5" />
      </g>
    </svg>
  ),
  forare: (
    <svg viewBox="0 0 24 24" aria-hidden="true" focusable="false">
      <g {...stroke}>
        <circle cx="9" cy="8" r="3.2" />
        <path d="M3.5 19.5c.6-3.2 2.8-5 5.5-5s4.9 1.8 5.5 5" />
        <circle cx="16.5" cy="9" r="2.6" />
        <path d="M16 14.6c2.4.1 4 1.7 4.5 4.4" />
      </g>
    </svg>
  ),
  jag: (
    <svg viewBox="0 0 24 24" aria-hidden="true" focusable="false">
      <g {...stroke}>
        <circle cx="12" cy="8" r="3.6" />
        <path d="M5 20c.8-3.8 3.6-6 7-6s6.2 2.2 7 6" />
      </g>
    </svg>
  ),
  message: (
    <svg viewBox="0 0 24 24" aria-hidden="true" focusable="false">
      <g {...stroke}>
        <path d="M4 5.5h16v10H9l-5 4z" />
      </g>
    </svg>
  ),
  paper: (
    <svg viewBox="0 0 24 24" aria-hidden="true" focusable="false">
      <g {...stroke}>
        <path d="M6 3h8l4 4v14H6z" />
        <path d="M14 3v4h4M9 12h6M9 16h6" />
      </g>
    </svg>
  ),
  back: (
    <svg viewBox="0 0 24 24" aria-hidden="true" focusable="false">
      <path d="M15 5l-7 7 7 7" {...stroke} />
    </svg>
  ),
  chevron: (
    <svg viewBox="0 0 24 24" aria-hidden="true" focusable="false">
      <path d="M9 5l7 7-7 7" {...stroke} />
    </svg>
  ),
  search: (
    <svg viewBox="0 0 24 24" aria-hidden="true" focusable="false">
      <g {...stroke}>
        <circle cx="11" cy="11" r="6" />
        <path d="M20 20l-4.5-4.5" />
      </g>
    </svg>
  ),
  warning: (
    <svg viewBox="0 0 24 24" aria-hidden="true" focusable="false">
      <g {...stroke}>
        <path d="M12 4l9 16H3z" />
        <path d="M12 10v4M12 17h.01" />
      </g>
    </svg>
  ),
  bell: (
    <svg viewBox="0 0 24 24" aria-hidden="true" focusable="false">
      <g {...stroke}>
        <path d="M6 16V11a6 6 0 0 1 12 0v5l1.5 2h-15z" />
        <path d="M10 20.5a2 2 0 0 0 4 0" />
      </g>
    </svg>
  ),
  check: (
    <svg viewBox="0 0 24 24" aria-hidden="true" focusable="false">
      <path d="M5 12.5l4.5 4.5L19 7.5" {...stroke} strokeWidth={2.4} />
    </svg>
  ),
  pin: (
    <svg viewBox="0 0 24 24" aria-hidden="true" focusable="false">
      <g {...stroke}>
        <path d="M12 21v-7" />
        <circle cx="12" cy="8" r="4.5" />
      </g>
    </svg>
  ),
  clock: (
    <svg viewBox="0 0 24 24" aria-hidden="true" focusable="false">
      <g {...stroke}>
        <circle cx="12" cy="12" r="8.5" />
        <path d="M12 7.5V12l3 2" />
      </g>
    </svg>
  ),
  camera: (
    <svg viewBox="0 0 24 24" aria-hidden="true" focusable="false">
      <g {...stroke}>
        <path d="M4 8h3.5l1.8-2.5h5.4L16.5 8H20v11H4z" />
        <circle cx="12" cy="13" r="3.5" />
      </g>
    </svg>
  ),
  close: (
    <svg viewBox="0 0 24 24" aria-hidden="true" focusable="false">
      <path d="M6 6l12 12M18 6L6 18" {...stroke} strokeWidth={2.2} />
    </svg>
  ),
};

/** The blue train mark: where the train is according to the stations (LOK-38). */
export function TrainMark() {
  return <span className="lok-tagmarke">{Icon.tag}</span>;
}

/** A driver's icon: the photo when the hub gives one, else the initials, else nothing to
 * read. Only what the API gives (LOK-37). */
export function Avatar({ driver, size = "liten" }: { driver: Driver; size?: "liten" | "stor" }) {
  if (driver.photo) {
    return <img className={`lok-ikon ${size}`} src={driver.photo} alt="" referrerPolicy="no-referrer" />;
  }
  return (
    <span className={`lok-ikon ${size} niva-${driver.level}`} aria-hidden="true">
      {driver.initials ?? ""}
    </span>
  );
}

/** GÅR · ×4, STOPPAD or INGEN KONTAKT: the clock's state beside its time. */
export function ClockPill({ mode, speed, text }: { mode: ClockMode; speed: number; text: Text }) {
  const said = mode === "running" ? text.clockStatus.running(speedText(speed)) : text.clockStatus[mode];
  return (
    <span className={`lok-klocklage ${mode}`} role="status">
      <span aria-hidden="true">●</span> {said}
    </span>
  );
}

/** A sheet from the bottom, over the page (meddela.jpg, slapp.jpg): Escape and Avbryt close it. */
export function Sheet({ title, onClose, children, text, closeLabel }: { title: string; onClose: () => void; children: ReactNode; text: Text; closeLabel?: string }) {
  const panel = useRef<HTMLDivElement>(null);
  useEffect(() => {
    panel.current?.querySelector<HTMLElement>("button, input, select, a[href]")?.focus();
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [onClose]);
  return (
    <div className="lok-ark-bakom" onClick={(event) => event.target === event.currentTarget && onClose()}>
      <div className="lok-ark" role="dialog" aria-modal="true" aria-label={title} ref={panel}>
        <span className="lok-ark-grepp" aria-hidden="true" />
        <h2>{title}</h2>
        {children}
        <button type="button" className="lok-avbryt" onClick={onClose}>
          {closeLabel ?? text.cancel}
        </button>
      </div>
    </div>
  );
}

export function Problem({ text }: { text: string | null }) {
  if (!text) return null;
  return (
    <p className="lok-problem" role="alert">
      {Icon.warning}
      <span>{text}</span>
    </p>
  );
}

export function PageHead({ title, sub, aside, back, onBack, backLabel, chip }: { title: string; sub?: ReactNode; aside?: ReactNode; back?: boolean; onBack?: () => void; backLabel?: string; chip?: string | null }) {
  return (
    <div className="lok-sidhuvud">
      <div className="lok-rubrik">
        <h1>
          {back && (
            <button type="button" className="lok-tillbaka" onClick={onBack} aria-label={backLabel}>
              {Icon.back}
            </button>
          )}
          <span>{title}</span>
          {chip && <span className="lok-papper">{chip}</span>}
        </h1>
        {sub && <p>{sub}</p>}
      </div>
      {aside}
    </div>
  );
}
