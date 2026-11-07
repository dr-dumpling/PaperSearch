import type { EntitledAccessReadiness } from "./carsiReadiness.js";
export type CapabilityStatus = "available" | "degraded" | "unavailable";
export interface CapabilityEntry {
    id: "metadata_search" | "citation_expansion" | "body_snippet_search" | "journal_metrics" | "pdf_discovery" | "entitled_access";
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
    carsiReadiness?: EntitledAccessReadiness;
}
export declare function buildCapabilityProfile(options?: CapabilityProfileOptions): CapabilityProfile;
//# sourceMappingURL=index.d.ts.map