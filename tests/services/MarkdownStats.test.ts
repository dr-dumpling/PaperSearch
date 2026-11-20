import { mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { afterEach, describe, expect, it } from "@jest/globals";
import { markdownStatsFile, readMarkdownStats, recordMarkdownSaved } from "../../src/capabilities/download/content/markdown/stats.js";
import { installPro, newerVersion } from "../../src/management/pro/install.js";
import { checkPro } from "../../src/management/pro/install.js";
import { createHash } from "node:crypto";

// The settings window's PaperSearch Pro page (user, 2026-11-19): the Markdown saved on this
// computer, Pro's records kept through an update, and 检查更新.
describe("the Markdown counted for the Pro page", () => {
  const dirs: string[] = [];
  const home = () => {
    const dir = mkdtempSync(join(tmpdir(), "papersearch-stats-"));
    dirs.push(dir);
    return { XDG_DATA_HOME: dir };
  };
  afterEach(() => dirs.splice(0).forEach((dir) => rmSync(dir, { recursive: true, force: true })));

  it("counts each Markdown saved and those complete, beside Pro's records", () => {
    const env = home();
    expect(readMarkdownStats(env)).toEqual({ converted: 0, complete: 0 });
    recordMarkdownSaved(true, env);
    recordMarkdownSaved(false, env);
    recordMarkdownSaved(true, env);
    expect(readMarkdownStats(env)).toEqual({ converted: 3, complete: 2 });
    expect(markdownStatsFile(env)).toBe(join(env.XDG_DATA_HOME, "paper-search-cli", "pro", "stats.json"));
    // A broken file starts again; a count of complete above the saved is cut to it.
    writeFileSync(markdownStatsFile(env), "{broken");
    expect(readMarkdownStats(env)).toEqual({ converted: 0, complete: 0 });
    writeFileSync(markdownStatsFile(env), JSON.stringify({ converted: 2, complete: 9 }));
    expect(readMarkdownStats(env)).toEqual({ converted: 2, complete: 2 });
  });

  it("keeps Pro's records through an update, and tells a newer version", async () => {
    const env = home();
    const release = join(env.XDG_DATA_HOME, "release");
    mkdirSync(release);
    const publish = (version: string) => {
      const bundle = Buffer.from(`export const VERSION = "${version}";\n`);
      writeFileSync(join(release, "index.js"), bundle);
      writeFileSync(join(release, "pro.json"), JSON.stringify({ version, bytes: bundle.length,
        sha256: createHash("sha256").update(bundle).digest("hex") }));
    };
    publish("0.1.1");
    expect(await installPro({ from: release, env })).toMatchObject({ ok: true, version: "0.1.1" });
    recordMarkdownSaved(true, env);
    const folder = join(env.XDG_DATA_HOME, "paper-search-cli", "pro");
    writeFileSync(join(folder, "access.json"), JSON.stringify({ mode: "free", firstSeen: 1 }));
    expect(await checkPro({ from: release, env })).toEqual({ ok: true, installed: true, version: "0.1.1", latest: "0.1.1", update: false });
    publish("0.1.2");
    expect(await checkPro({ from: release, env })).toEqual({ ok: true, installed: true, version: "0.1.1", latest: "0.1.2", update: true });
    expect(await installPro({ from: release, env })).toMatchObject({ ok: true, version: "0.1.2" });
    expect(readMarkdownStats(env)).toEqual({ converted: 1, complete: 1 });
    expect(JSON.parse(readFileSync(join(folder, "access.json"), "utf8"))).toEqual({ mode: "free", firstSeen: 1 });
    expect(readFileSync(join(folder, "index.js"), "utf8")).toContain("0.1.2");
    expect(await checkPro({ from: join(release, "missing"), env })).toMatchObject({ ok: false });
  });

  it("orders versions as releases go", () => {
    expect(newerVersion("0.1.10", "0.1.9")).toBe(true);
    expect(newerVersion("0.1.2", "0.1.2")).toBe(false);
    expect(newerVersion("0.2.0", "0.10.0")).toBe(false);
    expect(newerVersion("1.0.0", "1.0.0-beta.2")).toBe(true);
    expect(newerVersion("1.0.0-beta.10", "1.0.0-beta.9")).toBe(true);
    expect(newerVersion("v0.2.0", "0.1.9")).toBe(true);
  });
});
