# PaperSearch

[简体中文](README.zh.md) | English

PaperSearch is `paper-search`, an academic literature command for AI tools and the terminal, with a bundled Skill that teaches Claude Code, Codex, Cursor and other AI tools how to call it. It searches papers, verifies DOIs and PMIDs, expands citations and references, looks up journal impact factors and quartiles, finds Methods wording in body snippets, and downloads paper PDFs and supplementary files. Output is JSON by default, for AI tools and scripts.

It is the open version by default: once installed it searches and downloads open-access papers. To download through your school's subscriptions, add the optional institutional download extension.

![Node.js](https://img.shields.io/badge/node.js->=18.0.0-green.svg)
![License](https://img.shields.io/badge/license-MIT-blue.svg)
![Version](https://img.shields.io/badge/version-0.4.1-blue.svg)
[![LinuxDo](https://img.shields.io/badge/LinuxDo-community-1f6feb)](https://linux.do)

[How it works](#how-it-works) | [Quick start](#quick-start) | [Two ways to download](#two-ways-to-download) | [Search sources](#search-sources) | [Configuration](#configuration) | [Agent Skill](#agent-skill) | [Commands](#commands) | [Troubleshooting](#troubleshooting)

## How it works

```text
A literature request
│
├─ Find papers, verify DOI/PMID → paper-search search (Crossref, PubMed, OpenAlex, ...)
│    └─ Entries confirmed, full text needed → go to "Download" below
├─ Citing papers, references → paper-search run get_paper_citations / get_paper_references
├─ Impact factor, quartiles → paper-search journal-metrics (EasyScholar key)
├─ Methods wording, parameters → paper-search run search_semantic_snippets (Semantic Scholar key)
│
└─ Download main text, supplementary files → paper-search download / run download_with_fallback / run download_batch
     One download command, tried in order:
     ├─ ① Open downloading (built in): the source's own download, PMC, Unpaywall, publisher APIs
     ├─ ② Sci-Hub fallback (on by default, can be turned off)
     ├─ ③ Institutional download (optional extension): a browser signs in to your school through CARSI and takes the PDF and supplementary files from the publisher's site
     ├─ Every file is checked against the DOI and title on its first page; once one passes it is saved and the rest are not tried
     └─ Nothing found → paper-search failures says why
```

## Quick start

Requires Node.js 18 or later and npm.

```bash
npm install -g papersearch
paper-search setup
paper-search doctor --format text
```

`paper-search setup` asks three things in turn: API keys and email; which AI tools to install the Skill into (Claude Code, Codex, Cursor, ...); and whether to install the institutional download extension. Each can be skipped. `doctor` shows what works now and what is still missing.

The Skill is the instruction file that teaches an AI tool to call `paper-search`; install it when you use an AI tool for literature work. If you skipped it, install it any time, with `--targets` set to your tool (`claude`, `codex`, `cursor`, `gemini`, `agents`, or `all`):

```bash
paper-search skills update --targets claude
```

You can also send this to your AI tool and let it do the install:

```text
Please install PaperSearch for me: run npm install -g papersearch, then paper-search skills update --targets <your own target: claude for Claude Code, codex for Codex, cursor for Cursor>, then paper-search doctor --format text, and tell me which features work and which keys are missing. I will enter API keys myself with paper-search setup in a terminal; do not ask me to paste them into the chat.
```

**Coming from the old package `paper-search-cli`**: run `npm uninstall -g paper-search-cli`, then `npm install -g papersearch`. Both provide the same `paper-search` command and cannot be installed together; your configuration, Skill, school login and download records stay.

**Later upgrades**: `npm install -g papersearch@latest`. The first `paper-search` run after an upgrade brings the Skill you installed up to the new version.

Try the features:

```bash
paper-search search "machine learning clinical prediction" --platform crossref --max-results 3 --pretty
paper-search search "large language models" --sources no-key --max-results 5 --pretty
paper-search run get_paper_citations --arg doi="10.1038/nature12373" --arg limit=5 --pretty
paper-search journal-metrics "Nature" "BMJ" --pretty
paper-search download PMC11466435 --platform pmc --save-path ./downloads
paper-search run search_semantic_snippets --arg query="propensity score matching" --arg limit=3 --pretty
```

## Two ways to download

|  | Open downloading (default) | Institutional download (optional extension) |
|---|---|---|
| Available | As soon as PaperSearch is installed | After `paper-search carsi install` |
| Gets | Open-access main text | Main text your school subscribes to; supplementary files from the publishers with rules for them |
| How | Direct downloads, usually seconds, no login: the source's own download, PDF links in the metadata, PubMed Central, Unpaywall, publisher APIs (your own Elsevier/Springer keys); last, the Sci-Hub fallback, on by default | A browser signs in to your school through CARSI and takes the PDF from the publisher's site |
| What you do | Nothing | The first time, type your school account and password in the browser and click any human check; the program picks the school |

Both use the same download command: open downloading first, and when it finds nothing, the institutional download if it is installed.

```bash
paper-search download "<DOI>" --platform crossref --save-path ./downloads
paper-search run download_batch --json-args '{"items":[{"doi":"<DOI-1>"},{"doi":"<DOI-2>"}],"savePath":"./downloads"}'
paper-search failures --format text
```

- For dozens to hundreds of papers, use one `download_batch`; afterwards `paper-search failures` sorts the papers not downloaded into four classes: no access (with the evidence, such as the page's own words), needs you (login, human check, waiting), site not supported yet, and cause unknown.
- To leave out Sci-Hub, set `"useSciHub": false` in `download_with_fallback` / `download_batch`.
- Every saved PDF is checked against the DOI and title on its first page; a file of another article is not kept.

### Institutional download extension

```bash
paper-search carsi install
paper-search carsi status --format text
```

- Installing asks for your school (a CARSI member school, by Chinese name, English name or domain) and downloads the dedicated Camoufox browser, about 3 GB in all; on macOS, `--browser ego` uses ego lite instead, about 0.5 GB. `--skip-school` leaves the school for later.
- Schools sign in through CARSI (the Chinese university identity federation). When a publisher's institution list has no CARSI or no entry for your school, the program says so at once; download on campus or through your school's VPN instead.
- Downloads show a progress window: skip this paper, mark the journal or publisher as no access, stop the whole task, or change how long waits last (the gear at the top right). On the school's login page a paper waits up to 3 minutes by default; anywhere else (human checks, publisher pages, ...) it ends after 1 minute.
- `paper-search carsi update` updates the extension after a PaperSearch upgrade; `paper-search carsi uninstall` removes it (keeping the browser and the school settings by default).
- Windows: if PowerShell blocks `npm.ps1`, use `npm.cmd` or Command Prompt; downloads must run in a desktop session, as a browser window cannot open from SSH or a system service.

### Supplementary files

`content` in `download_with_fallback` / `download_batch` picks what to download: `main` (default, main text only), `both` (main text and supplementary files), or `supplements` (supplementary files only). Supplementary files come only through the institutional download; they are saved under `<save path>/<DOI>_supplements/`, with a `manifest.json` giving each file's status.

What each publisher supports, main text and supplementary files, is in the [publisher support table](skills/paper-search/references/publisher-support.md) (Chinese). Main text and supplementary files have both been fetched from Elsevier, Wiley, Springer Nature, OUP, Wolters Kluwer, Taylor & Francis, Sage, ACS, NEJM, ASCE, Dove and others; IEEE, Thieme and others give the main text only for now; sites not in the table are tried with the shared rules.

## Search sources

| Kind | Sources | Configuration |
|---|---|---|
| General academic metadata | Crossref, OpenAlex, Semantic Scholar, Google Scholar | None; Semantic Scholar body snippets need a key; Google Scholar must be asked for by name |
| Biomedicine | PubMed, PubMed Central, Europe PMC | Optional PubMed key |
| Preprints and conference papers | bioRxiv, medRxiv, OpenReview, IACR ePrint | None |
| Computer science and engineering | DBLP, ACM, USENIX, IEEE Xplore | IEEE needs a key |
| Open access and repositories | CORE, OpenAIRE, Unpaywall | Unpaywall needs an email; CORE key optional |
| Citation databases and publishers | Web of Science, Scopus, ScienceDirect, Springer Nature | Each needs its key; metadata only (Elsevier and Springer keys also serve the publisher API for full text) |
| Journal metrics | EasyScholar | EasyScholar key |

- One source with `--platform`, several with `--sources a,b,c`; `--sources no-key` needs no keys at all (Crossref, PubMed, Europe PMC, OpenReview).
- Google Scholar is read from its web pages and often meets human checks, so it is not in `--sources all`; use `--platform googlescholar` when you need it.
- Sci-Hub is not a search source; it only serves as a DOI fallback when downloading.

## Configuration

Most free sources need nothing. Run `paper-search setup` first to save keys in your user configuration:

```bash
paper-search setup
paper-search config list --pretty
paper-search config set SEMANTIC_SCHOLAR_API_KEY <your key>
```

The configuration file is `~/.config/paper-search-cli/config.json` (mode `0600`; the folder keeps its old name, so upgrades keep your settings). `config list` and `doctor` show keys masked.

| Key | Use | When |
|---|---|---|
| `SEMANTIC_SCHOLAR_API_KEY` | Body snippet search; steadier Semantic Scholar requests | For Methods details, or frequent Semantic Scholar use |
| `UNPAYWALL_EMAIL` | Open-access PDFs by DOI | Recommended; an email is enough |
| `CROSSREF_MAILTO` | Crossref's polite pool | Long or frequent searches |
| `CORE_API_KEY` | CORE repository search | Frequent CORE use, or rate limits |
| `EASYSCHOLAR_KEY` | Journal metrics | For impact factors and quartiles; `paper-search setup EASYSCHOLAR_KEY` hides the input |
| `PUBMED_API_KEY`, `NCBI_EMAIL` | Higher PubMed limits | Frequent PubMed use |
| `WOS_API_KEY`, `IEEE_API_KEY`, `ELSEVIER_API_KEY`, `SPRINGER_API_KEY` | Their metadata; Elsevier and Springer keys also serve the publisher API for full text (access follows your network or key) | When you use those sources |
| `ELSEVIER_INSTTOKEN` | Elsevier full text off campus through its API | Off campus; not needed on a campus network |
| `GOOGLE_SCHOLAR_PROXY_URL` | Egress proxy for Google Scholar | When direct requests keep being challenged; use a proxy you are allowed to use |
| `PAPER_SEARCH_CARSI_ENABLED` | Switch for the institutional download extension | Set by `paper-search carsi install` |
| `PAPER_SEARCH_SKILL_AUTO_UPDATE` | `false` stops upgrades from updating the installed Skill | On by default; set it to manage the Skill yourself |

Where to get keys: [EasyScholar](https://www.easyscholar.cc/console/user/open) · [Semantic Scholar](https://www.semanticscholar.org/product/api) · [Unpaywall](https://unpaywall.org/products/api) · [CORE](https://core.ac.uk/services/api) · [NCBI](https://ncbiinsights.ncbi.nlm.nih.gov/2017/11/02/new-api-keys-for-the-e-utilities/) · [Web of Science](https://developer.clarivate.com/apis) · [IEEE Xplore](https://developer.ieee.org/docs/read/Searching_the_IEEE_Xplore_Metadata_API) · [Elsevier](https://dev.elsevier.com/apikey/manage) · [Springer Nature](https://dev.springernature.com/) · [OpenAIRE](https://develop.openaire.eu/)

## Agent Skill

The Skill ships in the npm package (`skills/paper-search/`). It is written in Chinese, opens with the same overall diagram, and points the AI to focused references as needed: routing and the open download channels, the command contract, installing and using the institutional download, the [publisher support table](skills/paper-search/references/publisher-support.md), and troubleshooting. It only tells the AI how to call `paper-search`; it keeps no keys, cookies or accounts.

```bash
paper-search skills status --pretty
paper-search skills update --targets claude
```

- Targets: `agents`, `codex`, `claude`, `cursor`, `gemini`, `antigravity`, `all`. Updating overwrites the files the package manages and keeps files you added to the Skill directory.
- **Auto-update after upgrades**: the first `paper-search` run after an upgrade (other than `skills` and `setup`) brings the Skill you installed up to the new version: only where it was installed; replaced files are backed up under `~/.local/share/paper-search-cli/skill-backups/`; one line on stderr says what changed. With no Skill installed anywhere, it says once how to install it. To turn it off: `paper-search config set PAPER_SEARCH_SKILL_AUTO_UPDATE false`.
- `paper-search doctor` shows where the Skill is installed and whether it is current.

## Commands

| Command | Use |
|---|---|
| `paper-search search` | Search paper metadata |
| `paper-search journal-metrics` | Journal metrics (EasyScholar) |
| `paper-search download` | Download the PDF of a verified paper |
| `paper-search run <tool>` | Call one tool exactly, with `--arg` or `--json-args` |
| `paper-search failures` | Why downloads failed, summarized |
| `paper-search carsi` | Install, check, update or remove the institutional download extension |
| `paper-search setup` / `config` | Configure keys, the Skill and the extension |
| `paper-search doctor` | Health check: configuration, available features, Skill and extension status |
| `paper-search skills` | Skill status, differences and updates |
| `paper-search smoke` | Offline or live self-check |
| `paper-search tools` | All tool names and their arguments |

Commands print JSON by default; `--pretty` formats it and `--format text` prints a report for people. All commands: `paper-search tools --pretty`, or the [command contract](skills/paper-search/references/cli-contract.md) (Chinese).

## Troubleshooting

| Problem | What to do |
|---|---|
| `paper-search` not found | Reinstall with `npm install -g papersearch` |
| `EEXIST` while installing | The old package is still there: `npm uninstall -g paper-search-cli` first |
| A feature does not work | `paper-search doctor --format text` shows what is missing; then `paper-search setup` |
| Subscribed articles do not download | `paper-search carsi status --format text` for the extension; `paper-search failures --format text` for each paper's reason |
| A source rate-limits | Lower `--max-results`, configure its key, or switch sources |
| Google Scholar shows a human check | Wait and retry, or use `--sources no-key` |
| The AI reads an old Skill | `paper-search skills status --pretty`, then `paper-search skills update --targets <tool>`; start a new AI session |

## Use responsibly

Some sources are subject to platform terms, institutional subscriptions or local law; use them only where you have access. The institutional download uses your own school account and subscriptions; the source labels in results are for diagnosis and are not proof of entitlement.

## Origins

- Thanks to the [LinuxDo](https://linux.do) community, where the command-plus-Skill approach and workflow improvements came from discussion and open sharing.
- [openags/paper-search-mcp](https://github.com/openags/paper-search-mcp): the project draws on its ideas, reworked into a standalone command.
- [Rimagination/scansci-pdf](https://github.com/Rimagination/scansci-pdf) (MIT): the institutional download backend (`carsi/`) was carved out of it, keeping only the institutional access part (CARSI and other federation sign-in, publisher site capture, session reuse, PDF capture), with publisher rules added one by one since; its copyright notice is kept in `carsi/NOTICE`.

## License

MIT
