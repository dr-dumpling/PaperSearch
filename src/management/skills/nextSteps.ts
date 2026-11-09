// What the AI should do right after the Skill is first installed. The chat that ran the install cannot read
// the new Skill yet, so `skills update` hands these steps over in its output. Nothing else is installed here:
// school subscription downloads are offered, and installed only on the user's yes, once they say 请开始配置
// (agents' own safety reviews refuse an install the user did not agree to). That can be in this same chat,
// so the agent is told to read the setup reference of the Skill it just installed first.

export function firstInstallNextSteps(): string[] {
  return [
    "运行 paper-search doctor --format text，用一句话告诉用户现在能用哪些功能、哪些还缺 key。",
    "告诉用户：需要配置时说“请开始配置”（要不要装学校订阅下载，到时会先问用户）。用户这样说时，先读刚装好的 paper-search Skill 里的 references/setup.md，再照着做。",
  ];
}

/** The same steps as text for stderr: a tool that keeps only some JSON fields (Codex reading it in
 * PowerShell, 2026-11-09) still shows the command's stderr to the AI. */
export function nextStepsNotice(steps: string[]): string {
  return `paper-search：Skill 已装好。接下来请按顺序做：\n${steps.map((step, i) => `${i + 1}. ${step}`).join("\n")}\n`;
}
