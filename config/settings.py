import os
from pathlib import Path
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

BASE_DIR = Path(__file__).resolve().parent.parent

# Data Directories
DATA_DIR = BASE_DIR / "data"
INPUT_PDF_DIR = DATA_DIR / "01_input_pdf"
TEMP_MD_DIR = DATA_DIR / "02_temp_md"
FAILED_MD_DIR = DATA_DIR / "03_failed_md"
OUTPUT_MD_DIR = DATA_DIR / "04_output_md"

for directory in [INPUT_PDF_DIR, TEMP_MD_DIR, FAILED_MD_DIR, OUTPUT_MD_DIR]:
    directory.mkdir(parents=True, exist_ok=True)

# Google Drive Settings
GOOGLE_SERVICE_ACCOUNT_FILE = os.getenv("GOOGLE_SERVICE_ACCOUNT_FILE", str(BASE_DIR / "credentials.json"))
GOOGLE_DRIVE_FOLDER_ID = os.getenv("GOOGLE_DRIVE_FOLDER_ID", "")

# LLM Settings (OpenAI, Ollama, vLLM 등 로컬/클라우드 호환)
OPENAI_API_KEY = os.getenv("LLM_API_KEY") or os.getenv("OPENAI_API_KEY", "")
OPENAI_MODEL = os.getenv("LLM_MODEL") or os.getenv("OPENAI_MODEL", "gpt-4o-mini")
OPENAI_BASE_URL = os.getenv("LLM_BASE_URL") or os.getenv("OPENAI_BASE_URL", None)

# Pipeline Validation Threshold
SIMILARITY_THRESHOLD = float(os.getenv("SIMILARITY_THRESHOLD", "0.85"))
