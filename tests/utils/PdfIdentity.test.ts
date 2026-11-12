import { mkdtempSync, readFileSync, writeFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { afterEach, beforeEach, describe, expect, it } from "@jest/globals";
import { assessPdfIdentity, verifyPdfIdentity } from "../../src/infrastructure/pdf/PdfIdentity.js";
import { textPdf } from "../fixtures/textPdf.js";

// Page texts as PDF extraction gives them (publisher and date noted). The
// backend's pdf_guard runs the same cases: one rule for both, every group.
interface IdentityCase {
  group: string;
  name: string;
  text: string;
  doi: string;
  title: string;
  /** The URL the PDF came from (scans without a text layer). */
  source?: string;
  expected: string;
}
const cases = JSON.parse(
  readFileSync(join(process.cwd(), "school/tests/fixtures/pdf_identity_cases.json"), "utf8"),
) as IdentityCase[];

describe.each([...new Set(cases.map((c) => c.group))])("PDF identity: %s", (group) => {
  it.each(cases.filter((c) => c.group === group).map((c) => [c.name, c] as const))("%s", (_, c) => {
    expect(assessPdfIdentity(c.text, c.doi, c.title || undefined, c.source)).toBe(c.expected);
  });
});

describe("reading the PDF", () => {
  const doi = "10.1000/target";
  const title = "Nutrition and health in a long article title";
  let directory: string;
  beforeEach(() => {
    directory = mkdtempSync(join(tmpdir(), "paper-search-pdf-identity-"));
  });
  afterEach(() => {
    rmSync(directory, { recursive: true, force: true });
  });

  it("reads the first pages, not later ones", async () => {
    const file = join(directory, "paper.pdf");
    writeFileSync(file, textPdf([[title, "Abstract", "Body"], ["Page 2"], ["Page 3"], [`https://doi.org/10.1000/other`]]));
    expect(await verifyPdfIdentity(file, doi, title)).toBe("verified");
    writeFileSync(file, textPdf([["Unrelated article", "doi:10.1000/other"], ["References", `doi:${doi}`]]));
    expect(await verifyPdfIdentity(file, doi)).toBe("mismatch");
  });

  it("finds the title on page 2 after a cover or an opener page (Journal AWWA)", async () => {
    const file = join(directory, "feature.pdf");
    writeFileSync(file, textPdf([["FEATURE", "26 JOURNAL AWWA NOVEMBER 2026"], ["Nutrition and health", "in a long article title"], ["Body"]]));
    expect(await verifyPdfIdentity(file, doi, title)).toBe("verified");
    writeFileSync(file, textPdf([[title], [`To link to this article: https://doi.org/${doi}`]]));
    expect(await verifyPdfIdentity(file, doi, title)).toBe("verified");
  });

  it("keeps an unreadable file and a file without evidence out of verified results", async () => {
    const file = join(directory, "paper.pdf");
    writeFileSync(file, "%PDF-1.7\nnot a PDF\n%%EOF");
    expect(await verifyPdfIdentity(file, doi)).toBe("unreadable");
    writeFileSync(file, textPdf([["A document without an article identifier"]]));
    expect(await verifyPdfIdentity(file, doi, title)).toBe("unverified");
  });

  it("takes a scan without a text layer by the URL it came from, when that names the DOI", async () => {
    const file = join(directory, "scan.pdf");
    writeFileSync(file, textPdf([[], []]));
    expect(await verifyPdfIdentity(file, doi, title)).toBe("unverified");
    expect(await verifyPdfIdentity(file, doi, title, "https://journals.example/doi/pdfdirect/10.1000%2Ftarget")).toBe("source");
    expect(await verifyPdfIdentity(file, doi, title, "https://journals.example/doi/pdf/10.1000/other")).toBe("unverified");
    // A PDF with readable text is judged by its text, never by its URL.
    writeFileSync(file, textPdf([["Unrelated article", "doi:10.1000/other"]]));
    expect(await verifyPdfIdentity(file, doi, title, `https://journals.example/doi/pdf/${doi}`)).toBe("mismatch");
  });
});
