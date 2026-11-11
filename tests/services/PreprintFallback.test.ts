import { afterEach, describe, expect, it, jest } from '@jest/globals';
import { mkdtempSync, writeFileSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { PaperFactory } from '../../src/models/Paper.js';
import { handleGetPaperByDoi } from '../../src/capabilities/metadata-search/handler.js';
import { dedupePapers } from '../../src/capabilities/metadata-search/MultiSourceSearchService.js';
import { downloadWithFallback, createDefaultDownloadTiers, type DownloadTier } from '../../src/capabilities/pdf-discovery/OpenAccessFallbackService.js';
import { assessArxivIdentity, createPreprintTier } from '../../src/capabilities/pdf-discovery/tiers/preprint.js';
import { downloadBatch } from '../../src/capabilities/pdf-discovery/batch.js';
import { normalizeArxivId } from '../../src/infrastructure/arxiv.js';
import { textPdf } from '../fixtures/textPdf.js';

const doi = '10.1000/formal';
const id = '1706.03762v7';
const title = 'A study of version aware article downloads';
const paper = PaperFactory.create({paperId: id, source: 'arxiv', doi, title, pdfUrl: `https://arxiv.org/pdf/${id}`, extra: {version: 'preprint'}});
const dirs: string[] = [];
function setup(linkedDoi = doi) {
  const dir = mkdtempSync(join(tmpdir(), 'preprint-test-')); dirs.push(dir);
  const path = join(dir, 'preprint.pdf');
  writeFileSync(path, textPdf([[title, `arXiv:${id} [cs.CL] 1 Jan 2024`]]));
  const arxiv = {getPaperByDoi: jest.fn(async (_value: string) => ({...paper, doi: linkedDoi})), downloadPdf: jest.fn(async () => path)};
  return {arxiv, searchers: {arxiv} as any, path};
}
const stage = (name: string, success = false, code?: string): DownloadTier => ({id: name, stage: name,
  run: async () => success ? {status: 'ok', path: '/tmp/published.pdf', verified: true, message: 'formal'} : {status: 'error', code, message: 'not available'}});

afterEach(() => { for (const dir of dirs.splice(0)) rmSync(dir, {recursive: true, force: true}); });

describe('published version before arXiv', () => {
  it('places preprint after every existing route', () => {
    expect(createDefaultDownloadTiers().map(t => t.stage)).toEqual(['primary', 'direct_pdf_url', 'repositories', 'unpaywall', 'publisher_api', 'scihub', 'entitled_access', 'preprint']);
  });
  it('resolves the published DOI from arXiv before attempting the formal routes', async () => {
    const {searchers, arxiv} = setup();
    let seen: any;
    const formal: DownloadTier = {id: 'entitled_access', stage: 'entitled_access', run: async c => {seen = c; return {status: 'ok', path: '/tmp/formal.pdf', verified: true, message: 'ok'};}};
    const out = await downloadWithFallback(searchers, {source: 'arxiv', paperId: id}, [formal, createPreprintTier()]);
    expect(seen).toMatchObject({doi, paperId: doi, source: 'crossref'});
    expect(out).toMatchObject({status: 'ok', publishedDoi: doi});
    expect(out.version).toBeUndefined();
    expect(arxiv.downloadPdf).not.toHaveBeenCalled();
  });
  it('falls back only after formal failure and labels output and attempt', async () => {
    const {searchers, path} = setup();
    const out = await downloadWithFallback(searchers, {source: 'crossref', paperId: doi}, [stage('publisher_api'), stage('entitled_access'), createPreprintTier()]);
    expect(out).toMatchObject({status: 'ok', path: expect.stringMatching(/[\\/]arXiv_[^\\/]+\.pdf$/), version: 'preprint', arxivId: id, publishedDoi: doi});
    expect(out.attempts.map(a => a.stage)).toEqual(['publisher_api', 'entitled_access', 'preprint']);
    expect(out.attempts.at(-1)?.code).toBe('preprint_fallback');
  });
  it.each(['batch_stopped', 'user_skipped'])('does not fall back after %s', async code => {
    const {searchers, arxiv} = setup();
    const out = await downloadWithFallback(searchers, {source: 'crossref', paperId: doi}, [stage('entitled_access', false, code), createPreprintTier()]);
    expect(out.status).toBe('error'); expect(arxiv.downloadPdf).not.toHaveBeenCalled();
  });
  it('rejects conflicting DOI for both direct inputs and discovered candidates', async () => {
    for (const input of [{source: 'arxiv', paperId: id, doi}, {source: 'crossref', paperId: doi, preprintIds: [id]}]) {
      const {searchers, arxiv} = setup('10.1000/other');
      const out = await downloadWithFallback(searchers, input, [createPreprintTier()]);
      expect(out.status).toBe('error'); expect(arxiv.downloadPdf).not.toHaveBeenCalled();
    }
  });
  it('downloads an unlinked arXiv input as a clearly marked preprint', async () => {
    const {searchers, arxiv} = setup('');
    const formal = {id: 'primary', stage: 'primary', run: jest.fn(async () => ({status: 'error' as const, message: ''}))};
    const out = await downloadWithFallback(searchers, {source: 'arxiv', paperId: id}, [formal, createPreprintTier()]);
    expect(out.version).toBe('preprint'); expect(formal.run).not.toHaveBeenCalled(); expect(arxiv.downloadPdf).toHaveBeenCalled();
  });
  it('reports unavailable publication metadata instead of claiming the paper was never published', async () => {
    const {searchers, arxiv} = setup();
    arxiv.getPaperByDoi.mockRejectedValue(new Error('metadata unavailable'));
    const out = await downloadWithFallback(searchers, {source: 'arxiv', paperId: id}, [stage('primary'), createPreprintTier()]);
    expect(out.version).toBe('preprint');
    expect(out.attempts[0].message).toContain('metadata unavailable');
    expect(out.attempts.at(-1)?.message).toContain('publication status is unknown');
  });
  it('recovers Crossref DOI spelling after arXiv misses a lower-case DOI', async () => {
    const {searchers, arxiv} = setup('10.1000/mixedcase');
    arxiv.getPaperByDoi.mockImplementation(async value => value === '10.1000/MixedCase' ? {...paper, doi: '10.1000/mixedcase'} : null as any);
    searchers.crossref = {getPaperByDoi: async () => ({doi: '10.1000/MixedCase'})};
    const out = await downloadWithFallback(searchers, {source: 'crossref', paperId: '10.1000/mixedcase'}, [createPreprintTier()]);
    expect(out.version).toBe('preprint');
    expect(arxiv.getPaperByDoi).toHaveBeenCalledWith('10.1000/MixedCase');
  });
  it('preserves candidate discovery across the two batch phases', async () => {
    const seen: string[] = [];
    const tiers = (): DownloadTier[] => [
      {id: 'unpaywall', stage: 'unpaywall', run: async c => {seen.push('open'); c.preprintIds!.push(id); return {status: 'skipped', message: ''};}},
      {id: 'entitled_access', stage: 'entitled_access', run: async () => {seen.push('formal'); return {status: 'error', message: ''};}},
      {id: 'preprint', stage: 'preprint', run: async c => {seen.push('preprint'); expect(c.preprintIds).toContain(id); return {status: 'ok', path: '/tmp/preprint.pdf', verified: true, version: 'preprint', arxivId: id, publishedDoi: doi, message: ''};}},
    ];
    const out = await downloadBatch({} as any, {items: [{doi}], mode: 'two_phase'}, undefined, () => {}, tiers);
    expect(seen).toEqual(['open', 'formal', 'preprint']); expect(out.items[0].version).toBe('preprint');
  });
});

describe('arXiv identifiers and PDF identity', () => {
  it.each(['1706.03762v7', 'hep-th/9901001v2', 'cs.AI/0701001'])('preserves %s', value => expect(normalizeArxivId(value)).toBe(value));
  it('normalizes official URLs and rejects foreign URLs or partial IDs', () => {
    expect(normalizeArxivId('https://arxiv.org/pdf/1706.03762v7.pdf')).toBe(id);
    expect(normalizeArxivId('https://doi.org/10.48550/arXiv.1706.03762')).toBe('1706.03762');
    expect(normalizeArxivId('https://evil.org/pdf/1706.03762')).toBeUndefined();
    expect(normalizeArxivId('../1706.03762')).toBeUndefined();
  });
  it('requires the requested version and rejects the wrong watermark', () => {
    expect(assessArxivIdentity(`arXiv:${id} [cs.CL]`, id, title)).toBe('verified');
    expect(assessArxivIdentity('arXiv:1706.03762v6 [cs.CL]', id, title)).toBe('mismatch');
    expect(assessArxivIdentity(title, id, title)).toBe('unverified');
    expect(assessArxivIdentity(`arXiv:${id} [cs.CL]`, '1706.03762', title)).toBe('verified');
  });
});

describe('search keeps the published record', () => {
  const formal = {...paper, source: 'crossref', paperId: doi, pdfUrl: 'https://publisher.example/main.pdf', extra: {}};
  it.each([[paper, formal], [formal, paper]])('does not depend on input ordering', (first, second) => {
    const out = dedupePapers([first, second]);
    expect(out).toHaveLength(1); expect(out[0]).toMatchObject({source: 'crossref', pdfUrl: formal.pdfUrl, extra: {arxivId: id}});
  });
  it('does not merge a title-only match across versions', () => {
    expect(dedupePapers([{...paper, doi: ''}, {...formal, doi: ''}])).toHaveLength(2);
  });
});

it('DOI lookup accepts an arXiv DOI while preserving the linked publication DOI', async () => {
  const out = await handleGetPaperByDoi({doi: '10.48550/arXiv.1706.03762', platform: 'all'}, {arxiv: {getPaperByDoi: async () => paper}} as any);
  expect(out.content[0].text).toContain('"total": 1');
  expect(out.content[0].text).toContain(doi);
});
