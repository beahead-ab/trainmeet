// Ljud (TKL33, KLAR-07): for a request, a train on its way here and an alarm, each of which can
// be turned off per screen. A screen is this browser tab's device, so the choice is kept in the
// browser. Made with WebAudio, without sound files, as the old TKL did (feedback.js).
import type { Sound } from "./handelser";

export type Sounds = Record<Sound, boolean>;
export const SOUND_NAMES: Record<Sound, string> = { request: "Begäran", coming: "Tåg på väg hit", alarm: "Larm" };
const STORED = "tkl-ljud";
const ALL_ON: Sounds = { request: true, coming: true, alarm: true };

export function readSounds(storage: Pick<Storage, "getItem"> | null = globalThis.localStorage ?? null): Sounds {
  try {
    const found = JSON.parse(storage?.getItem(STORED) ?? "null") as Partial<Sounds> | null;
    return { ...ALL_ON, ...(found ?? {}) };
  } catch {
    return ALL_ON;
  }
}

export function saveSounds(sounds: Sounds) {
  try {
    globalThis.localStorage?.setItem(STORED, JSON.stringify(sounds));
  } catch {
    // A browser without storage keeps the choice until the page closes.
  }
}

// Each sound as tones: frequency in Hz and length in seconds.
const TONES: Record<Sound, [number, number][]> = {
  request: [
    [660, 0.16],
    [880, 0.22],
  ],
  coming: [[523, 0.3]],
  alarm: [
    [540, 0.16],
    [540, 0.16],
    [540, 0.16],
  ],
};

let context: AudioContext | null = null;

export function play(sound: Sound, sounds: Sounds) {
  if (!sounds[sound] || typeof AudioContext === "undefined") return;
  try {
    context ??= new AudioContext();
    let at = context.currentTime;
    for (const [frequency, length] of TONES[sound]) {
      const tone = context.createOscillator();
      const volume = context.createGain();
      tone.frequency.value = frequency;
      volume.gain.setValueAtTime(0.18, at);
      volume.gain.exponentialRampToValueAtTime(0.001, at + length);
      tone.connect(volume).connect(context.destination);
      tone.start(at);
      tone.stop(at + length);
      at += length + 0.06;
    }
  } catch {
    // No sound where the browser does not allow it yet; the screen still shows everything.
  }
}

/** Delställverk (#87): Tuta, the loco's horn in this screen's loudspeaker, and the ring when a part
 * rings or asks. Played here only, whatever the screen's sound choices: they are pressed for. */
export function tone(kind: "horn" | "ring") {
  if (typeof AudioContext === "undefined") return;
  try {
    context ??= new AudioContext();
    const start = context.currentTime;
    const parts: [number, number, number][] =
      kind === "horn"
        ? [
            [370, 0, 0.55],
            [466, 0, 0.55],
            [370, 0.7, 0.9],
            [466, 0.7, 0.9],
          ]
        : [
            [880, 0, 0.18],
            [1100, 0.2, 0.18],
            [880, 0.5, 0.18],
            [1100, 0.7, 0.18],
          ];
    for (const [frequency, at, length] of parts) {
      const sound = context.createOscillator();
      const volume = context.createGain();
      sound.type = kind === "horn" ? "sawtooth" : "sine";
      sound.frequency.value = frequency;
      volume.gain.setValueAtTime(0.0001, start + at);
      volume.gain.exponentialRampToValueAtTime(0.18, start + at + 0.02);
      volume.gain.exponentialRampToValueAtTime(0.0001, start + at + length);
      sound.connect(volume).connect(context.destination);
      sound.start(start + at);
      sound.stop(start + at + length + 0.05);
    }
  } catch {
    // No sound where the browser does not allow it yet; the screen still shows everything.
  }
}
