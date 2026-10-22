---
id: KBI-2
title: Drive 조회 모듈을 목록 전용으로 정리
status: Done
assignee: []
created_date: '2026-10-21 09:37'
updated_date: '2026-10-21 10:01'
labels:
  - drive
dependencies:
  - KBI-1
references:
  - decision-1
  - decision-2
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
대장에 필요한 메타데이터만 반환하도록 google_drive 모듈을 줄이고, 파일명에 '/'가 들어간 경우의 경로 깨짐을 고친다.

## 비즈니스 규칙
- B1 (AC #3) 경로는 '폴더 경로'와 '파일명'으로 따로 보존하며, 파일명 속 '/'를 폴더 구분자로 해석하지 않는다.
- B2 (AC #5) 확장자가 없어도 mimeType이 application/pdf면 도서로 본다.
- B3 (AC #4) 휴지통(trashed) 파일은 목록에서 제외한다.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [x] #1 목록 레코드가 id · name · folder_path · size_bytes · md5 · modified_time · web_view_link를 갖는다
- [x] #2 다운로드 · Changes API · 로컬 MD5 대조 코드를 제거한다
- [x] #3 파일명에 '/'가 포함돼도(예: A/B-테스트) folder_path와 name이 올바르게 분리된다
- [x] #4 GOOGLE_DRIVE_FOLDER_ID가 지정되면 그 폴더의 하위 트리만, 비어 있으면 드라이브 전체를 조회한다
- [x] #5 mimeType이 application/pdf이거나 이름이 .pdf로 끝나는 파일만 도서로 수집한다
<!-- AC:END -->

## Final Summary

<!-- SECTION:FINAL_SUMMARY:BEGIN -->
google_drive.py를 목록 전용으로 축소. list_pdf_files()가 id·name·folder_path·size_bytes·md5·modified_time·web_view_link 레코드를 (folder_path, name) 순으로 반환하고, 폴더 경로는 부모 폴더 체인으로만 만들어 파일명 속 '/'(A/B-테스트)를 구분자로 해석하지 않음. 다운로드·Changes API·sync token·로컬 MD5 헬퍼와 해당 테스트 2개 삭제(삭제 코드 대상 테스트). folder_id 지정 시 하위 트리만, 미지정 시 전체(부모 미상은 folder_path=''), trashed=false 유지, application/pdf 또는 .pdf만 수집. 검증: pytest 51 passed. 실제 Drive 232건(이전 구현도 같은 시점 232건, id 차이 0 → 드라이브 쪽 변화), A/B-테스트가 knowledge-base/raw-data에 정상 배치, 확장자 없는 PDF 21건 포함, md5 빈 값 0, doctree status 정상. 남은 것: ui.py 미사용 print_drive_tree, 미사용 HttpError import, .drive_sync_token 파일·gitignore 항목 정리 여부.
<!-- SECTION:FINAL_SUMMARY:END -->
