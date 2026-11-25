# Management layer: install, check, update, Skill sync

Use this file to judge whether `paper-search` is installed, configured and working, and whether the installed Skill matches the bundled one. These commands only help judge whether things work; they do no literature task themselves.

## When only the Skill is installed

When the user installed this Skill first (for example with `npx skills add`) but `command -v paper-search` finds no command, do the following directly. Do not search other directories for the command, and do not read `~/.npmrc` or shell configuration files: they may hold tokens, which would show up in the output.

1. Run `node --version`. Without Node.js, or below version 22, ask the user to install the Node.js LTS first (https://nodejs.org) and to continue in a new terminal once it is installed; do not install Node.js for the user.
2. Ask the user first, and install only after they agree: explain that this installs the PaperSearch command-line program globally with npm (the npm package `papersearch`, which provides the `paper-search` command), with the command `npm install -g papersearch@latest`.
3. After the user agrees, run it, then run `paper-search --version` to confirm. On a permission error (`EACCES`), do not add `sudo`; give the command to the user to run in their own terminal. When Windows PowerShell blocks `npm` or `paper-search` (script execution policy), use `npm.cmd` and `paper-search.cmd` instead; do not change the execution policy.
4. Do not run `paper-search skills update`: the Skill is already installed (it is the one you are reading), and installing it again would add a second Skill of the same name. When PaperSearch is upgraded later, this Skill updates automatically.
5. Run `paper-search doctor --format text`, tell the user in one sentence what they can use now, then carry on with the user's original request: for "start setup", go on with `setup.md`; for a literature request, first mention that they can say "start setup" when they need setup, then do it.

## Management commands

```bash
paper-search doctor --pretty
paper-search doctor --format text
paper-search smoke --mock --pretty
paper-search smoke --live --pretty
paper-search skills status --pretty
paper-search skills diff --format text
paper-search skills update --pretty
paper-search tools --pretty
paper-search config list --pretty
```

| Command | What it does | When to use |
|---|---|---|
| `paper-search doctor --pretty` | Full health report: the masked configuration, the capability summary, each source's status and what is missing | First use, an unclear environment, or when the user asks what they can use now |
| `paper-search doctor --format text` | Health report for people to read | When you need to summarize the health for the user |
| `paper-search smoke --mock --pretty` | Offline check of the command wiring, of the capability summary's judgments and of the Skill sync status judgments | After code changes or installation, or with no network |
| `paper-search smoke --live --pretty` | Small real check: free metadata sources, capabilities with configured keys, whether Sci-Hub mirrors are reachable | When the user wants a real test on this computer, or a source or the network seems wrong |
| `paper-search skills status --pretty` | Shows whether the installed Skill matches the bundled Skill | Installation, update checks, or an agent reading an old Skill |
| `paper-search skills diff --format text` | Previews the differences between the bundled Skill and the installed Skill | Before updating the Skill |
| `paper-search skills update --pretty` | Syncs the package-managed Skill files into the user's Skill directory; files left by the old version that the new version no longer uses move to a backup folder; the user's own files are kept | After the user confirms updating the Skill |
| `paper-search tools --pretty` | Lists the tool names and parameter schemas of `paper-search run` | When unsure of a tool name or parameter |
| `paper-search config list --pretty` | Shows the masked configuration status | To confirm whether keys, emails and switches are configured |

## Uninstall

When the user wants to uninstall PaperSearch:

1. Run `paper-search uninstall --dry-run --format text`, and tell the user what will be deleted and what kept (school subscription downloads and the sign-in state, run logs, configuration and API keys, the Skill in each AI tool; downloaded papers are kept).
2. After the user agrees, run `paper-search uninstall --yes --format text`. When some files were not deleted, ask the user, as the output says, to close the progress window and the Chrome used for downloads, then run it again.
3. Last, run `npm uninstall -g papersearch` (in Windows PowerShell use `npm.cmd`).

To remove only school subscription downloads, use `paper-search school uninstall` (see `school-setup.md`).

## Health check (doctor)

`paper-search doctor` is the main health report, with the masked configuration, the capability summary and each source's status.

Each item in the capability summary is an independent capability:

- `metadata_search`: metadata search through configured or free literature sources. Sci-Hub is not a search source.
- `citation_expansion`: the citing papers (OpenAlex) and the references (the publisher's list in Crossref, or OpenAlex) of a known paper; no key needed. `OPENALEX_API_KEY` is optional: without it, at most the newest 10,000 citing papers are listed; with it, all.
- `body_snippet_search`: Semantic Scholar open-access body snippet search; needs `SEMANTIC_SCHOLAR_API_KEY`.
- `journal_metrics`: EasyScholar journal metrics; needs `EASYSCHOLAR_KEY`.
- `pdf_discovery`: PDF retrieval and download, through the source's own download, the PDF address in the metadata, open-access sources, institutional repositories, Unpaywall, and the Sci-Hub fallback that is on by default.
- `entitled_access`: the optional school download backend (school subscription downloads). The school download backend (school subscription downloads) is the only optional authorized download backend, off by default. `doctor`, the interactive `setup` and the live smoke test give its running state: `disabled` (not enabled), `absent` (backend not found), `incompatible` (backend version incompatible) or `available` (reachable); the offline capability summary does not start the backend and shows `not_evaluated`.

Publisher or database keys (recorded as `metadata_entitled`) have nothing to do with `entitled_access`: they open only metadata or open-access APIs, and cannot serve as a local authorized PDF backend. Apart from the school download backend, there is no browser, WebVPN or EZProxy fallback.

`PAPER_SEARCH_SCHOOL_ENABLED` is not a secret; the school download backend is enabled only when its value is exactly `true`. The per-request `useEntitledAccess` defaults to `true`, but can only turn off this layer, never bypass the global switch. One failed download affects only that download and does not rewrite the global availability.

Agents read the JSON output for decisions; use `--format text` only when the user needs a readable report.

## Smoke test (smoke)

`paper-search smoke --mock` is fully offline and should pass without any key. It does not start the school download backend; the offline snapshot shows `not_evaluated`.

`paper-search smoke --live` makes a small real check:

- Free metadata sources are always checked;
- By default it checks whether Sci-Hub mirrors are reachable, without downloading PDFs;
- Capabilities with configured keys get a light check; those without are marked `skipped`;
- An enabled school download backend gets only an interface compatibility check (`initialize + tools/list`): no cache clearing, no sign-in, no PDF download.

Severity in the live smoke test:

- `critical`: the command is judged failed.
- `degraded`: a configured or default-on capability did not work as expected; it must come with a fix suggestion, but does not mean the whole tool is unusable.
- `warning`, `skipped`: for information only.

When reporting the results, tell the user both the `message` and the `remediation` of `degraded` items.

## Skill sync

The npm package carries a Skill under `skills/paper-search` (the bundled Skill). Installing or updating the Skill files the user sees takes an explicit command.

Supported targets: `agents`, `codex`, `claude`, `cursor`, `gemini`, `antigravity`. Without `--targets`, only places where the Skill is already installed are targeted (places linked to the same folder count as one), and no extra copy is installed elsewhere; when none is installed, it goes to `~/.agents/skills`, and when that folder does not exist, to codex, claude and cursor.

Routine sync after a package update:

```bash
paper-search skills status --pretty
paper-search skills diff --format text
paper-search skills update --pretty
```

`skills update` overwrites the package-managed files; files installed by the old version that the new version no longer has (`retiredFiles`) move to the `skill-backups/<time>-update/` backup folder; the user's own files are kept. `.paper-search-files.json` in each Skill records the files installed last time, used to tell old files from the user's own; do not delete or edit it. `skills diff` shows differences only for package-managed files; the user's own files are listed by name only.

Automatic sync after an upgrade: the first time `paper-search` runs after PaperSearch is upgraded (except `skills` and `setup`), it updates the Skills the user installed to the bundled version: only the places installed before are updated, and the user's own files are kept; replaced old files, and files left by the old version that the new version no longer uses, are backed up in `${XDG_DATA_HOME:-~/.local/share}/paper-search-cli/skill-backups/`, and one line on stderr says so; when none is installed, it only says once how to install it. `paper-search config set PAPER_SEARCH_SKILL_AUTO_UPDATE false` turns this off; then sync by hand with `skills update`. The `skills` item of `doctor` lists whether each place is up to date. When you see the update note on stderr, tell the user that only a new AI session reads the new version.

When the installed Skill is newer than the command-line program (the `metadata.version` at the top of the Skill is larger), automatic sync does not overwrite it with the older bundled Skill; stderr notes "PaperSearch 有新版本……本机版本为……" (PaperSearch has a new version …; this computer has …) at most once a day, and `doctor` says the same there. What needs updating then is the command-line program: tell the user and ask whether to run `npm install -g papersearch@latest`; do not run `skills update` (it would put the old Skill back).

## Package update and capability setup

`skills update` only syncs the bundled Skill into the chosen Skill directories; it does not update the npm package, a GitHub checkout, compiled command files or data source configuration.

`paper-search setup` only configures keys, emails and Skill install locations for the currently installed command; it does not update the package itself.

Update steps for ordinary users (when upgrading from the old package `paper-search-cli`, first run `npm uninstall -g paper-search-cli`: the two packages provide the same `paper-search` command and cannot be installed together; configuration and the Skill are kept):

```bash
npm install -g papersearch@latest
paper-search skills update --pretty
paper-search doctor --pretty
paper-search setup
paper-search smoke --mock --pretty
```

For keys, ask the user to run `paper-search setup <KEY>` in their own terminal (the input is hidden), or to fill them in in the settings window, then confirm with `paper-search config test <KEY>`. Before and after `setup`, `doctor` shows the capability summary. Missing, unavailable or degraded capabilities state which key, email, source or environment item the user needs to configure. The first setup also asks the user which folder downloaded papers go to by default, set as `DEFAULT_DOWNLOAD_PATH`; see "Default download folder" in SKILL.md.

Update steps for maintainers or local development builds:

```bash
git pull
npm install
npm run build
npm install -g .
paper-search skills update --pretty
paper-search doctor --pretty
paper-search setup
paper-search smoke --mock --pretty
```

`npm install -g .` links the global command to this repository directory; after the repository is rebuilt, the global command changes with it. To install a fixed version, first run `npm pack`, then `npm install -g <the generated .tgz>`. Before a release, or before installing a local build globally on this computer, verify the repository this way.

The school subscription downloads backend is updated separately from PaperSearch itself, and installed only when the user asks:

```bash
paper-search school status --format text
paper-search school install
paper-search doctor --pretty
```

`install` first checks that this computer has Google Chrome, lists what it will download and where, then prepares its own Python, installs the backend and enables it (`PAPER_SEARCH_SCHOOL_ENABLED=true`, `PAPER_SEARCH_SCHOOL_EXECUTABLE`). After PaperSearch is upgraded, on the first use of school subscription downloads the CLI first updates the extension automatically and then downloads (one line on stderr; when another download is using the extension, or the update failed, this download goes on with the old version); when the user turned off automatic updates (`PAPER_SEARCH_SCHOOL_AUTO_UPDATE=false`), `status` says when to run `paper-search school update`. A backend the user maintains elsewhere is set with `paper-search config set PAPER_SEARCH_SCHOOL_EXECUTABLE <path>`. For the school, the browser (Google Chrome or ego) and accounts, see `school-setup.md`; the account and password are entered only in the user's own browser, never in the chat, configuration, command arguments or logs. `available` in `doctor` only proves the backend interface works; it does not mean signed in to the school, or access to any paper. Everyday downloads still use `paper-search download`, `paper-search run download_with_fallback` or `download_batch`; see `browser-download.md`.

## Configuration check

Configuration sources, by priority:

1. Shell environment variables
2. `.env` in the current directory
3. The user configuration file `~/.config/paper-search-cli/config.json`
4. Built-in defaults for free sources

Common commands:

```bash
paper-search setup
paper-search config list --pretty
paper-search config get SEMANTIC_SCHOLAR_API_KEY --pretty
paper-search config get EASYSCHOLAR_KEY --pretty
paper-search doctor --pretty
```

The output of `doctor` and `config` masks configured keys.

## CLI new-version notice

Everyday online tasks may check asynchronously for a new stable release of the npm package `papersearch`; successful results are cached for 24 hours, and failed or unfinished requests back off for 1 hour. Once a new version is found, each everyday call notes the current/latest version and the upgrade command for the matching install channel, once; the notice is on stderr, and the stdout JSON and the original task's result do not change. Offline management commands do not go online; CI and help/version/config/setup/update do not notify automatically.

`paper-search config set PAPER_SEARCH_UPDATE_NOTIFY false` turns off the automatic check and notice; `true` turns it back on. This setting is separate from the capsule and the system notifications. `paper-search update check --format text` checks on demand, and works with automatic notices off too; when the network is unavailable, it reports truthfully that it could not check, and does not guess the latest version. An old install without this command reports only its version, and does not fake a successful check.

When you see the notice, you may tell the user there is a new version; without permission, do not run the upgrade command in the notice. Updating the CLI package itself, syncing the installed Skill, and updating the extension (automatic on first use after an upgrade, or `paper-search school update`) are three different steps.
