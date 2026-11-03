import { createCarsiBackend, } from "../../capabilities/pdf-discovery/carsi/index.js";
export async function resolveCarsiReadiness(enabled, createBackend = createCarsiBackend, signal) {
    if (!enabled) {
        return {
            state: "disabled",
            code: "integration_disabled",
            message: "CARSI integration is disabled.",
            missing: [],
        };
    }
    return createBackend().probe(signal);
}
//# sourceMappingURL=carsiReadiness.js.map