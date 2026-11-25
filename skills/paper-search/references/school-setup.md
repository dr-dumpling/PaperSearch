# School download: install the extension, set the school, choose the browser

School subscription downloads (signing in through the school's academic identity federation or OpenAthens) let PaperSearch use the user's school access to download subscription papers in a browser. On a computer with a graphical interface it is installed only after the user agrees: ask once when the user says "start setup" or first wants a subscription article; when the user said no (`PAPER_SEARCH_SCHOOL_DECLINED=true`), or on a server without a graphical interface, do not install it and do not ask. Search and open download do not need it.

## Check and install

```bash
paper-search school status --format text
```

Shows whether it is installed, the install directory, the browser used (Google Chrome's path and version, the driver version), the school, and whether PaperSearch has it enabled. When Chrome is older than the tested version, it says to update Chrome first.

After the user agrees, run (when the agent installs it for the user, add `--yes --skip-school`):

```bash
paper-search school install
```

- Needs a graphical interface: the school login must happen in a visible browser. On Linux without a graphical interface (a server, with no `DISPLAY` or `WAYLAND_DISPLAY`) installation stops at the first step, and `paper-search setup` no longer asks whether to install it; on such machines use `paper-search setup <KEY>` for keys; search and open-access download work as usual.
- Needs Google Chrome on this computer; without it, installation stops. Then tell the user that Chrome must be installed first; after the user agrees, install it for them: on macOS with Homebrew run `brew install --cask google-chrome`, on Windows run `winget install -e --id Google.Chrome`; then run the same `school install` again. Without Homebrew or winget, or when the installation fails, ask the user to download and install it from https://www.google.com/chrome/. `--browser ego` uses the user's own ego lite instead (macOS only).
- Before installing, it lists the install location and the download size (about 0.5 GB; no browser is downloaded), and starts only after the user confirms. `--yes` skips the confirmation; use it only after the user has agreed.
- The user does not need to install Python first; when it fails midway, fix the reported problem and run the same command again: it continues from the step that failed.
- When done, it opens the settings window on the API key page; the user closes it with the × at the top right after filling it in, or when nothing is needed.
- In development builds with YesCaptcha, the user enters ClientKey in Settings → API key → YesCaptcha, presses "测试" (Test) to check the balance, then "保存" (Save). Supported challenges send only puzzle images and the question; the local browser applies the answer. School sign-in pages are excluded. The test checks the key, not whether a website will accept an answer.
- It enables itself when done (`PAPER_SEARCH_SCHOOL_ENABLED=true`, `PAPER_SEARCH_SCHOOL_EXECUTABLE` pointing at the new backend). When another backend was configured, it first asks the user whether to replace it.
- Installation asks for the school; `--skip-school` skips that, to configure it later.
- The first time the extension is configured, it asks whether to turn on system notifications. New configurations default to off, and Enter keeps the current choice; `--yes` does not mean consent to turning notifications on. When the agent configures it for the user, first ask the user whether to turn them on or off, then save the answer with the same backend's `config set progress_notify true` or `false`; when there is already a clear choice, do not ask again. Later the user can change it at once with the "系统通知" (Notifications) switch under the capsule's gear → "等待和提醒" (Waits & alerts); turning it off does not affect the amber breathing or clicking to bring back the browser.
- The progress window's settings (download folder, waits and alerts, API keys): click the capsule's gear, or run `paper-search settings [about|download|wait|keys|<KEY>]` (about: version and updates). When no download is running, it opens a window of its own, which goes away when the settings window is closed.
- `paper-search setup` also asks at the end whether to install the extension; `--skip-school` does not ask, `--install-school` installs it directly.

A backend the user maintains (such as the development build in the repository) is set with `paper-search config set PAPER_SEARCH_SCHOOL_EXECUTABLE <path>`; do not change a path the user configured on your own.

## Sign in to the school first (optional)

```bash
paper-search school login --doi <DOI of an article the school subscribes to>
```

- Use it when the user wants to sign in before a batch download, or to try whether sign-in works; normally it is not needed: a download that meets a login stops and waits for the user.
- It opens the download browser, passes the site checks automatically, chooses the school, and stops at the school login page for the user to sign in (waiting at most `browser_login_timeout` seconds; `--max-wait <seconds>` changes it for this run only); after sign-in it checks that the full text of this article is visible, does not download the PDF, and keeps the sign-in for later downloads.
- Only `success: true` (`state: signed_in`) means sign-in succeeded. `access_without_login`: this article needs no sign-in (open access or campus network); try again with another article that needs a subscription; for `login_timeout`, `browser_closed`, `institution_pdf_entitlement_missing` and others, tell the user what the reply's `message` says.
- The program manages the download browser and its profile directory; sign in with this command or simply by downloading; do not dig through the source code for another way to sign in. When school subscription downloads are not installed or no school is configured, follow the hint in the reply.

## Update and uninstall

- After PaperSearch is upgraded, the first use of school subscription downloads makes the same update automatically (one line on stderr); when the user turned off automatic updates (`PAPER_SEARCH_SCHOOL_AUTO_UPDATE=false`) or the automatic update failed, `status` says the extension is behind; run `paper-search school update`: it reinstalls the backend and dependencies and checks Chrome; the school settings, sign-in sessions, Chrome and ego lite are left alone. An installation that used Camoufox switches to Chrome and states the directory of the old Camoufox browser; the user decides whether to delete it by hand. When it is already up to date it does nothing; `--force` forces a reinstall.
- Uninstall: `paper-search school uninstall`. It first lists what will be deleted and what kept, and deletes the install directory after the user confirms; when the PaperSearch config points at this installation's backend, it turns off the school download and clears the backend path; when it points elsewhere, it is left unchanged. School settings and sign-in sessions are kept by default, and it asks about them; with `--yes` they are kept unless `--remove-data` is also given. Google Chrome and ego lite are not affected.

## School

The user's school is stored in the backend configuration, as the user gives it; never preset or replace it. The user only needs to name the school; the backend works out its federation; do not ask the user which federation it is:

```bash
paper-search-school setup --institution "School name the user gave" [--also-name "The school's official English name"]
```

- Supported now: the academic identity federations of China mainland and Macao (CARSI), Hong Kong (HKAF), Singapore (SGAF), Japan (GakuNin), South Korea (KAFE), Malaysia (SIFULAN), India (INFED), Turkey (YETKİM), Sri Lanka (LIAF), Bangladesh (TIGERfed), Pakistan (PKIFED), Oman (OMREN), research institutes in China mainland (CSTCloud), Saudi Arabia (Maeen), Cyprus (CyNet), Israel (IUCC), Iran (IRFED), Azerbaijan (AzScienceNet), the United Kingdom (UK federation), Ireland (Edugate), France (RENATER), the Netherlands (SURFconext), Belgium (Belnet), Luxembourg (eduID Luxembourg), the countries of Northern, Central, Southern and Eastern Europe, and countries in the Americas, Oceania and Africa (each federation in `federation-support.md`), plus schools that sign in only through OpenAthens. `--institution` can be a school name (in any language), the school's domain or an entityID; the backend searches each federation's school list, saves only once it knows which school it is, and saves the federation it belongs to.
- Federation lists give school names in the local language and in English (China mainland and Macao have Chinese, Japan Japanese, Turkey Turkish, most European and Latin American countries local-language names; Hong Kong, South Korea, Singapore, Malaysia, South Asia, North America, Oceania and Africa mostly English only). When the school name the user gave is not English, add `--also-name` with the school's official English name (publishers mostly list schools by their English names); when you are unsure of the English name, leave it out.
- Some schools sign in through a login entry shared by several schools (universities in Israel, Norway and Croatia, research institutes in China mainland, some schools in Pakistan and Latvia), and the federation list has only their domains: when the school name finds nothing, search again with `--institution <school name> --also-name <school website domain>`; the program finds the entry by the domain and searches publishers by the given school name.
- On `school_ambiguous`, list the `candidates` (school name, federation, domain) for the user to choose, then rerun with the chosen school's `entity_id` as `--institution`; ask even when there is only one candidate: it is a school whose name does not quite match. On `school_not_found`, ask the user for the school's official name, English name or domain; when it is still not found, explain truthfully as the reply's `reasons` say: this school may not be connected to an academic identity federation or OpenAthens, and school subscription downloads cannot sign in for it; `federation_not_supported` means the school was found but its federation is not supported yet: tell the user so truthfully; `school_list_unavailable` means the list could not be fetched: retry later. When the user should send feedback, see "When school login fails" in `federation-support.md`.
- `--carsi --institution` searches only the CARSI list (error codes `carsi_school_*`); to look up the CARSI list: `paper-search-school setup --list-carsi-schools <keyword>`.
- When the `school` item of `setup --check` is `missing`, only the school name was saved; rerun the command above as the hint says.
- Once configured, the program chooses the federation and the school and presses continue; the user only enters the account and password on the school login page and completes human verification.
- With no school configured (`setup --carsi`), CARSI is still on, and the user chooses on the school-selection page.
- When the user's school is not in the publisher's list, report that it was not found; do not choose another school instead.
- Backend commands must use the same data directory as the downloads (PaperSearch's default is `${XDG_DATA_HOME:-~/.local/share}/paper-search-cli/school`); when needed, put `SCHOOL_DATA_DIR=<that directory>` before the command. The sign-in state is kept in the download browser in this directory.

### Several schools

Several schools can be saved; one of them is the current school, which downloads use by default. **Switch or name a school only when the user clearly asks; never switch on your own, and do not suggest which one to switch to.**

```bash
paper-search-school schools                      # list saved schools; current is the current school
paper-search-school use "School name"            # switch the current school; when not saved yet, look it up and save it as setup --institution does
paper-search-school forget "School name"         # remove it from the list (the current school cannot be removed)
```

- When `setup --institution` changes the school, the old school stays in the list too. `use` accepts a school name, English name, domain or entityID; on `school_ambiguous`, list the `candidates` for the user to choose. For a school not saved yet, `use` looks it up and reports errors as above (`--also-name` too).
- To use another saved school only for this batch (the user says "download these with school X"): add `school` (the school name, etc.) to `download_batch`; the current school does not change, and this batch's "go on" (接着下) uses it too. When the extension is too old to know it, it reports "需要更新" (update needed, `school_update_needed`); run `paper-search school update`.
- Every school's sign-in is in the same download browser; switching does not sign out of the others; the user still enters the account and password on the school login page.

## Browser

The backend setting `browser_backend` takes one of two values:

- `chrome` (default): the user's own Google Chrome, started by the backend with a separate browser profile, not touching the profile and tabs of the user's everyday Chrome. At the first download the user signs in to the school once in its window, and the sign-in is kept afterwards. Use it for everyday and batch downloads. When Chrome is installed elsewhere: `paper-search-school config set chrome_executable <Chrome program path>`. The old value `camoufox` is treated as `chrome`.
- `ego`: choose it to reuse sign-ins already in the user's ego lite (Chromium-based; the user and the agent look at the same browser; macOS only). The user must open `chrome://inspect/#remote-debugging` in ego and tick "Allow remote debugging for this browser instance" once. On each connection (for example after ego restarts) ego shows an "允许连接" (allow connection) prompt once, for the user to confirm; when the ego window is in the background the connection is often refused outright, and the download reports an error at once with the reason: ask the user to bring ego to the front, press "允许" (Allow), and retry.

Check or switch:

```bash
paper-search-school config get browser_backend
paper-search-school config set browser_backend chrome
```

The two browser profiles do not affect each other; switching does not delete the other one. Do not switch unless the user asks; `paper-search school install --browser ego` also switches the installation.

## Boundaries

- The account, password and verification codes are entered only by the user in the browser; they never appear in the chat, command arguments, configuration or logs.
- `entitled_access` as `available` in `doctor` only means the backend can be reached; it does not mean signed in, or access to any paper.
