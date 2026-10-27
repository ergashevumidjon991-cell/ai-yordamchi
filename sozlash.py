"""Kalitlarni birma-bir so'rab, .env faylini yaratadi.

Ishga tushiring:  python3 sozlash.py
"""
from pathlib import Path

ENV = Path(__file__).resolve().parent / ".env"

QUESTIONS = [
    ("BOT_TOKEN", "Telegram bot tokeni (@BotFather bergan)", True),
    ("OWNER_ID", "Sizning Telegram ID raqamingiz (@userinfobot bergan)", True),
    ("OWNER_NAME", "Bot sizga qanday murojaat qilsin (ismingiz)", True),
    ("ANTHROPIC_API_KEY", "Claude API kaliti (sk-ant- bilan boshlanadi)", True),
    ("ELEVEN_API_KEY", "ElevenLabs API kaliti", False),
    ("STT_API_KEY", "Groq kaliti (zaxira, bo'lmasa Enter bosing)", False),
    ("USERBOT_API_ID", "Qo'ng'iroq akkaunti api_id (hozircha bo'lmasa Enter bosing)", False),
    ("USERBOT_API_HASH", "Qo'ng'iroq akkaunti api_hash (hozircha bo'lmasa Enter bosing)", False),
]

DEFAULTS = {
    "CLAUDE_MODEL": "claude-opus-5-5",
    "CLAUDE_EFFORT": "low",
    "ELEVEN_VOICE_ID": "pNInz6obpgDQGcFmaJgB",
    "ELEVEN_TTS_MODEL": "eleven_v4",
    "STT_BASE_URL": "https://api.groq.com/openai/v1",
    "STT_MODEL": "whisper-large-v3",
    "TTS_VOICE": "uz-UZ-SardorNeural",
    "TIMEZONE": "Asia/Tashkent",
    "DATA_DIR": "data",
}


def clean(value: str) -> str:
    """Brauzer konsoli qo'yilgan matnga qo'shib yuboradigan belgilarni olib tashlaydi."""
    for junk in ("\x1b[200~", "\x1b[201~", "^[[200~", "^[[201~", "[200~", "[201~"):
        value = value.replace(junk, "")
    return value.strip().strip("~").strip().strip("'\"")


def read_env() -> dict:
    values = {}
    if ENV.exists():
        for line in ENV.read_text(encoding="utf-8").splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                key, value = line.split("=", 1)
                values[key.strip()] = value.strip()
    return values


def main() -> None:
    values = {**DEFAULTS, **read_env()}
    print("Kalitlarni nusxalab, so'ralgan joyga qo'ying va Enter bosing.")
    print("Qavs ichida eski qiymat bo'lsa, uni o'zgartirmaslik uchun shunchaki Enter bosing.\n")
    for key, question, required in QUESTIONS:
        old = values.get(key, "")
        hint = f" [{old[:6]}...]" if old else ""
        while True:
            answer = clean(input(f"{question}{hint}: "))
            if answer:
                values[key] = answer
            if values.get(key) or not required:
                break
            print("  Bu kalit majburiy, iltimos kiriting.")
        if key == "OWNER_ID" and not values[key].isdigit():
            print("  Diqqat: ID faqat raqamlardan iborat bo'lishi kerak. Keyin qayta tekshiring.")
    ENV.write_text("".join(f"{k}={v}\n" for k, v in values.items()), encoding="utf-8")
    ENV.chmod(0o600)
    print(f"\nTayyor! Sozlamalar saqlandi: {ENV}")


if __name__ == "__main__":
    main()
