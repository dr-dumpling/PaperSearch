import { spawnSync } from "child_process";
import { textPdf } from "../fixtures/textPdf.js";
import {
  chmodSync,
  existsSync,
  mkdirSync,
  mkdtempSync,
  readFileSync,
  rmSync,
  writeFileSync,
} from "fs";
import { join } from "path";
import { tmpdir } from "os";
import { afterEach, beforeEach, describe, expect, it } from "@jest/globals";

describe("CARSI CLI integration", () => {
  let tempDir: string;

  beforeEach(() => {
    tempDir = mkdtempSync(join(tmpdir(), "paper-search-carsi-cli-"));
  });

  afterEach(() => {
    rmSync(tempDir, { recursive: true, force: true });
  });

  it("downloads through the stable entitled-access port after explicitly skipping Sci-Hub", () => {
    const binDir = join(tempDir, "bin");
    const outputDir = join(tempDir, "downloads");
    const xdgDataHome = join(tempDir, "xdg-data");
    const logPath = join(tempDir, "fake-carsi.log");
    const pdfPath = join(tempDir, "fake-entitled.pdf");
    const wrapperPath = join(binDir, "paper-search-carsi");
    const fixturePath = join(
      process.cwd(),
      "tests/fixtures/carsi/fake/fake-carsi-mcp.mjs",
    );
    const canonicalDoi = "10.1000/test.doi";

    mkdirSync(binDir, { recursive: true });
    writeFileSync(
      pdfPath,
      textPdf([["Example article", `https://doi.org/${canonicalDoi}`]]),
    );
    writeFileSync(
      wrapperPath,
      [
        "#!/bin/sh",
        `exec ${shellQuote(process.execPath)} ${shellQuote(fixturePath)} --scenario success --log ${shellQuote(logPath)} --file ${shellQuote(pdfPath)} "$@"`,
        "",
      ].join("\n"),
    );
    chmodSync(wrapperPath, 0o755);
    writeFileSync(
      join(tempDir, "config.json"),
      JSON.stringify({
        PAPER_SEARCH_CARSI_EXECUTABLE: wrapperPath,
      }),
    );

    const args = {
      source: "no_searcher",
      paperId: "10.1000/TEST.DOI",
      doi: "",
      title: "",
      savePath: outputDir,
      useSciHub: false,
    };
    const env: NodeJS.ProcessEnv = {
      ...process.env,
      PATH: "",
      HOME: tempDir,
      XDG_DATA_HOME: xdgDataHome,
      PAPER_SEARCH_CONFIG_FILE: join(tempDir, "config.json"),
      PAPER_SEARCH_HIDE_SETUP_HINT: "1",
      PAPER_SEARCH_CARSI_ENABLED: "true",
      PAPER_SEARCH_FAKE_PARENT_SECRET: "must-not-cross-process-boundary",
      PAPER_SEARCH_TEST_PMC_LOG: join(tempDir, "pmc-requests.log"),
    };
    delete env.PAPER_SEARCH_UNPAYWALL_EMAIL;
    delete env.UNPAYWALL_EMAIL;
    delete env.PAPER_SEARCH_CARSI_EXECUTABLE;

    const result = spawnSync(
      process.execPath,
      [
        "--import", "tsx", "--import", join(process.cwd(), "tests/fixtures/carsi/fake/empty-pmc.mjs"),
        "src/cli.ts",
        "run",
        "download_with_fallback",
        "--json-args",
        JSON.stringify(args),
        "--pretty",
      ],
      { cwd: process.cwd(), env, encoding: "utf8", timeout: 30_000 },
    );

    expect(result.error).toBeUndefined();
    expect(result.status).toBe(0);
    expect(readFileSync(join(tempDir, "pmc-requests.log"), "utf8").trim()).toBe(canonicalDoi);
    const output = JSON.parse(result.stdout);
    expect(output).toEqual(
      expect.objectContaining({ ok: true, tool: "download_with_fallback" }),
    );
    expect(output.data).toEqual(
      expect.objectContaining({
        status: "ok",
        path: expect.stringContaining(`${outputDir}/papers/`),
        attempts: [
          expect.objectContaining({ stage: "primary", status: "skipped" }),
          expect.objectContaining({
            stage: "direct_pdf_url",
            status: "skipped",
          }),
          expect.objectContaining({ stage: "repositories", status: "skipped" }),
          expect.objectContaining({ stage: "unpaywall", status: "skipped" }),
          expect.objectContaining({
            stage: "publisher_api",
            status: "skipped",
          }),
          expect.objectContaining({ stage: "scihub", status: "skipped" }),
          expect.objectContaining({ stage: "entitled_access", status: "ok" }),
        ],
      }),
    );
    expect(existsSync(pdfPath)).toBe(true);

    const events = readFileSync(logPath, "utf8")
      .trim()
      .split("\n")
      .map((line) => JSON.parse(line));
    const start = events.find((event) => event.event === "start");
    const calls = events.filter((event) => event.event === "call");
    expect(start).toEqual(
      expect.objectContaining({
        parentSecretPresent: false,
        dataDir: join(xdgDataHome, "paper-search-cli", "carsi"),
      }),
    );
    expect(calls).toEqual([
      expect.objectContaining({
        tool: "carsi_cache_clear",
        arguments: { identifier: canonicalDoi },
      }),
      expect.objectContaining({
        tool: "carsi_download",
        arguments: {
          identifier: canonicalDoi,
          output_dir: expect.stringContaining(`${outputDir}/papers/`),
          scihub_enabled: false,
          use_tor: false,
          bibtex: false,
          strategy: "legal_only",
        },
      }),
    ]);
    expect(() => process.kill(start.pid, 0)).toThrow();
  });

  it.each([
    ["globally disabled", "false", undefined],
    ["disabled for the request", "true", false],
  ])(
    "does not create a CARSI backend when entitled access is %s",
    (_label, enabled, useEntitledAccess) => {
      const marker = join(tempDir, "scan-marker.log");
      const binDir = installMarkerExecutable(marker);
      const args: Record<string, unknown> = {
        source: "no_searcher",
        paperId: "10.1000/test.doi",
        doi: "",
        title: "",
        savePath: join(tempDir, "downloads"),
        useSciHub: false,
      };
      if (useEntitledAccess !== undefined)
        args.useEntitledAccess = useEntitledAccess;

      const result = runCli(
        [
          "run",
          "download_with_fallback",
          "--json-args",
          JSON.stringify(args),
          "--pretty",
        ],
        {
          PATH: binDir,
          PAPER_SEARCH_CARSI_ENABLED: enabled,
        },
      );

      expect(result.status).toBe(0);
      expect(JSON.parse(result.stdout).data.attempts).toEqual(
        expect.arrayContaining([
          expect.objectContaining({
            stage: "entitled_access",
            status: "skipped",
          }),
        ]),
      );
      expect(existsSync(marker)).toBe(false);
    },
  );

  it("never probes CARSI for config, status, tools, or mock smoke commands", () => {
    const marker = join(tempDir, "scan-marker.log");
    const binDir = installMarkerExecutable(marker);
    const env = {
      PATH: binDir,
      PAPER_SEARCH_CARSI_ENABLED: "true",
    };
    const commands = [
      ["config", "keys", "--pretty"],
      ["status", "--pretty"],
      ["tools", "--pretty"],
      ["smoke", "--mock", "--skills-root", tempDir, "--pretty"],
    ];

    for (const command of commands) {
      const result = runCli(command, env);
      expect(result.status).toBe(0);
    }
    expect(existsSync(marker)).toBe(false);
  });

  it("probes exactly once for doctor and reuses that readiness snapshot", () => {
    const logPath = join(tempDir, "doctor-carsi.log");
    const pdfPath = join(tempDir, "unused.pdf");
    const binDir = installFakeExecutable(logPath, pdfPath);

    const result = runCli(["doctor", "--pretty"], {
      PATH: binDir,
      XDG_DATA_HOME: join(tempDir, "xdg-data"),
      PAPER_SEARCH_CARSI_ENABLED: "true",
    });

    expect(result.status).toBe(0);
    const output = JSON.parse(result.stdout);
    expect(
      output.capabilityProfile.entries.find(
        (entry: any) => entry.id === "entitled_access",
      ).readiness,
    ).toEqual({
      state: "available",
      code: "ready",
    });
    const events = readEvents(logPath);
    expect(events.filter((event) => event.event === "start")).toHaveLength(1);
    expect(events.filter((event) => event.event === "call")).toEqual([]);
  });

  it.each([
    ["business_error", "login_required"],
    ["success", "pdf_identity_mismatch"],
  ])(
    "returns a structured %s failure without treating it as a successful PDF",
    (scenario, code) => {
      const pdfPath = join(tempDir, "other-paper.pdf");
      writeFileSync(
        pdfPath,
        textPdf([["Another article", "doi:10.1000/other"]]),
      );
      const binDir = installFakeExecutable(
        join(tempDir, "calls.jsonl"),
        pdfPath,
        scenario,
      );
      const result = runCli(
        [
          "run",
          "download_with_fallback",
          "--json-args",
          JSON.stringify({
            source: "no_searcher",
            paperId: "10.1000/target",
            doi: "",
            title: "",
            useSciHub: false,
            savePath: join(tempDir, "downloads"),
          }),
        ],
        {
          PATH: binDir,
          XDG_DATA_HOME: join(tempDir, "xdg-data"),
          PAPER_SEARCH_CARSI_ENABLED: "true",
        },
      );
      expect(result.error).toBeUndefined();
      const output = JSON.parse(result.stdout);
      expect(output.data.status).toBe("error");
      expect(output.data.path).toBeUndefined();
      expect(output.data.attempts.find((attempt: any) => attempt.stage === "entitled_access")).toMatchObject({
        stage: "entitled_access",
        status: "error",
        code,
      });
      if (scenario === "success") {
        expect(output.data.review).toEqual({ path: expect.stringContaining("/diagnostics/"), reason: code });
        expect(readFileSync(output.data.review.path)).toEqual(readFileSync(pdfPath));
        expect(existsSync(pdfPath)).toBe(true);
      }
      expect(result.stdout).not.toMatch(/do-not-leak|session-secret|cookie=/);
    },
  );

  it("writes fixed live progress to CLI stderr while stdout remains JSON", () => {
    const pdfPath = join(tempDir, "target.pdf");
    writeFileSync(
      pdfPath,
      textPdf([["Example article", "doi:10.1000/target"]]),
    );
    const binDir = installFakeExecutable(
      join(tempDir, "progress-calls.jsonl"),
      pdfPath,
      "progress_valid",
    );
    const result = runCli(
      [
        "run",
        "download_with_fallback",
        "--json-args",
        JSON.stringify({
          source: "no_searcher",
          paperId: "10.1000/target",
          useSciHub: false,
          savePath: join(tempDir, "downloads"),
        }),
      ],
      {
        PATH: binDir,
        XDG_DATA_HOME: join(tempDir, "xdg-data"),
        PAPER_SEARCH_CARSI_ENABLED: "true",
      },
    );
    expect(result.status).toBe(0);
    expect(JSON.parse(result.stdout).data.status).toBe("ok");
    expect(result.stderr).toContain("[CARSI] 正在等待机构登录");
    expect(result.stderr).toContain("[CARSI] 正在等待人工安全验证");
    expect(result.stderr).toContain("[CARSI] 正在获取 PDF");
    expect(result.stdout).not.toContain("[CARSI]");
    expect(result.stdout + result.stderr).not.toMatch(
      /do-not-leak|cookie=|token=|private/,
    );
  });

  function runCli(args: string[], extraEnv: NodeJS.ProcessEnv = {}) {
    const env: NodeJS.ProcessEnv = {
      ...process.env,
      HOME: tempDir,
      PAPER_SEARCH_CONFIG_FILE: join(tempDir, "config.json"),
      PAPER_SEARCH_HIDE_SETUP_HINT: "1",
      ...extraEnv,
    };
    delete env.PAPER_SEARCH_UNPAYWALL_EMAIL;
    delete env.UNPAYWALL_EMAIL;
    return spawnSync(
      process.execPath,
      ["--import", "tsx", "--import", join(process.cwd(), "tests/fixtures/carsi/fake/empty-pmc.mjs"), "src/cli.ts", ...args],
      {
        cwd: process.cwd(),
        env,
        encoding: "utf8",
        timeout: 30_000,
      },
    );
  }

  function installMarkerExecutable(marker: string): string {
    const binDir = join(tempDir, "marker-bin");
    mkdirSync(binDir, { recursive: true });
    const executable = join(binDir, "paper-search-carsi");
    writeFileSync(
      executable,
      `#!/bin/sh\nprintf spawned >> ${shellQuote(marker)}\nexit 1\n`,
    );
    chmodSync(executable, 0o755);
    return binDir;
  }

  function installFakeExecutable(
    logPath: string,
    resultFile: string,
    scenario = "success",
  ): string {
    const binDir = join(tempDir, "fake-bin");
    const wrapperPath = join(binDir, "paper-search-carsi");
    const fixturePath = join(
      process.cwd(),
      "tests/fixtures/carsi/fake/fake-carsi-mcp.mjs",
    );
    mkdirSync(binDir, { recursive: true });
    writeFileSync(
      wrapperPath,
      [
        "#!/bin/sh",
        `exec ${shellQuote(process.execPath)} ${shellQuote(fixturePath)} --scenario ${shellQuote(scenario)} --log ${shellQuote(logPath)} --file ${shellQuote(resultFile)} "$@"`,
        "",
      ].join("\n"),
    );
    chmodSync(wrapperPath, 0o755);
    return binDir;
  }
});

function readEvents(logPath: string): any[] {
  return readFileSync(logPath, "utf8")
    .trim()
    .split("\n")
    .map((line) => JSON.parse(line));
}

function shellQuote(value: string): string {
  return `'${value.replace(/'/g, `'"'"'`)}'`;
}
