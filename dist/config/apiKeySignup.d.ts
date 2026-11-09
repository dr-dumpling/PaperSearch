import type { ConfigKey } from "./ConfigService.js";
/**
 * Where to get each API key. Every place that says a key is missing (errors,
 * doctor, setup prompts, skipped download steps) points here, so the user
 * learns where to apply and how to enter the key in one go.
 */
export declare const API_KEY_SIGNUP_URLS: Readonly<Partial<Record<ConfigKey, string>>>;
export declare function apiKeySignupUrl(key: string): string | undefined;
/** The command that enters `key` with hidden input, kept out of shell history. */
export declare function apiKeySetupCommand(key: string): string;
/**
 * Keys the settings window (`paper-search settings`, part of school subscription
 * downloads) can enter: every key above. Its list is
 * carsi/paper_search_carsi/assets/api_keys.json; a test keeps the two equal.
 * (Elsevier's institution token, which only institutions get, stays in the terminal.)
 */
export declare const SETTINGS_WINDOW_KEYS: ReadonlySet<string>;
/**
 * One sentence: where to get `key` and how to enter it. The terminal works
 * everywhere, servers included; the settings window is the optional extra.
 */
export declare function apiKeyHint(key: string): string;
//# sourceMappingURL=apiKeySignup.d.ts.map