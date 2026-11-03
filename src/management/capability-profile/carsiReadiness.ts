import {
  createCarsiBackend,
  type CarsiBackend,
  type CarsiReadiness,
} from "../../capabilities/pdf-discovery/carsi/index.js";

export interface DisabledEntitledAccessReadiness {
  state: "disabled";
  code: "integration_disabled";
  message: string;
  missing: [];
}

export type EntitledAccessReadiness =
  | DisabledEntitledAccessReadiness
  | CarsiReadiness;

export async function resolveCarsiReadiness(
  enabled: boolean,
  createBackend: () => CarsiBackend = createCarsiBackend,
  signal?: AbortSignal,
): Promise<EntitledAccessReadiness> {
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
