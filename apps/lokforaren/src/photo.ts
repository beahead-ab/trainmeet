// The driver's own photo icon (LOK-27): drawn anew in the phone, square and small, before it is
// sent. Drawing it anew leaves the camera's data (place, time, device) behind; the hub takes a
// PNG, JPEG or WebP of at most 96 KB and reads nothing more out of it.

const SIZE = 256;
const MAX_BYTES = 96 * 1024;

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

/** The middle square of the picture, 256 × 256, as a JPEG small enough for the hub. */
export async function shrinkPhoto(file: File): Promise<Blob> {
  if (!file.type.startsWith("image/")) throw new Error("not a picture");
  const image = await load(file);
  const side = Math.min(image.naturalWidth, image.naturalHeight);
  if (!side) throw new Error("empty");
  const canvas = document.createElement("canvas");
  canvas.width = SIZE;
  canvas.height = SIZE;
  const context = canvas.getContext("2d");
  if (!context) throw new Error("canvas");
  context.fillStyle = "#475569";
  context.fillRect(0, 0, SIZE, SIZE);
  context.imageSmoothingQuality = "high";
  context.drawImage(image, (image.naturalWidth - side) / 2, (image.naturalHeight - side) / 2, side, side, 0, 0, SIZE, SIZE);
  for (const quality of [0.86, 0.72, 0.55]) {
    const made = await blob(canvas, quality);
    if (made && made.size <= MAX_BYTES) return made;
  }
  throw new Error("too big");
}
