export function createPrimaryTier() {
    return {
        id: 'primary',
        stage: 'primary',
        run: tryPrimaryDownload
    };
}
async function tryPrimaryDownload(context) {
    if (context.source === 'arxiv')
        return { status: 'skipped', message: 'arXiv is deferred until published-version routes finish.' };
    const primary = context.searchers[context.source];
    if (!primary?.getCapabilities().download) {
        return { status: 'skipped', message: `No primary downloader for ${context.source}` };
    }
    try {
        const path = await primary.downloadPdf(context.paperId, { savePath: context.savePath });
        return { status: 'ok', path, message: path };
    }
    catch (error) {
        return { status: 'error', message: error?.message || String(error) };
    }
}
//# sourceMappingURL=primary.js.map