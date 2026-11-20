/** package.json's answer, as a package.json says it. */
export declare function proFeaturesOf(pkg: unknown): boolean;
/** The command line, as it starts: its own package.json's answer. */
export declare function setPackageProFeatures(on: boolean): void;
/** PAPER_SEARCH_PRO_FEATURES=1 or 0 overrides package.json: for tests, and for the backend it starts. */
export declare const PRO_FEATURES_ENV = "PAPER_SEARCH_PRO_FEATURES";
export declare function proFeatures(env?: Record<string, string | undefined>): boolean;
//# sourceMappingURL=edition.d.ts.map