import { CONFIG_KEYS, listConfigEntries } from "../config/index.js";
import { getCapabilityProfileConfigKeysBySource, getCapabilityProfileSources, } from "../../registry/platformMetadata.js";
import { apiKeySetupCommand, apiKeySignupUrl } from "../../config/apiKeySignup.js";
const METADATA_FREE_SOURCES = getCapabilityProfileSources("metadata_free");
const METADATA_ENTITLED_SOURCES = getCapabilityProfileSources("metadata_entitled");
const OPEN_ACCESS_SOURCES = getCapabilityProfileSources("pdf_open_access");
const SCIHUB_SOURCES = getCapabilityProfileSources("pdf_scihub");
const CARSI_BACKEND_SOURCE = "carsi";
const METADATA_KEY_BY_SOURCE = getCapabilityProfileConfigKeysBySource([
    "metadata_entitled",
]);
export function buildCapabilityProfile(options = {}) {
    const configuredKeys = configuredConfigKeys();
    const carsi = carsiCapabilitySnapshot(options.carsiReadiness);
    const entries = [
        metadataSearchEntry(configuredKeys),
        citationExpansionEntry(),
        bodySnippetSearchEntry(configuredKeys),
        journalMetricsEntry(configuredKeys),
        pdfDiscoveryEntry(carsi),
        entitledAccessEntry(carsi),
    ];
    return {
        ok: entries.some((entry) => entry.status === "available" || entry.status === "degraded"),
        entries,
        summary: Object.fromEntries(entries.map((entry) => [entry.id, entry.status])),
    };
}
function metadataSearchEntry(configuredKeys) {
    const configuredEntitled = METADATA_ENTITLED_SOURCES.filter((source) => keysConfigured(configuredKeys, METADATA_KEY_BY_SOURCE[source] || []));
    const missingEntitled = METADATA_ENTITLED_SOURCES.filter((source) => !configuredEntitled.includes(source));
    return {
        id: "metadata_search",
        status: "available",
        reason: `Free metadata sources are available (${METADATA_FREE_SOURCES.join(", ")}). Sci-Hub is excluded from metadata_search; entitled metadata sources are ${configuredEntitled.length ? `configured for ${configuredEntitled.join(", ")}` : "not configured"}.`,
        configured: [...METADATA_FREE_SOURCES, ...configuredEntitled],
        missing: missingEntitled,
        sourceGroups: {
            free_sources: METADATA_FREE_SOURCES,
            entitled_sources: configuredEntitled,
            missing_entitled_sources: missingEntitled,
        },
        optionalKeys: unique(Object.values(METADATA_KEY_BY_SOURCE).flat()),
    };
}
function citationExpansionEntry() {
    return {
        id: "citation_expansion",
        status: "available",
        reason: "Citing papers come from OpenAlex, reference lists from the publisher's Crossref deposit or OpenAlex, without keys; OPENALEX_API_KEY lists citing papers beyond the newest 10,000.",
        configured: ["openalex", "crossref"],
        missing: [],
        sourceGroups: {
            citation_sources: ["openalex", "crossref", "semantic_scholar_graph"],
        },
        optionalKeys: ["OPENALEX_API_KEY"],
    };
}
function bodySnippetSearchEntry(configuredKeys) {
    const hasKey = configuredKeys.has("SEMANTIC_SCHOLAR_API_KEY");
    return {
        id: "body_snippet_search",
        status: hasKey ? "available" : "unavailable",
        reason: hasKey
            ? "SEMANTIC_SCHOLAR_API_KEY is configured, so Semantic Scholar Open Access body snippet search can run."
            : "SEMANTIC_SCHOLAR_API_KEY is missing; metadata search still works, but body snippet search cannot run.",
        configured: hasKey ? ["semantic_snippet_index"] : [],
        missing: hasKey ? [] : ["SEMANTIC_SCHOLAR_API_KEY"],
        requiredKeys: ["SEMANTIC_SCHOLAR_API_KEY"],
        ...(hasKey ? {} : { keySetup: [keySetup("SEMANTIC_SCHOLAR_API_KEY")] }),
    };
}
function journalMetricsEntry(configuredKeys) {
    const hasKey = configuredKeys.has("EASYSCHOLAR_KEY");
    return {
        id: "journal_metrics",
        status: hasKey ? "available" : "unavailable",
        reason: hasKey
            ? "EASYSCHOLAR_KEY is configured, so EasyScholar journal metrics can run."
            : "EASYSCHOLAR_KEY is missing; journal metrics are unavailable until the EasyScholar SecretKey is configured.",
        configured: hasKey ? ["easyscholar"] : [],
        missing: hasKey ? [] : ["EASYSCHOLAR_KEY"],
        requiredKeys: ["EASYSCHOLAR_KEY"],
        ...(hasKey ? {} : { keySetup: [keySetup("EASYSCHOLAR_KEY")] }),
    };
}
function keySetup(key) {
    const signupUrl = apiKeySignupUrl(key);
    return { key, ...(signupUrl ? { signupUrl } : {}), command: apiKeySetupCommand(key) };
}
function pdfDiscoveryEntry(carsi) {
    return {
        id: "pdf_discovery",
        status: "available",
        reason: `Open-access PDF discovery and the Sci-Hub fallback stage are available; ${carsi.reason}`,
        configured: [
            ...OPEN_ACCESS_SOURCES,
            ...carsi.configured,
            ...SCIHUB_SOURCES,
        ],
        missing: carsi.missing,
        sourceGroups: {
            open_access_sources: OPEN_ACCESS_SOURCES,
            entitled_access_sources: carsi.configured,
            missing_entitled_access_sources: carsi.missing,
            scihub_sources: SCIHUB_SOURCES,
        },
    };
}
function entitledAccessEntry(carsi) {
    return {
        id: "entitled_access",
        status: carsi.status,
        reason: `${carsi.reason} Publisher metadata keys do not enable entitled PDF retrieval.`,
        configured: carsi.configured,
        missing: carsi.missing,
        sourceGroups: {
            configured_sources: carsi.configured,
            missing_sources: carsi.missing,
        },
        readiness: {
            state: carsi.state,
            code: carsi.code,
        },
    };
}
function carsiCapabilitySnapshot(readiness) {
    if (!readiness) {
        return {
            state: "not_evaluated",
            code: "not_evaluated",
            status: "unavailable",
            reason: "CARSI readiness was not evaluated in this capability snapshot.",
            configured: [],
            missing: [],
        };
    }
    switch (readiness.state) {
        case "available":
            return {
                state: readiness.state,
                code: readiness.code,
                status: "available",
                reason: "The optional CARSI backend is enabled and contract-compatible.",
                configured: [CARSI_BACKEND_SOURCE],
                missing: [],
            };
        case "absent":
            return {
                state: readiness.state,
                code: readiness.code,
                status: "unavailable",
                reason: "The optional CARSI backend executable is not available.",
                configured: [],
                missing: [CARSI_BACKEND_SOURCE],
            };
        case "incompatible":
            return {
                state: readiness.state,
                code: readiness.code,
                status: "unavailable",
                reason: "The optional CARSI backend is not contract-compatible.",
                configured: [],
                missing: [],
            };
        case "disabled":
            return {
                state: readiness.state,
                code: readiness.code,
                status: "unavailable",
                reason: "The optional CARSI backend integration is disabled.",
                configured: [],
                missing: [],
            };
    }
}
function configuredConfigKeys() {
    return new Set(listConfigEntries(false)
        .filter((entry) => entry.configured)
        .map((entry) => entry.key));
}
function keysConfigured(configuredKeys, keys) {
    return keys.length > 0 && keys.some((key) => configuredKeys.has(key));
}
function unique(values) {
    return [
        ...new Set(values.filter((key) => CONFIG_KEYS.includes(key))),
    ];
}
//# sourceMappingURL=index.js.map