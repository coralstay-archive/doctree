---
id: DRAFT-1
title: 파이프라인 컴포넌트 삭제 및 knowledge-base-index로 이름 변경
status: Draft
assignee: []
created_date: '2026-10-21 09:36'
updated_date: '2026-10-21 09:37'
labels:
  - cleanup
dependencies: []
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
PDF→Markdown 변환 파이프라인을 폐기하고 도서 목록 대장 CLI로 전환하기 위해, 쓰지 않는 컴포넌트와 의존성을 걷어내고 패키지/CLI 이름을 바꾼다.

## 비즈니스 규칙
- B1 (AC #3) 인증은 기존 credentials.json / token.json 위치·방식을 그대로 써서 재로그인이 필요 없다.
- B2 (AC #4) 대장 산출물(ledger/)은 저장소에 커밋되지 않는다.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [ ] #1 src/converter.py · validator.py · summarizer.py · auth_login.py · main.py와 관련 테스트를 삭제하고, settings의 data/ 단계 폴더 설정을 제거한다
- [ ] #2 pdfplumber · langdetect · openai · httpx · aiofiles · pytest-asyncio 의존성과 .env.example/settings의 OpenAI·유사도 항목을 제거한다
- [ ] #3 패키지명은 knowledge-base-index, CLI는 kb-index이며 auth · status 명령이 동작하고 기존 gdrive-md/book2md/pdf2md 진입점은 없다
- [ ] #4 .gitignore에 ledger/가 추가돼 있다
- [ ] #5 남은 테스트가 모두 통과한다
<!-- AC:END -->
