/**
 * Markdown 没生成的原因：批量结束时窗口、命令行最后一行和清单上“Markdown 未生成”的说法，
 * 以及未登记规则的网站缺了什么。
 */
import { type FailureClass } from "../../../../infrastructure/runlog/failureClass.js";
import type { DownloadBatchItemResult } from "../../batch/batch.js";
/**
 * Why a paper has no Markdown, in a few words and a class, named as a PDF's or the files'
 * failure is (user, 2026-11-16): a full text missing figures goes to the institutional
 * download, and its reason is the institutional download's (the site blocked the network,
 * the login timed out, it never ran), or that the page's figures did not download. A site
 * without page rules is PaperSearch's to cover (待适配); a page that shows only the abstract and
 * an article whose page has no full text are the site's (外部原因, user 2026-11-25: they were
 * 暂不支持, as if PaperSearch could not convert them); an older extension is the user's to update.
 */
export declare function markdownMissing(markdown: NonNullable<DownloadBatchItemResult["markdown"]>): {
    cls: FailureClass;
    reason: string;
};
/**
 * Where a page from a site not yet supported fell short: "ard.eular.org · 不完整：参考文献少 1 条，
 * 少 1 张图", or that no rules read it, or that the batch gave the site up; undefined for any
 * other Markdown result.
 */
export declare function unverifiedNote(markdown: NonNullable<DownloadBatchItemResult["markdown"]>): string | undefined;
/**
 * A Markdown saved from a registered site's page whose checks found something short (user,
 * 2026-11-17): the group it is listed in by the first thing short (参考文献可能不全) and the
 * note on all of it (可能缺：参考文献少 2 条，正文缺约 12%); undefined when nothing was. One saved
 * without figures that did not download (user, 2026-11-23) is listed by them first: 图片没下载成功,
 * its note naming them (图片没下载成功：Figure 3).
 */
export declare function markdownDoubt(markdown: Pick<NonNullable<DownloadBatchItemResult["markdown"]>, "status" | "possiblyMissing" | "missingFigures"> | undefined): {
    reason: string;
    note: string;
} | undefined;
//# sourceMappingURL=shortfall.d.ts.map