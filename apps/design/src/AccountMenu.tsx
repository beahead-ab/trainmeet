import type { ReactNode } from "react";
import { useMenu } from "./menu";

type Props = {
  name: string;
  initials: string;
  detail: string;
  buttonLabel: string;
  children: (close: () => void) => ReactNode;
};

/** The account menu: who is logged in, then Mitt konto, Hjälp och fel (ST11) and Logga ut. */
export function AccountMenu({ name, initials, detail, buttonLabel, children }: Props) {
  const menu = useMenu();
  return (
    <div className="tm-meny-ankare">
      {/* The name starts with the initials the button shows (WCAG 2.5.3, label in name). */}
      <button type="button" className="tm-konto" aria-label={`${initials}, ${buttonLabel}`} {...menu.buttonProps}>
        <span aria-hidden="true">{initials}</span>
      </button>
      <div className="tm-panel tm-kontomeny" role="region" aria-label={buttonLabel} {...menu.panelProps}>
        <div className="tm-vem">
          <span className="tm-konto stor" aria-hidden="true">
            {initials}
          </span>
          <div>
            <b>{name}</b>
            <span>{detail}</span>
          </div>
        </div>
        <div className="tm-menyval">{children(() => menu.close())}</div>
      </div>
    </div>
  );
}
