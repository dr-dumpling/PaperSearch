import type { CarsiBackend } from "./types.js";
/** The configured backend, or the one at ``command`` (a fresh install's self-check). */
export declare function createCarsiBackend(command?: string): CarsiBackend;
export { resolveDefaultCarsiProfileDir, takeDownloadLock } from "./CarsiMcpClient.js";
export { carsiAttemptDetails, carsiShortReason } from "./CarsiAttempt.js";
export type { CarsiBackend, CarsiBatchPaper, CarsiBatchPapers, CarsiBatchPosition, CarsiBatchResults, CarsiBatchUpdate, CarsiDownloadRequest, CarsiInvocationOutcome, CarsiProgress, CarsiReadiness, CarsiReadinessState, } from "./types.js";
export type { CarsiProgressStage } from "./CarsiProgress.js";
//# sourceMappingURL=index.d.ts.map