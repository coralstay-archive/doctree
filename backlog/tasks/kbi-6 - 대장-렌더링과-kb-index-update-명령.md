---
id: KBI-6
title: 대장 렌더링과 doctree update 명령
status: Done
assignee: []
created_date: '2026-10-21 09:37'
updated_date: '2026-10-21 14:06'
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
- [x] #1 doctree update가 조회 · 분류 · 점검 · 스냅샷/이력을 거쳐 ledger/도서목록.md를 생성한다
- [x] #2 대장에 기준 시각, 스토리지 현황, 폴더 구성, 분야별 권수·용량, 분류 트리, 분야별 상세 표(제목·용량·경로·비고), 경고, 최근 변경 요약이 들어간다
- [x] #3 상세 표의 제목은 드라이브 web_view_link로 연결된다
- [x] #4 README를 새 용도로 다시 쓰고 루트의 도서목록-분류.md를 삭제한다
- [x] #5 실제 드라이브로 실행해 현재 도서 전체가 담긴 대장이 생성됨을 확인한다
<!-- AC:END -->

## Final Summary

<!-- SECTION:FINAL_SUMMARY:BEGIN -->
doctree update 명령 추가(src/cli.py): 조회 → 분류 → 점검 → record_run(스냅샷·변경이력) → ledger/도서목록.md(src/render.py 순수 함수 render_ledger, tmp 파일 후 교체). 인증 실패·목록 API 오류(DriveListError 신설)·0건·CategoryConfigError 시 오류 종료하고 기존 대장·스냅샷·이력을 건드리지 않음. 대장: 기준 시각(KST), 스토리지 현황, 요약, 폴더 구성, 분야별 권수·용량, 분류 트리, 분야별 상세 표(제목은 web_view_link 링크, 비고에 분류 메모·파일별 경고), 경고 절, 최근 변경 요약. 파일 MB(10^6)·합계 GB(10^9) 소수 1자리, 표 셀 '|'·백틱·개행 이스케이프. README 전면 재작성, 루트 수동 분류본(도서목록-분류.md, 미추적 파일) 삭제. 검증: pytest 165 passed, 실제 Drive로 doctree update 3회 실행(최초 등록 232권 → 변경 없음 → 변경 없음), 링크 행 232개, 미분류 0, 경고 21(확장자 누락), git status 깨끗(ledger/는 ignored). 남은 것: ui.py 미사용 코드·HttpError import 정리, 스토리지 현황은 1024³ 기준 GB라 파일 합계(10^9)와 기준 다름, 작은 폴더 용량이 0.0 GB로 표시됨.
<!-- SECTION:FINAL_SUMMARY:END -->
