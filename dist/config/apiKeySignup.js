/**
 * Where to get each API key. Every place that says a key is missing (errors,
 * doctor, setup prompts, skipped download steps) points here, so the user
 * learns where to apply and how to enter the key in one go.
 */
export const API_KEY_SIGNUP_URLS = {
    EASYSCHOLAR_KEY: "https://www.easyscholar.cc/",
    SEMANTIC_SCHOLAR_API_KEY: "https://www.semanticscholar.org/product/api",
    CORE_API_KEY: "https://core.ac.uk/services/api",
    PUBMED_API_KEY: "https://ncbiinsights.ncbi.nlm.nih.gov/2017/11/02/new-api-keys-for-the-e-utilities/",
    WOS_API_KEY: "https://developer.clarivate.com/apis",
    IEEE_API_KEY: "https://developer.ieee.org/docs/read/Searching_the_IEEE_Xplore_Metadata_API",
    ELSEVIER_API_KEY: "https://dev.elsevier.com/apikey/manage",
    SPRINGER_API_KEY: "https://dev.springernature.com/",
    OPENAIRE_API_KEY: "https://develop.openaire.eu/",
    OPENALEX_API_KEY: "https://openalex.org/settings/api",
};
export function apiKeySignupUrl(key) {
    return API_KEY_SIGNUP_URLS[key];
}
/**
 * Contact emails some services ask for, with the page saying what they are for (nothing to sign up for).
 * Without Unpaywall's, the Unpaywall step of open downloads is skipped; Crossref's (also OpenAlex's and
 * ACM's, and PubMed Central's without NCBI_EMAIL) gets their steadier lane. The settings window shows
 * both (user, 2026-11-11).
 */
export const CONTACT_EMAIL_URLS = {
    PAPER_SEARCH_UNPAYWALL_EMAIL: "https://unpaywall.org/products/api",
    CROSSREF_MAILTO: "https://www.crossref.org/documentation/retrieve-metadata/rest-api/tips-for-using-the-crossref-rest-api/",
};
/** The command that enters `key` with hidden input, kept out of shell history. */
export function apiKeySetupCommand(key) {
    return `paper-search setup ${key}`;
}
/**
 * Keys the settings window (`paper-search settings`, part of school subscription
 * downloads) can enter: every key and email above. Its list is
 * school/paper_search_school/assets/api_keys.json; a test keeps the two equal.
 * (Elsevier's institution token, which only institutions get, stays in the terminal.)
 */
export const SETTINGS_WINDOW_KEYS = new Set([
    ...Object.keys(API_KEY_SIGNUP_URLS),
    ...Object.keys(CONTACT_EMAIL_URLS),
]);
/**
 * One sentence: where to get `key` and how to enter it. The terminal works
 * everywhere, servers included; the settings window is the optional extra.
 */
export function apiKeyHint(key) {
    const url = apiKeySignupUrl(key);
    const enter = `run \`${apiKeySetupCommand(key)}\` in your own terminal`
        + (SETTINGS_WINDOW_KEYS.has(key)
            ? `; with school subscription downloads installed, \`paper-search settings ${key}\` opens a window for it instead`
            : "");
    return url ? `Get one at ${url}, then ${enter}.` : `${enter[0].toUpperCase()}${enter.slice(1)}.`;
}
//# sourceMappingURL=apiKeySignup.js.map