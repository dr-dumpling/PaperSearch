import { CarsiMcpClient } from "./CarsiMcpClient.js";
import { getConfigValue } from "../../../config/ConfigService.js";
import type { CarsiBackend } from "./types.js";

/** The configured backend, or the one at ``command`` (a fresh install's self-check). */
export function createCarsiBackend(command?: string): CarsiBackend {
  return new CarsiMcpClient({
    command: command || getConfigValue("PAPER_SEARCH_CARSI_EXECUTABLE") || undefined,
  });
}

export { resolveDefaultCarsiProfileDir } from "./CarsiMcpClient.js";

export { carsiAttemptDetails, carsiShortReason } from "./CarsiAttempt.js";

export type {
  CarsiBackend,
  CarsiBatchPosition,
  CarsiBatchResults,
  CarsiBatchUpdate,
  CarsiDownloadRequest,
  CarsiInvocationOutcome,
  CarsiProgress,
  CarsiReadiness,
  CarsiReadinessState,
} from "./types.js";
export type { CarsiProgressStage } from "./CarsiProgress.js";
