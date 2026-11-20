/**
 * Key-backed publisher full-text APIs (tier `publisher_api`).
 *
 * These are plain HTTPS requests authenticated with the user's own API key.
 * Entitlement follows the key and the request's network egress, never a
 * browser session, so they belong to PaperSearch itself (ADR 0007). Browser
 * based institutional access stays with the optional entitled-access backend.
 */
import { createElsevierAdapter } from "./elsevier.js";
import { createSpringerAdapter } from "./springer.js";

export type PublisherApiFormat = "pdf" | "jats-xml";

export type PublisherApiOutcome =
  | { kind: "ok"; path: string; format: PublisherApiFormat; source: string }
  | { kind: "skipped"; message: string }
  | { kind: "error"; code: string; message: string };

export interface PublisherApiEnv {
  [key: string]: string | undefined;
}

export interface PublisherApiAdapter {
  /** Stable adapter id, used in attempt messages and file names. */
  id: string;
  /** Config key that must be present for this adapter to run. */
  requiredConfigKey: string;
  matches(doi: string): boolean;
  configured(env: PublisherApiEnv): boolean;
  fetch(
    doi: string,
    savePath: string,
    env: PublisherApiEnv,
  ): Promise<PublisherApiOutcome>;
}

export function createDefaultPublisherApiAdapters(): PublisherApiAdapter[] {
  return [createElsevierAdapter(), createSpringerAdapter()];
}

export function selectPublisherApiAdapter(
  doi: string,
  adapters: readonly PublisherApiAdapter[],
): PublisherApiAdapter | undefined {
  const normalized = doi.trim().toLowerCase();
  return adapters.find((adapter) => adapter.matches(normalized));
}

export { createElsevierAdapter } from "./elsevier.js";
export { createSpringerAdapter } from "./springer.js";
