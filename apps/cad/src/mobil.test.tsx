// CAD i mobilen (#90): the phone's addresses, each step from 0 Välj väg to 5 Klart, the flow as pure
// functions, and Fota med mobilen on the computer. The camera's own checks are in fotohjalp.test.ts.
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import type { MobileFlow, MobileHandoff, Module, PhotoJob } from "./api";
import type { Quad } from "./fotohjalp";
import { CheckPage, CornersPage, DonePage, EntryPage, GablesPage, MeasuresPage, outcomeOf, PhotoStepPage, QuestionPage, StartPage } from "./Mobil";
import {
  answerOps,
  EMPTY_DRAFT,
  gablesReady,
  measureChange,
  measuresReady,
  newModuleOf,
  openChecks,
  photoFirst,
  photoStartFor,
  photoStartOf,
  resumePath,
  stepOf,
  withGables,
  type Draft,
} from "./mobilflode";
import { MobileFollow } from "./Mobilkod";
import { isMobilePath, mobilePath, mobileRouteFor } from "./routes";
import { CURVE, PROFILES, STATION } from "./testdata";
import { CONSENT, CORNERS, DONE, JOB_ID, LENGTH, PHOTOGRAPHED } from "./testphoto";

const ID = STATION.id;
const none = () => undefined;
const html = (node: React.ReactElement) => renderToStaticMarkup(node);

const STRAIGHT: Draft = {
  ...EMPTY_DRAFT,
  name: "Mobilstation",
  width: "600",
  a: { profile: "", norm: "", steps: ["140", "57", "253"] },
  b: { profile: "", norm: "", steps: ["140", "57", "63"] },
  sameB: false,
};

describe("the phone's addresses", () => {
  it("has the steps under /m: a new module's under /m/ny, a module's under /m/<id>", () => {
    expect(isMobilePath("/m")).toBe(true);
    expect(isMobilePath("/m/ny/matt")).toBe(true);
    expect(isMobilePath("/moduler")).toBe(false);
    expect(mobileRouteFor("/m")).toEqual({ page: "entry" });
    expect(mobileRouteFor(mobilePath("start"))).toEqual({ page: "start" });
    for (const page of ["matt", "gavlar", "skiss"] as const) expect(mobileRouteFor(mobilePath(page))).toEqual({ page });
    expect(mobileRouteFor(mobilePath("fota"))).toEqual({ page: "fota" });
    expect(mobileRouteFor(mobilePath("fota", ID))).toEqual({ page: "fota", id: ID });
    expect(mobileRouteFor(mobilePath("horn", ID, JOB_ID))).toEqual({ page: "horn", id: ID, job: JOB_ID });
    expect(mobileRouteFor(mobilePath("kontroll", ID, JOB_ID))).toEqual({ page: "kontroll", id: ID, job: JOB_ID });
    const [path, search] = mobilePath("fraga", ID, JOB_ID, "nod:x1").split("?");
    expect(mobileRouteFor(path!, `?${search}`)).toEqual({ page: "fraga", id: ID, job: JOB_ID, question: "nod:x1" });
    const [done, query] = mobilePath("klar", ID, JOB_ID).split("?");
    expect(mobileRouteFor(done!, `?${query}`)).toEqual({ page: "klar", id: ID, job: JOB_ID });
    expect(mobileRouteFor("/m/inte-en-modul/foto")).toEqual({ page: "missing" });
    expect(mobileRouteFor(`/m/${ID}/kontroll/annat`)).toEqual({ page: "missing" });
  });

  it("tells the computer the step of each page (CADMOB-01)", () => {
    expect(stepOf({ page: "entry" })).toBe("start");
    expect(stepOf({ page: "matt" })).toBe("matt");
    expect(stepOf({ page: "gavlar" })).toBe("gavlar");
    for (const page of ["fota", "horn", "skiss"] as const) expect(stepOf({ page, id: ID })).toBe("fota");
    expect(stepOf({ page: "kontroll", id: ID, job: JOB_ID })).toBe("kontroll");
    expect(stepOf({ page: "fraga", id: ID, job: JOB_ID })).toBe("fraga");
    expect(stepOf({ page: "klar", id: ID })).toBe("klar");
  });

  it("takes a phone that comes back to where it was", () => {
    const flow: MobileFlow = {
      handoff: "00000000-0000-0000-0000-000000000090",
      bound: null,
      module: null,
      job: null,
      step: "start",
      expires_at: "2026-11-20T23:00:00Z",
      ended: false,
    };
    expect(resumePath(flow)).toBe("/m/ny");
    expect(resumePath({ ...flow, step: "gavlar" })).toBe("/m/ny/gavlar");
    expect(resumePath({ ...flow, bound: ID, module: ID, step: "fota" })).toBe(`/m/${ID}/foto`);
    expect(resumePath({ ...flow, module: ID, job: JOB_ID, step: "fota" })).toBe(`/m/${ID}/foto/${JOB_ID}`);
    expect(resumePath({ ...flow, module: ID, job: JOB_ID, step: "fraga" })).toBe(`/m/${ID}/kontroll/${JOB_ID}`);
    expect(resumePath({ ...flow, module: ID, job: JOB_ID, step: "klar" })).toBe(`/m/${ID}/klar?jobb=${JOB_ID}`);
  });
});

describe("the flow into the same module as the web (CADMOB-05)", () => {
  it("leaves the length to the photo: the photo makes the module, then the gables go onto it (CADMOB-02)", () => {
    expect(measuresReady(STRAIGHT)).toBe(true);
    expect(measuresReady({ ...STRAIGHT, mode: "matt" })).toBe(false);
    expect(photoFirst(STRAIGHT)).toBe(true);
    expect(newModuleOf(STRAIGHT)).toBeNull();
    expect(photoStartOf(STRAIGHT)).toMatchObject({ module: null, profile: "modulfoto", name: "Mobilstation", kind: "straight", width: 600, length: null });
    const change = withGables({ ...STATION, latest: 3 }, STRAIGHT);
    expect(change.base).toBe(3);
    expect(change.gables).toEqual([
      { end: "A", profile: null, norm: null, tracks: [140, 197, 450] },
      { end: "B", profile: null, norm: null, tracks: [140, 197, 260] },
    ]);
  });

  it("makes the module first when the length is known, or for a curve, with its gables", () => {
    const known = newModuleOf({ ...STRAIGHT, length: "1500" });
    expect(known).toMatchObject({ name: "Mobilstation", shape: { kind: "straight", length: 1500, width: 600 }, visibility: "me" });
    const curve = newModuleOf({ ...STRAIGHT, kind: "curve", chord: "1035", sagitta: "68", edge: "outer" });
    expect(curve?.shape).toMatchObject({ kind: "curve", measured: { chord: 1035, sagitta: 68 }, edge: "outer" });
    if (curve?.shape.kind === "curve") {
      // CAD16: exact, never rounded to R 2000 · 30°.
      expect(curve.shape.radius).toBeCloseTo(2003.18, 1);
      expect(curve.shape.angle).not.toBe(30);
    }
    expect(photoFirst({ ...STRAIGHT, kind: "curve" })).toBe(false);
    expect(gablesReady({ ...STRAIGHT, a: { ...STRAIGHT.a, steps: ["140", ""] } })).toBe(false);
    expect(photoStartFor(STATION)).toMatchObject({ module: ID, scale: "H0", kind: "straight", name: null, width: null });
  });

  it("uses the photo's value or one measured again, as the web's Använd", () => {
    const track = measureChange(PHOTOGRAPHED, DONE, { gable: "B", track: 3 });
    expect(track?.gables[1]?.tracks?.[2]).toBe(380);
    expect(track?.gables[1]?.profile).toBeNull();
    expect(measureChange(PHOTOGRAPHED, DONE, { gable: "B", track: 3, value: 346.2 })?.gables[1]?.tracks?.[2]).toBe(346);
    const length = measureChange(PHOTOGRAPHED, LENGTH, { length: 1213.4 });
    expect(length?.shape).toMatchObject({ length: 1213.5 });
    expect(measureChange(CURVE, DONE, { length: 1 })).toBeNull();
  });

  it("sends the answers to Att kolla with Godkänn spårplanen", () => {
    expect(answerOps({ "slut:n3": "stoppbock" })).toEqual([{ op: "answer", key: "slut:n3", answer: "stoppbock" }]);
    const checks: Module["checks"] = [
      {
        key: "slut:n3",
        kind: "open_end",
        source: "code",
        at: [1360, 230],
        title: "Spåret slutar utan att mötas",
        text: "",
        refs: [],
        choices: [{ id: "stoppbock", text: "Det är en stoppbock", closes: true, action: null }],
        answer: null,
        assumed: false,
      },
      {
        key: "nod:x1",
        kind: "question",
        source: "ai",
        at: [1250, 300],
        title: "Två växlar eller en korsning?",
        text: "",
        refs: [],
        choices: [{ id: "svara", text: "Svara", closes: false, action: "photo" }],
        answer: null,
        assumed: false,
      },
    ];
    expect(openChecks({ ...PHOTOGRAPHED, checks }).map((c) => c.key)).toEqual(["slut:n3"]);
  });
});

describe("0 Välj väg, 1 Mått, 1b Kurva and 2 Gavlar", () => {
  it("offers three ways in with their prices and the balance", () => {
    const page = html(<StartPage name="Provkonto A" tokens={86} onChoose={none} onCancel={none} />);
    expect(page).toContain("Inloggad som <b>Provkonto A</b>.");
    expect(page).toContain("Hur vill du börja?");
    for (const text of [
      "Fota modulen",
      "Fota en skiss",
      "Bara mått nu",
      "◎ 12 tokens",
      "ca 10 min",
      "12 tokens per bild",
      "Gratis",
      "<b>86 tokens</b>",
      "Tejpen markerar Kant 1",
    ]) {
      expect(page).toContain(text);
    }
    expect(page).toContain("✕</span> Avbryt");
  });

  it("asks for the name, the scale, the form and the width; the length may be left to the photo", () => {
    const page = html(<MeasuresPage draft={STRAIGHT} onDraft={none} onNext={none} onCancel={none} />);
    for (const field of ['name="mobil-namn"', 'name="mobil-langd"', 'name="mobil-bredd"', 'placeholder="ur fotot"', ">H0<", ">N<", ">0<", "▭ Rak", "◠ Kurva"])
      expect(page).toContain(field);
    expect(page).toContain("Lämna längden tom, så räknas den fram ur fotot.");
    expect(page).toContain("längd ur fotot");
    expect(page).toMatch(/<ol class="mob-steg" aria-label="Stegen"><li class="har" aria-current="step">1 Mått<\/li>/);
    expect(page).toMatch(/<button type="button" class="tm-knapp primar mob-bred">Nästa: gavlarna →<\/button>/);
    const only = html(<MeasuresPage draft={{ ...STRAIGHT, mode: "matt" }} onDraft={none} onNext={none} onCancel={none} />);
    expect(only).not.toContain("Lämna längden tom");
    expect(only).toMatch(/disabled="">Nästa: gavlarna →/);
  });

  it("measures a curve with the string and the sagitta, and shows the radius and angle exactly (CADMOB-03, CAD16)", () => {
    const page = html(
      <MeasuresPage
        draft={{ ...STRAIGHT, kind: "curve", name: "Kurva 30° · K2", chord: "1035", sagitta: "68" }}
        onDraft={none}
        onNext={none}
        onCancel={none}
      />,
    );
    for (const text of [
      "Snöret A → B",
      "Pilhöjd",
      "Spänn ett snöre mellan spår 1:s mitt vid A och vid B.",
      "Kant 1 är",
      "Ytterkanten",
      "Innerkanten",
      "utan avrundning",
    ]) {
      expect(page).toContain(text);
    }
    expect(page).toContain("R 2003,2 · 29,9");
    expect(page).not.toContain("Avrunda");
  });

  it("measures the gables with the scale's profiles, or track by track", () => {
    const page = html(<GablesPage draft={STRAIGHT} profiles={PROFILES} onDraft={none} onNext={none} onBack={none} />);
    for (const text of [
      "FREMO dubbelspår",
      "MMM enkelspår",
      "Enkelspår",
      "Dubbelspår",
      "Egen gavel – mät spår för spår",
      "Kant 1 → spår 1",
      "Spår 1 → spår 2",
      "Spår 2 → spår 3",
      "+ Lägg till spår",
      "Spår 3 är 450 mm från Kant 1",
    ]) {
      expect(page).toContain(text);
    }
    expect(page).toContain('aria-label="Gavel A sedd utifrån"');
    expect(page).toContain('name="mobil-gavel-A-2" value="253"');
    expect(page).toContain("Nästa: fota modulen →");
    expect(html(<GablesPage draft={{ ...STRAIGHT, mode: "matt", length: "1500" }} profiles={PROFILES} onDraft={none} onNext={none} onBack={none} />)).toContain(
      "Spara modulen",
    );
    const empty = html(
      <GablesPage
        draft={{ ...STRAIGHT, a: { profile: "", norm: "", steps: [""] }, sameB: true }}
        profiles={PROFILES}
        onDraft={none}
        onNext={none}
        onBack={none}
      />,
    );
    expect(empty).toMatch(/disabled="">Nästa: fota modulen →/);
  });
});

describe("3 Fota: the camera, then the corners and the price", () => {
  const quad: Quad = [
    [32, 40],
    [227, 64],
    [214, 144],
    [28, 112],
  ];

  it("shows the frame, the level, the lights and the advice over the stream", () => {
    const seen = {
      quad,
      width: 240,
      height: 180,
      progress: 0.5,
      tilt: 35,
      verdict: {
        lights: { ram: "ok", vinkel: "warn", skarpa: "ok", ljus: "ok", stilla: "ok" },
        green: false,
        advice: "Håll telefonen plant, rakt ovanför modulen. Nu 35° snett.",
      },
    } as const;
    const page = html(<PhotoStepPage title="Fota uppifrån" onPhotos={none} camera={{ camera: "on", seen }} />);
    expect(page).toContain("✓ 4 av 4 hörn i bild");
    expect(page).toContain('<polygon class="mob-ram ok" points="32,40 227,64 214,144 28,112"');
    expect(page.match(/class="mob-horn"/g)?.length).toBe(4);
    expect(page).toContain("<b>35°</b>");
    expect(page).toContain('<li class="warn" data-lampa="vinkel">');
    expect(page).toContain("Nu 35° snett.");
    expect(page).toContain('aria-label="Ta bilden"');
    expect(page).toContain("Fota i delar");
    expect(page).toContain('capture="environment"');
    expect(page).toContain("Lång modul? Fota i delar: 2–4 bilder som överlappar på mitten");
  });

  it("without a camera, as on a computer, takes a photo through the file picker", () => {
    const page = html(<PhotoStepPage title="Fota uppifrån" onPhotos={none} camera={{ camera: "none" }} />);
    expect(page).toContain("Kameran går inte att använda här");
    expect(page).toContain('aria-label="Ta bilden med telefonens kamera"');
    expect(page).toContain('name="mobil-galleri"');
    expect(page).not.toContain("<video");
  });

  it("after a lying stream without ImageCapture: Sikta så här, then the phone's own camera (iOS)", () => {
    const page = html(<PhotoStepPage title="Fota uppifrån" onPhotos={none} camera={{ camera: "on", aim: true }} />);
    expect(page).toContain('aria-label="Sikta så här"');
    expect(page).toContain("Ta bilden med kameran");
  });

  it("puts the corners as handles, asks for Kant 1 and gable A, and shows the price before reading (CADMOB-08)", () => {
    const page = html(<CornersPage module={STATION} job={CORNERS} consent={CONSENT} onRead={none} onRetake={none} />);
    expect(page.match(/class="cad-fotohorn"/g)?.length).toBe(4);
    expect(page.match(/class="mob-sida-yta"/g)?.length).toBe(4);
    expect(page).toContain(">KANT 1<");
    expect(page).toContain(">GAVEL A<");
    expect(page).toContain("✓ 4 av 4 hörn hittade");
    expect(page).toContain("Tryck sedan på den långsida som är Kant 1 och på gavel A.");
    expect(page).toContain("<b>12 tokens</b> för mätbilden");
    expect(page).toContain("Jag godkänner att mätbilden skickas till");
    expect(page).toMatch(/disabled="">Läs av med AI · 12 tokens<\/button>/);
    expect(page).toContain("Läs av utan AI · gratis");
    const derived = html(
      <CornersPage
        module={STATION}
        job={{ ...CORNERS, corners: { ...CORNERS.corners!, derived: true } }}
        consent={{ ...CONSENT, given: true }}
        onRead={none}
        onRetake={none}
      />,
    );
    expect(derived).toContain("Kant 1 och gavel A är lästa ur gavlarnas spår.");
    expect(derived).toMatch(/<button type="button" class="tm-knapp primar mob-bred">Läs av med AI · 12 tokens<\/button>/);
  });
});

describe("4 Kontroll, 4b AI:n frågar and 5 Klart", () => {
  const props = { onUseMeasure: none, onAnswer: none, onQuestion: none, onApprove: none, onLater: none, onBack: none };

  it("follows the reading while it runs", () => {
    const page = html(<CheckPage module={PHOTOGRAPHED} job={{ ...DONE, state: "running", progress: 40, step: "Spåren" }} {...props} />);
    expect(page).toContain("Läser av fotot");
    expect(page).toContain("Spåren · 40 %");
    expect(page).not.toContain("Godkänn spårplanen");
  });

  it("shows the AI's tracks as a proposal, the measures against the photo, and holds Godkänn for the question (CADMOB-09)", () => {
    const page = html(<CheckPage module={PHOTOGRAPHED} job={DONE} {...props} />);
    expect(page).toContain("Spåren AI:n ritade");
    expect(page).toContain(">förslag<");
    expect(page).toContain("4 av 5 mått stämmer");
    expect(page).toContain("Gavel B · spår 3");
    expect(page).toContain("du 345 · foto ≈ 380,2");
    for (const button of ["Mät om", "Använd 380,2", "Behåll 345"]) expect(page).toContain(button);
    expect(page).toContain("AI:n frågar om 1 parti");
    expect(page).toContain("2 växlar · 1 stickspår · ≈ 4,8 m spår");
    expect(page).toMatch(/disabled="">Godkänn spårplanen<\/button>/);
    expect(page).toContain("Spara som förslag och fortsätt senare");
    const answered = { ...DONE, questions: DONE.questions?.map((q) => ({ ...q, answer: "korsning" })) } satisfies PhotoJob;
    expect(html(<CheckPage module={PHOTOGRAPHED} job={answered} {...props} />)).toMatch(
      /<button type="button" class="tm-knapp primar mob-bred">Godkänn spårplanen<\/button>/,
    );
  });

  it("gives the length from the photo with its ± and the sleeper check (CADMOB-02, CADMOB-10)", () => {
    const page = html(<CheckPage module={{ ...PHOTOGRAPHED, shape: { kind: "straight", length: 1180, width: 700 } }} job={LENGTH} {...props} />);
    expect(page).toContain("Längden ur fotot");
    expect(page).toContain("± 6 mm");
    expect(page).toContain("Kontrollerad med sliperdelningen, 7,09 mm på raka och sneda spår.");
    expect(page).toContain("Använd 1213 mm");
  });

  it("asks about the uncertain part with the AI's choice, and offers a close-up at its price (CADMOB-04)", () => {
    const page = html(<QuestionPage module={PHOTOGRAPHED} job={DONE} question="nod:x1" consent={CONSENT} onAnswer={none} onCloseup={none} onBack={none} />);
    expect(page).toContain("⚠ Fråga 1 av 1");
    expect(page).toContain("nära gavel B");
    expect(page).toContain('aria-label="Partiet förstorat ur fotot"');
    expect(page).toContain("Två växlar eller en korsning?");
    expect(page).toContain("Två växlar");
    expect(page).toContain("En korsning");
    expect(page).toContain(">AI:n<");
    expect(page).toContain("Ta en närbild i stället · 12 tokens");
    expect(page).toContain('name="mobil-narbild"');
    expect(page).toContain("Spara svaret →");
    const seen = { ...DONE, questions: DONE.questions?.map((q) => ({ ...q, closeup_ai: "korsning" })) };
    expect(
      html(
        <QuestionPage
          module={PHOTOGRAPHED}
          job={seen}
          question="nod:x1"
          consent={{ ...CONSENT, own_ai: "Egen AI" }}
          onAnswer={none}
          onCloseup={none}
          onBack={none}
        />,
      ),
    ).toContain("Med närbilden: En korsning");
  });

  it("says the module is approved, with its measures, switches, gables and tokens", () => {
    const approved = { ...PHOTOGRAPHED, status: "approved" as const };
    expect(outcomeOf(approved)).toBe("approved");
    expect(outcomeOf(PHOTOGRAPHED)).toBe("draft");
    expect(outcomeOf(STATION)).toBe("measures");
    const page = html(<DonePage module={approved} job={DONE} outcome="approved" onNext={none} onEnd={none} />);
    for (const text of [
      "Modulen är godkänd",
      "Exempelstation · M-001",
      "1500 × 700",
      "växlar · 1 stickspår",
      "2 + 3",
      "spår vid gavlarna",
      "<b>12</b>",
      "tokens använda",
      "+ Nästa modul",
      "Klar i mobilen",
    ]) {
      expect(page).toContain(text);
    }
    expect(page).toContain('aria-label="Mätbilden av Exempelstation"');
    const measures = html(<DonePage module={STATION} job={null} outcome="measures" onEnd={none} />);
    expect(measures).toContain("Måtten är sparade");
    expect(measures).not.toContain("Nästa modul");
  });

  it("says when the code holds no more, with a way to log in", () => {
    const page = html(<EntryPage failed="Koden gäller inte längre." login="/logga-in?next=%2Fm%2Fny" />);
    expect(page).toContain("Koden gäller inte");
    expect(page).toContain('href="/logga-in?next=%2Fm%2Fny"');
    expect(html(<EntryPage />)).toContain("Öppnar CAD i mobilen");
  });
});

describe("Fota med mobilen on the computer", () => {
  const made: MobileHandoff = {
    id: "00000000-0000-0000-0000-000000000090",
    state: "waiting",
    bound: null,
    module: null,
    job: null,
    step: null,
    created_at: "2026-11-20T12:00:00Z",
    expires_at: "2026-11-20T12:10:00Z",
    opened_at: null,
    url: "https://cad.example.test/m#k=abcdefghijklmnopqrstuvwxyz012345",
    qr: "data:image/svg+xml;base64,PHN2Zz48L3N2Zz4=",
  };
  const now = new Date("2026-11-20T12:01:30Z").getTime();

  it("shows the QR code, how long it holds, and the address for a phone that cannot scan", () => {
    const page = html(<MobileFollow handoff={made} now={now} />);
    expect(page).toContain('alt="QR-kod till CAD i mobilen"');
    expect(page).toContain('src="data:image/svg+xml;base64,PHN2Zz48L3N2Zz4="');
    expect(page).toContain("Skanna koden med mobilens kamera.");
    expect(page).toContain("Koden gäller en gång och i 9 minuter till.");
    expect(page).toContain(`href="${made.url}"`);
    expect(page).toContain("Väntar på mobilen …");
  });

  it("follows the phone's step and the photo's reading, and shows the result", () => {
    const opened = { ...made, state: "opened", step: "fota", module: STATION.id, job: JOB_ID, url: null, qr: null } satisfies MobileHandoff;
    const reading = html(<MobileFollow handoff={opened} module={STATION} job={{ ...DONE, state: "running", progress: 40, step: "Spåren" }} now={now} />);
    expect(reading).toContain("Öppnad i mobilen");
    expect(reading).toContain("Steg 3 Fota");
    expect(reading).toContain("Exempelstation · M-001");
    expect(reading).toContain("Fotot läses av: Spåren · 40 %");
    expect(reading).toContain("Avsluta i mobilen");
    expect(reading).not.toContain("QR-kod");
    const done = html(<MobileFollow handoff={{ ...opened, step: "klar" }} module={{ ...PHOTOGRAPHED, status: "approved" }} job={DONE} now={now} />);
    expect(done).toContain("Steg 5 Klart");
    expect(done).toContain("Exempelstation · M-001 · godkänd");
    expect(done).toContain(`href="/moduler/${STATION.id}/foto/${JOB_ID}"`);
    expect(done).toContain("Öppna modulen");
  });

  it("says when the code ran out, and offers a new one", () => {
    const page = html(<MobileFollow handoff={{ ...made, state: "expired", url: null, qr: null }} now={now} />);
    expect(page).toContain("QR-koden har gått ut utan att någon mobil använt den.");
    expect(page).toContain("Visa en ny QR-kod");
  });
});
