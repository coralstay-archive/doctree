---
id: KBI-3
title: categories.yaml 기반 분야 분류
status: To Do
assignee: []
created_date: '2026-10-21 09:37'
updated_date: '2026-10-21 09:39'
labels:
  - classify
dependencies:
  - KBI-2
references:
  - decision-1
documentation:
  - 'local:도서목록-분류.md (2026-10-21 수동 분류본'
  - 16분야 원본)
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
책 제목 키 → 분야/세부분야 매핑을 설정 파일로 관리하고, 현재 만든 16분야 체계를 이관한다.

## 비즈니스 규칙
- B1 (AC #4) 폴더 이동, .pdf 확장자 추가, 하이픈/공백·대소문자 변경만으로는 분류가 바뀌지 않는다.
- B2 (AC #3) 매핑이 없는 책도 대장에서 빠지지 않고 '미분류'에 들어간다.
- B3 (AC #1) 한 제목 키는 정확히 하나의 세부분야에만 속하며, 중복 매핑은 설정 오류로 실행을 중단한다.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [ ] #1 config/categories.yaml이 분야 > 세부분야 > 제목 키 목록 구조이고 로더가 이를 읽는다
- [ ] #2 기존 16분야 매핑이 이관돼 현재 드라이브 도서가 모두 분류된다(미분류 0)
- [ ] #3 매핑되지 않은 책은 '미분류'로 분류된다
- [ ] #4 제목 키 정규화: NFC, .pdf 제거, 'Copy of ' 제거, 하이픈·공백 무시, 소문자화
<!-- AC:END -->
