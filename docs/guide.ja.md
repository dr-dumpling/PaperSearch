# PaperSearch 使い方

インストール、API キー、機関ダウンロードの設定は [README](../README.ja.md) を参照してください。以下のコマンドはターミナルやスクリプトから直接実行することもでき、出力は既定で JSON です。

## コマンド例

```bash
# 論文を検索（キーが不要なソースの組み合わせ）
paper-search search "machine learning clinical prediction" --sources no-key --max-results 5 --pretty

# ソースを 1 つ指定（例：PubMed）
paper-search search "SGLT2 inhibitor heart failure" --platform pubmed --max-results 10 --pretty

# DOI を 1 件確認
paper-search run get_paper_by_doi --arg doi="10.1038/nature12373" --pretty

# 被引用論文。参考文献は get_paper_citations を get_paper_references に替える
paper-search run get_paper_citations --arg doi="10.1038/nature12373" --pretty

# 雑誌のインパクトファクターと四分位（EasyScholar のキーが必要）
paper-search journal-metrics "Nature" "BMJ" --pretty

# 本文から Methods の書き方を探す（Semantic Scholar のキーが必要）
paper-search run search_semantic_snippets --arg query="propensity score matching" --arg limit=3 --pretty

# 1 件ダウンロード
paper-search download "<DOI>" --platform crossref

# PDF と補足資料を一括ダウンロード（content には pdf、supplements、またはその両方を指定。省略すると PDF のみ）
paper-search run download_batch --json-args '{"items":[{"doi":"<DOI-1>"},{"doi":"<DOI-2>"}],"content":"pdf,supplements"}'

# ダウンロードできなかった論文とその理由
paper-search failures --format text
```

## 仕組み

```text
ユーザーの文献リクエスト
│
├─ 論文を探す、DOI/PMID を確認 → paper-search search（Crossref、PubMed、OpenAlex など）
│    └─ 項目を確認し、全文が必要 → 下の「ダウンロード」へ
├─ 被引用論文、参考文献 → paper-search run get_paper_citations / get_paper_references
├─ インパクトファクター、四分位 → paper-search journal-metrics（EasyScholar のキーが必要）
├─ Methods の書き方、パラメータを探す → paper-search run search_semantic_snippets（Semantic Scholar のキーが必要）
│
└─ 本文、補足資料のダウンロード → paper-search download / run download_with_fallback / run download_batch
     同じダウンロードコマンドで、順に試す：
     ├─ ① オープンダウンロード（標準で利用可）：ソース自身のダウンロード、PMC、Unpaywall、出版社 API
     ├─ ② Sci-Hub フォールバック（既定でオン、オフにできる）
     ├─ ③ 機関ダウンロード（任意の拡張機能）：ブラウザが学校の加盟する学術認証フェデレーションか OpenAthens 経由で学校にログインし、出版社サイトから PDF と補足資料を取得
     ├─ ④ arXiv プレプリント：それまでに正式な出版版が得られなかった場合だけ使い、プレプリントと明記
     ├─ 各段階で得たファイルは 1 ページ目の DOI とタイトルを確認。一致すれば保存し、以降の段階は試さない
     └─ どれでも得られない → paper-search failures で理由を説明
```

### 2 つのダウンロード方法

|  | オープンダウンロード（既定） | 機関ダウンロード（任意の拡張機能） |
|---|---|---|
| すぐ使えるか | インストールすればすぐ使える | 別途インストールが必要：`paper-search school install` |
| 得られるもの | オープンアクセスの本文 | 学校が購読している本文。ルールのある出版社では補足資料も取得 |
| 取得方法 | プログラムが直接ダウンロード、通常数秒、ログイン不要：ソース自身のダウンロード、メタデータ内の PDF アドレス、PubMed Central、Unpaywall、出版社 API（自分の Elsevier/Springer キー）。最後に既定でオンの Sci-Hub フォールバック | Chrome を開き、学校の加盟する学術認証フェデレーションか OpenAthens 経由で学校にログインし、出版社サイトで PDF を取得 |
| ユーザーの作業 | なし | ブラウザで学校にログイン。確認はプログラムが自動で通過し、手動の操作が必要なときは案内に従う |

どちらの方法も同じダウンロードコマンドを使います。まずオープンダウンロードを試し、得られない場合、機関ダウンロードがインストールされていれば学校の権限で続けます。

- 数十〜数百件は `download_batch` を 1 回使います：各論文はまずオープンな入手先を試し、本文が得られなかったものはすぐ機関ダウンロードに回し、両方が同時に進みます。学校ログインは開始から数秒で表示されます。終了後、`paper-search failures` がダウンロードできなかった論文を 5 つに分類します：アクセス権なし（ページの文言などの根拠付き）、要対応（ログイン、確認、待機など）、外部要因（サイト、学校、ネットワークの問題）、未対応（PaperSearch 側で規則を追加予定、スクリーンショットの場所付き）、原因不明。
- arXiv の論文はまず正式な出版版を探し、どれも得られなかった場合だけプレプリントをダウンロードします。結果には `version: "preprint"` と書かれ、わかっている場合は正式版の DOI を添えます。
- Sci-Hub を使わない場合は、`download_with_fallback` / `download_batch` で `"useSciHub": false` を指定します。
- PDF はすべて 1 ページ目の DOI とタイトルを確認します。一致しないものは成功とせず、別に保管して確認待ちにします。

### ダウンロード結果

ダウンロードのたびに、ダウンロード先に `<年月日-時分秒>_PaperSearchDownload` フォルダを作り、今回の論文はすべてその中に入ります。PDF はこのフォルダに直接置きます。補足資料を取得できた論文は個別のフォルダに分け、本文とその論文の `supplements/`（元のファイル名のまま）を入れます。補足資料を取得できなかった論文は PDF のまま並べて置きます。本文のファイル名は「雑誌略称_年月_タイトル」です（年月は論文が最初に発表された年月）。同じ名前の PDF には短い番号を自動で付け、上書きしません。2 本の論文の名前が同じときは、後の論文のフォルダ名に `_2` を付けます。問題が起きた論文や確認が必要な論文の診断記録とスクリーンショットは、ダウンロード先ではなく PaperSearch 自身の実行記録（`~/.local/share/paper-search-cli/runs/`、30 日後に自動削除）に置き、問題を調べるときに使います。ログイン情報を含むことがあるので、他人に渡さないでください。雑誌名や年がわからないときは「未知期刊」「未知年份」と書きます。コマンドが返す JSON に各ファイルの実際の場所が書かれています。

## 検索ソース

| 分類 | ソース | 必要な API キー |
|---|---|---|
| 総合的な学術メタデータ | Crossref、OpenAlex、Semantic Scholar、Google Scholar | 不要（Semantic Scholar の本文スニペット検索には必要） |
| 生物医学 | PubMed、PubMed Central、Europe PMC | 不要（PubMed のキーで上限が上がる） |
| プレプリントと会議論文 | arXiv、bioRxiv、medRxiv、OpenReview、IACR ePrint | 不要 |
| コンピュータと工学 | DBLP、ACM、USENIX | 不要 |
| オープンアクセスとリポジトリ | CORE、OpenAIRE、Unpaywall | Unpaywall はメールアドレスを入力。CORE、OpenAIRE は任意 |
| 出版社と引用データベース | ScienceDirect、Scopus、Springer Nature、IEEE Xplore、Web of Science | それぞれのキーが必要（ScienceDirect と Scopus は Elsevier のキーを共用） |
| 雑誌の指標 | EasyScholar | 必要 |

- キーが不要なソースだけで、主要出版社の論文はすでに収録されています。キーを設定すると、出版社自身の検索窓口が加わります。
- ソース 1 つなら `--platform`、複数なら `--sources a,b,c` を使います。`--sources no-key` はキーがまったく不要な組み合わせです（Crossref、PubMed、Europe PMC、arXiv、OpenReview）。
- Google Scholar は Web ページを解析するため確認が出やすく、`--sources all` には含まれません。必要なときは `--platform googlescholar` を使います。
- 複数のソースが同じ論文を返したときは DOI でまとめます。arXiv のプレプリントと正式な出版版が DOI で明確に関連付けられている場合は、正式版の記録を残します。
- Sci-Hub は検索ソースではなく、ダウンロード時に DOI で補完するためだけに使います。

## Agent Skill

Skill は npm パッケージに同梱して配布しています（`skills/paper-search/`）。すべて英語で書かれ、冒頭に全体の流れ図があり、必要に応じて次の参照ファイルを読みます：機能の振り分けとオープンダウンロードの各経路、コマンド仕様、機関ダウンロードのインストールと使い方、[出版社対応表](../skills/paper-search/references/publisher-support.md)、トラブルシューティング。Skill は AI に `paper-search` の呼び出し方を伝えるだけで、キー、Cookie、アカウントは保存しません。

Skill だけをインストールするには（Node.js 22 以上が必要）、次を実行して、使っている AI ツールを選びます：

```bash
npx skills add dr-dumpling/PaperSearch -g
```

初めて使うとき、AI は `paper-search` コマンドがまだインストールされていないことに気づくと、まず確認し、同意を得てからインストールします。

AI を介さずに、自分でターミナルからコマンドと Skill をまとめてインストールする場合は 1 行で済みます（Claude Code の例）：

```bash
npm install -g papersearch && paper-search skills update --targets claude
```

```bash
paper-search skills status --pretty
paper-search skills update
```

`--targets` を指定しないと、すでに Skill がインストールされている場所だけを確認・更新し、ほかの場所に追加でインストールすることはありません。`--targets` には `codex`、`claude`、`cursor`、`gemini`、`antigravity`、`agents`（共有ディレクトリ `~/.agents/skills/`）を指定できます。Skill フォルダを読むその他の AI ツールでは、同梱の Skill をそのツールの Skill ディレクトリにコピーします：`npm root -g` でグローバルの npm ディレクトリを確認でき、同梱の Skill はその下の `papersearch/skills/paper-search/` にあります。コピーするときは `references/` を含むフォルダ全体を保持し、更新時は新しいバージョンからコピーし直します。インストール後、AI の新しいセッションを開くと使えます。

- `--targets all` は組み込みのすべての場所に同期します。更新するとパッケージが管理するファイルは上書きされ、旧バージョンでインストールされ新バージョンでは使わなくなったファイルは `skill-backups` バックアップフォルダに移ります。Skill ディレクトリに自分で追加したファイルは残ります。
- PaperSearch をアップグレードした後の最初の実行時に、インストール済みの Skill が自動で更新され、置き換えられた古いファイルは `~/.local/share/paper-search-cli/skill-backups/` にバックアップされます。自動更新しない場合：`paper-search config set PAPER_SEARCH_SKILL_AUTO_UPDATE false`。インストールした Skill がコマンドラインプログラムより新しい場合（たとえば先に GitHub から新しい Skill をインストールした場合）、古いバージョンに戻されることはなく、コマンドラインが 1 日 1 回 `npm install -g papersearch@latest` の実行を案内します。
- 学校購読ダウンロードをインストールしている場合、アップグレード後に初めてそれを使うときに拡張機能も先に自動更新され（ターミナルに 1 行表示されます）、そのままダウンロードを続けます。自動更新しない場合：`paper-search config set PAPER_SEARCH_SCHOOL_AUTO_UPDATE false` を設定し、以後は自分で `paper-search school update` を実行します。
- `paper-search doctor` は、組み込みのインストール先にある Skill の場所とバージョンの状態を表示します。

## コマンド一覧

| コマンド | 用途 |
|---|---|
| `paper-search search` | 論文のメタデータを検索 |
| `paper-search journal-metrics` | 雑誌の指標（EasyScholar） |
| `paper-search download` | 確認済みの論文の PDF をダウンロード |
| `paper-search run <ツール>` | 特定のツールを直接呼び出す。引数は `--arg` か `--json-args` で指定 |
| `paper-search failures` | ダウンロード失敗の理由をまとめる |
| `paper-search update check` | 新しいバージョンがあるか確認 |
| `paper-search update install` | 新しいバージョンに更新（設定ウィンドウの「PaperSearch について」ページで「… に更新」を押しても、すべてのコンポーネントを一度に更新できる） |
| `paper-search school` | 学校購読ダウンロードのインストール、状態確認、更新、アンインストール |
| `paper-search setup` / `config` | キー、Skill、拡張機能を設定 |
| `paper-search settings` | 設定ウィンドウを開く：ダウンロード先、待機と通知、API キー（学校購読ダウンロードのインストールと GUI 環境が必要） |
| `paper-search uninstall` | アンインストール：削除する内容（学校購読ダウンロードとログイン状態、実行記録、設定と API キー、各 AI ツールの Skill）をまず一覧にし、確認後にまとめて削除。ダウンロードした論文はそのまま。`--dry-run` は一覧表示のみで削除しない |
| `paper-search doctor` | ヘルスチェック：設定、使える機能、Skill と拡張機能の状態 |
| `paper-search skills` | Skill の状態、差分、更新 |
| `paper-search smoke` | オフラインまたは実環境でのセルフチェック |
| `paper-search tools` | すべてのツール名と引数を一覧表示 |

コマンドは既定で JSON を出力します。`--pretty` で整形し、`--format text` で人が読むためのレポートを出力します。全コマンドは `paper-search tools --pretty` か [コマンド仕様](../skills/paper-search/references/cli-contract.md)を参照してください。

## その他の設定

`paper-search config set <設定項目> <値>` で変更するか、`paper-search setup <設定項目>` を実行します。

| 設定項目 | 役割 | 既定値 |
|---|---|---|
| `DEFAULT_DOWNLOAD_PATH` | ダウンロードした論文の既定の保存先フォルダ | コマンドを実行したディレクトリの `./downloads`。進捗カプセルの設定でも変更できる |
| `UNPAYWALL_EMAIL`、`CROSSREF_MAILTO` | Unpaywall で DOI からオープンアクセスの PDF を探すとき、Crossref の優先枠を使うときの連絡用メールアドレス | `paper-search setup` で空欄にすると自動生成。設定ウィンドウでも入力できる |
| `GOOGLE_SCHOLAR_PROXY_URL` | Google Scholar 用の出口プロキシ。直接接続が繰り返しブロックされるときに、利用が許可されたプロキシを使う | 未設定 |
| `PAPER_SEARCH_SKILL_AUTO_UPDATE` | `false` にすると、アップグレード後にインストール済みの Skill を自動更新しない | オン |
| `PAPER_SEARCH_SCHOOL_AUTO_UPDATE` | `false` にすると、アップグレード後に学校購読ダウンロードの拡張機能を自動更新せず、自分で `paper-search school update` を実行する | オン |
| `PAPER_SEARCH_UPDATE_NOTIFY` | `false` にすると、新しいバージョンの通知を出さない | オン |
| `PAPER_SEARCH_SCHOOL_DECLINED` | `true` にすると、AI は学校購読ダウンロードのインストールを自分から勧めない（インストールしないと伝えると AI が自動で設定する）。インストールしたいときはそう伝えるだけでよい | 未設定 |
| `PAPER_SEARCH_SCHOOL_ENABLED` | 学校購読ダウンロードのオン/オフ | `paper-search school install` が自動で設定 |

## トラブルシューティング

| 問題 | 対処 |
|---|---|
| `paper-search` コマンドが見つからない | `npm install -g papersearch` で再インストール |
| インストール時に `EEXIST` が出る、または旧パッケージ `paper-search-cli` から移行する | 先に `npm uninstall -g paper-search-cli` を実行してから `papersearch` をインストール。設定、Skill、学校ログイン、ダウンロード記録はすべて残る |
| 一部の機能が使えない | `paper-search doctor --format text` で足りないものを確認し、`paper-search setup` で設定 |
| 学校が購読している論文をダウンロードできない | `paper-search school status --format text` で学校購読ダウンロードがインストールされているか確認。`paper-search failures --format text` で論文ごとの理由を確認 |
| ソースのレート制限 | `--max-results` を減らす、対応するキーを設定する、またはソースを変える |
| Google Scholar で確認ページが出る | しばらく待って再試行するか、`--sources no-key` に切り替える |
| AI が読み込む Skill が古い | `paper-search skills status --pretty` の後に `paper-search skills update`。AI の新しいセッションを開く |
| 先に学校にログインしたい、またはログインできるか試したい | `paper-search school login --doi <学校が購読している論文の DOI>`：ダウンロード用ブラウザが開くので、学校のログインページでログインする |
| 学校購読ダウンロードの更新またはアンインストール | `paper-search school update`、`paper-search school uninstall` |
| PaperSearch のアンインストール | `paper-search uninstall` で確認した後、`npm uninstall -g papersearch` を実行 |
| Windows の PowerShell で `npm` がブロックされる | `npm.cmd` を使うか、コマンドプロンプトで実行 |
| ダウンロードの失敗を報告したい | Issue の「Download failure or publisher request」テンプレートを使い、バージョン、OS、サイト、DOI を記入。`paper-search failures --export ./failure-report.zip` で失敗記録を書き出せる。添付する前に、中の `summary.md` とスクリーンショットに個人情報がないか確認 |
| アップグレード方法 | `npm install -g papersearch@latest`。アップグレード後の最初の実行時に、インストール済みの Skill が自動で更新される |
