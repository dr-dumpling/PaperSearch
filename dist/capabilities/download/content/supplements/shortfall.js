/**
 * 补充材料缺了哪些、为什么：批量结束时窗口和清单上“补充材料没下全”的原因。
 */
import { classifyFailureCode } from "../../../../infrastructure/runlog/failureClass.js";
import { schoolShortReason } from "../../../../infrastructure/school/index.js";
/** Supplement outcomes that are no shortfall: the user or the batch ended them. */
const NOT_A_SHORTFALL = new Set(["batch_stopped", "user_skipped", "cancelled"]);
/**
 * The reason a paper whose main text was saved still lacks supplementary files:
 * its first file not saved, a real failure before "no rule for this site".
 * A paper without its main text is told by its main text's reason instead.
 */
export function supplementShortfall(item) {
    if (item.status !== "ok")
        return undefined;
    const missed = (item.supplements ?? []).filter((file) => file.status !== "saved" && file.reason && !NOT_A_SHORTFALL.has(file.reason));
    return (missed.find((file) => file.reason !== "supplements_not_supported") ?? missed[0])?.reason;
}
/** Supplementary files a saved paper is missing (content "both"): the class and the reason in a few words. */
export function supplementsMissing(item, content) {
    const shortfall = content === "both" ? supplementShortfall(item) : undefined;
    return shortfall ? { cls: classifyFailureCode(shortfall), reason: schoolShortReason(shortfall, "附录没下载成功") } : undefined;
}
//# sourceMappingURL=shortfall.js.map