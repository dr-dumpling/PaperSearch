/**
 * Where an open-access PDF URL may be fetched from.
 *
 * "browser": the host refuses plain HTTP PDF downloads behind bot protection
 * (Cloudflare, Akamai, proof-of-work pages; checked 2026-10). Its copies are
 * left to the browser stage (entitled access), which reads them like a reader.
 * "excluded": not used as a source at all (arXiv, maintainer decision).
 */
const BROWSER_ONLY_HOSTS = [
  "wiley.com",
  "sciencedirect.com",
  "elsevier.com",
  "cell.com",
  "thelancet.com",
  "springer.com",
  "biomedcentral.com",
  "mdpi.com",
  "medrxiv.org",
  "core.ac.uk",
  "ncbi.nlm.nih.gov",
  "europepmc.org",
];
const EXCLUDED_HOSTS = ["arxiv.org"];

export type OaHostPolicy = "http" | "browser" | "excluded";

export function oaHostPolicy(url: string): OaHostPolicy {
  let host = "";
  try {
    host = new URL(url).hostname.toLowerCase();
  } catch {
    return "excluded";
  }
  const within = (domain: string) => host === domain || host.endsWith(`.${domain}`);
  if (EXCLUDED_HOSTS.some(within)) return "excluded";
  return BROWSER_ONLY_HOSTS.some(within) ? "browser" : "http";
}
