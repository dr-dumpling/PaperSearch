/**
 * The Markdown (content markdown, or --markdown): the paper's full-text package goes into
 * the paper's own folder (docs/dependencies/publisher-rules-markdown.zh.md), the folder its
 * supplementary files would use; a main text lying in the download folder moves in beside
 * it. Beside the PDF the package is extra to the download: its outcome is an attempt of
 * its own ("markdown") and never changes the paper's result. Asked for without the PDF
 * (content "markdown", or "supplements,markdown"), it is fetched on its own (fulltextAlone);
 * no PDF stands in for it (user, 2026-11-16).
 */
import { copyFileSync, existsSync, mkdirSync, rmSync, writeFileSync } from "node:fs";
import { basename, dirname, join } from "node:path";
import { resolveDownloadPath } from "../../../../config/ConfigService.js";
import { FULLTEXT_FOLDER } from "./types.js";
import { loadMarkdownPro, markdownBlocked, markdownPro } from "./pro.js";
import { createOutputLayout, inPaperDir, isInside, lookupOutputMetadata, moveIntoPaperDir, organizeFiles, removeWorkFolder } from "../../outputLayout.js";
import { SCHOOL_UPDATE_NEEDED, schoolShortReason } from "../../../../infrastructure/school/index.js";
import { pastNetworkLoss } from "../../batch/networkLoss.js";
import { recordMarkdownSaved } from "./stats.js";
function doiOf(result, request) {
    const candidates = [result.publishedDoi, request.doi, request.paperId];
    return (candidates.find((value) => /^\s*(https?:\/\/(dx\.)?doi\.org\/|doi:\s*)?10\.\d{4,9}\/\S+/i.test(value || "")) || "").trim();
}
function summaryOf(outcome) {
    return {
        status: outcome.status,
        ...(outcome.source ? { source: outcome.source } : {}),
        ...(outcome.markdown ? { file: outcome.markdown } : {}),
        ...(outcome.raw ? { original: outcome.raw } : {}),
        ...(outcome.manifest ? { manifest: outcome.manifest } : {}),
        ...(outcome.warnings?.length ? { warnings: outcome.warnings } : {}),
        ...(outcome.figures ? { figures: outcome.figures } : {}),
        ...(outcome.code ? { code: outcome.code } : {}),
        // The checks stay in the run's records (keepUnverifiedPage), not in the result.
        ...(outcome.unverified ? { unverified: (({ checks: _checks, attempt: _attempt, ...site }) => site)(outcome.unverified) } : {}),
        ...(outcome.possiblyMissing ? { possiblyMissing: outcome.possiblyMissing } : {}),
        ...(outcome.missingFigures?.length ? { missingFigures: outcome.missingFigures } : {}),
        ...(outcome.rulesFallback ? { rulesFallback: outcome.rulesFallback } : {}),
        message: outcome.message,
    };
}
/** The paper's own folder, as its supplementary files and full text use it; beside a main text already in one. */
async function paperLayout(request, mainPath, searchers) {
    const savePath = resolveDownloadPath(request.savePath);
    const identity = request.doi || request.paperId;
    const metadata = searchers ? await lookupOutputMetadata(searchers, request.doi ? "crossref" : request.source, identity) : {};
    const layout = createOutputLayout(savePath, identity, { ...metadata, title: request.title || metadata.title }, false, { diagnosticsDir: request.diagnosticsDir });
    return mainPath && isInside(dirname(mainPath), savePath) && dirname(mainPath) !== savePath ? inPaperDir(layout, dirname(mainPath)) : layout;
}
/** The package's summary beside a PDF the user asked for too: only the PDF, not converted. */
function pdfOnly(summary) {
    return { ...summary, status: "unavailable", code: "pdf_only",
        message: `Only the PDF: ${summary.message} The PDF is not converted to Markdown.` };
}
/**
 * The Markdown asked for without the PDF (content "markdown", or "supplements" with the
 * Markdown): its package, and nothing in its place. No source with the whole full text
 * (one missing figures is not kept) leaves the paper without it, saying why, for 接着下
 * to fetch it again (user, 2026-11-16; until then the PDF stood in). ``result``: what was
 * fetched so far (the supplementary files, or nothing). For content "markdown" the result's
 * status is the Markdown's; for supplementary files it stays theirs, the Markdown being in
 * ``markdown``.
 */
export async function fulltextAlone(result, request, searchers, visitPage) {
    const summary = await fulltextForItem(result, { ...request, fulltext: true }, searchers, visitPage);
    if (request.content !== "markdown")
        return result;
    return { ...result, status: summary?.status === "ok" ? "ok" : "error" };
}
/**
 * 接着下 (resume.ts): the Markdown of a paper whose PDF a batch saved before (``mainPath``),
 * beside it; the PDF is not downloaded again. ok when the Markdown, or the files ``result``
 * went for, were saved.
 */
export async function markdownBeside(result, mainPath, request, searchers, visitPage) {
    const withPdf = { ...result, status: "ok", path: result.path || mainPath };
    const summary = await fulltextForItem(withPdf, { ...request, fulltext: true }, searchers, visitPage);
    return { ...withPdf, status: summary?.status === "ok" ? "ok" : result.status };
}
export async function fulltextForItem(result, request, searchers, visitPage) {
    if (!request.fulltext)
        return undefined;
    const startedAt = Date.now();
    // The page the browser saved is read here once, then its files go.
    const page = result.fulltextPage;
    delete result.fulltextPage;
    // The visit that took the PDF read the article page and saw no full text: a visit for the
    // page alone would read it the same way (a minute or two for nothing, 2026-11-15).
    const pageShowedNone = result.fulltextNotShown === true;
    delete result.fulltextNotShown;
    const doi = doiOf(result, request);
    let outcome;
    let visited;
    let layout;
    // The conversion is PaperSearch Pro's: without it, or while it cannot be used, nothing is
    // visited or fetched for the Markdown (pro.ts).
    const pro = doi ? await loadMarkdownPro() : undefined;
    const blocked = doi ? markdownBlocked(pro) : undefined;
    if (!doi) {
        outcome = { status: "unavailable", code: "no_doi", message: "A full text is looked up by DOI; this paper has none." };
    }
    else if (blocked || !pro) {
        outcome = { status: "unavailable", ...(blocked ?? { code: "markdown_pro_required", message: "" }) };
    }
    else {
        try {
            // A main text already in a folder of its own: the package goes beside it.
            const mainPath = result.status === "ok" && result.path && !result.version ? result.path : "";
            layout = await paperLayout(request, mainPath, searchers);
            // Looked up for its folder's name: the paper's journal and title for the lists too, as the
            // PDF's and the files' steps give them (a batch of the Markdown alone showed titles alone,
            // no journal, user 2026-11-17).
            if (!result.journal && layout.metadata.journal)
                result.journal = layout.metadata.journal;
            if (!result.title && layout.metadata.title)
                result.title = layout.metadata.title;
            // The package in a folder of its own inside the paper's: article.md, the original, figures/.
            const packageDir = join(layout.paperDir, FULLTEXT_FOLDER);
            // The article page alone, visited at most once: for a PubMed Central record without its
            // figures (inside fetchFulltext), or when no source had the full text (below).
            let visit;
            let visitDone = false;
            const paperLayoutNow = layout;
            const visitOnce = async () => {
                if (!visitDone && typeof visitPage === "function") {
                    visitDone = true;
                    visit = await visitPage(doi, paperLayoutNow.paperDir, paperLayoutNow.workDiagnosticsDir);
                    if (visit?.trace) {
                        organizeFiles({ trace: visit.trace, status: visit.page ? "ok" : "error" }, paperLayoutNow, paperLayoutNow.paperDir, undefined, request.recordsDir);
                    }
                    if (visit?.page)
                        visited = visit.page;
                }
                return visit?.page;
            };
            // Not opened: a page on a site this batch gave up (no rules name the DOI's prefix).
            const skipSite = pro.hasRulesForDoi(doi) ? undefined : pro.givenUpForDoi(doi);
            const canVisit = !page && !pageShowedNone && !skipSite;
            outcome = await pro.fetchFulltext({ doi, dir: packageDir, ...(page ? { page } : {}),
                ...(request.fulltextPageOnly ? { pageOnly: true } : {}),
                ...(canVisit && visitPage === "later" ? { visit: async () => "later" } : {}),
                ...(canVisit && typeof visitPage === "function" ? { visit: visitOnce } : {}) });
            // A visit that read no page: its reason is the Markdown's, for a record missing figures and
            // for the page alone of a batch through the school too. The lost network was said there as
            // a page not saved, and the batch went on instead of waiting for it (Windows, 2026-11-18).
            if (outcome.status !== "ok" && visitDone && !visited && visit?.code) {
                outcome = { ...outcome, code: visit.code, message: `${outcome.message} The article page was not read: ${visit.message ?? visit.code}` };
            }
            if (outcome.status !== "ok" && !page && visitPage === "later" && canVisit) {
                removeWorkFolder(layout);
                return "later";
            }
            if (outcome.status !== "ok" && !page && pageShowedNone) {
                outcome = { ...outcome, message: `${outcome.message} The article page showed no full text when the PDF was taken.`.trim() };
            }
            else if (outcome.status !== "ok" && !page && !visitDone && typeof visitPage === "function" && canVisit) {
                const visitedPage = await visitOnce();
                if (visitedPage) {
                    const fromPage = await pro.fulltextFromPage(visitedPage, doi, { dir: packageDir });
                    outcome = fromPage.status === "ok" ? fromPage : { ...fromPage, message: `${outcome.message} ${fromPage.message}` };
                }
                else if (visit?.code) {
                    outcome = { ...outcome, code: visit.code, message: `${outcome.message} ${visit.message ?? ""}`.trim() };
                }
                else {
                    outcome = { ...outcome, message: `${outcome.message} A visit for the article page saved none.` };
                }
            }
            if (outcome.status === "ok" && mainPath)
                result.path = moveIntoPaperDir(mainPath, layout);
            // No page read: why the institutional download gave none, named as for a PDF (user, 2026-11-16).
            // A page read without its full text is that reason, also in a batch through the school
            // alone, where the sources say only that no page was saved (page_not_saved: 22 papers of
            // the sweep were said 原因不明 · 文章页没存下来, 2026-11-22).
            if ((outcome.status === "incomplete" || outcome.status === "unavailable") && !page && !visited
                && (pageShowedNone || !institutionalReason(outcome.code))) {
                // The visit that took the PDF through the school saw no full text on the page: not a
                // missing subscription (Volume Index, withdrawal notices, articles whose text is not
                // online yet; 14 of an AR batch were said 学校没有订阅, Windows 2026-11-17).
                const code = pageShowedNone ? "page_no_fulltext" : skipSite ? "page_not_supported"
                    : typeof visitPage !== "function" || visitDone ? "institutional_not_run" : undefined;
                if (skipSite)
                    outcome = { ...pro.givenUpOutcome(skipSite), message: `${outcome.message} ${pro.givenUpOutcome(skipSite).message}`.trim() };
                else if (code)
                    outcome = { ...outcome, code };
            }
            // Only a PDF: it is not turned into Markdown here (user, 2026-11-13); other
            // tools (the literature package's MinerU, docling) convert it.
            // An extension too old to save the page keeps saying so: updating it gives the Markdown.
            if (outcome.status === "unavailable" && mainPath && !institutionalReason(outcome.code)) {
                outcome = { ...outcome, code: "pdf_only", message: pdfOnly(summaryOf(outcome)).message };
            }
        }
        catch (error) {
            outcome = { status: "error", code: "fulltext_failed", message: `Full text failed: ${error instanceof Error ? error.message : String(error)}` };
        }
    }
    // A site not yet supported whose page was tried: the page and what the rules made of it
    // stay in the run's records for a report (user 2026-11-16), also when the rules saw only an
    // abstract or no access: on such a site that is often the rules' failing (an open-access
    // Geosphere page was taken for an abstract, 2026-11-17). A page converted completely by
    // another site's rules too (user, 2026-11-17): the report says the site needs listing only.
    if (outcome.unverified && !outcome.unverified.skipped
        && (page ?? visited) && request.recordsDir && doi) {
        const report = keepUnverifiedPage((page ?? visited), doi, outcome, request.recordsDir);
        if (report)
            outcome = { ...outcome, unverified: { ...outcome.unverified, report } };
    }
    else if (outcome.rulesFallback && (page ?? visited) && request.recordsDir && doi) {
        // A listed site's page other rules converted: the page and which rules did, for its
        // listing to be brought up to date (user, 2026-11-18).
        const report = keepFallbackPage((page ?? visited), doi, outcome, request.recordsDir);
        if (report)
            outcome = { ...outcome, rulesFallback: { ...outcome.rulesFallback, report } };
    }
    else if (!outcome.unverified && outcome.status !== "ok" && outcome.source === "publisher_page"
        && (page ?? visited) && request.recordsDir && doi) {
        // A listed site's page its rules did not convert (taken for an abstract, short of figures
        // or tables): the page alone stays in the records, for the rules to be looked into
        // (2026-11-18, JACS communications with full text were taken for abstracts and their
        // pages were gone). No report: those list the sites not yet supported.
        keepPage((page ?? visited), doi, request.recordsDir);
    }
    for (const saved of [page, visited])
        if (saved)
            removeCapturedPage(saved.file);
    // No folder left behind with nothing in it (a page that gave no package).
    if (layout)
        removeWorkFolder(layout);
    // Counted for the settings window's Pro page.
    if (outcome.status === "ok")
        recordMarkdownSaved(!outcome.possiblyMissing && !outcome.missingFigures?.length);
    // Missing figures is a failure to try again (接着下), as an error is.
    const attempt = {
        stage: "markdown",
        status: outcome.status === "ok" ? "ok" : outcome.status === "error" || outcome.status === "incomplete" ? "error" : "skipped",
        message: outcome.message,
        ...(outcome.code ? { code: outcome.code } : {}),
    };
    result.attempts.push(attempt);
    const summary = summaryOf(outcome);
    result.markdown = summary;
    request.onStage?.({ ...attempt, ...(outcome.markdown ? { path: outcome.markdown } : {}),
        ...(outcome.possiblyMissing ? { possiblyMissing: outcome.possiblyMissing } : {}),
        ...(outcome.missingFigures?.length ? { missingFigures: outcome.missingFigures } : {}),
        ...(outcome.rulesFallback ? { rulesFallback: outcome.rulesFallback } : {}),
        startedAt: new Date(startedAt).toISOString(), durationMs: Date.now() - startedAt });
    return summary;
}
/** A Markdown saved without some figures (each marked in it): a batch tries them once more at its end. */
export function figuresMissing(result) {
    return result?.markdown?.status === "ok" && !!result.markdown.missingFigures?.length && !!result.markdown.file;
}
/**
 * A batch's end (user, 2026-11-23: "批量最后再试一次图片，仍缺的保留 Markdown 并标明缺哪张图"): the
 * figures the paper's saved Markdown lacks, downloaded once more by Pro, each that comes put in
 * its place. The Markdown stays saved either way; its new state is a "markdown" stage of its
 * own (the run's records and the batch's list say what is still missing).
 */
export async function figuresOnceMore(result, request) {
    const markdown = result.markdown;
    const pro = markdownPro();
    if (!markdown || !figuresMissing(result) || !pro?.retryMissingFigures || markdownBlocked(pro))
        return;
    const startedAt = Date.now();
    let outcome;
    try {
        outcome = await pro.retryMissingFigures(markdown.file);
    }
    catch (error) {
        // The package stays as it was, its figures marked; the attempt says why it was not retried.
        outcome = { status: "ok", ...(markdown.figures ? { figures: markdown.figures } : {}), missingFigures: markdown.missingFigures,
            message: `Figures not tried again: ${error instanceof Error ? error.message : String(error)}` };
    }
    const { missingFigures: _before, ...kept } = markdown;
    result.markdown = { ...kept, ...(outcome.figures ? { figures: outcome.figures } : {}),
        ...(outcome.missingFigures?.length ? { missingFigures: outcome.missingFigures } : {}), message: `${markdown.message} ${outcome.message}` };
    const attempt = { stage: "markdown", status: "ok", message: outcome.message };
    result.attempts.push(attempt);
    request.onStage?.({ ...attempt, path: markdown.file,
        ...(markdown.possiblyMissing ? { possiblyMissing: markdown.possiblyMissing } : {}),
        ...(outcome.missingFigures?.length ? { missingFigures: outcome.missingFigures } : {}),
        startedAt: new Date(startedAt).toISOString(), durationMs: Date.now() - startedAt });
}
/**
 * A code saying why the institutional download gave no page (or no whole package), as the
 * finished card names it: the visit's own failure, or one set above. Kept as it is.
 */
function institutionalReason(code) {
    return !!code && (code === SCHOOL_UPDATE_NEEDED || !!schoolShortReason(code, "")
        || ["page_not_entitled", "page_no_fulltext", "page_not_supported", "institutional_not_run"].includes(code));
}
/**
 * The page of a site not yet supported, beside what each rule made of it and the page's own
 * facts: "<DOI>_markdown-page.html", "<DOI>_markdown-report.json" and the Markdown the rules
 * made, "<DOI>_markdown-attempt.md" (the saved article.md, else the closest rules'), in the
 * run's records. The report's path; undefined when it could not be written (the paper's
 * result stands).
 */
function keepUnverifiedPage(page, doi, outcome, recordsDir) {
    const name = doi.replace(/[^A-Za-z0-9._-]+/g, "_");
    try {
        const html = keepPage(page, doi, recordsDir);
        if (!html)
            return undefined;
        // The Markdown beside it, as it came out.
        const { attempt, ...site } = outcome.unverified ?? { host: "" };
        let attemptFile = join(recordsDir, `${name}_markdown-attempt.md`);
        if (attempt)
            writeFileSync(attemptFile, attempt);
        else if (outcome.markdown && existsSync(outcome.markdown))
            copyFileSync(outcome.markdown, attemptFile);
        else
            attemptFile = undefined;
        const report = join(recordsDir, `${name}_markdown-report.json`);
        const rules = markdownPro()?.rulesName(site.template);
        writeFileSync(report, JSON.stringify({ schemaVersion: 1, doi, url: page.url, page: html, ...(attemptFile ? { attempt: attemptFile } : {}),
            images: page.images.length, ...site, ...(rules ? { rules } : {}), status: outcome.status, code: outcome.code, message: outcome.message }, null, 2));
        return report;
    }
    catch {
        return undefined;
    }
}
/**
 * A listed site's page converted by other rules than its listed ones: "<DOI>_markdown-page.html"
 * and "<DOI>_markdown-fallback.json" (the site, its listed rules and what they made of the page,
 * the rules used and why, the outcome) in the run's records. The latter's path.
 */
function keepFallbackPage(page, doi, outcome, recordsDir) {
    const html = keepPage(page, doi, recordsDir);
    if (!html || !outcome.rulesFallback)
        return undefined;
    try {
        const report = join(recordsDir, `${doi.replace(/[^A-Za-z0-9._-]+/g, "_")}_markdown-fallback.json`);
        const pro = markdownPro();
        const { report: _report, ...fallback } = outcome.rulesFallback;
        writeFileSync(report, JSON.stringify({ schemaVersion: 1, doi, url: page.url, page: html, ...fallback,
            listedRules: pro?.rulesName(fallback.listed) ?? fallback.listed, usedRules: pro?.rulesName(fallback.used) ?? fallback.used,
            status: outcome.status, code: outcome.code, message: outcome.message }, null, 2));
        return report;
    }
    catch {
        return undefined;
    }
}
/** The saved page in the run's records, "<DOI>_markdown-page.html"; undefined when it could not be copied. */
function keepPage(page, doi, recordsDir) {
    try {
        mkdirSync(recordsDir, { recursive: true });
        const html = join(recordsDir, `${doi.replace(/[^A-Za-z0-9._-]+/g, "_")}_markdown-page.html`);
        copyFileSync(page.file, html);
        return html;
    }
    catch {
        return undefined;
    }
}
/** The backend's folder for a saved page ("<DOI>_fulltext_page"), once packaged or not wanted. */
function removeCapturedPage(file) {
    const folder = dirname(file);
    if (!basename(folder).endsWith("_fulltext_page"))
        return;
    try {
        rmSync(folder, { recursive: true, force: true });
    }
    catch {
        // Left for the user; the package (or its absence) is reported either way.
    }
}
/**
 * fulltextForItem, asked again after a network loss: the Markdown's attempt the lost network
 * failed is taken back and the Markdown fetched anew once it is back.
 */
export async function markdownPastNetworkLoss(result, request, searchers, visit, watch) {
    const before = result.attempts.length;
    await pastNetworkLoss(async () => {
        result.attempts.length = before;
        delete result.markdown;
        const summary = await fulltextForItem(result, request, searchers, visit);
        return { status: summary?.status === "ok" ? "ok" : "error", attempts: result.attempts.slice(before) };
    }, watch);
}
//# sourceMappingURL=step.js.map