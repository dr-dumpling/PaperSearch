/**
 * PaperSearch Pro: the Markdown converter, apart from the open core (user, 2026-11-18). The core arranges each paper's folders, visits and
 * records (step.ts) and asks Pro for the conversion through ``MarkdownPro``, handing it the
 * little it needs of the core (``ProHost``). Pro is loaded from PaperSearch's data folder
 * (or ``PAPER_SEARCH_PRO_PATH``); without it, or while it says it cannot be used now
 * (``access``), a paper's Markdown says so and the PDF and supplementary files go on.
 */
import { existsSync, mkdirSync, readdirSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { dirname, join, relative } from "node:path";
import { pathToFileURL } from "node:url";
import { USER_AGENT } from "../../../../config/constants.js";
import { proFeatures } from "../../../../config/edition.js";
import { markdownProEntry, paperSearchDataHome } from "../../../../infrastructure/school/index.js";
import { pmcidForDoi } from "../pdf/open/pmcCloud.js";
/** Raised when ``ProHost`` or ``MarkdownPro`` changes; Pro says which one it was built for. */
export const MARKDOWN_PRO_API = 1;
/** No Pro on this computer. */
export const MARKDOWN_PRO_REQUIRED = "markdown_pro_required";
let loading;
let current;
/** Where Pro is installed (the same path the backend and the settings window are given). */
export function proEntry(env = process.env) {
    return markdownProEntry(env);
}
export function proHost(env = process.env) {
    return { apiVersion: MARKDOWN_PRO_API, userAgent: USER_AGENT, dataHome: paperSearchDataHome(env), pmcidForDoi };
}
/**
 * Pro, loaded once; undefined when it is not installed or was built for another core, and never
 * loaded without PaperSearch Pro's features (config/edition.ts).
 */
export function loadMarkdownPro() {
    if (!proFeatures())
        return Promise.resolve(undefined);
    loading ??= (async () => {
        const entry = proEntry();
        if (!existsSync(entry))
            return undefined;
        try {
            const module = await import(pathToFileURL(entry).href);
            const pro = await module.createMarkdownPro?.(proHost());
            if (!pro || pro.apiVersion !== MARKDOWN_PRO_API) {
                process.stderr.write(`[Markdown] 本机的 PaperSearch Pro 与当前版本不配套（接口 ${pro?.apiVersion ?? "?"}，需要 ${MARKDOWN_PRO_API}），请更新 Pro。\n`);
                return undefined;
            }
            current = pro;
            return pro;
        }
        catch (error) {
            process.stderr.write(`[Markdown] PaperSearch Pro 没能加载：${error instanceof Error ? error.message : String(error)}\n`);
            return undefined;
        }
    })();
    return loading;
}
/** Pro as loaded so far (loadMarkdownPro first). */
export function markdownPro() {
    return current;
}
/** This Pro, or none: for tests, and for a program that embeds Pro itself. */
export function useMarkdownPro(pro) {
    current = pro;
    loading = Promise.resolve(pro);
}
/** Why no Markdown can be made now, or undefined when it can (loadMarkdownPro first). */
export function markdownBlocked(pro = current) {
    if (!pro) {
        return { code: MARKDOWN_PRO_REQUIRED,
            message: "Markdown full texts come with PaperSearch Pro, which is not installed on this computer; the PDF and supplementary files are not affected. Install it with `paper-search pro install`, or 安装 on the settings window's Markdown page (`paper-search settings markdown`); then 接着下 makes the Markdown left out." };
    }
    const access = pro.access();
    return access.ok ? undefined
        : { code: access.code || "markdown_pro_unavailable", message: access.message || "PaperSearch Pro cannot be used now." };
}
/** Where the backend finds Pro's school sign-in (school/paper_search_school/school_login.py). */
export const SCHOOL_LOGIN_ENV = "PAPER_SEARCH_PRO_SCHOOL_LOGIN";
/** Maintainers testing a school Pro lists as still being tested. */
export const SCHOOL_LOGIN_TRIAL_ENV = "PAPER_SEARCH_SCHOOL_LOGIN_TRIAL";
export const SCHOOL_LOGIN_API = 1;
/**
 * Pro's school sign-in, for the backend this command starts: its package (the general rules, its
 * schools by federation) written into Pro's folder as ``school/`` when it changed, and its entry
 * named in ``env``, once Pro is installed, its access given and its interface this one. Otherwise
 * ``env`` names none and the user signs in as before. The entry's path, or undefined.
 */
export async function prepareProSchoolLogin(env = process.env) {
    delete env[SCHOOL_LOGIN_ENV];
    const pro = await loadMarkdownPro();
    if (!pro || markdownBlocked(pro) || pro.schoolLogin?.apiVersion !== SCHOOL_LOGIN_API)
        return undefined;
    const folder = join(dirname(proEntry(env)), "school");
    const files = pro.schoolLogin.files();
    const there = existsSync(folder) ? readdirSync(folder, { recursive: true, withFileTypes: true })
        .filter((entry) => entry.isFile()).map((entry) => relative(folder, join(entry.parentPath, entry.name)).split("\\").join("/"))
        .filter((path) => !path.includes("__pycache__")) : [];
    const changed = there.length !== Object.keys(files).length || Object.entries(files).some(([path, text]) => !existsSync(join(folder, path)) || readFileSync(join(folder, path), "utf8") !== text);
    if (changed) {
        // Written afresh: a school's file Pro no longer has goes with the old copy.
        rmSync(folder, { recursive: true, force: true });
        for (const [path, text] of Object.entries(files)) {
            mkdirSync(dirname(join(folder, path)), { recursive: true, mode: 0o700 });
            writeFileSync(join(folder, path), text, { mode: 0o600 });
        }
    }
    const entry = join(folder, "school_login", "__init__.py");
    env[SCHOOL_LOGIN_ENV] = entry;
    return entry;
}
//# sourceMappingURL=pro.js.map