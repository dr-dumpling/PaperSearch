import { describe, expect, it, jest } from "@jest/globals";
import { OpenAlexGraph } from "../../src/capabilities/citation-expansion/OpenAlexGraph.js";

// A fake OpenAlex: `total` citing works, served 200 a page by number or by cursor.
function fakeClient(total: number) {
  const calls: any[] = [];
  const get = jest.fn(async (_path: string, config: any) => {
    const params = config.params;
    calls.push(params);
    const start = params.cursor !== undefined ? (params.cursor === "*" ? 0 : Number(params.cursor)) : (params.page - 1) * 200;
    const results = Array.from({ length: Math.max(0, Math.min(200, total - start)) }, (_, i) => ({ id: `https://openalex.org/W${start + i}`, display_name: `Work ${start + i}` }));
    const next = start + 200 < total ? String(start + 200) : null;
    return { data: { results, meta: { next_cursor: params.cursor !== undefined ? next : null } } };
  });
  return { get, calls };
}

describe("OpenAlexGraph.citedBy", () => {
  it("without a key pages by number through the first 10,000 only", async () => {
    const graph = new OpenAlexGraph("me@example.org", "");
    const client = fakeClient(29491);
    (graph as any).client = client;

    const works = await graph.citedBy("W1");

    expect(works).toHaveLength(10000);
    expect(client.calls).toHaveLength(50);
    expect(client.calls[1]).toMatchObject({ page: 2, "per-page": 200, mailto: "me@example.org" });
    expect(client.calls[1].api_key).toBeUndefined();
    expect(client.calls[1].cursor).toBeUndefined();
  });

  it("with a key follows the cursor to the last citing work", async () => {
    const graph = new OpenAlexGraph("me@example.org", "test-key");
    const client = fakeClient(10450);
    (graph as any).client = client;

    const works = await graph.citedBy("W1");

    expect(works).toHaveLength(10450);
    expect(client.calls[0]).toMatchObject({ cursor: "*", api_key: "test-key" });
    expect(client.calls.at(-1)).toMatchObject({ cursor: "10400" });
  });

  it("stops at a short page when there are fewer than 10,000", async () => {
    const graph = new OpenAlexGraph("me@example.org", "");
    const client = fakeClient(31);
    (graph as any).client = client;

    expect(await graph.citedBy("W1")).toHaveLength(31);
    expect(client.calls).toHaveLength(1);
  });
});
