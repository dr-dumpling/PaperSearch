# PaperSearch 사용 안내

설치, API key, 기관 다운로드 설정은 [README](../README.ko.md)를 참고하세요. 아래 명령은 터미널이나 스크립트에서 바로 실행할 수도 있으며, 기본 출력은 JSON입니다.

## 명령 예시

```bash
# 논문 검색(키가 전혀 필요 없는 소스 조합)
paper-search search "machine learning clinical prediction" --sources no-key --max-results 5 --pretty

# 소스 하나 지정, 예: PubMed
paper-search search "SGLT2 inhibitor heart failure" --platform pubmed --max-results 10 --pretty

# DOI 하나 확인
paper-search run get_paper_by_doi --arg doi="10.1038/nature12373" --pretty

# 인용 문헌. 참고문헌은 get_paper_citations를 get_paper_references로 바꾸기
paper-search run get_paper_citations --arg doi="10.1038/nature12373" --pretty

# 저널 임팩트 팩터와 분위(EasyScholar 키 필요)
paper-search journal-metrics "Nature" "BMJ" --pretty

# 본문에서 Methods 서술 찾기(Semantic Scholar 키 필요)
paper-search run search_semantic_snippets --arg query="propensity score matching" --arg limit=3 --pretty

# 한 편 다운로드
paper-search download "<DOI>" --platform crossref

# PDF와 보충 자료 일괄 다운로드(content에는 pdf, supplements 중 하나 또는 둘 다; 생략하면 PDF만)
paper-search run download_batch --json-args '{"items":[{"doi":"<DOI-1>"},{"doi":"<DOI-2>"}],"content":"pdf,supplements"}'

# 받지 못한 논문과 원인
paper-search failures --format text
```

## 작동 방식

```text
사용자의 문헌 요청
│
├─ 논문 찾기, DOI/PMID 확인 → paper-search search(Crossref, PubMed, OpenAlex 등)
│    └─ 항목 확인, 전문 필요 → 아래 ‘다운로드’로
├─ 인용 문헌, 참고문헌 조회 → paper-search run get_paper_citations / get_paper_references
├─ 임팩트 팩터, 분위 조회 → paper-search journal-metrics(EasyScholar 키 필요)
├─ Methods 서술, 매개변수 찾기 → paper-search run search_semantic_snippets(Semantic Scholar 키 필요)
│
└─ 본문, 보충 자료 다운로드 → paper-search download / run download_with_fallback / run download_batch
     같은 다운로드 명령이 차례대로 시도:
     ├─ ① 오픈 다운로드(기본 제공): 소스 자체 다운로드, PMC, Unpaywall, 출판사 API
     ├─ ② Sci-Hub 대체 경로(기본으로 켜짐, 끌 수 있음)
     ├─ ③ 기관 다운로드(선택 확장): 브라우저가 학교가 속한 학술 인증 연합이나 OpenAthens로 학교에 로그인해 출판사 사이트에서 PDF와 보충 자료를 가져옴
     ├─ ④ arXiv 프리프린트: 앞 단계에서 정식 출판본을 받지 못했을 때만 쓰고, 프리프린트라고 표시
     ├─ 단계마다 받은 파일의 첫 페이지 DOI와 제목을 확인. 통과하면 저장하고 이후 단계는 시도하지 않음
     └─ 모두 실패 → paper-search failures가 원인을 알려 줌
```

### 두 가지 다운로드 방식

|  | 오픈 다운로드(기본) | 기관 다운로드(선택 확장) |
|---|---|---|
| 바로 쓸 수 있나 | 설치하면 바로 사용 | 따로 설치 필요: `paper-search school install` |
| 받을 수 있는 것 | 오픈 액세스 본문 | 학교가 구독하는 본문. 규칙이 있는 출판사는 보충 자료도 |
| 받는 방법 | 프로그램이 직접 다운로드하며 보통 몇 초, 로그인 불필요: 소스 자체 다운로드, 메타데이터의 PDF 주소, PubMed Central, Unpaywall, 출판사 API(본인의 Elsevier/Springer 키). 마지막은 기본으로 켜진 Sci-Hub 대체 경로 | Chrome을 열어 학교가 속한 학술 인증 연합이나 OpenAthens로 학교에 로그인하고, 출판사 사이트에서 PDF를 가져옴 |
| 사용자가 할 일 | 없음 | 브라우저에서 학교에 로그인. 확인은 프로그램이 자동으로 통과하고, 직접 처리해야 할 때 안내에 따라 조작 |

두 방식은 같은 다운로드 명령을 씁니다. 먼저 오픈 다운로드를 시도하고, 받지 못하면 기관 다운로드가 설치된 경우에만 학교 권한으로 이어서 받습니다.

- 수십~수백 편은 `download_batch` 한 번으로 받습니다. 논문마다 먼저 오픈 액세스 경로를 시도하고, 본문을 받지 못한 논문은 곧바로 기관 다운로드로 넘어가며 두 가지가 동시에 진행됩니다. 학교 로그인 안내는 시작 후 몇 초 안에 나옵니다. 끝나면 `paper-search failures`가 받지 못한 논문을 다섯 가지로 분류합니다: 권한 없음(페이지 원문 등 근거 첨부), 조치 필요(로그인, 확인, 대기 등), 외부 원인(사이트, 학교, 네트워크 문제), 미지원(PaperSearch에서 규칙을 추가할 문제, 스크린샷 위치 첨부), 원인 불명.
- arXiv 논문은 먼저 정식 출판본을 찾고, 받지 못했을 때만 프리프린트를 받습니다. 결과에는 `version: "preprint"`라고 적고, 알면 정식 출판본 DOI를 붙입니다.
- Sci-Hub를 쓰지 않으려면 `download_with_fallback` / `download_batch`에서 `"useSciHub": false`로 설정하세요.
- PDF마다 첫 페이지의 DOI와 제목을 확인합니다. 맞지 않으면 성공으로 치지 않고 따로 두어 확인을 기다립니다.

### 다운로드 결과

다운로드할 때마다 다운로드 폴더에 `<연월일-시분초>_PaperSearchDownload` 폴더가 새로 생기고, 이번에 받은 논문이 모두 들어갑니다. PDF는 이 폴더에 바로 들어갑니다. 보충 자료를 받은 논문은 따로 폴더가 생기고, 그 안에 본문과 이 논문의 `supplements/`(원래 파일 이름 유지)가 있습니다. 보충 자료를 받지 못한 논문은 그대로 PDF만 놓입니다. 본문 파일 이름은 ‘저널 약어_연월_제목’입니다(연월은 논문이 처음 발표된 연월). 이름이 같은 PDF에는 짧은 번호가 자동으로 붙어 서로 덮어쓰지 않으며, 두 논문의 이름이 같으면 뒤 논문의 폴더 이름 끝에 `_2`가 붙습니다. 문제가 있었거나 확인이 필요한 논문의 진단 기록과 스크린샷은 다운로드 폴더가 아니라 PaperSearch 자체 실행 기록(`~/.local/share/paper-search-cli/runs/`, 30일 후 자동 삭제)에 두며, 문제를 찾을 때 씁니다. 로그인 정보가 들어 있을 수 있으니 다른 사람에게 보내지 마세요. 저널이나 연도가 없으면 ‘未知期刊’(저널 미상), ‘未知年份’(연도 미상)으로 적습니다. 명령이 반환하는 JSON에 각 파일의 실제 위치가 나옵니다.

## 검색 소스

| 분류 | 소스 | 필요한 API key |
|---|---|---|
| 종합 학술 메타데이터 | Crossref, OpenAlex, Semantic Scholar, Google Scholar | 불필요(Semantic Scholar 본문 구절 검색은 필요) |
| 생의학 | PubMed, PubMed Central, Europe PMC | 불필요(PubMed 키가 있으면 한도 상향) |
| 프리프린트와 학회 논문 | arXiv, bioRxiv, medRxiv, OpenReview, IACR ePrint | 불필요 |
| 컴퓨터와 공학 | DBLP, ACM, USENIX | 불필요 |
| 오픈 액세스와 리포지터리 | CORE, OpenAIRE, Unpaywall | Unpaywall은 이메일 입력, CORE와 OpenAIRE는 선택 |
| 출판사와 인용 데이터베이스 | ScienceDirect, Scopus, Springer Nature, IEEE Xplore, Web of Science | 각자의 키 필요(ScienceDirect와 Scopus는 Elsevier 키 공용) |
| 저널 지표 | EasyScholar | 필요 |

- 키가 필요 없는 소스에도 주요 출판사의 논문이 이미 수록되어 있습니다. 키를 설정하면 출판사 자체 검색 창구가 추가됩니다.
- 소스 하나는 `--platform`, 여러 개는 `--sources a,b,c`를 씁니다. `--sources no-key`는 키가 전혀 필요 없는 조합입니다(Crossref, PubMed, Europe PMC, arXiv, OpenReview).
- Google Scholar는 웹 페이지를 파싱하므로 확인 페이지가 자주 나와 `--sources all`에 포함되지 않습니다. 필요하면 `--platform googlescholar`를 쓰세요.
- 여러 소스가 같은 논문을 돌려주면 DOI로 합칩니다. arXiv 프리프린트와 정식 출판본이 DOI로 명확히 연결되어 있으면 정식 출판 기록을 남깁니다.
- Sci-Hub는 검색 소스가 아니며, 다운로드할 때 DOI로 받는 대체 경로로만 쓰입니다.

## Agent Skill

Skill은 npm 패키지와 함께 배포되며(`skills/paper-search/`), 전부 영어로 쓰여 있고 첫머리에 전체 흐름도가 있습니다. 필요에 따라 다음 참고 파일을 읽습니다: 기능 라우팅과 오픈 다운로드의 각 경로, 명령 규약, 기관 다운로드의 설치와 사용, [출판사 지원표](../skills/paper-search/references/publisher-support.md), 문제 해결. Skill은 AI에게 `paper-search`를 호출하는 방법만 알려 주며, 키, 쿠키, 계정은 저장하지 않습니다.

Skill만 따로 설치하려면(Node.js 22 이상 필요) 다음을 실행한 뒤 사용하는 AI 도구를 고르세요:

```bash
npx skills add dr-dumpling/PaperSearch -g
```

처음 쓸 때 AI가 `paper-search` 명령이 아직 설치되지 않은 것을 알면 먼저 묻고, 동의하면 설치합니다.

AI를 거치지 않고 터미널에서 명령과 Skill을 함께 설치하려면 한 줄이면 됩니다(Claude Code 기준):

```bash
npm install -g papersearch && paper-search skills update --targets claude
```

```bash
paper-search skills status --pretty
paper-search skills update
```

`--targets`를 쓰지 않으면 Skill이 이미 설치된 위치만 확인·업데이트하고, 다른 곳에 추가로 설치하지 않습니다. `--targets`에는 `codex`, `claude`, `cursor`, `gemini`, `antigravity`, `agents`(공유 디렉터리 `~/.agents/skills/`)를 쓸 수 있습니다. Skill 폴더를 읽는 다른 AI 도구는 함께 제공된 Skill을 그 도구의 Skill 디렉터리에 복사하면 됩니다. `npm root -g`로 전역 npm 디렉터리를 확인할 수 있고, 함께 제공된 Skill은 그 아래 `papersearch/skills/paper-search/`에 있습니다. 복사할 때는 `references/`를 포함한 폴더 전체를 복사하고, 업데이트할 때는 새 버전에서 다시 복사하세요. 설치한 뒤 AI 세션을 새로 열면 바로 쓸 수 있습니다.

- `--targets all`은 모든 기본 위치에 동기화합니다. 업데이트는 패키지가 관리하는 파일을 덮어쓰고, 이전 버전이 설치했지만 새 버전에서 더 이상 쓰지 않는 파일은 `skill-backups` 백업 폴더로 옮기며, 사용자가 Skill 디렉터리에 직접 추가한 파일은 그대로 둡니다.
- PaperSearch를 업그레이드한 뒤 처음 실행하면 설치된 Skill이 자동으로 업데이트되고, 교체된 이전 파일은 `~/.local/share/paper-search-cli/skill-backups/`에 백업됩니다. 자동 업데이트를 끄려면: `paper-search config set PAPER_SEARCH_SKILL_AUTO_UPDATE false`. 설치된 Skill이 명령줄 프로그램보다 새 버전이면(예: GitHub에서 새 Skill을 먼저 설치한 경우) 이전 버전으로 되돌리지 않으며, 명령줄이 하루에 한 번 `npm install -g papersearch@latest`를 실행하라고 알려 줍니다.
- 학교 구독 다운로드를 설치했다면 업그레이드 후 처음 쓸 때 확장도 먼저 자동으로 업데이트되고(터미널에 한 줄 안내가 나옵니다) 이어서 다운로드합니다. 자동 업데이트를 끄려면: `paper-search config set PAPER_SEARCH_SCHOOL_AUTO_UPDATE false`. 이후에는 `paper-search school update`를 직접 실행하세요.
- `paper-search doctor`는 기본 설치 대상의 Skill 위치와 버전 상태를 보여 줍니다.

## 전체 명령

| 명령 | 용도 |
|---|---|
| `paper-search search` | 논문 메타데이터 검색 |
| `paper-search journal-metrics` | 저널 지표(EasyScholar) |
| `paper-search download` | 확인된 논문의 PDF 다운로드 |
| `paper-search run <도구>` | 특정 도구를 정확히 호출. 매개변수는 `--arg`나 `--json-args` |
| `paper-search failures` | 다운로드 실패 원인 요약 |
| `paper-search update check` | 새 버전이 있는지 확인 |
| `paper-search update install` | 새 버전으로 업데이트(설정 창의 ‘PaperSearch 정보’ 페이지에서 업데이트 버튼을 눌러 모든 구성 요소를 한 번에 업데이트할 수도 있음) |
| `paper-search school` | 학교 구독 다운로드 설치, 상태, 업데이트, 제거 |
| `paper-search setup` / `config` | 키, Skill, 확장 설정 |
| `paper-search settings` | 설정 창 열기: 다운로드 폴더, 대기 및 알림, API key(학교 구독 다운로드 설치와 그래픽 화면 필요) |
| `paper-search uninstall` | 제거: 삭제할 내용(학교 구독 다운로드와 로그인 상태, 실행 기록, 설정과 API key, 각 AI 도구의 Skill)을 먼저 보여 주고, 확인하면 한 번에 삭제. 받은 논문은 건드리지 않음. `--dry-run`은 목록만 보여 주고 삭제하지 않음 |
| `paper-search doctor` | 상태 점검: 설정, 사용 가능한 기능, Skill과 확장 상태 |
| `paper-search skills` | Skill 상태, 차이, 업데이트 |
| `paper-search smoke` | 오프라인 또는 실제 자체 점검 |
| `paper-search tools` | 모든 도구 이름과 매개변수 표시 |

명령은 기본으로 JSON을 출력하고, `--pretty`는 보기 좋게 정리하며, `--format text`는 사람이 읽는 보고서를 출력합니다. 전체 명령은 `paper-search tools --pretty`나 [명령 규약](../skills/paper-search/references/cli-contract.md)을 참고하세요.

## 기타 설정

`paper-search config set <설정 항목> <값>`으로 바꾸거나 `paper-search setup <설정 항목>`을 실행하세요.

| 설정 항목 | 역할 | 기본값 |
|---|---|---|
| `DEFAULT_DOWNLOAD_PATH` | 받은 논문을 기본으로 저장하는 폴더 | 명령을 실행한 현재 디렉터리의 `./downloads`. 진행 캡슐의 설정에서도 바꿀 수 있음 |
| `UNPAYWALL_EMAIL`, `CROSSREF_MAILTO` | Unpaywall에서 DOI로 오픈 액세스 PDF를 찾을 때, Crossref 우선 채널을 쓸 때 필요한 연락처 이메일 | `paper-search setup`에서 비워 두면 자동 생성. 설정 창에서도 입력 가능 |
| `GOOGLE_SCHOLAR_PROXY_URL` | Google Scholar용 출구 프록시. 직접 연결이 계속 막힐 때 사용 권한이 있는 프록시를 씀 | 설정 안 함 |
| `PAPER_SEARCH_SKILL_AUTO_UPDATE` | `false`로 설정하면 업그레이드 후 설치된 Skill을 자동으로 업데이트하지 않음 | 켬 |
| `PAPER_SEARCH_SCHOOL_AUTO_UPDATE` | `false`로 설정하면 업그레이드 후 학교 구독 다운로드 확장을 자동으로 업데이트하지 않고, `paper-search school update`를 직접 실행 | 켬 |
| `PAPER_SEARCH_UPDATE_NOTIFY` | `false`로 설정하면 새 버전 알림을 표시하지 않음 | 켬 |
| `PAPER_SEARCH_SCHOOL_DECLINED` | `true`로 설정하면 AI가 학교 구독 다운로드 설치를 먼저 권하지 않음(설치하지 않겠다고 하면 AI가 직접 설정). 설치하고 싶으면 그냥 말하면 됨 | 설정 안 함 |
| `PAPER_SEARCH_SCHOOL_ENABLED` | 학교 구독 다운로드 스위치 | `paper-search school install`이 자동 설정 |

## 문제 해결

| 문제 | 해결 방법 |
|---|---|
| `paper-search` 명령을 찾을 수 없음 | `npm install -g papersearch`로 다시 설치 |
| 설치할 때 `EEXIST` 오류가 나거나, 이전 패키지 `paper-search-cli`에서 옮겨 온 경우 | 먼저 `npm uninstall -g paper-search-cli`를 실행한 뒤 `papersearch`를 설치. 설정, Skill, 학교 로그인, 다운로드 기록은 모두 유지됨 |
| 어떤 기능이 작동하지 않음 | `paper-search doctor --format text`로 무엇이 빠졌는지 확인한 뒤 `paper-search setup`으로 설정 |
| 학교 구독 논문을 받지 못함 | `paper-search school status --format text`로 학교 구독 다운로드가 설치됐는지 확인. `paper-search failures --format text`로 논문별 원인 확인 |
| 소스 요청 제한 | `--max-results`를 줄이거나, 해당 키를 설정하거나, 소스를 바꿈 |
| Google Scholar에 확인 페이지가 나옴 | 잠시 후 다시 시도하거나 `--sources no-key`로 바꿈 |
| AI가 읽는 Skill이 이전 버전임 | `paper-search skills status --pretty` 후 `paper-search skills update`. AI 세션을 새로 열기 |
| 먼저 학교에 로그인하거나, 로그인되는지 시험해 보기 | `paper-search school login --doi <학교가 구독하는 논문의 DOI>`: 다운로드 브라우저가 열리면 학교 로그인 페이지에서 로그인 |
| 학교 구독 다운로드 업데이트 또는 제거 | `paper-search school update`; `paper-search school uninstall` |
| PaperSearch 제거 | `paper-search uninstall`로 확인한 뒤 `npm uninstall -g papersearch` 실행 |
| Windows PowerShell이 `npm`을 막음 | `npm.cmd`를 쓰거나 명령 프롬프트에서 실행 |
| 다운로드 실패를 알리고 싶음 | 이슈의 ‘다운로드 실패’ 템플릿에 버전, 운영체제, 사이트, DOI를 적어 주세요. `paper-search failures --export ./failure-report.zip`으로 실패 기록을 내보낼 수 있으며, 첨부하기 전에 안에 든 `summary.md`와 스크린샷에 개인 정보가 없는지 확인하세요 |
| 업그레이드 방법 | `npm install -g papersearch@latest`. 업그레이드 후 처음 실행하면 설치된 Skill이 자동으로 업데이트됨 |
