/**
 * PaperSearch Pro's features: the Markdown (content markdown, --markdown), `paper-search pro`,
 * `failures --markdown` and the settings window's Markdown page (user, 2026-11-19). Whether this
 * edition has them is package.json's `paperSearch.proFeatures`: true in the private repository,
 * false in the public export (maintainer/release-public.py) until Pro is public at 1.0.0. The
 * command line reads it as it starts (cli.ts), so that the compiled dist/ is the same in both.
 * The backend has the same switch (school/.../edition.py) and is told this one's answer when the
 * command line starts it.
 */
let packaged;
/** package.json's answer, as a package.json says it. */
export function proFeaturesOf(pkg) {
    return pkg?.paperSearch?.proFeatures === true;
}
/** The command line, as it starts: its own package.json's answer. */
export function setPackageProFeatures(on) {
    packaged = on;
}
/** PAPER_SEARCH_PRO_FEATURES=1 or 0 overrides package.json: for tests, and for the backend it starts. */
export const PRO_FEATURES_ENV = "PAPER_SEARCH_PRO_FEATURES";
export function proFeatures(env = process.env) {
    const given = env[PRO_FEATURES_ENV]?.trim().toLowerCase();
    if (given === "1" || given === "true")
        return true;
    if (given === "0" || given === "false")
        return false;
    if (packaged === undefined)
        throw new Error("PaperSearch's edition is not known: the command line sets it from package.json as it starts");
    return packaged;
}
//# sourceMappingURL=edition.js.map