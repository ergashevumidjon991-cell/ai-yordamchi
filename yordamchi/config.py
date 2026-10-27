import os
from pathlib import Path
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

load_dotenv()


def _get(name: str, default: str | None = None, required: bool = False) -> str:
    value = os.getenv(name, default)
    if required and not value:
        raise SystemExit(f".env faylida {name} ko'rsatilmagan")
    return value or ""


BOT_TOKEN = _get("BOT_TOKEN", required=True)
OWNER_ID = int(_get("OWNER_ID", required=True))
OWNER_NAME = _get("OWNER_NAME", "Xo'jayin")

CLAUDE_MODEL = _get("CLAUDE_MODEL", "claude-opus-5-5")
CLAUDE_EFFORT = _get("CLAUDE_EFFORT", "low")

ELEVEN_API_KEY = _get("ELEVEN_API_KEY")
ELEVEN_VOICE_ID = _get("ELEVEN_VOICE_ID", "pNInz6obpgDQGcFmaJgB")  # "Adam", erkak ovozi
ELEVEN_TTS_MODEL = _get("ELEVEN_TTS_MODEL", "eleven_v4")
ELEVEN_STT_MODEL = _get("ELEVEN_STT_MODEL", "scribe_v2")

STT_API_KEY = _get("STT_API_KEY")
STT_BASE_URL = _get("STT_BASE_URL", "https://api.groq.com/openai/v1")
STT_MODEL = _get("STT_MODEL", "whisper-large-v3")

TTS_VOICE = _get("TTS_VOICE", "uz-UZ-SardorNeural")

USERBOT_API_ID = _get("USERBOT_API_ID")
USERBOT_API_HASH = _get("USERBOT_API_HASH")
# "userbot" — suhbat, eslatma va budilniklar ikkinchi akkaunt orqali; "bot" — oddiy bot orqali
CHAT_VIA = _get("CHAT_VIA", "userbot").lower()
# Qo'ng'iroq ovozini tekshirish uchun batafsil yozuvlar (har qo'ng'iroqdan keyin fayl yuboriladi)
CALL_DEBUG = _get("CALL_DEBUG", "1") == "1"

TZ = ZoneInfo(_get("TIMEZONE", "Asia/Tashkent"))

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / _get("DATA_DIR", "data")
DATA_DIR.mkdir(parents=True, exist_ok=True)
DB_PATH = DATA_DIR / "yordamchi.db"
USERBOT_SESSION = str(DATA_DIR / "userbot")
KNOWLEDGE_DIR = ROOT / "knowledge"

# Mijozga eslatma: kim nomidan yoziladi; 1 — o'zi yuboradi, 0 — avval egasidan «yubor» deb so'raydi
OWNER_FULL_NAME = _get("OWNER_FULL_NAME", "Umidjon Ergashev")
CLIENT_AUTO_SEND = _get("CLIENT_AUTO_SEND", "1") == "1"

# Eslatma sozlamalari (daqiqalarda)
SHOOT_REMINDERS = [24 * 60, 60, 30]   # s'yomkadan oldin: 1 kun, 1 soat, 30 daqiqa
SHOOT_NAG_EVERY = 5                    # "Yo'lga chiqdim" bosilmaguncha har 5 daqiqada
SHOOT_NAG_UNTIL_AFTER = 30             # s'yomka boshlanganidan keyin 30 daqiqagacha eslatadi
CLIENT_REMINDERS = [24 * 60, 120]       # mijozga: 1 kun va 2 soat oldin
TASK_REMINDERS = [60, 0]               # montaj/post: 1 soat oldin va vaqtida
ALARM_REPEAT_EVERY = 3                 # "Turdim" bosilmaguncha har 3 daqiqada
ALARM_MAX_TRIES = 10
HISTORY_TURNS = 20                     # AI eslab qoladigan oxirgi xabarlar soni
