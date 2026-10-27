"""Yordamchi akkauntga boshqa odamlar (mijozlar) yozganda: o'qiydi, javob beradi, egasiga xabar beradi.

S'yomka eslatmasini olgan mijozga yordamchi o'zi javob beradi, lekin faqat s'yomka vaqti va joyi
haqida. Narx, ko'chirish va boshqa savollarni egasiga yetkazadi. Notanish odamlarga javob bermaydi,
xabarini egasiga ko'rsatadi xolos.
"""
import logging
import tempfile
from collections import defaultdict, deque
from pathlib import Path

from . import ai, config, db, notify, voice
from .caller import caller

log = logging.getLogger(__name__)

# Har bir mijoz bilan oxirgi gaplar (server qayta ishga tushsa tozalanadi)
_history: dict[int, deque] = defaultdict(lambda: deque(maxlen=10))

CLIENT_PROMPT = """Sen — {owner}ning yordamchisisan. {owner} videograf: Instagram reels va video \
suratga oladi. Hozir sen uning mijozi bilan Telegramda yozishyapsan. Mijoz: {client}.

Mijozning rejadagi s'yomkalari:
{events}

Qoidalar:
- O'zbek tilida (lotin), hurmat bilan, "siz" deb, qisqa (1-3 gap) yoz. Markdown ishlatma.
- Faqat yuqoridagi s'yomka vaqti, manzili va unga tayyorgarlik haqida javob ber.
- Narx, to'lov, s'yomkani ko'chirish yoki bekor qilish, yangi buyurtma va boshqa har qanday savolga: \
"{owner_short}ga yetkazaman, o'zi sizga javob beradi" de. O'zingdan va'da berma, narx aytma.
- Bilmagan narsangni o'ylab topma. Shaxsiy ma'lumot berma.
- Mijoz rahmat yoki xayr desa, qisqa javob qaytar.
"""


def _events_text(events: list[dict]) -> str:
    if not events:
        return "Hozircha rejada s'yomka yo'q."
    lines = []
    for e in events:
        line = f"- {db.parse_dt(e['start_at']):%d.%m.%Y soat %H:%M}: {e['title']}"
        if e["location"]:
            line += f", manzil: {e['location']}"
        lines.append(line)
    return "\n".join(lines)


async def _read_text(event) -> str:
    if event.voice or event.audio:
        path = Path(tempfile.mkdtemp()) / "mijoz.ogg"
        await event.download_media(file=str(path))
        try:
            return await voice.speech_to_text(path) or ""
        except Exception:  # noqa: BLE001
            log.exception("Mijoz ovozini tushunib bo'lmadi")
            return ""
    return (event.raw_text or "").strip()


def _who(sender, contact: dict | None) -> str:
    name = (contact or {}).get("name") or " ".join(
        p for p in (getattr(sender, "first_name", ""), getattr(sender, "last_name", "")) if p)
    username = getattr(sender, "username", None)
    if username:
        return f"{name} (@{username})" if name else f"@{username}"
    return name or "Noma'lum odam"


def _key(sender, contact: dict | None) -> str:
    """Egasi «...ga yoz» deyishi uchun aniq nom: @username, bo'lmasa ism."""
    username = getattr(sender, "username", None)
    return "@" + username if username else _who(sender, contact)


async def handle(event) -> None:
    sender = await event.get_sender()
    if getattr(sender, "bot", False):
        return
    try:
        await event.mark_read()
    except Exception:  # noqa: BLE001
        pass

    contact = db.get_contact(event.sender_id)
    who = _who(sender, contact)
    text = await _read_text(event)
    shown = text or ("[ovozli xabar]" if (event.voice or event.audio) else "[rasm yoki fayl]")
    if (event.voice or event.audio) and text:
        shown = "🎙 " + text

    is_client = bool(contact and contact.get("event_id"))
    if not is_client or not text:
        # Notanish odam yoki o'qib bo'lmaydigan xabar: faqat egasiga ko'rsatamiz
        if not contact:
            db.save_contact(event.sender_id, _who(sender, None).split(" (@")[0],
                            "@" + sender.username if getattr(sender, "username", None) else "")
        await notify.text(f"📩 {who} yozdi:\n{shown}",
                          hint=f"Javob berish uchun: «{_key(sender, contact)}ga yoz: ...»")
        return

    history = _history[event.sender_id]
    history.append({"role": "user", "content": text})
    system = CLIENT_PROMPT.format(
        owner=config.OWNER_FULL_NAME,
        owner_short=config.OWNER_FULL_NAME.split()[0] + " aka",
        client=contact["name"] or who,
        events=_events_text(db.client_events(contact)),
    )
    async with caller._client.action(event.sender_id, "typing"):
        reply = await ai.chat(system, list(history))
    if not reply:
        history.pop()
        await notify.text(f"📩 Mijoz {who} yozdi (javob bera olmadim):\n{shown}",
                          hint=f"Javob berish uchun: «{_key(sender, contact)}ga yoz: ...»")
        return
    history.append({"role": "assistant", "content": reply})
    await caller.send_to_id(event.sender_id, reply)
    await notify.text(f"📩 Mijoz {who}:\n{shown}\n\n🤖 Javobim:\n{reply}",
                      hint=f"O'zingiz qo'shimcha yozmoqchi bo'lsangiz: «{_key(sender, contact)}ga yoz: ...»")


def setup() -> None:
    caller.on_other_message(handle)
