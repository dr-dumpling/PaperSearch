import { existsSync, mkdtempSync, readFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import {
  afterEach,
  beforeEach,
  describe,
  expect,
  it,
  jest,
} from "@jest/globals";
import { createElsevierAdapter } from "../../src/capabilities/pdf-discovery/publisherApi/elsevier.js";
import { createSpringerAdapter } from "../../src/capabilities/pdf-discovery/publisherApi/springer.js";
import { createPublisherApiTier, resetRejectedPublisherKeys } from "../../src/capabilities/pdf-discovery/tiers/publisherApi.js";
import { createDefaultDownloadTiers } from "../../src/capabilities/pdf-discovery/OpenAccessFallbackService.js";
import type { DownloadTierContext } from "../../src/capabilities/pdf-discovery/DownloadTier.js";
import { textPdf } from "../fixtures/textPdf.js";

const ELSEVIER_DOI = "10.1016/j.test.2026.01.001";
const SPRINGER_DOI = "10.1007/s00000-026-00001-0";

function fakeHttp(
  response:
    | { status: number; data: unknown; headers?: Record<string, string> }
    | Error,
) {
  const get = jest.fn(async () => {
    if (response instanceof Error) throw response;
    return { headers: {}, ...response };
  });
  return { get } as unknown as { get: typeof get } & Parameters<
    typeof createElsevierAdapter
  >[0];
}

function jats(doi: string, bodyWords: number) {
  const body =
    bodyWords > 0
      ? `<body><sec><p>${"full text word ".repeat(bodyWords)}</p></sec></body>`
      : "";
  return `<?xml version="1.0"?><response><records><article><front><article-meta><article-id pub-id-type="doi">${doi}</article-id></article-meta></front>${body}</article></records></response>`;
}

describe("publisher_api tier", () => {
  let dir: string;
  let context: DownloadTierContext;

  beforeEach(() => {
    resetRejectedPublisherKeys();
    dir = mkdtempSync(join(tmpdir(), "paper-search-publisher-api-"));
    context = {
      searchers: {} as DownloadTierContext["searchers"],
      source: "crossref",
      paperId: ELSEVIER_DOI,
      doi: ELSEVIER_DOI,
      savePath: dir,
      useEntitledAccess: true,
      useSciHub: true,
    };
  });

  afterEach(() => rmSync(dir, { recursive: true, force: true }));

  it("sits between unpaywall and scihub in the default funnel", () => {
    expect(createDefaultDownloadTiers().map((tier) => tier.stage)).toEqual([
      "primary",
      "direct_pdf_url",
      "repositories",
      "unpaywall",
      "publisher_api",
      "scihub",
      "entitled_access",
      "preprint",
    ]);
  });

  it("skips DOIs without a publisher API and unconfigured keys without calling the network", async () => {
    const http = fakeHttp(new Error("must not be called"));
    const tier = createPublisherApiTier(
      [createElsevierAdapter(http), createSpringerAdapter(http)],
      {},
    );
    expect(await tier.run({ ...context, doi: "10.1002/other" })).toEqual({
      status: "skipped",
      message: "No publisher full-text API for this DOI prefix.",
    });
    expect(await tier.run(context)).toEqual({
      status: "skipped",
      message:
        "ELSEVIER_API_KEY not configured. Get one at https://dev.elsevier.com/apikey/manage, then run `paper-search setup ELSEVIER_API_KEY` in your own terminal.",
    });
    expect(
      await tier.run({ ...context, doi: "not a doi", paperId: "x" }),
    ).toEqual({
      status: "skipped",
      message: "Publisher API requires a valid DOI.",
    });
    expect(http.get).not.toHaveBeenCalled();
  });

  it("downloads an entitled Elsevier PDF and verifies its identity", async () => {
    const pdf = textPdf([
      ["Offline article title", `DOI: ${ELSEVIER_DOI}`, "Abstract", "Results"],
      ["Second page"],
    ]);
    const http = fakeHttp({
      status: 200,
      data: pdf,
      headers: { "content-type": "application/pdf" },
    });
    const tier = createPublisherApiTier([createElsevierAdapter(http)], {
      ELSEVIER_API_KEY: "key-fixture",
      ELSEVIER_INSTTOKEN: "token-fixture",
    });
    const result = await tier.run(context);
    expect(result.status).toBe("ok");
    expect(result.format).toBe("pdf");
    expect(result.path?.endsWith(".pdf")).toBe(true);
    expect(existsSync(result.path!)).toBe(true);
    const call = (http.get as jest.Mock).mock.calls[0] as unknown[];
    expect(call[0]).toBe(
      "https://api.elsevier.com/content/article/doi/" +
        encodeURIComponent(ELSEVIER_DOI),
    );
    const options = call[1] as { headers: Record<string, string> };
    expect(options.headers["X-ELS-APIKey"]).toBe("key-fixture");
    expect(options.headers["X-ELS-Insttoken"]).toBe("token-fixture");
    expect(options.headers.Accept).toBe("application/pdf");
  });

  it("treats a one-page Elsevier response as the unentitled preview and removes it", async () => {
    const pdf = textPdf([["Preview", `DOI: ${ELSEVIER_DOI}`]]);
    const http = fakeHttp({
      status: 200,
      data: pdf,
      headers: { "content-type": "application/pdf" },
    });
    const tier = createPublisherApiTier([createElsevierAdapter(http)], {
      ELSEVIER_API_KEY: "k",
    });
    const result = await tier.run(context);
    expect(result.status).toBe("error");
    expect(result.code).toBe("not_entitled");
    expect(
      existsSync(join(dir, "elsevier_10.1016_j.test.2026.01.001.pdf")),
    ).toBe(false);
    expect(JSON.stringify(result)).not.toContain("secret-fixture-key");
  });

  it.each([
    [401, "api_key_rejected", "error"],
    [403, "not_entitled", "error"],
    [429, "rate_limited", "error"],
    [404, undefined, "skipped"],
  ])("maps Elsevier HTTP %s to %s", async (status, code, expected) => {
    const http = fakeHttp({ status, data: Buffer.from("") });
    const tier = createPublisherApiTier([createElsevierAdapter(http)], {
      ELSEVIER_API_KEY: "secret-key-value",
    });
    const result = await tier.run(context);
    expect(result.status).toBe(expected);
    if (code) expect(result.code).toBe(code);
    expect(JSON.stringify(result)).not.toContain("secret-key-value");
  });

  it("blocks an Elsevier PDF whose first page carries a different DOI", async () => {
    const pdf = textPdf([
      ["Other article", "DOI: 10.1016/j.other.2026.09.009", "Abstract"],
      ["p2"],
    ]);
    const http = fakeHttp({
      status: 200,
      data: pdf,
      headers: { "content-type": "application/pdf" },
    });
    const tier = createPublisherApiTier([createElsevierAdapter(http)], {
      ELSEVIER_API_KEY: "k",
    });
    const result = await tier.run(context);
    expect(result.status).toBe("error");
    expect(result.code).toBe("pdf_identity_mismatch");
    expect(result.review?.path).toBeDefined();
  });

  it("asks no more once a key was rejected in this run, but tries a changed key", async () => {
    resetRejectedPublisherKeys();
    const http = fakeHttp({ status: 401, data: "" });
    const springer = { ...context, doi: SPRINGER_DOI, paperId: SPRINGER_DOI };
    const tier = createPublisherApiTier([createSpringerAdapter(http)], { SPRINGER_API_KEY: "metadata-only" });
    expect(await tier.run(springer)).toEqual(expect.objectContaining({ status: "error", code: "api_key_rejected" }));
    expect(await tier.run(springer)).toEqual(expect.objectContaining({ status: "skipped", code: "api_key_rejected" }));
    expect(http.get).toHaveBeenCalledTimes(1);
    const renewed = createPublisherApiTier([createSpringerAdapter(http)], { SPRINGER_API_KEY: "tdm-key" });
    await renewed.run(springer);
    expect(http.get).toHaveBeenCalledTimes(2);
    resetRejectedPublisherKeys();
  });

  it("saves Springer subscription full text as JATS XML", async () => {
    const http = fakeHttp({ status: 200, data: jats(SPRINGER_DOI, 400) });
    const tier = createPublisherApiTier([createSpringerAdapter(http)], {
      SPRINGER_API_KEY: "springer-key",
    });
    const result = await tier.run({
      ...context,
      doi: SPRINGER_DOI,
      paperId: SPRINGER_DOI,
    });
    expect(result.status).toBe("ok");
    expect(result.format).toBe("jats-xml");
    expect(result.path?.endsWith(".xml")).toBe(true);
    expect(readFileSync(result.path!, "utf8")).toContain("<body>");
    const options = ((http.get as jest.Mock).mock.calls[0] as unknown[])[1] as {
      params: Record<string, string>;
    };
    expect(options.params.q).toBe(`doi:"${SPRINGER_DOI}"`);
    expect(options.params.api_key).toBe("springer-key");
  });

  it("reports Springer records without a body as not entitled and mismatched DOIs as errors", async () => {
    const noBody = createPublisherApiTier(
      [
        createSpringerAdapter(
          fakeHttp({ status: 200, data: jats(SPRINGER_DOI, 0) }),
        ),
      ],
      {
        SPRINGER_API_KEY: "k",
      },
    );
    const result = await noBody.run({
      ...context,
      doi: SPRINGER_DOI,
      paperId: SPRINGER_DOI,
    });
    expect(result).toMatchObject({ status: "error", code: "not_entitled" });

    const wrong = createPublisherApiTier(
      [
        createSpringerAdapter(
          fakeHttp({ status: 200, data: jats("10.1007/other-article", 400) }),
        ),
      ],
      { SPRINGER_API_KEY: "k" },
    );
    expect(
      await wrong.run({ ...context, doi: SPRINGER_DOI, paperId: SPRINGER_DOI }),
    ).toMatchObject({
      status: "error",
      code: "record_mismatch",
    });
    expect(
      existsSync(join(dir, "springer_10.1007_s00000-026-00001-0.xml")),
    ).toBe(false);

    const empty = createPublisherApiTier(
      [
        createSpringerAdapter(
          fakeHttp({
            status: 200,
            data: "<response><records></records></response>",
          }),
        ),
      ],
      { SPRINGER_API_KEY: "k" },
    );
    expect(
      (
        await empty.run({
          ...context,
          doi: SPRINGER_DOI,
          paperId: SPRINGER_DOI,
        })
      ).status,
    ).toBe("skipped");
  });
});
