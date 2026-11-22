import { createServer, type IncomingMessage, type Server } from "node:http";
import type { AddressInfo } from "node:net";
import { existsSync, mkdtempSync, readFileSync, rmSync, writeFileSync, mkdirSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { afterEach, beforeEach, describe, expect, it } from "@jest/globals";
import { activatePro, activationStatus, installAllowed } from "../../src/management/pro/activate.js";
import { installPro } from "../../src/management/pro/install.js";

// Activating PaperSearch Pro (user, 2026-11-21): checked by PaperSearch's activation server,
// whose address is left empty for now; the interface is there for when it comes.
describe("activating PaperSearch Pro", () => {
  let dir: string;
  let env: Record<string, string | undefined>;
  let server: Server | undefined;
  const asked: Array<Record<string, unknown>> = [];
  const proDir = () => join(dir, "data", "paper-search-cli", "pro");

  /** A stand-in activation server answering with `answer(body)`: [status, JSON]. */
  async function serve(answer: (body: Record<string, unknown>) => [number, unknown]): Promise<string> {
    server = createServer((request: IncomingMessage, response) => {
      let raw = "";
      request.on("data", (chunk) => { raw += chunk; });
      request.on("end", () => {
        const body = JSON.parse(raw || "{}") as Record<string, unknown>;
        asked.push(body);
        const [status, json] = answer(body);
        response.writeHead(status, { "Content-Type": "application/json" });
        response.end(JSON.stringify(json));
      });
    });
    await new Promise<void>((resolve) => server!.listen(0, "127.0.0.1", resolve));
    return `http://127.0.0.1:${(server!.address() as AddressInfo).port}/activate`;
  }

  beforeEach(() => {
    dir = mkdtempSync(join(tmpdir(), "psc-pro-activate-"));
    env = { XDG_DATA_HOME: join(dir, "data") };
    asked.length = 0;
  });
  afterEach(async () => {
    if (server) await new Promise<void>((resolve) => server!.close(() => resolve()));
    server = undefined;
    rmSync(dir, { recursive: true, force: true });
  });

  it("says there is no activation server yet, keeps nothing, and lets an install go ahead as before", async () => {
    expect(await activatePro({ code: "PSPRO-7KQ2-M4XD", env })).toEqual({ ok: false, code: "pro_activation_unavailable", message: "激活服务还没开放" });
    expect(existsSync(proDir())).toBe(false);
    expect(activationStatus(env)).toEqual({ service: false, state: "none", tail: "", until: "" });
    expect(installAllowed(env)).toBe(true);
  });

  it("asks for a code, and one of a plausible form", async () => {
    expect(await activatePro({ code: "  ", env })).toMatchObject({ ok: false, code: "pro_activation_code_missing", message: "请输入激活码" });
    expect(await activatePro({ code: "PS!", env })).toMatchObject({ ok: false, code: "pro_activation_code_invalid", message: "激活码格式不对" });
  });

  it("keeps the server's yes: the code's tail and its end, this computer's id sent and kept", async () => {
    env.PAPER_SEARCH_PRO_ACTIVATION_URL = await serve(() => [200, { ok: true, until: "2099-03-01" }]);
    expect(activationStatus(env)).toMatchObject({ service: true, state: "none" });
    expect(installAllowed(env)).toBe(false);
    expect(await activatePro({ code: " pspro-7kq2-m4xd ", env })).toEqual({ ok: true, state: "active", tail: "M4XD", until: "2099-03-01" });
    expect(asked[0]).toMatchObject({ schemaVersion: 1, code: "PSPRO-7KQ2-M4XD" });
    const device = JSON.parse(readFileSync(join(proDir(), "device.json"), "utf8")).id;
    expect(asked[0].device).toBe(device);
    expect(activationStatus(env)).toEqual({ service: true, state: "active", tail: "M4XD", until: "2099-03-01" });
    expect(installAllowed(env)).toBe(true);
    // The same computer asks again with the same id.
    await activatePro({ code: "PSPRO-7KQ2-M4XD", env });
    expect(asked[1].device).toBe(device);
  });

  it("keeps the activation through an install that follows it", async () => {
    env.PAPER_SEARCH_PRO_ACTIVATION_URL = await serve(() => [200, { ok: true }]);
    await activatePro({ code: "PSPRO-7KQ2-M4XD", env });
    const bundle = "export const createMarkdownPro = () => 1;";
    const release = join(dir, "release");
    mkdirSync(release);
    writeFileSync(join(release, "index.js"), bundle);
    writeFileSync(join(release, "pro.json"), JSON.stringify({ version: "0.1.0" }));
    expect(await installPro({ from: release, env })).toMatchObject({ ok: true, version: "0.1.0" });
    expect(activationStatus(env)).toEqual({ service: true, state: "active", tail: "M4XD", until: "" });
  });

  it("passes on the server's no, and an install then waits for an activation", async () => {
    env.PAPER_SEARCH_PRO_ACTIVATION_URL = await serve(() => [403, { ok: false, message: "激活码已停用" }]);
    expect(await activatePro({ code: "PSPRO-7KQ2-M4XD", env })).toEqual({ ok: false, code: "pro_activation_rejected", message: "激活码已停用" });
    expect(activationStatus(env).state).toBe("none");
    expect(await installPro({ from: join(dir, "nowhere"), env })).toEqual({ ok: false, code: "pro_activation_required", message: "请先激活 PaperSearch Pro" });
  });

  it("says a server that cannot be reached is not reached", async () => {
    env.PAPER_SEARCH_PRO_ACTIVATION_URL = await serve(() => [200, {}]);
    await new Promise<void>((resolve) => server!.close(() => resolve()));
    server = undefined;
    expect(await activatePro({ code: "PSPRO-7KQ2-M4XD", env, timeoutMs: 2_000 })).toEqual({ ok: false, code: "pro_activation_failed", message: "网络连接中断" });
  });

  it("counts an activation past its end as ended", () => {
    mkdirSync(proDir(), { recursive: true });
    writeFileSync(join(proDir(), "activation.json"), JSON.stringify({ code: "PSPRO-7KQ2-M4XD", until: "2026-01-31", activatedAt: "2026-01-01" }));
    env.PAPER_SEARCH_PRO_ACTIVATION_URL = "https://activation.example/activate";
    expect(activationStatus(env, new Date(2026, 1, 1))).toEqual({ service: true, state: "expired", tail: "M4XD", until: "2026-01-31" });
    expect(activationStatus(env, new Date(2026, 0, 31)).state).toBe("active");
  });
});
