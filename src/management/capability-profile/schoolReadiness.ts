import {
  createSchoolBackend,
  type SchoolBackend,
  type SchoolReadiness,
} from "../../capabilities/pdf-discovery/school/index.js";

export interface DisabledEntitledAccessReadiness {
  state: "disabled";
  code: "integration_disabled";
  message: string;
  missing: [];
}

export type EntitledAccessReadiness =
  | DisabledEntitledAccessReadiness
  | SchoolReadiness;

export async function resolveSchoolReadiness(
  enabled: boolean,
  createBackend: () => SchoolBackend = createSchoolBackend,
  signal?: AbortSignal,
): Promise<EntitledAccessReadiness> {
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
