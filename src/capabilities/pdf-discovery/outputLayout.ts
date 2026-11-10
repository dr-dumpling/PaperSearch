/** File layout only: no publisher rules, browser operations or download routes. */
import { createHash } from 'node:crypto';
import { copyFileSync, constants, existsSync, mkdirSync, readdirSync, readFileSync, realpathSync, renameSync, rmdirSync, statSync, unlinkSync, writeFileSync } from 'node:fs';
import { basename, dirname, extname, isAbsolute, join, relative, resolve } from 'node:path';
import type { Searchers } from '../../core/searchers.js';
import type { Paper } from '../../models/Paper.js';
import { withTimeout } from '../../infrastructure/security/SecurityUtils.js';
import { plainText } from '../../utils/plainText.js';

export type OutputMetadata = Partial<Pick<Paper, 'title' | 'journal' | 'year' | 'publishedDate'>>;
export interface OutputLayout { paperDir: string; diagnosticsDir: string; name: string; metadata: OutputMetadata & { identity: string } }

/**
 * Each paper's own diagnostics, inside its folder. They keep full addresses and
 * may carry login tokens (unmasked by the user's choice, 2026-10-29); the guide
 * and the Skill say not to pass them on. A plain name (user, 2026-11-10).
 */
export const DIAGNOSTICS_FOLDER = 'diagnostics';

const hash = (value: string | Buffer) => createHash('sha256').update(value).digest('hex').slice(0, 10);

export function safeComponent(value: string, limit: number): string {
  let text = plainText(value.normalize('NFC')).replace(/[<>:"/\\|?*\x00-\x1f\x7f]/g, '_').replace(/\s+/g, ' ').trim().replace(/[. ]+$/g, '');
  if (/^(con|prn|aux|nul|com[1-9]|lpt[1-9])(?:\.|$)/i.test(text)) text = '_' + text;
  // Limit UTF-8 bytes too: Windows and Unix count path components differently.
  while (text.length > limit || Buffer.byteLength(text) > limit * 2) text = Array.from(text).slice(0, -1).join('');
  return text.replace(/[. ]+$/g, '') || 'unknown';
}

export async function lookupOutputMetadata(searchers: Searchers, source: string, id: string): Promise<OutputMetadata> {
  const searcher = (searchers as unknown as Record<string, { getPaperByDoi?: (id: string) => Promise<Paper | null> }>)[source];
  if (!searcher?.getPaperByDoi) return {};
  try {
    return await withTimeout(searcher.getPaperByDoi(id), 4_000, 'Output metadata lookup timed out') || {};
  } catch {
    // Naming metadata is optional; never block an otherwise valid download.
    return {};
  }
}

export function createOutputLayout(root: string, identity: string, metadata: OutputMetadata, preprint = false): OutputLayout {
  const base = resolve(root);
  const key = hash(identity.trim().toLowerCase());
  const year = metadata.year || metadata.publishedDate?.getUTCFullYear();
  const journal = preprint ? 'arXiv' : metadata.journal || '未知期刊';
  // Repeated directory/file names must still fit traditional Windows paths.
  const budget = Math.min(88, Math.floor((238 - base.length - '/papers//.pdf'.length - 11) / 2));
  if (budget < 32) throw new Error('Download root is too long; choose a shorter savePath.');
  const prefix = `${safeComponent(journal, Math.min(28, Math.floor(budget / 3)))}_${year && Number.isInteger(year) ? year : '未知年份'}_`;
  const title = safeComponent(metadata.title || identity, Math.max(8, budget - prefix.length));
  const name = `${prefix}${title}`;
  // Stable identity suffix prevents different papers with identical titles colliding.
  const paperDir = join(base, 'papers', `${name}_${key}`);
  return { name, paperDir, diagnosticsDir: join(paperDir, DIAGNOSTICS_FOLDER), metadata: { ...metadata, identity, ...(preprint ? { journal: 'arXiv' } : {}) } };
}

/** The layout with another folder for the paper (an existing download's), its diagnostics inside it. */
export function inPaperDir(layout: OutputLayout, paperDir: string): OutputLayout {
  return { ...layout, paperDir, diagnosticsDir: join(paperDir, DIAGNOSTICS_FOLDER) };
}

/** When a diagnostic was made, local time: 20261109-153012. */
function stampOf(date: Date): string {
  const two = (n: number) => String(n).padStart(2, '0');
  return `${date.getFullYear()}${two(date.getMonth() + 1)}${two(date.getDate())}-${two(date.getHours())}${two(date.getMinutes())}${two(date.getSeconds())}`;
}

/** How ``what`` ends a diagnostic's name, and the room it leaves in front for the paper's name. */
function diagnosticEnd(layout: OutputLayout, what: string): { end: string; room: number } {
  const extension = /^\.[a-z0-9]{1,10}$/i.test(extname(what)) ? extname(what) : '';
  const room = 238 - layout.diagnosticsDir.length - 1 - extension.length;
  const tail = safeComponent(basename(what, extension), Math.max(12, Math.min(80, room)));
  return { end: tail + extension, room: room - tail.length - 1 };
}

/**
 * A diagnostic file's name: the paper's own name (as its PDF), when, and what it
 * is, e.g. "Nature_2020_Array programming with NumPy_20261109-153012_login_timeout.json".
 * The paper's name gives way first when the path would pass Windows' limit, cut
 * the same for every file of one run (``room``, the least any of them leaves),
 * then, under a very long download folder, the end of what it is.
 */
function diagnosticName(layout: OutputLayout, what: string, room = diagnosticEnd(layout, what).room): string {
  return `${room >= 8 ? `${safeComponent(layout.name, room)}_` : ''}${diagnosticEnd(layout, what).end}`;
}

/** Remove ``dir`` and the folders under it when they hold no file; never one that does. */
function pruneEmpty(dir: string): void {
  if (!existsSync(dir) || !statSync(dir).isDirectory()) return;
  for (const entry of readdirSync(dir)) pruneEmpty(join(dir, entry));
  if (readdirSync(dir).length === 0) rmdirSync(dir);
}

/**
 * A path with its links followed where it exists: the backend reports real paths
 * (macOS: /private/tmp), the caller may have named the same folder through a link (/tmp).
 */
export function realPath(path: string): string {
  try {
    return realpathSync(resolve(path));
  } catch {
    return resolve(path);
  }
}

/** ``path`` lies under ``dir`` (not ``dir`` itself), links followed. */
export function isInside(path: string, dir: string): boolean {
  const local = relative(realPath(dir), realPath(path));
  return !!local && !local.startsWith('..') && !isAbsolute(local);
}

/** Never overwrite an existing download, including a different revision of the same paper. */
export function placeFile(source: string, target: string, ownedDir: string): string {
  if (resolve(source) === resolve(target)) return source;
  mkdirSync(dirname(target), { recursive: true });
  let destination = target;
  if (existsSync(destination)) {
    const data = readFileSync(source);
    if (statSync(destination).size !== data.length || !readFileSync(destination).equals(data)) {
      destination = join(dirname(target), `${basename(target, extname(target))}_${hash(data)}${extname(target)}`);
    }
  }
  try {
    copyFileSync(source, destination, constants.COPYFILE_EXCL);
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code !== 'EEXIST' || !readFileSync(destination).equals(readFileSync(source))) throw error;
  }
  if (isInside(source, ownedDir) && !resolve(source).startsWith(resolve(destination) + '/')) unlinkSync(source);
  return destination;
}

/** Rewrite only known local record paths, never arbitrary page strings or URLs. */
export function updateRecordPaths(paths: unknown[], replacements: Map<string, string>): void {
  const update = (value: any): any => {
    if (Array.isArray(value)) return value.map(update);
    if (!value || typeof value !== 'object') return value;
    return Object.fromEntries(Object.entries(value).map(([key, val]) => [key,
      ['pdf_path', 'file', 'path', 'screenshot', 'html'].includes(key) && typeof val === 'string' ? replacements.get(val) || val : update(val)]));
  };
  for (const path of paths) {
    if (typeof path !== 'string' || !existsSync(path)) continue;
    const data = update(JSON.parse(readFileSync(path, 'utf8')));
    const temporary = `${path}.tmp`;
    writeFileSync(temporary, JSON.stringify(data, null, 2));
    renameSync(temporary, path);
  }
}

/**
 * Finalize only files reported by this request, preserving unrelated files.
 * The paper's folder gets its PDF, its supplementary files, and, when there is
 * something to look at, a diagnostics folder whose files carry the paper's own
 * name: the backend's record or diagnostic packet with its screenshots, a PDF
 * left for review, the supplementary files' manifest. A paper that went fine
 * (saved, every supplementary file too) keeps them in ``recordsDir`` instead, its
 * run's folder: a diagnostics folder beside a good PDF read as a failure (user,
 * 2026-11-10).
 */
export function organizeFiles<T extends { status?: string; path?: string; format?: string; review?: { path: string }; supplements?: import('./types.js').SupplementFile[]; trace?: Record<string, unknown> }>(
  result: T, paperLayout: OutputLayout, ownedDir: string, now: Date = new Date(), recordsDir?: string,
): T {
  const fine = !!recordsDir && result.status === 'ok' && (result.supplements ?? []).every((file) => file.status === 'saved');
  const layout = fine ? { ...paperLayout, diagnosticsDir: recordsDir } : paperLayout;
  const replacements = new Map<string, string>();
  const stamp = stampOf(now);
  const inside = isInside;
  // The files for the diagnostics folder are gathered first and placed together,
  // so that those of one run share one cut of the paper's name.
  const toPlace: { source: string; what: string; then?: (placed: string) => void }[] = [];
  const toDiagnostics = (source: string, what: string, then?: (placed: string) => void) => {
    toPlace.push({ source, what: `${stamp}_${what}`, then });
  };
  if (result.path && existsSync(result.path)) {
    const target = join(layout.paperDir, `${layout.name}${result.format === 'jats-xml' ? '.xml' : '.pdf'}`);
    const placed = placeFile(result.path, target, ownedDir);
    replacements.set(result.path, placed);
    result.path = placed;
  }
  const review = result.review;
  if (review && existsSync(review.path)) {
    toDiagnostics(review.path, `review${extname(review.path) || '.pdf'}`, (placed) => { review.path = placed; });
  }
  const manifests = new Set<string>();
  for (const file of result.supplements || []) {
    if (!file.file || !existsSync(file.file)) continue;
    manifests.add(join(dirname(file.file), 'manifest.json'));
    const targetDir = join(layout.paperDir, 'supplements');
    const extension = /^\.[a-z0-9]{1,10}$/i.test(extname(file.file)) ? extname(file.file) : '';
    const budget = Math.max(12, Math.min(100, 238 - targetDir.length - 1 - extension.length));
    const filename = safeComponent(basename(file.file, extension), budget) + extension;
    const placed = placeFile(file.file, join(targetDir, filename), ownedDir);
    replacements.set(file.file, placed);
    file.file = placed;
  }
  // Old backend compatibility: its per-call packet sat in the paper's folder.
  const legacy = join(ownedDir, '.browser_runs');
  if (existsSync(legacy)) {
    mkdirSync(layout.diagnosticsDir, { recursive: true });
    const dest = join(layout.diagnosticsDir, diagnosticName(layout, `${stamp}_legacy`));
    renameSync(legacy, dest);
    for (const key of ['record', 'diagnostic']) {
      const path = result.trace?.[key];
      if (typeof path === 'string' && inside(path, legacy)) result.trace![key] = join(dest, relative(legacy, path));
    }
  }
  // The backend's packet (its record, or its diagnostic with the screenshots beside
  // it, and a manifest): out of its run folder, under the paper's name.
  const runFolders = new Set<string>();
  const moved: string[] = [];
  const gathered = (file: string) => toPlace.some(({ source }) => source === file);
  const state = typeof result.trace?.state === 'string' && /^[a-z0-9_]{1,64}$/.test(result.trace.state) ? result.trace.state : 'failed';
  for (const key of ['diagnostic', 'record'] as const) {
    const path = result.trace?.[key];
    if (typeof path !== 'string' || !existsSync(path) || !inside(path, ownedDir)) continue;
    // <run>/<doi>.json, or <run>/diagnostics/<doi>/diagnostic.json
    runFolders.add(key === 'diagnostic' ? dirname(dirname(dirname(path))) : dirname(path));
    manifests.add(join(dirname(path), 'manifest.json'));
    const own = basename(path) === 'manifest.json' ? 'supplements-manifest.json' : key === 'diagnostic' ? `${state}.json` : 'record.json';
    toDiagnostics(path, own, (placed) => { moved.push(placed); result.trace![key] = placed; });
    // Screenshots and page structures: beside the diagnostic, or in the record's own folder.
    const pictures = key === 'diagnostic' ? dirname(path) : join(dirname(path), 'diagnostics', basename(path, '.json'));
    if (existsSync(pictures) && statSync(pictures).isDirectory() && inside(pictures, ownedDir)) {
      for (const entry of readdirSync(pictures)) {
        const file = join(pictures, entry);
        if (statSync(file).isFile() && !gathered(file)) toDiagnostics(file, entry);
      }
    }
  }
  for (const manifest of manifests) {
    if (existsSync(manifest) && inside(manifest, ownedDir) && !gathered(manifest)) {
      toDiagnostics(manifest, 'supplements-manifest.json', (placed) => moved.push(placed));
    }
  }
  const room = Math.min(...toPlace.map(({ what }) => diagnosticEnd(layout, what).room));
  for (const { source, what, then } of toPlace) {
    const placed = placeFile(source, join(layout.diagnosticsDir, diagnosticName(layout, what, room)), ownedDir);
    replacements.set(source, placed);
    then?.(placed);
  }
  updateRecordPaths(moved, replacements);
  if (typeof result.trace?.file === 'string') result.trace.file = replacements.get(result.trace.file) || result.trace.file;
  // Emptied run folders, the paper's diagnostics folder when the record went to
  // the run, and an older backend's "diagnostics" beside the PDF.
  for (const folder of [...runFolders, paperLayout.diagnosticsDir, join(layout.paperDir, 'diagnostics')]) {
    if (inside(folder, ownedDir)) pruneEmpty(folder);
  }
  return result;
}
