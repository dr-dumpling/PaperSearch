export function renderDoctorTextReport(report) {
    const lines = [
        "PaperSearch Doctor",
        "",
        `Config: ${report.config.path}`,
        `Configured keys: ${report.config.configured}`,
        `Missing keys: ${report.config.missing.length}`,
        "",
    ];
    if (report.carsi) {
        const extension = report.carsi;
        lines.push(`School subscription downloads (CARSI): ${extension.complete ? (extension.enabled ? "installed" : "installed, not enabled") : extension.installed ? "install not finished" : "not installed"}`, ...extension.notes.map((note) => `  ${note}`), "");
    }
    if (report.skills) {
        lines.push(...renderSkillLines(report.skills), "");
    }
    const configuredEntries = report.config.entries.filter((entry) => entry.configured);
    if (configuredEntries.length > 0) {
        lines.push("Configured:");
        for (const entry of configuredEntries) {
            lines.push(`- ${entry.key}: ${entry.value} (${entry.source})`);
        }
        lines.push("");
    }
    lines.push("Capability Profile:");
    for (const entry of report.capabilityProfile.entries) {
        lines.push(`- ${entry.id}: ${entry.status}`);
        lines.push(`  Reason: ${entry.reason}`);
        if (entry.readiness) {
            lines.push(`  Readiness: ${entry.readiness.state} (${entry.readiness.code})`);
        }
        if (entry.missing.length > 0) {
            lines.push(`  Missing: ${entry.missing.join(", ")}`);
        }
        for (const setup of entry.keySetup ?? []) {
            lines.push(setup.signupUrl
                ? `  To enable: get ${setup.key} at ${setup.signupUrl}, then run ${setup.command}`
                : `  To enable: run ${setup.command}`);
        }
    }
    lines.push("");
    const platformData = report.platformStatus?.data;
    if (Array.isArray(platformData)) {
        const counts = countBy(platformData, (item) => String(item.apiKeyStatus || "unknown"));
        lines.push("Platform API key status:");
        for (const [status, count] of Object.entries(counts).sort()) {
            lines.push(`- ${status}: ${count}`);
        }
        lines.push("");
    }
    lines.push("Next commands:");
    lines.push("- paper-search smoke --mock --pretty");
    lines.push("- paper-search smoke --live --pretty");
    lines.push("- paper-search skills status --pretty");
    return lines.join("\n");
}
export function renderSkillDiffTextReport(report) {
    const lines = [
        "PaperSearch Skill Diff",
        "",
        `Skill: ${report.skill}`,
        `Root: ${report.root}`,
        `Targets: ${report.selected.join(", ") || "(none)"}`,
        "",
    ];
    for (const target of report.targets) {
        lines.push(`${target.target} (${target.label})`);
        lines.push(`Path: ${target.path}`);
        lines.push(`Status: ${target.status}`);
        lines.push(`Managed files: ${target.files}; installed files: ${target.installedFiles}`);
        if (target.error) {
            lines.push(`Error: ${target.error}`);
        }
        if (target.missingFiles.length > 0) {
            lines.push(`Missing managed files: ${target.missingFiles.join(", ")}`);
        }
        if (target.staleFiles.length > 0) {
            lines.push(`Stale managed files: ${target.staleFiles.join(", ")}`);
        }
        if (target.extraFiles.length > 0) {
            lines.push(`Extra Skill Files (${target.extraFiles.length}, names only): ${target.extraFiles.join(", ")}`);
        }
        const diffs = target.managedFiles.filter((file) => file.status === "stale" && file.diff);
        for (const diff of diffs) {
            lines.push("");
            lines.push(String(diff.diff));
        }
        lines.push("");
    }
    return lines.join("\n").trimEnd();
}
function renderSkillLines(skills) {
    const lines = ["Agent Skill（paper-search）："];
    if (skills.error) {
        lines.push(`  检查出错：${skills.error}`);
    }
    else if (skills.locations.length === 0) {
        lines.push("  还没有给 AI 工具安装：运行 paper-search setup，或 paper-search skills update --targets <工具>（claude、codex、cursor 等）");
    }
    for (const location of skills.locations) {
        lines.push(`  ${location.path}（${location.targets.join("、")}）：${skillLocationState(location)}`);
    }
    lines.push(skills.autoUpdate
        ? "  自动更新：开启，升级后第一次运行 paper-search 时同步已安装的 Skill（关闭：paper-search config set PAPER_SEARCH_SKILL_AUTO_UPDATE false）"
        : "  自动更新：已关闭，升级后运行 paper-search skills update --targets <目标> 同步");
    return lines;
}
function skillLocationState(location) {
    if (location.status === "error")
        return `出错：${location.error}`;
    if (location.status === "stale") {
        const files = location.staleFiles.length + location.missingFiles.length;
        return `不是最新（${files} 个文件要更新），运行 paper-search skills update --targets ${location.targets[0]}`;
    }
    if (location.status === "extra_files") {
        return `最新（另有 ${location.extraFiles.length} 个自己加的文件，更新时保留）`;
    }
    return "最新";
}
function countBy(items, getKey) {
    const counts = {};
    for (const item of items) {
        const key = getKey(item);
        counts[key] = (counts[key] || 0) + 1;
    }
    return counts;
}
//# sourceMappingURL=index.js.map