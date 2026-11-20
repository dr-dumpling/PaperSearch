/**
 * A stand-in for PaperSearch Pro in the core's tests (the converter is not in the open core):
 * it converts nothing, and answers only what a test gives it.
 */
import type { MarkdownPro } from "../../src/capabilities/download/content/markdown/pro.js";

export function fakeMarkdownPro(overrides: Partial<MarkdownPro> = {}): MarkdownPro {
  const none = async () => ({ status: "unavailable" as const, code: "fake_pro", message: "The core's tests convert nothing." });
  return {
    apiVersion: 1,
    version: "test",
    access: () => ({ ok: true }),
    fetchFulltext: none,
    fulltextFromPage: none,
    hasRulesForUrl: () => false,
    hasRulesForDoi: () => false,
    rulesName: () => undefined,
    givenUpForDoi: () => undefined,
    givenUpOutcome: (host) => ({ status: "unavailable", code: "page_not_supported", message: `${host}: given up.` }),
    batchStarted: () => {},
    triedFirstCount: 3,
    landingHosts: async () => new Map(),
    triedFirst: (items) => ({ items, sites: [] }),
    ...overrides,
  };
}
