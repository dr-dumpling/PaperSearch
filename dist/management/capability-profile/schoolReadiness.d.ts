import { type SchoolBackend, type SchoolReadiness } from "../../capabilities/pdf-discovery/school/index.js";
export interface DisabledEntitledAccessReadiness {
    state: "disabled";
    code: "integration_disabled";
    message: string;
    missing: [];
}
export type EntitledAccessReadiness = DisabledEntitledAccessReadiness | SchoolReadiness;
export declare function resolveSchoolReadiness(enabled: boolean, createBackend?: () => SchoolBackend, signal?: AbortSignal): Promise<EntitledAccessReadiness>;
//# sourceMappingURL=schoolReadiness.d.ts.map