import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { MESSAGE_KINDS } from "./api";
import { CLOCK, hub, korplan, lokWith, me, notifier, offer, services } from "./testdata";

// What the driver does, against a fetch that answers like the hub (hub/driver_api.py).

const NOW = { meet_id: "provbanan", name: "Provbanan", clock: CLOCK, places: [{ place: "nby", code: "Nby", name: "Norrby" }] };

beforeEach(() => {
  vi.useFakeTimers();
  vi.setSystemTime(new Date("2026-11-18T09:00:00Z"));
});
afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

describe("coming in (LOK-01, LOK-16, LOK-32)", () => {
  it("joins with the QR code's code, the name and the level, and the cookie does the rest", async () => {
    const lok = lokWith({ phase: "join" });
    lok.readCode("#kod=482915");
    const { calls } = hub({
      "POST /api/drift/1/drivers/join": { status: 201, body: { driver: me().driver, key: "telefonens-nyckel" } },
      "GET /api/drift/1/drivers/me": { body: me({ service: null, start: null }) },
    });
    expect(await lok.join(" Kim Ek ", "medium", "sv", null)).toBe(true);
    expect(calls[0]).toEqual({ method: "POST", path: "/api/drift/1/drivers/join", body: { name: "Kim Ek", level: "medium", code: "482915" } });
    expect(lok.state.phase).toBe("app");
    expect(lok.state.route).toBe("tag");
    expect(JSON.stringify(lok.state)).not.toContain("telefonens-nyckel");
  });

  it("asks for the code when the hub wants it, off the meet's network", async () => {
    const lok = lokWith({ phase: "join", code: null });
    hub({ "POST /api/drift/1/drivers/join": { status: 422, body: { detail: "Skanna QR-koden på träffen, eller skriv koden." } } });
    expect(await lok.join("Kim", "easy", "sv", null)).toBe(false);
    expect(lok.state.needsCode).toBe(true);
    expect(lok.state.problem).toBe("Skanna QR-koden på träffen, eller skriv koden.");
  });

  it("joins again when the session is lost", async () => {
    const lok = lokWith({ me: me() });
    hub({ "GET /api/drift/1/drivers/me": { status: 401, body: { detail: "Kom in med QR-koden på träffen först." } }, "GET /api/drift/1/now": { body: NOW } });
    await lok.refresh();
    expect(lok.state.phase).toBe("join");
    expect(lok.state.sessionLost).toBe(true);
    expect(lok.state.me).toBeNull();
  });
});

describe("the list and the search (LOK-17, LOK-18, LOK-32)", () => {
  it("reads the list, and searches on the paper's number", async () => {
    const lok = lokWith({ me: me({ service: null }) });
    const { calls } = hub({
      "GET /api/drift/1/drivers/services": { body: services() },
      "GET /api/drift/1/drivers/services?q=5": { body: services([offer("5", { exact: true })]) },
    });
    await lok.loadServices("");
    expect(lok.state.services?.services?.map((s) => s.number)).toEqual(["1", "5", "2", "3"]);
    await lok.loadServices("5");
    expect(calls.at(-1)?.path).toBe("/api/drift/1/drivers/services?q=5");
    expect(lok.state.services?.services?.map((s) => [s.number, s.exact])).toEqual([["5", true]]);
  });

  it("keeps the paper's number beside the plan's when they differ (LOK-19)", async () => {
    const lok = lokWith({ me: me({ service: null }) });
    hub({
      "POST /api/drift/1/drivers/claim": { body: me({ service: offer("2", { taken: true }) }) },
      "GET /api/drift/1/drivers/korplan": { body: korplan({ number: "2" }) },
    });
    lok.paperHint("34");
    expect(await lok.claim(offer("2"), lok.state.paper)).toBe(true);
    expect(lok.paperOf(offer("2"))).toBe("34");
    expect(lok.state.route).toBe("korplan");
  });
});

describe("the first one gets the service (LOK-40)", () => {
  it("says it is taken when someone else was first, and reads the list again", async () => {
    const lok = lokWith({ me: me({ service: null }) });
    const { calls } = hub({
      "POST /api/drift/1/drivers/claim": { status: 409, reason: "service_taken", body: { detail: "Tjänsten är tagen." } },
      "GET /api/drift/1/drivers/services": { body: services([offer("1", { taken: true, driver: "forare-b", driver_name: "Bo" })]) },
    });
    expect(await lok.claim(offer("1"))).toBe(false);
    expect(lok.state.problem).toBe("Tjänsten är tagen. Någon annan hann före.");
    expect(calls.map((c) => `${c.method} ${c.path}`)).toEqual(["POST /api/drift/1/drivers/claim", "GET /api/drift/1/drivers/services"]);
    expect(lok.state.services?.services?.[0]?.driver_name).toBe("Bo");
    lok.setLanguage("en");
    await lok.claim(offer("1"));
    expect(lok.state.problem).toBe("The service is taken. Someone else was first.");
  });
});

describe("the four messages (LOK-23)", () => {
  it("sends Försenad, Står på linjen, Behöver hjälp and Loket krånglar", async () => {
    const lok = lokWith({ me: me() });
    const { calls } = hub({
      "POST /api/drift/1/drivers/messages": (_url, init) => ({
        status: 201,
        body: { seq: 9, kind: JSON.parse(String(init.body)).kind, driver: "forare-a", model_time: "06:04", wall_time: "2026-11-18T09:00:00Z" },
      }),
    });
    for (const kind of MESSAGE_KINDS) expect(await lok.send(kind)).toBe(true);
    expect(calls.map((c) => c.body)).toEqual([{ kind: "delayed" }, { kind: "stopped_on_line" }, { kind: "needs_help" }, { kind: "engine_trouble" }]);
    expect(lok.state.notice).toBe("Skickat 06:04 · Loket krånglar");
  });
});

describe("the reminders 20 and 10 game minutes before the start (LOK-41)", () => {
  const starting = () => me({ start: { time: "06:30", seconds: 6 * 3600 + 30 * 60, in_game_seconds: 0, in_real_seconds: null } });

  it("come as a banner in the app when notifications are not allowed, each once", () => {
    const lok = lokWith({ me: starting() });
    lok.clock.accept({ ...CLOCK, seconds: 6 * 3600 + 9 * 60 + 50 }); // 20 min 10 s to go
    lok.tick();
    expect(lok.state.notice).toBeNull();
    vi.advanceTimersByTime(5_000); // ×4: 20 game seconds later, 19 min 50 s to go
    lok.tick();
    expect(lok.state.notice).toBe("20 min kvar till tjänst 1 · börjar 06:30 (≈ 5 min i verklig tid)");
    lok.dismiss();
    lok.tick();
    expect(lok.state.notice).toBeNull();
    lok.clock.accept({ ...CLOCK, seconds: 6 * 3600 + 20 * 60 + 5 });
    lok.tick();
    expect(lok.state.notice).toBe("10 min kvar till tjänst 1 · börjar 06:30 (≈ 3 min i verklig tid) Körplanen öppnas.");
  });

  it("come as a notification when the phone allows it", () => {
    const told = notifier(true);
    const lok = lokWith({ me: starting() }, { notifier: told });
    lok.clock.accept({ ...CLOCK, seconds: 6 * 3600 + 10 * 60 + 30 });
    lok.tick();
    expect(told.shown).toEqual(["20 min kvar till tjänst 1 · börjar 06:30 (≈ 5 min i verklig tid)"]);
    expect(lok.state.notice).toBeNull();
  });

  it("stay quiet when the driver has turned them off, or the clock stands", () => {
    const lok = lokWith({ me: starting(), remindersOn: false });
    lok.clock.accept({ ...CLOCK, seconds: 6 * 3600 + 10 * 60 + 30 });
    lok.tick();
    expect(lok.state.notice).toBeNull();
    const stopped = lokWith({ me: starting() });
    stopped.clock.accept({ ...CLOCK, seconds: 6 * 3600 + 10 * 60 + 30, running: false });
    stopped.tick();
    expect(stopped.state.notice).toBeNull();
  });
});

describe("releasing and leaving (LOK-25, LOK-41)", () => {
  it("releases, stands as Paus, and leaves the meet", async () => {
    const lok = lokWith({ me: me(), korplan: korplan() });
    const { calls } = hub({
      "POST /api/drift/1/drivers/release": { body: me({ service: null }) },
      "POST /api/drift/1/drivers/me": { body: me({ service: null, driver: { ...me().driver, state: "pause" } }) },
      "POST /api/drift/1/drivers/leave": { status: 204 },
    });
    expect(await lok.release("pause")).toBe(true);
    expect(calls.map((c) => [c.path, c.body])).toEqual([
      ["/api/drift/1/drivers/release", {}],
      ["/api/drift/1/drivers/me", { state: "pause" }],
    ]);
    expect(lok.state.me?.driver.state).toBe("pause");
    expect(lok.state.route).toBe("forare");
    expect(await lok.leave()).toBe(true);
    expect(lok.state.phase).toBe("join");
    expect(lok.state.me).toBeNull();
  });
});
