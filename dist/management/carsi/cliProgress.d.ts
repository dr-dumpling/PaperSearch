import type { CarsiBackend } from "../../capabilities/pdf-discovery/carsi/index.js";
/**
 * The CLI's backend: a download can be stopped with Ctrl-C and tells its steps
 * on stderr; every other method of the backend is passed on as it is (each one
 * by name: a method left out here is gone for the CLI, see the wrapper test).
 */
export declare function withCliCarsiProgress(backend: CarsiBackend): CarsiBackend;
//# sourceMappingURL=cliProgress.d.ts.map