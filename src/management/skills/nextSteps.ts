// What the AI should do right after the Skill is first installed. The chat that ran the install cannot read
// the new Skill yet, so `skills update` hands these steps over in its output.

import { hasScreen } from "../carsi/runtime.js";

export function firstInstallNextSteps(
  platform: NodeJS.Platform = process.platform,
  env: NodeJS.ProcessEnv = process.env,
): string[] {
  const school = hasScreen(platform, env)
    ? "问用户要不要装学校订阅下载（CARSI）：装了就能用学校账号下载非 OA 文章的全文和补充材料，需要 Google Chrome，下载约 0.5 GB。" +
      "用户同意后运行 paper-search carsi install；没有 Chrome 时先替用户装上（macOS：brew install --cask google-chrome；Windows：winget install -e --id Google.Chrome）。" +
      "用户说不装时运行 paper-search config set PAPER_SEARCH_CARSI_DECLINED true，以后不再主动提，除非用户自己要求。"
    : "这台机器没有图形界面，装不了学校订阅下载，不要问；用户要下订阅文章时，告诉他可以在校园网里配 Elsevier、Springer 的 API key。";
  return [
    "运行 paper-search doctor --format text，用一句话告诉用户现在能用哪些功能、哪些还缺 key。",
    school,
    "告诉用户：新开一个 AI 对话，Skill 才会生效。",
  ];
}
