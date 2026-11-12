import {
  existsSync,
  mkdtempSync,
  readFileSync,
  rmSync,
  writeFileSync,
} from "node:fs";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";
import {
  afterEach,
  beforeEach,
  describe,
  expect,
  it,
  jest,
} from "@jest/globals";
import { StdioClientTransport } from "@modelcontextprotocol/sdk/client/stdio.js";
import {
  SCHOOL_DOWNLOAD_TIMEOUT_MS,
  SCHOOL_STARTUP_TIMEOUT_MS,
  SchoolMcpClient,
  resolveDefaultSchoolProfileDir,
} from "../../src/capabilities/pdf-discovery/school/SchoolMcpClient.js";
import {
  createSchoolBackend,
  type SchoolBackend,
  type SchoolProgress,
} from "../../src/capabilities/pdf-discovery/school/index.js";
import * as schoolPort from "../../src/capabilities/pdf-discovery/school/index.js";

interface FakeLogEntry {
  event: "start" | "call" | "signal" | "list";
  cursor?: string | null;
  pid?: number;
  dataDir?: string | null;
  parentSecretPresent?: boolean;
  argv?: string[];
  tool?: string;
  arguments?: Record<string, unknown>;
  signal?: string;
}

const FIXTURE = join(
  process.cwd(),
  "tests/fixtures/school/fake/fake-school-mcp.mjs",
);
const EXIT_IMMEDIATELY_FIXTURE = join(
  process.cwd(),
  "tests/fixtures/school/fake/exit-immediately.mjs",
);
const LIFECYCLE_FIXTURE = join(
  process.cwd(),
  "tests/fixtures/school/fake/lifecycle-child.mjs",
);

describe("SchoolMcpClient", () => {
  const originalSecret = process.env.PAPER_SEARCH_FAKE_PARENT_SECRET;
  const originalSchoolDataDir = process.env.SCHOOL_DATA_DIR;
  let tempDir: string;
  let profileDir: string;
  let userDefaultProfileDir: string;
  let logPath: string;

  beforeEach(() => {
    tempDir = mkdtempSync(join(tmpdir(), "paper-search school;safe-"));
    profileDir = join(tempDir, "paper-search-owned-profile");
    userDefaultProfileDir = join(tempDir, "user-default-school-profile");
    logPath = join(tempDir, "fake calls;not-shell.jsonl");
    process.env.PAPER_SEARCH_FAKE_PARENT_SECRET = "must-not-reach-child";
    process.env.SCHOOL_DATA_DIR = userDefaultProfileDir;
  });

  afterEach(() => {
    if (originalSecret === undefined)
      delete process.env.PAPER_SEARCH_FAKE_PARENT_SECRET;
    else process.env.PAPER_SEARCH_FAKE_PARENT_SECRET = originalSecret;
    if (originalSchoolDataDir === undefined)
      delete process.env.SCHOOL_DATA_DIR;
    else process.env.SCHOOL_DATA_DIR = originalSchoolDataDir;
    rmSync(tempDir, { recursive: true, force: true });
  });

  it("freezes the production profile and timeout defaults", () => {
    expect(
      resolveDefaultSchoolProfileDir(
        { XDG_DATA_HOME: "/tmp/xdg-data" },
        "/tmp/home",
      ),
    ).toBe("/tmp/xdg-data/paper-search-cli/school");
    expect(resolveDefaultSchoolProfileDir({}, "/tmp/home")).toBe(
      "/tmp/home/.local/share/paper-search-cli/school",
    );
    expect(SCHOOL_STARTUP_TIMEOUT_MS).toBe(15_000);
    expect(SCHOOL_DOWNLOAD_TIMEOUT_MS).toBe(1_200_000);
  });

  it("delivers only request-bound fixed stages through the stable optional callback", async () => {
    const events: SchoolProgress[] = [];
    const outcome = await fakeClient("progress_valid").downloadLegalDoi({
      identifier: "https://doi.org/10.1000/TARGET",
      outputDir: tempDir,
      onProgress: (event) => events.push(event),
    });
    expect(outcome.kind).toBe("success");
    expect(events.map((event) => event.stage)).toEqual([
      "opening_article",
      "waiting_login",
      "waiting_verification",
      "fetching_pdf",
    ]);
    for (const event of events) {
      expect(event.identifier).toBe("10.1000/target");
      expect(event.message).toMatch(/[\u4e00-\u9fff]/);
      expect(Object.keys(event).sort()).toEqual([
        "identifier",
        "message",
        "stage",
      ]);
    }
    expect(JSON.stringify(events)).not.toMatch(
      /cookie|token|private|https|do-not-leak/,
    );
    const calls = readLog().filter((entry) => entry.event === "call");
    expect(calls.map((entry) => entry.tool)).toEqual([
      "school_cache_clear",
      "school_download",
    ]);
    expect(Object.keys(calls[1].arguments!).sort()).toEqual([
      "bibtex",
      "identifier",
      "output_dir",
      "scihub_enabled",
      "strategy",
      "use_tor",
    ]);
    await expectAllChildrenExited();
  });

  it("keeps older servers without progress compatible", async () => {
    const onProgress = jest.fn();
    const result = await fakeClient("success").downloadLegalDoi({
      identifier: "10.1000/target",
      outputDir: tempDir,
      onProgress,
    });
    expect(result.kind).toBe("success");
    expect(onProgress).not.toHaveBeenCalled();
  });

  it("does not let a progress observer change the result or leak its exception", async () => {
    const result = await fakeClient("progress_valid").downloadLegalDoi({
      identifier: "10.1000/target",
      outputDir: tempDir,
      onProgress: () => {
        throw new Error("cookie=private");
      },
    });
    expect(result.kind).toBe("success");
    expect(JSON.stringify(result)).not.toContain("private");
  });

  it("does not deliver a notification for a different request token", async () => {
    const onProgress = jest.fn();
    const result = await fakeClient("progress_wrong_token").downloadLegalDoi({
      identifier: "10.1000/target",
      outputDir: tempDir,
      onProgress,
    });
    expect(onProgress).not.toHaveBeenCalled();
    expect(result).toMatchObject({
      kind: "attempt_error",
      code: "invalid_download_result",
    });
    expect(JSON.stringify(result)).not.toContain("progressToken");
  });

  it("stops progress on cancellation and releases the profile lock", async () => {
    const controller = new AbortController();
    const events: SchoolProgress[] = [];
    const result = await fakeClient("progress_hang").downloadLegalDoi({
      identifier: "10.1000/target",
      outputDir: tempDir,
      signal: controller.signal,
      onProgress: (event) => {
        events.push(event);
        controller.abort();
      },
    });
    expect(result).toMatchObject({ kind: "attempt_error", code: "cancelled" });
    expect(events).toHaveLength(1);
    expect(existsSync(join(profileDir, ".paper-search-download.lock"))).toBe(
      false,
    );
    await expectAllChildrenExited();
  });

  it("keeps the download deadline bounded despite progress heartbeats", async () => {
    const result = await fakeClient("progress_heartbeat", {
      downloadTimeoutMs: 150,
    }).downloadLegalDoi({
      identifier: "10.1000/target",
      outputDir: tempDir,
      onProgress: () => {},
    });
    expect(result).toMatchObject({
      kind: "attempt_error",
      code: "download_timeout",
    });
    await expectAllChildrenExited();
  });

  it("exposes a stable backend port without MCP-specific call methods", () => {
    const backend: SchoolBackend = createSchoolBackend();

    expect(typeof backend.probe).toBe("function");
    expect(typeof backend.downloadLegalDoi).toBe("function");
    expect(backend).not.toHaveProperty("callTool");
    expect(backend).not.toHaveProperty("transport");
    expect(schoolPort).not.toHaveProperty("SchoolMcpClient");
  });

  it("accepts the compatible contract and additive optional fields", async () => {
    const readiness = await fakeClient("extra_optional").probe();

    expect(readiness).toEqual({
      state: "available",
      code: "ready",
      message: "School backend MCP contract is compatible.",
      missing: [],
    });
    const [start] = readLog().filter((entry) => entry.event === "start");
    expect(start).toEqual(
      expect.objectContaining({
        dataDir: resolve(profileDir),
        parentSecretPresent: false,
      }),
    );
    expect(start.argv).toContain(logPath);
    expect(existsSync(userDefaultProfileDir)).toBe(false);
    expect(readLog().filter((entry) => entry.event === "call")).toEqual([]);
  });

  it.each([
    ["wrong_server", "server_name_mismatch"],
    ["missing_download", "missing_download_tool"],
    ["missing_clear", "missing_cache_clear_tool"],
    ["extra_required", "download_schema_incompatible"],
    ["bad_field_type", "download_schema_incompatible"],
    ["strategy_rejects_legal_only", "download_schema_incompatible"],
    ["scihub_requires_true", "download_schema_incompatible"],
    ["clear_without_identifier", "cache_clear_schema_incompatible"],
    ["duplicate_tools", "ambiguous_tool_contract"],
    ["pagination_cycle", "tools_list_incomplete"],
  ])("classifies %s as an incompatible backend", async (scenario, code) => {
    const readiness = await fakeClient(scenario).probe();

    expect(readiness).toEqual(
      expect.objectContaining({
        state: "incompatible",
        code,
        missing: [],
      }),
    );
    expect(readLog().filter((entry) => entry.event === "call")).toEqual([]);
  });

  it("accepts a cache-clear schema that requires the identifier", async () => {
    const readiness = await fakeClient("clear_identifier_required").probe();

    expect(readiness).toEqual(
      expect.objectContaining({ state: "available", code: "ready" }),
    );
    expect(readLog().filter((entry) => entry.event === "call")).toEqual([]);
  });

  it("accepts and invokes a newer contract requiring policy fields we already send", async () => {
    const outcome = await fakeClient("compatible_required").downloadLegalDoi({
      identifier: "10.1000/example",
      outputDir: tempDir,
    });

    expect(outcome.kind).toBe("success");
    expect(
      readLog()
        .filter((entry) => entry.event === "call")
        .map((entry) => entry.tool),
    ).toEqual(["school_cache_clear", "school_download"]);
  });

  it("reads all tool pages before declaring compatibility without invoking tools", async () => {
    const readiness = await fakeClient("paginated_tools").probe();

    expect(readiness.state).toBe("available");
    expect(
      readLog()
        .filter((entry) => entry.event === "list")
        .map((entry) => entry.cursor),
    ).toEqual([null, "download", "clear"]);
    expect(readLog().filter((entry) => entry.event === "call")).toEqual([]);
    await expectAllChildrenExited();
  });

  it("keeps later tool pages inside the startup deadline", async () => {
    const readiness = await fakeClient("pagination_hang", {
      startupTimeoutMs: 500,
    }).probe();

    expect(readiness.code).toBe("startup_timeout");
    expect(readLog().filter((entry) => entry.event === "list")).toHaveLength(2);
    await expectAllChildrenExited();
  });

  it("rechecks an upstream change on the next session instead of caching readiness", async () => {
    const scenarioPath = join(tempDir, "upstream-scenario.txt");
    writeFileSync(scenarioPath, "success");
    const client = new SchoolMcpClient({
      command: process.execPath,
      args: [FIXTURE, "--scenario-file", scenarioPath, "--log", logPath],
      profileDir,
    });
    expect((await client.probe()).state).toBe("available");

    writeFileSync(scenarioPath, "extra_required");
    const outcome = await client.downloadLegalDoi({
      identifier: "10.1000/example",
      outputDir: tempDir,
    });
    expect(outcome).toEqual(
      expect.objectContaining({
        kind: "backend_unavailable",
        readiness: expect.objectContaining({
          code: "download_schema_incompatible",
        }),
      }),
    );
    expect(readLog().filter((entry) => entry.event === "call")).toEqual([]);
    await expectAllChildrenExited();
  });

  it("classifies a missing executable without leaking the attempted command", async () => {
    const client = new SchoolMcpClient({
      command: join(tempDir, "missing school;do-not-run"),
      args: ["run"],
      profileDir,
      startupTimeoutMs: 200,
      cleanupTimeoutMs: 500,
    });

    const readiness = await client.probe();

    expect(readiness).toEqual({
      state: "absent",
      code: "executable_missing",
      message: "School backend executable was not found.",
      missing: ["school"],
    });
    expect(JSON.stringify(readiness)).not.toContain(tempDir);
  });

  it("uses one canonical DOI for clear then download with fixed safe arguments", async () => {
    const outputDir = join(tempDir, "downloads");
    const outcome = await fakeClient("success").downloadLegalDoi({
      identifier: "https://doi.org/10.1000/Example",
      outputDir,
    });

    expect(outcome).toEqual({
      kind: "success",
      identifier: "10.1000/example",
      path: "/tmp/fake-school.pdf",
      source: "Publisher(Campus)",
    });
    const entries = readLog();
    const starts = entries.filter((entry) => entry.event === "start");
    const calls = entries.filter((entry) => entry.event === "call");
    expect(starts).toHaveLength(1);
    expect(starts[0]).toEqual(
      expect.objectContaining({
        dataDir: resolve(profileDir),
        parentSecretPresent: false,
      }),
    );
    expect(calls.map((entry) => entry.tool)).toEqual([
      "school_cache_clear",
      "school_download",
    ]);
    expect(calls[0].arguments).toEqual({ identifier: "10.1000/example" });
    expect(calls[1].arguments).toEqual({
      identifier: "10.1000/example",
      output_dir: resolve(outputDir),
      scihub_enabled: false,
      use_tor: false,
      bibtex: false,
      strategy: "legal_only",
    });
  });

  it.each([
    ["strategy_enum_institutional", "institutional_only"],
    ["strategy_enum_without_institutional", "legal_only"],
    ["success", "legal_only"],
  ])(
    "selects the download strategy from the advertised schema (%s)",
    async (scenario, strategy) => {
      const client = fakeClient(scenario);
      expect(await client.probe()).toEqual(
        expect.objectContaining({ state: "available", code: "ready" }),
      );
      const outcome = await client.downloadLegalDoi({
        identifier: "10.1000/strategy",
        outputDir: tempDir,
      });
      expect(outcome.kind).toBe("success");
      const download = readLog().find(
        (entry) =>
          entry.event === "call" && entry.tool === "school_download",
      );
      expect(download?.arguments).toEqual(
        expect.objectContaining({
          strategy,
          scihub_enabled: false,
          use_tor: false,
        }),
      );
    },
  );

  it("injects the dedicated profile and clears the DOI on every invocation", async () => {
    const client = fakeClient("success");

    await client.downloadLegalDoi({
      identifier: "10.1000/one",
      outputDir: tempDir,
    });
    await client.downloadLegalDoi({
      identifier: "10.1000/two",
      outputDir: tempDir,
    });

    const entries = readLog();
    expect(
      entries
        .filter((entry) => entry.event === "start")
        .map((entry) => entry.dataDir),
    ).toEqual([resolve(profileDir), resolve(profileDir)]);
    expect(
      entries
        .filter((entry) => entry.event === "call")
        .map((entry) => [entry.tool, entry.arguments?.identifier]),
    ).toEqual([
      ["school_cache_clear", "10.1000/one"],
      ["school_download", "10.1000/one"],
      ["school_cache_clear", "10.1000/two"],
      ["school_download", "10.1000/two"],
    ]);
  });

  it("treats cache clear zero as a successful no-op", async () => {
    const outcome = await fakeClient("clear_zero").downloadLegalDoi({
      identifier: "doi:10.1000/no-cache",
      outputDir: tempDir,
    });

    expect(outcome.kind).toBe("success");
    expect(
      readLog()
        .filter((entry) => entry.event === "call")
        .map((entry) => entry.tool),
    ).toEqual(["school_cache_clear", "school_download"]);
  });

  it.each(["clear_is_error", "clear_malformed", "clear_hang"])(
    "does not download when DOI-scoped cache clear fails in %s",
    async (scenario) => {
      const outcome = await fakeClient(scenario, {
        toolTimeoutMs: 100,
      }).downloadLegalDoi({
        identifier: "10.1000/cache-failure",
        outputDir: tempDir,
      });

      expect(outcome).toEqual(
        expect.objectContaining({
          kind: "backend_unavailable",
          readiness: expect.objectContaining({
            state: "incompatible",
            code: "cache_clear_failed",
          }),
        }),
      );
      expect(JSON.stringify(outcome)).not.toMatch(/do-not-leak|https?:\/\//);
      expect(
        readLog()
          .filter((entry) => entry.event === "call")
          .map((entry) => entry.tool),
      ).toEqual(["school_cache_clear"]);
      await expectAllChildrenExited();
    },
  );

  it("keeps a business download failure request-scoped and redacted", async () => {
    const client = fakeClient("business_error");
    const readinessBefore = await client.probe();
    const outcome = await client.downloadLegalDoi({
      identifier: "10.1000/paywall",
      outputDir: tempDir,
    });
    const readinessAfter = await client.probe();

    expect(readinessBefore.state).toBe("available");
    expect(readinessAfter.state).toBe("available");
    expect(outcome).toEqual(
      expect.objectContaining({
        kind: "attempt_error",
        identifier: "10.1000/paywall",
        code: "login_required",
      }),
    );
    expect(JSON.stringify(outcome)).not.toMatch(
      /do-not-leak|cookie|https?:\/\//i,
    );
  });

  it.each([
    "download_is_error",
    "download_malformed",
    "download_multiple_blocks",
  ])(
    "rejects an unusable download tool result in %s without changing compatibility",
    async (scenario) => {
      const client = fakeClient(scenario);
      const outcome = await client.downloadLegalDoi({
        identifier: "10.1000/unusable",
        outputDir: tempDir,
      });

      expect(outcome).toEqual(
        expect.objectContaining({
          kind: "attempt_error",
          identifier: "10.1000/unusable",
          code: "invalid_download_result",
        }),
      );
      expect(JSON.stringify(outcome)).not.toMatch(/do-not-leak|https?:\/\//);
      expect((await client.probe()).state).toBe("available");
    },
  );

  it("keeps unknown source labels as diagnostics rather than compatibility gates", async () => {
    const source = "Future Publisher Route";
    const outcome = await fakeClient("success", { source }).downloadLegalDoi({
      identifier: "10.1000/future-source",
      outputDir: tempDir,
    });

    expect(outcome).toEqual(
      expect.objectContaining({
        kind: "success",
        source,
      }),
    );
  });

  it("times out a stalled download, closes the child, and reports an attempt error", async () => {
    const outcome = await fakeClient("download_hang", {
      downloadTimeoutMs: 100,
    }).downloadLegalDoi({
      identifier: "10.1000/timeout",
      outputDir: tempDir,
    });

    expect(outcome).toEqual(
      expect.objectContaining({
        kind: "attempt_error",
        identifier: "10.1000/timeout",
        code: "download_timeout",
      }),
    );
    await expectAllChildrenExited();
  });

  it("times out a stalled initialize handshake and closes the child", async () => {
    const readiness = await fakeClient("startup_hang", {
      startupTimeoutMs: 500,
    }).probe();

    expect(readiness).toEqual({
      state: "incompatible",
      code: "startup_timeout",
      message: "School backend MCP startup timed out.",
      missing: [],
    });
    await expectAllChildrenExited();
  });

  it("uses one startup deadline across initialize and tools/list", async () => {
    const startedAt = Date.now();
    const readiness = await fakeClient("slow_handshake", {
      startupTimeoutMs: 500,
    }).probe();

    expect(readiness).toEqual(
      expect.objectContaining({
        state: "incompatible",
        code: "startup_timeout",
      }),
    );
    expect(Date.now() - startedAt).toBeLessThan(800);
    await expectAllChildrenExited();
  });

  it("uses the same hard deadline across transport start and initialize", async () => {
    const originalStart = StdioClientTransport.prototype.start;
    const startSpy = jest
      .spyOn(StdioClientTransport.prototype, "start")
      .mockImplementation(async function (this: StdioClientTransport) {
        await originalStart.call(this);
        await new Promise((resolvePromise) => setTimeout(resolvePromise, 700));
      });
    const startedAt = Date.now();

    try {
      const readiness = await fakeClient("slow_initialize", {
        startupTimeoutMs: 1_000,
        cleanupTimeoutMs: 100,
      }).probe();

      expect(readiness).toEqual(
        expect.objectContaining({
          state: "incompatible",
          code: "startup_timeout",
        }),
      );
    } finally {
      startSpy.mockRestore();
    }

    expect(Date.now() - startedAt).toBeLessThan(1_250);
    await expectAllChildrenExited();
  });

  it("classifies a nonzero child exit after tools/list as incompatible", async () => {
    const readiness = await fakeClient("exit_nonzero_after_list").probe();

    expect(readiness).toEqual({
      state: "incompatible",
      code: "process_exited_nonzero",
      message: "School backend MCP process exited with an error.",
      missing: [],
    });
    await expectAllChildrenExited();
  });

  it("captures an immediate nonzero child exit during startup", async () => {
    const readiness = await new SchoolMcpClient({
      command: process.execPath,
      args: [EXIT_IMMEDIATELY_FIXTURE],
      profileDir,
      startupTimeoutMs: 2_000,
      cleanupTimeoutMs: 1_000,
    }).probe();

    expect(readiness).toEqual({
      state: "incompatible",
      code: "process_exited_nonzero",
      message: "School backend MCP process exited with an error.",
      missing: [],
    });
  });

  it("rejects malformed MCP stdout even if the server later responds", async () => {
    const readiness = await fakeClient("stdout_malformed").probe();

    expect(readiness).toEqual({
      state: "incompatible",
      code: "protocol_error",
      message: "School backend MCP stdout contained invalid protocol data.",
      missing: [],
    });
    expect(readLog().filter((entry) => entry.event === "call")).toEqual([]);
    await expectAllChildrenExited();
  });

  it("cancels an in-flight download and still closes the child", async () => {
    const controller = new AbortController();
    const promise = fakeClient("download_hang", {
      downloadTimeoutMs: 2_000,
    }).downloadLegalDoi({
      identifier: "10.1000/cancelled",
      outputDir: tempDir,
      signal: controller.signal,
    });
    void abortOnceLogged(
      controller,
      (entry) => entry.event === "call" && entry.tool === "school_download",
    );

    await expect(promise).resolves.toEqual({
      kind: "attempt_error",
      identifier: "10.1000/cancelled",
      code: "cancelled",
      message: "School backend download was cancelled.",
    });
    await expectAllChildrenExited();
  });

  it("classifies a cancelled readiness probe before startup timeout", async () => {
    const controller = new AbortController();
    const promise = fakeClient("startup_hang", {
      startupTimeoutMs: 2_000,
    }).probe(controller.signal);
    void abortOnceLogged(controller, (entry) => entry.event === "start");

    await expect(promise).resolves.toEqual({
      state: "incompatible",
      code: "probe_cancelled",
      message: "School backend MCP readiness probe was cancelled.",
      missing: [],
    });
    await expectAllChildrenExited();
  });

  it("bounds failed-open cleanup by the configured cleanup deadline", async () => {
    const startedAt = Date.now();
    const readiness = await new SchoolMcpClient({
      command: process.execPath,
      args: [LIFECYCLE_FIXTURE, "--log", logPath],
      profileDir,
      startupTimeoutMs: 300,
      cleanupTimeoutMs: 100,
    }).probe();

    expect(readiness).toEqual(
      expect.objectContaining({
        state: "incompatible",
        code: expect.stringMatching(/^(?:startup_timeout|cleanup_failed)$/),
      }),
    );
    expect(Date.now() - startedAt).toBeLessThan(800);
    expect(readLog()).toContainEqual(
      expect.objectContaining({ event: "signal", signal: "SIGTERM" }),
    );
    await expectAllChildrenExited();
  });

  it("escalates cleanup to SIGKILL when the child ignores SIGTERM", async () => {
    const outcome = await fakeClient("ignore_sigterm", {
      downloadTimeoutMs: 100,
      cleanupTimeoutMs: 1_000,
    }).downloadLegalDoi({
      identifier: "10.1000/ignore-term",
      outputDir: tempDir,
    });

    expect(outcome).toEqual(
      expect.objectContaining({
        kind: "attempt_error",
        code: "download_timeout",
      }),
    );
    expect(readLog()).toContainEqual(
      expect.objectContaining({ event: "signal", signal: "SIGTERM" }),
    );
    await expectAllChildrenExited();
  });

  it("rejects an invalid DOI before spawning the school backend", async () => {
    const outcome = await fakeClient("success").downloadLegalDoi({
      identifier: "not-a-doi",
      outputDir: tempDir,
    });

    expect(outcome).toEqual({
      kind: "attempt_error",
      identifier: "",
      code: "invalid_identifier",
      message: "A valid DOI is required for school subscription downloads.",
    });
    expect(existsSync(logPath)).toBe(false);
  });

  it("serializes downloads across backend instances and releases the lock after cancellation", async () => {
    const controller = new AbortController();
    const first = fakeClient("download_hang", {
      downloadTimeoutMs: 10_000,
    }).downloadLegalDoi({
      identifier: "10.1000/first",
      outputDir: tempDir,
      signal: controller.signal,
    });
    try {
      const deadline = Date.now() + 4_000;
      while (
        !readLog().some((entry) => entry.tool === "school_download") &&
        Date.now() < deadline
      ) {
        await new Promise((resolve) => setTimeout(resolve, 20));
      }
      expect(
        readLog().some((entry) => entry.tool === "school_download"),
      ).toBe(true);
      expect(
        await fakeClient("success").downloadLegalDoi({
          identifier: "10.1000/second",
          outputDir: tempDir,
        }),
      ).toMatchObject({ kind: "attempt_error", code: "profile_busy" });
      expect(readLog().filter((entry) => entry.event === "start")).toHaveLength(
        1,
      );
    } finally {
      controller.abort();
    }
    expect(await first).toMatchObject({
      kind: "attempt_error",
      code: "cancelled",
    });
    expect(existsSync(join(profileDir, ".paper-search-download.lock"))).toBe(
      false,
    );
    expect(
      await fakeClient("success").downloadLegalDoi({
        identifier: "10.1000/second",
        outputDir: tempDir,
      }),
    ).toMatchObject({ kind: "success" });
    await expectAllChildrenExited();
  });

  it.each(["normal", "cancelled", "verification_timeout"])("keeps one backend and lock through a %s batch", async (mode) => {
    const client = fakeClient(mode === "verification_timeout" ? "batch_browser_verification_timeout" : "batch_browser");
    const lock = join(profileDir, ".paper-search-download.lock");
    const batch = { id: "batch-browser", index: 1, total: 2, done: 0, succeeded: 0, failed: 0 };
    const run = client.withBatchSession(async (backend) => {
      expect(await backend.downloadLegalDoi({ identifier: "10.1000/first", outputDir: tempDir, batch }))
        .toMatchObject(mode === "verification_timeout"
          ? { kind: "attempt_error", code: "download_timeout" } : { kind: "success" });
      expect(existsSync(lock)).toBe(true);
      if (mode === "cancelled") throw new Error("batch cancelled");
      expect(await backend.downloadLegalDoi({ identifier: "10.1000/second", outputDir: tempDir,
        batch: { ...batch, index: 2, done: 1, succeeded: 1 } })).toMatchObject({ kind: "success" });
    });
    if (mode === "cancelled") await expect(run).rejects.toThrow("batch cancelled");
    else await run;
    expect(readLog().filter((row) => row.event === "start")).toHaveLength(1);
    const calls = readLog().filter((row) => row.event === "call");
    expect(calls.filter((row) => row.tool === "school_download").map((row) => row.arguments?.keep_browser))
      .toEqual(mode === "cancelled" ? [true] : [true, true]);
    expect(calls.at(-1)?.tool).toBe("school_close_batch_browser");
    expect(existsSync(lock)).toBe(false);
    await expectAllChildrenExited();
  });

  it("sends a batch's papers on its backend, starting one only for the last list", async () => {
    const update = { id: "batch-papers", folder: tempDir,
      papers: [{ index: 1, doi: "10.1000/one", title: "One", journal: "", state: "open" as const }] };
    await fakeClient("batch_browser_lanes").withBatchSession(async (backend) => {
      // No backend yet: a list in the middle of the batch waits for one.
      expect(await backend.reportBatchPapers!(update)).toBe(false);
      expect(readLog().filter((row) => row.event === "start")).toHaveLength(0);
      // The last one starts it; the finished card's report goes on the same process.
      expect(await backend.reportBatchPapers!(update, true)).toBe(true);
      expect(await backend.reportBatchProgress!({ id: "batch-papers", total: 1, done: 1, succeeded: 0, failed: 1, finished: true }))
        .toBe(true);
    });
    expect(readLog().filter((row) => row.event === "start")).toHaveLength(1);
    expect(readLog().filter((row) => row.event === "call" && row.tool === "school_batch_papers")
      .map((row) => row.arguments)).toEqual([{ batch_id: "batch-papers", folder: tempDir, papers: update.papers }]);
    await expectAllChildrenExited();

    // A backend without the lists is asked once.
    rmSync(logPath, { force: true });
    await fakeClient("batch_browser").withBatchSession(async (backend) => {
      expect(await backend.reportBatchPapers!(update, true)).toBe(false);
      expect(await backend.reportBatchPapers!(update, true)).toBe(false);
    });
    expect(readLog().filter((row) => row.event === "start")).toHaveLength(1);
    expect(readLog().some((row) => row.tool === "school_batch_papers")).toBe(false);
    await expectAllChildrenExited();
  });

  function fakeClient(
    scenario: string,
    overrides: {
      source?: string;
      startupTimeoutMs?: number;
      toolTimeoutMs?: number;
      downloadTimeoutMs?: number;
      cleanupTimeoutMs?: number;
    } = {},
  ): SchoolMcpClient {
    const args = [FIXTURE, "--scenario", scenario, "--log", logPath];
    if (overrides.source) args.push("--source", overrides.source);
    return new SchoolMcpClient({
      command: process.execPath,
      args,
      profileDir,
      startupTimeoutMs: overrides.startupTimeoutMs ?? 2_000,
      toolTimeoutMs: overrides.toolTimeoutMs ?? 2_000,
      downloadTimeoutMs: overrides.downloadTimeoutMs ?? 2_000,
      cleanupTimeoutMs: overrides.cleanupTimeoutMs ?? 1_000,
    });
  }

  function readLog(): FakeLogEntry[] {
    if (!existsSync(logPath)) return [];
    return readFileSync(logPath, "utf8")
      .split("\n")
      .filter(Boolean)
      .map((line) => JSON.parse(line) as FakeLogEntry);
  }

  // Cancel only once the fake child has reached the step under test; a fixed delay can fire before
  // a slow machine has even started the child, and then there is no child to check.
  async function abortOnceLogged(
    controller: AbortController,
    reached: (entry: FakeLogEntry) => boolean,
  ): Promise<void> {
    const deadline = Date.now() + 10_000;
    while (Date.now() < deadline && !readLog().some(reached)) {
      await new Promise((resolvePromise) => setTimeout(resolvePromise, 25));
    }
    controller.abort();
  }

  async function expectAllChildrenExited(): Promise<void> {
    const pids = readLog()
      .filter((entry) => entry.event === "start" && entry.pid)
      .map((entry) => entry.pid as number);
    expect(pids.length).toBeGreaterThan(0);

    const deadline = Date.now() + 2_000;
    while (Date.now() < deadline && pids.some(isProcessAlive)) {
      await new Promise((resolvePromise) => setTimeout(resolvePromise, 25));
    }
    expect(pids.filter(isProcessAlive)).toEqual([]);
  }
});

function isProcessAlive(pid: number): boolean {
  try {
    process.kill(pid, 0);
    return true;
  } catch {
    return false;
  }
}
