import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { PAGE_MAX_BYTES, PAGE_SIDE, redrawPage, scaleTo, shrinkPhoto } from "./photo";

// The photos are drawn anew on a canvas in the phone before they are sent (LOK-27, LOK-29): the
// camera's data stays behind. Vitest runs without a browser, so the canvas, the picture and the
// file reader are stand-ins that note what was drawn.

const CAMERA = "GPS 57.1834 N 14.0432 E, Pixel 9";

type Drawn = { width: number; height: number; calls: unknown[][]; quality: number[] };

let canvases: Drawn[] = [];
let size = { width: 4032, height: 3024 };
let blobBytes = 900 * 1024;

class Reader {
  result: string | null = null;
  onload: (() => void) | null = null;
  onerror: (() => void) | null = null;
  readAsDataURL(file: Blob) {
    void file.text().then((read) => {
      this.result = `data:${file.type};base64,${btoa(read)}`;
      this.onload?.();
    });
  }
}

class Picture {
  naturalWidth = 0;
  naturalHeight = 0;
  onload: (() => void) | null = null;
  onerror: (() => void) | null = null;
  source = "";
  set src(value: string) {
    this.source = value;
    this.naturalWidth = size.width;
    this.naturalHeight = size.height;
    queueMicrotask(() => this.onload?.());
  }
}

function canvas(): Drawn & Record<string, unknown> {
  const made: Drawn & Record<string, unknown> = {
    width: 0,
    height: 0,
    calls: [],
    quality: [],
    getContext: () => ({
      set fillStyle(value: string) {
        made.calls.push(["fillStyle", value]);
      },
      imageSmoothingQuality: "low",
      fillRect: (...args: unknown[]) => made.calls.push(["fillRect", ...args]),
      drawImage: (...args: unknown[]) => made.calls.push(["drawImage", ...args]),
    }),
    toBlob: (done: (blob: Blob | null) => void, type: string, quality: number) => {
      made.quality.push(quality);
      done(new Blob([new Uint8Array(blobBytes)], { type }));
    },
    toDataURL: (type: string) => `data:${type};base64,bGl0ZW4=`,
  };
  canvases.push(made);
  return made;
}

beforeEach(() => {
  canvases = [];
  size = { width: 4032, height: 3024 };
  blobBytes = 900 * 1024;
  vi.stubGlobal("FileReader", Reader);
  vi.stubGlobal("Image", Picture);
  vi.stubGlobal("document", { createElement: (tag: string) => (tag === "canvas" ? canvas() : null) });
});
afterEach(() => vi.unstubAllGlobals());

const photo = (type = "image/jpeg") => new File([`JPEG ${CAMERA}`], "IMG_0042.jpg", { type });

describe("a page of the paper drawn anew in the phone (LOK-29)", () => {
  it("draws the whole page on white, at most 2048 on its longest side, as a new JPEG without the camera's data", async () => {
    const page = await redrawPage(photo());
    const [drawn, small] = canvases;
    expect([drawn?.width, drawn?.height]).toEqual([PAGE_SIDE, 1536]);
    expect(drawn?.calls[0]).toEqual(["fillStyle", "#ffffff"]);
    expect(drawn?.calls[1]).toEqual(["fillRect", 0, 0, 2048, 1536]);
    expect(drawn?.calls[2]?.[0]).toBe("drawImage");
    expect(drawn?.calls[2]?.slice(2)).toEqual([0, 0, 2048, 1536]);
    // What is sent is the canvas's own picture, never the file the camera made.
    expect(page.picture.type).toBe("image/jpeg");
    expect(page.picture.size).toBe(900 * 1024);
    expect(await page.picture.text()).not.toContain(CAMERA);
    // The copy to show is small, and a data: address that stays in the phone.
    expect([small?.width, small?.height]).toEqual([320, 240]);
    expect(page.preview).toMatch(/^data:image\/jpeg;base64,/);
  });

  it("never draws a small photo larger, and lowers the quality until the hub takes it", async () => {
    size = { width: 900, height: 1200 };
    await redrawPage(photo("image/png"));
    expect([canvases[0]?.width, canvases[0]?.height]).toEqual([900, 1200]);
    blobBytes = PAGE_MAX_BYTES + 1;
    await expect(redrawPage(photo())).rejects.toThrow("too big");
    expect(canvases.at(-1)?.quality).toEqual([0.86, 0.72, 0.55]);
  });

  it("takes only pictures", async () => {
    await expect(redrawPage(new File(["%PDF"], "papper.pdf", { type: "application/pdf" }))).rejects.toThrow("not a picture");
    expect(canvases).toEqual([]);
  });

  it("scales the longest side down, never up", () => {
    expect(scaleTo(4032, 3024, 2048)).toBeCloseTo(2048 / 4032);
    expect(scaleTo(3024, 4032, 2048)).toBeCloseTo(2048 / 4032);
    expect(scaleTo(800, 600, 2048)).toBe(1);
  });
});

describe("the driver's own photo icon (LOK-27)", () => {
  it("is the middle square, 256 × 256, drawn anew", async () => {
    blobBytes = 40 * 1024;
    const made = await shrinkPhoto(photo());
    expect([canvases[0]?.width, canvases[0]?.height]).toEqual([256, 256]);
    expect(canvases[0]?.calls.find((call) => call[0] === "drawImage")?.slice(2)).toEqual([504, 0, 3024, 3024, 0, 0, 256, 256]);
    expect(await made.text()).not.toContain(CAMERA);
  });
});
