// What the AI should do right after the Skill is first installed. The chat that ran the install cannot read
// the new Skill yet, so `skills update` hands these steps over in its output.
import { hasScreen } from "../carsi/runtime.js";
export function firstInstallNextSteps(platform = process.platform, env = process.env) {
    const school = hasScreen(platform, env)
        ? "接着装上学校订阅下载（CARSI），不用先问：它随 PaperSearch 一起装，用学校账号下载非 OA 文章的全文和补充材料。" +
            "运行 paper-search carsi install --yes --skip-school；没有 Chrome 时先替用户装上（macOS：brew install --cask google-chrome；Windows：winget install -e --id Google.Chrome）。" +
            "装完会弹出设置窗口的 API key 页，告诉用户在窗口里填要用的 key、改下载文件夹，填完点右上角 × 关闭；学校可以现在告诉你，也可以第一次下载时在选校页选。" +
            "用户说不要学校订阅下载时跳过，并运行 paper-search config set PAPER_SEARCH_CARSI_DECLINED true，以后不再提，除非用户自己要求。"
        : "这台机器没有图形界面，装不了学校订阅下载，不要问；用户要下订阅文章时，告诉他可以在校园网里配 Elsevier、Springer 的 API key。";
    return [
        "运行 paper-search doctor --format text，用一句话告诉用户现在能用哪些功能、哪些还缺 key。",
        school,
        "告诉用户：新开一个 AI 对话，Skill 才会生效。",
    ];
}
/** The same steps as text for stderr: a tool that keeps only some JSON fields (Codex reading it in
 * PowerShell, 2026-11-09) still shows the command's stderr to the AI. */
export function nextStepsNotice(steps) {
    return `paper-search：Skill 已装好。接下来请按顺序做：\n${steps.map((step, i) => `${i + 1}. ${step}`).join("\n")}\n`;
}
//# sourceMappingURL=nextSteps.js.map