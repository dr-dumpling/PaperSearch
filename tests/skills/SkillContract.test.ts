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
    expect(management).toContain(
      "paper-search skills update --targets agents --pretty",
    );
    expect(management).toContain("paper-search doctor --pretty");
    expect(management).toContain("paper-search setup");
    expect(management).toContain("git pull");
    expect(management).toContain("npm run build");
    expect(management).toContain("npm install -g .");
    expect(management).toContain("能力概况");
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
      "paper-search carsi login",
      "paper-search carsi download",
      "carsiProvider",
      "authorizedPdfProvider",
    ];

    for (const phrase of forbidden) {
      expect(bundledText).not.toContain(phrase);
    }

    expect(bundledText).toContain("机构下载后端（CARSI）是唯一可选的授权下载后端");
    expect(bundledText).toContain("PAPER_SEARCH_CARSI_ENABLED");
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

    // Open downloading is the default; the institutional download is an optional extension.
    expect(skill).toContain("## 两种下载方式");
    expect(skill).toContain("## 整体逻辑");
    expect(skill).toContain("本 Skill 默认是开放版本");
    expect(skill).toMatch(/\|\s*\|\s*开放下载（默认）\s*\|\s*机构下载（可选扩展）\s*\|/);
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
