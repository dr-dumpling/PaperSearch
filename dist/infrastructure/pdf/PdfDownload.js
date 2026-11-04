import axios from 'axios';
import { normalizeArxivId } from '../arxiv.js';
import * as fs from 'fs';
import * as path from 'path';
import { Readable } from 'stream';
import { TIMEOUTS, USER_AGENT } from '../../config/constants.js';
const MIN_PDF_SIZE_BYTES = 10_000;
const PDF_TAIL_BYTES = 2_048;
export function safeFilename(value, fallback = 'paper') {
    const safe = value.replace(/[^a-zA-Z0-9._-]+/g, '_').replace(/^[_\-.]+|[_\-.]+$/g, '');
    return (safe || fallback).slice(0, 120);
}
export function isPdfBuffer(buffer, contentType = '') {
    return contentType.toLowerCase().includes('pdf') || buffer.subarray(0, 4).toString() === '%PDF';
}
/**
 * Validate a completed PDF using the same strong boundary applied to delegated
 * downloads: plausible size, an exact `%PDF-` header, and a trailing `%%EOF`
 * marker. This validates bytes on disk rather than trusting a URL or response
 * content type.
 */
export function isValidPdfFile(filePath, minBytes = MIN_PDF_SIZE_BYTES) {
    let descriptor;
    try {
        const stat = fs.statSync(filePath);
        if (!stat.isFile() || stat.size < minBytes)
            return false;
        descriptor = fs.openSync(filePath, 'r');
        const head = Buffer.alloc(5);
        if (fs.readSync(descriptor, head, 0, head.length, 0) !== head.length)
            return false;
        if (head.toString('latin1') !== '%PDF-')
            return false;
        const tailLength = Math.min(PDF_TAIL_BYTES, stat.size);
        const tail = Buffer.alloc(tailLength);
        fs.readSync(descriptor, tail, 0, tailLength, stat.size - tailLength);
        return tail.includes(Buffer.from('%%EOF', 'latin1'));
    }
    catch {
        return false;
    }
    finally {
        if (descriptor !== undefined) {
            try {
                fs.closeSync(descriptor);
            }
            catch {
                // Validation is best-effort; a close failure does not make bad bytes valid.
            }
        }
    }
}
async function getStreamSnippet(stream, maxBytes = 240) {
    return new Promise((resolve) => {
        let buffer = Buffer.alloc(0);
        const onData = (chunk) => {
            buffer = Buffer.concat([buffer, chunk]);
            if (buffer.length >= maxBytes) {
                cleanup();
                stream.destroy?.();
            }
        };
        const cleanup = () => {
            if (typeof stream.off === 'function') {
                stream.off('data', onData);
            }
        };
        stream.on('data', onData);
        stream.on('end', () => {
            cleanup();
            resolve(buffer.subarray(0, maxBytes).toString('utf8').replace(/\s+/g, ' ').trim());
        });
        stream.on('close', () => {
            cleanup();
            resolve(buffer.subarray(0, maxBytes).toString('utf8').replace(/\s+/g, ' ').trim());
        });
        stream.on('error', () => {
            cleanup();
            resolve(buffer.subarray(0, maxBytes).toString('utf8').replace(/\s+/g, ' ').trim());
        });
    });
}
function removePartialDownload(filePath) {
    try {
        fs.rmSync(filePath, { force: true });
    }
    catch {
        // Best-effort cleanup only; preserve the original download error.
    }
}
export async function downloadPdfFromUrl(pdfUrl, savePath, filenameHint, options = {}) {
    if (!pdfUrl) {
        throw new Error('Missing PDF URL');
    }
    if (pdfUrl.startsWith('ftp://')) {
        throw new Error('FTP PDF links are not supported by the Node downloader.');
    }
    if (!options.allowPreprint && normalizeArxivId(pdfUrl)) {
        throw new Error('arXiv PDF deferred until published-version routes finish');
    }
    fs.mkdirSync(savePath, { recursive: true });
    const outputPath = path.join(savePath, `${safeFilename(filenameHint)}.pdf`);
    let response;
    try {
        response = await axios.get(pdfUrl, {
            responseType: 'stream',
            timeout: options.timeoutMs ?? TIMEOUTS.DOWNLOAD,
            maxRedirects: 5,
            beforeRedirect: (redirect) => {
                if (!options.allowPreprint && normalizeArxivId(`${redirect.protocol}//${redirect.hostname}${redirect.path}`)) {
                    throw new Error('arXiv PDF deferred until published-version routes finish');
                }
            },
            headers: {
                'User-Agent': USER_AGENT,
                Accept: 'application/pdf,*/*',
                ...(options.headers || {})
            },
            validateStatus: status => status < 500
        });
    }
    catch (error) {
        const status = Number(error?.response?.status) || undefined;
        const code = typeof error?.code === 'string' && /^[A-Z0-9_]+$/.test(error.code)
            ? error.code
            : undefined;
        const detail = status ? ` with HTTP ${status}` : code ? ` (${code})` : '';
        throw new Error(`PDF download request failed${detail}.`);
    }
    const finalUrl = response.request?.res?.responseUrl;
    if (!options.allowPreprint && finalUrl && normalizeArxivId(finalUrl)) {
        response.data?.destroy?.();
        throw new Error('arXiv PDF deferred until published-version routes finish');
    }
    if (response.status >= 400) {
        let errStream = response.data;
        if (!(errStream instanceof Readable) && !(errStream && typeof errStream.on === 'function')) {
            errStream = Readable.from(Buffer.isBuffer(errStream) ? errStream : Buffer.from(errStream || ''));
        }
        const errorSnippet = await getStreamSnippet(errStream);
        const cfHeader = response.headers['cf-mitigated'];
        const challenge = !!cfHeader || /cloudflare|challenge|just a moment/i.test(errorSnippet);
        const reason = challenge ? 'provider returned an HTML anti-bot challenge instead of a PDF' : 'provider refused the request';
        throw new Error(`PDF download failed with HTTP ${response.status}: ${reason}`);
    }
    return new Promise((resolve, reject) => {
        let reader = response.data;
        if (!(reader instanceof Readable) && !(reader && typeof reader.on === 'function')) {
            reader = Readable.from(Buffer.isBuffer(reader) ? reader : Buffer.from(reader || ''));
        }
        let writer;
        let checked = false;
        let settled = false;
        let readerEnded = false;
        let totalBytes = 0;
        const contentLengthHeader = response.headers['content-length'];
        const expectedLength = contentLengthHeader ? parseInt(String(contentLengthHeader), 10) : 0;
        const fail = (err) => {
            if (settled)
                return;
            settled = true;
            if (typeof reader.destroy === 'function')
                reader.destroy();
            if (writer) {
                writer.once('close', () => {
                    removePartialDownload(outputPath);
                    reject(err);
                });
                writer.destroy();
                return;
            }
            removePartialDownload(outputPath);
            reject(err);
        };
        const ensureWriter = () => {
            if (writer)
                return writer;
            writer = fs.createWriteStream(outputPath);
            writer.on('error', fail);
            writer.on('drain', () => {
                if (typeof reader.resume === 'function')
                    reader.resume();
            });
            writer.on('finish', () => {
                if (settled)
                    return;
                if (expectedLength && totalBytes !== expectedLength) {
                    settled = true;
                    writer?.once('close', () => {
                        removePartialDownload(outputPath);
                        reject(new Error(`PDF download incomplete: received ${totalBytes} bytes, expected ${expectedLength} bytes`));
                    });
                    return;
                }
                if (!isValidPdfFile(outputPath)) {
                    settled = true;
                    writer?.once('close', () => {
                        removePartialDownload(outputPath);
                        reject(new Error('Downloaded file failed strict PDF validation (%PDF- header, %%EOF trailer, or minimum size).'));
                    });
                    return;
                }
                settled = true;
                resolve(outputPath);
            });
            return writer;
        };
        reader.on('data', (chunk) => {
            totalBytes += chunk.length;
            if (!checked) {
                checked = true;
                const contentType = String(response.headers['content-type'] || '').toLowerCase();
                const isPdf = contentType.includes('pdf') || chunk.subarray(0, 4).toString() === '%PDF';
                if (!isPdf) {
                    const snippet = chunk.subarray(0, 240).toString('utf8').replace(/\s+/g, ' ').trim();
                    const cfHeader = response.headers['cf-mitigated'];
                    const challenge = !!cfHeader || /cloudflare|challenge|preparing to download|proof-of-work|<!doctype html/i.test(snippet);
                    const reason = challenge
                        ? 'the provider returned an HTML challenge page instead of a PDF'
                        : `content-type was ${contentType || 'unknown'}`;
                    fail(new Error(`Resolved URL did not return a PDF (${reason}).`));
                    return;
                }
            }
            if (!ensureWriter().write(chunk)) {
                if (typeof reader.pause === 'function')
                    reader.pause();
            }
        });
        reader.on('end', () => {
            readerEnded = true;
            if (settled)
                return;
            if (!checked) {
                fail(new Error('Resolved URL did not return a PDF (empty response).'));
                return;
            }
            writer?.end();
        });
        reader.on('aborted', () => {
            fail(new Error('PDF download stream was aborted before completion.'));
        });
        reader.on('close', () => {
            if (!readerEnded && !settled) {
                fail(new Error('PDF download stream closed before completion.'));
            }
        });
        reader.on('error', (err) => {
            const code = typeof err?.code === 'string' && /^[A-Z0-9_]+$/.test(err.code)
                ? ` (${err.code})`
                : '';
            fail(new Error(`PDF download stream failed${code}.`));
        });
    });
}
//# sourceMappingURL=PdfDownload.js.map