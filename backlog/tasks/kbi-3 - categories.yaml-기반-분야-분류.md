---
id: KBI-3
title: categories.yaml 기반 분야 분류
status: Done
assignee: []
created_date: '2026-10-21 09:37'
updated_date: '2026-10-21 10:08'
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
- [x] #1 config/categories.yaml이 분야 > 세부분야 > 제목 키 목록 구조이고 로더가 이를 읽는다
- [x] #2 기존 16분야 매핑이 이관돼 현재 드라이브 도서가 모두 분류된다(미분류 0)
- [x] #3 매핑되지 않은 책은 '미분류'로 분류된다
- [x] #4 제목 키 정규화: NFC, .pdf 제거, 'Copy of ' 제거, 하이픈·공백 무시, 소문자화
<!-- AC:END -->

## Final Summary

<!-- SECTION:FINAL_SUMMARY:BEGIN -->
src/classify.py 추가: title_key(NFC·.pdf/Copy of 제거·하이픈/공백 무시·소문자, '/'는 유지), load_categories(분야>세부분야>제목 YAML, 정규화 후 키 중복·구조 오류 시 CategoryConfigError), assign/classify(이름만 사용, folder_path 무시, 매핑 없으면 '미분류>미분류', YAML 순서 유지·미분류는 항상 마지막). config/categories.yaml에 기존 16분야·55세부분야·233제목과 비고 13건을 이관(설정 경로는 DOCTREE_CATEGORIES_FILE로 변경 가능). 검증: pytest 80 passed, 실제 Drive 232권 전부 분류·미분류 0. 남은 것: YAML의 stale 제목 '트러블-슈팅-자바'(드라이브에서 삭제됨) 정리 여부, wheel 배포 시 categories.yaml package-data 미설정, CLI에서 CategoryConfigError 처리는 KBI-6.
<!-- SECTION:FINAL_SUMMARY:END -->
