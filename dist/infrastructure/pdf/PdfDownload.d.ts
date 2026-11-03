export interface PdfDownloadOptions {
    headers?: Record<string, string>;
    /** Overall request timeout; defaults to TIMEOUTS.DOWNLOAD. */
    timeoutMs?: number;
}
export declare function safeFilename(value: string, fallback?: string): string;
export declare function isPdfBuffer(buffer: Buffer, contentType?: string): boolean;
/**
 * Validate a completed PDF using the same strong boundary applied to delegated
 * downloads: plausible size, an exact `%PDF-` header, and a trailing `%%EOF`
 * marker. This validates bytes on disk rather than trusting a URL or response
 * content type.
 */
export declare function isValidPdfFile(filePath: string, minBytes?: number): boolean;
export declare function downloadPdfFromUrl(pdfUrl: string, savePath: string, filenameHint: string, options?: PdfDownloadOptions): Promise<string>;
//# sourceMappingURL=PdfDownload.d.ts.map