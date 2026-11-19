// PROV (TKLMOLN-11, F17): a preview run in Provbanan is kept apart from the real meet in the hub,
// and TKL marks it the same way everywhere it is connected to one: PROV in the header and a row
// in Ställverket. The hub says whether a run is Provbanan's (ConnectReply.preview, STUDIO-12).

export const PROV_SAID = "Provkörning i Provbanan, skild från den riktiga träffen. Inget här går till träffen.";

/** PROV in the header, beside the hub's chip. */
export function ProvChip() {
  return (
    <span className="tm-chip prov" title={PROV_SAID} aria-label="Provkörning">
      PROV
    </span>
  );
}

/** The row in Ställverket while TKL is connected to a preview run. */
export function ProvRad({ hub }: { hub?: string | null }) {
  return (
    <p className="prov-rad" role="note">
      <span className="prov-markering">PROV</span> {hub ? `Provkörning i Provbanan på ${hub}, skild från den riktiga träffen.` : "Provkörning i Provbanan, skild från den riktiga träffen."} Inget här går till träffen.
    </p>
  );
}
