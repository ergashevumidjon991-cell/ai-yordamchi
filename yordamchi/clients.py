"""Mijozlarga s'yomkadan oldin eslatma: yordamchi akkauntidan mijozning Telegramiga yoziladi.

Odatda o'zi yuboradi va egasiga xabar beradi. CLIENT_AUTO_SEND=0 bo'lsa, avval egasiga ko'rsatadi,
u «yubor» desagina ketadi.
"""
import json
import logging

from . import config, db, notify
from .caller import caller

log = logging.getLogger(__name__)

SEND_WORDS = ("yubor", "jo'nat", "jonat", "yuboraver")
SKIP_WORDS = ("yuborma", "jo'natma", "jonatma", "kerak emas", "kerakmas")


def client_text(event: dict) -> str:
    start = db.parse_dt(event["start_at"])
    days = (start.date() - db.now().date()).days
    day = "bugun" if days == 0 else "ertaga" if days == 1 else f"{start:%d.%m}"
    hello = f"Assalomu alaykum, {event['client_name']}!" if event["client_name"] else "Assalomu alaykum!"
    lines = [hello,
             f"Eslatma: {config.OWNER_FULL_NAME} {day} soat {start:%H:%M} da s'yomkaga keladi."]
    if event["location"]:
        lines.append(f"📍 Manzil: {event['location']}")
    lines.append("Iltimos, joy va kerakli narsalarni tayyorlab qo'ying. Savol bo'lsa, shu yerga yozing.")
    return "\n".join(lines)


async def _send(event: dict) -> str | None:
    """Mijozga yuboradi. Xato bo'lsa sababini qaytaradi."""
    if caller._client is None:
        return "yordamchi akkaunt ulanmagan"
    try:
        await caller.send_to(event["client_contact"], client_text(event))
    except Exception as e:  # noqa: BLE001
        log.exception("Mijozga yuborib bo'lmadi")
        return str(e)[:200]
    return None


async def check() -> None:
    now = db.now()
    for event in db.active_events():
        if event["kind"] != "syomka" or not event["client_contact"]:
            continue
        minutes_left = int((db.parse_dt(event["start_at"]) - now).total_seconds() // 60)
        sent = json.loads(event["client_sent"] or "[]")
        due = [m for m in config.CLIENT_REMINDERS if minutes_left <= m and m not in sent]
        if not due:
            continue
        db.update_event(event["id"], client_sent=json.dumps(sorted(set(sent + due))))
        if minutes_left < 30:   # juda kech, mijozga yozishning foydasi yo'q
            continue
        who = event["client_name"] or event["client_contact"]
        if config.CLIENT_AUTO_SEND:
            error = await _send(event)
            await notify.text(f"📤 {who}ga eslatma yuborildi." if not error
                              else f"⚠️ {who}ga eslatma yuborilmadi: {error}")
            continue
        db.update_event(event["id"], client_pending="1")
        await notify.text(
            f"📤 Mijozga eslatma tayyor ({who}, {event['client_contact']}):\n\n{client_text(event)}",
            hint="Yuborish uchun «yubor», kerak bo'lmasa «yuborma» deb yozing.",
        )


async def answer(text: str) -> str | None:
    """«yubor» / «yuborma» javobini bajaradi. Kutilayotgan xabar bo'lmasa None."""
    t = text.lower().strip()
    if len(t) > 40:
        return None
    pending = db.client_pending_events()
    if not pending:
        return None
    if any(w in t for w in SKIP_WORDS):
        for e in pending:
            db.update_event(e["id"], client_pending="")
        return "Mayli, mijozga yubormadim."
    if any(w in t for w in SEND_WORDS):
        results = []
        for e in pending:
            db.update_event(e["id"], client_pending="")
            who = e["client_name"] or e["client_contact"]
            error = await _send(e)
            results.append(f"✅ {who}ga yuborildi" if not error else f"⚠️ {who}ga yuborilmadi: {error}")
        return "\n".join(results)
    return None
