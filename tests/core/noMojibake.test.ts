/**
 * Source text must not carry mojibake: UTF-8 Chinese read as GBK and stored again (Windows
 * PowerShell 5.1 reads and writes the system code page). Cloudflare's Chinese marker in the
 * school backend sat that way for months while its test, written with the same wrong string,
 * passed (found 2026-11-18). The backend has its own check (school/tests/test_no_mojibake.py);
 * this one covers the core, Pro and the Skill, whose Chinese is what users and their AI read.
 *
 * The check is a round trip, not a list of odd characters: a line is mojibake only when its GBK
 * bytes are valid UTF-8 holding Chinese, so ordinary Chinese that merely looks unusual passes.
 */
import { describe, expect, it } from "@jest/globals";
import { existsSync, readdirSync, readFileSync } from "node:fs";
import { join, relative } from "node:path";

// GBK's two-byte characters, from the runtime's own GBK decoder (Node has no GBK encoder).
const GBK_BYTES = (() => {
  const decoder = new TextDecoder("gbk");
  const bytes = new Map<string, [number, number]>();
  for (let lead = 0x81; lead <= 0xfe; lead++) {
    for (let trail = 0x40; trail <= 0xfe; trail++) {
      if (trail === 0x7f) continue;
      const char = decoder.decode(new Uint8Array([lead, trail]));
      if (char.length === 1 && char !== "�" && !bytes.has(char)) bytes.set(char, [lead, trail]);
    }
  }
  return bytes;
})();

/** The text ``line`` becomes when its GBK bytes are read as UTF-8, or undefined. */
function mojibakeOf(line: string): string | undefined {
  if (!/[^\x00-\x7f]/.test(line)) return undefined;
  const bytes: number[] = [];
  for (const char of line) {
    const code = char.codePointAt(0)!;
    if (code < 0x80) bytes.push(code);
    else {
      const pair = GBK_BYTES.get(char);
      if (!pair) return undefined; // not in GBK: not text that went through it
      bytes.push(...pair);
    }
  }
  let recovered: string;
  try {
    recovered = new TextDecoder("utf-8", { fatal: true }).decode(new Uint8Array(bytes));
  } catch {
    return undefined;
  }
  return recovered !== line && /[一-鿿]/.test(recovered) ? recovered : undefined;
}

const ROOT = process.cwd();
// What is shipped or run, and read by users or their AI. Pro is absent from the public tree.
// Fixtures are third parties' pages, kept as they came.
const SEARCHED = ["src", "pro/src", "pro/tests", "tests", "skills"];
const TEXT = /\.(?:ts|js|mjs|cjs|json|md|html|css|txt)$/;

function* sourceFiles(dir: string): Generator<string> {
  for (const entry of readdirSync(dir, { withFileTypes: true })) {
    const path = join(dir, entry.name);
    if (entry.isDirectory()) {
      if (!["node_modules", "fixtures", "dist"].includes(entry.name)) yield* sourceFiles(path);
    } else if (TEXT.test(entry.name)) yield path;
  }
}

describe("source text carries no mojibake", () => {
  it("in the core, Pro, their tests and the Skill", () => {
    const offenders: string[] = [];
    for (const folder of SEARCHED) {
      const root = join(ROOT, folder);
      if (!existsSync(root)) continue;
      for (const file of sourceFiles(root)) {
        readFileSync(file, "utf8").split(/\r?\n/).forEach((line, index) => {
          const recovered = mojibakeOf(line);
          if (recovered) offenders.push(`${relative(ROOT, file)}:${index + 1}: ${line.trim().slice(0, 70)}  (reads as ${recovered.trim().slice(0, 40)})`);
        });
      }
    }
    expect(offenders).toEqual([]);
  });

  it("finds mojibake and leaves ordinary Chinese alone", () => {
    // What the backend's Cloudflare marker was stored as until 2026-11-18, as escapes so this
    // file carries no mojibake of its own.
    expect(mojibakeOf("    \"瀹夊叏楠岃瘉\",")).toBe("    \"安全验证\",");
    expect(mojibakeOf("    \"楠木与浠水的例子\",")).toBeUndefined();
    expect(mojibakeOf("学校登录后没回到出版社")).toBeUndefined();
    expect(mojibakeOf("plain ASCII")).toBeUndefined();
  });
});
