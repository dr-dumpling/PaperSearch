import axios from "axios";
export interface UpdateSource {
    kind: "npm" | "github";
    owner?: string;
    repo?: string;
    branch?: string;
}
/** The package's own update source: `github:<owner>/<repo>#<branch>`, else npm. */
export declare function updateSourceOf(pkg: unknown): UpdateSource;
/** -1, 0 or 1 by precedence (pre-release parts compared as numbers where they are: preview.10 after preview.9);
 *  undefined for what is no version. */
export declare function compareVersions(a: string, b: string): number | undefined;
export type SelfCheck = {
    ok: true;
    source: "npm" | "github";
    current: string;
    latest: string;
    update: boolean;
    releaseNotesUrl: string;
} | {
    ok: false;
    source: "npm" | "github";
    current: string;
    code: string;
    message: string;
};
/** The newest version where this install updates from, beside the one running. */
export declare function checkSelf(options: {
    current: string;
    source: UpdateSource;
    env?: Record<string, string | undefined>;
    timeoutMs?: number;
    queryNpm?: (signal: AbortSignal) => Promise<string>;
    get?: typeof axios.get;
    /** The GitHub login ("" for none); else this computer's. */
    githubToken?: string;
    /** gh's account list, when there is no login to read (githubLoginMissing). */
    ghStatus?: () => string;
}): Promise<SelfCheck>;
/**
 * The npm prefix a global install of PaperSearch sits in: `<prefix>/lib/node_modules/papersearch` with
 * `<prefix>/bin/paper-search`, or on Windows `<prefix>\node_modules\papersearch` with `<prefix>\paper-search.cmd`;
 * "" for anything else (a checkout, a project's own node_modules, npx).
 */
export declare function globalPrefixOf(packageRoot: string, platform?: NodeJS.Platform): string;
/**
 * The PaperSearch copies the PATH finds, one per package (a command linked from two places counts once). Two on one
 * computer are updated apart, and the older one, run, takes the school extension back to its own version (the
 * maintainer's Mac, 2026-11-21: fnm's node had 0.7.1-preview.1 before Homebrew's 0.7.2-preview.5 in the PATH).
 */
export declare function installedCopies(pathEnv?: string, platform?: NodeJS.Platform): Array<{
    command: string;
    version: string;
    root: string;
}>;
/** npm as the node running PaperSearch has it (its npm-cli.js beside it), else `npm` on the PATH. */
export declare function npmCommand(execPath?: string, platform?: NodeJS.Platform): string[];
export type SelfInstall = {
    ok: true;
    from: string;
    to: string;
} | {
    ok: false;
    code: string;
    message: string;
};
/** The version ``checked`` found, installed over this one with npm (-g). */
export declare function installSelf(checked: Extract<SelfCheck, {
    ok: true;
}>, options: {
    source: UpdateSource;
    env?: Record<string, string | undefined>;
    npm?: string[];
    run?: (argv: string[]) => {
        status: number | null;
        stderr: string;
    };
    get?: typeof axios.get;
    /** The GitHub login ("" for none); else this computer's. */
    githubToken?: string;
    /** gh's account list, when there is no login to read (githubLoginMissing). */
    ghStatus?: () => string;
    /** Where this copy is installed (globalPrefixOf): the new one goes there, not where the npm would put it. */
    prefix?: string;
}): Promise<SelfInstall>;
//# sourceMappingURL=selfUpdate.d.ts.map