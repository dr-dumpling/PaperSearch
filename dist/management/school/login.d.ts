export declare const LOGIN_UNAVAILABLE = "\u767B\u5F55\u5B66\u6821\u8981\u7528\u5B66\u6821\u8BA2\u9605\u4E0B\u8F7D\uFF1A\u5148\u8FD0\u884C paper-search school install\u3002";
export declare const LOGIN_NO_SCREEN = "\u767B\u5F55\u5B66\u6821\u8981\u5728\u770B\u5F97\u89C1\u7684\u6D4F\u89C8\u5668\u91CC\u5B8C\u6210\uFF0C\u8FD9\u53F0\u7535\u8111\u6CA1\u6709\u56FE\u5F62\u754C\u9762\u3002";
type Run = (file: string, args: string[], env: Record<string, string | undefined>) => Promise<{
    stdout: string;
    code: number;
}>;
export interface SchoolLoginOptions {
    /** The installed backend (PAPER_SEARCH_SCHOOL_EXECUTABLE). */
    executable: string;
    /** An article the school subscribes to: its page leads to the school's login. */
    doi: string;
    /** Seconds to wait on the school's login page; the setting when omitted. */
    maxWait?: number;
    env: Record<string, string | undefined>;
    platform?: NodeJS.Platform;
    exists?: (path: string) => boolean;
    run?: Run;
}
/**
 * Sign in to the school the way a download does, without its PDF (the
 * backend's `login`): the download browser opens the article's page, gets past
 * the site's verification, picks the school and waits on its login page for
 * the user. Success only once the school's login is confirmed and the article
 * opens in full; the session stays for the downloads that follow.
 */
export declare function schoolLogin(options: SchoolLoginOptions): Promise<Record<string, unknown>>;
export {};
//# sourceMappingURL=login.d.ts.map