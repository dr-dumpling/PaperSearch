import { describe, expect, it } from "@jest/globals";
import { schoolAttemptDetails, schoolShortReason } from "../../src/capabilities/pdf-discovery/school/index.js";
import { classifyFailureCode } from "../../src/infrastructure/runlog/failureClass.js";
import { LOGIN_NO_SCREEN, LOGIN_UNAVAILABLE, schoolLogin } from "../../src/management/school/login.js";

describe("paper-search school login", () => {
  const base = { executable: "/runtime/venv/bin/paper-search-school", env: {}, platform: "darwin" as const, exists: () => true };
  const never = async () => { throw new Error("must not run"); };

  it("needs the extension, a screen and an article's DOI before it starts anything", async () => {
    expect(await schoolLogin({ ...base, executable: "", doi: "10.1/x", run: never }))
      .toEqual({ ok: false, success: false, error: LOGIN_UNAVAILABLE, exitCode: 1 });
    expect(await schoolLogin({ ...base, platform: "linux", doi: "10.1/x", run: never }))
      .toEqual({ ok: false, success: false, error: LOGIN_NO_SCREEN, exitCode: 1 });
    expect(await schoolLogin({ ...base, doi: "elsevier", run: never })).toMatchObject({ ok: false, exitCode: 2 });
  });

  it("runs the backend's login and passes on its reply: success only once signed in", async () => {
    const calls: string[][] = [];
    const signedIn = { success: true, state: "signed_in", message: "已登录学校，这篇文章能看全文；之后下载沿用这个登录" };
    const result = await schoolLogin({ ...base, doi: "https://doi.org/10.1016/j.arth.2022.02.032", maxWait: 120,
      run: async (_file, args) => { calls.push(args); return { stdout: `progress\n${JSON.stringify(signedIn)}\n`, code: 0 }; } });
    expect(calls).toEqual([["login", "--doi", "10.1016/j.arth.2022.02.032", "--max-wait", "120"]]);
    expect(result).toEqual({ ...signedIn, ok: true });
    const closed = { success: false, state: "browser_closed", message: "下载浏览器被关闭了，没有完成登录" };
    expect(await schoolLogin({ ...base, doi: "10.1016/j.arth.2022.02.032",
      run: async () => ({ stdout: JSON.stringify(closed), code: 1 }) })).toEqual({ ...closed, ok: false, exitCode: 1 });
  });
});

describe("a download browser closed by the user", () => {
  it("is said as such and counted as the user's, not unexplained", () => {
    expect(schoolAttemptDetails("browser_closed").message).toBe("下载浏览器被关闭了，这一篇没有下完；需要时重新下载即可。");
    expect(schoolShortReason("browser_closed")).toBe("下载浏览器被关闭了");
    expect(classifyFailureCode("browser_closed")).toBe("user_or_external");
  });
});
