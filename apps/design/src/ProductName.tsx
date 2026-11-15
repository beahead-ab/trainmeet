import { dotsFor, RADIUS } from "./glyphs";

/** A product name (HUB, CATALOG ...) in 5×7 dots, in the text colour. Never blue. */
export function ProductName({ name, label, className }: { name: string; label: string; className?: string }) {
  const { dots, width, height } = dotsFor(name);
  return (
    <svg
      className={className ?? "tm-namn"}
      viewBox={`0 0 ${width} ${height}`}
      role="img"
      aria-label={label}
      focusable="false"
    >
      <g fill="currentColor">
        {dots.map((dot) => (
          <circle key={`${dot.cx}-${dot.cy}`} cx={dot.cx} cy={dot.cy} r={RADIUS} />
        ))}
      </g>
    </svg>
  );
}
