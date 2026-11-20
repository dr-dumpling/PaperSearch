/**
 * 只为 Markdown 打开文章页：PDF 已从开放来源取得、又要 Markdown 时，经学校订阅下载后端打开文章页、
 * 存下网页（不再下 PDF），交给 step.ts 转换。
 */
import { SCHOOL_UPDATE_NEEDED } from "../../../../infrastructure/school/index.js";
// The backend's reason a page it read was not saved, in the normalized message (SchoolResultNormalizer).
const NOT_SAVED = /did not save its page \(([a-z_]{1,40})\)/;
/**
 * --fulltext for an article whose PDF came from an open stage: a visit for its full-text
 * page alone (no PDF), on a site with page rules (step.ts). Undefined without a
 * backend, or with entitled access turned off.
 */
export function fulltextPageVisit(backend, request) {
    if (!backend || request.useEntitledAccess === false)
        return undefined;
    return async (doi, outputDir, diagnosticsDir) => {
        const outcome = await backend.downloadLegalDoi({
            identifier: doi,
            outputDir,
            diagnosticsDir,
            fulltext: "only",
            // The progress window shows the paper by its title, as for a PDF (it showed the DOI, 2026-11-16).
            ...(request.title ? { title: request.title } : {}),
            ...(request.batch ? { batch: request.batch } : {}),
            ...(request.shortUserWait ? { userWait: "short" } : {}),
            ...(request.school ? { school: request.school } : {}),
        });
        if (outcome.kind === "backend_unavailable")
            return undefined;
        // Why no page, when the backend says: an extension too old to save one, or the visit's
        // own reason (the site blocked the network, the login timed out, the hourly limit),
        // shown as the Markdown's (user, 2026-11-16).
        const notSaved = outcome.kind === "attempt_error" && outcome.code === "page_not_saved"
            ? NOT_SAVED.exec(outcome.message)?.[1] : undefined;
        const why = !outcome.fulltextPage && outcome.kind === "attempt_error" && outcome.code !== "fulltext_page_only"
            ? { code: outcome.code,
                message: outcome.code === SCHOOL_UPDATE_NEEDED ? outcome.message
                    // Read but not saved: the backend's own reason (page_not_stable, time_limit, browser…),
                    // not page_not_saved alone (Frontiers, 2026-11-18).
                    : notSaved ? `The article page was read but not saved (${notSaved}).`
                        : `The article page was not read (${outcome.code}).`,
                ...(outcome.retryAfterSec ? { retryAfterSec: outcome.retryAfterSec } : {}),
                ...(outcome.hourlyPublisher ? { hourlyPublisher: outcome.hourlyPublisher } : {}) }
            : {};
        return {
            ...(outcome.fulltextPage ? { page: outcome.fulltextPage } : {}),
            ...(outcome.trace ? { trace: { ...outcome.trace } } : {}),
            ...why,
        };
    };
}
//# sourceMappingURL=pageVisit.js.map