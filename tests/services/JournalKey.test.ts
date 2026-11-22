import { describe, expect, it } from "@jest/globals";
import { journalOfDoi, takeNext } from "../../src/capabilities/download/batch/journalKey.js";

// 没权限时换下一所学校 (user, 2026-11-21): a batch takes one journal's papers one after another.
describe("a journal's papers one after another", () => {
  it("guesses the journal from the DOI", () => {
    expect(journalOfDoi("10.1016/j.metabol.2024.155800")).toBe("10.1016/j.metabol");
    expect(journalOfDoi("10.1016/j.metabol.2026.156850")).toBe("10.1016/j.metabol");
    expect(journalOfDoi("10.1007/s00125-024-06191-8")).toBe("10.1007/s00125");
    expect(journalOfDoi("10.1111/dom.15869")).toBe("10.1111/dom");
    expect(journalOfDoi("10.1093/eurheartj/ehae407")).toBe("10.1093/eurheartj");
    expect(journalOfDoi("10.1038/s41586-024-07000-1")).toBe("10.1038/s41586");
    expect(journalOfDoi("10.1001/jama.2024.1234")).toBe("10.1001/jama");
    expect(journalOfDoi("10.1371/journal.pone.0300000")).toBe("10.1371/journal.pone");
    expect(journalOfDoi("10.1056/NEJMoa2300000")).toBe("10.1056/nejmoa");
    expect(journalOfDoi("10.3390/nu16010001")).toBe("10.3390/nu");
    expect(journalOfDoi("10.1016/S0140-6736(23)01234-5")).toBe("10.1016/s0140");
    expect(journalOfDoi("not a doi")).toBe("");
    expect(journalOfDoi(undefined)).toBe("");
  });

  it("takes the next paper of the last one's journal first, when asked to", () => {
    const dois = ["10.1016/j.metabol.1", "10.1016/j.jhep.1", "10.1016/j.metabol.2", "10.1007/s00125-1", "10.1016/j.jhep.2"];
    const journal = (at: number) => journalOfDoi(dois[at]);
    const order = (group: boolean) => {
      const queue = [0, 1, 2, 3, 4];
      const taken: number[] = [];
      let last = "";
      for (let next = takeNext(queue, journal, last, group); next !== undefined; next = takeNext(queue, journal, last, group)) {
        taken.push(next);
        last = journal(next);
      }
      return taken;
    };
    expect(order(true)).toEqual([0, 2, 1, 4, 3]);
    expect(order(false)).toEqual([0, 1, 2, 3, 4]);
  });
});
