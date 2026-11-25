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

/**
 * The backend's word that the publisher's site did not answer (the connection dropped, or opening it timed out) while
 * the network is up: the paper is done once more after ``SITE_AGAIN_MS``, whatever 失败后自动重试 says (user,
 * 2026-11-24: 2 of some 1300 papers of the publisher sweep, Springer Publishing's and Cambridge's, a few seconds' trouble).
 * Only the paper's own stages: a supplementary file not answered is not worth the paper again.
 */
export const SITE_UNREACHABLE_CODE = "publisher_unreachable";
export const SITE_AGAIN_MS = 15_000;

/** doi.org or PubMed's E-utilities answering anything, any status: the network is up. */
export async function networkReachable(): Promise<boolean> {
  const answers = await Promise.all(["https://doi.org/", "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/einfo.fcgi"]
    .map((url) => axios.head(url, { timeout: 8_000, maxRedirects: 0, validateStatus: () => true })
      .then(() => true, () => false)));
  return answers.some(Boolean);
}

/**
 * "lost": the backend found neither doi.org nor PubMed; "suspect": a stage could not
 * reach its host (one site's trouble or the network's, the network to be looked at);
 * "site": the publisher's site did not answer the paper's own stage (``SITE_UNREACHABLE_CODE``).
 */
export function networkSigns(result: DownloadWithFallbackResult): "lost" | "suspect" | "site" | undefined {
  const codes = [...result.attempts.map((attempt) => attempt.code),
    ...(result.supplements ?? []).map((file) => file.reason)];
  if (codes.includes(NETWORK_LOST_CODE)) return "lost";
  if (result.attempts.some((attempt) => attempt.status === "error" && NETWORK_ERROR.test(attempt.message ?? ""))) {
    return "suspect";
  }
  return result.status !== "ok" && result.attempts.some((attempt) => attempt.status === "error" && attempt.code === SITE_UNREACHABLE_CODE)
    ? "site" : undefined;
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
  let siteAgain = false;
  for (let again = 0; again < NETWORK_AGAIN; again += 1) {
    const signs = networkSigns(result);
    if (!signs) break;
    if (!(await watch.online())) await waitForNetwork(watch);
    else if (signs === "suspect") break;
    else if (signs === "site") {
      // Once a paper: a site still not answering after the wait is the site's, its reason kept.
      if (siteAgain) break;
      siteAgain = true;
      watch.log(`[批量] 出版社网站没有应答（连接被断开或打开超时）：${SITE_AGAIN_MS / 1000} 秒后重下这一篇`);
      await watch.pause(SITE_AGAIN_MS);
    } else watch.log("[批量] 刚才网络断过（doi.org 和 PubMed 都没连上），重下这一篇");
    result = await run();
  }
  return result;
}
