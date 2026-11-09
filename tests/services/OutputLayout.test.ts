import { mkdtempSync, mkdirSync, writeFileSync, readFileSync, existsSync, readdirSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, dirname, basename } from 'node:path';
import { describe, it, expect } from '@jest/globals';
import { createOutputLayout, organizeFiles, placeFile, safeComponent } from '../../src/capabilities/pdf-discovery/outputLayout.js';
import { downloadWithFallback } from '../../src/capabilities/pdf-discovery/OpenAccessFallbackService.js';
import { downloadBatch } from '../../src/capabilities/pdf-discovery/batch.js';
import { normalizeDownloadResult } from '../../src/capabilities/pdf-discovery/carsi/CarsiResultNormalizer.js';
import { createCarsiDownloadArguments, selectCarsiBatchSupport } from '../../src/capabilities/pdf-discovery/carsi/CarsiReadiness.js';

const metadata = { journal: 'Nature', year: 2026, title: 'A useful article' };
const root = () => mkdtempSync(join(tmpdir(), 'output-layout-'));
const put = (path: string, content: string) => { mkdirSync(dirname(path), { recursive: true }); writeFileSync(path, content); return path; };

describe('download output layout', () => {
  it('names files with the journal and title as plain text', () => {
    const layout = createOutputLayout('/tmp/output', '10.1002/art.70156',
      { journal: 'Arthritis &amp; Rheumatology', year: 2026, title: 'Identifying <i>Systemic</i> Lupus' });
    expect(layout.name).toBe('Arthritis & Rheumatology_2026_Identifying Systemic Lupus');
  });

  it('bounds Windows paths, sanitizes reserved names and separates identical titles by identity', () => {
    expect(safeComponent('CON', 20)).toBe('_CON');
    expect(safeComponent(' a:b/c\\d?* . ', 30)).toBe('a_b_c_d__');
    const a = createOutputLayout('/tmp/output', '10.1000/a', metadata);
    const b = createOutputLayout('/tmp/output', '10.1000/b', metadata);
    expect(a.name).toBe('Nature_2026_A useful article');
    expect(a.paperDir).not.toBe(b.paperDir);
    expect(createOutputLayout('/tmp/output', '10.1000/A', metadata).paperDir).toEqual(a.paperDir);
    const long = createOutputLayout('/tmp/' + 'x'.repeat(70), '10.1000/a', { journal: '中文期刊'.repeat(20), title: '中文:标题?'.repeat(90) });
    expect(join(long.paperDir, long.name + '.pdf').length).toBeLessThan(240);
    expect(Buffer.byteLength(basename(long.paperDir))).toBeLessThan(255);
    expect(long.name).toContain('未知年份');
    expect(createOutputLayout('/tmp', '1706.03762', metadata, true).name).toMatch(/^arXiv_2026_/);
  });

  it('does not overwrite different existing bytes or remove a source outside this request', () => {
    const dir = root();
    const source = put(join(dir, 'source.pdf'), 'new revision');
    const target = put(join(dir, 'papers', 'paper.pdf'), 'old revision');
    const placed = placeFile(source, target, join(dir, 'papers'));
    expect(readFileSync(target, 'utf8')).toBe('old revision');
    expect(readFileSync(placed, 'utf8')).toBe('new revision');
    expect(existsSync(source)).toBe(true);
    expect(placeFile(source, target, join(dir, 'papers'))).toBe(placed);
  });

  it('moves main, supplements and review files while updating only file references in records', () => {
    const dir = root();
    const layout = createOutputLayout(dir, '10.1000/example', metadata);
    const main = put(join(layout.paperDir, 'doi.pdf'), 'PDF bytes');
    const extra = put(join(layout.paperDir, 'doi_supplements', 'Table S1.xlsx'), 'XLSX bytes');
    const manifest = put(join(dirname(extra), 'manifest.json'), JSON.stringify({files: [{file: extra}]}));
    const record = put(join(layout.diagnosticsDir, 'record.json'), JSON.stringify({ pdf_path: main, supplements: [{file: extra}], article_url: main }));
    const result = organizeFiles({path: main, supplements: [{status: 'saved' as const, label: 'S1', file: extra}], trace: {record, file: main}}, layout, layout.paperDir);
    expect(readFileSync(result.path!, 'utf8')).toBe('PDF bytes');
    expect(result.path).toBe(join(layout.paperDir, 'Nature_2026_A useful article.pdf'));
    expect(result.supplements![0].file).toBe(join(layout.paperDir, 'supplements', 'Table S1.xlsx'));
    expect(existsSync(main)).toBe(false);
    expect(existsSync(manifest)).toBe(false);
    const savedRecord = JSON.parse(readFileSync(record, 'utf8'));
    expect(savedRecord.pdf_path).toBe(result.path);
    expect(savedRecord.supplements[0].file).toBe(result.supplements![0].file);
    expect(savedRecord.article_url).toBe(main);
    expect(JSON.parse(readFileSync(join(layout.diagnosticsDir, 'supplements-manifest.json'), 'utf8')).files[0].file).toBe(result.supplements![0].file);
    const review = put(join(layout.paperDir, 'wrong.pdf'), 'wrong');
    const rejected = organizeFiles({review: {path: review}}, layout, layout.paperDir);
    expect(rejected.review.path).toContain('/diagnostics/');
    expect(existsSync(review)).toBe(false);
    const longFile = put(join(layout.paperDir, 'a'.repeat(180) + '.xlsx'), 'long filename');
    const longResult = organizeFiles({supplements: [{status: 'saved' as const, label: '', file: longFile}]}, layout, layout.paperDir);
    expect(longResult.supplements[0].file).toMatch(/\.xlsx$/);
    expect(longResult.supplements[0].file.length).toBeLessThan(240);
  });

  it('uses the same layout for real files through single, batch and supplements-only workflows', async () => {
    const dir = root();
    const searchers = {crossref: {getPaperByDoi: async () => metadata}} as any;
    const stages = () => [{id: 'fixture', stage: 'fixture', run: async (c: any) => ({status: 'ok' as const, verified: true, message: 'fixture', path: put(join(c.savePath, 'captured.pdf'), 'same bytes')})}];
    const one = await downloadWithFallback(searchers, {source: 'crossref', paperId: '10.1000/example', savePath: dir}, stages());
    const batch = await downloadBatch(searchers, {items: [{doi: '10.1000/example'}], savePath: dir}, undefined, () => {}, stages);
    expect(batch.items[0].path).toBe(one.path);
    expect(readFileSync(one.path!, 'utf8')).toBe('same bytes');
    expect(readdirSync(join(dir, 'diagnostics', 'runs')).length).toBeGreaterThan(0);
    let manifest = '';
    const backend = {downloadLegalDoi: async (r: any) => {
      const file = put(join(r.outputDir, 'supplements', 'S1.pdf'), 'supplement');
      manifest = put(join(r.diagnosticsDir, 'request', 'manifest.json'), JSON.stringify({files: [{file}]}));
      return {kind: 'attempt_error', identifier: r.identifier, code: 'supplements_only', message: '', trace: {record: manifest},
        supplements: [{status: 'saved', label: 'S1', file}]};
    }} as any;
    const extra = await downloadBatch(searchers, {items: [{doi: '10.1000/example'}], savePath: dir, content: 'supplements'}, backend, () => {});
    expect(extra.items[0].supplements![0].file).toBe(join(dirname(one.path!), 'supplements', 'S1.pdf'));
    expect(extra.status).toBe('ok');
    expect(JSON.parse(readFileSync(manifest, 'utf8')).files[0].file).toBe(extra.items[0].supplements![0].file);
    expect(readdirSync(dirname(one.path!)).filter(f => /json|log/.test(f))).toEqual([]);
  });

  it('accepts only an explicitly allowed diagnostic root and advertises the optional MCP field', () => {
    const payload = {content: [{type: 'text', text: JSON.stringify({success: false, error_type: 'paywall', artifacts: {record: '/diagnostics/a/record.json', diagnostic: '/private/secret.json'}})}]};
    const outcome = normalizeDownloadResult(payload, '10.1000/example', '/papers/a', '/diagnostics/a');
    expect(outcome).toMatchObject({trace: {record: '/diagnostics/a/record.json'}});
    expect((outcome as any).trace.diagnostic).toBeUndefined();
    expect((normalizeDownloadResult(payload, '10.1000/example', '/papers/a') as any).trace).toBeUndefined();
    const args = createCarsiDownloadArguments('10.1000/example', '/papers/a', 'legal_only', undefined, undefined, undefined, '/diagnostics/a');
    const properties = Object.fromEntries(Object.entries(args).map(([k, v]) => [k, {type: typeof v}]));
    const tools = [{name: 'carsi_download', inputSchema: {type: 'object', properties}}];
    expect(selectCarsiBatchSupport(tools, 'legal_only').diagnosticsDirField).toBe(true);
    delete properties.diagnostics_dir;
    expect(selectCarsiBatchSupport(tools, 'legal_only').diagnosticsDirField).toBe(false);
  });
});
