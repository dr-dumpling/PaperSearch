import type { ConfigKey } from "./ConfigService.js";

/**
 * Where to get each API key. Every place that says a key is missing (errors,
 * doctor, setup prompts, skipped download steps) points here, so the user
 * learns where to apply and how to enter the key in one go.
 */
export const API_KEY_SIGNUP_URLS: Readonly<Partial<Record<ConfigKey, string>>> = {
  EASYSCHOLAR_KEY: "https://www.easyscholar.cc/console/user/open",
  SEMANTIC_SCHOLAR_API_KEY: "https://www.semanticscholar.org/product/api",
  CORE_API_KEY: "https://core.ac.uk/services/api",
  PUBMED_API_KEY:
    "https://ncbiinsights.ncbi.nlm.nih.gov/2017/11/02/new-api-keys-for-the-e-utilities/",
  WOS_API_KEY: "https://developer.clarivate.com/apis",
  IEEE_API_KEY:
    "https://developer.ieee.org/docs/read/Searching_the_IEEE_Xplore_Metadata_API",
  ELSEVIER_API_KEY: "https://dev.elsevier.com/apikey/manage",
  SPRINGER_API_KEY: "https://dev.springernature.com/",
  OPENAIRE_API_KEY: "https://develop.openaire.eu/",
};

export function apiKeySignupUrl(key: string): string | undefined {
  return API_KEY_SIGNUP_URLS[key as ConfigKey];
}

/** The command that enters `key` with hidden input, kept out of shell history. */
export function apiKeySetupCommand(key: string): string {
  return `paper-search setup ${key}`;
}

/** One sentence: where to get `key` and how to enter it. */
export function apiKeyHint(key: string): string {
  const url = apiKeySignupUrl(key);
  const command = `\`${apiKeySetupCommand(key)}\``;
  return url
    ? `Get one at ${url}, then run ${command} in your own terminal.`
    : `Run ${command} in your own terminal.`;
}
