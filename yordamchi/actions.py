"""Tugma yoki matnli javob ("chiqdim", "turdim"...) bilan bajariladigan amallar."""
from datetime import timedelta
from pathlib import Path

from . import config, db

# Hozir jiringlayotgan budilniklar: alarm_id -> urinishlar soni
ringing: dict[int, int] = {}

AWAKE_WORDS = ("turdim", "uyg'ondim", "uygondim", "uyg‘ondim", "turdik", "uyg'ondik")
DEPART_WORDS = ("chiqdim", "yo'ldaman", "yoldaman", "yo‘ldaman", "ketyapman", "yo'lga chiqdim")
SNOOZE_WORDS = ("15 daqiqa", "keyinroq", "kechroq", "kutib tur")
DONE_WORDS = ("bajarildi", "bajardim", "tayyor", "qildim", "joyladim", "tugatdim")


def depart(event_id: int) -> None:
    db.update_event(event_id, status="departed")


def done(event_id: int) -> None:
    db.update_event(event_id, status="done")


def snooze(event_id: int) -> None:
    # Keyingi eslatma 15 daqiqadan keyin keladi
    db.set_last_nag(event_id, db.now() + timedelta(minutes=15 - config.SHOOT_NAG_EVERY))


def awake(alarm_id: int | None = None) -> bool:
    """Budilnikni to'xtatadi. Biror budilnik jiringlayotgan bo'lsa True."""
    if alarm_id is not None:
        return ringing.pop(alarm_id, None) is not None
    was = bool(ringing)
    ringing.clear()
    return was


def nagging_shoot() -> dict | None:
    """Eslatmasi boshlangan, hali "chiqdim" deyilmagan eng yaqin s'yomka."""
    now = db.now()
    best = None
    for e in db.active_events():
        if e["kind"] != "syomka" or not e["sent"] or e["sent"] == "[]":
            continue
        start = db.parse_dt(e["start_at"])
        if start - now > timedelta(hours=3) or now - start > timedelta(minutes=config.SHOOT_NAG_UNTIL_AFTER):
            continue
        if best is None or start < db.parse_dt(best["start_at"]):
            best = e
    return best


def due_task() -> dict | None:
    """Eslatmasi yuborilgan, vaqti yaqin yoki o'tgan s'yomka bo'lmagan ish."""
    now = db.now()
    best = None
    for e in db.active_events():
        if e["kind"] == "syomka" or not e["sent"] or e["sent"] == "[]":
            continue
        start = db.parse_dt(e["start_at"])
        if start - now > timedelta(hours=2):
            continue
        if best is None or abs(start - now) < abs(db.parse_dt(best["start_at"]) - now):
            best = e
    return best


def _has(text: str, words: tuple[str, ...]) -> bool:
    return any(w in text for w in words)


def quick_reply(text: str) -> tuple[str, str] | None:
    """Qisqa javoblarni ("turdim", "chiqdim"...) AI'siz bajaradi. (amal, javob) yoki None."""
    t = text.lower().strip()
    if len(t) > 40:
        return None
    if _has(t, AWAKE_WORDS):
        if awake():
            return "awake", "Xayrli tong! ☀️"
        return None
    if _has(t, DEPART_WORDS):
        e = nagging_shoot()
        if e:
            depart(e["id"])
            return "depart", (f"Zo'r, yo'lingiz bexatar bo'lsin! 🎬 ({e['title']})\n"
                              "S'yomkadan keyin montaj vaqtini rejalashtirishni unutmang.")
        return None
    if _has(t, SNOOZE_WORDS):
        e = nagging_shoot()
        if e:
            snooze(e["id"])
            return "snooze", "Mayli, 15 daqiqadan keyin yana eslataman."
        return None
    if _has(t, DONE_WORDS):
        e = due_task()
        if e:
            done(e["id"])
            return "done", f"Bajarildi ✅ ({e['title']})"
        return None
    return None


def knowledge_files() -> list[str]:
    return sorted(p.name for p in config.KNOWLEDGE_DIR.glob("*")
                  if p.suffix.lower() in {".md", ".txt"} and p.name.lower() != "readme.md")


def knowledge_target(file_name: str) -> Path | None:
    """Yuborilgan fayl uchun xavfsiz yo'l. Shaxsiy fayllar git'ga tushmasligi uchun "shaxsiy-" bilan boshlanadi."""
    name = Path(file_name or "").name
    if Path(name).suffix.lower() not in {".md", ".txt"}:
        return None
    safe = "".join(c if c.isalnum() or c in "-_." else "-" for c in name)
    if not safe.startswith("shaxsiy-"):
        safe = "shaxsiy-" + safe
    return config.KNOWLEDGE_DIR / safe
