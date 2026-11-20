// Ny modul: four ways in (CAD-01): Fota med mobilen with a QR code (#90), Ladda upp ett foto, Från
// en skiss and Bara mått.
import { linkClick, type Navigate } from "@trainmeet/design";
import { MobileHandoffPanel } from "./Mobilkod";
import { formPath, PATHS, SKETCH_PATH, UPLOAD_PATH } from "./routes";

export function NewModulePage({ tokens, navigate }: { tokens?: number | null; navigate?: Navigate }) {
  return (
    <section className="cad-sida" aria-labelledby="rubrik">
      <nav className="cad-brodsmulor" aria-label="Var du är">
        <a href={PATHS.library} onClick={linkClick(navigate, PATHS.library)}>
          Moduler
        </a>{" "}
        › <span aria-current="page">Ny modul</span>
      </nav>
      <div className="cad-rubrikrad">
        <div>
          <h1 id="rubrik">Ny modul</h1>
          <p className="cad-ingress">
            Välj hur modulen kommer in. Allt hamnar i samma modulkort och kan kompletteras senare, till exempel med ett foto efter
            måtten.
          </p>
        </div>
        <span className="cad-fyll" />
        {tokens != null ? <span className="cad-pill">◎ {tokens} tokens kvar</span> : null}
      </div>
      <div className="cad-vagar">
        <article className="cad-kort cad-vag-aktiv" id="fota-med-mobilen">
          <h2>Fota med mobilen</h2>
          <p>Mät längd, bredd och gavlar vid modulen och ta en bild rakt ovanifrån. AI:n ritar spåren och jämför med dina mått.</p>
          <p className="cad-taggar">
            <span className="cad-tagg">12 tokens</span> <span className="cad-tagg">ca 10 min vid modulen</span>
          </p>
          <p className="cad-dampad">Skanna QR-koden med mobilen. Mobilen hjälper dig att fota rakt, skarpt och i jämnt ljus, och tar bilden själv.</p>
          <MobileHandoffPanel navigate={navigate} />
        </article>
        <article className="cad-kort cad-vag-aktiv" id="ladda-upp-foto">
          <h2>Ladda upp ett foto</h2>
          <p>Har du redan en bild rakt ovanifrån? Ladda upp den, eller 2–4 bilder av en lång modul, och fyll i bredden. Längden kan räknas fram ur fotot.</p>
          <p className="cad-taggar">
            <span className="cad-tagg">12 tokens per mätbild</span> <span className="cad-tagg gron">Utan AI gratis</span> <span className="cad-tagg">JPG, PNG</span>
          </p>
          <div className="cad-knapprad">
            <a className="tm-knapp primar" href={UPLOAD_PATH} onClick={linkClick(navigate, UPLOAD_PATH)}>
              Ladda upp foto
            </a>
          </div>
        </article>
        <article className="cad-kort cad-vag-aktiv" id="fran-skiss">
          <h2>Från en skiss</h2>
          <p>En handritad spårplan med modulramarna utritade. Skalan tas från modulens längd. Måtten blir ungefärliga tills du fotar.</p>
          <p className="cad-taggar">
            <span className="cad-tagg">12 tokens per skiss</span> <span className="cad-tagg gron">Utan AI gratis</span>{" "}
            <span className="cad-tagg gul">± 20 mm</span>
          </p>
          <div className="cad-knapprad">
            <a className="tm-knapp primar" href={SKETCH_PATH} onClick={linkClick(navigate, SKETCH_PATH)}>
              Ladda upp skiss
            </a>
          </div>
        </article>
        <article className="cad-kort cad-vag-aktiv" id="bara-matt">
          <h2>Bara mått</h2>
          <p>
            Längd, bredd och gavlar räcker för att modulen ska passa i en anläggning. Spåren mellan gavlarna ritas ur måtten när
            gavlarna är lika, annars när du fotar.
          </p>
          <p className="cad-taggar">
            <span className="cad-tagg gron">Gratis</span>
          </p>
          <div className="cad-knapprad">
            <a className="tm-knapp" href={formPath("straight")} onClick={linkClick(navigate, formPath("straight"))}>
              Rak modul
            </a>
            <a className="tm-knapp" href={formPath("curve")} onClick={linkClick(navigate, formPath("curve"))}>
              Kurvmodul
            </a>
            <a className="tm-knapp" href={formPath("trapezoid")} onClick={linkClick(navigate, formPath("trapezoid"))}>
              Trapets
            </a>
          </div>
        </article>
      </div>
      <div className="cad-kort cad-filrad">
        <span className="cad-overrubrik">Har du redan en fil?</span>
        <div className="cad-knapprad">
          <button type="button" className="tm-knapp" disabled>
            TrainMeet-modul från Exportera
          </button>
          <button type="button" className="tm-knapp" disabled>
            DXF-ritning
          </button>
          <button type="button" className="tm-knapp" disabled>
            AnyRail
          </button>
        </div>
        <p className="cad-dampad">
          TrainMeet-modul och DXF kommer med exporten och anläggningarna (del d). DXF läses in med modulramen och spårmitten på ett
          eget lager, som i FREMO:s ritningar. AnyRail kommer med AnyRail-importen (ärende 91).
        </p>
      </div>
    </section>
  );
}
