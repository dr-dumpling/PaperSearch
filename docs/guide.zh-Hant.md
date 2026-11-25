# PaperSearch 使用說明

安裝、API key 和機構下載的配置見 [README](../README.zh-Hant.md)。下面的命令也可以在終端或腳本裡直接執行，輸出預設是 JSON。

## 命令示例

```bash
# 檢索論文（不需要任何 key 的來源組合）
paper-search search "machine learning clinical prediction" --sources no-key --max-results 5 --pretty

# 指定一個來源，例如 PubMed
paper-search search "SGLT2 inhibitor heart failure" --platform pubmed --max-results 10 --pretty

# 核驗一個 DOI
paper-search run get_paper_by_doi --arg doi="10.1038/nature12373" --pretty

# 施引文獻；參考文獻把 get_paper_citations 換成 get_paper_references
paper-search run get_paper_citations --arg doi="10.1038/nature12373" --pretty

# 期刊影響因子和分區（需要 EasyScholar key）
paper-search journal-metrics "Nature" "BMJ" --pretty

# 在正文裡找 Methods 寫法（需要 Semantic Scholar key）
paper-search run search_semantic_snippets --arg query="propensity score matching" --arg limit=3 --pretty

# 下載一篇
paper-search download "<DOI>" --platform crossref

# 批次下載 PDF 和補充材料（content 可寫 pdf、supplements，或兩樣都寫；不寫只下 PDF）
paper-search run download_batch --json-args '{"items":[{"doi":"<DOI-1>"},{"doi":"<DOI-2>"}],"content":"pdf,supplements"}'

# 沒下到的篇目和原因
paper-search failures --format text
```

## 工作方式

```text
使用者的文獻請求
│
├─ 找論文、核驗 DOI/PMID → paper-search search（Crossref、PubMed、OpenAlex 等）
│    └─ 確認條目、需要全文 → 轉到下面的「下載」
├─ 查施引文獻、參考文獻 → paper-search run get_paper_citations / get_paper_references
├─ 查影響因子、分區 → paper-search journal-metrics（需要 EasyScholar key）
├─ 找 Methods 寫法、參數 → paper-search run search_semantic_snippets（需要 Semantic Scholar key）
│
└─ 下載正文、補充材料 → paper-search download / run download_with_fallback / run download_batch
     同一個下載命令，按順序嘗試：
     ├─ ① 開放下載（預設就有）：來源自帶的下載、PMC、Unpaywall、出版社接口
     ├─ ② Sci-Hub 兜底（預設開啟，可關閉）
     ├─ ③ 機構下載（可選擴展）：瀏覽器經學校所屬的學術身份聯盟或 OpenAthens 登入你的學校，在出版社網站取 PDF 和補充材料
     ├─ ④ arXiv 預印本：前面都沒拿到正式發表版時才用，並標明是預印本
     ├─ 每一步拿到檔案都核對首頁的 DOI 和題名；通過就儲存，後面的步驟不再試
     └─ 都沒拿到 → paper-search failures 說明原因
```

### 兩種下載方式

|  | 開放下載（預設） | 機構下載（可選擴展） |
|---|---|---|
| 能不能直接用 | 裝好就能用 | 要另外安裝：`paper-search school install` |
| 能拿到什麼 | 開放獲取的正文 | 你的學校訂閱的正文；有規則的出版社還能取補充材料 |
| 怎麼拿 | 程式直接下載，通常幾秒，不用登入：來源自帶的下載、元資料里的 PDF 地址、PubMed Central、Unpaywall、出版社接口（你自己的 Elsevier/Springer key）；最後是預設開啟的 Sci-Hub 兜底 | 打開 Chrome，經學校所屬的學術身份聯盟或 OpenAthens 登入你的學校，在出版社網站上取 PDF |
| 你要做的事 | 無 | 在瀏覽器裡登入學校；程式自動過驗證，需要人工接管時再按提示操作 |

兩種方式用同一個下載命令：先試開放下載，拿不到時，裝了機構下載才繼續用學校權限。

- 幾十到幾百篇用一次 `download_batch`：每篇先試開放渠道，沒拿到正文的隨即用機構下載，兩者同時進行，學校登入在開始後幾秒就會提示。結束後 `paper-search failures` 把沒下到的篇目分成五類：沒權限（附頁面原話等依據）、要你處理（登入、驗證、等待等）、外部原因（網站、學校或網路的問題）、暫不支援（PaperSearch 待補規則，附截圖位置）、原因不明。
- arXiv 論文先找正式發表版，都沒拿到才下載預印本；結果裡寫 `version: "preprint"`，已知時附正式版 DOI。
- 不想用 Sci-Hub 時，在 `download_with_fallback` / `download_batch` 里設 `"useSciHub": false`。
- 每個 PDF 都核對首頁的 DOI 和題名；對不上的不算成功，單獨留待核查。

### 下載結果

每次下載在下載目錄裡新建一個 `<年月日-時分秒>_PaperSearchDownload` 資料夾，這次的論文都在裡面：PDF 直接放在這個資料夾里；取到了補充材料的論文單獨一個資料夾，正文和該篇的 `supplements/`（保留原檔案名）在其中，沒取到補充材料的仍是平鋪的 PDF。正文按「期刊縮寫_年月_標題」命名（年月是文章首次發表的年月），同名的 PDF 自動加一段短編號，不會互相覆蓋；兩篇論文名字相同時，後一篇的資料夾名後加 `_2`。出過問題或需要核查的論文，診斷記錄和截圖不放在下載資料夾里，放在 PaperSearch 自己的執行記錄裡（`~/.local/share/paper-search-cli/runs/`，30 天后自動刪除），查問題時用；裡面可能帶登入資訊，不要發給別人。缺少期刊或年份時寫「未知期刊」「未知年份」。命令返回的 JSON 里寫著每個檔案的實際位置。

## 檢索來源

| 類別 | 來源 | 需要的 API key |
|---|---|---|
| 綜合學術元資料 | Crossref、OpenAlex、Semantic Scholar、Google Scholar | 不需要（Semantic Scholar 的正文片段檢索需要） |
| 生物醫學 | PubMed、PubMed Central、Europe PMC | 不需要（PubMed key 可提高限額） |
| 預印本和會議稿 | arXiv、bioRxiv、medRxiv、OpenReview、IACR ePrint | 不需要 |
| 計算機和工程 | DBLP、ACM、USENIX | 不需要 |
| 開放獲取和倉儲 | CORE、OpenAIRE、Unpaywall | Unpaywall 填電子郵件；CORE、OpenAIRE 可選 |
| 出版社和引文庫 | ScienceDirect、Scopus、Springer Nature、IEEE Xplore、Web of Science | 需要各自的 key（ScienceDirect、Scopus 共用 Elsevier key） |
| 期刊指標 | EasyScholar | 需要 |

- 不需要 key 的來源已經收錄了各大出版社的論文；配了 key，多的是出版社自己的檢索入口。
- 單個來源用 `--platform`，多個用 `--sources a,b,c`；`--sources no-key` 是不需要任何 key 的組合（Crossref、PubMed、Europe PMC、arXiv、OpenReview）。
- Google Scholar 是網頁解析，容易觸發驗證，不在 `--sources all` 里；需要時用 `--platform googlescholar`。
- 多個來源返回同一篇論文時按 DOI 合併；arXiv 預印本和正式發表版有明確 DOI 關聯時，保留正式發表記錄。
- Sci-Hub 不是檢索來源，只在下載時按 DOI 兜底。

## Agent Skill

Skill 隨 npm 包發布（`skills/paper-search/`），全英文，開頭有整體邏輯圖，按需讀這些參考檔案：功能路由與開放下載的各個渠道、命令約定、機構下載的安裝和使用、[出版社支援表](../skills/paper-search/references/publisher-support.md)、排障。它只告訴 AI 怎麼調用 `paper-search`，不儲存 key、Cookie 或帳號。

單獨安裝 Skill（需要 Node.js 22 或以上），執行後選你用的 AI 工具：

```bash
npx skills add dr-dumpling/PaperSearch -g
```

第一次用時，AI 發現還沒裝 `paper-search` 命令，會先問你，同意後再裝。

不經過 AI、自己在終端把命令和 Skill 一起裝好，一行即可（以 Claude Code 為例）：

```bash
npm install -g papersearch && paper-search skills update --targets claude
```

```bash
paper-search skills status --pretty
paper-search skills update
```

不寫 `--targets` 時只檢查、更新已經裝了 Skill 的位置，不會在別處多裝一份。`--targets` 可選 `codex`、`claude`、`cursor`、`gemini`、`antigravity`、`agents`（共享目錄 `~/.agents/skills/`）。其他讀取 Skill 資料夾的 AI 工具，把隨包 Skill 複製到它的 Skill 目錄即可：`npm root -g` 可查看全局 npm 目錄，隨包 Skill 位於其下的 `papersearch/skills/paper-search/`；複製時保留完整資料夾及 `references/`，更新時從新版本複製。安裝後新開 AI 會話即可使用。

- `--targets all` 會同步到所有內置位置。更新會覆蓋包里管理的檔案，舊版裝進來、新版已不再用的檔案移到 `skill-backups` 備份資料夾，保留你在 Skill 目錄裡自己加的檔案。
- 升級 PaperSearch 後第一次執行時，裝過的 Skill 會自動更新，被替換的舊檔案備份在 `~/.local/share/paper-search-cli/skill-backups/`。不想自動更新：`paper-search config set PAPER_SEARCH_SKILL_AUTO_UPDATE false`。裝的 Skill 比命令行程式新時（例如先從 GitHub 裝了新版 Skill），不會被換回舊版，命令行每天提示一次執行 `npm install -g papersearch@latest`。
- 裝了學校訂閱下載的，升級後第一次用到它時，擴展也會先自動更新（終端里有一行說明），再接著下載。不想自動更新：`paper-search config set PAPER_SEARCH_SCHOOL_AUTO_UPDATE false`，之後自己執行 `paper-search school update`。
- `paper-search doctor` 顯示內置安裝目標中的 Skill 位置和版本狀態。

## 全部命令

| 命令 | 用途 |
|---|---|
| `paper-search search` | 檢索論文元資料 |
| `paper-search journal-metrics` | 期刊指標（EasyScholar） |
| `paper-search download` | 下載已核驗論文的 PDF |
| `paper-search run <工具>` | 精確調用某個工具，參數用 `--arg` 或 `--json-args` |
| `paper-search failures` | 匯總下載失敗的原因 |
| `paper-search update check` | 檢查是否有新版本 |
| `paper-search update install` | 更新到新版本（也可以在設定視窗「關於」頁點「更新到」，一次更新全部組件） |
| `paper-search school` | 學校訂閱下載的安裝、狀態、更新、卸載 |
| `paper-search setup` / `config` | 配置 key、Skill 和擴展 |
| `paper-search settings` | 打開設定視窗：下載資料夾、等待和提醒、API key（需裝學校訂閱下載、有圖形界面） |
| `paper-search uninstall` | 卸載：先列出要刪的內容（學校訂閱下載和登入狀態、執行記錄、配置和 API key、各 AI 工具裡的 Skill），確認後一次刪完；下載的論文不動；`--dry-run` 只列出不刪 |
| `paper-search doctor` | 健康檢查：配置、可用功能、Skill 和擴展的狀態 |
| `paper-search skills` | Skill 的狀態、差異和更新 |
| `paper-search smoke` | 離線或真實的自檢 |
| `paper-search tools` | 列出所有工具名和參數 |

命令預設輸出 JSON，`--pretty` 排版，`--format text` 輸出給人看的報告。完整命令見 `paper-search tools --pretty` 或 [命令約定](../skills/paper-search/references/cli-contract.md)。

## 其他設定

用 `paper-search config set <設定項> <值>` 修改，或執行 `paper-search setup <設定項>`。

| 設定項 | 作用 | 預設 |
|---|---|---|
| `DEFAULT_DOWNLOAD_PATH` | 下載的論文預設存放的資料夾 | 命令當前目錄下的 `./downloads`；也可以在進度膠囊的設定里改 |
| `UNPAYWALL_EMAIL`、`CROSSREF_MAILTO` | Unpaywall 按 DOI 找開放獲取 PDF、Crossref 優先通道要用的聯繫電子郵件 | `paper-search setup` 留空時自動生成；也可以在設定視窗填 |
| `GOOGLE_SCHOLAR_PROXY_URL` | Google Scholar 的出口代理；直連反覆被攔時，用有授權的代理 | 不設定 |
| `PAPER_SEARCH_SKILL_AUTO_UPDATE` | 設為 `false` 時，升級後不再自動更新已安裝的 Skill | 開啟 |
| `PAPER_SEARCH_SCHOOL_AUTO_UPDATE` | 設為 `false` 時，升級後不再自動更新學校訂閱下載擴展，改為自己執行 `paper-search school update` | 開啟 |
| `PAPER_SEARCH_UPDATE_NOTIFY` | 設為 `false` 時，不再提示有新版本 | 開啟 |
| `PAPER_SEARCH_SCHOOL_DECLINED` | 設為 `true` 時，AI 不再主動建議安裝學校訂閱下載（你說過不裝時它會自己設上）；你要裝時直接說即可 | 未設定 |
| `PAPER_SEARCH_SCHOOL_ENABLED` | 學校訂閱下載的開關 | `paper-search school install` 自動設定 |

## 排障

| 問題 | 怎麼辦 |
|---|---|
| 找不到 `paper-search` 命令 | `npm install -g papersearch` 重新安裝 |
| 安裝時報 `EEXIST`，或從舊包 `paper-search-cli` 換過來 | 先 `npm uninstall -g paper-search-cli`，再裝 `papersearch`；配置、Skill、學校登入和下載記錄都會保留 |
| 某個功能不能用 | `paper-search doctor --format text` 看缺什麼，再 `paper-search setup` 配置 |
| 學校訂閱的文章下載不到 | `paper-search school status --format text` 看學校訂閱下載是否裝好；`paper-search failures --format text` 看每篇的原因 |
| 來源限流 | 減小 `--max-results`、配置對應 key，或換來源 |
| Google Scholar 出驗證頁 | 等一會兒再試，或改用 `--sources no-key` |
| AI 讀到的 Skill 是舊的 | `paper-search skills status --pretty`，再 `paper-search skills update`；新開一個 AI 會話 |
| 先登入學校、或試一下能不能登入 | `paper-search school login --doi <學校訂閱的一篇文章的 DOI>`：彈出下載用的瀏覽器，在學校登入頁登入即可 |
| 更新或卸載學校訂閱下載 | `paper-search school update`；`paper-search school uninstall` |
| 卸載 PaperSearch | `paper-search uninstall`，確認後再執行 `npm uninstall -g papersearch` |
| Windows 的 PowerShell 攔住 `npm` | 改用 `npm.cmd`，或在命令提示符里執行 |
| 想反饋下載失敗 | 用 Issue 里的「下載失敗」模板，寫明版本、系統、網站和 DOI；`paper-search failures --export ./failure-report.zip` 可以導出失敗記錄，附上前先檢查包里的 `summary.md` 和截圖有沒有個人資訊 |
| 怎麼升級 | `npm install -g papersearch@latest`；升級後第一次執行時，裝過的 Skill 會自動更新 |
