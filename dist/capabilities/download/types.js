/** The kinds a download asked for, as the caller names them: "pdf", "supplements,markdown"… */
export function contentKinds(content, markdown) {
    const kinds = content === "supplements" ? ["supplements"] : content === "both" ? ["pdf", "supplements"]
        : content === "markdown" ? [] : ["pdf"];
    return [...kinds, ...(markdown || content === "markdown" ? ["markdown"] : [])].join(",");
}
//# sourceMappingURL=types.js.map