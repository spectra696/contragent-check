import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

CHECKO_API_KEY = os.environ.get("CHECKO_API_KEY", "").strip()
if not CHECKO_API_KEY:
    raise SystemExit("Не задан CHECKO_API_KEY в .env")

DATANEWTON_API_KEY = os.getenv("DATANEWTON_API_KEY", "").strip()

GIGACHAT_CREDENTIALS = os.getenv("GIGACHAT_CREDENTIALS", "").strip()
GIGACHAT_SCOPE = os.getenv("GIGACHAT_SCOPE", "GIGACHAT_API_PERS")
GIGACHAT_MODEL = os.getenv("GIGACHAT_MODEL", "GigaChat")
GIGACHAT_CA_BUNDLE = os.getenv("GIGACHAT_CA_BUNDLE", "").strip() or None

OUT_DIR = Path(os.getenv("OUT_DIR", "reports"))