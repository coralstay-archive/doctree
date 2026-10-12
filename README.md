# GDrive Book Markdown Pipeline (`gdrive-book-markdown-pipeline`)

400 DPI 도서 PDF를 구글 드라이브로부터 자동 수집하여 분석한 뒤, 인덱스(TOC)/장별 요약 및 YAML 프론트매터가 포함된 고품질 마크다운으로 자동 변환하는 5단계 파이프라인 프로젝트입니다.

## 📂 프로젝트 구조

```text
gdrive-book-markdown-pipeline/
├── config/
│   ├── __init__.py
│   └── settings.py             # 디렉터리 경로, 환경 변수 및 임계치 설정
├── data/
│   ├── 01_input_pdf/           # 구글 드라이브 동기화 및 입력 PDF 저장소
│   ├── 02_temp_md/             # 1차 변환된 임시 마크다운
│   ├── 03_failed_md/           # 일치율 검증 실패 격리 저장소
│   └── 04_output_md/           # 최종 완성 마크다운 (YAML+요약+인덱스+본문)
├── src/
│   ├── __init__.py
│   ├── cli.py                  # CLI 진입점
│   ├── ui.py                   # Rich 터미널 대시보드 및 디렉토리 트리 뷰
│   ├── google_drive.py         # 1단계: 구글 드라이브 청크 다운로더 & Changes API
│   ├── converter.py            # 2단계: 언어 분석 및 Marker/MinerU 변환 분기
│   ├── validator.py            # 3단계: 원본/MD 텍스트 유사도 검증 Gate
│   └── summarizer.py           # 4~5단계: 목차 생성, LLM 챕터별 비동기 요약 및 YAML 결합
├── tests/                      # 단위 및 통합 테스트 슈트
├── .env.example                # 환경 변수 템플릿
├── pyproject.toml              # 프로젝트 패키지 설정 및 CLI 명령어 등록
├── main.py                     # 파이프라인 메인 실행 파일
└── requirements.txt            # 필수 라이브러리 목록
```

## 🛠️ 시작하기

### 1. 가상환경 및 패키지 설치
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
```

### 2. 환경 변수 설정
`.env.example` 파일을 복사하여 `.env` 파일을 생성하고 필요한 인증 키를 설정합니다:
```bash
cp .env.example .env
```

`.env` 설정 항목:
- `GOOGLE_SERVICE_ACCOUNT_FILE`: 서비스 계정 또는 OAuth 클라이언트 키 파일 경로 (`credentials.json`)
- `GOOGLE_DRIVE_FOLDER_ID`: 스캔할 구글 드라이브 폴더 ID (비워둘 시 전체 드라이브 탐색)
- `OPENAI_API_KEY`: 요약에 사용할 OpenAI API 키
- `OPENAI_MODEL`: 요약 모델 (`gpt-4o-mini` 권장)
- `SIMILARITY_THRESHOLD`: 텍스트 정합성 통과 임계치 (기본: `0.85`)

### 3. CLI 명령어 및 단계별 서브커맨드

패키지 설치(`pip install -e .`) 후 `gdrive-book-markdown-pipeline` 및 간편 별칭(`gdrive-md`, `book2md`, `pdf2md`)으로 각 단계를 개별 또는 전체 실행할 수 있습니다:

```bash
# ==========================================
# 🚀 전체 파이프라인 실행 (Run)
# ==========================================
gdrive-md run                           # 전체 5단계 자동 가동
gdrive-md run --skip-sync               # 구글 드라이브 동기화 생략 (로컬 모드)
gdrive-md run --pdf data/01_input_pdf/책.pdf # 특정 단일 도서만 지정 처리
gdrive-md run --limit 3                 # 최대 3권만 순차 처리

# ==========================================
# 📥 1단계: 구글 드라이브 동기화 (Sync / Download)
# ==========================================
gdrive-md sync                          # 신규/수정된 PDF 도서만 다운로드
gdrive-md sync --force-md5              # MD5 해시 재대조 강제 수행

# ==========================================
# ⚙️ 2단계: 맞춤형 마크다운 변환 (Convert)
# ==========================================
gdrive-md convert                       # data/01_input_pdf 전체 변환 -> data/02_temp_md
gdrive-md convert my_book.pdf           # 단일 파일 변환
gdrive-md convert my_book.pdf --engine MinerU --lang ko # 엔진 및 언어 수동 지정

# ==========================================
# 🔍 3단계: 정합성 유사도 검증 Gate (Validate)
# ==========================================
gdrive-md validate --pdf input.pdf --md temp.md
gdrive-md validate --pdf input.pdf --md temp.md --threshold 0.85

# ==========================================
# 🧠 4단계: 목차 파싱 및 LLM 요약 (Summarize)
# ==========================================
gdrive-md summarize temp.md             # 목차 파싱 + 장별 비동기 요약
gdrive-md summarize temp.md --skip-llm  # 목차(TOC)만 생성

# ==========================================
# 📑 5단계: YAML 결합 및 최종본 생성 (Assemble / Build)
# ==========================================
gdrive-md assemble temp.md              # 프론트매터+요약+TOC+본문 결합 -> data/04_output_md
gdrive-md assemble temp.md --title "도서 제목"

# ==========================================
# 📊 시스템 상태 및 관리 도구
# ==========================================
gdrive-md status                        # 계정 정보, 스토리지 게이지 및 로컬 데이터 현황
gdrive-md watch --interval 30           # 구글 드라이브 변경 감지 실시간 모니터링 데몬
gdrive-md auth                          # Google OAuth 2.0 대화형 로그인
gdrive-md clean --target temp -y        # 임시 데이터 폴더 정리 (temp / failed / output / all)
```
