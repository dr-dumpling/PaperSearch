import { mkdirSync, readFileSync, renameSync, statSync, unlinkSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { randomUUID } from "node:crypto";
import { paperSearchDataRoot } from "../skills/autoSync.js";
const DAY = 24 * 60 * 60 * 1000;
const RETRY = 60 * 60 * 1000;
const TIMEOUT = 1500;
export const RELEASE_NOTES = "https://github.com/dr-dumpling/PaperSearch/releases";
const REGISTRY = "https://registry.npmjs.org/papersearch/latest";
function version(value) {
    const match = /^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)(-[0-9A-Za-z.-]+)?(?:\+[0-9A-Za-z.-]+)?$/.exec(value);
    if (!match)
        return undefined;
    const parts = match.slice(1, 4).map(Number);
    return parts.every(Number.isSafeInteger) ? { parts, prerelease: Boolean(match[4]) } : undefined;
}
/** Only recommend stable releases. A newer local prerelease is never downgraded. */
export function compareStableRelease(current, latest) {
    const installed = version(current), published = version(latest);
    if (!installed || !published || published.prerelease)
        return undefined;
    for (let i = 0; i < 3; i += 1) {
        if (published.parts[i] !== installed.parts[i])
            return Math.sign(published.parts[i] - installed.parts[i]);
    }
    return installed.prerelease ? 1 : 0;
}
/** Upgrade the installation being used, including temporary npx and local installs. */
export function upgradeCommand(latest, packageRoot = "") {
    const path = packageRoot.replace(/\\/g, "/").toLowerCase();
    if (path.includes("/_npx/"))
        return `npx papersearch@${latest}`;
    if (path.includes("/pnpm/") || path.includes("/.pnpm/")) {
        return `pnpm add${/\/global\//.test(path) ? " -g" : ""} papersearch@${latest}`;
    }
    if (path.includes("/yarn/global/"))
        return `yarn global add papersearch@${latest}`;
    const local = path.includes("/node_modules/") && !/\/(lib|npm)\/node_modules\//.test(path);
    return `npm install${local ? "" : " -g"} papersearch@${latest}`;
}
function cacheFile(options) {
    return join(options.dataRoot ?? paperSearchDataRoot(), "update-check.json");
}
function readCache(options, now) {
    try {
        const file = cacheFile(options);
        if (statSync(file).size > 16 * 1024)
            return undefined;
        const data = JSON.parse(readFileSync(file, "utf8"));
        if (data.schemaVersion !== 1 || !Number.isFinite(data.checkedAt) || data.checkedAt <= 0 || data.checkedAt > now + 60_000)
            return undefined;
        if (data.latest !== undefined && (typeof data.latest !== "string" || compareStableRelease("0.0.0", data.latest) === undefined ||
            !Number.isFinite(data.latestCheckedAt) || Number(data.latestCheckedAt) > now + 60_000 || Number(data.latestCheckedAt) <= 0))
            return undefined;
        return data;
    }
    catch {
        return undefined;
    } // Optional cache: missing/corrupt files never break a paper command.
}
function saveCache(options, data) {
    const target = cacheFile(options);
    const temp = `${target}.${randomUUID()}.tmp`;
    try {
        mkdirSync(dirname(target), { recursive: true });
        writeFileSync(temp, JSON.stringify(data), { mode: 0o600, flag: "wx" });
        renameSync(temp, target);
    }
    catch { /* Optional cache; read-only homes still allow the original command. */ }
    finally {
        try {
            unlinkSync(temp);
        }
        catch { /* Already renamed or never created. */ }
    }
}
/** Fixed public endpoint, no credentials, bounded response and no redirects. */
export async function queryLatestStable(signal) {
    const response = await fetch(REGISTRY, { signal, redirect: "error", headers: { Accept: "application/json" } });
    if (!response.ok || !response.body)
        throw new Error("registry_unavailable");
    const reader = response.body.getReader();
    const chunks = [];
    let size = 0;
    try {
        while (true) {
            const part = await reader.read();
            if (part.done)
                break;
            size += part.value.byteLength;
            if (size > 128 * 1024)
                throw new Error("registry_response_too_large");
            chunks.push(part.value);
        }
    }
    finally {
        await reader.cancel().catch(() => { });
    }
    const data = JSON.parse(Buffer.concat(chunks).toString("utf8"));
    if (data.name !== "papersearch" || typeof data.version !== "string" || data.deprecated ||
        compareStableRelease("0.0.0", data.version) === undefined || typeof data.dist?.tarball !== "string" ||
        !data.dist.tarball.startsWith("https://registry.npmjs.org/papersearch/-/")) {
        throw new Error("invalid_registry_metadata");
    }
    return data.version;
}
function resultFor(options, latest, checkedAt) {
    const compared = compareStableRelease(options.current, latest);
    if (compared === undefined)
        return unavailable(options);
    return { ok: true, currentVersion: options.current, latestVersion: latest,
        updateAvailable: compared > 0, status: compared > 0 ? "update_available" : compared < 0 ? "newer_than_registry" : "up_to_date",
        source: "npm", checkedAt: new Date(checkedAt).toISOString(),
        ...(compared > 0 ? { upgradeCommand: upgradeCommand(latest, options.packageRoot) } : {}), releaseNotesUrl: RELEASE_NOTES };
}
function unavailable(options) {
    return { ok: false, currentVersion: options.current, latestVersion: null, updateAvailable: null,
        status: "unavailable", source: "npm", checkedAt: null, releaseNotesUrl: RELEASE_NOTES };
}
function startCheck(options) {
    const now = options.now ?? Date.now;
    const old = readCache(options, now());
    // Record attempts as well as successes: failures and quick commands that
    // cancel an unfinished request do not repeatedly contact the registry.
    saveCache(options, { ...old, schemaVersion: 1, checkedAt: now() });
    const controller = new AbortController();
    let stopped = false;
    const timer = setTimeout(() => controller.abort(), TIMEOUT);
    const done = (async () => {
        try {
            const latest = await (options.queryLatest ?? queryLatestStable)(controller.signal);
            if (stopped || controller.signal.aborted)
                return unavailable(options);
            const checkedAt = now();
            const result = resultFor(options, latest, checkedAt);
            if (result.ok)
                saveCache(options, { schemaVersion: 1, checkedAt, latest, latestCheckedAt: checkedAt });
            return result;
        }
        catch {
            return unavailable(options);
        } // Optional network errors never change a paper result.
        finally {
            clearTimeout(timer);
        }
    })();
    return { done, stop() { stopped = true; controller.abort(); clearTimeout(timer); } };
}
export async function checkForUpdate(options) {
    const check = startCheck(options);
    try {
        return await check.done;
    }
    finally {
        check.stop();
    }
}
export function renderUpdateNotice(result) {
    return `PaperSearch update available: ${result.currentVersion} → ${result.latestVersion}\n` +
        `Run: ${result.upgradeCommand}\n`;
}
/** Runs alongside the original command. stop() cancels at command completion. */
export function beginUpdateNotification(options) {
    const idle = { stop() { }, done: Promise.resolve() };
    if (!options.enabled || !version(options.current))
        return idle;
    const now = (options.now ?? Date.now)();
    const cached = readCache(options, now);
    let printed = false;
    const notify = (result) => {
        if (!printed && result.ok && result.updateAvailable) {
            printed = true;
            options.write(renderUpdateNotice(result));
        }
    };
    if (cached?.latest && cached.latestCheckedAt && now - cached.latestCheckedAt < DAY) {
        notify(resultFor(options, cached.latest, cached.latestCheckedAt));
    }
    const successful = cached?.latestCheckedAt === cached?.checkedAt && Boolean(cached?.latest);
    if (!options.allowNetwork || (cached && now - cached.checkedAt < (successful ? DAY : RETRY)))
        return idle;
    const check = startCheck(options);
    return { stop: check.stop, done: check.done.then(notify) };
}
//# sourceMappingURL=index.js.map