import { describe, expect, it } from "@jest/globals";
import { plainText } from "../../src/utils/plainText.js";

describe("plainText", () => {
  it("drops markup and decodes entities in metadata text", () => {
    expect(plainText("Arthritis &amp; Rheumatology")).toBe("Arthritis & Rheumatology");
    expect(plainText("Dual-RNA&#8211;Guided  <i>DNA</i>&#x2F;RNA")).toBe("Dual-RNA–Guided DNA/RNA");
    expect(plainText("CO<sub>2</sub> &lt;5%")).toBe("CO2 <5%");
    expect(plainText("&unknown; &#99999999;")).toBe("&unknown; &#99999999;");
  });
});
