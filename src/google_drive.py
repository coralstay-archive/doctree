import hashlib
import io
import json
import os
import time
import unicodedata
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

try:
    from google.oauth2 import service_account
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow
    from google.auth.transport.requests import Request
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaIoBaseDownload
    from googleapiclient.errors import HttpError
    GOOGLE_API_AVAILABLE = True
except ImportError:
    service_account = None
    Credentials = None
    InstalledAppFlow = None
    Request = None
    build = None
    MediaIoBaseDownload = None
    HttpError = None
    GOOGLE_API_AVAILABLE = False

SCOPES = ['https://www.googleapis.com/auth/drive.readonly']

FOLDER_MIME = 'application/vnd.google-apps.folder'
PDF_MIME = 'application/pdf'
LIST_FIELDS = 'nextPageToken, files(id, name, mimeType, parents, size, md5Checksum, modifiedTime, webViewLink)'


def normalize_str(text: str) -> str:
    """한글 자모 분리(NFD) 현상을 표준 완성형(NFC)으로 정규화합니다."""
    return unicodedata.normalize('NFC', text) if text else ""


def is_pdf_item(item: dict) -> bool:
    """mimeType이 application/pdf이거나 이름이 .pdf로 끝나면(대소문자 무시) 도서 PDF로 본다."""
    return item.get('mimeType') == PDF_MIME or (item.get('name') or '').lower().endswith('.pdf')


def calculate_file_md5(file_path: Path) -> str:
    """로컬 파일의 MD5 해시를 계산합니다."""
    if not file_path.exists():
        return ""
    hash_md5 = hashlib.md5()
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024 * 4), b""):
            hash_md5.update(chunk)
    return hash_md5.hexdigest()


def is_valid_pdf_file(file_path: Path) -> bool:
    """PDF 파일의 기본 무결성 검증 (0바이트 여부 및 %PDF- 매직 넘버 확인)"""
    if not file_path.exists() or file_path.stat().st_size == 0:
        return False
    try:
        with open(file_path, "rb") as f:
            header = f.read(5)
            return header.startswith(b"%PDF-")
    except Exception:
        return False


class GoogleDriveManager:
    """구글 드라이브 API 연동 (서비스 계정 및 OAuth 2.0 지원), 변경 감지 및 청크 단위 PDF 다운로더"""

    def __init__(self, service_account_file: Optional[str] = None, folder_id: Optional[str] = None):
        self.service_account_file = service_account_file or os.getenv("GOOGLE_SERVICE_ACCOUNT_FILE")
        if not self.service_account_file and Path("credentials.json").exists():
            self.service_account_file = "credentials.json"

        self.folder_id = folder_id or os.getenv("GOOGLE_DRIVE_FOLDER_ID")
        self.token_file = Path(self.service_account_file).parent / "token.json" if self.service_account_file else Path("token.json")
        self.sync_token_file = Path(self.service_account_file).parent / ".drive_sync_token" if self.service_account_file else Path(".drive_sync_token")
        self.service = None

        if GOOGLE_API_AVAILABLE:
            if self.token_file.exists() or (self.service_account_file and os.path.exists(self.service_account_file)):
                self._authenticate()

    def _authenticate(self):
        """Service Account 또는 OAuth 2.0 InstalledAppFlow를 감지하여 인증 초기화"""
        try:
            # 1. token.json이 존재하면 우선 로드
            if self.token_file.exists():
                try:
                    credentials = Credentials.from_authorized_user_file(str(self.token_file), SCOPES)
                    if credentials and credentials.valid:
                        self.service = build('drive', 'v3', credentials=credentials)
                        return
                    elif credentials and credentials.expired and credentials.refresh_token:
                        credentials.refresh(Request())
                        with open(self.token_file, 'w', encoding='utf-8') as token_f:
                            token_f.write(credentials.to_json())
                        self.service = build('drive', 'v3', credentials=credentials)
                        return
                except Exception as e:
                    print(f"[GoogleDriveManager] 기존 token.json 로드 실패: {e}")

            if not self.service_account_file or not os.path.exists(self.service_account_file):
                print("[GoogleDriveManager] 인증 키 파일(credentials.json)이 없습니다.")
                return

            with open(self.service_account_file, 'r', encoding='utf-8') as f:
                creds_data = json.load(f)

            if "type" in creds_data and creds_data["type"] == "service_account":
                # 2. 서비스 계정 JSON
                credentials = service_account.Credentials.from_service_account_file(
                    self.service_account_file,
                    scopes=SCOPES
                )
            elif "installed" in creds_data or "web" in creds_data:
                # 3. OAuth 2.0 클라이언트 JSON
                flow = InstalledAppFlow.from_client_secrets_file(self.service_account_file, SCOPES)
                print("\n[GoogleDriveManager] 🌐 브라우저를 열어 구글 로그인을 진행합니다...")
                credentials = flow.run_local_server(port=0)

                # 발급된 토큰 저장
                with open(self.token_file, 'w', encoding='utf-8') as token_f:
                    token_f.write(credentials.to_json())
                print(f"[GoogleDriveManager] 인증 토큰 저장 완료: {self.token_file}")
            else:
                print(f"[GoogleDriveManager] 알 수 없는 인증 파일 형식입니다: {self.service_account_file}")
                return

            self.service = build('drive', 'v3', credentials=credentials)
        except Exception as e:
            print(f"[GoogleDriveManager] 인증 초기화 경고: {e}")

    def get_account_and_quota(self) -> Optional[dict]:
        """현재 로그인된 구글 계정 정보 및 드라이브 스토리지 사용 현황을 조회합니다 (about.get)."""
        if not self.service:
            return None
        try:
            about = self.service.about().get(
                fields="user(displayName, emailAddress, photoLink), storageQuota(limit, usage, usageInDrive, usageInDriveTrash)"
            ).execute()
            user = about.get('user', {})
            quota = about.get('storageQuota', {})
            limit_bytes = int(quota.get('limit', 0)) if 'limit' in quota else 0
            usage_bytes = int(quota.get('usage', 0))
            drive_usage_bytes = int(quota.get('usageInDrive', 0))

            return {
                "name": user.get('displayName', 'Unknown'),
                "email": user.get('emailAddress', 'Unknown'),
                "photo_link": user.get('photoLink', ''),
                "limit_gb": round(limit_bytes / (1024**3), 2) if limit_bytes else None,
                "usage_gb": round(usage_bytes / (1024**3), 2),
                "drive_usage_gb": round(drive_usage_bytes / (1024**3), 2),
                "usage_percent": round((usage_bytes / limit_bytes) * 100, 1) if limit_bytes else 0.0
            }
        except Exception as e:
            print(f"[GoogleDriveManager] 계정 및 스토리지 정보 조회 실패: {e}")
            return None

    def get_start_page_token(self) -> Optional[str]:
        """변경 감지를 위한 시작 페이지 토큰을 가져옵니다 (changes.getStartPageToken)."""
        if not self.service:
            return None
        try:
            response = self.service.changes().getStartPageToken().execute()
            token = response.get('startPageToken')
            if token:
                with open(self.sync_token_file, 'w', encoding='utf-8') as f:
                    f.write(token)
            return token
        except Exception as e:
            print(f"[GoogleDriveManager] 변경 시작 토큰 발급 실패: {e}")
            return None

    def check_changes(self) -> Tuple[List[dict], Optional[str]]:
        """마지막 동기화 이후 드라이브에서 발생한 변경사항(신규 업로드/수정/삭제)을 감지합니다 (changes.list)."""
        if not self.service:
            return [], None

        saved_token = None
        if self.sync_token_file.exists():
            try:
                with open(self.sync_token_file, 'r', encoding='utf-8') as f:
                    saved_token = f.read().strip()
            except Exception:
                pass

        if not saved_token:
            new_token = self.get_start_page_token()
            return [], new_token

        try:
            changes = []
            page_token = saved_token
            new_start_token = None

            while page_token:
                response = self.service.changes().list(
                    pageToken=page_token,
                    spaces='drive',
                    fields='nextPageToken, newStartPageToken, changes(fileId, removed, file(id, name, mimeType, md5Checksum, modifiedTime, trashed, parents, size))'
                ).execute()

                changes.extend(response.get('changes', []))
                page_token = response.get('nextPageToken')
                if 'newStartPageToken' in response:
                    new_start_token = response['newStartPageToken']

            if new_start_token:
                with open(self.sync_token_file, 'w', encoding='utf-8') as f:
                    f.write(new_start_token)

            return changes, new_start_token
        except Exception as e:
            print(f"[GoogleDriveManager] 변경 감지 조회 실패: {e}")
            # 토큰 만료 등의 경우 초기화
            new_token = self.get_start_page_token()
            return [], new_token

    def _list_all_items(self) -> List[dict]:
        """휴지통을 제외한 드라이브 항목(폴더·파일)을 페이지네이션으로 모두 수집한다."""
        all_items: List[dict] = []
        page_token = None
        while True:
            response = self.service.files().list(
                q="trashed=false",
                spaces='drive',
                pageSize=1000,
                fields=LIST_FIELDS,
                pageToken=page_token
            ).execute()
            all_items.extend(response.get('files', []))
            page_token = response.get('nextPageToken')
            if not page_token:
                break
        return all_items

    def _resolve_folder_path(self, item: dict, folders_map: Dict[str, dict]) -> Optional[str]:
        """파일의 상위 폴더 이름만 '/'로 이어 folder_path를 만든다 (파일명은 절대 쪼개지 않는다).

        - folder_id 지정: 조상 체인이 folder_id에 닿아야 하며, 그 폴더 기준 상대 경로를 돌려준다
          (바로 아래 파일은 ""). 닿지 않으면(상위가 폴더 맵에 없는 공유 항목 포함) None → 제외.
        - folder_id 미지정: 내 드라이브 루트 기준 경로. 체인은 폴더 맵에 없는 부모(루트 또는 알 수 없는
          공유 폴더)에서 멈추므로, 루트 파일과 부모를 알 수 없는 공유 항목은 "".
        """
        parents = item.get('parents') or []
        curr = parents[0] if parents else None
        parts: List[str] = []
        visited: Set[str] = set()
        while curr and curr not in visited:
            if self.folder_id and curr == self.folder_id:
                return '/'.join(reversed(parts))
            folder = folders_map.get(curr)
            if folder is None:
                break
            visited.add(curr)
            parts.append(folder['name'])
            folder_parents = folder.get('parents') or []
            curr = folder_parents[0] if folder_parents else None
        if self.folder_id:
            return None
        return '/'.join(reversed(parts))

    def list_pdf_files(self) -> List[dict]:
        """도서 PDF 목록을 대장용 메타데이터 레코드로 반환한다.

        레코드 키: id, name, folder_path, size_bytes(int), md5(str, 없으면 ""),
        modified_time(Drive RFC3339 문자열), web_view_link. (folder_path, name) 순 정렬.
        """
        if not self.service:
            print("[GoogleDriveManager] 구글 드라이브 서비스가 활성화되지 않았습니다 (자격 증명 파일 확인 필요).")
            return []

        try:
            all_items = self._list_all_items()
        except Exception as e:
            print(f"[GoogleDriveManager] 파일 목록 조회 실패: {e}")
            return []

        folders_map: Dict[str, dict] = {
            item['id']: {'name': normalize_str(item.get('name', '')), 'parents': item.get('parents') or []}
            for item in all_items
            if item.get('mimeType') == FOLDER_MIME
        }

        records: List[dict] = []
        for item in all_items:
            if item.get('mimeType') == FOLDER_MIME or not is_pdf_item(item):
                continue
            folder_path = self._resolve_folder_path(item, folders_map)
            if folder_path is None:
                continue
            records.append({
                'id': item['id'],
                'name': normalize_str(item.get('name', '')),
                'folder_path': folder_path,
                'size_bytes': int(item.get('size') or 0),
                'md5': item.get('md5Checksum') or "",
                'modified_time': item.get('modifiedTime') or "",
                'web_view_link': item.get('webViewLink') or "",
            })

        records.sort(key=lambda r: (r['folder_path'], r['name']))
        return records

    def download_new_pdfs(self, target_dir: str or Path, force_recheck_md5: bool = False) -> List[Path]:
        """새로운 PDF 파일들을 드라이브 디렉토리 구조를 보존하여 청크 단위로 로컬에 다운로드합니다 (MD5 해시/크기 검증 지원)."""
        target_path = Path(target_dir)
        target_path.mkdir(parents=True, exist_ok=True)

        downloaded_files: List[Path] = []
        files = self.list_pdf_files()

        for file_info in files:
            file_id = file_info['id']
            file_name = file_info['name']
            relative_path = file_info.get('relative_path', file_name)
            remote_md5 = file_info.get('md5Checksum', '')
            remote_size = int(file_info['size']) if 'size' in file_info and file_info['size'] else None
            file_dest = target_path / relative_path

            # 하위 폴더가 있는 경우 디렉토리 자동 생성
            file_dest.parent.mkdir(parents=True, exist_ok=True)

            if file_dest.exists():
                is_same = True
                # 크기 및 무결성 1차 비교
                if remote_size and file_dest.stat().st_size != remote_size:
                    is_same = False
                elif not is_valid_pdf_file(file_dest):
                    print(f"[GoogleDriveManager] 기존 파일 손상 감지(재다운로드): {relative_path}")
                    is_same = False
                elif force_recheck_md5 and remote_md5:
                    local_md5 = calculate_file_md5(file_dest)
                    if local_md5 != remote_md5:
                        is_same = False

                if is_same:
                    downloaded_files.append(file_dest)
                    continue
                else:
                    print(f"[GoogleDriveManager] 변경 감지(재다운로드 필요): {relative_path}")

            print(f"[GoogleDriveManager] 다운로드 시작: {relative_path} (ID: {file_id})")
            part_dest = file_dest.with_suffix(file_dest.suffix + ".part")
            
            # 네트워크 불안정 대비 재시도 (최대 3회 지수 백오프)
            max_retries = 3
            download_success = False

            for attempt in range(1, max_retries + 1):
                try:
                    request = self.service.files().get_media(fileId=file_id)
                    with io.FileIO(str(part_dest), 'wb') as fh:
                        downloader = MediaIoBaseDownload(fh, request, chunksize=1024 * 1024 * 10) # 10MB chunk
                        done = False
                        while not done:
                            status, done = downloader.next_chunk()
                            if status:
                                print(f"  [{relative_path}] 진행률: {int(status.progress() * 100)}% (시도 {attempt}/{max_retries})")

                    # 무결성 검증 후 원자적 이름 변경 (.part -> .pdf)
                    if part_dest.exists() and is_valid_pdf_file(part_dest):
                        if part_dest.exists():
                            if file_dest.exists():
                                file_dest.unlink()
                            part_dest.rename(file_dest)
                        download_success = True
                        print(f"[GoogleDriveManager] 다운로드 및 무결성 검증 완료: {relative_path}")
                        downloaded_files.append(file_dest)
                        break
                    else:
                        print(f"[GoogleDriveManager] 경고: 다운로드된 파일이 유효한 PDF가 아닙니다 (시도 {attempt}/{max_retries})")
                        if part_dest.exists():
                            part_dest.unlink()
                except Exception as e:
                    print(f"[GoogleDriveManager] 다운로드 중 에러 발생 (시도 {attempt}/{max_retries}): {e}")
                    if part_dest.exists():
                        try:
                            part_dest.unlink()
                        except Exception:
                            pass
                    if attempt < max_retries:
                        time.sleep(2 ** attempt)

            if not download_success:
                print(f"[GoogleDriveManager] ❌ 최종 다운로드 실패: {relative_path}")

        # 시작 토큰 초기화 (최초 동기화 시점 기준)
        if not self.sync_token_file.exists():
            self.get_start_page_token()

        return downloaded_files
