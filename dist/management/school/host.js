import { spawn } from "node:child_process";
import { createHash } from "node:crypto";
import * as fs from "node:fs";
import { createReadStream, createWriteStream, existsSync } from "node:fs";
import { homedir } from "node:os";
import { dirname } from "node:path";
import { Readable } from "node:stream";
import { pipeline } from "node:stream/promises";
/** The real machine: processes, downloads and the user's answers on the terminal. */
export function createNodeHost(prompt) {
    return {
        platform: process.platform,
        arch: process.arch,
        home: homedir(),
        env: process.env,
        run: (command, args, options = {}) => new Promise((resolve, reject) => {
            const child = spawn(command, args, {
                env: { ...process.env, ...(options.env ?? {}) },
                stdio: ["ignore", "pipe", "pipe"],
                windowsHide: true,
            });
            let stdout = "";
            let stderr = "";
            child.stdout.on("data", (chunk) => {
                stdout += chunk.toString();
                if (options.echo)
                    process.stderr.write(chunk);
            });
            child.stderr.on("data", (chunk) => {
                stderr += chunk.toString();
                if (options.echo)
                    process.stderr.write(chunk);
            });
            child.on("error", reject);
            child.on("close", (code) => resolve({ code: code ?? 1, stdout, stderr }));
        }),
        async download(url, file) {
            const response = await fetch(url, { redirect: "follow" });
            if (!response.ok || !response.body)
                throw new Error(`下载失败：${url}（HTTP ${response.status}）`);
            await pipeline(Readable.fromWeb(response.body), createWriteStream(file));
        },
        sha256: (file) => new Promise((resolve, reject) => {
            const hash = createHash("sha256");
            createReadStream(file).on("data", (chunk) => hash.update(chunk)).on("error", reject)
                .on("end", () => resolve(hash.digest("hex")));
        }),
        freeBytes(path) {
            let existing = path;
            while (!existsSync(existing) && dirname(existing) !== existing)
                existing = dirname(existing);
            // statfs arrived in Node 18.15; on an older Node the space is not checked.
            if (typeof fs.statfsSync !== "function")
                return Number.POSITIVE_INFINITY;
            const stats = fs.statfsSync(existing);
            return stats.bavail * stats.bsize;
        },
        async confirm(question) {
            return /^y(?:es)?$/i.test((await prompt(question)).trim());
        },
        ask: (question) => prompt(question),
        log: (line) => process.stderr.write(`${line}\n`),
    };
}
//# sourceMappingURL=host.js.map