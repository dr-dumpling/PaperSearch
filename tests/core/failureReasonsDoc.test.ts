import { existsSync, readFileSync } from "node:fs";
import { describe, expect, it } from "@jest/globals";
import {
  FAILURE_CLASSES,
  FAILURE_CLASS_NAMES,
  classifyFailureCode,
} from "../../src/infrastructure/runlog/failureClass.js";
import { schoolShortReason } from "../../src/infrastructure/school/index.js";

/**
 * docs/contracts/failure-reasons.zh.md is where the failure classes and their phrasings are told (user,
 * 2026-11-22: eight classes and 58 phrasings in five places were too many to follow): its two tables say
 * what the code does, and every code with a phrasing is in it.
 */
// The doc is the maintainers' (docs/contracts is not in the public tree): checked where it is.
const DOC = "docs/contracts/failure-reasons.zh.md";
const doc = existsSync(DOC) ? readFileSync(DOC, "utf8") : "";

function table(heading: string): string[][] {
  const section = doc.split(/^## /m).find((part) => part.startsWith(heading)) ?? "";
  return section.split("\n").filter((line) => /^\|(?!\s*-)/.test(line)).slice(1)
    .map((line) => line.split("|").slice(1, -1).map((cell) => cell.trim()));
}

(doc ? describe : describe.skip)("the failure reasons doc", () => {
  it("names the five classes as the code does", () => {
    const rows = table("五个大类");
    expect(rows.map(([name, key]) => [name, key.replace(/`/g, "")]))
      .toEqual(FAILURE_CLASSES.map((cls) => [FAILURE_CLASS_NAMES[cls], cls]));
  });

  it("gives each code the class and the phrasing the code gives it, and lists every code with a phrasing", () => {
    const listed = new Set<string>();
    for (const [name, phrasing, codes] of table("每种原因")) {
      for (const code of [...codes.matchAll(/`([a-z][a-z0-9_]*)`/g)].map((m) => m[1])) {
        listed.add(code);
        expect([code, FAILURE_CLASS_NAMES[classifyFailureCode(code)], schoolShortReason(code)]).toEqual([code, name, phrasing]);
      }
    }
    const source = readFileSync("src/infrastructure/school/SchoolAttempt.ts", "utf8");
    const shortReasons = source.slice(source.indexOf("const SHORT_REASONS"), source.indexOf("};", source.indexOf("const SHORT_REASONS")));
    const codes = [...shortReasons.matchAll(/^\s+([a-z][a-z0-9_]*):/gm)].map((m) => m[1]);
    expect(codes.length).toBeGreaterThan(40);
    expect(codes.filter((code) => !listed.has(code))).toEqual([]);
  });
});

describe("the failure classes' names and phrasings", () => {
  it("keeps names to four characters and phrasings to ten (user, 2026-11-22: longer ones were too long)", () => {
    expect(FAILURE_CLASSES.map((cls) => FAILURE_CLASS_NAMES[cls]).filter((name) => [...name].length > 4)).toEqual([]);
    const said = (file: string, pattern: RegExp) => [...readFileSync(file, "utf8").matchAll(pattern)].map((m) => m[1]);
    const attempt = readFileSync("src/infrastructure/school/SchoolAttempt.ts", "utf8");
    const shortReasons = attempt.slice(attempt.indexOf("const SHORT_REASONS"), attempt.indexOf("};", attempt.indexOf("const SHORT_REASONS")));
    const phrasings = [...shortReasons.matchAll(/:\s*"([^"]+)"/g)].map((m) => m[1])
      .concat(said("src/capabilities/download/content/markdown/shortfall.ts", /reason: "([^"]+)"/g));
    expect(phrasings.length).toBeGreaterThan(40);
    expect(phrasings.filter((text) => [...text].length > 10)).toEqual([]);
  });
});
