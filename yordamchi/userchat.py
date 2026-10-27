"""Ikkinchi akkauntdagi suhbat: egasi yozgan matn, ovoz va fayllarga javob beradi."""
import logging
import tempfile
from pathlib import Path

from . import actions, ai, config, db, reminders, voice
from .caller import caller

log = logging.getLogger(__name__)

HELP = (
    "Salom! Men sizning shaxsiy yordamchingizman.\n\n"
    "Menga oddiy gapirib yoki yozib yuboring, masalan:\n"
    "• «Ertaga soat 10 da kafe uchun s'yomka bor»\n"
    "• «Bugungi rejalarim qanaqa?»\n"
    "• «Har kuni 6:30 da meni uyg'ot»\n\n"
    "Eslatmalarga qisqa javoblar:\n"
    "• «turdim» — budilnikni to'xtatadi\n"
    "• «chiqdim» — s'yomkaga yo'lga chiqdingiz\n"
    "• «15 daqiqa» — keyinroq eslatish\n"
    "• «bajarildi» — montaj yoki post tayyor\n\n"
    "Buyruqlar:\n"
    "/bugun /ertaga /hafta — rejalar\n"
    "/budilnik — budilniklar ro'yxati\n"
    "/bilim — bilim bazasi\n"
    "/yangi — suhbatni yangidan boshlash\n"
    "/test_qongiroq — qo'ng'iroqni sinash\n\n"
    "Bilim bazasiga fayl qo'shish: .md yoki .txt faylni shu yerga yuboring."
)

PLAN_QUESTIONS = {
    "bugun": "Bugungi rejalarimni aytib ber.",
    "ertaga": "Ertangi rejalarimni aytib ber.",
    "hafta": "Keyingi 7 kunlik rejalarimni kunma-kun qisqa aytib ber.",
}


def alarms_text() -> str:
    items = db.list_alarms()
    if not items:
        return "Budilnik yo'q. Masalan, «Har kuni 6:30 da uyg'ot» deb yozing."
    days = ["Du", "Se", "Ch", "Pa", "Ju", "Sh", "Ya"]
    lines = []
    for a in items:
        when = a["date"] or ", ".join(days[int(d)] for d in a["days"])
        lines.append(f"#{a['id']}  {a['time']}  ({when}) {a['label']}")
    return "⏰ Budilniklar:\n" + "\n".join(lines)


async def _reply(text: str, as_voice: bool) -> None:
    if as_voice:
        try:
            async with caller.typing(voice=True):
                ogg = await voice.text_to_speech(text)
            await caller.send_voice(ogg, text)
            return
        except Exception:  # noqa: BLE001 — ovoz ishlamasa matn bilan javob beramiz
            log.exception("TTS error")
    await caller.send_text(text)


async def _command(cmd: str) -> None:
    if cmd in ("start", "yordam"):
        await caller.send_text(HELP)
    elif cmd in PLAN_QUESTIONS:
        async with caller.typing():
            reply = await ai.ask(PLAN_QUESTIONS[cmd], remember=False)
        await caller.send_text(reply)
    elif cmd == "budilnik":
        await caller.send_text(alarms_text())
    elif cmd == "yangi":
        db.clear_history()
        await caller.send_text("Suhbat tarixi tozalandi. Rejalaringiz joyida qoldi.")
    elif cmd == "bilim":
        files = actions.knowledge_files()
        await caller.send_text("📚 Bilim bazasi:\n" + "\n".join(f"• {f}" for f in files) if files
                               else "Bilim bazasi bo'sh.")
    elif cmd == "test_qongiroq":
        await caller.send_text("Hozir qo'ng'iroq qilaman...")
        ogg = await voice.text_to_speech(f"Salom {config.OWNER_NAME}, bu sinov qo'ng'irog'i. Hammasi ishlayapti!")
        ok = await caller.ring(await voice.to_call_audio(ogg), seconds=15)
        await caller.send_text("Qo'ng'iroq ishladi ✅" if ok else "Qo'ng'iroqqa javob berilmadi yoki xato bo'ldi.")
    else:
        await caller.send_text("Bunday buyruq yo'q. /yordam — nimalar qila olishim.")


async def _document(event) -> None:
    target = actions.knowledge_target(event.file.name or "")
    if target is None:
        await caller.send_text("Bilim bazasiga faqat .md yoki .txt fayl qo'shiladi.")
        return
    if event.file.size and event.file.size > 200_000:
        await caller.send_text("Fayl juda katta (200 KB dan ko'p). Uni qisqaroq konspekt qilib yuboring.")
        return
    await event.download_media(file=str(target))
    await caller.send_text(f"📚 Bilim bazasiga qo'shildi: {target.name}\n"
                           "Endi maslahatlarimda shuni ham hisobga olaman.")


async def _voice(event) -> None:
    path = Path(tempfile.mkdtemp()) / "xabar.ogg"
    async with caller.typing():
        await event.download_media(file=str(path))
        try:
            text = await voice.speech_to_text(path)
        except Exception as e:  # noqa: BLE001
            log.exception("STT error")
            await caller.send_text(f"Ovozli xabarni tushuna olmadim. Iltimos, yozib yuboring.\n\n"
                                   f"Texnik sabab: {str(e)[:300]}")
            return
    if not text:
        await caller.send_text("Ovozli xabarda gap eshitilmadi.")
        return
    await caller.send_text(f"🎙 {text}")
    await _text(text, as_voice=True)


async def _text(text: str, as_voice: bool) -> None:
    quick = actions.quick_reply(text)
    if quick:
        result, reply = quick
        await _reply(reply, as_voice)
        if result == "awake":
            await reminders.morning_briefing()
        return
    async with caller.typing():
        reply = await ai.ask(text)
    await _reply(reply, as_voice)


async def handle(event) -> None:
    if event.voice or event.audio:
        await _voice(event)
    elif event.document:
        await _document(event)
    elif event.raw_text:
        text = event.raw_text.strip()
        if text.startswith("/"):
            await _command(text.split()[0][1:].split("@")[0].lower())
        else:
            await _text(text, as_voice=False)


def setup() -> None:
    caller.on_owner_message(handle)
