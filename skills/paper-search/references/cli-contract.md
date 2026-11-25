# Command contract

This file records the stable commands this Skill can rely on. Do not write commands, parameters or defaults that are neither here nor in the current command.

## Entry points

- `paper-search` is the main command.
- `paper-search --version`, `paper-search -v`, `paper-search version` show the installed version.
- `paper-search --help`, `paper-search help` show usage.
- `paper-search tools --pretty` lists the tool names and parameter schemas that `run` can call directly.
- Private API keys, emails and tokens are configured through `paper-search setup`, `paper-search config`, `.env` or shell environment variables, never written into Skill files.

## Top-level commands

- `paper-search search <query> [--platform NAME] [--sources CSV] [--max-results N] [--year YEAR] [--pretty]`
- `paper-search run <tool-name> --arg key=value --json-args '{"key":"value"}' [--pretty]`
  - Windows PowerShell strips the double quotes from arguments passed to programs, so JSON written directly reports `is not valid JSON`: write the JSON to a UTF-8 file and pass `--json-args '@<file path>'` (quote it, since it starts with `@`). Do not write another script to work around it.
- `paper-search download <paper-id> --platform NAME [--save-path PATH] [--pretty]`
- `paper-search journal-metrics <journal...> [--file PATH] [--include-raw] [--pretty]`
- `paper-search metrics ...` is an alias of `journal-metrics`.
- `paper-search status [--validate] [--pretty]`
- `paper-search doctor [--validate] [--format text] [--pretty]`
- `paper-search failures [--run ID|--since YYYY-MM-DD|--runs N] [--doi DOI] [--export file.zip] [--all] [--format text] [--pretty]`
- `paper-search update check [--format text] [--pretty]` (checks only, does not install)
- `paper-search school install [--browser chrome|ego] [--yes] [--force] [--skip-school] [--format text]`
- `paper-search school status [--format text] [--pretty]`
- `paper-search school update [--force] [--format text] [--pretty]`
- `paper-search school login --doi <DOI> [--max-wait <seconds>] [--pretty]`
- `paper-search school uninstall [--yes] [--remove-data] [--format text] [--pretty]`
- `paper-search uninstall [--dry-run] [--yes] [--format text]`: uninstalls PaperSearch's data, configuration and the Skill in each tool; usage in "Uninstall" in `management-layer.md`
- `paper-search smoke --mock [--pretty]`
- `paper-search smoke --live [--pretty]`
- `paper-search skills status [--targets CSV] [--pretty]`
- `paper-search skills diff [--targets CSV] [--format text] [--pretty]`
- `paper-search skills update [--targets CSV] [--pretty]`
- `paper-search setup [--all] [--keys CSV] [--install-skills CSV] [--skip-skills]`
- `paper-search config test [KEY] [--stdin] [--format text]`: tests with one small request whether a key works (valid, rejected, rate-limited, unreachable); without KEY, tests all keys entered.
- `paper-search settings [about|download|wait|keys|<KEY>] [--format text]`: with school subscription downloads installed, opens the settings window (download folder, waits and alerts, API keys; about is the version and updates); when it is not installed or there is no graphical interface, returns an error with the terminal command.
- `paper-search tools [--pretty]`
- `paper-search diagnostics [--pretty]`
- `paper-search requirements [--pretty]` is an alias of `diagnostics`.
- `paper-search config init [--pretty]`
- `paper-search config path [--pretty]`
- `paper-search config keys [--pretty]`
- `paper-search config list [--all] [--pretty]`
- `paper-search config doctor [--pretty]` is a configuration summary kept for compatibility; for the full health report use the top-level `doctor`.
- `paper-search config get KEY [--raw] [--pretty]`
- `paper-search config set KEY VALUE [--pretty]`
- `paper-search config unset KEY [--pretty]`
- `paper-search config delete KEY [--pretty]` and `paper-search config remove KEY [--pretty]` are aliases of `unset`.
- `paper-search config import-env [file] [--pretty]`

The school download backend's own command `paper-search-school` (`issues`, `progress`, `preview`, `entitlements`, `setup`, `config`): see `browser-download.md` and `school-setup.md`; it is usually not on PATH; call it by the full backend path that `paper-search school status --format text` shows.

## Tools for direct calls

The names below can be used with `paper-search run <tool-name>`:

- `search_papers`
- `search_arxiv`
- `search_webofscience`
- `search_pubmed`
- `search_biorxiv`
- `search_medrxiv`
- `search_semantic_scholar`
- `search_semantic_snippets`
- `get_paper_citations`
- `get_paper_references`
- `search_iacr`
- `download_paper`
- `search_google_scholar`
- `get_paper_by_doi`
- `search_scihub`
- `check_scihub_mirrors`
- `get_platform_status`
- `query_journal_metrics`
- `search_sciencedirect`
- `search_springer`
- `search_scopus`
- `search_crossref`
- `search_openalex`
- `search_unpaywall`
- `search_pmc`
- `search_europepmc`
- `search_core`
- `search_openaire`
- `download_with_fallback`
- `download_batch`
- `search_dblp`
- `search_ieee`
- `search_acm`
- `search_usenix`
- `search_openreview`
- `search_springerlink`

## Output formats

- JSON by default, for agents and scripts.
- `--pretty` prints the JSON formatted.
- `--format text` is for the top-level `doctor`, `failures`, `school` and `skills diff`, used when the user clearly needs a readable report.
- `--include-text` keeps the tool's raw text in the JSON, in the commands that support it.
- Parse the JSON for decisions; use the text format only when the user needs a readable report.

## Search commands

- `paper-search search` is the integrated metadata search entry.
- `--platform NAME` queries one source; `--sources a,b,c` names several sources.
- `--sources no-key` (aliases `free`, `no_key`) expands to Crossref, PubMed, Europe PMC, arXiv and OpenReview; it does not call Google Scholar, and plain metadata search needs no API key from the user.
- `search_google_scholar` is still a best-effort web source that must be named explicitly: a single low-frequency client (default `SCHOLAR_RATE_LIMIT_RPS=0.5`), a limited number of transient retries, an in-process cache for one hour, and it recognizes verification pages; on a CAPTCHA or `/sorry` page it reports, and never retries blindly.
- `--platform all` or `--sources all` only when recall matters more than precision.
- `search_papers` is the tool behind the integrated `search` command.
- The count parameter of `search_semantic_snippets` is `limit`, not `maxResults`; it searches body, title and abstract snippets, not complete full texts.
- `search_unpaywall` looks up open-access metadata by DOI and returns at most one record.
- `search_scihub` looks up by DOI or URL; it is not a metadata search source.
- `CORE_MAX_RESULTS_CAP` sets CORE's result cap, default `100`, maximum `500`; other sources keep their own caps.

## Citation expansion

`get_paper_citations` finds the papers citing the target paper; `get_paper_references` finds the target paper's references. Both return all results and have no `limit`; each result comes from one source only, named in `provider`.

- Citations: all of OpenAlex's citing papers, newest first, with `citedByCount` (the citation count OpenAlex records). Without `OPENALEX_API_KEY`, at most the newest 10,000 are listed; with it, all. Only when OpenAlex lacks this paper is Semantic Scholar used (at most 1,000), and `notes` says so.
- References: when the publisher registered each reference's title or citation in Crossref (such as Elsevier, Springer Nature, Frontiers, Wolters Kluwer), this list is used, in the original order; when the original numbering can be seen, each item has `number`, and the result has `numberedTo` and `missing` (numbers the publisher left out). When the publisher registered only DOIs or nothing (such as Wiley, NEJM), OpenAlex's list is used, newest first. When neither has them, Semantic Scholar is used. `notes` explains why the source changed.

- Give at least one of `paperId`, `doi`, `arxivId`.
- Priority: `paperId`, then `doi`, then `arxivId`.
- `doi` becomes `DOI:<doi>`, `arxivId` becomes `ARXIV:<id>`.

```bash
paper-search run get_paper_citations --arg doi="10.1038/nature12373" --pretty
paper-search run get_paper_references --arg doi="10.1038/nature12373" --pretty
```

## Download commands

`download_paper` and `download_with_fallback` use the same download funnel; the source's own download belongs to the `primary` layer and is tried at most once.

The fixed order is `primary -> direct_pdf_url -> repositories -> unpaywall -> publisher_api -> scihub -> entitled_access -> preprint`. When Sci-Hub succeeds, the school download backend is not called; when Sci-Hub fails or is skipped, it goes on to the optional school download. `publisher_api` comes before Sci-Hub and uses the user's own `ELSEVIER_API_KEY` / `SPRINGER_API_KEY`; Springer's result is JATS XML, and then the top-level result has `format: "jats-xml"`.

The school download backend (school subscription downloads) is the only optional authorized download backend; it is off by default, enabled only when `PAPER_SEARCH_SCHOOL_ENABLED` is exactly `true`. Both download tools have `useEntitledAccess`, default `true`; `false` turns off this layer; `true` cannot bypass the global switch.

```json
{ "useEntitledAccess": false }
```

The Sci-Hub fallback is on by default. With `download_with_fallback`, to skip this layer and go on to the optional school download:

```json
{ "useSciHub": false }
```

Common usage:

```bash
# Install and enable school subscription downloads (asks before installing):
paper-search school install
# Or point at a backend installed elsewhere:
paper-search config set PAPER_SEARCH_SCHOOL_EXECUTABLE /absolute/path/to/paper-search-school
paper-search config set PAPER_SEARCH_SCHOOL_ENABLED true
paper-search doctor --pretty
paper-search download "<DOI>" --platform crossref
paper-search run download_with_fallback --json-args '{"source":"crossref","paperId":"<DOI>","doi":"<DOI>","title":"<paper title>","useSciHub":false,"useEntitledAccess":true}'
```

For a set of papers (dozens or more, no upper limit), use one `download_batch`, which runs them in order; do not loop over single downloads:

- `"mode"`: default `"two_phase"`: each paper tries the open channels first, and those not found go straight on to the school download (one at a time); the two run side by side, and the browser and school login appear within seconds of the start; the progress window counts the whole batch (k / N), and with school subscription downloads installed, batches of 5 or more papers show it from the start; `"per_item"` takes each paper through the whole funnel; `"entitled_only"` is school only: it skips the open channels and each paper goes straight to the school download; use it when the user wants only the school download, or to test the school route. `resume` ("go on", 接着下) without `mode` keeps the batch's original mode.
- Without `savePath`, files go to `DEFAULT_DOWNLOAD_PATH`; the whole batch or each paper can have its own `savePath`; pass it only when the user names another folder.
- `"folderName"`: this batch's own folder name, named for its contents (a journal's papers: the same journal abbreviation that begins each paper's folder, plus years, such as `"Osteoarthritis Cartilage_2024-2026"`), created in the download folder (or `savePath`); each paper's folder goes straight into it, beside `_run/` (the download arguments, the progress log, each run's details, and the list of every paper's result, `article_index.csv`). "go on" (接着下) fills in the same folder. Without it, a new `<YYYYMMDD-HHmmss>_PaperSearchDownload` is created, with the same layout.
- `"content"`: the two contents are each fetched on their own, and both can be wanted, joined with commas: `"pdf"` (the full-text PDF, default), `"supplements"` (this article's supplementary files; alone, it skips the full-text layers), such as `"pdf,supplements"`. The batch result's `content` echoes it in the same form. Supplementary files are saved in `<savePath>/<journal abbreviation_year-month_title>/supplements/` (another paper with the same name in the same download gets `_2`) (when only the full text was downloaded, it goes straight into `<savePath>`); the list and browser diagnostics are in `diagnostics/` of the run-log directory that the result's `runLog` points to (`records/` when everything was downloaded), and the result's `supplements` gives each file's status; they are fetched only through the school download backend; which publishers have rules: see `publisher-support.md`.
- Each download writes a local run log; the result's `runLog` is its directory (`run.json`; `items.jsonl`, with each layer's timing and code, and the backend's page events and screenshots; `timeline.log`). Read it when investigating failures; do not guess.
- The batch result gives only a summary, not each paper: `status`, `total`, `succeeded`, `failed`, `failureClasses` (failures per class), `supplementsMissing` (papers with the PDF but with incomplete supplementary files), `folder` (the batch folder) and `index` (the list of each paper's result, `_run/article_index.csv`). For each paper's PDF, supplementary files and failure reason, see `index`; to explain failures by class, use `paper-search failures --format text`; each attempt is in `runLog`.

```bash
paper-search run download_batch --json-args '{"items":[{"doi":"<DOI-1>","title":"<title 1>"},{"doi":"<DOI-2>"}],"folderName":"<batch folder name>","useSciHub":false}'
```

When an outside loop must call `download_with_fallback` paper by paper, pass `"batch":{"id":"<the same id>","index":k,"total":N,"done":…,"succeeded":…,"failed":…}` to get the same progress window.

Command-line arguments use kebab-case; JSON arguments use the camelCase of the tool definitions. `--platform` / `source` choose the paper's metadata source, not the backend. `useSciHub`, `doi` and `title` exist only on `download_with_fallback`, not on `download_paper` and its short form `download`. The backend path is optional configuration; it neither enables the school download backend nor changes its configuration; PaperSearch starts the configured backend (`PAPER_SEARCH_SCHOOL_EXECUTABLE`) with `run`; the user does not need to start a service before each download.

Supported progress notices are bound to the current request and written to stderr as fixed text; by default stdout has only the final JSON, not a line-by-line progress stream. Old backends that send no notices give no guessed stages. A saved PDF still needs its identity checked; an error with `review.path` is not a successful download. Manual sign-in, screenshot previews bound to the request, and the boundaries for supplementary files are in `browser-download.md`.

The school download backend is installed, checked, updated and uninstalled only with `paper-search school install` / `status` / `update` / `uninstall`; do not make up other install commands, account sign-in flows or ways of choosing the backend. The backend has its own MCP stdio service; PaperSearch needs no separate MCP, global MCP configuration, resident process or port.

Publisher and database keys used elsewhere in the command cannot serve as a local authorized PDF backend: `ELSEVIER_API_KEY` and `SPRINGER_API_KEY` are also used for the `publisher_api` layer (calling full-text APIs directly over HTTPS, with access following the user's network or key); browser-based institutional access is handled only by the optional school download backend. The school download adapter fixes `strategy=legal_only` (`institutional_only` when the backend declares support for it), `scihub_enabled=false` and `use_tor=false`, but `legal_only` cannot prove that the result came from school authorization. Apart from the school download backend, there is no browser, WebVPN or EZProxy fallback.

## Configuration and key boundaries

Configuration sources, by priority:

1. Shell environment variables
2. `.env` in the current directory
3. The user configuration file `~/.config/paper-search-cli/config.json`
4. Built-in defaults for free sources

Common configuration commands:

```bash
paper-search setup
paper-search config set DEFAULT_DOWNLOAD_PATH "~/Documents/Papers"
paper-search config set PAPER_SEARCH_SCHOOL_ENABLED true
paper-search config set SEMANTIC_SCHOLAR_API_KEY your_key
paper-search setup EASYSCHOLAR_KEY
paper-search settings EASYSCHOLAR_KEY
paper-search config list --pretty
paper-search doctor --pretty
```

The output of `doctor` and `config` masks configured keys.

`PAPER_SEARCH_SCHOOL_ENABLED` is a strict switch and not a secret: only the string `true` enables it; `TRUE`, `1`, `yes` or values with surrounding spaces all count as off.

The user's school is configured with `paper-search-school setup --institution "<school>"`, with the same data directory as the downloads; see `school-setup.md`. Write only the school the user told you; `doctor=available` cannot be presented as proof that the school session is valid or that there is access to any paper.

### arXiv

`search_arxiv`: `query` is required; `maxResults`, `category`, `author`, `year`, `sortBy`, `sortOrder` are optional. For example: `paper-search run search_arxiv --arg query="transformer" --arg maxResults=3 --pretty`.

`paper-search download 1706.03762 --platform arxiv` also follows the published-version-first policy; when it returns `version: "preprint"`, you must say clearly that a preprint was obtained. `publishedDoi` is a metadata link and does not mean the published version was downloaded. The `entitled_only` batch mode does not try preprints.
