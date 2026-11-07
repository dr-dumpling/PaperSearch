import { createHash } from "node:crypto";
import { isValidPdfFile } from "../../../infrastructure/pdf/PdfDownload.js";
import { verifyPdfIdentity } from "../../../infrastructure/pdf/PdfIdentity.js";
import { identityRejection } from "../identity.js";
import { sanitizeDoi } from "../../../infrastructure/security/SecurityUtils.js";
import { apiKeyHint } from "../../../config/apiKeySignup.js";
import { createDefaultPublisherApiAdapters, selectPublisherApiAdapter, } from "../publisherApi/index.js";
/**
 * Keys a publisher rejected (HTTP 401) in this process, by adapter and key
 * fingerprint: a batch does not ask again for every article. A changed key is
 * tried afresh.
 */
const rejectedKeys = new Set();
function keyFingerprint(adapter, env) {
    const key = env[adapter.requiredConfigKey] || "";
    return `${adapter.id}:${createHash("sha256").update(key).digest("hex").slice(0, 16)}`;
}
/** For tests: forget remembered rejections. */
export function resetRejectedPublisherKeys() {
    rejectedKeys.clear();
}
/**
 * `publisher_api`: the user's own publisher API keys fetch full text over
 * plain HTTPS (Elsevier PDF, Springer JATS). Runs after the open-access tiers
 * and before Sci-Hub; it never opens a browser and never needs the entitled
 * access backend. See ADR 0007.
 */
export function createPublisherApiTier(adapters = createDefaultPublisherApiAdapters(), env = process.env) {
    return {
        id: "publisher_api",
        stage: "publisher_api",
        run: (context) => tryPublisherApi(context, adapters, env),
    };
}
async function tryPublisherApi(context, adapters, env) {
    const validation = sanitizeDoi(context.doi || context.paperId);
    if (!validation.valid) {
        return {
            status: "skipped",
            message: "Publisher API requires a valid DOI.",
        };
    }
    const doi = validation.sanitized;
    const adapter = selectPublisherApiAdapter(doi, adapters);
    if (!adapter) {
        return {
            status: "skipped",
            message: "No publisher full-text API for this DOI prefix.",
        };
    }
    if (!adapter.configured(env)) {
        return {
            status: "skipped",
            message: `${adapter.requiredConfigKey} not configured. ${apiKeyHint(adapter.requiredConfigKey)}`,
        };
    }
    const fingerprint = keyFingerprint(adapter, env);
    if (rejectedKeys.has(fingerprint)) {
        return {
            status: "skipped",
            code: "api_key_rejected",
            message: `${adapter.requiredConfigKey} was rejected earlier in this run; not retried.`,
        };
    }
    let outcome;
    try {
        outcome = await adapter.fetch(doi, context.savePath, env);
    }
    catch {
        return {
            status: "error",
            code: "provider_error",
            message: `${adapter.id} API attempt failed.`,
        };
    }
    if (outcome.kind === "skipped")
        return { status: "skipped", message: outcome.message };
    if (outcome.kind === "error") {
        if (outcome.code === "api_key_rejected")
            rejectedKeys.add(fingerprint);
        return { status: "error", code: outcome.code, message: outcome.message };
    }
    if (outcome.format === "jats-xml") {
        return {
            status: "ok",
            path: outcome.path,
            format: "jats-xml",
            message: `${adapter.id} full text saved as JATS XML.`,
        };
    }
    if (!isValidPdfFile(outcome.path)) {
        return {
            status: "error",
            code: "invalid_pdf",
            message: `${adapter.id} API returned an invalid PDF.`,
        };
    }
    const identity = await verifyPdfIdentity(outcome.path, doi, context.title);
    const rejection = identityRejection(identity, outcome.path);
    if (rejection)
        return rejection;
    return {
        status: "ok",
        path: outcome.path,
        format: "pdf",
        verified: true,
        message: `${adapter.id} API PDF downloaded.`,
    };
}
//# sourceMappingURL=publisherApi.js.map