import type { SchoolBackend } from "./types.js";
/** The configured backend, or the one at ``command`` (a fresh install's self-check). */
/** ``command``, else the configured backend as it is when a process starts. */
export declare function createSchoolBackend(command?: string): SchoolBackend;
export { browserProfileInUse, DOWNLOAD_LOCK_FILE, isStaleDownloadLock, LEGACY_SCHOOL_DATA_DIR, paperSearchDataHome, markdownProEntry, resolveDefaultSchoolProfileDir, SCHOOL_BACKEND_UTF8_ENV, schoolLoginEnv, takeDownloadLock, } from "./SchoolMcpClient.js";
export { schoolAttemptDetails, schoolShortReason } from "./SchoolAttempt.js";
export { SCHOOL_UPDATE_NEEDED, SCHOOL_UPDATE_NEEDED_MESSAGE } from "./types.js";
export type { SchoolBackend, SchoolBatchPaper, SchoolBatchPapers, SchoolBatchPosition, SchoolBatchResults, SchoolBatchUpdate, SchoolBatchRequests, SchoolHeldPublisher, SchoolDownloadRequest, SchoolInvocationOutcome, SchoolProgress, SchoolReadiness, SchoolReadinessState, } from "./types.js";
export type { SchoolProgressStage } from "./SchoolProgress.js";
//# sourceMappingURL=index.d.ts.map