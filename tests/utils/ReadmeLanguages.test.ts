import { existsSync, readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "@jest/globals";

/**
 * The README and the guide in the progress window's six languages (user, 2026-11-24): Simplified Chinese is the
 * original, the others are kept beside it (the maintainers' conventions). Each has the same headings and
 * PaperSearch Pro marks as the original, its in-page links reach its own headings, it links to the guide and the README
 * of its own language, and the README's top line switches to all the others.
 */
const ROOT = join(__dirname, "..", "..");
const LANGUAGES = ["zh", "zh-Hant", "en", "ja", "ko", "fr"] as const;
const readme = (lang: string) => (lang === "zh" ? "README.md" : `README.${lang}.md`);
const guide = (lang: string) => `docs/guide.${lang}.md`;
const read = (path: string) => readFileSync(join(ROOT, path), "utf8");

/** The text outside fenced code blocks. */
function prose(text: string): string {
  return text.replace(/^```[\s\S]*?^```/gm, "");
}

/** GitHub's anchor for a heading: lower case, punctuation but - and _ dropped, spaces to -; repeats numbered. */
function anchors(text: string): Set<string> {
  const seen = new Map<string, number>();
  const out = new Set<string>();
  for (const [, title] of prose(text).matchAll(/^#{1,6}\s+(.+)$/gm)) {
    const plain = title.replace(/<!--[\s\S]*?-->/g, "").replace(/<[^>]+>/g, "").replace(/\[([^\]]*)\]\([^)]*\)/g, "$1")
      .replace(/[`*]/g, "").trim();
    const base = plain.toLowerCase().replace(/[^\p{L}\p{M}\p{N}\p{Pc}\- ]/gu, "").replace(/ /g, "-");
    const n = seen.get(base) ?? 0;
    seen.set(base, n + 1);
    out.add(n ? `${base}-${n}` : base);
  }
  return out;
}

const headings = (text: string) => [...prose(text).matchAll(/^(#{1,6})\s/gm)].map((m) => m[1].length);
// The Pro edition's marks (release-public.py strips them); the public edition's own wording (`<!-- public: … -->`) may
// take another number of places in another language's sentences (the English README's file layout line).
const marks = (text: string) => ["<!-- pro -->", "<!-- /pro -->", "<!-- pro-line -->"].map((mark) => text.split(mark).length - 1);
const inPage = (text: string) => [...text.matchAll(/(?:href="|\]\()#([^")]+)[")]/g)].map((m) => decodeURIComponent(m[1]));

describe("the README and the guide in six languages", () => {
  for (const [kind, file] of [["README", readme], ["guide", guide]] as const) {
    const original = read(file("zh"));
    for (const lang of LANGUAGES) {
      it(`${kind} ${lang}: as the original, its links its own`, () => {
        const path = file(lang);
        expect(existsSync(join(ROOT, path))).toBe(true);
        const text = read(path);
        expect(headings(text)).toEqual(headings(original));
        expect(marks(text)).toEqual(marks(original));
        const own = anchors(text);
        expect(inPage(text).filter((anchor) => !own.has(anchor))).toEqual([]);
        // The other language's guide or README is never linked from this one.
        const others = LANGUAGES.filter((other) => other !== lang);
        const guides = [...text.matchAll(/docs\/guide\.([A-Za-z-]+)\.md|\.\/guide\.([A-Za-z-]+)\.md/g)].map((m) => m[1] ?? m[2]);
        expect(guides.filter((linked) => linked !== lang)).toEqual([]);
        if (kind === "guide") {
          const back = [...text.matchAll(/\.\.\/(README(?:\.[A-Za-z-]+)?\.md)/g)].map((m) => m[1]);
          expect(back.filter((linked) => linked !== readme(lang))).toEqual([]);
        } else {
          // The language switch at the top: every other README.
          for (const other of others) expect(text).toContain(`href="${readme(other)}"`);
          // Screenshots, animations and the video: the Chinese README's own, the English ones elsewhere (user, 2026-11-24).
          const media = [...text.matchAll(/src="assets\/([^"]+)\.(png|webp|gif)"/g)].map((m) => m[1]);
          expect(media.filter((name) => (lang === "zh" ? name.endsWith(".en") : !name.endsWith(".en")))).toEqual([]);
        }
      });
    }
  }
});
