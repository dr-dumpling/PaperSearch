import axios from "axios";
import { createHash } from "node:crypto";
import { mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { Readable } from "node:stream";
import { afterEach, beforeEach, describe, expect, it, jest } from "@jest/globals";
import { installPro, proStatus } from "../../src/management/pro/install.js";

// `paper-search pro install` (the settings window's 安装): two files from a folder or Pro's
// release address, the bundle checked against its SHA-256, the old install replaced only once
// the new one is whole (user, 2026-11-18).
describe("installing PaperSearch Pro", () => {
  let dir: string;
  let env: Record<string, string | undefined>;
  const release = (bundle: string, manifest: Record<string, unknown> = {}) => {
    const folder = join(dir, `release-${Math.random().toString(36).slice(2)}`);
    mkdirSync(folder);
    writeFileSync(join(folder, "index.js"), bundle);
    writeFileSync(join(folder, "pro.json"), JSON.stringify({ version: "0.1.0", bytes: bundle.length,
      sha256: createHash("sha256").update(bundle).digest("hex"), ...manifest }));
    return folder;
  };

  beforeEach(() => {
    dir = mkdtempSync(join(tmpdir(), "psc-pro-install-"));
    env = { XDG_DATA_HOME: join(dir, "data") };
  });
  afterEach(() => {
    jest.restoreAllMocks();
    rmSync(dir, { recursive: true, force: true });
  });

  it("says when there is nowhere to install it from", async () => {
    expect(await installPro({ env: { ...env, PAPER_SEARCH_PRO_RELEASE_URL: "" } })).toEqual({ ok: false, code: "pro_release_unavailable", message: "PaperSearch Pro 的下载地址还没开放" });
    expect(proStatus(env)).toMatchObject({ installed: false, version: "" });
  });

  it("installs from a folder into PaperSearch's data, saying how far it got", async () => {
    const progress: Array<[number, number]> = [];
    const result = await installPro({ from: release("export const createMarkdownPro = () => 1;"), env,
      onProgress: (done, total) => progress.push([done, total]) });
    expect(result).toEqual({ ok: true, version: "0.1.0", path: join(dir, "data", "paper-search-cli", "pro", "index.js") });
    expect(progress.at(-1)?.[0]).toBe(progress.at(-1)?.[1]);
    expect(proStatus(env)).toMatchObject({ installed: true, version: "0.1.0" });
  });

  it("leaves the installed one when the new file does not match its SHA-256, or is missing", async () => {
    await installPro({ from: release("first"), env });
    const tampered = release("second", { version: "0.2.0", sha256: "0".repeat(64) });
    expect(await installPro({ from: tampered, env })).toMatchObject({ ok: false, code: "pro_checksum_mismatch" });
    const missing = release("third", { version: "0.3.0" });
    rmSync(join(missing, "index.js"));
    expect(await installPro({ from: missing, env })).toMatchObject({ ok: false, code: "pro_install_failed", message: "找不到安装文件" });
    expect(readFileSync(join(dir, "data", "paper-search-cli", "pro", "index.js"), "utf8")).toBe("first");
    expect(proStatus(env)).toMatchObject({ installed: true, version: "0.1.0" });
  });

  it("downloads from the release address in pieces, each one reported", async () => {
    const bundle = Buffer.from("export const createMarkdownPro = () => 2;");
    const sha256 = createHash("sha256").update(bundle).digest("hex");
    jest.spyOn(axios, "get").mockImplementation((async (url: string) => url.endsWith("/pro.json")
      ? { data: { version: "0.2.0", bytes: bundle.length, sha256 } }
      : { headers: { "content-length": String(bundle.length) }, data: Readable.from([bundle.subarray(0, 10), bundle.subarray(10)]) }) as never);
    const progress: number[] = [];
    const result = await installPro({ from: "https://releases.example.org/pro/", env, onProgress: (done) => progress.push(done) });
    expect(result).toMatchObject({ ok: true, version: "0.2.0" });
    expect(progress).toEqual([10, bundle.length]);
    expect((axios.get as unknown as jest.Mock).mock.calls.map((call) => call[0]))
      .toEqual(["https://releases.example.org/pro/pro.json", "https://releases.example.org/pro/index.js"]);
  });

  // For now Pro's releases are the private repository's (user, 2026-11-18): read with this
  // computer's GitHub login; without one, the install says to sign in.
  describe("from a GitHub release", () => {
    const API = "https://api.github.com/repos/owner/Pro";
    const bundle = Buffer.from("export const createMarkdownPro = () => 3;");
    const manifest = { version: "0.3.0", bytes: bundle.length, sha256: createHash("sha256").update(bundle).digest("hex") };
    const releases = [
      { tag_name: "v1.0.0", draft: false, assets: [] },
      { tag_name: "pro-v0.4.0", draft: true, assets: [] },
      { tag_name: "pro-v0.3.0", draft: false, assets: [
        { name: "index.js", size: bundle.length, url: `${API}/releases/assets/2` },
        { name: "pro.json", size: 100, url: `${API}/releases/assets/1` }] },
    ];
    let asked: Array<{ url: string; headers: Record<string, string> }>;
    const answer = (status?: number) => jest.spyOn(axios, "get").mockImplementation((async (url: string, config: { headers: Record<string, string> }) => {
      asked.push({ url, headers: config.headers });
      if (status) throw Object.assign(new axios.AxiosError("failed"), { response: { status } });
      if (url.includes("/releases?")) return { data: releases };
      if (url.endsWith("/assets/1")) return { data: Buffer.from(JSON.stringify(manifest)) };
      return { data: Readable.from([bundle]) };
    }) as never);
    beforeEach(() => { asked = []; });

    it("installs the newest published pro-v release, signed in", async () => {
      answer();
      const progress: Array<[number, number]> = [];
      const result = await installPro({ from: "github:owner/Pro", env, githubToken: "t0ken", onProgress: (done, total) => progress.push([done, total]) });
      expect(result).toMatchObject({ ok: true, version: "0.3.0" });
      expect(asked.map((call) => call.url)).toEqual([`${API}/releases?per_page=30`, `${API}/releases/assets/1`, `${API}/releases/assets/2`]);
      expect(asked.every((call) => call.headers.Authorization === "Bearer t0ken")).toBe(true);
      expect(asked.slice(1).every((call) => call.headers.Accept === "application/octet-stream")).toBe(true);
      expect(progress).toEqual([[bundle.length, bundle.length]]);
    });

    it("says to sign in to GitHub when the repository does not answer without a login", async () => {
      answer(404);
      expect(await installPro({ from: "github:owner/Pro", env, githubToken: "" }))
        .toEqual({ ok: false, code: "pro_github_login_required", message: "请先在终端运行 gh auth login 登录 GitHub" });
      expect(asked[0].headers.Authorization).toBeUndefined();
      answer(404);
      expect(await installPro({ from: "github:owner/Pro", env, githubToken: "t0ken" }))
        .toMatchObject({ ok: false, code: "pro_release_not_found" });
      expect(proStatus(env)).toMatchObject({ installed: false });
    });
  });
});
