// Web NFC in Chrome on Android (CAT-117, CAT-118). iPhone has no Web NFC: it reads a tag that
// already carries the address with the system's own reader and opens Safari (CAT-119, CAT-120).

type NdefRecord = { recordType: string; data?: string };
type NdefReading = { serialNumber: string };
type NdefReader = {
  scan(options?: { signal?: AbortSignal }): Promise<void>;
  write(message: { records: NdefRecord[] }, options?: { signal?: AbortSignal }): Promise<void>;
  onreading: ((event: NdefReading) => void) | null;
  onreadingerror: (() => void) | null;
};
type NdefReaderClass = new () => NdefReader;

function readerClass(): NdefReaderClass | null {
  const found = (globalThis as unknown as { NDEFReader?: NdefReaderClass }).NDEFReader;
  return typeof found === "function" ? found : null;
}

/** Can this browser read and write NFC tags? Chrome on Android can. */
export const nfcSupported = () => readerClass() !== null;

/** An iPhone or iPad: tags open in Safari with the system's reader. */
export function isIos(agent: string = typeof navigator === "undefined" ? "" : navigator.userAgent): boolean {
  return /iPhone|iPad|iPod/.test(agent) || (/Macintosh/.test(agent) && /Mobile/.test(agent));
}

/** Read the serial number of the next tag, also of an empty one or one with another address. */
export async function scan(onSerial: (serial: string) => void, signal: AbortSignal, onError: () => void): Promise<void> {
  const Reader = readerClass();
  if (!Reader) throw new Error("NFC saknas");
  const reader = new Reader();
  reader.onreading = (event) => onSerial(event.serialNumber);
  reader.onreadingerror = onError;
  await reader.scan({ signal });
}

/** Write one URL record with the tag's address, so an iPhone can tap the tag too (CAT-116, CAT-118). */
export async function writeAddress(address: string, signal?: AbortSignal): Promise<void> {
  const Reader = readerClass();
  if (!Reader) throw new Error("NFC saknas");
  await new Reader().write({ records: [{ recordType: "url", data: address }] }, { signal });
}
