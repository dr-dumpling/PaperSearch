/** File layout only: no publisher rules, browser operations or download routes. */
import { createHash } from 'node:crypto';
import { copyFileSync, constants, existsSync, mkdirSync, readdirSync, readFileSync, realpathSync, renameSync, rmdirSync, statSync, unlinkSync, writeFileSync } from 'node:fs';
import { basename, dirname, extname, isAbsolute, join, relative, resolve } from 'node:path';
import { withTimeout } from '../../infrastructure/security/SecurityUtils.js';
import { plainText } from '../../utils/plainText.js';
/**
 * Diagnostics keep full addresses and may carry login tokens (unmasked by the
 * user's choice, 2026-10-29); the guide and the Skill say not to pass them on.
 */
export const DIAGNOSTICS_FOLDER = 'diagnostics';
const hash = (value) => createHash('sha256').update(value).digest('hex').slice(0, 10);
export function safeComponent(value, limit) {
    let text = plainText(value.normalize('NFC')).replace(/[<>:"/\\|?*\x00-\x1f\x7f]/g, '_').replace(/\s+/g, ' ').trim().replace(/[. ]+$/g, '');
    if (/^(con|prn|aux|nul|com[1-9]|lpt[1-9])(?:\.|$)/i.test(text))
        text = '_' + text;
    // Limit UTF-8 bytes too: Windows and Unix count path components differently.
    while (text.length > limit || Buffer.byteLength(text) > limit * 2)
        text = Array.from(text).slice(0, -1).join('');
    return text.replace(/[. ]+$/g, '') || 'unknown';
}
/**
 * Where a DOI's journal and year are asked next when Crossref gives none: rate-limited
 * or queued past the lookup's time, a paper was named 未知期刊_未知年份 (Windows, 2026-11-11).
 */
const DOI_FALLBACKS = ['openalex', 'pubmed'];
/** A DOI's journal and year once found: the open lane's lookup also names its institutional download. */
const foundByDoi = new Map();
/** The journal, year and title a download is named with; ``{}`` when no source answers in time. */
export async function lookupOutputMetadata(searchers, source, id) {
    const doi = source === 'crossref' ? id.trim().toLowerCase() : '';
    const known = doi ? foundByDoi.get(doi) : undefined;
    if (known)
        return known;
    let found = await lookupOnce(searchers, source, id);
    for (const other of doi && !found.journal ? DOI_FALLBACKS : []) {
        const more = await lookupOnce(searchers, other, id);
        if (!more.journal)
            continue;
        // What the first source did give (a title) stays.
        found = { ...more, ...Object.fromEntries(Object.entries(found).filter(([, value]) => value !== undefined && value !== '')) };
        break;
    }
    if (doi && found.journal) {
        if (foundByDoi.size >= 1_000)
            foundByDoi.clear();
        foundByDoi.set(doi, found);
    }
    return found;
}
async function lookupOnce(searchers, source, id) {
    const searcher = searchers[source];
    if (!searcher?.getPaperByDoi)
        return {};
    try {
        return await withTimeout(searcher.getPaperByDoi(id), 4_000, 'Output metadata lookup timed out') || {};
    }
    catch {
        // Naming metadata is optional; never block an otherwise valid download.
        return {};
    }
}
export function createOutputLayout(root, identity, metadata, preprint = false, placement = {}) {
    const base = resolve(root);
    const key = hash(identity.trim().toLowerCase());
    const year = metadata.year || metadata.publishedDate?.getUTCFullYear();
    const journal = preprint ? 'arXiv' : metadata.journal || '未知期刊';
    // Repeated directory/file names must still fit traditional Windows paths.
    const budget = Math.min(88, Math.floor((238 - base.length - '/papers//.pdf'.length - 11) / 2));
    if (budget < 32)
        throw new Error('Download root is too long; choose a shorter savePath.');
    const prefix = `${safeComponent(journal, Math.min(28, Math.floor(budget / 3)))}_${year && Number.isInteger(year) ? year : '未知年份'}_`;
    const title = safeComponent(metadata.title || identity, Math.max(8, budget - prefix.length));
    const name = `${prefix}${title}`;
    // Stable identity suffix prevents different papers with identical titles colliding.
    const paperDir = join(base, `${name}_${key}`);
    return {
        name, paperDir, fileDir: placement.flat ? base : paperDir,
        workDiagnosticsDir: placement.diagnosticsDir ? join(placement.diagnosticsDir, `work-${key}`) : join(paperDir, DIAGNOSTICS_FOLDER),
        diagnosticsDir: placement.diagnosticsDir || join(base, DIAGNOSTICS_FOLDER),
        metadata: { ...metadata, identity, ...(preprint ? { journal: 'arXiv' } : {}) },
    };
}
/** The layout with another folder for the paper (an existing download's, its supplementary files beside its main text). */
export function inPaperDir(layout, paperDir) {
    const inside = layout.workDiagnosticsDir === join(layout.paperDir, DIAGNOSTICS_FOLDER);
    return { ...layout, paperDir, fileDir: paperDir, workDiagnosticsDir: inside ? join(paperDir, DIAGNOSTICS_FOLDER) : layout.workDiagnosticsDir };
}
/** The paper's working folder is not left behind once nothing is in it (its main text lies in the download folder). */
export function removeWorkFolder(layout) {
    pruneWork(layout);
    pruneEmpty(layout.paperDir);
}
/**
 * The backend's working diagnostics folder once nothing is left in it; in the run's
 * folder, the run's diagnostics folder too when it holds nothing else (a paper that
 * went fine leaves none).
 */
function pruneWork(layout) {
    pruneEmpty(layout.workDiagnosticsDir);
    if (existsSync(layout.workDiagnosticsDir) || isInside(layout.workDiagnosticsDir, layout.paperDir))
        return;
    try {
        rmdirSync(dirname(layout.workDiagnosticsDir));
    }
    catch (error) {
        // It still holds a diagnostic (or is gone already): it stays as it is.
        if (!['ENOTEMPTY', 'EEXIST', 'ENOENT'].includes(error.code ?? ''))
            throw error;
    }
}
/** A saved supplementary file came with this result: the paper keeps a folder of its own. */
export function savedSupplements(result) {
    return (result.supplements ?? []).some((file) => file.status === 'saved' && !!file.file);
}
/**
 * Move a main text that lies in the download folder into the paper's own folder, once
 * supplementary files were saved for it later (an open-access main text, its files
 * fetched from the article page after it). The moved file's path; the same one when
 * it is already in a folder of its own.
 */
export function moveIntoPaperDir(mainPath, layout) {
    if (!existsSync(mainPath) || isInside(mainPath, layout.paperDir))
        return mainPath;
    return placeFile(mainPath, join(layout.paperDir, basename(mainPath)), dirname(mainPath));
}
/** When a diagnostic was made, local time: 20261109-153012. */
function stampOf(date) {
    const two = (n) => String(n).padStart(2, '0');
    return `${date.getFullYear()}${two(date.getMonth() + 1)}${two(date.getDate())}-${two(date.getHours())}${two(date.getMinutes())}${two(date.getSeconds())}`;
}
/** How ``what`` ends a diagnostic's name, and the room it leaves in front for the paper's name. */
function diagnosticEnd(layout, what) {
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
function diagnosticName(layout, what, room = diagnosticEnd(layout, what).room) {
    return `${room >= 8 ? `${safeComponent(layout.name, room)}_` : ''}${diagnosticEnd(layout, what).end}`;
}
/** Remove ``dir`` and the folders under it when they hold no file; never one that does. */
function pruneEmpty(dir) {
    if (!existsSync(dir) || !statSync(dir).isDirectory())
        return;
    for (const entry of readdirSync(dir))
        pruneEmpty(join(dir, entry));
    if (readdirSync(dir).length === 0)
        rmdirSync(dir);
}
/**
 * A path with its links followed where it exists: the backend reports real paths
 * (macOS: /private/tmp), the caller may have named the same folder through a link (/tmp).
 */
export function realPath(path) {
    try {
        return realpathSync(resolve(path));
    }
    catch {
        return resolve(path);
    }
}
/** ``path`` lies under ``dir`` (not ``dir`` itself), links followed. */
export function isInside(path, dir) {
    const local = relative(realPath(dir), realPath(path));
    return !!local && !local.startsWith('..') && !isAbsolute(local);
}
/** Never overwrite an existing download, including a different revision of the same paper. */
export function placeFile(source, target, ownedDir) {
    if (resolve(source) === resolve(target))
        return source;
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
    }
    catch (error) {
        if (error.code !== 'EEXIST' || !readFileSync(destination).equals(readFileSync(source)))
            throw error;
    }
    if (isInside(source, ownedDir) && !resolve(source).startsWith(resolve(destination) + '/'))
        unlinkSync(source);
    return destination;
}
/** Rewrite only known local record paths, never arbitrary page strings or URLs. */
export function updateRecordPaths(paths, replacements) {
    const update = (value) => {
        if (Array.isArray(value))
            return value.map(update);
        if (!value || typeof value !== 'object')
            return value;
        return Object.fromEntries(Object.entries(value).map(([key, val]) => [key,
            ['pdf_path', 'file', 'path', 'screenshot', 'html'].includes(key) && typeof val === 'string' ? replacements.get(val) || val : update(val)]));
    };
    for (const path of paths) {
        if (typeof path !== 'string' || !existsSync(path))
            continue;
        const data = update(JSON.parse(readFileSync(path, 'utf8')));
        const temporary = `${path}.tmp`;
        writeFileSync(temporary, JSON.stringify(data, null, 2));
        renameSync(temporary, path);
    }
}
/**
 * Finalize only files reported by this request, preserving unrelated files.
 * The main text goes to ``fileDir``, the supplementary files to the paper's
 * folder; what there is to look at goes to the diagnostics folder under the
 * paper's own name: the backend's record or diagnostic packet with its
 * screenshots, a PDF left for review, the supplementary files' manifest. A
 * paper that went fine (saved, every supplementary file too) keeps them in
 * ``recordsDir`` instead (user, 2026-11-10).
 */
export function organizeFiles(result, paperLayout, ownedDir, now = new Date(), recordsDir) {
    // A site without a supplementary-file rule is no fault of this download (user, 2026-11-11).
    const fine = !!recordsDir && result.status === 'ok' && (result.supplements ?? [])
        .every((file) => file.status === 'saved' || file.reason === 'supplements_not_supported');
    const layout = fine ? { ...paperLayout, diagnosticsDir: recordsDir } : paperLayout;
    const replacements = new Map();
    const stamp = stampOf(now);
    const inside = isInside;
    // The backend's working diagnostics folder is this request's own too, wherever it is.
    const workDir = paperLayout.workDiagnosticsDir;
    const owned = (path) => inside(path, ownedDir) || resolve(path) === resolve(workDir) || inside(path, workDir);
    const ownerOf = (path) => (inside(path, workDir) ? workDir : ownedDir);
    // The files for the diagnostics folder are gathered first and placed together,
    // so that those of one run share one cut of the paper's name.
    const toPlace = [];
    const toDiagnostics = (source, what, then) => {
        toPlace.push({ source, what: `${stamp}_${what}`, then });
    };
    if (result.path && existsSync(result.path)) {
        const home = savedSupplements(result) ? layout.paperDir : layout.fileDir;
        const target = join(home, `${layout.name}${result.format === 'jats-xml' ? '.xml' : '.pdf'}`);
        const placed = placeFile(result.path, target, ownedDir);
        replacements.set(result.path, placed);
        result.path = placed;
    }
    const review = result.review;
    if (review && existsSync(review.path)) {
        toDiagnostics(review.path, `review${extname(review.path) || '.pdf'}`, (placed) => { review.path = placed; });
    }
    const manifests = new Set();
    for (const file of result.supplements || []) {
        if (!file.file || !existsSync(file.file))
            continue;
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
            if (typeof path === 'string' && inside(path, legacy))
                result.trace[key] = join(dest, relative(legacy, path));
        }
    }
    // The backend's packet (its record, or its diagnostic with the screenshots beside
    // it, and a manifest): out of its run folder, under the paper's name.
    const runFolders = new Set();
    const moved = [];
    // The same file may be reached through a link to the download folder (macOS /tmp): compared by its real path.
    const gathered = (file) => toPlace.some(({ source }) => realPath(source) === realPath(file));
    const state = typeof result.trace?.state === 'string' && /^[a-z0-9_]{1,64}$/.test(result.trace.state) ? result.trace.state : 'failed';
    for (const key of ['diagnostic', 'record']) {
        const path = result.trace?.[key];
        if (typeof path !== 'string' || !existsSync(path) || !owned(path))
            continue;
        // <run>/<doi>.json, or <run>/diagnostics/<doi>/diagnostic.json
        runFolders.add(key === 'diagnostic' ? dirname(dirname(dirname(path))) : dirname(path));
        manifests.add(join(dirname(path), 'manifest.json'));
        const own = basename(path) === 'manifest.json' ? 'supplements-manifest.json' : key === 'diagnostic' ? `${state}.json` : 'record.json';
        toDiagnostics(path, own, (placed) => { moved.push(placed); result.trace[key] = placed; });
        // Screenshots and page structures: beside the diagnostic, or in the record's own folder.
        const pictures = key === 'diagnostic' ? dirname(path) : join(dirname(path), 'diagnostics', basename(path, '.json'));
        if (existsSync(pictures) && statSync(pictures).isDirectory() && owned(pictures)) {
            for (const entry of readdirSync(pictures)) {
                const file = join(pictures, entry);
                if (statSync(file).isFile() && !gathered(file))
                    toDiagnostics(file, entry);
            }
        }
    }
    for (const manifest of manifests) {
        if (existsSync(manifest) && owned(manifest) && !gathered(manifest)) {
            toDiagnostics(manifest, 'supplements-manifest.json', (placed) => moved.push(placed));
        }
    }
    // Whatever else the backend left in the paper's working diagnostics folder (the
    // supplements-only visit's page snapshots, 0.5.11 on Windows) goes with the rest:
    // nothing diagnostic stays beside the papers.
    const sweep = (dir) => {
        if (!existsSync(dir) || !statSync(dir).isDirectory() || !owned(dir))
            return;
        for (const entry of readdirSync(dir)) {
            const file = join(dir, entry);
            if (statSync(file).isDirectory())
                sweep(file);
            else if (!gathered(file))
                toDiagnostics(file, entry);
        }
    };
    sweep(paperLayout.workDiagnosticsDir);
    const room = Math.min(...toPlace.map(({ what }) => diagnosticEnd(layout, what).room));
    for (const { source, what, then } of toPlace) {
        const placed = placeFile(source, join(layout.diagnosticsDir, diagnosticName(layout, what, room)), ownerOf(source));
        replacements.set(source, placed);
        then?.(placed);
    }
    updateRecordPaths(moved, replacements);
    if (typeof result.trace?.file === 'string')
        result.trace.file = replacements.get(result.trace.file) || result.trace.file;
    // Emptied run folders and the backend's working diagnostics folder.
    for (const folder of runFolders) {
        if (owned(folder))
            pruneEmpty(folder);
    }
    pruneWork(paperLayout);
    return result;
}
//# sourceMappingURL=outputLayout.js.map