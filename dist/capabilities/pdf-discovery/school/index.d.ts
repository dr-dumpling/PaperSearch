import type { SchoolBackend } from "./types.js";
/** The configured backend, or the one at ``command`` (a fresh install's self-check). */
/** ``command``, else the configured backend as it is when a process starts. */
export declare function createSchoolBackend(command?: string): SchoolBackend;
export { browserProfileInUse, DOWNLOAD_LOCK_FILE, isStaleDownloadLock, LEGACY_SCHOOL_DATA_DIR, paperSearchDataHome, resolveDefaultSchoolProfileDir, takeDownloadLock, } from "./SchoolMcpClient.js";
export { schoolAttemptDetails, schoolShortReason } from "./SchoolAttempt.js";
export type { SchoolBackend, SchoolBatchPaper, SchoolBatchPapers, SchoolBatchPosition, SchoolBatchResults, SchoolBatchUpdate, SchoolDownloadRequest, SchoolInvocationOutcome, SchoolProgress, SchoolReadiness, SchoolReadinessState, } from "./types.js";
export type { SchoolProgressStage } from "./SchoolProgress.js";
//# sourceMappingURL=index.d.ts.map