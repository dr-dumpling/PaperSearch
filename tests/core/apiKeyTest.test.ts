import { describe, expect, it } from "@jest/globals";
import { TESTABLE_KEYS, probeKeyFor, testApiKey, type HttpGet } from "../../src/config/apiKeyTest.js";
import { SETTINGS_WINDOW_KEYS } from "../../src/config/apiKeySignup.js";

const answering = (status: number, data: unknown = {}, headers: Record<string, unknown> = {}) => {
  const calls: Array<[string, any]> = [];
  const get: HttpGet = async (url, config) => { calls.push([url, config]); return { status, data, headers }; };
  return { get, calls };
};

describe("testing an API key against its service", () => {
  it("covers every key the settings window lists", () => {
    expect(new Set(TESTABLE_KEYS)).toEqual(new Set(SETTINGS_WINDOW_KEYS));
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

  it("tests a contact email by the service's answer to it", async () => {
    const unpaywall = answering(200);
    expect(await testApiKey("PAPER_SEARCH_UNPAYWALL_EMAIL", { PAPER_SEARCH_UNPAYWALL_EMAIL: "me@lab.org" }, unpaywall.get))
      .toEqual({ key: "PAPER_SEARCH_UNPAYWALL_EMAIL", status: "valid", message: "可以用：Unpaywall 接受这个邮箱" });
    expect(unpaywall.calls[0][1].params).toEqual({ email: "me@lab.org" });
    // Unpaywall's answer to test@example.com or a non-email (checked 2026-11-11).
    const refused = answering(422, { error: true, message: "Please use your own email address in API calls. See http://unpaywall.org/products/api" });
    expect(await testApiKey("PAPER_SEARCH_UNPAYWALL_EMAIL", { PAPER_SEARCH_UNPAYWALL_EMAIL: "test@example.com" }, refused.get))
      .toMatchObject({ status: "invalid", message: "被拒绝：Unpaywall 不接受这个邮箱，请填你自己常用的邮箱（HTTP 422）" });
    // Crossref answers 200 either way; its x-api-pool header names the pool the mailto got.
    const polite = answering(200, {}, { "x-api-pool": "polite-array" });
    expect(await testApiKey("CROSSREF_MAILTO", { CROSSREF_MAILTO: "me@lab.org" }, polite.get))
      .toMatchObject({ status: "valid", message: "可以用：已走 Crossref 优先通道" });
    expect(polite.calls[0][1].params).toMatchObject({ mailto: "me@lab.org" });
    expect(await testApiKey("CROSSREF_MAILTO", { CROSSREF_MAILTO: "me" }, answering(200, {}, { "x-api-pool": "public-array" }).get))
      .toMatchObject({ status: "invalid", message: "Crossref 没有认这个邮箱，仍走普通通道" });
    expect((await testApiKey("CROSSREF_MAILTO", { CROSSREF_MAILTO: "" }, polite.get)).status).toBe("missing");
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
