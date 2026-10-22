import os
from pathlib import Path
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

BASE_DIR = Path(__file__).resolve().parent.parent

# Google Drive Settings
GOOGLE_SERVICE_ACCOUNT_FILE = os.getenv("GOOGLE_SERVICE_ACCOUNT_FILE", str(BASE_DIR / "credentials.json"))
GOOGLE_DRIVE_FOLDER_ID = os.getenv("GOOGLE_DRIVE_FOLDER_ID", "")

# Classification Settings
CATEGORIES_FILE = os.getenv("DOCTREE_CATEGORIES_FILE", str(BASE_DIR / "config" / "categories.yaml"))

# Ledger Settings (스냅샷·변경 이력 등 대장 산출물 위치, gitignore 대상)
LEDGER_DIR = os.getenv("DOCTREE_LEDGER_DIR", str(BASE_DIR / "ledger"))
