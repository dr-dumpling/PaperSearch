import { describe, expect, it } from "@jest/globals";
import { TESTABLE_KEYS, probeKeyFor, testApiKey, type HttpGet } from "../../src/config/apiKeyTest.js";
import { API_KEY_SIGNUP_URLS } from "../../src/config/apiKeySignup.js";

const answering = (status: number, data: unknown = {}) => {
  const calls: Array<[string, any]> = [];
  const get: HttpGet = async (url, config) => { calls.push([url, config]); return { status, data }; };
  return { get, calls };
};

describe("testing an API key against its service", () => {
  it("covers every key the settings window lists", () => {
    expect(new Set(TESTABLE_KEYS)).toEqual(new Set(Object.keys(API_KEY_SIGNUP_URLS)));
    expect(probeKeyFor("ELSEVIER_INSTTOKEN")).toBe("ELSEVIER_API_KEY");
    expect(probeKeyFor("NCBI_EMAIL")).toBeUndefined();
  });

  it("reads the status code: taken, refused, rate-limited, or no answer", async () => {
    expect(await testApiKey("IEEE_API_KEY", { IEEE_API_KEY: "k" }, answering(200).get))
      .toEqual({ key: "IEEE_API_KEY", status: "valid", message: "可以用" });
    expect((await testApiKey("IEEE_API_KEY", { IEEE_API_KEY: "k" }, answering(403).get)).status).toBe("invalid");
    expect((await testApiKey("CORE_API_KEY", { CORE_API_KEY: "k" }, answering(401).get)).message).toBe("被拒绝：key 不对，或已失效（HTTP 401）");
    expect((await testApiKey("CORE_API_KEY", { CORE_API_KEY: "k" }, answering(429).get)).status).toBe("limited");
    expect((await testApiKey("CORE_API_KEY", { CORE_API_KEY: "k" }, answering(502).get)).status).toBe("unreachable");
    const offline: HttpGet = async () => { throw Object.assign(new Error("connect"), { code: "ECONNREFUSED" }); };
    expect(await testApiKey("CORE_API_KEY", { CORE_API_KEY: "k" }, offline))
      .toMatchObject({ status: "unreachable", message: expect.stringContaining("ECONNREFUSED") });
    expect((await testApiKey("CORE_API_KEY", { CORE_API_KEY: " " }, offline)).status).toBe("missing");
  });

  it("reads the answer of services that say it in the body", async () => {
    const refused = await testApiKey("EASYSCHOLAR_KEY", { EASYSCHOLAR_KEY: "k" }, answering(200, { code: 40001, msg: "secretKey无效" }).get);
    expect(refused).toMatchObject({ status: "invalid", message: "被拒绝：key 不对，或已失效（secretKey无效）" });
    expect((await testApiKey("EASYSCHOLAR_KEY", { EASYSCHOLAR_KEY: "k" }, answering(200, { code: 200, msg: "SUCCESS" }).get)).status).toBe("valid");
    expect((await testApiKey("PUBMED_API_KEY", { PUBMED_API_KEY: "k" }, answering(400, { error: "API key invalid" }).get)).status).toBe("invalid");
  });

  it("sends Elsevier's institution token with its API key, and the key only where the service wants it", async () => {
    const { get, calls } = answering(200);
    await testApiKey("ELSEVIER_INSTTOKEN", { ELSEVIER_API_KEY: "key-1", ELSEVIER_INSTTOKEN: "token-2" }, get);
    expect(calls[0][1].headers).toMatchObject({ "X-ELS-APIKey": "key-1", "X-ELS-Insttoken": "token-2" });
    await testApiKey("SEMANTIC_SCHOLAR_API_KEY", { SEMANTIC_SCHOLAR_API_KEY: "s2" }, get);
    expect(calls[1][1].headers["x-api-key"]).toBe("s2");
    expect(calls[1][1].params).not.toHaveProperty("api_key");
  });
});
