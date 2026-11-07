import { CarsiMcpClient } from "./CarsiMcpClient.js";
import { getConfigValue } from "../../../config/ConfigService.js";
/** The configured backend, or the one at ``command`` (a fresh install's self-check). */
export function createCarsiBackend(command) {
    return new CarsiMcpClient({
        command: command || getConfigValue("PAPER_SEARCH_CARSI_EXECUTABLE") || undefined,
    });
}
export { resolveDefaultCarsiProfileDir } from "./CarsiMcpClient.js";
export { carsiAttemptDetails, carsiShortReason } from "./CarsiAttempt.js";
//# sourceMappingURL=index.js.map