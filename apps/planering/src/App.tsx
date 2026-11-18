import { Sidhuvud, useHub } from "@trainmeet/hubben";
import { useCallback, useEffect, useState } from "react";
import { planning, type Check, type Deviation, type Draft, type DoubleTrackQuestion, type IdMeetChoice, type MeetSummary, type NewMeet, type Proposal, type Version } from "./api";
import { BanaPage } from "./Bana";
import { DataPage } from "./Data";
import { ForarnaPage } from "./Forarna";
import { GrafPage } from "./Graf";
import { TraffarPage } from "./Traffar";
import { VersionerPage } from "./Versioner";

// Planering (PLAN-23) under the Hub's header: Träffar, and for each meet Data, Bana, Graf,
// Versioner (S6) and Förarna (PLAN-40, H77).

export type Route = { page: "traffar" } | { page: "data" | "bana" | "graf" | "versioner" | "forarna"; meet: string };

const MEET = /^\/planering\/([^/]+)(?:\/(data|bana|graf|versioner|forarna))?$/;

export function routeOf(path: string): Route {
  const found = path.replace(/\/+$/, "").match(MEET);
  if (!found?.[1]) return { page: "traffar" };
  const page = found[2] === "bana" || found[2] === "graf" || found[2] === "versioner" || found[2] === "forarna" ? found[2] : "data";
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
  // Visa i rutnätet opens Data with a block and a search from the address.
  const asked = Object.fromEntries(new URLSearchParams(typeof window === "undefined" ? "" : window.location.search)) as { block?: string; sok?: string };
  const meet = route.page === "traffar" ? null : route.meet;
  const hubState = useHub();
  // Planering: the PIN holder plans every meet (H18); someone logged in with TrainMeet ID the
  // meets where ID makes them Administratör or Arrangör (PLAN-19, #78). Someone let in with a
  // one-time code runs the traffic only (H56).
  const { owner, act, say, fail } = hubState;
  const person = Boolean(hubState.info?.person);
  const [ok, setOk] = useState(false);
  const [meets, setMeets] = useState<MeetSummary[] | null>(null);
  const [idMeets, setIdMeets] = useState<IdMeetChoice[] | null>(null);
  // Publicera and Dra tillbaka have rights of their own (PLAN-19, PLAN-24): the Arrangör
  // publishes only with Får publicera at the meet, and only Administratör withdraws.
  const mine = meet === null ? undefined : meets?.find((summary) => summary.meet.id === meet);
  const admin = owner || (mine?.may_plan ?? false);
  const mayPublish = owner || (mine?.may_publish ?? false);
  const mayWithdraw = owner || (mine?.may_withdraw ?? false);
  const [draft, setDraft] = useState<Draft | null>(null);
  const [check, setCheck] = useState<Check | null>(null);
  const [versions, setVersions] = useState<Version[] | null>(null);
  const [proposals, setProposals] = useState<Proposal[] | null>(null);
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
        const [checked, listed, proposed] = await Promise.all([planning.check(id), planning.versions(id), planning.proposals(id)]);
        setCheck(checked);
        setVersions(listed);
        setProposals(proposed);
      } catch (error) {
        fail(error);
      }
    },
    [fail],
  );

  // The list says which meets the one logged in may plan, so it is read on every page.
  const loggedIn = hubState.info?.logged_in;
  useEffect(() => {
    void planning.meets().then(setMeets, (error: unknown) => fail(error));
  }, [meet, loggedIn]);

  useEffect(() => {
    if (!person || meet !== null) return setIdMeets(null);
    void planning.idMeets().then(setIdMeets, (error: unknown) => fail(error));
  }, [person, meet]);

  useEffect(() => {
    if (meet === null) return;
    setDraft(null);
    setCheck(null);
    setVersions(null);
    setProposals(null);
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

  // Dubbelspårsfrågan (PLAN-35): Ja makes the section double track, Nej keeps it single.
  const onDoubleTrack = async (question: DoubleTrackQuestion, double: boolean) => {
    if (!meet) return;
    setBusy(true);
    let done = false;
    await act(async () => {
      setDraft(await planning.doubleTrack(meet, question.section, { double, fingerprint: question.fingerprint }));
      done = true;
    });
    if (done) tell(double ? "Sträckan är dubbelspårig i utkastet." : "Sträckan förblir enkelspårig. Frågan kommer tillbaka om tågen på den ändras.", true);
    await readVersions(meet);
    setBusy(false);
  };

  // Rimlighetskontrollen (PLAN-36): Låt stå puts a deviation aside until its calls change.
  const onLetStand = async (deviation: Deviation, stand: boolean) => {
    if (!meet) return;
    setBusy(true);
    let done = false;
    await act(async () => {
      setDraft(await (stand ? planning.letStand(meet, deviation) : planning.takeBack(meet, deviation)));
      done = true;
    });
    if (done) tell(stand ? "Avvikelsen står kvar. Den kommer tillbaka om tåget ändras där." : "Avvikelsen är tillbaka att granska.", true);
    await readVersions(meet);
    setBusy(false);
  };

  // Dra tillbaka (PLAN-18): the version stays, but can no longer be run.
  const onWithdraw = async (number: number) => {
    if (!meet) return;
    setBusy(true);
    let done = false;
    await act(async () => {
      await planning.withdraw(meet, number);
      done = true;
    });
    if (done) tell(`Version ${number} är tillbakadragen. Den kan inte längre startas eller tas i drift.`, true);
    await readVersions(meet);
    setBusy(false);
  };

  // Förslag från Drift (PLAN-03): Ta med lays it on the draft; Avslå leaves it out.
  const onAnswer = async (id: string, take: boolean) => {
    if (!meet) return;
    setBusy(true);
    let done = false;
    await act(async () => {
      if (take) setDraft(await planning.take(meet, id));
      else await planning.reject(meet, id);
      done = true;
    });
    if (done) tell(take ? "Förslaget är med i utkastet till nästa version." : "Förslaget är avslaget.", true);
    await readVersions(meet);
    setBusy(false);
  };

  return (
    <>
      <Sidhuvud {...hubState.header({ current: route.page === "traffar" ? "/planering" : `/planering/${encodeURIComponent(route.meet)}/${route.page}`, viewed: meet, navigate })} />
      <main id="innehall" className="planering">
        {route.page === "traffar" && <TraffarPage admin={owner} person={person} idMeets={idMeets} meets={meets} navigate={navigate} onCreate={(fresh) => void onCreate(fresh)} />}
        {route.page === "data" && (
          <DataPage
            admin={admin}
            meet={route.meet}
            draft={draft}
            initialBlocks={asked.block ? asked.block.split(",") : undefined}
            initialSearch={asked.sok ?? undefined}
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
        {route.page === "forarna" && (
          <ForarnaPage
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
        {route.page === "versioner" && (
          <VersionerPage
            admin={admin}
            mayPublish={mayPublish}
            mayWithdraw={mayWithdraw}
            meet={route.meet}
            draft={draft}
            check={check}
            versions={versions}
            busy={busy}
            onPublish={() => void onPublish()}
            proposals={proposals}
            onTake={(id) => void onAnswer(id, true)}
            onReject={(id) => void onAnswer(id, false)}
            onWithdraw={(number) => void onWithdraw(number)}
            onDoubleTrack={(question, double) => void onDoubleTrack(question, double)}
            onLetStand={(deviation) => void onLetStand(deviation, true)}
            onTakeBack={(deviation) => void onLetStand(deviation, false)}
          />
        )}
        <p id="message" className={"meddelande" + (ok ? " ok" : "")} role="alert">
          {hubState.message}
        </p>
      </main>
    </>
  );
}
