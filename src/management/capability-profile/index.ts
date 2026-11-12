import { CONFIG_KEYS, listConfigEntries } from "../config/index.js";
import {
  getCapabilityProfileConfigKeysBySource,
  getCapabilityProfileSources,
} from "../../registry/platformMetadata.js";
import type { EntitledAccessReadiness } from "./schoolReadiness.js";
import { apiKeySetupCommand, apiKeySignupUrl } from "../../config/apiKeySignup.js";

export type CapabilityStatus = "available" | "degraded" | "unavailable";

export interface CapabilityEntry {
  id:
    | "metadata_search"
    | "citation_expansion"
    | "body_snippet_search"
    | "journal_metrics"
    | "pdf_discovery"
    | "entitled_access";
  status: CapabilityStatus;
  reason: string;
  configured: string[];
  missing: string[];
  sourceGroups?: Record<string, string[]>;
  requiredKeys?: string[];
  optionalKeys?: string[];
  /** Where to get each missing required key and the command that enters it. */
  keySetup?: KeySetup[];
  readiness?: {
    state: EntitledAccessReadiness["state"] | "not_evaluated";
    code: string;
  };
}

export interface KeySetup {
  key: string;
  signupUrl?: string;
  command: string;
}

export interface CapabilityProfile {
  ok: boolean;
  entries: CapabilityEntry[];
  summary: Record<string, CapabilityStatus>;
}

export interface CapabilityProfileOptions {
  schoolReadiness?: EntitledAccessReadiness;
}

interface SchoolCapabilitySnapshot {
  state: EntitledAccessReadiness["state"] | "not_evaluated";
  code: string;
  status: CapabilityStatus;
  reason: string;
  configured: string[];
  missing: string[];
}

const METADATA_FREE_SOURCES = getCapabilityProfileSources("metadata_free");
const METADATA_ENTITLED_SOURCES =
  getCapabilityProfileSources("metadata_entitled");
const OPEN_ACCESS_SOURCES = getCapabilityProfileSources("pdf_open_access");
const SCIHUB_SOURCES = getCapabilityProfileSources("pdf_scihub");
const SCHOOL_BACKEND_SOURCE = "school";

const METADATA_KEY_BY_SOURCE = getCapabilityProfileConfigKeysBySource([
  "metadata_entitled",
]);

export function buildCapabilityProfile(
  options: CapabilityProfileOptions = {},
): CapabilityProfile {
  const configuredKeys = configuredConfigKeys();
  const school = schoolCapabilitySnapshot(options.schoolReadiness);
  const entries: CapabilityEntry[] = [
    metadataSearchEntry(configuredKeys),
    citationExpansionEntry(),
    bodySnippetSearchEntry(configuredKeys),
    journalMetricsEntry(configuredKeys),
    pdfDiscoveryEntry(school),
    entitledAccessEntry(school),
  ];
  return {
    ok: entries.some(
      (entry) => entry.status === "available" || entry.status === "degraded",
    ),
    entries,
    summary: Object.fromEntries(
      entries.map((entry) => [entry.id, entry.status]),
    ) as CapabilityProfile["summary"],
  };
}

function metadataSearchEntry(configuredKeys: Set<string>): CapabilityEntry {
  const configuredEntitled = METADATA_ENTITLED_SOURCES.filter((source) =>
    keysConfigured(configuredKeys, METADATA_KEY_BY_SOURCE[source] || []),
  );
  const missingEntitled = METADATA_ENTITLED_SOURCES.filter(
    (source) => !configuredEntitled.includes(source),
  );
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

function citationExpansionEntry(): CapabilityEntry {
  return {
    id: "citation_expansion",
    status: "available",
    reason:
      "Citing papers come from OpenAlex, reference lists from the publisher's Crossref deposit or OpenAlex, without keys; OPENALEX_API_KEY lists citing papers beyond the newest 10,000.",
    configured: ["openalex", "crossref"],
    missing: [],
    sourceGroups: {
      citation_sources: ["openalex", "crossref", "semantic_scholar_graph"],
    },
    optionalKeys: ["OPENALEX_API_KEY"],
  };
}

function bodySnippetSearchEntry(configuredKeys: Set<string>): CapabilityEntry {
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

function journalMetricsEntry(configuredKeys: Set<string>): CapabilityEntry {
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

function keySetup(key: string): KeySetup {
  const signupUrl = apiKeySignupUrl(key);
  return { key, ...(signupUrl ? { signupUrl } : {}), command: apiKeySetupCommand(key) };
}

function pdfDiscoveryEntry(
  school: SchoolCapabilitySnapshot,
): CapabilityEntry {
  return {
    id: "pdf_discovery",
    status: "available",
    reason: `Open-access PDF discovery and the Sci-Hub fallback stage are available; ${school.reason}`,
    configured: [
      ...OPEN_ACCESS_SOURCES,
      ...school.configured,
      ...SCIHUB_SOURCES,
    ],
    missing: school.missing,
    sourceGroups: {
      open_access_sources: OPEN_ACCESS_SOURCES,
      entitled_access_sources: school.configured,
      missing_entitled_access_sources: school.missing,
      scihub_sources: SCIHUB_SOURCES,
    },
  };
}

function entitledAccessEntry(
  school: SchoolCapabilitySnapshot,
): CapabilityEntry {
  return {
    id: "entitled_access",
    status: school.status,
    reason: `${school.reason} Publisher metadata keys do not enable entitled PDF retrieval.`,
    configured: school.configured,
    missing: school.missing,
    sourceGroups: {
      configured_sources: school.configured,
      missing_sources: school.missing,
    },
    readiness: {
      state: school.state,
      code: school.code,
    },
  };
}

function schoolCapabilitySnapshot(
  readiness?: EntitledAccessReadiness,
): SchoolCapabilitySnapshot {
  if (!readiness) {
    return {
      state: "not_evaluated",
      code: "not_evaluated",
      status: "unavailable",
      reason:
        "School backend readiness was not evaluated in this capability snapshot.",
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
        reason:
          "The optional school backend is enabled and contract-compatible.",
        configured: [SCHOOL_BACKEND_SOURCE],
        missing: [],
      };
    case "absent":
      return {
        state: readiness.state,
        code: readiness.code,
        status: "unavailable",
        reason: "The optional school backend executable is not available.",
        configured: [],
        missing: [SCHOOL_BACKEND_SOURCE],
      };
    case "incompatible":
      return {
        state: readiness.state,
        code: readiness.code,
        status: "unavailable",
        reason: "The optional school backend is not contract-compatible.",
        configured: [],
        missing: [],
      };
    case "disabled":
      return {
        state: readiness.state,
        code: readiness.code,
        status: "unavailable",
        reason: "The optional school backend integration is disabled.",
        configured: [],
        missing: [],
      };
  }
}

function configuredConfigKeys(): Set<string> {
  return new Set(
    listConfigEntries(false)
      .filter((entry) => entry.configured)
      .map((entry) => entry.key),
  );
}

function keysConfigured(configuredKeys: Set<string>, keys: string[]): boolean {
  return keys.length > 0 && keys.some((key) => configuredKeys.has(key));
}

function unique(values: string[]): string[] {
  return [
    ...new Set(
      values.filter((key) => (CONFIG_KEYS as readonly string[]).includes(key)),
    ),
  ];
}
