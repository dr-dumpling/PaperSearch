import { appendFileSync, readFileSync } from "node:fs";
import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
import * as z from "zod/v4";

function argumentValue(name) {
  const index = process.argv.indexOf(name);
  return index >= 0 ? process.argv[index + 1] || "" : "";
}

const scenarioFile = argumentValue("--scenario-file");
const scenario = scenarioFile
  ? readFileSync(scenarioFile, "utf8").trim()
  : argumentValue("--scenario") || "success";
const logPath = argumentValue("--log");
const resultFile = argumentValue("--file") || "/tmp/fake-carsi.pdf";
const resultSource = argumentValue("--source") || "Publisher(Campus)";

function log(event, detail = {}) {
  if (!logPath) return;
  appendFileSync(logPath, `${JSON.stringify({ event, ...detail })}\n`, "utf8");
}

log("start", {
  pid: process.pid,
  dataDir: process.env.CARSI_DATA_DIR || null,
  parentSecretPresent: Boolean(process.env.PAPER_SEARCH_FAKE_PARENT_SECRET),
  argv: process.argv.slice(2),
});

process.on("SIGTERM", () => {
  log("signal", { signal: "SIGTERM" });
  if (!scenario.includes("ignore_sigterm")) process.exit(0);
});

if (scenario === "stdout_malformed") {
  process.stdout.write("not-json\n");
}
if (scenario === "stderr_noise") {
  process.stderr.write(
    "startup token=do-not-leak https://publisher.example/private\n",
  );
}

if (
  [
    "exit_nonzero_after_list",
    "slow_handshake",
    "slow_initialize",
    "tools_list_hang",
    "paginated_tools",
    "pagination_cycle",
    "pagination_hang",
    "duplicate_tools",
  ].includes(scenario)
) {
  await runRawScenario(scenario);
} else if (scenario.startsWith("startup_hang")) {
  setInterval(() => {}, 60_000);
} else {
  const server = new McpServer({
    name: scenario === "wrong_server" ? "other-server" : "paper-search-carsi",
    version: "0.1.0",
  });

  const downloadShape = {
    identifier: z.string(),
    output_dir: z.string().nullable().optional(),
    scihub_enabled: z.boolean().nullable().optional(),
    use_tor: z.boolean().optional(),
    use_vpnsci: z.boolean().optional(),
    bibtex: z.boolean().optional(),
    strategy: z.string().nullable().optional(),
  };

  if (scenario === "extra_required") {
    downloadShape.unexpected_required = z.string();
  }
  if (scenario === "extra_optional") {
    downloadShape.future_optional = z.string().optional();
  }
  if (scenario === "compatible_required") {
    downloadShape.strategy = z.literal("legal_only");
    downloadShape.scihub_enabled = z.literal(false);
    downloadShape.output_dir = z.string();
  }
  if (scenario === "bad_field_type") {
    downloadShape.scihub_enabled = z.string().nullable().optional();
  }
  if (scenario === "strategy_rejects_legal_only") {
    downloadShape.strategy = z.literal("oa_only").optional();
  }
  if (scenario === "strategy_enum_institutional") {
    downloadShape.strategy = z
      .enum(["fastest", "legal_only", "institutional_only"])
      .nullable()
      .optional();
  }
  if (scenario === "strategy_enum_without_institutional") {
    downloadShape.strategy = z
      .enum(["fastest", "legal_only"])
      .nullable()
      .optional();
  }
  if (scenario === "scihub_requires_true") {
    downloadShape.scihub_enabled = z.literal(true).optional();
  }
  if (scenario.startsWith("batch")) {
    Object.assign(downloadShape, {
      batch_id: z.string().nullable().optional(),
      batch_index: z.number().int().nullable().optional(),
      batch_total: z.number().int().nullable().optional(),
      batch_done: z.number().int().nullable().optional(),
      batch_succeeded: z.number().int().nullable().optional(),
      batch_failed: z.number().int().nullable().optional(),
    });
  }
  if (scenario.startsWith("batch_browser")) {
    downloadShape.keep_browser = z.boolean().optional();
    server.registerTool("carsi_close_batch_browser", { description: "Close retained browser", inputSchema: {} }, async () => {
      log("call", { tool: "carsi_close_batch_browser" });
      return { content: [{ type: "text", text: '{"closed":true}' }] };
    });
  }

  if (scenario !== "missing_download") {
    server.registerTool(
      "carsi_download",
      {
        description: "Fake CARSI download tool",
        inputSchema: downloadShape,
      },
      async (args, extra) => {
        log("call", { tool: "carsi_download", arguments: args });

        if (scenario === "batch_browser_verification_timeout" && args.identifier.endsWith("/first")) {
          return { content: [{ type: "text", text: JSON.stringify({
            success: false, identifier: args.identifier, error_type: "download_timeout",
            artifacts: { state: "challenge_or_viewer_timeout" },
          }) }] };
        }

        if (scenario.startsWith("progress_")) {
          const token = extra._meta?.progressToken;
          const sendProgress = (progress, message, progressToken = token) =>
            extra.sendNotification({
              method: "notifications/progress",
              params: { progressToken, progress, message },
            });
          if (scenario === "progress_wrong_token") {
            await sendProgress(
              1,
              "carsi.stage:waiting_login",
              Number(token) + 100,
            );
          } else {
            for (const [revision, message] of [
              [1, "carsi.stage:opening_article"],
              [2, "carsi.stage:waiting_login"],
              [2, "carsi.stage:waiting_verification"],
              [3, "carsi.stage:waiting_login"],
              [4, "cookie=do-not-leak https://example.org/?token=private"],
              [5, "carsi.stage:unknown-cookie=do-not-leak"],
              [6, "carsi.stage:waiting_verification"],
              [7, "carsi.stage:fetching_pdf"],
            ]) {
              await sendProgress(revision, message);
            }
          }
          if (scenario === "progress_hang") await new Promise(() => {});
          if (scenario === "progress_heartbeat") {
            let revision = 8;
            setInterval(() => {
              void sendProgress(
                revision++,
                "carsi.stage:fetching_pdf",
              ).catch(() => {});
            }, 20);
            await new Promise(() => {});
          }
        }

        if (scenario === "download_hang" || scenario === "ignore_sigterm") {
          setInterval(() => {}, 60_000);
          await new Promise(() => {});
        }
        if (scenario === "download_is_error") {
          return {
            isError: true,
            content: [
              {
                type: "text",
                text: "token=do-not-leak https://publisher.example/file?secret=value",
              },
            ],
          };
        }
        if (scenario === "download_malformed") {
          return { content: [{ type: "text", text: "{not-json" }] };
        }
        if (scenario === "download_multiple_blocks") {
          return {
            content: [
              { type: "text", text: '{"success":true}' },
              { type: "text", text: '{"file":"/tmp/ambiguous.pdf"}' },
            ],
          };
        }
        if (scenario === "business_error") {
          return {
            content: [
              {
                type: "text",
                text: JSON.stringify({
                  success: false,
                  identifier: args.identifier,
                  doi: args.identifier,
                  reason:
                    "login required at https://publisher.example/login?token=do-not-leak",
                  error_type: "paywall",
                  action: "login_required",
                  agent_hint: "cookie=session-secret",
                }),
              },
            ],
          };
        }

        return {
          content: [
            {
              type: "text",
              text: JSON.stringify({
                success: true,
                identifier: args.identifier,
                doi: args.identifier,
                file: resultFile,
                source: resultSource,
                size_kb: 42,
              }),
            },
          ],
        };
      },
    );
  }

  if (scenario !== "missing_clear") {
    server.registerTool(
      "carsi_cache_clear",
      {
        description: "Fake CARSI cache clear tool",
        inputSchema:
          scenario === "clear_without_identifier"
            ? {}
            : scenario === "clear_identifier_required"
              ? { identifier: z.string() }
              : { identifier: z.string().nullable().optional() },
      },
      async (args) => {
        log("call", { tool: "carsi_cache_clear", arguments: args });

        if (scenario === "clear_hang") {
          await new Promise(() => {});
        }
        if (scenario === "clear_is_error") {
          return {
            isError: true,
            content: [
              { type: "text", text: "cache clear failed token=do-not-leak" },
            ],
          };
        }
        if (scenario === "clear_malformed") {
          return { content: [{ type: "text", text: '{"cleared":"all"}' }] };
        }

        return {
          content: [
            {
              type: "text",
              text: JSON.stringify({
                cleared: scenario === "clear_zero" ? 0 : 1,
              }),
            },
          ],
        };
      },
    );
  }

  if (scenario.startsWith("batch")) {
    server.registerTool(
      "carsi_batch_progress",
      {
        description: "Fake batch progress tool",
        inputSchema: {
          batch_id: z.string(),
          total: z.number().int(),
          done: z.number().int(),
          succeeded: z.number().int(),
          failed: z.number().int(),
          current: z.string().optional(),
          finished: z.boolean().optional(),
        },
      },
      async (args) => {
        log("call", { tool: "carsi_batch_progress", arguments: args });
        return { content: [{ type: "text", text: JSON.stringify({ updated: true }) }] };
      },
    );
  }

  const transport = new StdioServerTransport();
  await server.connect(transport);
}

async function runRawScenario(rawScenario) {
  let buffer = "";

  process.stdin.setEncoding("utf8");
  process.stdin.on("data", (chunk) => {
    buffer += chunk;
    while (buffer.includes("\n")) {
      const newline = buffer.indexOf("\n");
      const line = buffer.slice(0, newline).replace(/\r$/, "");
      buffer = buffer.slice(newline + 1);
      if (!line) continue;
      void handleRawMessage(JSON.parse(line));
    }
  });

  async function handleRawMessage(message) {
    if (message.method === "initialize") {
      if (rawScenario === "slow_handshake") await delay(300);
      if (rawScenario === "slow_initialize") await delay(700);
      writeResult(message.id, {
        protocolVersion: "2025-11-25",
        capabilities: { tools: { listChanged: false } },
        serverInfo: { name: "paper-search-carsi", version: "0.1.0" },
      });
      return;
    }

    if (message.method === "tools/list") {
      log("list", { cursor: message.params?.cursor ?? null });
      if (rawScenario === "tools_list_hang") return;
      if (rawScenario === "slow_handshake") await delay(300);
      if (
        rawScenario.startsWith("pagination") ||
        rawScenario === "paginated_tools"
      ) {
        const cursor = message.params?.cursor;
        if (rawScenario === "pagination_cycle") {
          writeResult(message.id, {
            tools: compatibleRawTools(),
            nextCursor: "repeat",
          });
        } else if (cursor === undefined) {
          writeResult(message.id, { tools: [], nextCursor: "download" });
        } else if (rawScenario === "pagination_hang") {
          return;
        } else if (cursor === "download") {
          writeResult(message.id, {
            tools: compatibleRawTools().slice(0, 1),
            nextCursor: "clear",
          });
        } else {
          writeResult(message.id, { tools: compatibleRawTools().slice(1) });
        }
        return;
      }
      if (rawScenario === "duplicate_tools") {
        writeResult(message.id, {
          tools: [...compatibleRawTools(), compatibleRawTools()[0]],
        });
        return;
      }
      writeResult(message.id, { tools: compatibleRawTools() }, () => {
        if (rawScenario === "exit_nonzero_after_list") {
          setTimeout(() => process.exit(17), 1);
        }
      });
    }
  }
}

function compatibleRawTools() {
  return [
    {
      name: "carsi_download",
      inputSchema: {
        type: "object",
        properties: {
          identifier: { type: "string" },
          output_dir: { anyOf: [{ type: "string" }, { type: "null" }] },
          scihub_enabled: {
            anyOf: [{ type: "boolean" }, { type: "null" }],
          },
          use_tor: { type: "boolean" },
          use_vpnsci: { type: "boolean" },
          bibtex: { type: "boolean" },
          strategy: { anyOf: [{ type: "string" }, { type: "null" }] },
        },
        required: ["identifier"],
      },
    },
    {
      name: "carsi_cache_clear",
      inputSchema: {
        type: "object",
        properties: {
          identifier: { anyOf: [{ type: "string" }, { type: "null" }] },
        },
      },
    },
  ];
}

function writeResult(id, result, callback) {
  process.stdout.write(
    `${JSON.stringify({ jsonrpc: "2.0", id, result })}\n`,
    callback,
  );
}

function delay(milliseconds) {
  return new Promise((resolvePromise) =>
    setTimeout(resolvePromise, milliseconds),
  );
}
