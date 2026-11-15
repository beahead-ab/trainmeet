import type { MouseEvent, ReactNode } from "react";
import { ProductName } from "./ProductName";
import { Skylt } from "./Skylt";

export type NavItem = { href: string; label: string; current: boolean; icon?: ReactNode };
export type Navigate = (href: string) => void;

/** Follow an internal link without reloading the page; let the browser handle the rest. */
export function linkClick(navigate: Navigate | undefined, href: string) {
  return (event: MouseEvent<HTMLAnchorElement>) => {
    if (!navigate || event.defaultPrevented || event.button !== 0) return;
    if (event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
    event.preventDefault();
    navigate(href);
  };
}

type HeaderProps = {
  product: string;
  productLabel: string;
  place: string;
  home: string;
  navLabel: string;
  tabs: NavItem[];
  navigate?: Navigate;
  children?: ReactNode;
};

/**
 * The header of every TrainMeet app: the sign, the product name in dots, a thin line, the
 * page's name, the tabs, and to the far right the app switcher and the account menu.
 */
export function Header({ product, productLabel, place, home, navLabel, tabs, navigate, children }: HeaderProps) {
  return (
    <header className="tm-sidhuvud">
      <a className="tm-marke" href={home} onClick={linkClick(navigate, home)}>
        <Skylt />
        <ProductName name={product} label={productLabel} />
      </a>
      <span className="tm-streck" aria-hidden="true" />
      <span className="tm-plats">{place}</span>
      <nav className="tm-flikar" aria-label={navLabel}>
        {tabs.map((tab) => (
          <a
            key={tab.href}
            href={tab.href}
            aria-current={tab.current ? "page" : undefined}
            onClick={linkClick(navigate, tab.href)}
          >
            {tab.label}
          </a>
        ))}
      </nav>
      <span className="tm-fyll" />
      <div className="tm-hoger">{children}</div>
    </header>
  );
}

/** The bottom menu on the phone. */
export function BottomNav({ items, label, navigate }: { items: NavItem[]; label: string; navigate?: Navigate }) {
  return (
    <nav className="tm-bottenmeny" aria-label={label}>
      {items.map((item) => (
        <a
          key={item.href}
          href={item.href}
          aria-current={item.current ? "page" : undefined}
          onClick={linkClick(navigate, item.href)}
        >
          {item.icon}
          <span>{item.label}</span>
        </a>
      ))}
    </nav>
  );
}
