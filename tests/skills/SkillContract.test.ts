import { existsSync, readFileSync } from "fs";
import { join } from "path";
import { describe, expect, it } from "@jest/globals";
import { proFeatures } from "../../src/config/edition.js";
import { toolList } from "../../src/core/tools.js";
import { skillVersion } from "../../src/management/skills/index.js";

const SKILL_ROOT = join(process.cwd(), "skills", "paper-search");

function readSkillFile(relativePath: string): string {
  return readFileSync(join(SKILL_ROOT, relativePath), "utf8");
}

const REFERENCE_FILES = [
  "references/cli-contract.md",
  "references/management-layer.md",
  "references/capability-routing.md",
  "references/browser-download.md",
  "references/school-setup.md",
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
    expect(skill).toContain("This is a routing Skill");
    expect(skill).toContain("Open-ended literature tasks take two steps");
    expect(skill).toContain("Direct download requests");
    expect(skill).toContain("paper-search doctor --pretty");
    // Setup lives in its own reference; the main file must always point to it.
    const setup = readSkillFile("references/setup.md");
    expect(skill).toContain('"请开始配置"');
    expect(skill).toMatch(/\| Setup \("start setup", "请开始配置"\)[^\n]*\| `references\/setup\.md` \|/);
    expect(skill).toContain("**read `references/setup.md` first and follow its fixed flow**");
    expect(setup).toContain('When the user says "start setup" (or "请开始配置"');
    expect(setup).toContain("run `paper-search settings` directly to open the settings window");
    // Setup asks one thing at a time, and first whether to use school subscription downloads; the two routes differ.
    expect(setup).toContain("Ask one question at a time");
    expect(setup).toContain("A. School setup");
    expect(setup).toContain("B. No school setup");
    // Agents' skill vetting rejects a Skill that asks for API keys in the chat (Codex skill-vetter, 2026-11-10).
    for (const text of [setup, readSkillFile("references/management-layer.md")]) {
      expect(text).not.toMatch(/发给你|直接发给 Agent|key 是直接发给|send (?:it|them|the keys?|your keys?) (?:directly )?to (?:you|me|the agent|the AI)|paste (?:the|your) keys?/i);
    }
    expect(setup).toContain("paper-search setup --skip-school");
    expect(skill).toContain("Sci-Hub");
  });

  it("documents management commands as explicit agent checks", () => {
    const skill = readSkillFile("SKILL.md");
    const management = readSkillFile("references/management-layer.md");

    expect(skill).toContain("references/management-layer.md");
    expect(management).toContain("## Management commands");
    expect(management).toMatch(
      /\|\s*Command\s*\|\s*What it does\s*\|\s*When to use\s*\|/,
    );
    expect(management).toContain("`paper-search doctor --pretty`");
    expect(management).toContain("Full health report");
    expect(management).toContain("`paper-search smoke --mock --pretty`");
    expect(management).toContain("Offline check of the command wiring");
    expect(management).toContain("`paper-search skills status --pretty`");
    expect(management).toContain("whether the installed Skill matches the bundled Skill");
    expect(management).toContain("`paper-search tools --pretty`");
  });

  it("documents package update, Skill sync, and capability setup as separate steps", () => {
    const skill = readSkillFile("SKILL.md");
    const management = readSkillFile("references/management-layer.md");

    expect(skill).toContain("first tell apart updating the package itself and syncing the Skill");
    expect(skill).toContain("do not just run `skills update`");
    expect(skill).toContain("Package update and capability setup");
    // The commands themselves live in the reference, not on the Skill's main path.
    expect(management).toContain("## Package update and capability setup");
    expect(management).toContain(
      "it does not update the npm package, a GitHub checkout, compiled command files or data source configuration",
    );
    expect(management).toContain("it does not update the package itself");
    expect(management).toContain("npm install -g papersearch@latest");
    expect(management).toContain("paper-search skills update --pretty");
    expect(management).toContain("paper-search doctor --pretty");
    expect(management).toContain("paper-search setup");
    expect(management).toContain("git pull");
    expect(management).toContain("npm run build");
    expect(management).toContain("npm install -g .");
    expect(management).toContain("capability summary");
  });

  it("installs the command only with the user's yes when only the Skill is installed", () => {
    const skill = readSkillFile("SKILL.md");
    const management = readSkillFile("references/management-layer.md");
    const first = management.slice(management.indexOf("## When only the Skill is installed"), management.indexOf("## Management commands"));

    expect(skill).toContain('"When only the Skill is installed" in `references/management-layer.md`, and install the command only after the user agrees');
    expect(first).toContain("install only after they agree");
    expect(first).toContain("npm install -g papersearch@latest");
    // The Skill came first (npx skills add): installing it again would leave two copies of one name.
    expect(first).toContain("Do not run `paper-search skills update`");
    expect(first).toContain("do not add `sudo`");
    // Codex, told nothing, searched ~/.npmrc and shell files for the command and printed a token (2026-11-10).
    expect(first).toContain("Do not search other directories for the command, and do not read `~/.npmrc`");
    expect(first).toContain("carry on with the user's original request");
    // README's first sentence after installing the Skill is "/paper-search 请开始配置".
    expect(readSkillFile("references/setup.md")).toContain('install it with the user\'s consent as "When only the Skill is installed"');
  });

  it("names the PaperSearch version it goes with, the package's own", () => {
    // An older command no longer puts its Skill back over a newer one (user, 2026-11-11).
    const pkg = JSON.parse(readFileSync(join(process.cwd(), "package.json"), "utf8")) as { version: string };
    expect(skillVersion(join(process.cwd(), "skills", "paper-search"))).toBe(pkg.version);
    expect(readSkillFile("SKILL.md")).toContain("When `paper-search --version` is older than the version in `metadata.version` at the top of this Skill");
  });

  it("keeps what the AI shows and says short", () => {
    // DeepSeek, 2026-11-10: a 500-character description listed in the skill picker, replies of 1,000+
    // characters with tables of paths and versions, and the PowerShell execution policy changed unasked.
    const skill = readSkillFile("SKILL.md");
    const description = skill.split("---")[1].split("description:")[1].split("metadata:")[0];
    // In English since 2026-11-24 (the Chinese one stayed under 220): short, with the phrases users type in Chinese too.
    expect(description.replace(/\s/g, "").length).toBeLessThan(240);
    expect(description).toContain("请开始配置");
    expect(description).toContain('"start setup"');
    expect(skill).toContain("## Reply to the user");
    // Written in English and read in every language: replies, and the program's Chinese output, in the user's language.
    expect(skill).toContain("Reply in the language the user writes in. This Skill is written in English");
    expect(skill).toContain("The program's own messages and output may be in Chinese: say them in the user's language");
    expect(skill).toContain("no tables when reporting installation or setup");
    expect(readSkillFile("references/setup.md")).toContain("Recommend only two keys");
    for (const file of ["references/management-layer.md", "references/troubleshooting.md"]) {
      expect(readSkillFile(file)).toContain("do not change the execution policy");
    }
  });

  it("clearly exposes the five agent-facing literature capabilities", () => {
    const skill = readSkillFile("SKILL.md");
    const routing = readSkillFile("references/capability-routing.md");

    expect(skill).toContain("## Capability map");
    expect(skill).toMatch(
      /\|\s*User intent\s*\|\s*Capability\s*\|\s*Preferred entry\s*\|\s*Key boundary\s*\|/,
    );
    expect(skill).toContain("`paper-search search` integrated entry");
    expect(skill).toContain("`metadata_search`");
    expect(skill).toContain("`citation_expansion`");
    expect(skill).toContain("`journal_metrics`");
    expect(skill).toContain("`pdf_discovery`");
    expect(skill).toContain("`body_snippet_search`");
    expect(skill).toContain("Sci-Hub is not a search source");
    expect(routing).toContain("## Capability map");
    expect(routing).toContain("## Metadata search");
    expect(routing).toContain("## Citation expansion");
    expect(routing).toContain("## Journal metrics");
    expect(routing).toContain("## PDF retrieval");
    expect(routing).toContain("## Body snippet search");
    expect(routing).toContain(
      "It does not call `citation_expansion`, `journal_metrics`, `pdf_discovery` or `body_snippet_search`",
    );
    expect(routing).toContain("The Sci-Hub fallback is on by default");
    expect(routing).toContain('"useSciHub":false');
    expect(skill).not.toMatch(/友好入口：|friendly entry/i);
  });

  it("documents the optional school backend as the current stable entitled-access boundary", () => {
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
      "paper-search school download",
      "schoolProvider",
      "authorizedPdfProvider",
    ];

    for (const phrase of forbidden) {
      expect(bundledText).not.toContain(phrase);
    }

    expect(bundledText).toContain("The school download backend (school subscription downloads) is the only optional authorized download backend");
    expect(bundledText).toContain("PAPER_SEARCH_SCHOOL_ENABLED");
    // Signing in first goes through the download's own steps (2026-11-09); the programme manages the browser.
    expect(bundledText).toContain("paper-search school login --doi");
    expect(bundledText).toContain("The program manages the download browser and its profile directory");
    expect(bundledText).toContain("do not dig through the source code for another way to sign in");
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
    expect(bundledText).toContain("cannot serve as a local authorized PDF backend");
    expect(bundledText).toContain(
      "Apart from the school download backend, there is no browser, WebVPN or EZProxy fallback",
    );
  });

  it("keeps direct run tool names synchronized with the source tool registry", () => {
    const contract = readSkillFile("references/cli-contract.md");
    const section = contract.match(
      /## Tools for direct calls\n\n[\s\S]*?\n\n## Output formats/,
    );
    expect(section).not.toBeNull();

    const contractTools = Array.from(
      (section?.[0] || "").matchAll(/^- `([^`]+)`$/gm),
    )
      .map((match) => match[1])
      .sort();
    const sourceTools = toolList().map((tool) => tool.name).sort();

    expect(contractTools).toEqual(sourceTools);
  });

  it("lists, per publisher, what the institutional download fetches", () => {
    const skill = readSkillFile("SKILL.md");
    const support = readSkillFile("references/publisher-support.md");

    // Open downloading always works; the institutional download is installed only after the user agrees.
    expect(skill).toContain("## Two ways to download");
    expect(skill).toContain("## Overall flow");
    expect(skill).toContain("Open download works as soon as `paper-search` is installed");
    expect(skill).toContain("paper-search school install --yes --skip-school");
    expect(readSkillFile("references/setup.md")).toContain("ask once whether to install it");
    expect(skill).not.toMatch(/不用先问|without asking|no need to ask/i);
    expect(skill).toMatch(/\|\s*\|\s*Open download\s*\|\s*School download \(school subscription downloads\)\s*\|/);
    // The agent asks once, before downloading, which kinds are wanted: with PaperSearch Pro's features
    // (package.json's paperSearch.proFeatures) the Markdown too; the public export takes its words out
    // by their marks (maintainer/release-public.py), and then none is left.
    const PRO_FEATURES = proFeatures();
    expect(skill).toContain("Ask what is wanted before downloading");
    for (const choice of ["`pdf`: the full-text PDF", "`supplements`: supplementary files", ...(PRO_FEATURES ? ["`markdown`: the paper's Markdown", "in any combination"] : [])]) {
      expect(skill).toContain(choice);
    }
    expect(support).toMatch(PRO_FEATURES
      ? /\|\s*Publisher\s*\|\s*Site\s*\|\s*Common DOI prefixes\s*\|\s*Full text\s*\|\s*Supplementary files\s*\|\s*Markdown <!-- pro-column -->\s*\|\s*\n/
      : /\|\s*Publisher\s*\|\s*Site\s*\|\s*Common DOI prefixes\s*\|\s*Full text\s*\|\s*Supplementary files\s*\|\s*\n/);
    if (!PRO_FEATURES) {
      for (const file of ["SKILL.md", ...REFERENCE_FILES]) expect(readSkillFile(file)).not.toMatch(/markdown|PaperSearch Pro\b|<!-- \/?(pro|public)/i);
    }
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

    expect(contract).toContain("`paper-search metrics ...` is an alias of `journal-metrics`");
    expect(contract).toContain(
      "`paper-search requirements [--pretty]` is an alias of `diagnostics`",
    );
    expect(contract).not.toContain("paper-search config setup");
  });
});
