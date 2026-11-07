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
/** One sentence: where to get `key` and how to enter it. */
export declare function apiKeyHint(key: string): string;
//# sourceMappingURL=apiKeySignup.d.ts.map