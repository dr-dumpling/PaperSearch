import axios from 'axios';
import * as fs from 'fs';
import * as os from 'os';
import * as path from 'path';
import { PassThrough } from 'stream';
import { afterEach, describe, expect, it, jest } from '@jest/globals';
import {
  downloadPdfFromUrl,
  isPdfBuffer,
  isValidPdfFile
} from '../../src/infrastructure/pdf/PdfDownload.js';

function pdfBuffer(size = 10_000, options: { header?: string; eof?: boolean } = {}): Buffer {
  const buffer = Buffer.alloc(size, 0x20);
  buffer.write(options.header ?? '%PDF-1.7\n', 0, 'latin1');
  if (options.eof !== false && size >= 7) {
    buffer.write('\n%%EOF\n', size - 7, 'latin1');
  }
  return buffer;
}

describe('PdfDownload', () => {
  const tempDirs: string[] = [];

  afterEach(() => {
    jest.restoreAllMocks();
    for (const dir of tempDirs.splice(0)) {
      fs.rmSync(dir, { recursive: true, force: true });
    }
  });

  function tempDir(): string {
    const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'pdf-download-test-'));
    tempDirs.push(dir);
    return dir;
  }

  function mockDownload(data: Buffer, contentType = 'application/pdf') {
    return jest.spyOn(axios, 'get').mockResolvedValue({
      status: 200,
      headers: {
        'content-type': contentType,
        'content-length': String(data.length)
      },
      data
    } as any);
  }

  it('defers arXiv requests and redirects unless the final tier opts in', async () => {
    const get = mockDownload(pdfBuffer());
    const dir = tempDir();
    await expect(downloadPdfFromUrl('https://arxiv.org/pdf/1706.03762', dir, 'preprint')).rejects.toThrow('deferred');
    expect(get).not.toHaveBeenCalled();
    const saved = await downloadPdfFromUrl('https://arxiv.org/pdf/1706.03762', dir, 'allowed', {allowPreprint: true});
    expect(isValidPdfFile(saved)).toBe(true);
    await downloadPdfFromUrl('https://repo.example/paper.pdf', dir, 'formal');
    const config = get.mock.calls.at(-1)![1]!;
    expect(() => config.beforeRedirect!({protocol: 'https:', hostname: 'arxiv.org', path: '/pdf/1706.03762'} as any, {} as any, {} as any)).toThrow('deferred');
  });

  it('recognizes an initial PDF signature without treating it as full-file validation', () => {
    expect(isPdfBuffer(Buffer.from('%PDF-1.7'), 'application/octet-stream')).toBe(true);
    expect(isPdfBuffer(Buffer.from('<html>'), 'text/html')).toBe(false);
  });

  it('accepts a completed file only at or above the minimum size with header and EOF', () => {
    const dir = tempDir();
    const tooSmall = path.join(dir, 'too-small.pdf');
    const minimum = path.join(dir, 'minimum.pdf');
    fs.writeFileSync(tooSmall, pdfBuffer(9_999));
    fs.writeFileSync(minimum, pdfBuffer(10_000));

    expect(isValidPdfFile(tooSmall)).toBe(false);
    expect(isValidPdfFile(minimum)).toBe(true);
  });

  it('requires an exact %PDF- header', () => {
    const filePath = path.join(tempDir(), 'wrong-header.pdf');
    fs.writeFileSync(filePath, pdfBuffer(10_100, { header: '%PDFX1.7\n' }));

    expect(isValidPdfFile(filePath)).toBe(false);
  });

  it('requires %%EOF in the completed file tail', () => {
    const filePath = path.join(tempDir(), 'missing-eof.pdf');
    fs.writeFileSync(filePath, pdfBuffer(10_100, { eof: false }));

    expect(isValidPdfFile(filePath)).toBe(false);
  });

  it('returns false for missing paths instead of masking them as valid PDFs', () => {
    expect(isValidPdfFile(path.join(tempDir(), 'missing.pdf'))).toBe(false);
  });

  it('rejects HTML challenge pages instead of writing them as PDFs', async () => {
    jest.spyOn(axios, 'get').mockResolvedValue({
      status: 200,
      headers: { 'content-type': 'text/html' },
      data: Buffer.from('<html><title>Preparing to download ...</title></html>')
    } as any);
    const dir = tempDir();

    await expect(downloadPdfFromUrl('https://example.test/paper.pdf', dir, 'paper')).rejects.toThrow(
      'did not return a PDF'
    );
    expect(fs.existsSync(path.join(dir, 'paper.pdf'))).toBe(false);
  });

  it('explains HTTP challenge responses clearly', async () => {
    jest.spyOn(axios, 'get').mockResolvedValue({
      status: 403,
      headers: { 'content-type': 'text/html', 'cf-mitigated': 'challenge' },
      data: Buffer.from('<html><title>Just a moment...</title></html>')
    } as any);

    await expect(
      downloadPdfFromUrl('https://example.test/paper.pdf', tempDir(), 'paper')
    ).rejects.toThrow('anti-bot challenge');
  });

  it('does not expose a signed PDF URL in validation errors', async () => {
    jest.spyOn(axios, 'get').mockResolvedValue({
      status: 200,
      headers: { 'content-type': 'text/html' },
      data: Buffer.from('<html><title>Not a PDF</title></html>')
    } as any);
    const signedUrl = 'https://publisher.example/paper.pdf?token=super-secret&X-Amz-Signature=signature';

    let thrown: unknown;
    try {
      await downloadPdfFromUrl(signedUrl, tempDir(), 'signed');
    } catch (error) {
      thrown = error;
    }

    expect(thrown).toBeInstanceOf(Error);
    expect((thrown as Error).message).toContain('did not return a PDF');
    expect((thrown as Error).message).not.toContain(signedUrl);
    expect((thrown as Error).message).not.toContain('super-secret');
    expect((thrown as Error).message).not.toContain('signature');
  });

  it('sanitizes request failures instead of returning the signed URL from Axios', async () => {
    const signedUrl = 'https://publisher.example/paper.pdf?token=super-secret';
    const requestError = Object.assign(new Error(`request failed for ${signedUrl}`), {
      code: 'ECONNRESET',
      config: { url: signedUrl }
    });
    jest.spyOn(axios, 'get').mockRejectedValue(requestError);

    await expect(downloadPdfFromUrl(signedUrl, tempDir(), 'network-error')).rejects.toThrow(
      'PDF download request failed (ECONNRESET).'
    );
  });

  it('rejects a small placeholder even when it starts with %PDF-', async () => {
    mockDownload(pdfBuffer(9_999));
    const dir = tempDir();

    await expect(downloadPdfFromUrl('https://example.test/small.pdf', dir, 'small')).rejects.toThrow(
      'strict PDF validation'
    );
    expect(fs.existsSync(path.join(dir, 'small.pdf'))).toBe(false);
  });

  it('rejects a large response with PDF content-type but no exact PDF header', async () => {
    mockDownload(pdfBuffer(10_100, { header: 'NOTPDF---\n' }));
    const dir = tempDir();

    await expect(downloadPdfFromUrl('https://example.test/wrong-header.pdf', dir, 'wrong-header')).rejects.toThrow(
      'strict PDF validation'
    );
    expect(fs.existsSync(path.join(dir, 'wrong-header.pdf'))).toBe(false);
  });

  it('rejects a PDF-shaped response whose completed bytes lack %%EOF', async () => {
    mockDownload(pdfBuffer(10_100, { eof: false }));
    const dir = tempDir();

    await expect(downloadPdfFromUrl('https://example.test/truncated.pdf', dir, 'truncated')).rejects.toThrow(
      'strict PDF validation'
    );
    expect(fs.existsSync(path.join(dir, 'truncated.pdf'))).toBe(false);
  });

  it('rejects a stream that closes before end and removes the partial file', async () => {
    const reader = new PassThrough();
    jest.spyOn(axios, 'get').mockResolvedValue({
      status: 200,
      headers: { 'content-type': 'application/pdf', 'content-length': '10100' },
      data: reader
    } as any);
    const dir = tempDir();
    const download = downloadPdfFromUrl('https://example.test/interrupted.pdf', dir, 'interrupted');

    await new Promise(resolve => setImmediate(resolve));
    reader.write(pdfBuffer(10_100).subarray(0, 5_000));
    reader.destroy();

    await expect(download).rejects.toThrow('stream closed before completion');
    expect(fs.existsSync(path.join(dir, 'interrupted.pdf'))).toBe(false);
  });

  it('writes only a strictly validated PDF response', async () => {
    const data = pdfBuffer(10_100);
    mockDownload(data);
    const dir = tempDir();

    const filePath = await downloadPdfFromUrl('https://example.test/paper.pdf', dir, 'paper');

    expect(fs.readFileSync(filePath).subarray(0, 5).toString('latin1')).toBe('%PDF-');
    expect(fs.readFileSync(filePath).subarray(-32).toString('latin1')).toContain('%%EOF');
    expect(isValidPdfFile(filePath)).toBe(true);
  });
});
