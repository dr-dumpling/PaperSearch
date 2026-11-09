/** File layout only: no publisher rules, browser operations or download routes. */
import { createHash } from 'node:crypto';
import { copyFileSync, constants, existsSync, mkdirSync, readFileSync, renameSync, statSync, unlinkSync, writeFileSync } from 'node:fs';
import { basename, dirname, extname, join, relative, resolve } from 'node:path';
import { withTimeout } from '../../infrastructure/security/SecurityUtils.js';
import { plainText } from '../../utils/plainText.js';
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
export async function lookupOutputMetadata(searchers, source, id) {
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
export function createOutputLayout(root, identity, metadata, preprint = false) {
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
    return { name, paperDir: join(base, 'papers', `${name}_${key}`), diagnosticsDir: join(base, 'diagnostics', key), metadata: { ...metadata, identity, ...(preprint ? { journal: 'arXiv' } : {}) } };
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
    const local = relative(resolve(ownedDir), resolve(source));
    if (local && !local.startsWith('..') && !resolve(source).startsWith(resolve(destination) + '/'))
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
            ['pdf_path', 'file', 'path'].includes(key) && typeof val === 'string' ? replacements.get(val) || val : update(val)]));
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
/** Finalize only files reported by this request, preserving unrelated files. */
export function organizeFiles(result, layout, ownedDir) {
    const replacements = new Map();
    if ([result.path, result.review?.path, ...(result.supplements || []).map(f => f.file)].some(path => path && existsSync(path))) {
        mkdirSync(layout.diagnosticsDir, { recursive: true });
        writeFileSync(join(layout.diagnosticsDir, 'metadata.json'), JSON.stringify({ ...layout.metadata, paperDirectory: layout.paperDir }, null, 2));
    }
    if (result.path && existsSync(result.path)) {
        const target = join(layout.paperDir, `${layout.name}${result.format === 'jats-xml' ? '.xml' : '.pdf'}`);
        const placed = placeFile(result.path, target, ownedDir);
        replacements.set(result.path, placed);
        result.path = placed;
    }
    if (result.review && existsSync(result.review.path)) {
        const placed = placeFile(result.review.path, join(layout.diagnosticsDir, 'review', basename(result.review.path)), ownedDir);
        replacements.set(result.review.path, placed);
        result.review.path = placed;
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
    const records = [result.trace?.record, result.trace?.diagnostic];
    // New backend keeps its manifest beside the record, old backends beside files.
    for (const record of records)
        if (typeof record === 'string')
            manifests.add(join(dirname(record), 'manifest.json'));
    updateRecordPaths([...records, ...manifests], replacements);
    if (typeof result.trace?.file === 'string')
        result.trace.file = replacements.get(result.trace.file) || result.trace.file;
    // Old backend compatibility: move its per-call packet out of the paper directory.
    const legacy = join(ownedDir, '.browser_runs');
    if (existsSync(legacy)) {
        mkdirSync(layout.diagnosticsDir, { recursive: true });
        const dest = join(layout.diagnosticsDir, `legacy-${Date.now()}`);
        renameSync(legacy, dest);
        for (const key of ['record', 'diagnostic']) {
            const path = result.trace?.[key];
            if (typeof path === 'string' && !relative(legacy, path).startsWith('..'))
                result.trace[key] = join(dest, relative(legacy, path));
        }
    }
    for (const manifest of manifests) {
        if (existsSync(manifest) && !relative(ownedDir, manifest).startsWith('..')) {
            placeFile(manifest, join(layout.diagnosticsDir, 'supplements-manifest.json'), ownedDir);
        }
    }
    return result;
}
//# sourceMappingURL=outputLayout.js.map