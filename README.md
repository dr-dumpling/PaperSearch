# PaperSearch

[简体中文](README.zh.md) | English

PaperSearch is an agent-facing Skill + CLI package built on a standalone Node.js command line tool for academic literature work. It gives AI agents, terminal users, and scripts one reproducible command layer with agent-friendly JSON output for literature metadata search, citation expansion, journal metrics lookup, PDF discovery/download, and paper body snippet search.

![Node.js](https://img.shields.io/badge/node.js->=18.0.0-green.svg)
![TypeScript](https://img.shields.io/badge/typescript-^5.5.3-blue.svg)
![License](https://img.shields.io/badge/license-MIT-blue.svg)
![Platforms](https://img.shields.io/badge/platforms-25-brightgreen.svg)
![Version](https://img.shields.io/badge/version-0.4.0-blue.svg)
[![LinuxDo](https://img.shields.io/badge/LinuxDo-community-1f6feb)](https://linux.do)

[Quick Start](#quick-start) | [Architecture](#architecture) | [Configuration](#configuration) | [Agent Skill](#agent-skill) | [Supported Platforms](#supported-platforms) | [Commands](#commands) | [Troubleshooting](#troubleshooting)

## Core Workflows

| Workflow                   | Primary commands                                                                | What it returns                                                                                                                    |
| -------------------------- | ------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------- |
| Literature metadata search | `paper-search search`, `paper-search run search_*`                              | Paper title, authors, year, journal, DOI, PMID/PMCID, URL, abstract, and source metadata                                 |
| Citation expansion         | `paper-search run get_paper_citations`, `paper-search run get_paper_references` | Citing papers and cited references for a known Semantic Scholar paper ID, DOI, or arXiv ID                                         |
| Journal metrics lookup     | `paper-search journal-metrics`, `paper-search run query_journal_metrics`        | Impact factor, 5-year IF, JCR/SSCI quartile, CAS zone, JCI, ESI, warning flags, and rank fields                                    |
| PDF discovery and download | `paper-search download`, `paper-search run download_with_fallback`              | Verified PDF paths through native public sources, open access, repositories, Unpaywall, Sci-Hub when enabled, and the optional CARSI backend |
| Body snippet search        | `paper-search run search_semantic_snippets`                                     | Semantic Scholar Open Access body snippets for methods, parameters, and wording clues                                              |

## Architecture

`paper-search` is not an MCP server. It is a normal CLI that AI agents can call through the bundled Skill, while terminal users and scripts can call the same `paper-search` command directly.

| Layer                     | Responsibility                                                                                                                                                                                                                                                                                                                                                                                                             |
| ------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| CLI package body          | Executes literature search, citation expansion, journal metrics lookup, PDF discovery/download, body snippet search, and stable JSON output                                                                                                                                                                                                                                                                                |
| Bundled Skill             | Ships `skills/paper-search` with agent routing rules and focused references; it does not store API keys, cookies, or account credentials                                                                                                                                                                                                                                                                                   |
| Friendly Management Layer | Provides `doctor`, `smoke`, `skills`, `config`, and `tools` around the five main capabilities: `metadata_search`, `citation_expansion`, `journal_metrics`, `pdf_discovery`, and `body_snippet_search`. `doctor` health reports include masked configuration, Capability Profile, platform/source status, and missing or degraded items; `smoke` checks command wiring and live readiness; `skills` syncs the bundled Skill |

The five main capabilities are executed by the CLI package body and reported by the management layer. The Capability Profile also reports the optional `entitled_access` tier. The CARSI backend is its only optional Entitled Download Backend and is disabled by default. `doctor` reports `disabled`, `absent`, `incompatible`, or `available`; offline profiles that intentionally do not start the backend report `not_evaluated`. Publisher and database keys may still enable `metadata_entitled` records or open-access endpoints, but they must not be interpreted as a local authorized-PDF backend. Missing or degraded configuration for one workflow does not make unrelated workflows unavailable.

## Quick Start

Requires Node.js >= 18.0.0 and npm.

```bash
npm install -g papersearch
paper-search setup
paper-search doctor --pretty
```

`paper-search setup` asks three things in turn: API keys and email; which AI tools to install the Skill into (Claude Code, Codex, Cursor, ...); and whether to install the institutional download extension. The Skill is the instruction file that teaches an AI tool how to call paper-search; install it when you use an AI tool for literature work. If you skipped it, install it any time, with `--targets` set to your tool (`claude`, `codex`, `cursor`, `gemini`, `agents`, or `all`):

```bash
paper-search skills update --targets claude
```

Coming from the old package `paper-search-cli`: run `npm uninstall -g paper-search-cli`, then `npm install -g papersearch` (both provide the same `paper-search` command and cannot be installed together); your configuration, Skill, school login and download records stay.

After later upgrades (`npm install -g papersearch@latest`), the first `paper-search` run brings the Skill you installed up to the new version; see [Agent Skill](#agent-skill).

You can also send this to your AI tool and let it do the install:

```text
Please install PaperSearch for me: run npm install -g papersearch, then paper-search skills update --targets <your own target: claude for Claude Code, codex for Codex, cursor for Cursor>, then paper-search doctor --format text, and tell me which features work and which keys are missing. I will enter API keys myself with paper-search setup in a terminal; do not ask me to paste them into the chat.
```

Try the five main workflows:

```bash
paper-search search "machine learning clinical prediction" --platform crossref --max-results 3 --pretty
paper-search search "large language models" --sources no-key --max-results 5 --pretty
paper-search run get_paper_citations --arg doi="10.1038/nature12373" --arg limit=5 --pretty
paper-search journal-metrics "Nature" "BMJ" --pretty
paper-search download PMC11466435 --platform pmc --save-path ./downloads
paper-search run search_semantic_snippets --arg query="propensity score matching" --arg limit=3 --pretty
```

Useful checks:

```bash
paper-search tools --pretty
paper-search doctor --format text
paper-search smoke --mock --pretty
paper-search skills status --pretty
```

## Supported Platforms

The quick group table helps choose a source family. The capability matrix below is the clearer source of truth for what each platform can actually do.

### Platform Groups

| Family                           | Platforms                                                           | Main use                                                                      |
| -------------------------------- | ------------------------------------------------------------------- | ----------------------------------------------------------------------------- |
| General scholarly metadata       | Crossref, OpenAlex, Semantic Scholar, Google Scholar                | Broad discovery, DOI metadata, citation clues, first-pass screening           |
| Journal metrics                  | EasyScholar                                                         | Impact factor, JCR/SSCI quartile, CAS zone, JCI, ESI, warning flags           |
| Biomedical and life sciences     | PubMed, PubMed Central, Europe PMC                                  | Biomedical metadata, PMID/PMCID verification, open full text                  |
| Preprints and conference papers  | bioRxiv, medRxiv, OpenReview, IACR ePrint                           | Preprints, AI/ML submissions, cryptography ePrints                            |
| Computer science and engineering | DBLP, ACM metadata, IEEE Xplore, USENIX                             | CS bibliography, engineering metadata, conference proceedings                 |
| Open access and repositories     | CORE, OpenAIRE, Unpaywall                                           | Repository discovery and open-access PDF fallback                             |
| Citation indexes and publishers  | Web of Science, Scopus, ScienceDirect, Springer Nature/SpringerLink | Key-backed metadata and publisher records; not a local authorized-PDF backend |
| DOI-targeted fallback            | Sci-Hub                                                             | DOI-based PDF fallback when enabled                                           |

### Capability Matrix

#### General Scholarly Metadata

| Platform         | Metadata search | PDF path       | Body/full text   | Citation signal | Config                                                   | Notes                                                                                          |
| ---------------- | --------------- | -------------- | ---------------- | --------------- | -------------------------------------------------------- | ---------------------------------------------------------------------------------------------- |
| Crossref         | ✅ Yes          | ❌ No          | ❌ No            | ✅ Yes          | ❌ None                                                  | Default broad metadata source                                                                  |
| OpenAlex         | ✅ Yes          | 🟡 Conditional | ❌ No            | ✅ Yes          | ❌ None                                                  | Free metadata; OA links can help PDF fallback                                                  |
| Semantic Scholar | ✅ Yes          | 🟡 Conditional | ✅ Body snippets | ✅ Yes          | 🟡 Optional; snippets require `SEMANTIC_SCHOLAR_API_KEY` | Good for AI/CS, citation expansion, and body snippet clues                                     |
| Google Scholar   | ✅ Yes          | ❌ No          | ❌ No            | ✅ Yes          | 🟡 Optional `GOOGLE_SCHOLAR_PROXY_URL`                   | Best-effort page parsing; explicit source only because Scholar may challenge automated traffic |

#### Journal Metrics

| Platform    | Metadata search         | PDF path | Body/full text | Citation signal | Config                        | Notes                                                                       |
| ----------- | ----------------------- | -------- | -------------- | --------------- | ----------------------------- | --------------------------------------------------------------------------- |
| EasyScholar | 🟡 Journal metrics only | ❌ No    | ❌ No          | ❌ No           | ✅ Required `EASYSCHOLAR_KEY` | Impact factor, JCR/SSCI quartile, CAS zone, JCI, ESI, warnings, rank fields |

#### Biomedical and Life Sciences

| Platform       | Metadata search | PDF path       | Body/full text | Citation signal | Config                                                  | Notes                                        |
| -------------- | --------------- | -------------- | -------------- | --------------- | ------------------------------------------------------- | -------------------------------------------- |
| PubMed         | ✅ Yes          | ❌ No          | ❌ No          | ❌ No           | 🟡 Optional `PUBMED_API_KEY`, `NCBI_EMAIL`, `NCBI_TOOL` | NCBI E-utilities biomedical metadata         |
| PubMed Central | ✅ Yes          | ✅ Yes         | ✅ Yes         | ❌ No           | ❌ None                                                 | Open biomedical full text and PMC PDFs       |
| Europe PMC     | ✅ Yes          | 🟡 Conditional | 🟡 Conditional | ❌ No           | ❌ None                                                 | Biomedical metadata and open full-text links |

#### Preprints and Conference Papers

| Platform    | Metadata search | PDF path | Body/full text | Citation signal | Config  | Notes                                             |
| ----------- | --------------- | -------- | -------------- | --------------- | ------- | ------------------------------------------------- |
| bioRxiv     | ✅ Yes          | ✅ Yes   | ✅ Yes         | ❌ No           | ❌ None | Biology preprints                                 |
| medRxiv     | ✅ Yes          | ✅ Yes   | ✅ Yes         | ❌ No           | ❌ None | Medical preprints                                 |
| OpenReview  | ✅ Yes          | ❌ No    | ❌ No          | ❌ No           | ❌ None | Public OpenReview notes, reviews, and submissions |
| IACR ePrint | ✅ Yes          | ✅ Yes   | ✅ Yes         | ❌ No           | ❌ None | Cryptography ePrint papers                        |

#### Computer Science and Engineering

| Platform     | Metadata search | PDF path | Body/full text | Citation signal | Config                     | Notes                                                                 |
| ------------ | --------------- | -------- | -------------- | --------------- | -------------------------- | --------------------------------------------------------------------- |
| DBLP         | ✅ Yes          | ❌ No    | ❌ No          | ❌ No           | ❌ None                    | Official DBLP computer-science bibliography                           |
| ACM metadata | ✅ Yes          | ❌ No    | ❌ No          | ✅ Yes          | ❌ None                    | Uses Crossref ACM DOI-prefix metadata; does not scrape ACM pages      |
| USENIX       | ✅ Yes          | ❌ No    | ❌ No          | ❌ No           | ❌ None                    | Uses DBLP-backed USENIX metadata; does not scrape USENIX search pages |
| IEEE Xplore  | ✅ Yes          | ❌ No    | ❌ No          | ✅ Yes          | ✅ Required `IEEE_API_KEY` | Official IEEE Xplore Metadata API                                     |

#### Open Access and Repositories

| Platform  | Metadata search    | PDF path       | Body/full text | Citation signal | Config                                                          | Notes                                                         |
| --------- | ------------------ | -------------- | -------------- | --------------- | --------------------------------------------------------------- | ------------------------------------------------------------- |
| CORE      | ✅ Yes             | 🟡 Conditional | 🟡 Conditional | ❌ No           | 🟡 Optional `CORE_API_KEY`                                      | Repository records may expose PDF or full-text links          |
| OpenAIRE  | ✅ Yes             | 🟡 Conditional | ❌ No          | ❌ No           | 🟡 Optional `OPENAIRE_API_KEY`                                  | Public search usually works without a key                     |
| Unpaywall | 🟡 DOI lookup only | 🟡 Conditional | ❌ No          | ❌ No           | ✅ Required `UNPAYWALL_EMAIL` or `PAPER_SEARCH_UNPAYWALL_EMAIL` | Finds DOI-based open-access PDF locations; email, not API key |

#### Citation Indexes and Publishers

| Platform                       | Metadata search | PDF path                | Body/full text | Citation signal | Config                                                                    | Notes                                                                             |
| ------------------------------ | --------------- | ----------------------- | -------------- | --------------- | ------------------------------------------------------------------------- | --------------------------------------------------------------------------------- |
| Web of Science                 | ✅ Yes          | ❌ No                   | ❌ No          | ✅ Yes          | ✅ Required `WOS_API_KEY`                                                 | Citation database metadata, date sorting, year ranges                             |
| ScienceDirect                  | ✅ Yes          | 🟡 OA / `publisher_api` | ❌ No          | ✅ Yes          | ✅ Required `ELSEVIER_API_KEY`                                            | Elsevier metadata; the key does not provide a local authorized-PDF fallback       |
| Springer Nature / SpringerLink | ✅ Yes          | 🟡 Open access only     | ❌ No          | ❌ No           | ✅ Required `SPRINGER_API_KEY`; 🟡 Optional `SPRINGER_OPENACCESS_API_KEY` | `springerlink` is an alias for the Springer integration                           |
| Scopus                         | ✅ Yes          | 🟡 Conditional metadata | ❌ No          | ✅ Yes          | ✅ Required `ELSEVIER_API_KEY`                                            | Abstract and citation database; product permission is separate from ScienceDirect |

#### DOI-Targeted Fallback

| Platform | Metadata search | PDF path | Body/full text | Citation signal | Config  | Notes                                                                         |
| -------- | --------------- | -------- | -------------- | --------------- | ------- | ----------------------------------------------------------------------------- |
| Sci-Hub  | ❌ No           | ✅ Yes   | ❌ No          | ❌ No           | ❌ None | DOI/URL-targeted fallback after OA routes and before optional entitled access |

Notes:

- `Metadata search` means finding and screening papers; it is not the same as PDF download or body evidence.
- `pdf_discovery` keeps open-access sources, repositories, Unpaywall, Sci-Hub, and the optional CARSI backend independently classified. The CARSI backend is the only optional Entitled Download Backend.
- EasyScholar is a journal metrics source, not a paper search source.
- Sci-Hub is not part of `metadata_search`; it is DOI/URL-targeted PDF fallback.
- `🟡 Conditional` means the platform can help only when the record exposes a DOI, open-access link, or public PDF URL. It does not imply authorized full-text access.
- API keys are only required when you use the corresponding key-backed source or workflow.
- Google Scholar is excluded from `--sources all` to avoid amplifying anti-bot limits. Use `--platform googlescholar` or `--sources googlescholar` explicitly; if needed, set `GOOGLE_SCHOLAR_PROXY_URL` to an authorized HTTP(S) or SOCKS proxy.
- The Scholar adapter follows the low-volume client pattern used by [bingshuoguo/google-scholar-mcp](https://github.com/bingshuoguo/google-scholar-mcp): one keep-alive client, a default `0.5` requests/second limiter, bounded retries, result caching, and immediate classification of CAPTCHA/`/sorry` challenge pages. It is still best-effort HTML scraping, not an official API.
- `--sources no-key` (aliases: `free`, `no_key`) is the strict no-user-key fallback bundle: Crossref, PubMed, Europe PMC, and OpenReview. Results retain their actual `source` fields and are not presented as Google Scholar results. Semantic Scholar is intentionally excluded because its stable quota may require a key.

## Configuration

Most free metadata sources work without configuration. For stable agent workflows, run setup once and store credentials in the user config file:

```bash
paper-search setup
paper-search config list --pretty
paper-search doctor --pretty
```

Default config path:

```text
~/.config/paper-search-cli/config.json
```

The config file is written with `0600` permissions. `config list`, `doctor`, and related commands mask secrets.

### API Key Tiers

| Tier                                 | Keys                                                                                                 | Used for                                                                                                | When to configure                                                                                                                                              |
| ------------------------------------ | ---------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Recommended for most users           | `SEMANTIC_SCHOLAR_API_KEY`                                                                           | Body snippet search and more stable Semantic Scholar requests                                           | Configure if you use methods/detail searches or high-frequency Semantic Scholar lookup                                                                         |
| Recommended for most users           | `UNPAYWALL_EMAIL` or `PAPER_SEARCH_UNPAYWALL_EMAIL`                                                  | DOI-based open-access PDF resolution                                                                    | Configure during setup; an email is required, not an API key                                                                                                   |
| Recommended for most users           | `CROSSREF_MAILTO`                                                                                    | Crossref polite pool                                                                                    | Configure for long-running or frequent metadata search                                                                                                         |
| Recommended for most users           | `CORE_API_KEY`                                                                                       | CORE repository search                                                                                  | Configure if you rely on CORE or hit anonymous rate limits                                                                                                     |
| Journal metrics                      | `EASYSCHOLAR_KEY`                                                                                    | EasyScholar impact factor, JCR/SSCI, CAS, JCI, ESI, warning flags                                       | Configure if you need journal metrics; use `paper-search setup EASYSCHOLAR_KEY` for hidden input                                                               |
| Biomedical-heavy use                 | `PUBMED_API_KEY`, `NCBI_EMAIL`, `NCBI_TOOL`                                                          | NCBI E-utilities stability and higher limits                                                            | Configure if PubMed is a frequent source                                                                                                                       |
| Key-backed metadata and OA APIs      | `WOS_API_KEY`, `IEEE_API_KEY`, `ELSEVIER_API_KEY`, `SPRINGER_API_KEY`, `SPRINGER_OPENACCESS_API_KEY` | Web of Science, IEEE, Scopus, ScienceDirect, and Springer metadata or open-access responses             | `ELSEVIER_API_KEY` and `SPRINGER_API_KEY` also drive the `publisher_api` full-text tier when your network or key is entitled; the other keys are metadata only |
| Elsevier off-campus full text        | `ELSEVIER_INSTTOKEN`                                                                                 | Institution token sent with `publisher_api` Elsevier requests                                           | Only when full text is needed off campus; a campus egress IP needs no token                                                                                    |
| Institutional download extension     | `PAPER_SEARCH_CARSI_ENABLED`                                                                       | Enables the institutional download extension only when the effective value is exactly `true`            | `paper-search carsi install` sets it; this is not a secret                                                                                             |
| Skill auto-update                    | `PAPER_SEARCH_SKILL_AUTO_UPDATE`                                                                   | `false` stops upgrades from updating the installed Skill                                                | On by default, nothing to configure; set `false` to manage the Skill yourself                                                                         |
| Usually optional                     | `OPENAIRE_API_KEY`                                                                                   | OpenAIRE account/quota use                                                                              | Usually unnecessary for public search                                                                                                                          |
| Scholar network routing              | `GOOGLE_SCHOLAR_PROXY_URL`                                                                           | Dedicated HTTP(S)/SOCKS egress for Google Scholar                                                       | Only when direct requests are repeatedly challenged; use an authorized proxy                                                                                   |
| Scholar request tuning               | `SCHOLAR_RATE_LIMIT_RPS`, `SCHOLAR_MAX_RETRIES`, `SCHOLAR_TIMEOUT_MS`                                | Low-volume client limits adapted from bingshuoguo/google-scholar-mcp                                    | Keep the conservative defaults; these are not API keys                                                                                                         |

Useful key dashboards:

| Service          | Link                                                                                                    |
| ---------------- | ------------------------------------------------------------------------------------------------------- |
| EasyScholar      | [EasyScholar Open API](https://www.easyscholar.cc/console/user/open)                                    |
| Semantic Scholar | [Semantic Scholar API](https://www.semanticscholar.org/product/api)                                     |
| Unpaywall        | [Unpaywall API](https://unpaywall.org/products/api)                                                     |
| CORE             | [CORE API](https://core.ac.uk/services/api)                                                             |
| PubMed           | [NCBI API Keys](https://ncbiinsights.ncbi.nlm.nih.gov/2017/11/02/new-api-keys-for-the-e-utilities/)     |
| Web of Science   | [Clarivate Developer Portal](https://developer.clarivate.com/apis)                                      |
| IEEE Xplore      | [IEEE Xplore Metadata API](https://developer.ieee.org/docs/read/Searching_the_IEEE_Xplore_Metadata_API) |
| Elsevier         | [Elsevier Developer Portal](https://dev.elsevier.com/apikey/manage)                                     |
| Springer Nature  | [Springer Nature Developers](https://dev.springernature.com/)                                           |
| OpenAIRE         | [OpenAIRE APIs](https://develop.openaire.eu/)                                                           |

### PDFs Through Your School's Subscription (Institutional Download Extension)

Articles that no open route provides but your school subscribes to are fetched by the institutional download extension: it opens a browser and downloads the PDF with your school's access. The extension ships with PaperSearch and installs with one command (`paper-search setup` also offers it at the end):

```bash
paper-search carsi install
paper-search download "<DOI>" --platform crossref --save-path ./downloads
```

- Installing asks for your school (looked up in the CARSI member list by Chinese name, English name or domain) and downloads the dedicated Camoufox browser, about 3 GB in all (about 0.5 GB with `--browser ego`, which uses ego lite instead). `--skip-school` leaves the school for later.
- The first time school access is needed, a browser window opens. You only enter your account at the school's login page and pass any human verification; the program picks the school from your configuration, and later downloads reuse the sign-in.
- `paper-search carsi status` shows the state, `paper-search carsi update` updates the extension after a PaperSearch upgrade, and `paper-search carsi uninstall` removes it (keeping the browser and school settings by default).
- Every PDF's first page is checked for the DOI or title; a file of another article is not kept. Failures say why, for example no subscription, no CARSI route at the publisher, login needed, or the publisher pausing access; `paper-search failures --format text` summarizes the latest batch.
- Windows: if PowerShell blocks `npm.ps1`, use `npm.cmd` or the Command Prompt; run downloads from a desktop session, since a browser window cannot open from SSH or a service.

`PAPER_SEARCH_CARSI_ENABLED` switches the extension on and is set to `true` by the installer. The request-level `useEntitledAccess` defaults to `true` and can only suppress the tier; it cannot override global disablement. Use the full tool entry when supplying a title or skipping Sci-Hub for a request:

```bash
paper-search run download_with_fallback --json-args '{"source":"crossref","paperId":"<DOI>","doi":"<DOI>","title":"<paper title>","savePath":"./downloads","useSciHub":false,"useEntitledAccess":true}' --pretty
```

`--platform` / `source` identifies the paper's metadata source. `useSciHub`, `doi`, and `title` belong to `download_with_fallback`, not the shorthand `download` command. Both entries use `primary -> direct_pdf_url -> repositories -> unpaywall -> publisher_api -> scihub -> entitled_access`, with native download attempted once. An earlier success stops the funnel; Sci-Hub failure or a request-level skip continues to optional entitled access.

Downloads sharing a profile are mutually exclusive; wait for the active request on `profile_busy`. Backends supporting live notifications report stages bound to the current request. The CLI writes fixed local messages to stderr while stdout remains final JSON; it does not invent stages for older backends without notifications. Cancelling the call triggers cleanup of its child processes. Final `attempts[].code` values distinguish login, manual verification, timeout, access, and file failures without forwarding raw backend logs.

A PDF visible in the browser or reported as saved still needs file and first-page identity checks against the DOI and supplied title. Unverified files return an error and may be retained in `review.path`; declaration forms and supplementary PDFs do not count as the main article. `doctor=available` proves executable/MCP compatibility only, not login, per-paper entitlement, or file identity. The CARSI backend is called with `legal_only` and Sci-Hub/Tor disabled; when the backend schema enumerates `institutional_only`, that value is sent instead so the backend skips its own public-source race. Success is still not proof of institutional authorization.

The extension's source is `carsi/` in this repository: the Python backend `paper-search-carsi`, cut from scansci-pdf down to institutional downloading; its `doctor` handshake name is `paper-search-carsi`, and PaperSearch calls it over MCP.

```
PaperSearch/
├── src/ tests/ scripts/ docs/ skills/      PaperSearch itself (TypeScript)
├── acceptance/                             per-publisher acceptance sets, run by scripts/publisher-acceptance.mjs
├── campus-proxy/                           parked WebVPN / EZProxy code, not connected to PaperSearch
└── carsi/                                  CARSI backend: institutional downloads (Python, MCP server)
    ├── bin/paper-search-carsi              launcher (PAPER_SEARCH_CARSI_EXECUTABLE points here)
    ├── tests/
    └── paper_search_carsi/
        ├── adapters/                       publisher adapters (by publisher and site type); others use the generic flow
        ├── engine/                         generic engine, school choice, PDF checks, supplements
        └── browser/                        browser backends (Camoufox / ego)
```

Scholar tuning defaults are `SCHOLAR_RATE_LIMIT_RPS=0.5`, `SCHOLAR_MAX_RETRIES=2`, and `SCHOLAR_TIMEOUT_MS=15000`. A challenge page is not retried blindly; wait and retry later or use the strict `no-key` bundle. The Go MCP project is not installed or spawned automatically—the Node adapter keeps the same request policy without adding a Go runtime dependency.

## Agent Skill

The npm package ships a bundled agent Skill at `skills/paper-search/SKILL.md`. Terminal users can use the CLI directly; AI agent workflows should install or sync the Skill so the agent can route the five main workflows correctly.

```bash
paper-search setup --install-skills agents
paper-search skills status --pretty
paper-search skills diff --targets agents --format text
paper-search skills update --targets agents --pretty
```

Supported targets include `agents`, `codex`, `claude`, `cursor`, `gemini`, `antigravity`, and `all`. Skill updates overwrite package-managed Skill files while preserving extra files in the installed Skill directory.

Auto-update after upgrades: the first `paper-search` run after an upgrade (other than `skills` and `setup`) notices that the bundled Skill changed and brings the Skill you installed up to it: only where it was installed, never anywhere new; your own files in the Skill directory are kept; replaced files are backed up under `~/.local/share/paper-search-cli/skill-backups/`; one line on stderr says what was updated. With no Skill installed anywhere, it says once how to install it. To manage the Skill yourself, run `paper-search config set PAPER_SEARCH_SKILL_AUTO_UPDATE false` and sync with `skills update`. `paper-search doctor` shows where the Skill is installed and whether it is current.

The Skill only teaches agents how to call the `paper-search` CLI. API keys still belong in `paper-search setup`, `paper-search config`, `.env`, or shell environment variables.

## Commands

| Command                        | Purpose                                                |
| ------------------------------ | ------------------------------------------------------ |
| `paper-search search`          | Integrated metadata search                             |
| `paper-search journal-metrics` | EasyScholar journal metrics lookup                     |
| `paper-search download`        | Direct PDF download for a verified paper ID or DOI     |
| `paper-search run`             | Precise tool invocation with `--arg` or `--json-args`  |
| `paper-search tools`           | Runtime tool names and schemas                         |
| `paper-search doctor`          | Masked config, Capability Profile, and platform status |
| `paper-search smoke`           | Mock or live self-checks                               |
| `paper-search skills`          | Bundled Skill status, diff, and update                 |
| `paper-search config`          | User-level configuration management                    |

Full command and tool schema: run `paper-search tools --pretty` or see [`skills/paper-search/references/cli-contract.md`](skills/paper-search/references/cli-contract.md).

## Output

Commands return JSON by default. Use `--pretty` for formatted JSON and `--format text` only when you need a human-readable report.

```bash
paper-search search "machine learning" --platform crossref --max-results 1 --pretty
paper-search search "machine learning" --sources no-key --max-results 5 --pretty
paper-search doctor --format text
```

## Troubleshooting

| Problem                                         | First check                                                                                                                            |
| ----------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------- |
| Command not found                               | Reinstall globally with `npm install -g papersearch`                                                                              |
| Missing capability                              | Run `paper-search doctor --pretty` and configure the missing key with `paper-search setup`                                             |
| Institutional extension `disabled`, `absent`, or `incompatible` | Run `paper-search carsi status` for the reason; install with `paper-search carsi install`, or update an existing install with `paper-search carsi update` |
| Provider rate limits                            | Lower `--max-results`, configure the relevant key, or switch sources                                                                   |
| Skill looks stale                               | Run `paper-search skills status --pretty`, then `paper-search skills update --targets agents --pretty`                                 |
| Need complete CLI details                       | Run `paper-search tools --pretty`                                                                                                      |

## Usage Boundaries

Some sources may be subject to platform terms, institutional subscriptions, or local law. Use restricted integrations only when you have the appropriate access rights and permission. The institutional download extension is optional; its result label is diagnostic, not proof of entitlement.

## Project Origin

This project acknowledges and thanks the [LinuxDo](https://linux.do) community. The CLI + Skill direction and paper-search workflow refinements were shaped by community discussions and open-source sharing.

It also references ideas from [openags/paper-search-mcp](https://github.com/openags/paper-search-mcp) while adapting the workflow to a standalone CLI.

## License

MIT
