// Pictures drawn anew in the phone before they are sent: the driver's own photo icon (LOK-27)
// and the photos of a paper (LOK-29). Drawing a picture anew on a canvas leaves the camera's data
// (place, time, device) behind, and keeps it small; the hub takes a PNG, JPEG or WebP and reads
// nothing more out of it. Nothing leaves the phone before the driver sends it.

const SIZE = 256;
const MAX_BYTES = 96 * 1024;
/** A page of the paper: long enough on its longest side for the AI to read the timetable. */
export const PAGE_SIDE = 2048;
/** The hub's limit per photo (integrationer/scanned.py MAX_PICTURE). */
export const PAGE_MAX_BYTES = 5 * 1024 * 1024;
/** The page as the driver sees it before it is read: small, as a data: address, which the
 * page's rules allow (hub/web.py), and which stays in the phone. */
const PREVIEW_SIDE = 320;

function load(file: File): Promise<HTMLImageElement> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onerror = () => reject(new Error("read"));
    reader.onload = () => {
      const image = new Image();
      image.onload = () => resolve(image);
      image.onerror = () => reject(new Error("image"));
      // A data: address: the page's rules allow it, and nothing leaves the phone.
      image.src = String(reader.result);
    };
    reader.readAsDataURL(file);
  });
}

function blob(canvas: HTMLCanvasElement, quality: number): Promise<Blob | null> {
  return new Promise((resolve) => canvas.toBlob(resolve, "image/jpeg", quality));
}

function canvasOf(width: number, height: number): { canvas: HTMLCanvasElement; context: CanvasRenderingContext2D } {
  const canvas = document.createElement("canvas");
  canvas.width = width;
  canvas.height = height;
  const context = canvas.getContext("2d");
  if (!context) throw new Error("canvas");
  context.imageSmoothingQuality = "high";
  return { canvas, context };
}

/** The middle square of the picture, 256 × 256, as a JPEG small enough for the hub. */
export async function shrinkPhoto(file: File): Promise<Blob> {
  if (!file.type.startsWith("image/")) throw new Error("not a picture");
  const image = await load(file);
  const side = Math.min(image.naturalWidth, image.naturalHeight);
  if (!side) throw new Error("empty");
  const { canvas, context } = canvasOf(SIZE, SIZE);
  context.fillStyle = "#475569";
  context.fillRect(0, 0, SIZE, SIZE);
  context.drawImage(image, (image.naturalWidth - side) / 2, (image.naturalHeight - side) / 2, side, side, 0, 0, SIZE, SIZE);
  for (const quality of [0.86, 0.72, 0.55]) {
    const made = await blob(canvas, quality);
    if (made && made.size <= MAX_BYTES) return made;
  }
  throw new Error("too big");
}

/** A page of the paper, drawn anew. */
export type Page = { picture: Blob; preview: string };

/** The scale that brings the longest side down to side, never up. */
export const scaleTo = (width: number, height: number, side: number) => Math.min(1, side / Math.max(width, height));

/** A photo of a page, the whole of it, at most 2048 on its longest side, as a JPEG the hub
 * takes (LOK-29): white behind it, without the camera's data. And a small copy to show. */
export async function redrawPage(file: File): Promise<Page> {
  // Some phones give a photo no type: the picture itself then says whether it is one.
  if (file.type && !file.type.startsWith("image/")) throw new Error("not a picture");
  const image = await load(file);
  const { naturalWidth: width, naturalHeight: height } = image;
  if (!width || !height) throw new Error("empty");
  const scale = scaleTo(width, height, PAGE_SIDE);
  const page = canvasOf(Math.round(width * scale), Math.round(height * scale));
  page.context.fillStyle = "#ffffff";
  page.context.fillRect(0, 0, page.canvas.width, page.canvas.height);
  page.context.drawImage(image, 0, 0, page.canvas.width, page.canvas.height);
  let picture: Blob | null = null;
  for (const quality of [0.86, 0.72, 0.55]) {
    const made = await blob(page.canvas, quality);
    if (made && made.size <= PAGE_MAX_BYTES) {
      picture = made;
      break;
    }
  }
  if (!picture) throw new Error("too big");
  const small = scaleTo(width, height, PREVIEW_SIDE);
  const preview = canvasOf(Math.max(1, Math.round(width * small)), Math.max(1, Math.round(height * small)));
  preview.context.drawImage(page.canvas, 0, 0, preview.canvas.width, preview.canvas.height);
  return { picture, preview: preview.canvas.toDataURL("image/jpeg", 0.7) };
}
