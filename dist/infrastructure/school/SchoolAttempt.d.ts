export declare function schoolShortReason(code: string | undefined, unknown?: string): string;
/**
 * 被网站拦截: the site blocked the current network, or its human verification was not passed. A
 * batch pauses the paper's publisher on it (batch.ts, user 2026-11-23).
 */
export declare function blockedBySite(code: string | undefined): boolean;
/**
 * The kinds of verification the backend tells apart on a verification page (browser/challenge/kinds.py
 * LABELS, the same keys and names): the record names the one a paper last waited on (the user, 2026-11-25).
 */
export declare const CHALLENGE_TYPE_LABELS: Readonly<Record<string, string>>;
export declare function schoolAttemptDetails(code: string, trace?: {
    stoppedHost?: string;
    challengeType?: string;
}): {
    code: string;
    message: string;
};
//# sourceMappingURL=SchoolAttempt.d.ts.map