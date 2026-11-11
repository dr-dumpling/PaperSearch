import { mkdtempSync, mkdirSync, writeFileSync, readFileSync, existsSync, readdirSync, realpathSync, symlinkSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, dirname, basename, relative } from 'node:path';
import { describe, it, expect } from '@jest/globals';
import { DIAGNOSTICS_FOLDER, createOutputLayout, organizeFiles, placeFile, removeWorkFolder, safeComponent } from '../../src/capabilities/pdf-discovery/outputLayout.js';
import { downloadWithFallback } from '../../src/capabilities/pdf-discovery/OpenAccessFallbackService.js';
import { downloadBatch, downloadSupplementsOnly } from '../../src/capabilities/pdf-discovery/batch.js';
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

  it("lays main texts only side by side, and puts diagnostics in the run's folder", () => {
    // Main texts only: no folder per paper; diagnostics never in the download folder (user, 2026-11-11).
    const dir = root();
    const runDiagnostics = join(root(), 'runs', '20261111-120000-abc123', 'diagnostics');
    const layout = createOutputLayout(dir, '10.1000/example', metadata, false, {flat: true, diagnosticsDir: runDiagnostics});
    expect(layout.fileDir).toBe(dir);
    expect(layout.workDiagnosticsDir).toBe(join(layout.paperDir, DIAGNOSTICS_FOLDER));
    const main = put(join(layout.paperDir, 'doi.pdf'), 'PDF');
    const shot = put(join(layout.workDiagnosticsDir, 'run', 'diagnostics', '10.1000_example', 'screenshot.png'), 'png');
    const diagnostic = put(join(dirname(shot), 'diagnostic.json'), '{}');
    const now = new Date(2026, 10, 11, 12, 0, 1);
    const result = organizeFiles({status: 'error', path: main, trace: {diagnostic, state: 'login_timeout'}}, layout, layout.paperDir, now);
    expect(result.path).toBe(join(dir, 'Nature_2026_A useful article.pdf'));
    expect(dirname(result.trace.diagnostic as string)).toBe(runDiagnostics);
    expect(readdirSync(runDiagnostics)).toHaveLength(2);
    removeWorkFolder(layout);
    expect(readdirSync(dir)).toEqual(['Nature_2026_A useful article.pdf']);
    // Two papers whose names come out the same keep both their PDFs.
    const other = createOutputLayout(dir, '10.1000/other', metadata, false, {flat: true});
    const second = organizeFiles({path: put(join(other.paperDir, 'doi.pdf'), 'other PDF')}, other, other.paperDir);
    removeWorkFolder(other);
    expect(second.path).not.toBe(result.path);
    expect(readFileSync(second.path!, 'utf8')).toBe('other PDF');
    expect(readdirSync(dir)).toHaveLength(2);
    // With supplementary files the folder stays: the main text is in it.
    const kept = createOutputLayout(dir, '10.1000/kept', metadata);
    organizeFiles({path: put(join(kept.paperDir, 'doi.pdf'), 'PDF')}, kept, kept.paperDir);
    removeWorkFolder(kept);
    expect(readdirSync(kept.paperDir)).toEqual(['Nature_2026_A useful article.pdf']);
  });

  it("gives a paper a folder only once a supplementary file is saved", async () => {
    // A folder per paper only for papers with supplementary files (user, 2026-11-11).
    const dir = root();
    const runs = root();
    const flat = (doi: string) => createOutputLayout(dir, doi, metadata, false, {flat: true, diagnosticsDir: join(runs, 'diagnostics')});
    // Main text and files in one answer (school download): saved files, so a folder.
    const both = flat('10.1000/both');
    const withFiles = organizeFiles({status: 'ok', path: put(join(both.paperDir, 'doi.pdf'), 'PDF'),
      supplements: [{status: 'saved' as const, label: 'S1', file: put(join(both.paperDir, 'S1.xlsx'), 'x')}]}, both, both.paperDir);
    expect(dirname(withFiles.path!)).toBe(both.paperDir);
    // Files listed but none saved: the main text lies in the download folder, no folder left.
    const none = flat('10.1000/none');
    const without = organizeFiles({status: 'ok', path: put(join(none.paperDir, 'doi.pdf'), 'PDF B'),
      supplements: [{status: 'failed' as const, label: 'S1', reason: 'http_404'}]}, none, none.paperDir);
    removeWorkFolder(none);
    expect(dirname(without.path!)).toBe(dir);
    expect(existsSync(none.paperDir)).toBe(false);

    // An open-access main text, its files fetched afterwards: it moves into the folder beside them.
    const searchers = {crossref: {getPaperByDoi: async () => metadata}} as any;
    const main = put(join(dir, 'Nature_2026_A useful article.pdf'), 'open PDF');
    const backend = (supplements: (outputDir: string) => any[]) => ({downloadLegalDoi: async (r: any) => ({
      kind: 'attempt_error', identifier: r.identifier, code: 'supplements_only', message: '', supplements: supplements(r.outputDir)})}) as any;
    const fetched = await downloadSupplementsOnly({source: 'crossref', paperId: '10.1000/open', doi: '10.1000/open', savePath: dir},
      backend((out) => [{status: 'saved', label: 'S1', file: put(join(out, 'supplements', 'S1.pdf'), 's')}]), searchers, main);
    const folder = createOutputLayout(dir, '10.1000/open', metadata).paperDir;
    expect(fetched.path).toBe(join(folder, 'Nature_2026_A useful article.pdf'));
    expect(readFileSync(fetched.path!, 'utf8')).toBe('open PDF');
    expect(existsSync(main)).toBe(false);
    // None found: the main text stays where it is, and no empty folder is made.
    const other = put(join(dir, 'Other.pdf'), 'other PDF');
    const empty = await downloadSupplementsOnly({source: 'crossref', paperId: '10.1000/empty', doi: '10.1000/empty', savePath: dir},
      backend(() => []), searchers, other);
    expect(empty.path).toBeUndefined();
    expect(existsSync(other)).toBe(true);
    expect(existsSync(createOutputLayout(dir, '10.1000/empty', metadata).paperDir)).toBe(false);
  });

  it("takes a site without a supplementary-file rule as no fault: no diagnostics, nothing left behind", async () => {
    // BMJ before its rule (Windows, 2026-11-11): reported as a failure, with a diagnostics
    // folder, and the page snapshots left in the download folder.
    const dir = root();
    const records = join(root(), 'records');
    const searchers = {crossref: {getPaperByDoi: async () => metadata}} as any;
    const backend = {downloadLegalDoi: async (r: any) => {
      const shot = put(join(r.diagnosticsDir, 'run1', 'diagnostics', '10.1136_x', 'snapshot-1-supplements-page.html'), '<p>page</p>');
      const manifest = put(join(r.diagnosticsDir, 'run1', 'supplements', 'manifest.json'),
        JSON.stringify({snapshots: [{why: 'supplements page', html: shot}]}));
      return {kind: 'attempt_error', identifier: r.identifier, code: 'supplements_only', message: '', trace: {record: manifest},
        supplements: [{status: 'skipped', label: '', reason: 'supplements_not_supported'}]};
    }} as any;
    const stages: any[] = [];
    const result = await downloadSupplementsOnly({source: 'crossref', paperId: '10.1136/x', doi: '10.1136/x', savePath: dir,
      recordsDir: records, diagnosticsDir: join(dirname(records), 'diagnostics'), onStage: (s: any) => stages.push(s)}, backend, searchers);
    expect(result.status).toBe('ok');
    expect(result.attempts[0]).toMatchObject({stage: 'supplements', status: 'skipped', code: 'supplements_not_supported'});
    expect(stages[0].code).toBe('supplements_not_supported');
    // Nothing in the download folder; the manifest and the page snapshot with the run's records.
    expect(readdirSync(dir)).toEqual([]);
    expect(existsSync(join(dirname(records), 'diagnostics'))).toBe(false);
    const kept = readdirSync(records).sort();
    expect(kept).toHaveLength(2);
    const manifest = kept.find((name) => name.endsWith('_supplements-manifest.json'))!;
    const html = kept.find((name) => name.endsWith('_snapshot-1-supplements-page.html'))!;
    expect(JSON.parse(readFileSync(join(records, manifest), 'utf8')).snapshots[0].html).toBe(join(records, html));
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
    const record = put(join(layout.workDiagnosticsDir, 'a1b2c3', '10.1000_example.json'), JSON.stringify({ pdf_path: main, supplements: [{file: extra}], article_url: main }));
    const now = new Date(2026, 10, 9, 15, 30, 12);
    const result = organizeFiles({path: main, supplements: [{status: 'saved' as const, label: 'S1', file: extra}], trace: {record, file: main}}, layout, layout.paperDir, now);
    const base = join(layout.diagnosticsDir, 'Nature_2026_A useful article_20261109-153012');
    expect(readFileSync(result.path!, 'utf8')).toBe('PDF bytes');
    expect(result.path).toBe(join(layout.paperDir, 'Nature_2026_A useful article.pdf'));
    expect(result.supplements![0].file).toBe(join(layout.paperDir, 'supplements', 'Table S1.xlsx'));
    expect(existsSync(main)).toBe(false);
    expect(existsSync(manifest)).toBe(false);
    expect(result.trace!.record).toBe(`${base}_record.json`);
    expect(existsSync(layout.workDiagnosticsDir)).toBe(false);
    const savedRecord = JSON.parse(readFileSync(result.trace!.record as string, 'utf8'));
    expect(savedRecord.pdf_path).toBe(result.path);
    expect(savedRecord.supplements[0].file).toBe(result.supplements![0].file);
    expect(savedRecord.article_url).toBe(main);
    expect(JSON.parse(readFileSync(`${base}_supplements-manifest.json`, 'utf8')).files[0].file).toBe(result.supplements![0].file);
    const review = put(join(layout.paperDir, 'wrong.pdf'), 'wrong');
    const rejected = organizeFiles({review: {path: review}}, layout, layout.paperDir, now);
    expect(rejected.review.path).toBe(`${base}_review.pdf`);
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
    // Main texts only: the PDF lies in the download folder, nothing else there (user, 2026-11-11).
    expect(one.path).toBe(join(dir, 'Nature_2026_A useful article.pdf'));
    expect(readdirSync(dir)).toEqual(['Nature_2026_A useful article.pdf']);
    expect(existsSync(join(batch.runLog!, 'run.json'))).toBe(true);  // the run's records in PaperSearch's own data
    let manifest = '';
    const backend = {downloadLegalDoi: async (r: any) => {
      const file = put(join(r.outputDir, 'supplements', 'S1.pdf'), 'supplement');
      manifest = put(join(r.diagnosticsDir, 'request', 'manifest.json'), JSON.stringify({files: [{file}]}));
      return {kind: 'attempt_error', identifier: r.identifier, code: 'supplements_only', message: '', trace: {record: manifest},
        supplements: [{status: 'saved', label: 'S1', file}]};
    }} as any;
    const extra = await downloadBatch(searchers, {items: [{doi: '10.1000/example'}], savePath: dir, content: 'supplements'}, backend, () => {});
    // Supplementary files: the paper's own folder, in the download folder.
    const paperDir = createOutputLayout(dir, '10.1000/example', metadata).paperDir;
    expect(extra.items[0].supplements![0].file).toBe(join(paperDir, 'supplements', 'S1.pdf'));
    expect(extra.status).toBe('ok');
    // Every file saved: the record goes to the run's folder, none beside the paper.
    expect(existsSync(join(paperDir, DIAGNOSTICS_FOLDER))).toBe(false);
    const records = join(extra.runLog!, 'records');
    const moved = readdirSync(records).filter(f => f.endsWith('_supplements-manifest.json'));
    expect(moved).toHaveLength(1);
    expect(existsSync(manifest)).toBe(false);
    expect(JSON.parse(readFileSync(join(records, moved[0]), 'utf8')).files[0].file).toBe(extra.items[0].supplements![0].file);
    expect(readdirSync(dir).sort()).toEqual(['Nature_2026_A useful article.pdf', basename(paperDir)].sort());
    expect(readdirSync(paperDir)).toEqual(['supplements']);
  });

  it("keeps a fine paper's record in the run's records, the others' in its diagnostics", () => {
    // A diagnostics folder beside a good PDF read as a failure (user, 2026-11-10).
    const dir = root();
    const layout = createOutputLayout(dir, '10.1000/example', metadata);
    const now = new Date(2026, 10, 9, 15, 30, 12);
    const records = join(dir, 'runs', '20261109-153000-abc123', 'records');
    // Saved: the backend wrote its record into the paper's diagnostics folder.
    const record = put(join(layout.workDiagnosticsDir, 'a1b2c3', '10.1000_example.json'), JSON.stringify({ status: 'success' }));
    const main = put(join(layout.paperDir, 'doi.pdf'), 'PDF');
    const saved = organizeFiles({status: 'ok', path: main, trace: {record}}, layout, dir, now, records);
    expect(saved.trace.record).toBe(join(records, 'Nature_2026_A useful article_20261109-153012_record.json'));
    expect(JSON.parse(readFileSync(saved.trace.record as string, 'utf8')).status).toBe('success');
    expect(readdirSync(layout.paperDir)).toEqual(['Nature_2026_A useful article.pdf']);
    // Saved, but a supplementary file was not; or not saved at all: the diagnostics folder.
    for (const result of [{status: 'ok', supplements: [{status: 'failed' as const, label: 'S1', reason: 'http_404'}]},
                          {status: 'error'}]) {
      const own = put(join(layout.workDiagnosticsDir, 'd4e5f6', '10.1000_example.json'), JSON.stringify(result));
      const kept = organizeFiles({...result, trace: {record: own}}, layout, dir, now, records);
      expect(dirname(kept.trace.record as string)).toBe(layout.diagnosticsDir);
    }
    // Without a run's folder (run records off): the diagnostics folder too.
    const plain = put(join(layout.workDiagnosticsDir, 'g7h8i9', '10.1000_example.json'), '{}');
    expect(dirname(organizeFiles({status: 'ok', trace: {record: plain}}, layout, dir, now).trace.record as string))
      .toBe(layout.diagnosticsDir);
  });

  it("keeps each paper's diagnostics in the diagnostics folder, named as its PDF", () => {
    const dir = root();
    const layout = createOutputLayout(dir, '10.1000/example', metadata);
    const now = new Date(2026, 10, 9, 15, 30, 12);
    // An open-access PDF: no diagnostics folder at all.
    organizeFiles({path: put(join(layout.paperDir, 'doi.pdf'), 'PDF')}, layout, layout.paperDir, now);
    expect(readdirSync(layout.paperDir)).toEqual(['Nature_2026_A useful article.pdf']);
    // The backend's packet for a failed attempt: <run>/diagnostics/<doi>/ with its screenshots.
    const run = join(layout.workDiagnosticsDir, '6b9853af3159');
    const folder = join(run, 'diagnostics', '10.1000_example');
    const shot = put(join(folder, 'screenshot.png'), 'png');
    const snapshot = put(join(folder, 'snapshot-1-article-access-checked.jpg'), 'jpg');
    const diagnostic = put(join(folder, 'diagnostic.json'), JSON.stringify({
      state: 'login_timeout', snapshots: [{screenshot: snapshot, html: '<p>page</p>'}], tabs: [{screenshot: shot}]}));
    const failed = organizeFiles({trace: {diagnostic, state: 'login_timeout'}}, layout, layout.paperDir, now);
    const base = join(layout.diagnosticsDir, 'Nature_2026_A useful article_20261109-153012');
    expect(failed.trace.diagnostic).toBe(`${base}_login_timeout.json`);
    expect(readdirSync(layout.diagnosticsDir).sort()).toEqual([
      'Nature_2026_A useful article_20261109-153012_login_timeout.json',
      'Nature_2026_A useful article_20261109-153012_screenshot.png',
      'Nature_2026_A useful article_20261109-153012_snapshot-1-article-access-checked.jpg',
    ]);
    const packet = JSON.parse(readFileSync(failed.trace.diagnostic as string, 'utf8'));
    expect(packet.snapshots[0]).toEqual({screenshot: `${base}_snapshot-1-article-access-checked.jpg`, html: '<p>page</p>'});
    expect(packet.tabs[0].screenshot).toBe(`${base}_screenshot.png`);
    expect(existsSync(run)).toBe(false);
    // A long download folder: the paper's name gives way, the paths stay within Windows' limit.
    const long = createOutputLayout(join(dir, 'x'.repeat(20)), '10.1000/long', {...metadata, title: 'A '.repeat(80)});
    const deep = put(join(long.workDiagnosticsDir, 'run', 'diagnostics', '10.1000_long', 'diagnostic.json'), '{}');
    const placed = organizeFiles({trace: {diagnostic: deep, state: 'browser_closed'}}, long, long.paperDir, now).trace.diagnostic as string;
    expect(placed).toMatch(/20261109-153012_browser_closed\.json$/);
    expect(placed.length).toBeLessThan(240);
    // A deeper diagnostics folder cuts the paper's name: the same cut for every file of the run.
    const tight = createOutputLayout(dir, '10.1000/tight', {...metadata, title: 'Word '.repeat(30)}, false,
      {diagnosticsDir: join(dir, 'p'.repeat(Math.max(1, 160 - dir.length - 28)))});
    const run2 = join(tight.workDiagnosticsDir, 'run2', 'diagnostics', '10.1000_tight');
    put(join(run2, 'screenshot.png'), 'png');
    put(join(run2, 'snapshot-2-pdf-attempt-failed.jpg'), 'jpg');
    organizeFiles({trace: {diagnostic: put(join(run2, 'diagnostic.json'), '{}'), state: 'login_timeout'}}, tight, tight.paperDir, now);
    const heads = readdirSync(tight.diagnosticsDir).map((name) => name.split('_20261109-153012_')[0]);
    expect(heads).toHaveLength(3);
    expect(new Set(heads).size).toBe(1);
    expect(heads[0].length).toBeGreaterThan(8);
    expect(tight.name.startsWith(heads[0])).toBe(true);
  });

  it('follows links: the backend reports the real path of a linked download folder (macOS /tmp)', () => {
    const real = root();
    const link = join(root(), 'linked');
    symlinkSync(real, link, process.platform === 'win32' ? 'junction' : 'dir');
    const layout = createOutputLayout(link, '10.1000/example', metadata);
    const run = join(realpathSync(real), relative(link, layout.workDiagnosticsDir), 'run1');
    const diagnostic = put(join(run, 'diagnostics', '10.1000_example', 'diagnostic.json'), '{}');
    put(join(run, 'diagnostics', '10.1000_example', 'screenshot.png'), 'png');
    const payload = {content: [{type: 'text', text: JSON.stringify({success: false, error_type: 'login_timeout',
      artifacts: {diagnostic, state: 'login_timeout'}})}]};
    const outcome = normalizeDownloadResult(payload, '10.1000/example', layout.paperDir, layout.workDiagnosticsDir) as any;
    expect(outcome.trace.diagnostic).toBe(diagnostic);  // Mac 2026-11-09: dropped, as outside /tmp/...
    const organized = organizeFiles({trace: outcome.trace}, layout, layout.paperDir, new Date(2026, 10, 9, 15, 30, 12));
    expect(basename(organized.trace.diagnostic as string)).toBe('Nature_2026_A useful article_20261109-153012_login_timeout.json');
    expect(readdirSync(layout.diagnosticsDir)).toHaveLength(2);
    expect(existsSync(run)).toBe(false);
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
