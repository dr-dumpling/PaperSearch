import { EventEmitter } from "node:events";
import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { PassThrough } from "node:stream";
import { afterAll, describe, expect, it, jest } from "@jest/globals";

/**
 * What cross-spawn (the MCP SDK's spawn) does on Windows with a command it cannot
 * find: it starts cmd.exe for it, and when cmd.exe exits with 1 it reports ENOENT
 * as an "error" event in place of the "exit" event. The process did start, so the
 * SDK's start() has already resolved by then (Windows, 2026-11-18: an absent
 * backend was reported as "exited before readiness", and `doctor` then said to
 * run `school update` instead of `school install`).
 */
jest.mock("cross-spawn", () => {
  const spawn = () => {
    const child = Object.assign(new EventEmitter(), {
      stdin: new PassThrough(),
      stdout: new PassThrough(),
      stderr: new PassThrough(),
      pid: 4242,
      exitCode: null as number | null,
      signalCode: null as string | null,
      kill: () => true,
    });
    setImmediate(() => {
      child.emit("spawn");
      setTimeout(() => {
        child.exitCode = 1;
        child.emit("error", Object.assign(new Error("spawn missing-school ENOENT"), {
          code: "ENOENT", errno: "ENOENT", syscall: "spawn missing-school", path: "missing-school", spawnargs: ["run"],
        }));
        child.emit("close", 1, null);
      }, 20);
    });
    return child;
  };
  return { __esModule: true, default: spawn };
});

import { SchoolMcpClient } from "../../src/infrastructure/school/SchoolMcpClient.js";

const profileDir = mkdtempSync(join(tmpdir(), "paper-search-missing-windows-"));
afterAll(() => rmSync(profileDir, { recursive: true, force: true }));

describe("a school backend that is not installed, on Windows", () => {
  it("is reported absent, as on macOS and Linux, not as a process that exited", async () => {
    const readiness = await new SchoolMcpClient({
      command: "missing-school",
      profileDir,
      startupTimeoutMs: 2_000,
      cleanupTimeoutMs: 500,
    }).probe();

    expect(readiness).toEqual({
      state: "absent",
      code: "executable_missing",
      message: "School backend executable was not found.",
      missing: ["school"],
    });
  });
});
