import { spawn } from "node:child_process";
import { resolve } from "node:path";
import { selectFailures } from "./index.js";
/** Offline backend command: no readiness probe, profile, login or download. */
export async function exportFailureReport(options) {
    const selected = selectFailures(options.root, options.query, { forExport: true });
    if (!selected.papers.length)
        throw new Error("没有匹配的机构下载失败记录。");
    if (selected.papers.length > 100)
        throw new Error("单包最多 100 篇，请用 --run 或 --doi 缩小范围。");
    if (!options.output.toLowerCase().endsWith(".zip"))
        throw new Error("导出路径须以 .zip 结尾。");
    const input = JSON.stringify({ schemaVersion: 1, version: options.version, papers: selected.papers });
    if (Buffer.byteLength(input) > 8 * 1024 * 1024)
        throw new Error("记录超过 8 MiB，请用 --run 或 --doi 缩小范围。");
    return new Promise((resolveResult, reject) => {
        const child = spawn(options.command, ["report-export", "--output", resolve(options.output)], {
            stdio: ["pipe", "pipe", "pipe"], windowsHide: true,
            env: Object.fromEntries(Object.entries(process.env).filter(([key]) => /^(PATH|HOME|USERPROFILE|SYSTEMROOT|WINDIR|TEMP|TMP|TMPDIR|LANG|LC_ALL|XDG_DATA_HOME|XDG_CONFIG_HOME|CARSI_DATA_DIR|CARSI_PYTHON|PYTHONPATH|OPENBLAS_NUM_THREADS)$/i.test(key))),
        });
        const chunks = [];
        let size = 0;
        let problem;
        const stop = (message) => { problem ??= new Error(message); child.kill(); };
        const timer = setTimeout(() => stop("失败记录导出超时（60 秒），请缩小范围后重试。"), 60_000);
        child.stdout.on("data", (chunk) => {
            size += chunk.length;
            if (size > 64 * 1024)
                stop("后端导出输出超过限制。");
            else
                chunks.push(chunk);
        });
        // Do not echo backend diagnostics, which can contain private source paths.
        child.stderr.on("data", (chunk) => {
            size += chunk.length;
            if (size > 64 * 1024)
                stop("后端导出输出超过限制。");
        });
        child.on("error", () => {
            clearTimeout(timer);
            reject(new Error("无法启动机构下载扩展，请运行 paper-search carsi status 检查安装。"));
        });
        child.stdin.on("error", () => { });
        child.on("close", (code) => {
            clearTimeout(timer);
            if (problem)
                return reject(problem);
            let data;
            try {
                data = JSON.parse(Buffer.concat(chunks).toString("utf8"));
            }
            catch {
                return reject(new Error("机构下载扩展未返回导出结果，请更新支持 report-export 的扩展。"));
            }
            if (code !== 0 || data.ok !== true) {
                // Only stable codes, never arbitrary exception text from an older backend.
                const code = typeof data.error === "string" ? data.error.split(";")[0] : "";
                const known = new Set(["invalid_export_request", "export_request_too_large", "no_matching_failures",
                    "too_many_failures", "export_path_must_end_in_zip", "export_target_exists", "source_size_limit",
                    "package_size_limit", "export_permission_denied", "export_io_or_input_error"]);
                const error = known.has(code) ? code : "export_failed";
                return reject(new Error(`失败记录导出未完成：${error}`));
            }
            if (data.schemaVersion !== 1 || data.path !== resolve(options.output) || data.reviewRequired !== true ||
                ![data.papers, data.files, data.bytes, data.incompletePapers].every((v) => Number.isInteger(v) && Number(v) >= 0)) {
                return reject(new Error("机构下载扩展返回了不兼容的导出结果。"));
            }
            resolveResult(data);
        });
        child.stdin.end(input);
    });
}
//# sourceMappingURL=exportReport.js.map