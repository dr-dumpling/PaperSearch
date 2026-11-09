import { describe, expect, it } from "@jest/globals";
import {
  createCarsiDownloadArguments,
  selectCarsiBatchSupport,
} from "../../src/capabilities/pdf-discovery/carsi/CarsiReadiness.js";
import { createEntitledAccessTier } from "../../src/capabilities/pdf-discovery/tiers/entitledAccess.js";
import type { CarsiBackend, CarsiDownloadRequest } from "../../src/capabilities/pdf-discovery/carsi/index.js";

// The backend checks the PDF against this title when the article page names none
// (Science on Atypon gives no citation_title, and its older PDFs print the DOI on the last page).
describe("the paper's title for the backend's PDF identity check", () => {
  it("is plain text: no markup, entities decoded, spaces collapsed, at most 500 characters", () => {
    const args = (title: string) =>
      createCarsiDownloadArguments("10.1/x", "out", "legal_only", undefined, undefined, undefined, undefined, title);
    expect(args("A Programmable Dual-RNA&#8211;Guided  DNA <i>Endonuclease</i> &amp; more"))
      .toMatchObject({ title: "A Programmable Dual-RNA–Guided DNA Endonuclease & more" });
    expect(String(args("x".repeat(600)).title)).toHaveLength(500);
  });

  it("goes only to a backend whose download tool declares it", () => {
    const declared = (title: boolean) => [{
      name: "carsi_download",
      inputSchema: {
        type: "object",
        properties: Object.fromEntries(Object.keys({ ...createCarsiDownloadArguments("10.1/x", "out", "legal_only"),
          ...(title ? { title: "" } : {}) }).map((name) => [name, {}])),
        required: ["identifier"],
      },
    }];
    expect(selectCarsiBatchSupport(declared(true) as any, "legal_only").titleField).toBe(true);
    expect(selectCarsiBatchSupport(declared(false) as any, "legal_only").titleField).toBeUndefined();
    expect(createCarsiDownloadArguments("10.1/x", "out", "legal_only", undefined, undefined, undefined, undefined,
      "A <b>title</b>")).toMatchObject({ title: "A title" });
    expect(createCarsiDownloadArguments("10.1/x", "out")).not.toHaveProperty("title");
  });

  it("is what the entitled-access step sends with the DOI", async () => {
    const requests: CarsiDownloadRequest[] = [];
    const backend = {
      downloadLegalDoi: async (request: CarsiDownloadRequest) => {
        requests.push(request);
        return { kind: "backend_unavailable" };
      },
    } as unknown as CarsiBackend;
    await createEntitledAccessTier(backend).run({
      useEntitledAccess: true, useSciHub: false, doi: "10.1126/science.1225829", paperId: "10.1126/science.1225829",
      title: "A Programmable Dual-RNA–Guided DNA Endonuclease in Adaptive Bacterial Immunity", savePath: "/tmp/out",
      source: "crossref", searchers: {} as any,
    });
    expect(requests[0]).toMatchObject({ identifier: "10.1126/science.1225829",
      title: "A Programmable Dual-RNA–Guided DNA Endonuclease in Adaptive Bacterial Immunity" });
  });
});
