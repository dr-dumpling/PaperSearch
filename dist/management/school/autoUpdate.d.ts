import type { SchoolBackend } from "../../capabilities/pdf-discovery/school/index.js";
import { type InstallContext, type InstallerHost } from "./installer.js";
export type AutoUpdateOutcome = "off" | "not_needed" | "busy" | "updated" | "failed";
/**
 * After a PaperSearch upgrade, the extension is brought up to it before its
 * first use (`school update`), as the Skill is synced after an upgrade;
 * PAPER_SEARCH_SCHOOL_AUTO_UPDATE=false turns this off. Only the extension this
 * PaperSearch installed and uses: another backend (a developer's) is left alone.
 * ``lock`` takes the download lock and answers how to release it (it throws
 * EEXIST while another PaperSearch holds it), so a download running elsewhere
 * keeps its backend and two upgrades never install at once. Every step is said
 * on stderr; a failed update leaves the old backend for this download.
 */
export declare function autoUpdateSchool(host: InstallerHost, context: InstallContext, lock: () => () => void): Promise<AutoUpdateOutcome>;
/**
 * ``backend`` with ``update`` run once, before the first call that starts the
 * backend process: a probe, a download, or a batch progress or papers report (a
 * batch session itself starts nothing). Calls made meanwhile wait for the same update.
 */
export declare function withAutoUpdate(backend: SchoolBackend, update: () => Promise<unknown>): SchoolBackend;
//# sourceMappingURL=autoUpdate.d.ts.map