# Capability routing

Use this file to map the user's literature request to one of the five literature capabilities of `paper-search`.

## Capability map

| User intent | Capability | Preferred entry | Boundary |
|---|---|---|---|
| Search papers, find related studies, verify DOI/PMID, first screening | `metadata_search` | `paper-search search` integrated entry / `paper-search run search_*` exact tool entry | Returns and verifies paper metadata only; Sci-Hub is not a search source |
| Expand the citation network of a known paper | `citation_expansion` | `paper-search run get_paper_citations` / `paper-search run get_paper_references` | Needs a known `paperId`, DOI or arXiv ID; returns citing papers or references; not a keyword search |
| Impact factor, JCR/SSCI/CAS zones, JCI, ESI, warning lists, journal grades | `journal_metrics` | `paper-search journal-metrics` / `paper-search run query_journal_metrics` | Looks up journals, not papers; needs `EASYSCHOLAR_KEY` |
| Get or download the PDF and supplementary files of a verified paper | `pdf_discovery` | `paper-search download` / `paper-search run download_with_fallback` / `download_batch` | Verify identity before downloading; after the open channels come Sci-Hub (when on) and school subscription downloads (when enabled) |
| Find how Methods are written, parameters, software, models or statistical wording in body snippets | `body_snippet_search` | `paper-search run search_semantic_snippets` | Searches the Semantic Scholar open-access snippet index; needs `SEMANTIC_SCHOLAR_API_KEY`; not full-text parsing |

## Workflow boundaries

Open-ended literature tasks take two steps:

1. Do `metadata_search`: put together and verify the list of papers, with title, authors, year, journal or source, DOI, PMID/PMCID, URL, abstract clues and relevance.
2. Do `pdf_discovery` only after the user confirms the chosen papers, or the task clearly needs PDFs. Record the reason for each failed download and do not let it block the others.

When the user gives a DOI, PMID, PMCID or a verified list, the broad search can be skipped, but the target's identity is still verified before downloading.

Do not make up PMIDs, DOIs, titles, authors, journals or years from model memory. For an important citation, give the point it supports, the title, authors, journal or source and year, the DOI or PMID when there is one, and a stable URL.

## Metadata search

`metadata_search` is for finding papers, expanding keywords, first screening, and verifying DOI/PMID/PMCID.

`paper-search search` is the integrated metadata search entry:

- `--platform NAME`: one source only;
- `--sources a,b,c`: several named sources;
- `--platform all` or `--sources all`: only when recall matters more than precision.

It does not call `citation_expansion`, `journal_metrics`, `pdf_discovery` or `body_snippet_search`.

```bash
paper-search search "machine learning" --platform crossref --max-results 5 --pretty
paper-search search "osteoarthritis occupational exposure" --platform pubmed --max-results 10 --pretty
paper-search search "transformer attention mechanism" --sources semantic,crossref,openalex --max-results 5 --pretty
paper-search search "causal inference target trial emulation" --sources all --max-results 5 --pretty
```

Exact tool entry:

```bash
paper-search run search_pubmed --arg query="osteoarthritis occupational exposure" --arg maxResults=10 --pretty
paper-search run search_openalex --arg query="causal inference target trial emulation" --arg maxResults=5 --pretty
paper-search run get_paper_by_doi --arg doi="10.xxxx/xxxxx" --pretty
```

Do not use `search_scihub` as a search source: it looks up by DOI or URL and is not part of `metadata_search`.

## Citation expansion

`citation_expansion` is for when the user has a known paper and asks which papers cite it, or what it cites.

```bash
paper-search run get_paper_citations --arg doi="10.1038/nature12373" --pretty
paper-search run get_paper_references --arg doi="10.1038/nature12373" --pretty
```

The identifier priority is `paperId` > `doi` > `arxivId`. Citing papers come from OpenAlex, reference lists from the publisher's Crossref deposit or else OpenAlex (`cli-contract.md`); a Semantic Scholar `paperId` is first turned into its DOI through the Semantic Scholar Graph API. This is separate from the keyword-based `metadata_search`.

## Journal metrics

`journal_metrics` looks up journal-level metrics: impact factor, JCR/SSCI quartiles, CAS zones, JCI, ESI, warning lists and grades.

```bash
paper-search journal-metrics "Nature" "BMJ" --pretty
paper-search journal-metrics --file journals.txt --include-raw --pretty
paper-search run query_journal_metrics --json-args '{"journals":["Nature"],"includeRaw":true}' --pretty
```

Needs `EASYSCHOLAR_KEY`. Without it, give the user the sign-up address from the error, and ask the user to configure it in their own terminal:

```bash
paper-search setup EASYSCHOLAR_KEY
```

When school subscription downloads are installed and the user is at this computer, you can also run `paper-search settings EASYSCHOLAR_KEY` to open the settings window for the user to fill in.

For many journals, use one `journal-metrics` with several journal names or `--file`; do not send EasyScholar requests in parallel.

## PDF retrieval

`pdf_discovery` gets the PDFs of verified papers. Do not start an open-ended literature task with a batch download.

```bash
paper-search download PMC11466435 --platform pmc --pretty
paper-search run download_paper --arg paperId="10.xxxx/xxxxx" --arg platform=springer --pretty
paper-search run download_with_fallback --json-args '{"source":"crossref","paperId":"10.xxxx/xxxxx","doi":"10.xxxx/xxxxx","title":"Paper title"}' --pretty
```

Without `savePath`, files go to `DEFAULT_DOWNLOAD_PATH` (see "Default download folder" in SKILL.md); pass `savePath` / `--save-path` only when the user names another folder for this download.

Downloads come in two kinds: steps 1–6 are open download (available by default), step 7 is the school download (school subscription downloads, `entitled_access`, installed on a computer with the user's consent). The order of `download_with_fallback`:

1. The source's own download;
2. The PDF address in the metadata;
3. PubMed Central's official channels: DOI → PMCID (NCBI ID conversion) → the PDF in PMC Article Datasets (S3), otherwise Europe PMC's `getPdf`; CORE and OpenAIRE are search sources only;
4. Unpaywall: all open-access locations, the published version first; copies on sites that refuse plain HTTP downloads (Wiley, ScienceDirect, Springer, MDPI, PMC, etc.) are marked `browser_only` and left to `entitled_access`; arXiv copies are left to the final `preprint` stage;
5. `publisher_api`: the user's own `ELSEVIER_API_KEY` (PDF) or `SPRINGER_API_KEY` (JATS XML full text), over plain HTTPS; skipped without a key; `not_entitled` when the network or the key has no subscription;
6. PaperSearch's Sci-Hub, unless `useSciHub=false`;
7. The optional school download backend (`entitled_access`);
8. arXiv preprint (`preprint`): tried only when no published-version route got the full text; on success you must tell the user `version: "preprint"`.

Fixed order: `primary -> direct_pdf_url -> repositories -> unpaywall -> publisher_api -> scihub -> entitled_access -> preprint`. `download_paper` enters the same funnel, and the source's own download is tried at most once. When Sci-Hub succeeds, the school download backend is not called; only when Sci-Hub fails or is skipped does it go on to `entitled_access`.

The school download backend (school subscription downloads) is the only optional authorized download backend. It is off globally unless `PAPER_SEARCH_SCHOOL_ENABLED` is exactly `true`; the request's `useEntitledAccess` defaults to `true` and can only turn off this layer, never bypass the global switch. To turn it off for one request:

```bash
paper-search run download_with_fallback --json-args '{"source":"crossref","paperId":"10.xxxx/xxxxx","doi":"10.xxxx/xxxxx","title":"Paper title","useEntitledAccess":false}' --pretty
```

The Sci-Hub fallback is on by default. To skip Sci-Hub for one request and go straight on to the optional school download:

```bash
paper-search run download_with_fallback --json-args '{"source":"crossref","paperId":"10.xxxx/xxxxx","doi":"10.xxxx/xxxxx","title":"Paper title","useSciHub":false}' --pretty
```

What to download is chosen with `content`: `pdf` (the full-text PDF, default), `supplements` (supplementary files, fetched only through the school download backend; which publishers: see `publisher-support.md`); both can be wanted (`"pdf,supplements"`); details in `browser-download.md`.

PDF source groups:

- `open_access_sources`: bioRxiv, medRxiv, PMC, Europe PMC, CORE, OpenAIRE, Unpaywall, OpenAlex's open-access metadata, Semantic Scholar's openAccessPdf, publishers' open-access modes, IACR;
- `scihub_sources`: Sci-Hub, marked separately: a layer on by default after the open channels and before the school download; it is neither open access nor institutional authorization.

`metadata_entitled` is the metadata class for databases and publishers with keys; it cannot serve as a local authorized PDF backend. The school download backend is called only through PaperSearch's fixed `SchoolBackend` interface; it is installed with `paper-search school install` when the user asks (see `school-setup.md`), and has its own MCP stdio service; no separate MCP package, global MCP configuration, resident process or port is needed.

When calling the school download backend, always use `legal_only` (or `institutional_only` when the backend declares support for it, skipping the backend's own race among public sources), and turn off the backend's internal Sci-Hub and Tor. `legal_only` is not `entitled_only`: a successful result may also come from open access, and cannot prove school authorization. Apart from the school download backend, there is no browser, WebVPN or EZProxy fallback.

## Verify papers

Verify key papers before reporting them:

```bash
paper-search run search_pubmed --arg query="37654321[PMID]" --arg maxResults=1 --pretty
paper-search run get_paper_by_doi --arg dois="10.xxxx/aaaaa,10.xxxx/bbbbb,10.xxxx/ccccc" --pretty
paper-search run search_crossref --arg query="full paper title" --arg maxResults=3 --pretty
```

To check several DOIs, pass them at once with `dois` (comma-separated, up to 100); do not call them one by one; with only one, `--arg doi=...` works too. The result has a fixed structure:
- `data.papers`: the papers found, one per DOI, in the order given;
- `data.not_found`: DOIs that every source checked and none had; they may be mistyped or not exist;
- `data.lookup_failed`: DOIs that could not be checked because every source erred; retry later; do not treat them as nonexistent;
- `data.warnings`: the sources that erred.

Crossref is checked first by default; only the DOIs it lacks go to other sources; to see each source's own record, add `--arg platform=all`. The `data` returned by `paper-search search` is itself the list of papers.

A PMID is confirmed by PubMed; a DOI by a DOI lookup or the results of Crossref, OpenAlex or Semantic Scholar. The PMID, DOI, title, first author and year of one paper should agree; when they do not, mark it as doubtful.

## Body snippet search

`body_snippet_search` finds body-snippet clues such as how Methods are written, parameters, software names, model descriptions and statistical wording.

```bash
paper-search run search_semantic_snippets --arg query="comparative risk assessment methods uncertainty propagation" --arg limit=5 --arg fieldsOfStudy=Medicine --pretty
```

`search_semantic_snippets` needs `SEMANTIC_SCHOLAR_API_KEY`, and its count parameter is `limit`, not `maxResults`. Without the key, give the user the sign-up address from the error and `paper-search setup SEMANTIC_SCHOLAR_API_KEY` (with a settings window, `paper-search settings SEMANTIC_SCHOLAR_API_KEY` also works).

Only results with `snippetKind="body"` can serve as body-snippet evidence; those from `title` or `abstract` are only clues. Before citing or relying on a snippet, verify the title, authors, year, journal or source, DOI or PMID.

When giving a body snippet in an answer, quote the original English sentence as it is (no translation, no rewording, no joining of sentences), and on the next line give the source, using this result's `source` directly (first author et al., year, journal · section · DOI · license); when an explanation in another language (such as Chinese) is wanted, put it in a separate paragraph:

```text
> "The primary outcome in the DAPA-HF trial was the composite of … whichever occurred first."
> —— M. Kosiborod et al., 2019, Circulation · Clinical outcomes · DOI 10.1161/CIRCULATIONAHA.119.044138 · CC BY
```

- Results matched in `title` or `abstract` do not use this format; when listing them, mark them "clue (abstract)" or "clue (title)", in the user's language.
- When `paper.metadataStatus` is not `found`, the source has no year, journal or DOI: write "DOI to be verified", and look it up with the verification steps above before citing it; for `lookup_failed`, the command's first line says so.

## Choose sources

| Task | Preferred | Also |
|---|---|---|
| Biomedicine, clinical medicine, pharmacy, public health | `pubmed` | `pmc`, `europepmc`, `semantic`, `crossref` |
| Methods, body-snippet clues | `search_semantic_snippets` | first use `pubmed`, `semantic` to find titles and synonyms |
| Citation network expansion | `get_paper_citations`, `get_paper_references` | only after the target paper's identifier is known |
| Computer science, AI, mathematics, physics | `semantic`, `dblp` | `crossref`, `openalex`, `openreview` |
| Computer science bibliography and conference metadata | `dblp` | `acm`, `usenix`, `openreview`; `ieee` needs a key |
| Cross-disciplinary coverage | `crossref` | `openalex`, `semantic` |
| Find open-access full text | the layers of `download_with_fallback` (PMC official channels, Unpaywall) | `download_with_fallback` |
| Journal impact factor, quartiles, grades | `journal-metrics` | `query_journal_metrics` |
| Cryptography | `iacr` | `dblp` |
| Sort by citation count | `semantic`, `crossref`, `openalex` | `webofscience`, `scopus` need keys |
| Metadata of publishers or paid databases | `webofscience`, `ieee`, `scopus`, `sciencedirect`, `springer` / `springerlink` | only with the matching metadata key configured; this does not authorize PDF downloads |

## Build search terms

- Research questions in Chinese (or another language) are translated into English keywords by default.
- Use 3–8 core concept words, not long sentences.
- Add MeSH or standard terms for medical topics when needed.
- For method details, add software names, parameter names, model names, or section words such as `methods`, `statistical analysis`, `adjusted for`, `bootstrap`, `sensitivity analysis`.
