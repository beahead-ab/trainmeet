// Blippa: hold the phone to the tag, or scan the QR code with the camera (CAT-114). Android reads
// the tag's serial number with Web NFC, also an empty tag (CAT-117). iPhone opens tags that carry
// the address in Safari (CAT-119, CAT-120). In the test environment, simulated tags try the flows
// without hardware (CAT-96).
import { useEffect, useId, useRef, useState } from "react";
import { api, type Account } from "./api";
import { ErrorLine, problemText, type Ctx } from "./common";
import { isIos, nfcSupported, scan } from "./nfc";
import { tagPagePath, uidFrom } from "./routes";

export type Reader = "nfc" | "ios" | "none";

export function readerHere(): Reader {
  if (nfcSupported()) return "nfc";
  return isIos() ? "ios" : "none";
}

export function TapView({
  ctx,
  account,
  simulated,
  reader,
  scanning,
  error,
  onStart,
  onStop,
  onSimulated,
  onOpen,
}: {
  ctx: Ctx;
  account: Account | null;
  simulated: boolean;
  reader: Reader;
  scanning: boolean;
  error: string | null;
  onStart?: () => void;
  onStop?: () => void;
  onSimulated?: () => void;
  onOpen?: (uid: string) => void;
}) {
  const { t } = ctx;
  const [text, setText] = useState("");
  const id = useId();
  return (
    <>
      <h1>{t("tapTitle")}</h1>
      <section className="tm-kort cat-tomt cat-blippa" aria-live="polite">
        {reader === "nfc" ? (
          scanning ? (
            <>
              <p className="cat-tomt-rubrik">{t("tapHold")}</p>
              <button type="button" className="tm-knapp" onClick={onStop}>
                {t("tapStop")}
              </button>
            </>
          ) : (
            <>
              <p>{t("tapAndroid")}</p>
              <button type="button" className="tm-knapp primar" onClick={onStart}>
                {t("tapStart")}
              </button>
            </>
          )
        ) : reader === "ios" ? (
          <>
            <p>{t("tapIphone")}</p>
            {account ? null : <p className="cat-under">{t("tapIphoneLogin")}</p>}
          </>
        ) : (
          <p>{t("tapNoNfc")}</p>
        )}
      </section>
      <ErrorLine text={error} />
      {simulated && account ? (
        <section className="tm-kort cat-avsnitt" aria-labelledby="sim-rubrik">
          <h2 id="sim-rubrik">{t("simulatedTitle")}</h2>
          <p className="cat-under">{t("simulatedIntro")}</p>
          <button type="button" className="tm-knapp" onClick={onSimulated}>
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
            if (uidFrom(text)) onOpen?.(uidFrom(text));
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

export function TapPage({ ctx, account, simulated }: { ctx: Ctx; account: Account | null; simulated: boolean }) {
  const { t, navigate } = ctx;
  const [scanning, setScanning] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [reader] = useState<Reader>(readerHere);
  const stop = useRef<AbortController | null>(null);

  useEffect(() => () => stop.current?.abort(), []);

  return (
    <TapView
      ctx={ctx}
      account={account}
      simulated={simulated}
      reader={reader}
      scanning={scanning}
      error={error}
      onStart={async () => {
        setError(null);
        const controller = new AbortController();
        stop.current = controller;
        setScanning(true);
        try {
          await scan(
            (serial) => {
              controller.abort();
              setScanning(false);
              navigate?.(tagPagePath(serial));
            },
            controller.signal,
            () => setError(t("tapReadError")),
          );
        } catch {
          setScanning(false);
          setError(t("tapNoNfcAllowed"));
        }
      }}
      onStop={() => {
        stop.current?.abort();
        setScanning(false);
      }}
      onSimulated={async () => {
        try {
          const tag = await api.newSimulated();
          navigate?.(tagPagePath(tag.uid));
        } catch (failure) {
          setError(problemText(t, failure));
        }
      }}
      onOpen={(uid) => navigate?.(tagPagePath(uid))}
    />
  );
}
