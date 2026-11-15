import { Sidhuvud, useHub } from "@trainmeet/hubben";
import { useCallback, useEffect, useState } from "react";
import { planning, type Check, type Draft, type MeetSummary, type NewMeet, type Version } from "./api";
import { BanaPage } from "./Bana";
import { DataPage } from "./Data";
import { GrafPage } from "./Graf";
import { TraffarPage } from "./Traffar";
import { VersionerPage } from "./Versioner";

// Planering (PLAN-23) under the Hub's header: Träffar, and for each meet Data, Bana, Graf and
// Versioner (S6).

export type Route = { page: "traffar" } | { page: "data" | "bana" | "graf" | "versioner"; meet: string };

const MEET = /^\/planering\/([^/]+)(?:\/(data|bana|graf|versioner))?$/;

export function routeOf(path: string): Route {
  const found = path.replace(/\/+$/, "").match(MEET);
  if (!found?.[1]) return { page: "traffar" };
  const page = found[2] === "bana" || found[2] === "graf" || found[2] === "versioner" ? found[2] : "data";
  return { page, meet: decodeURIComponent(found[1]) };
}

/** The addresses this app draws itself; the rest (Drift, Provbanan) are other pages. */
export const isOwn = (path: string) => {
  const clean = path.replace(/\/+$/, "");
  return clean === "/planering" || MEET.test(clean);
};

export function App() {
  const [path, setPath] = useState(() => window.location.pathname);
  const route = routeOf(path);
  const meet = route.page === "traffar" ? null : route.meet;
  const hubState = useHub();
  const { admin, act, say, fail } = hubState;
  const [ok, setOk] = useState(false);
  const [meets, setMeets] = useState<MeetSummary[] | null>(null);
  const [draft, setDraft] = useState<Draft | null>(null);
  const [check, setCheck] = useState<Check | null>(null);
  const [versions, setVersions] = useState<Version[] | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    const onPop = () => setPath(window.location.pathname);
    window.addEventListener("popstate", onPop);
    document.body.classList.add("biblioteket");
    return () => window.removeEventListener("popstate", onPop);
  }, []);

  const tell = useCallback(
    (text: string, good = false) => {
      say(text);
      setOk(good);
    },
    [say],
  );

  const readVersions = useCallback(
    async (id: string) => {
      try {
        const [checked, listed] = await Promise.all([planning.check(id), planning.versions(id)]);
        setCheck(checked);
        setVersions(listed);
      } catch (error) {
        fail(error);
      }
    },
    [fail],
  );

  useEffect(() => {
    if (meet === null) {
      void planning.meets().then(setMeets, (error: unknown) => fail(error));
      return;
    }
    setDraft(null);
    setCheck(null);
    setVersions(null);
    void (async () => {
      try {
        const found = await planning.draft(meet);
        setDraft(found);
        document.title = `${found.meet.name} · Planering`;
        await readVersions(meet);
      } catch (error) {
        fail(error);
      }
    })();
  }, [meet, readVersions]);

  const navigate = useCallback(
    (href: string) => {
      const target = new URL(href, window.location.origin);
      if (!isOwn(target.pathname)) {
        window.location.assign(href);
        return;
      }
      window.history.pushState(null, "", href);
      setPath(target.pathname);
      tell("");
      window.scrollTo(0, 0);
    },
    [tell],
  );

  const onCreate = async (fresh: NewMeet) => {
    try {
      const created = await planning.create(fresh);
      window.location.assign(`/planering/${encodeURIComponent(created.meet.id)}`);
    } catch (error) {
      fail(error);
    }
  };

  const onPublish = async () => {
    if (!meet) return;
    setBusy(true);
    let published: Version | null = null;
    await act(async () => {
      published = await planning.publish(meet);
    });
    if (published) tell(`Version ${(published as Version).number} är publicerad.`, true);
    await readVersions(meet);
    setBusy(false);
  };

  return (
    <>
      <Sidhuvud {...hubState.header({ current: route.page === "traffar" ? "/planering" : `/planering/${encodeURIComponent(route.meet)}/${route.page}`, viewed: meet, navigate })} />
      <main id="innehall" className="planering">
        {route.page === "traffar" && <TraffarPage admin={admin} meets={meets} navigate={navigate} onCreate={(fresh) => void onCreate(fresh)} />}
        {route.page === "data" && (
          <DataPage
            admin={admin}
            meet={route.meet}
            draft={draft}
            findings={check?.findings ?? []}
            versions={versions}
            onDraft={(next) => {
              setDraft(next);
              void readVersions(route.meet);
            }}
            onTell={tell}
            onFail={fail}
          />
        )}
        {route.page === "bana" && (
          <BanaPage
            admin={admin}
            meet={route.meet}
            draft={draft}
            onDraft={(next) => {
              setDraft(next);
              void readVersions(route.meet);
            }}
            onTell={tell}
            onFail={fail}
          />
        )}
        {route.page === "graf" && <GrafPage draft={draft} findings={check?.findings ?? []} />}
        {route.page === "versioner" && <VersionerPage admin={admin} meet={route.meet} draft={draft} check={check} versions={versions} busy={busy} onPublish={() => void onPublish()} />}
        <p id="message" className={"meddelande" + (ok ? " ok" : "")} role="alert">
          {hubState.message}
        </p>
      </main>
    </>
  );
}
