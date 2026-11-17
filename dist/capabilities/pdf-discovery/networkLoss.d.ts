import type { DownloadWithFallbackResult } from "./types.js";
/**
 * A batch that loses the computer's network waits for it, then does the paper again (user,
 * 2026-11-17: the Mac's Wi-Fi was gone for 100 s at 05:00, and in that time 40 papers ended,
 * 2 s each, as "DOI 暂时查不到").
 */
/** The backend's word that neither doi.org nor PubMed answered (bridge._offline). */
export declare const NETWORK_LOST_CODE = "network_unavailable";
/** How often a batch without network looks again. */
export declare const NETWORK_POLL_MS = 15000;
/** doi.org or PubMed's E-utilities answering anything, any status: the network is up. */
export declare function networkReachable(): Promise<boolean>;
/**
 * "lost": the backend found neither doi.org nor PubMed; "suspect": a stage could not
 * reach its host (one site's trouble or the network's, the network to be looked at).
 */
export declare function networkSigns(result: DownloadWithFallbackResult): "lost" | "suspect" | undefined;
export interface NetworkWatch {
    log: (line: string) => void;
    pause: (ms: number) => Promise<void>;
    online: () => Promise<boolean>;
    /** The window's line while the batch waits ("" when the network is back). */
    notice?: (phase: string) => unknown;
}
/**
 * ``run`` again after the network comes back, when its result shows a network loss: a
 * stage that could not reach its host, the network then found down; or the backend's own
 * word, which is done again even if the network is back by the time it is looked at.
 */
export declare function pastNetworkLoss(run: () => Promise<DownloadWithFallbackResult>, watch: NetworkWatch): Promise<DownloadWithFallbackResult>;
//# sourceMappingURL=networkLoss.d.ts.map