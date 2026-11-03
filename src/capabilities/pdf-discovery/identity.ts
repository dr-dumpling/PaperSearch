import type { PdfIdentityStatus } from "../../infrastructure/pdf/PdfIdentity.js";
import type { DownloadTierResult } from "./DownloadTier.js";

/**
 * The error result for a saved PDF that is not verifiably this article; null when
 * verified, or when a scan without text came from a URL naming the DOI ("source").
 */
export function identityRejection(
  identity: PdfIdentityStatus,
  path: string,
): DownloadTierResult | null {
  if (identity === "verified" || identity === "source") return null;
  const code =
    identity === "mismatch"
      ? "pdf_identity_mismatch"
      : identity === "unreadable"
        ? "invalid_pdf"
        : "pdf_identity_unverified";
  return {
    status: "error",
    code,
    message:
      identity === "mismatch"
        ? "下载文件的论文 DOI 与目标不符，已拦截并保留文件供核查。"
        : identity === "unreadable"
          ? "下载文件无法解析为可读 PDF，已保留文件供核查。"
          : "下载文件的论文身份尚未确认，请人工核查；未计为下载成功。",
    review: { path, reason: code },
  };
}
