# PaperSearch guide

Installation, API keys and the institutional download are set up as the [README](../README.en.md) describes. These commands also run directly in a terminal or a script; output is JSON by default.

## Command examples

```bash
# Search papers (a set of sources that needs no keys)
paper-search search "machine learning clinical prediction" --sources no-key --max-results 5 --pretty

# One source, for example PubMed
paper-search search "SGLT2 inhibitor heart failure" --platform pubmed --max-results 10 --pretty

# Verify a DOI
paper-search run get_paper_by_doi --arg doi="10.1038/nature12373" --pretty

# Citing papers; for references use get_paper_references
paper-search run get_paper_citations --arg doi="10.1038/nature12373" --pretty

# Journal impact factors and quartiles (EasyScholar key)
paper-search journal-metrics "Nature" "BMJ" --pretty

# Find Methods wording in body text (Semantic Scholar key)
paper-search run search_semantic_snippets --arg query="propensity score matching" --arg limit=3 --pretty

# Download one paper
paper-search download "<DOI>" --platform crossref

# Download main texts and supplementary files in a batch (omit content for main text only; "supplements" for supplementary files only)
paper-search run download_batch --json-args '{"items":[{"doi":"<DOI-1>"},{"doi":"<DOI-2>"}],"content":"both"}'

# Papers not downloaded, and why
paper-search failures --format text
```

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
     ├─ ④ arXiv preprint: only when no published version was found, and labelled as a preprint
     ├─ Every file is checked against the DOI and title on its first page; once one passes it is saved and the rest are not tried
     └─ Nothing found → paper-search failures says why
```

### Two ways to download

|  | Open downloading (default) | Institutional download (optional extension) |
|---|---|---|
| Available | As soon as PaperSearch is installed | After `paper-search carsi install` |
| Gets | Open-access main text | Main text your school subscribes to; supplementary files from the publishers with rules for them |
| How | Direct downloads, usually seconds, no login: the source's own download, PDF links in the metadata, PubMed Central, Unpaywall, publisher APIs (your own Elsevier/Springer keys); last, the Sci-Hub fallback, on by default | Chrome signs in to your school through CARSI and takes the PDF from the publisher's site |
| What you do | Nothing | Sign in to your school in the browser; verification is handled automatically, with a prompt when manual action is needed |

Both use the same download command: open downloading first, and when it finds nothing, the institutional download if it is installed.

- For dozens to hundreds of papers, use one `download_batch`: each paper tries the open channels first, and one they miss goes straight on to the institutional download while the open channels go on with the rest; the school login comes within seconds. Afterwards `paper-search failures` sorts the papers not downloaded into four classes: no access (with the evidence, such as the page's own words), needs you (login, verification, waiting), site not supported yet, and cause unknown.
- For arXiv papers the published version is tried first; the preprint is downloaded only when none was found. The result says `version: "preprint"` and, when known, gives the published DOI.
- To leave out Sci-Hub, set `"useSciHub": false` in `download_with_fallback` / `download_batch`.
- Every PDF is checked against the DOI and title on its first page; a file that does not match is not counted as a success and is kept aside for review.

### Download results

Each download gets its own `<YYYYMMDD-HHmmss>_PaperSearchDownload` folder inside the download folder, holding that download's papers: main texts alone lie directly in it; downloaded with their supplementary files, each paper has a folder, its supplementary files under `supplements/` with their original names. The main text is named journal_year_title; PDFs that come out with the same name get a short code added, so none is overwritten, and the short ID at the end of a folder name tells apart papers with the same title. The diagnostic records and screenshots of a paper that ran into a problem, or needs checking, are kept out of the download folder, in PaperSearch's own run records (`~/.local/share/paper-search-cli/runs/`, removed after 30 days), for tracking down the problem; they may contain login details, so do not pass them on. A missing journal or year is written as unknown. The JSON a command returns gives each file's actual location.

## Search sources

| Kind | Sources | API key |
|---|---|---|
| General academic metadata | Crossref, OpenAlex, Semantic Scholar, Google Scholar | None (Semantic Scholar body snippets need one) |
| Biomedicine | PubMed, PubMed Central, Europe PMC | None (a PubMed key raises the limits) |
| Preprints and conference papers | arXiv, bioRxiv, medRxiv, OpenReview, IACR ePrint | None |
| Computer science and engineering | DBLP, ACM, USENIX | None |
| Open access and repositories | CORE, OpenAIRE, Unpaywall | Unpaywall takes an email; CORE and OpenAIRE optional |
| Publishers and citation databases | ScienceDirect, Scopus, Springer Nature, IEEE Xplore, Web of Science | Each needs its key (ScienceDirect and Scopus share the Elsevier key) |
| Journal metrics | EasyScholar | Needed |

- The sources that need no key already cover the major publishers' papers; a key adds the publisher's own search.
- One source with `--platform`, several with `--sources a,b,c`; `--sources no-key` needs no keys at all (Crossref, PubMed, Europe PMC, arXiv, OpenReview).
- Google Scholar is read from its web pages and often meets human checks, so it is not in `--sources all`; use `--platform googlescholar` when you need it.
- The same paper from several sources is merged by DOI; when an arXiv preprint is explicitly linked to its published DOI, the published record is kept.
- Sci-Hub is not a search source; it only serves as a DOI fallback when downloading.

## Agent Skill

The Skill ships in the npm package (`skills/paper-search/`). It is written in Chinese, opens with the same overall diagram, and points the AI to focused references as needed: routing and the open download channels, the command contract, installing and using the institutional download, the [publisher support table](../skills/paper-search/references/publisher-support.md), and troubleshooting. It only tells the AI how to call `paper-search`; it keeps no keys, cookies or accounts.

To install the Skill on its own (Node.js 22 or later), run this and pick the AI tools you use:

```bash
npx skills add dr-dumpling/PaperSearch -g
```

The first time you use it, your AI finds that the `paper-search` command is not installed yet, asks you, and installs it once you agree.

To install the command and the Skill together from your own terminal, without your AI, one line does it (Claude Code as the example):

```bash
npm install -g papersearch && paper-search skills update --targets claude
```

```bash
paper-search skills status --pretty
paper-search skills update
```

Without `--targets`, these check and update only the places where the Skill is already installed, never adding a copy elsewhere. `--targets` takes `codex`, `claude`, `cursor`, `gemini`, `antigravity` or `agents` (the shared `~/.agents/skills/` directory). For other AI tools that read Skill folders, copy the bundled Skill into their Skill directory: run `npm root -g` to locate the global npm directory; the bundled Skill is under `papersearch/skills/paper-search/` there. Copy the entire folder, including `references/`, and copy it again after an update. Start a new AI session after installation.

- `--targets all` syncs the Skill to all built-in locations. Updating overwrites the files the package manages and keeps files you added to the Skill directory.
- The first run after upgrading PaperSearch updates the Skill you installed; replaced files are backed up under `~/.local/share/paper-search-cli/skill-backups/`. To turn this off: `paper-search config set PAPER_SEARCH_SKILL_AUTO_UPDATE false`.
- If you installed school subscription downloads, the first download that uses them after an upgrade updates the extension first (one line in the terminal says so) and then goes on. To turn this off: `paper-search config set PAPER_SEARCH_CARSI_AUTO_UPDATE false`, then run `paper-search carsi update` yourself.
- `paper-search doctor` shows Skill locations and version status for the built-in installation targets.

## All commands

| Command | Use |
|---|---|
| `paper-search search` | Search paper metadata |
| `paper-search journal-metrics` | Journal metrics (EasyScholar) |
| `paper-search download` | Download the PDF of a verified paper |
| `paper-search run <tool>` | Call one tool exactly, with `--arg` or `--json-args` |
| `paper-search failures` | Why downloads failed, summarized |
| `paper-search update check` | Check for a new version |
| `paper-search carsi` | Install, check, update or remove school subscription downloads (CARSI) |
| `paper-search setup` / `config` | Configure keys, the Skill and the extension |
| `paper-search settings` | Open the settings window: download folder, waits and reminders, API keys (needs school subscription downloads and a screen) |
| `paper-search uninstall` | Uninstall: lists what goes (school subscription downloads and its login, run records, config and API keys, the Skill in each AI tool), then removes it all once you agree; downloaded papers stay; `--dry-run` only lists |
| `paper-search doctor` | Health check: configuration, available features, Skill and extension status |
| `paper-search skills` | Skill status, differences and updates |
| `paper-search smoke` | Offline or live self-check |
| `paper-search tools` | All tool names and their arguments |

Commands print JSON by default; `--pretty` formats it and `--format text` prints a report for people. All commands: `paper-search tools --pretty`, or the [command contract](../skills/paper-search/references/cli-contract.md) (Chinese).

## Other settings

Change them with `paper-search config set <setting> <value>`, or run `paper-search setup <setting>`.

| Setting | What it does | Default |
|---|---|---|
| `DEFAULT_DOWNLOAD_PATH` | Folder downloaded papers go to | `./downloads` under the command's current directory; also in the progress capsule's settings |
| `UNPAYWALL_EMAIL`, `CROSSREF_MAILTO` | Contact emails for Unpaywall's open-access PDF lookup by DOI and Crossref's polite pool | Generated by `paper-search setup` when left blank; also in the settings window |
| `GOOGLE_SCHOLAR_PROXY_URL` | Egress proxy for Google Scholar, when direct requests keep being challenged; use a proxy you are allowed to use | Not set |
| `PAPER_SEARCH_SKILL_AUTO_UPDATE` | `false` stops upgrades from updating the installed Skill | On |
| `PAPER_SEARCH_CARSI_AUTO_UPDATE` | `false` stops upgrades from updating the school subscription download extension; run `paper-search carsi update` yourself | On |
| `PAPER_SEARCH_UPDATE_NOTIFY` | `false` stops the new-version notices | On |
| `PAPER_SEARCH_CARSI_DECLINED` | `true` stops your AI from suggesting school subscription downloads (it sets this when you say no); ask for them any time | Unset |
| `PAPER_SEARCH_CARSI_ENABLED` | Switch for school subscription downloads (CARSI) | Set by `paper-search carsi install` |

## Troubleshooting

| Problem | What to do |
|---|---|
| `paper-search` not found | Reinstall with `npm install -g papersearch` |
| `EEXIST` during installation, or coming from the old package `paper-search-cli` | Run `npm uninstall -g paper-search-cli` first, then install `papersearch`; your configuration, Skill, school login and download records stay |
| A feature does not work | `paper-search doctor --format text` shows what is missing; then `paper-search setup` |
| Subscribed articles do not download | `paper-search carsi status --format text` to check school subscription downloads; `paper-search failures --format text` for each paper's reason |
| A source rate-limits | Lower `--max-results`, configure its key, or switch sources |
| Google Scholar shows a human check | Wait and retry, or use `--sources no-key` |
| The AI reads an old Skill | `paper-search skills status --pretty`, then `paper-search skills update`; start a new AI session |
| Sign in to your school first, or check that signing in works | `paper-search carsi login --doi <DOI of an article your school subscribes to>`: the download browser opens; sign in on your school's page |
| Update or remove school subscription downloads | `paper-search carsi update`; `paper-search carsi uninstall` |
| Uninstall PaperSearch | `paper-search uninstall`, then `npm uninstall -g papersearch` |
| PowerShell on Windows blocks `npm` | Use `npm.cmd`, or run it in Command Prompt |
| Reporting a failed download | Use the download-failure issue template with the version, OS, website and DOI; `paper-search failures --export ./failure-report.zip` exports the failure records — check the `summary.md` and screenshots in it for personal information before attaching it |
| How to upgrade | `npm install -g papersearch@latest`; the first run after an upgrade updates the Skill you installed |
