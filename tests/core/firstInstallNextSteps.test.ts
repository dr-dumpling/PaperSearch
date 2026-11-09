import { describe, expect, it } from "@jest/globals";
import { firstInstallNextSteps } from "../../src/management/skills/nextSteps.js";
import { CONFIG_KEYS } from "../../src/config/ConfigService.js";

describe("first-install next steps", () => {
  it("installs nothing more and sends the user to a new chat to start setup", () => {
    const steps = firstInstallNextSteps();
    expect(steps).toHaveLength(2);
    expect(steps[0]).toContain("paper-search doctor --format text");
    expect(steps[1]).toContain("请开始配置");
    for (const install of ["carsi install", "brew install", "winget install", "不用先问"]) {
      expect(steps.join("\n")).not.toContain(install);
    }
  });

  it("can store the user's no in the config file", () => {
    expect(CONFIG_KEYS).toContain("PAPER_SEARCH_CARSI_DECLINED");
  });
});
