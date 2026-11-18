// What the phone keeps for itself, in localStorage under lf.*: the language, the theme, the
// reminders, the paper's number beside the plan's (LOK-19), and which reminders have been given.
// Never the key (it is an HttpOnly cookie) and never anything about the other drivers (LOK-37).

export type Storage = { getItem(key: string): string | null; setItem(key: string, value: string): void; removeItem(key: string): void };

const browser = (): Storage | null => {
  try {
    return typeof localStorage === "undefined" ? null : localStorage;
  } catch {
    return null; // private mode
  }
};

export class Memory {
  constructor(private readonly storage: Storage | null = browser()) {}

  get<T>(key: string, fallback: T): T {
    try {
      const value = this.storage?.getItem(`lf.${key}`);
      return value === null || value === undefined ? fallback : (JSON.parse(value) as T);
    } catch {
      return fallback;
    }
  }

  set(key: string, value: unknown): void {
    try {
      this.storage?.setItem(`lf.${key}`, JSON.stringify(value));
    } catch {
      /* full or private: the app works without */
    }
  }

  forget(key: string): void {
    try {
      this.storage?.removeItem(`lf.${key}`);
    } catch {
      /* nothing to forget */
    }
  }
}

/** A Storage in memory, for the tests. */
export function memoryStorage(): Storage {
  const items = new Map<string, string>();
  return {
    getItem: (key) => items.get(key) ?? null,
    setItem: (key, value) => void items.set(key, value),
    removeItem: (key) => void items.delete(key),
  };
}
