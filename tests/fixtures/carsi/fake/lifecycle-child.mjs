import { appendFileSync } from "node:fs";

const logIndex = process.argv.indexOf("--log");
const logPath = logIndex >= 0 ? process.argv[logIndex + 1] : undefined;

if (logPath) {
  appendFileSync(
    logPath,
    `${JSON.stringify({
      event: "start",
      pid: process.pid,
      dataDir: process.env.CARSI_DATA_DIR || null,
    })}\n`,
    "utf8",
  );
}

process.on("SIGTERM", () => {
  if (logPath) {
    appendFileSync(
      logPath,
      `${JSON.stringify({ event: "signal", signal: "SIGTERM" })}\n`,
      "utf8",
    );
  }
});

setInterval(() => {}, 60_000);
