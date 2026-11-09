export type KeyTestStatus = "valid" | "invalid" | "limited" | "unreachable" | "missing";
export interface KeyTestResult {
    key: string;
    status: KeyTestStatus;
    message: string;
}
type Values = Record<string, string | undefined>;
/** The key whose probe tests `key`: the institution token is tested with its API key. */
export declare function probeKeyFor(key: string): string | undefined;
export declare const TESTABLE_KEYS: readonly string[];
export type HttpGet = (url: string, config: Record<string, unknown>) => Promise<{
    status: number;
    data: unknown;
}>;
/** Test one key (with its companions, e.g. the institution token) against its service. */
export declare function testApiKey(key: string, values: Values, get?: HttpGet): Promise<KeyTestResult>;
export {};
//# sourceMappingURL=apiKeyTest.d.ts.map