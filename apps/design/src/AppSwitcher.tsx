import { useMenu } from "./menu";
import { ProductName } from "./ProductName";

export type App = {
  product: string;
  label: string;
  what: string;
  href?: string;
};

type Props = {
  apps: App[];
  current: string;
  title: string;
  sameAccount: string;
  buttonLabel: string;
  comingLabel: string;
};

/** The app switcher: every TrainMeet app with the same account (KONTO-38). */
export function AppSwitcher({ apps, current, title, sameAccount, buttonLabel, comingLabel }: Props) {
  const menu = useMenu();
  return (
    <div className="tm-meny-ankare">
      <button type="button" className="tm-ikonknapp" aria-label={buttonLabel} {...menu.buttonProps}>
        <svg viewBox="0 0 24 24" aria-hidden="true" focusable="false">
          <rect x="4" y="4" width="6.5" height="6.5" rx="1.5" />
          <rect x="13.5" y="4" width="6.5" height="6.5" rx="1.5" />
          <rect x="4" y="13.5" width="6.5" height="6.5" rx="1.5" />
          <rect x="13.5" y="13.5" width="6.5" height="6.5" rx="1.5" />
        </svg>
      </button>
      <div className="tm-panel tm-vaxlare" role="region" aria-label={title} {...menu.panelProps}>
        <div className="tm-panel-rubrik">
          <h2>{title}</h2>
          <span>{sameAccount}</span>
        </div>
        <ul>
          {apps.map((app) => {
            const isCurrent = app.product === current;
            const content = (
              <>
                <span className="tm-mini-skylt" aria-hidden="true">TRAINMEET</span>
                <ProductName name={app.product} label={app.label} className="tm-namn-liten" />
                <span className="tm-vad">{app.href || isCurrent ? app.what : comingLabel}</span>
              </>
            );
            return (
              <li key={app.product}>
                {app.href && !isCurrent ? (
                  <a className="tm-app" href={app.href}>
                    {content}
                  </a>
                ) : (
                  <span className="tm-app" aria-current={isCurrent ? "true" : undefined} aria-disabled={isCurrent ? undefined : "true"}>
                    {content}
                  </span>
                )}
              </li>
            );
          })}
        </ul>
      </div>
    </div>
  );
}
