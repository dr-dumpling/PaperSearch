/**
 * - verified: the PDF names this article;
 * - source: a scan without readable text, fetched from a URL that names the DOI
 *   (only when a source URL is given);
 * - mismatch: it names other articles and not this one;
 * - unverified: no decision (kept for review);
 * - unreadable: not a parseable PDF.
 */
export type PdfIdentityStatus = "verified" | "source" | "mismatch" | "unverified" | "unreadable";
type TitleEvidence = "strong" | "single" | null;
export interface IdentityEvidence {
    /** An attachment or a notice about an article. */
    notArticle: boolean;
    doi: boolean;
    title: TitleEvidence;
    otherDois: string[];
}
/** What the first pages show; null without any text. */
export declare function identityEvidence(firstPages: string, identifier: string, title?: string): IdentityEvidence | null;
/**
 * The decision on the text of the first pages. `source` is the URL the PDF came
 * from: the only evidence for a scan without a text layer ("source"), when
 * nothing printed points elsewhere (a notice, an attachment, another DOI).
 */
export declare function assessPdfIdentity(firstPages: string, identifier: string, title?: string, source?: string): PdfIdentityStatus;
/** Isolate pdf-parse diagnostics and CPU work from CLI JSON output. */
export declare function verifyPdfIdentity(filePath: string, identifier: string, title?: string, source?: string): Promise<PdfIdentityStatus>;
export {};
//# sourceMappingURL=PdfIdentity.d.ts.map