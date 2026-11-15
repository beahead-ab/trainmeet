import { describe, expect, it } from "vitest";
import { LANGUAGES, startLanguage, text, TEXTS } from "./i18n";

describe("the texts", () => {
  it("has every text in Swedish and English, and none is empty", () => {
    const keys = Object.keys(TEXTS.sv).sort();
    for (const language of LANGUAGES) {
      expect(Object.keys(TEXTS[language]).sort()).toEqual(keys);
      for (const value of Object.values(TEXTS[language])) expect(value.trim()).not.toBe("");
    }
  });

  it("keeps the same placeholders in both languages", () => {
    const placeholders = (value: string) => (value.match(/\{\w+\}/g) ?? []).sort();
    for (const key of Object.keys(TEXTS.sv) as (keyof typeof TEXTS.sv)[]) {
      expect(placeholders(TEXTS.en[key])).toEqual(placeholders(TEXTS.sv[key]));
    }
  });

  it("fills in names and leaves unknown placeholders as they are", () => {
    expect(text("sv", "fleetOf", { name: "Provkonto A" })).toBe("Vagnparken · Provkonto A");
    expect(text("en", "fleetOf")).toBe("Fleet · {name}");
  });

  it("starts in the language chosen before, otherwise Swedish only for a Swedish browser", () => {
    expect(startLanguage("en", ["sv-SE"])).toBe("en");
    expect(startLanguage(null, ["sv-SE", "en"])).toBe("sv");
    expect(startLanguage(null, ["de-DE", "en-GB"])).toBe("en");
    expect(startLanguage("fr", [])).toBe("en");
  });
});
