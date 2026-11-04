/** These messages are local product text. Backend prose never reaches callers. */
const STAGES = {
    starting: "正在查找可用全文来源。",
    opening_article: "正在打开论文页面。",
    waiting_login: "正在等待机构登录，请在下载浏览器中完成。",
    waiting_verification: "正在等待人工安全验证，请在下载浏览器中完成。",
    checking_access: "正在检查当前页面的全文访问状态。",
    fetching_pdf: "正在获取 PDF。",
    pdf_captured: "已捕获 PDF，正在保存。",
    saved_pending_verification: "PDF 已保存，正在等待产品核验论文身份。",
    supplements_checked: "补充材料检查已完成，正在整理文件结果。",
    route_failed: "当前下载路径未完成，正在尝试其余可用路径。",
    failed: "本次下载未完成，正在整理结果。",
    cancelled: "本次下载已取消。",
    interrupted: "本次下载已中断。",
    unknown: "后端尚未提供可识别的下载阶段。",
};
export function decodeCarsiProgress(value, identifier) {
    const prefix = "carsi.stage:";
    if (!value.message?.startsWith(prefix))
        return undefined;
    const stage = value.message.slice(prefix.length);
    if (!Object.hasOwn(STAGES, stage))
        return undefined;
    return {
        identifier,
        stage: stage,
        message: STAGES[stage],
    };
}
//# sourceMappingURL=CarsiProgress.js.map