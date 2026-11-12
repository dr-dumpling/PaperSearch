import { createSchoolBackend, } from "../../capabilities/pdf-discovery/school/index.js";
export async function resolveSchoolReadiness(enabled, createBackend = createSchoolBackend, signal) {
    if (!enabled) {
        return {
            state: "disabled",
            code: "integration_disabled",
            message: "School backend integration is disabled.",
            missing: [],
        };
    }
    return createBackend().probe(signal);
}
//# sourceMappingURL=schoolReadiness.js.map