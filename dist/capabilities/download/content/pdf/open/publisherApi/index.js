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
export function createDefaultPublisherApiAdapters() {
    return [createElsevierAdapter(), createSpringerAdapter()];
}
export function selectPublisherApiAdapter(doi, adapters) {
    const normalized = doi.trim().toLowerCase();
    return adapters.find((adapter) => adapter.matches(normalized));
}
export { createElsevierAdapter } from "./elsevier.js";
export { createSpringerAdapter } from "./springer.js";
//# sourceMappingURL=index.js.map