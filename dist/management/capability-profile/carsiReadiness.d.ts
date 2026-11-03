import { type CarsiBackend, type CarsiReadiness } from "../../capabilities/pdf-discovery/carsi/index.js";
export interface DisabledEntitledAccessReadiness {
    state: "disabled";
    code: "integration_disabled";
    message: string;
    missing: [];
}
export type EntitledAccessReadiness = DisabledEntitledAccessReadiness | CarsiReadiness;
export declare function resolveCarsiReadiness(enabled: boolean, createBackend?: () => CarsiBackend, signal?: AbortSignal): Promise<EntitledAccessReadiness>;
//# sourceMappingURL=carsiReadiness.d.ts.map