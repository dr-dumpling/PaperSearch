/**
 * Markdown 没生成的原因：批量结束时窗口、命令行最后一行和清单上“Markdown 未生成”的说法，
 * 以及未登记规则的网站缺了什么。
 */
import { classifyFailureCode } from "../../../../infrastructure/runlog/failureClass.js";
import { schoolShortReason } from "../../../../infrastructure/school/index.js";
/**
 * Why a paper has no Markdown, in a few words and a class, named as a PDF's or the files'
 * failure is (user, 2026-11-16): a full text missing figures goes to the institutional
 * download, and its reason is the institutional download's (the site blocked the network,
 * the login timed out, it never ran), or that the page's figures did not download. A site
 * without page rules is PaperSearch's to cover (待适配); a page that shows only the abstract and
 * an article whose page has no full text are the site's (外部原因, user 2026-11-25: they were
 * 暂不支持, as if PaperSearch could not convert them); an older extension is the user's to update.
 */
export function markdownMissing(markdown) {
    const code = markdown.code ?? "";
    if (code === "school_update_needed")
        return { cls: "user_side", reason: "扩展需要更新" };
    // PaperSearch Pro (pro.ts): not installed, or not usable now (it says why in the message).
    if (code === "markdown_pro_required")
        return { cls: classifyFailureCode(code), reason: "需要 Pro" };
    if (code.startsWith("markdown_pro_"))
        return { cls: classifyFailureCode(code), reason: "Pro 暂不可用" };
    const school = schoolShortReason(code, "");
    if (school)
        return { cls: classifyFailureCode(code), reason: school };
    if (code === "institutional_not_run")
        return { cls: classifyFailureCode(code), reason: "没进行学校订阅下载" };
    // The page, opened through the school's login, showed no access: as a PDF the school has no subscription to.
    if (code === "page_not_entitled")
        return { cls: classifyFailureCode("entitlement_missing"), reason: schoolShortReason("entitlement_missing") };
    // The PDF came through the school; the page has no full text of it (not yet online, or none at all).
    if (code === "page_no_fulltext")
        return { cls: "external", reason: "文章页没有正文" };
    if (code === "figures_missing")
        return { cls: classifyFailureCode(code), reason: "图片没下载成功" };
    if (code === "tables_missing")
        return { cls: classifyFailureCode(code), reason: "表格没取到" };
    if (code === "page_not_supported")
        return { cls: "unsupported", reason: "网站暂不支持转换" };
    // A site not yet supported whose page did not convert completely (user, 2026-11-16).
    if (code === "unverified_incomplete")
        return { cls: "unsupported", reason: "内容不完整" };
    if (code === "pmc_failed")
        return { cls: classifyFailureCode(code), reason: "PMC 没响应" };
    if (markdown.status === "abstract_only" || code === "abstract_only")
        return { cls: "external", reason: "网页只有摘要" };
    if (code === "no_doi")
        return { cls: "unsupported", reason: "没有有效 DOI" };
    if (markdown.status === "error")
        return { cls: "unexplained", reason: "转换出错" };
    return { cls: "unsupported", reason: "没有可转换的全文" };
}
/**
 * Where a page from a site not yet supported fell short: "ard.eular.org · 不完整：参考文献少 1 条，
 * 少 1 张图", or that no rules read it, or that the batch gave the site up; undefined for any
 * other Markdown result.
 */
export function unverifiedNote(markdown) {
    const site = markdown.unverified;
    if (!site)
        return undefined;
    if (markdown.code === "page_not_supported") {
        return `${site.host} · ${site.skipped ? "本批前 3 篇都没转换完整，未再尝试" : "没有规则能读出正文"}`;
    }
    // Only an abstract or no access read: the site's (Geosphere gives the abstract and the PDF
    // alone, 2026-11-17), or rules not yet right for it.
    if (markdown.code === "abstract_only")
        return `${site.host} · 只读到摘要`;
    if (markdown.code === "page_not_entitled")
        return `${site.host} · 网页显示没有权限`;
    if (markdown.code !== "unverified_incomplete")
        return undefined;
    const parts = lackParts(site.shortfall ?? {});
    return `${site.host} · 不完整：${parts.length ? parts.join("，") : "核对没通过"}`;
}
/** "参考文献少 1 条", "少 2 张图", "表格没取到", "正文缺约 15%", in that order. */
function lackParts(lack) {
    return [
        lack.references ? `参考文献少 ${lack.references} 条` : "",
        lack.figures ? `少 ${lack.figures} 张图` : "",
        lack.tables ? "表格没取到" : "",
        lack.text ? `正文缺约 ${lack.text}%` : "",
    ].filter(Boolean);
}
/**
 * A Markdown saved from a registered site's page whose checks found something short (user,
 * 2026-11-17): the group it is listed in by the first thing short (参考文献可能不全) and the
 * note on all of it (可能缺：参考文献少 2 条，正文缺约 12%); undefined when nothing was. One saved
 * without figures that did not download (user, 2026-11-23) is listed by them first: 图片没下载成功,
 * its note naming them (图片没下载成功：Figure 3).
 */
export function markdownDoubt(markdown) {
    if (markdown?.status !== "ok")
        return undefined;
    const figures = markdown.missingFigures ?? [];
    const lack = markdown.possiblyMissing;
    const parts = lack ? lackParts(lack) : [];
    // Up to three named; more, counted (少 N 张图: a phrase the window's tables know).
    const notes = [
        figures.length ? `图片没下载成功：${figures.length > 3 ? `少 ${figures.length} 张图` : figures.join("，")}` : "",
        parts.length ? `可能缺：${parts.join("，")}` : "",
    ].filter(Boolean);
    if (!notes.length)
        return undefined;
    const reason = figures.length ? "图片没下载成功" : lack.references ? "参考文献可能不全" : lack.figures ? "图片可能不全"
        : lack.tables ? "可能缺表" : "正文可能不全";
    return { reason, note: notes.join(" · ") };
}
//# sourceMappingURL=shortfall.js.map