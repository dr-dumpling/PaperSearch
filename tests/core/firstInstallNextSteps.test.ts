import { describe, expect, it } from "@jest/globals";
import { firstInstallNextSteps } from "../../src/management/skills/nextSteps.js";
import { CONFIG_KEYS } from "../../src/config/ConfigService.js";

describe("first-install next steps", () => {
  it("asks about school subscription downloads where a browser can be shown, and records a no", () => {
    for (const [platform, env] of [["darwin", {}], ["win32", {}], ["linux", { DISPLAY: ":0" }], ["linux", { WAYLAND_DISPLAY: "wayland-0" }]] as const) {
      const school = firstInstallNextSteps(platform, env)[1];
      expect(school).toContain("paper-search carsi install");
      expect(school).toContain("PAPER_SEARCH_CARSI_DECLINED true");
    }
  });

  it("does not offer it on a server without a screen", () => {
    const steps = firstInstallNextSteps("linux", {});
    expect(steps).toHaveLength(3);
    expect(steps.join("\n")).not.toContain("carsi install");
    expect(steps[1]).toContain("没有图形界面");
  });

  it("can store the user's no in the config file", () => {
    expect(CONFIG_KEYS).toContain("PAPER_SEARCH_CARSI_DECLINED");
  });
});
