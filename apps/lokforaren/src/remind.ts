// The reminders before the start (LOK-41): a notification when the phone allows it, otherwise a
// banner in the app; with a short sound and a buzz, as in the old Lokföraren. Push comes later.

export type Notifier = {
  /** Notifications are allowed in this browser. */
  allowed(): boolean;
  /** Not yet asked: the driver can say yes. */
  askable(): boolean;
  ask(): Promise<boolean>;
  show(title: string, body: string): void;
};

const hasNotifications = () => typeof Notification !== "undefined";

export const browserNotifier: Notifier = {
  allowed: () => hasNotifications() && Notification.permission === "granted",
  askable: () => hasNotifications() && Notification.permission === "default",
  ask: async () => {
    if (!hasNotifications()) return false;
    try {
      return (await Notification.requestPermission()) === "granted";
    } catch {
      return false;
    }
  },
  show: (title, body) => {
    const options = { body, icon: "/lokforaren/icon-192.png", tag: "lokforaren-paminnelse" };
    // On a phone, a page with a service worker shows notifications through it.
    const worker = typeof navigator !== "undefined" ? navigator.serviceWorker : undefined;
    if (worker?.controller) {
      worker.ready.then((registration) => registration.showNotification(title, options)).catch(() => undefined);
      return;
    }
    try {
      new Notification(title, options);
    } catch {
      /* the browser wants the service worker: it is not there yet */
    }
  },
};

/** A short sound and a buzz. Sound needs that the page has been used; otherwise silence. */
export function beep(): void {
  try {
    navigator.vibrate?.([200, 100, 200]);
  } catch {
    /* no vibration */
  }
  try {
    const Context = window.AudioContext;
    if (!Context) return;
    const context = new Context();
    for (const [offset, frequency] of [
      [0, 880],
      [0.25, 1175],
    ] as const) {
      const tone = context.createOscillator();
      const gain = context.createGain();
      tone.frequency.value = frequency;
      gain.gain.setValueAtTime(0.0001, context.currentTime + offset);
      gain.gain.exponentialRampToValueAtTime(0.25, context.currentTime + offset + 0.02);
      gain.gain.exponentialRampToValueAtTime(0.0001, context.currentTime + offset + 0.2);
      tone.connect(gain).connect(context.destination);
      tone.start(context.currentTime + offset);
      tone.stop(context.currentTime + offset + 0.22);
    }
  } catch {
    /* no sound */
  }
}
