import axios from "axios";
import type { DownloadWithFallbackResult } from "../types.js";

/**
 * A batch that loses the computer's network waits for it, then does the paper again (user,
 * 2026-11-17: the Mac's Wi-Fi was gone for 100 s at 05:00, and in that time 40 papers ended,
 * 2 s each, as "DOI 查不到").
 */

/** The backend's word that neither doi.org nor PubMed answered (bridge._offline). */
export const NETWORK_LOST_CODE = "network_unavailable";

/** A connection that found no route or no name server: a sign to look at the network. */
const NETWORK_ERROR = /\b(ENOTFOUND|EAI_AGAIN|ENETUNREACH|ENETDOWN|EHOSTUNREACH)\b|fetch failed|getaddrinfo/i;

/** How often a batch without network looks again. */
export const NETWORK_POLL_MS = 15_000;

/** A paper done again at most this often for the network (a site of its own failing is no network loss). */
const NETWORK_AGAIN = 3;

/** doi.org or PubMed's E-utilities answering anything, any status: the network is up. */
export async function networkReachable(): Promise<boolean> {
  const answers = await Promise.all(["https://doi.org/", "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/einfo.fcgi"]
    .map((url) => axios.head(url, { timeout: 8_000, maxRedirects: 0, validateStatus: () => true })
      .then(() => true, () => false)));
  return answers.some(Boolean);
}

/**
 * "lost": the backend found neither doi.org nor PubMed; "suspect": a stage could not
 * reach its host (one site's trouble or the network's, the network to be looked at).
 */
export function networkSigns(result: DownloadWithFallbackResult): "lost" | "suspect" | undefined {
  const codes = [...result.attempts.map((attempt) => attempt.code),
    ...(result.supplements ?? []).map((file) => file.reason)];
  if (codes.includes(NETWORK_LOST_CODE)) return "lost";
  return result.attempts.some((attempt) => attempt.status === "error" && NETWORK_ERROR.test(attempt.message ?? ""))
    ? "suspect" : undefined;
}

export interface NetworkWatch {
  log: (line: string) => void;
  pause: (ms: number) => Promise<void>;
  online: () => Promise<boolean>;
  /** The window's line while the batch waits ("" when the network is back). */
  notice?: (phase: string) => unknown;
}

const WAIT_PHASE = "网络断了，等网络恢复后接着下";

/** Waits as long as the network is gone, said once when it goes and once when it is back. */
async function waitForNetwork(watch: NetworkWatch): Promise<void> {
  const since = Date.now();
  watch.log("[批量] 网络断了（doi.org 和 PubMed 都连不上）：等网络恢复后重下这一篇，后面的篇目也先等着");
  await watch.notice?.(WAIT_PHASE);
  while (!(await watch.online())) await watch.pause(NETWORK_POLL_MS);
  const minutes = Math.max(1, Math.round((Date.now() - since) / 60_000));
  watch.log(`[批量] 网络恢复了（断了约 ${minutes} 分钟），重下这一篇`);
  await watch.notice?.("");
}

/**
 * ``run`` again after the network comes back, when its result shows a network loss: a
 * stage that could not reach its host, the network then found down; or the backend's own
 * word, which is done again even if the network is back by the time it is looked at.
 */
export async function pastNetworkLoss(
  run: () => Promise<DownloadWithFallbackResult>,
  watch: NetworkWatch,
): Promise<DownloadWithFallbackResult> {
  let result = await run();
  for (let again = 0; again < NETWORK_AGAIN; again += 1) {
    const signs = networkSigns(result);
    if (!signs) break;
    if (!(await watch.online())) await waitForNetwork(watch);
    else if (signs === "suspect") break;
    else watch.log("[批量] 刚才网络断过（doi.org 和 PubMed 都没连上），重下这一篇");
    result = await run();
  }
  return result;
}
