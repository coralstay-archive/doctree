# doctree

구글 드라이브의 도서 PDF 메타데이터만 읽어 도서 목록 대장을 만드는 작은 CLI입니다.

> 🚧 재작성 중: 기존 PDF→Markdown 5단계 파이프라인(변환·검증·LLM 요약)은 폐기했습니다
> (backlog decision-1). 대장 생성(`update`) 등 나머지 명령은 이후 태스크에서 추가되며,
> README 전면 개편은 KBI-6에서 진행합니다.

## 🛠️ 시작하기

### 1. 가상환경 및 패키지 설치
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
```

### 2. 인증 파일과 환경 변수
- 저장소 루트의 `credentials.json`(OAuth 클라이언트 키)과, 최초 로그인 후 생성되는 `token.json`을 사용합니다.
- `.env` (선택):
  - `GOOGLE_SERVICE_ACCOUNT_FILE`: 인증 키 파일 경로 (기본: 저장소 루트 `credentials.json`)
  - `GOOGLE_DRIVE_FOLDER_ID`: 스캔할 구글 드라이브 폴더 ID

### 3. CLI 명령어
```bash
doctree auth      # Google OAuth 2.0 로그인(token.json 생성·갱신) 후 계정 정보 출력
doctree status    # 구글 드라이브 계정 및 스토리지 용량 출력
```

## 🧪 테스트
```bash
.venv/bin/python -m pytest -q
```
