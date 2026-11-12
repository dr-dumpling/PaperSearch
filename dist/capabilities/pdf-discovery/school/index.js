import { SchoolMcpClient } from "./SchoolMcpClient.js";
import { getConfigValue } from "../../../config/ConfigService.js";
/** The configured backend, or the one at ``command`` (a fresh install's self-check). */
/** ``command``, else the configured backend as it is when a process starts. */
export function createSchoolBackend(command) {
    return new SchoolMcpClient({
        command: command || (() => getConfigValue("PAPER_SEARCH_SCHOOL_EXECUTABLE")),
    });
}
export { browserProfileInUse, DOWNLOAD_LOCK_FILE, isStaleDownloadLock, LEGACY_SCHOOL_DATA_DIR, paperSearchDataHome, resolveDefaultSchoolProfileDir, takeDownloadLock, } from "./SchoolMcpClient.js";
export { schoolAttemptDetails, schoolShortReason } from "./SchoolAttempt.js";
//# sourceMappingURL=index.js.map