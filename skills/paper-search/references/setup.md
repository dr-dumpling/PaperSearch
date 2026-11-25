# Setup: "start setup" (请开始配置)

When the user says "start setup" (or "请开始配置", "配置 PaperSearch", "set up PaperSearch"), follow the fixed flow below. Ask one question at a time and wait for the answer before going on; do not list all the settings for the user to fill in at once.

1. Run `paper-search doctor --format text` to see what is already set up; this step needs no question to the user. When there is no `paper-search` command, first install it with the user's consent as "When only the Skill is installed" in `management-layer.md` says, then run it.
2. Ask only one question: whether to use school subscription downloads (school setup). When asking, explain that it downloads the full texts and supplementary files of non-OA articles with the school account, and needs Google Chrome (installed too if missing). Do not ask in these cases: already installed (`entitled_access` in `doctor` is `available`): go straight to A; this computer has no graphical interface, or the user said no before (`PAPER_SEARCH_SCHOOL_DECLINED` is `true`): go straight to B. When the user says no, run `paper-search config set PAPER_SEARCH_SCHOOL_DECLINED true` to record it, then go to B.

A. School setup (the user agrees to use school subscription downloads)

1. When it is not installed, install it (see `school-setup.md`): `paper-search school install --yes --skip-school`; when there is no Chrome, install Chrome first.
2. Ask the user for their school right away and set it: run `paper-search-school setup --institution "School name"` (see "School" in `school-setup.md`). Skip this only when the user says to skip it; then they choose on the school-selection page at the first download.
3. Everything else is set in the settings window: it opens by itself after installation; when it did not open, or it was installed long ago, run `paper-search settings` directly to open the settings window. Tell the user to enter the API keys they want and change the download folder and wait times in the window; each key has a "测试" (Test) button; when done, close it with the × at the top right. Recommend EasyScholar (impact factors and quartiles) and Semantic Scholar (body snippets) first; the other keys are optional. Do not ask for keys or the download folder one by one in the chat.
4. When the user says they are done, run `paper-search doctor --format text` and tell the user what they can use now.

B. No school setup

1. Recommend only two keys: `EASYSCHOLAR_KEY` (impact factors and quartiles) and `SEMANTIC_SCHOLAR_API_KEY` (body snippets), with where to apply (the To enable line in `doctor`); all other keys are optional; mention them only when the user asks. When the user needs neither, skip to step 4.
2. Ask the user to run `paper-search setup --skip-school` in their own terminal to enter the keys (the input is hidden), and to tell you when done.
3. When the user says they are done, run `paper-search config test <KEY>` for each key they entered to confirm it works.
4. Set the default download folder (see "Default download folder" below).
5. Run `paper-search doctor --format text` and tell the user what they can use now.

Outside "start setup": when the user first wants a subscription article, school subscription downloads are not installed, the user has not said no, and this computer has a graphical interface, also ask once whether to install it (explained as in step 2); when they agree, do steps 1–3 of A. When the user only asks what a capability lacks, mention only the key it needs and where to apply; for entering it, use step 3 of A (the settings window) or step 2 of B (the terminal).

## Default download folder

During setup, or at the first download when it has not been set, first check whether it is set:

```bash
paper-search config get DEFAULT_DOWNLOAD_PATH
```

When it is not set (`configured` is `false`), ask the user: "Which folder should downloaded papers go to by default?" When the user gives a place, save it as a full path (`~` means the home folder):

```bash
paper-search config set DEFAULT_DOWNLOAD_PATH "~/Documents/Papers"
```

After that, do not pass `savePath` / `--save-path` when downloading: files go into a new `<YYYYMMDD-HHmmss>_PaperSearchDownload` folder created in this folder each time; pass it only when the user names another place for this download. When it is not set, files go to `./downloads` under the command's current directory, a place that changes and that users find hard to locate. Users can also change this folder in the settings of the progress capsule.
