---
id: KBI-5
title: 중복·파일명 점검
status: Done
assignee: []
created_date: '2026-10-21 09:37'
updated_date: '2026-10-21 13:58'
labels:
  - checks
dependencies:
  - KBI-2
  - KBI-3
references:
  - decision-1
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
드라이브 정리에 도움이 되는 경고를 만든다. 점검은 읽기 전용이다.

## 비즈니스 규칙
- B1 (AC #1) 완전 중복은 MD5만으로 판정한다(이름 무관).
- B2 (AC #4) 점검은 경고만 만들고 드라이브 파일을 수정·삭제하지 않는다.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [x] #1 MD5가 같은 파일 묶음을 '완전 중복'으로 보고한다
- [x] #2 제목 키가 같지만 MD5가 다른 파일 묶음을 '동명 다른 파일'로 보고한다
- [x] #3 파일명 점검: .pdf 확장자 누락, 'Copy of ' 접두어, 앞뒤 공백을 경고한다
- [x] #4 점검 결과를 종류 · 대상 파일 · 메시지를 가진 구조화된 경고 목록으로 반환한다
<!-- AC:END -->

## Final Summary

<!-- SECTION:FINAL_SUMMARY:BEGIN -->
src/checks.py 추가: CheckWarning(kind, files, message)과 find_exact_duplicates(비어 있지 않은 MD5 동일 묶음), find_same_title_different_content(title_key 같고 MD5 2종 이상, 빈 MD5는 별도 값으로 보수적 집계), find_filename_issues(.pdf 확장자 누락·'Copy of ' 접두어·앞뒤 공백), run_checks(종류 → 경로 순 결정적 정렬). 드라이브 API를 쓰지 않는 순수 함수이며 입력을 변경하지 않음. 검증: pytest 125 passed(테스트 선작성 후 실패 확인), 샘플 레코드로 4종 경고 메시지 확인, 실제 Drive 232건에서 확장자 누락 21건 외 경고 0건.
<!-- SECTION:FINAL_SUMMARY:END -->
