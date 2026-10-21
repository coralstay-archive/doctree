---
id: KBI-6
title: 대장 렌더링과 doctree update 명령
status: To Do
assignee: []
created_date: '2026-10-21 09:37'
updated_date: '2026-10-21 09:39'
labels:
  - ledger
dependencies:
  - KBI-3
  - KBI-4
  - KBI-5
references:
  - decision-1
  - decision-2
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
조회 → 분류 → 점검 → 스냅샷/이력 → 대장 md 생성을 한 명령으로 묶고 README를 새 용도로 다시 쓴다.

## 비즈니스 규칙
- B1 (AC #2) 개별 용량은 MB(10^6) 소수 1자리, 합계는 GB(10^9) 소수 1자리로 표기한다.
- B2 (AC #1) 인증·조회 실패 시 기존 대장·스냅샷을 덮어쓰지 않고 오류로 종료한다(빈 대장 방지).
- B3 (AC #2) 표 셀 안의 '|'는 이스케이프한다.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [ ] #1 doctree update가 조회 · 분류 · 점검 · 스냅샷/이력을 거쳐 ledger/도서목록.md를 생성한다
- [ ] #2 대장에 기준 시각, 스토리지 현황, 폴더 구성, 분야별 권수·용량, 분류 트리, 분야별 상세 표(제목·용량·경로·비고), 경고, 최근 변경 요약이 들어간다
- [ ] #3 상세 표의 제목은 드라이브 web_view_link로 연결된다
- [ ] #4 README를 새 용도로 다시 쓰고 루트의 도서목록-분류.md를 삭제한다
- [ ] #5 실제 드라이브로 실행해 현재 도서 전체가 담긴 대장이 생성됨을 확인한다
<!-- AC:END -->
