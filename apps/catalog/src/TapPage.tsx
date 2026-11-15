// Blippa: hold the phone to the tag, or scan the QR code with the camera (CAT-114). In the test
// environment, simulated tags try the flows without hardware (CAT-96).
import { useId, useState } from "react";
import { api, type Account } from "./api";
import { ErrorLine, problemText, type Ctx } from "./common";
import { tagPagePath, uidFrom } from "./routes";

export function TapPage({ ctx, account, simulated }: { ctx: Ctx; account: Account | null; simulated: boolean }) {
  const { t, navigate } = ctx;
  const [text, setText] = useState("");
  const [error, setError] = useState<string | null>(null);
  const id = useId();
  return (
    <>
      <h1>{t("tapTitle")}</h1>
      <section className="tm-kort cat-tomt">
        <p className="cat-tomt-rubrik">{t("tapNotYet")}</p>
        <p>{t("tapDetail")}</p>
      </section>
      <ErrorLine text={error} />
      {simulated && account ? (
        <section className="tm-kort cat-avsnitt" aria-labelledby="sim-rubrik">
          <h2 id="sim-rubrik">{t("simulatedTitle")}</h2>
          <p className="cat-under">{t("simulatedIntro")}</p>
          <button
            type="button"
            className="tm-knapp primar"
            onClick={async () => {
              try {
                const tag = await api.newSimulated();
                navigate?.(tagPagePath(tag.uid));
              } catch (failure) {
                setError(problemText(t, failure));
              }
            }}
          >
            {t("newSimulated")}
          </button>
        </section>
      ) : null}
      <section className="tm-kort cat-avsnitt" aria-labelledby="oppna-rubrik">
        <h2 id="oppna-rubrik">{t("openTag")}</h2>
        <form
          className="cat-rad"
          onSubmit={(event) => {
            event.preventDefault();
            if (uidFrom(text)) navigate?.(tagPagePath(uidFrom(text)));
          }}
        >
          <label htmlFor={id}>{t("openTagLabel")}</label>
          <input id={id} className="tm-mono" value={text} spellCheck={false} autoComplete="off" onChange={(e) => setText(e.target.value)} />
          <button type="submit" className="tm-knapp" disabled={!uidFrom(text)}>
            {t("open")}
          </button>
        </form>
      </section>
    </>
  );
}
