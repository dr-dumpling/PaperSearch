import type { CarsiProgress } from "./types.js";
/** These messages are local product text. Backend prose never reaches callers. */
declare const STAGES: {
    readonly starting: "正在查找可用全文来源。";
    readonly opening_article: "正在打开论文页面。";
    readonly waiting_login: "正在等待机构登录，请在下载浏览器中完成。";
    readonly waiting_verification: "正在等待人工安全验证，请在下载浏览器中完成。";
    readonly checking_access: "正在检查当前页面的全文访问状态。";
    readonly fetching_pdf: "正在获取 PDF。";
    readonly pdf_captured: "已捕获 PDF，正在保存。";
    readonly saved_pending_verification: "PDF 已保存，正在等待产品核验论文身份。";
    readonly supplements_checked: "补充材料检查已完成，正在整理文件结果。";
    readonly route_failed: "当前下载路径未完成，正在尝试其余可用路径。";
    readonly failed: "本次下载未完成，正在整理结果。";
    readonly cancelled: "本次下载已取消。";
    readonly interrupted: "本次下载已中断。";
    readonly unknown: "后端尚未提供可识别的下载阶段。";
};
export type CarsiProgressStage = keyof typeof STAGES;
export declare function decodeCarsiProgress(value: {
    message?: string;
}, identifier: string): CarsiProgress | undefined;
export {};
//# sourceMappingURL=CarsiProgress.d.ts.map