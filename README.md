# doctree

구글 드라이브에 쌓아 둔 도서 PDF의 **메타데이터만** 읽어(읽기 전용, 파일 다운로드 없음)
분야별 도서 목록 대장을 마크다운으로 만들어 주는 작은 CLI입니다.

`doctree update` 한 번으로 다음을 차례로 수행합니다.

1. **조회** — 드라이브의 PDF 목록(이름·폴더 경로·용량·MD5·수정 시각·링크)을 가져온다.
2. **분류** — `config/categories.yaml`의 분야 > 세부분야 > 제목 목록으로 각 책을 분류한다.
3. **점검** — 완전 중복(MD5 동일), 동명 다른 파일, `.pdf` 확장자 누락, `Copy of ` 접두어, 파일명 앞뒤 공백을 찾는다.
4. **스냅샷·변경 이력** — 직전 스냅샷과 비교해 추가·삭제·이름 변경·폴더 이동·내용 변경을 `변경이력.md`에 쌓는다.
5. **대장 생성** — `ledger/도서목록.md`를 새로 쓴다.

## 시작하기

### 1. 가상환경과 설치

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e .            # 테스트까지 돌리려면: pip install -e ".[dev]"
```

### 2. Google OAuth 클라이언트 키 (`credentials.json`)

1. [Google Cloud Console](https://console.cloud.google.com/)에서 프로젝트를 만들고 **Google Drive API**를 사용 설정한다.
2. *API 및 서비스 → 사용자 인증 정보 → OAuth 클라이언트 ID 만들기*에서 애플리케이션 유형을 **데스크톱 앱**으로 고른다.
3. 내려받은 JSON을 저장소 루트에 `credentials.json`으로 둔다.
4. 처음 한 번 로그인한다. 브라우저가 열리고, 승인하면 저장소 루트에 `token.json`이 생긴다.

```bash
doctree auth
```

요청 권한은 `drive.readonly`뿐입니다. doctree는 드라이브 파일을 고치거나 지우지 않습니다.

`.env`(선택)로 바꿀 수 있는 값:

| 변수 | 기본값 | 설명 |
|---|---|---|
| `GOOGLE_SERVICE_ACCOUNT_FILE` | `credentials.json` | 인증 키 파일 경로 (`token.json`은 이 파일과 같은 폴더) |
| `GOOGLE_DRIVE_FOLDER_ID` | (없음 = 드라이브 전체) | 이 폴더 아래만 스캔 |
| `DOCTREE_CATEGORIES_FILE` | `config/categories.yaml` | 분류 설정 파일 |
| `DOCTREE_LEDGER_DIR` | `ledger/` | 대장 출력 디렉터리 |

### ⚠️ OAuth "테스트" 모드의 토큰 만료

OAuth 동의 화면이 **테스트** 상태(게시 전)이면 refresh token이 **7일 뒤 만료**됩니다.
일주일쯤 지나 `doctree update`가 인증 오류로 멈추면 `token.json`을 지우고 다시 로그인하세요.

```bash
rm token.json
doctree auth
```

## 명령

```bash
doctree auth                     # OAuth 로그인(token.json 생성·갱신) 후 계정 정보 출력
doctree status                   # 계정과 스토리지 사용량 출력
doctree update                   # 조회 → 분류 → 점검 → 스냅샷/이력 → ledger/도서목록.md 생성
doctree update --ledger-dir DIR  # 다른 디렉터리에 출력 (기본: ledger/ 또는 DOCTREE_LEDGER_DIR)
```

`update`가 끝나면 총 권수, 분류/미분류 권수, 경고 수, 변경 요약, 출력 경로를 콘솔에 보여 줍니다.

다음 경우에는 **아무 파일도 쓰지 않고** 오류 코드로 끝나므로, 기존 대장·스냅샷·이력이 빈 내용으로 덮이지 않습니다.

- 인증 실패 (`credentials.json`/`token.json` 없음, 토큰 만료 등)
- 드라이브 목록 조회 API 오류
- 조회 결과가 0개 (오류가 없어도 폴더 ID·권한 문제일 가능성이 커서 실패로 본다)
- `categories.yaml` 오류

## 산출물 (`ledger/`)

```text
ledger/
├── 도서목록.md            # 대장. 실행할 때마다 새로 쓴다
├── 변경이력.md            # 실행마다 맨 위에 블록이 쌓이는 누적 이력
└── snapshots/
    └── YYYY-MM-DD.json    # 그날의 목록 스냅샷 (같은 날 재실행 시 덮어씀)
```

`ledger/도서목록.md`에는 기준 시각(시간대 포함), 스토리지 현황, 요약, 폴더 구성,
분야별 권수·용량, 분류 트리, 분야별 상세 표(제목은 드라이브 링크 · 용량 · 경로 · 비고),
경고, 최근 변경 요약이 들어갑니다. 개별 용량은 MB(10^6), 합계는 GB(10^9) 소수 1자리입니다.

`ledger/`는 개인 도서 목록이라 **git에 커밋하지 않습니다** (`.gitignore` 대상).

## 분류 설정 (`config/categories.yaml`) 편집

```yaml
categories:
  "1. 컴퓨터 과학 기초":          # 분야
    "알고리즘·자료구조":            # 세부분야
      - "종만북-1권"               # 제목 (드라이브 파일명에서 .pdf를 뺀 것)
notes:                             # 선택: 대장 비고 칸에 붙는 설명
  "종만북-1권": "알고리즘 문제 해결 전략"
```

- 제목은 정규화해서 비교합니다: NFC, 끝의 `.pdf` 제거, 앞의 `Copy of ` 제거, 하이픈·공백 무시, 소문자화.
  그래서 `종만북-1권`, `종만북 1권`, `종만북1권.pdf`는 같은 책으로 봅니다.
- **새 책 추가**: 드라이브에 PDF를 올리고 `doctree update`를 돌리면 대장의 **미분류**에 나타납니다.
  그 제목을 알맞은 세부분야 목록에 한 줄 추가하고 다시 `doctree update`를 돌리세요.
- **미분류**: 어떤 제목에도 매칭되지 않은 파일은 빠짐없이 `미분류`로 모입니다. 미분류가 0권이면 대장에서 숨겨집니다.
- **중복 키 오류**: 정규화한 제목 키가 두 곳(같은 세부분야 안 포함)에 나오거나, 한 매핑 안에 같은 이름이
  두 번 나오면 `update`가 두 위치를 알려 주며 중단합니다. 한쪽을 지우고 다시 실행하세요.
- 분야·세부분야 순서는 파일에 적은 순서 그대로 대장에 나옵니다. 책이 하나도 없는 세부분야·분야는 대장에서 생략됩니다.

## 테스트

```bash
.venv/bin/python -m pytest -q
```
