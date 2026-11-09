import { describe, expect, it } from "@jest/globals";
import { missingNumbers, referenceNumbers } from "../../src/capabilities/citation-expansion/CrossrefReferences.js";

// Keys as publishers deposit them with Crossref (shapes taken from real records).
const range = (from: number, to: number) => Array.from({ length: to - from + 1 }, (_, i) => from + i);

describe("reference numbering from Crossref keys", () => {
  it("reads Elsevier's numbers and finds the one it did not deposit", () => {
    const keys = range(1, 27).filter((n) => n !== 9).map((n) => `10.1016/j.arth.2024.06.028_bib${n}`);
    const numbers = referenceNumbers(keys)!;
    expect(numbers[8]).toBe(10);
    expect(missingNumbers(numbers.map((number) => ({ paperId: "", title: "", citationCount: 0, referenceCount: 0, number })))).toEqual([9]);
  });

  it("reads Springer Nature, Atypon (Wiley, NEJM), Wolters Kluwer and plain numbered keys", () => {
    expect(referenceNumbers(range(1, 65).map((n) => `12882_CR${n}`))).toEqual(range(1, 65));
    expect(referenceNumbers(range(2, 50).map((n) => `e_1_2_6_${n}_1`))).toEqual(range(1, 49));
    expect(referenceNumbers(range(1, 23).map((n) => `R${n}-20230721`))).toEqual(range(1, 23));
    expect(referenceNumbers(range(1, 148).map((n) => `B${n}`))).toEqual(range(1, 148));
  });

  it("trusts no numbering that skips too much or does not rise with the list", () => {
    expect(referenceNumbers(range(1, 100).map((n) => `ehab368-B${n * 2}`))).toBeNull();
    expect(referenceNumbers(["ref3", "ref1", "ref2"])).toBeNull();
    expect(referenceNumbers(["smith2019", "jones2020a"])).toBeNull();
  });
});
