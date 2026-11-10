import type { CarsiBackend } from "../../capabilities/pdf-discovery/carsi/index.js";
import { type InstallContext, type InstallerHost } from "./installer.js";
export type AutoUpdateOutcome = "off" | "not_needed" | "busy" | "updated" | "failed";
/**
 * After a PaperSearch upgrade, the extension is brought up to it before its
 * first use (`carsi update`), as the Skill is synced after an upgrade;
 * PAPER_SEARCH_CARSI_AUTO_UPDATE=false turns this off. Only the extension this
 * PaperSearch installed and uses: another backend (a developer's) is left alone.
 * ``lock`` takes the download lock and answers how to release it (it throws
 * EEXIST while another PaperSearch holds it), so a download running elsewhere
 * keeps its backend and two upgrades never install at once. Every step is said
 * on stderr; a failed update leaves the old backend for this download.
 */
export declare function autoUpdateCarsi(host: InstallerHost, context: InstallContext, lock: () => () => void): Promise<AutoUpdateOutcome>;
/**
 * ``backend`` with ``update`` run once, before the first call that starts the
 * backend process: a probe, a download, or a batch progress or papers report (a
 * batch session itself starts nothing). Calls made meanwhile wait for the same update.
 */
export declare function withAutoUpdate(backend: CarsiBackend, update: () => Promise<unknown>): CarsiBackend;
//# sourceMappingURL=autoUpdate.d.ts.map