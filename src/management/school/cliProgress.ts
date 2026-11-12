import type { SchoolBackend } from "../../capabilities/pdf-discovery/school/index.js";

/**
 * The CLI's backend: a download can be stopped with Ctrl-C and tells its steps
 * on stderr; every other method of the backend is passed on as it is (each one
 * by name: a method left out here is gone for the CLI, see the wrapper test).
 */
export function withCliSchoolProgress(backend: SchoolBackend): SchoolBackend {
  const withBatchSession = backend.withBatchSession?.bind(backend);
  return {
    probe: (signal) => backend.probe(signal),
    withBatchSession: withBatchSession && ((run) =>
      withBatchSession((scoped) => run(withCliSchoolProgress(scoped)))),
    reportBatchProgress: async (update, signal) =>
      (await backend.reportBatchProgress?.(update, signal)) ?? false,
    reportBatchPapers: async (update, last) =>
      (await backend.reportBatchPapers?.(update, last)) ?? false,
    downloadLegalDoi: async (request) => {
      const controller = new AbortController();
      const cancel = () => controller.abort();
      process.once("SIGINT", cancel);
      process.once("SIGTERM", cancel);
      if (process.stderr.isTTY) {
        process.stderr.write(
          "正在通过学校订阅获取全文；若浏览器要求登录或安全验证，请在窗口中完成。\n",
        );
      }
      try {
        return await backend.downloadLegalDoi({
          ...request,
          signal: controller.signal,
          onProgress: (progress) => {
            process.stderr.write(`[学校订阅] ${progress.message}\n`);
            request.onProgress?.(progress);
          },
        });
      } finally {
        process.removeListener("SIGINT", cancel);
        process.removeListener("SIGTERM", cancel);
      }
    },
  };
}
