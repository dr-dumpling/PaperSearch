import { existsSync, readFileSync } from "fs";
import { join } from "path";
import { describe, expect, it } from "@jest/globals";
import { TOOLS } from "../../src/core/tools.js";

const SKILL_ROOT = join(process.cwd(), "skills", "paper-search");

function readSkillFile(relativePath: string): string {
  return readFileSync(join(SKILL_ROOT, relativePath), "utf8");
}

const REFERENCE_FILES = [
  "references/cli-contract.md",
  "references/management-layer.md",
  "references/capability-routing.md",
  "references/browser-download.md",
  "references/carsi-setup.md",
  "references/troubleshooting.md",
  "references/publisher-support.md",
];

describe("paper-search bundled skill contract", () => {
  it("keeps the routing skill short and backed by focused references", () => {
    const skill = readSkillFile("SKILL.md");

    for (const file of REFERENCE_FILES) {
      expect(existsSync(join(SKILL_ROOT, file))).toBe(true);
      expect(skill).toContain(file);
    }
    expect(skill).toContain("路由 Skill");
    expect(skill).toContain("开放式的文献任务分两步");
    expect(skill).toContain("直接下载请求");
    expect(skill).toContain("paper-search doctor --pretty");
    // Setup lives in its own reference; the main file must always point to it.
    const setup = readSkillFile("references/setup.md");
    expect(skill).toContain("“请开始配置”");
    expect(skill).toMatch(/\| 配置（“请开始配置”）[^\n]*\| `references\/setup\.md` \|/);
    expect(skill).toContain("**先读 `references/setup.md`，按里面固定的流程做**");
    expect(setup).toContain("用户说“请开始配置”");
    expect(setup).toContain("直接运行 `paper-search settings` 打开设置窗口");
    // Setup asks one thing at a time, and first whether to use school subscription downloads; the two routes differ.
    expect(setup).toContain("一次只问一个问题");
    expect(setup).toContain("A. 机构配置");
    expect(setup).toContain("B. 不用机构配置");
    // Agents' skill vetting rejects a Skill that asks for API keys in the chat (Codex skill-vetter, 2026-11-10).
    for (const text of [setup, readSkillFile("references/management-layer.md")]) {
      expect(text).not.toMatch(/发给你|直接发给 Agent|key 是直接发给/);
    }
    expect(setup).toContain("paper-search setup --skip-carsi");
    expect(skill).toContain("Sci-Hub");
  });

  it("documents management commands as explicit agent checks", () => {
    const skill = readSkillFile("SKILL.md");
    const management = readSkillFile("references/management-layer.md");

    expect(skill).toContain("references/management-layer.md");
    expect(management).toContain("## 管理命令");
    expect(management).toMatch(
      /\|\s*命令\s*\|\s*作用\s*\|\s*何时用\s*\|/,
    );
    expect(management).toContain("`paper-search doctor --pretty`");
    expect(management).toContain("完整健康报告");
    expect(management).toContain("`paper-search smoke --mock --pretty`");
    expect(management).toContain("离线检查命令接线");
    expect(management).toContain("`paper-search skills status --pretty`");
    expect(management).toContain("已安装的 Skill 是否与包内 Skill 一致");
    expect(management).toContain("`paper-search tools --pretty`");
  });

  it("documents package update, Skill sync, and capability setup as separate steps", () => {
    const skill = readSkillFile("SKILL.md");
    const management = readSkillFile("references/management-layer.md");

    expect(skill).toContain("先区分包本体更新和 Skill 同步");
    expect(skill).toContain("不要只运行 `skills update`");
    expect(skill).toContain("包更新与功能配置");
    // The commands themselves live in the reference, not on the Skill's main path.
    expect(management).toContain("## 包更新与功能配置");
    expect(management).toContain(
      "不更新 npm 包、GitHub 检出、编译后的命令文件或数据源配置",
    );
    expect(management).toContain("不更新包本体");
    expect(management).toContain("npm install -g papersearch@latest");
    expect(management).toContain("paper-search skills update --pretty");
    expect(management).toContain("paper-search doctor --pretty");
    expect(management).toContain("paper-search setup");
    expect(management).toContain("git pull");
    expect(management).toContain("npm run build");
    expect(management).toContain("npm install -g .");
    expect(management).toContain("能力概况");
  });

  it("installs the command only with the user's yes when only the Skill is installed", () => {
    const skill = readSkillFile("SKILL.md");
    const management = readSkillFile("references/management-layer.md");
    const first = management.slice(management.indexOf("## 只装了 Skill 时"), management.indexOf("## 管理命令"));

    expect(skill).toContain("“只装了 Skill 时”，征得用户同意后安装命令");
    expect(first).toContain("同意后才装");
    expect(first).toContain("npm install -g papersearch@latest");
    // The Skill came first (npx skills add): installing it again would leave two copies of one name.
    expect(first).toContain("不运行 `paper-search skills update`");
    expect(first).toContain("不加 `sudo`");
    // Codex, told nothing, searched ~/.npmrc and shell files for the command and printed a token (2026-11-10).
    expect(first).toContain("不要到别的目录翻找命令，也不要读 `~/.npmrc`");
    expect(first).toContain("接着做用户原来的请求");
    // README's first sentence after installing the Skill is "$paper-search 请开始配置".
    expect(readSkillFile("references/setup.md")).toContain("“只装了 Skill 时”征得同意装好");
  });

  it("keeps what the AI shows and says short", () => {
    // DeepSeek, 2026-11-10: a 500-character description listed in the skill picker, replies of 1,000+
    // characters with tables of paths and versions, and the PowerShell execution policy changed unasked.
    const skill = readSkillFile("SKILL.md");
    const description = skill.split("---")[1].split("description:")[1];
    expect(description.replace(/\s/g, "").length).toBeLessThan(220);
    expect(description).toContain("请开始配置");
    expect(skill).toContain("## 回复用户");
    expect(skill).toContain("安装、配置的汇报不用表格");
    expect(readSkillFile("references/setup.md")).toContain("只推荐两个 key");
    for (const file of ["references/management-layer.md", "references/troubleshooting.md"]) {
      expect(readSkillFile(file)).toContain("不改执行策略");
    }
  });

  it("clearly exposes the five agent-facing literature capabilities", () => {
    const skill = readSkillFile("SKILL.md");
    const routing = readSkillFile("references/capability-routing.md");

    expect(skill).toContain("## 功能地图");
    expect(skill).toMatch(
      /\|\s*用户意图\s*\|\s*能力名\s*\|\s*首选入口\s*\|\s*关键边界\s*\|/,
    );
    expect(skill).toContain("`paper-search search` 集成入口");
    expect(skill).toContain("`metadata_search`");
    expect(skill).toContain("`citation_expansion`");
    expect(skill).toContain("`journal_metrics`");
    expect(skill).toContain("`pdf_discovery`");
    expect(skill).toContain("`body_snippet_search`");
    expect(skill).toContain("Sci-Hub 不属于搜索源");
    expect(routing).toContain("## 功能地图");
    expect(routing).toContain("## 元数据检索");
    expect(routing).toContain("## 施引扩展");
    expect(routing).toContain("## 期刊指标");
    expect(routing).toContain("## PDF 获取");
    expect(routing).toContain("## 正文片段检索");
    expect(routing).toContain(
      "它不调用 `citation_expansion`、`journal_metrics`、`pdf_discovery` 或 `body_snippet_search`",
    );
    expect(routing).toContain("Sci-Hub 兜底默认开启");
    expect(routing).toContain('"useSciHub":false');
    expect(skill).not.toContain("友好入口：");
  });

  it("documents the optional CARSI backend as the current stable entitled-access boundary", () => {
    const bundledText = [
      readSkillFile("SKILL.md"),
      ...REFERENCE_FILES.map((file) => readSkillFile(file)),
    ].join("\n");
    const forbidden = [
      "download_batch_with_fallback",
      "download-sources",
      "downloadStrategy",
      "legacy",
      "institution browser-download",
      "antiBotRecovery",
      "camofox",
      "webvpn.dat",
      "WILEY_TDM_TOKEN",
      "search_wiley",
      "paper-search carsi download",
      "carsiProvider",
      "authorizedPdfProvider",
    ];

    for (const phrase of forbidden) {
      expect(bundledText).not.toContain(phrase);
    }

    expect(bundledText).toContain("机构下载后端（CARSI）是唯一可选的授权下载后端");
    expect(bundledText).toContain("PAPER_SEARCH_CARSI_ENABLED");
    // Signing in first goes through the download's own steps (2026-11-09); the programme manages the browser.
    expect(bundledText).toContain("paper-search carsi login --doi");
    expect(bundledText).toContain("下载浏览器和它的资料目录由程序管理");
    expect(bundledText).toContain("不要翻源码另找登录办法");
    expect(bundledText).toContain("useEntitledAccess");
    expect(bundledText).toContain(
      "primary -> direct_pdf_url -> repositories -> unpaywall -> publisher_api -> scihub -> entitled_access",
    );
    expect(bundledText).toContain("disabled");
    expect(bundledText).toContain("absent");
    expect(bundledText).toContain("incompatible");
    expect(bundledText).toContain("available");
    expect(bundledText).toContain("not_evaluated");
    expect(bundledText).toContain("publisher_api");
    expect(bundledText).toContain("不能当作本机的授权 PDF 后端");
    expect(bundledText).toContain(
      "除机构下载后端外，没有浏览器、WebVPN 或 EZProxy 兜底",
    );
  });

  it("keeps direct run tool names synchronized with the source tool registry", () => {
    const contract = readSkillFile("references/cli-contract.md");
    const section = contract.match(
      /## 可直接调用的工具\n\n[\s\S]*?\n\n## 输出格式/,
    );
    expect(section).not.toBeNull();

    const contractTools = Array.from(
      (section?.[0] || "").matchAll(/^- `([^`]+)`$/gm),
    )
      .map((match) => match[1])
      .sort();
    const sourceTools = TOOLS.map((tool) => tool.name).sort();

    expect(contractTools).toEqual(sourceTools);
  });

  it("lists, per publisher, what the institutional download fetches", () => {
    const skill = readSkillFile("SKILL.md");
    const support = readSkillFile("references/publisher-support.md");

    // Open downloading always works; the institutional download is installed only after the user agrees.
    expect(skill).toContain("## 两种下载方式");
    expect(skill).toContain("## 整体逻辑");
    expect(skill).toContain("装好 `paper-search` 就能用开放下载");
    expect(skill).toContain("paper-search carsi install --yes --skip-school");
    expect(readSkillFile("references/setup.md")).toContain("问一次要不要装");
    expect(skill).not.toContain("不用先问");
    expect(skill).toMatch(/\|\s*\|\s*开放下载\s*\|\s*机构下载（学校订阅下载）\s*\|/);
    // The agent asks once, before downloading, whether supplementary files are wanted.
    expect(skill).toContain("下载前问清要什么");
    for (const choice of ["只要正文", "正文加补充材料", "只要补充材料"]) {
      expect(skill).toContain(choice);
    }
    expect(support).toMatch(
      /\|\s*出版社\s*\|\s*网站\s*\|\s*常见 DOI 前缀\s*\|\s*正文\s*\|\s*补充材料\s*\|\s*\n/,
    );
    for (const code of [
      "supplements_not_supported",
      "institution_federation_unavailable",
      "generic_institution_entry_missing",
      "unsupported_platform",
    ]) {
      expect(support).toContain(code);
    }
  });

  it("documents only accepted compatibility command aliases", () => {
    const contract = readSkillFile("references/cli-contract.md");

    expect(contract).toContain("`paper-search metrics ...` 是 `journal-metrics` 的别名");
    expect(contract).toContain(
      "`paper-search requirements [--pretty]` 是 `diagnostics` 的别名",
    );
    expect(contract).not.toContain("paper-search config setup");
  });
});
