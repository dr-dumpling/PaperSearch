import type { CapabilityProfile } from "../capability-profile/index.js";
import type { EntitledAccessReadiness } from "../capability-profile/schoolReadiness.js";
import type { SkillStatusResult } from "../skills/index.js";
export type SmokeSeverity = "critical" | "degraded" | "warning" | "skipped";
export type SmokeCaseStatus = "passed" | "failed" | "skipped";
export interface SmokeCase {
    name: string;
    ok: boolean;
    severity: SmokeSeverity;
    status: SmokeCaseStatus;
    message: string;
    remediation?: string;
    configured?: boolean;
    enabled?: boolean;
    skipped?: boolean;
    tool?: string;
    data?: unknown;
}
export interface LiveSmokeResult {
    ok: boolean;
    mode: "live";
    cases: SmokeCase[];
    failedCases: SmokeCase[];
    degradedCases: SmokeCase[];
    severityCounts: Record<SmokeSeverity, number>;
    capabilityProfile: CapabilityProfile;
    skillStatus?: SkillStatusResult;
    nextSteps: string[];
    exitCode: number;
}
export interface LiveSmokeRunner {
    callTool(tool: string, args: Record<string, unknown>): Promise<{
        ok: boolean;
        message?: string;
        data?: unknown;
    }>;
    capabilityProfile: CapabilityProfile;
    schoolReadiness: EntitledAccessReadiness;
    skillStatus?: SkillStatusResult;
    hasConfig(key: string): boolean;
}
export declare function runLiveSmoke(runner: LiveSmokeRunner): Promise<LiveSmokeResult>;
export declare function summarizeLiveSmoke(cases: SmokeCase[], capabilityProfile: CapabilityProfile, skillStatus?: SkillStatusResult): LiveSmokeResult;
//# sourceMappingURL=index.d.ts.map