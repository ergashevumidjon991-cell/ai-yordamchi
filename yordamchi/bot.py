import asyncio
import logging
import tempfile
from datetime import timedelta
from pathlib import Path

from aiogram import Bot, Dispatcher, F
from aiogram.enums import ChatAction
from aiogram.filters import Command, CommandStart
from aiogram.types import CallbackQuery, FSInputFile, Message

from . import ai, config, db, reminders, voice
from .caller import caller

log = logging.getLogger(__name__)
dp = Dispatcher()
# Bot faqat egasining xabarlariga javob beradi
dp.message.filter(F.from_user.id == config.OWNER_ID)
dp.callback_query.filter(F.from_user.id == config.OWNER_ID)

HELP = (
    "Salom! Men sizning shaxsiy yordamchingizman.\n\n"
    "Menga oddiy gapirib yoki yozib yuboring, masalan:\n"
    "• «Ertaga soat 10 da Chilonzorda kafe uchun s'yomka bor»\n"
    "• «Bugungi rejalarim qanaqa?»\n"
    "• «Har kuni 6:30 da meni uyg'ot»\n"
    "• «Reelsning birinchi 3 soniyasini qanday qilsam bo'ladi?»\n\n"
    "Buyruqlar:\n"
    "/bugun — bugungi reja\n"
    "/ertaga — ertangi reja\n"
    "/hafta — 7 kunlik reja\n"
    "/budilnik — budilniklar ro'yxati\n"
    "/yangi — suhbatni yangidan boshlash\n"
    "/test_qongiroq — uyg'otish qo'ng'irog'ini sinash\n"
    "/bilim — bilim bazasidagi fayllar ro'yxati\n\n"
    "Bilim bazasiga fayl qo'shish: .md yoki .txt faylni botga yuboring."
)


async def _answer(message: Message, text: str, as_voice: bool) -> None:
    if as_voice:
        try:
            await message.bot.send_chat_action(message.chat.id, ChatAction.RECORD_VOICE)
            ogg = await voice.text_to_speech(text)
            await message.answer_voice(FSInputFile(ogg), caption=text[:1000])
            return
        except Exception:  # noqa: BLE001 — ovoz ishlamasa matn bilan javob beramiz
            log.exception("TTS error")
    await message.answer(text)


@dp.message(CommandStart())
@dp.message(Command("yordam"))
async def start(message: Message) -> None:
    await message.answer(HELP)


@dp.message(Command("bugun", "ertaga", "hafta"))
async def plan(message: Message) -> None:
    cmd = message.text.split()[0].lstrip("/").split("@")[0]
    question = {
        "bugun": "Bugungi rejalarimni aytib ber.",
        "ertaga": "Ertangi rejalarimni aytib ber.",
        "hafta": "Keyingi 7 kunlik rejalarimni kunma-kun qisqa aytib ber.",
    }[cmd]
    await message.bot.send_chat_action(message.chat.id, ChatAction.TYPING)
    await message.answer(await ai.ask(question, remember=False))


@dp.message(Command("budilnik"))
async def alarms(message: Message) -> None:
    items = db.list_alarms()
    if not items:
        await message.answer("Budilnik yo'q. Masalan, «Har kuni 6:30 da uyg'ot» deb yozing.")
        return
    days = ["Du", "Se", "Ch", "Pa", "Ju", "Sh", "Ya"]
    lines = []
    for a in items:
        when = a["date"] or ", ".join(days[int(d)] for d in a["days"])
        lines.append(f"#{a['id']}  {a['time']}  ({when}) {a['label']}")
    await message.answer("⏰ Budilniklar:\n" + "\n".join(lines))


@dp.message(Command("yangi"))
async def reset(message: Message) -> None:
    db.clear_history()
    await message.answer("Suhbat tarixi tozalandi. Rejalaringiz joyida qoldi.")


@dp.message(Command("test_qongiroq"))
async def test_call(message: Message) -> None:
    if not caller.enabled:
        await message.answer("Qo'ng'iroq akkaunti ulanmagan. O'rnatish yo'riqnomasidagi 5-qadamni bajaring.")
        return
    await message.answer("Hozir qo'ng'iroq qilaman...")
    ogg = await voice.text_to_speech(f"Salom {config.OWNER_NAME}, bu sinov qo'ng'irog'i. Hammasi ishlayapti!")
    ok = await caller.ring(await voice.to_call_audio(ogg), seconds=15)
    await message.answer("Qo'ng'iroq ishladi ✅" if ok else "Qo'ng'iroqqa javob berilmadi yoki xato bo'ldi.")


@dp.message(Command("bilim"))
async def knowledge_list(message: Message) -> None:
    files = sorted(p.name for p in config.KNOWLEDGE_DIR.glob("*") if p.suffix.lower() in {".md", ".txt"}
                   and p.name.lower() != "readme.md")
    await message.answer("📚 Bilim bazasi:\n" + "\n".join(f"• {f}" for f in files) if files else "Bilim bazasi bo'sh.")


@dp.message(F.document)
async def on_document(message: Message) -> None:
    """Egasi yuborgan .md/.txt faylni bilim bazasiga qo'shadi (faqat serverda saqlanadi)."""
    name = Path(message.document.file_name or "").name
    if Path(name).suffix.lower() not in {".md", ".txt"}:
        await message.answer("Bilim bazasiga faqat .md yoki .txt fayl qo'shiladi.")
        return
    if message.document.file_size and message.document.file_size > 200_000:
        await message.answer("Fayl juda katta (200 KB dan ko'p). Uni qisqaroq konspekt qilib yuboring.")
        return
    # Shaxsiy fayllar git'ga tushmasligi uchun "shaxsiy-" bilan boshlanadi
    safe = "".join(c if c.isalnum() or c in "-_." else "-" for c in name)
    if not safe.startswith("shaxsiy-"):
        safe = "shaxsiy-" + safe
    await message.bot.download(message.document, destination=config.KNOWLEDGE_DIR / safe)
    await message.answer(f"📚 Bilim bazasiga qo'shildi: {safe}\nEndi maslahatlarimda shuni ham hisobga olaman.")


@dp.message(F.voice | F.audio)
async def on_voice(message: Message) -> None:
    await message.bot.send_chat_action(message.chat.id, ChatAction.TYPING)
    media = message.voice or message.audio
    path = Path(tempfile.mkdtemp()) / "xabar.ogg"
    await message.bot.download(media, destination=path)
    try:
        text = await voice.speech_to_text(path)
    except Exception as e:  # noqa: BLE001
        log.exception("STT error")
        await message.answer(f"Ovozli xabarni tushuna olmadim. Iltimos, yozib yuboring.\n\nTexnik sabab: {str(e)[:300]}")
        return
    if not text:
        await message.answer("Ovozli xabarda gap eshitilmadi.")
        return
    await message.answer(f"🎙 {text}")
    reply = await ai.ask(text)
    await _answer(message, reply, as_voice=True)


@dp.message(F.text)
async def on_text(message: Message) -> None:
    await message.bot.send_chat_action(message.chat.id, ChatAction.TYPING)
    reply = await ai.ask(message.text)
    await _answer(message, reply, as_voice=False)


@dp.callback_query(F.data.startswith("depart:"))
async def on_depart(call: CallbackQuery) -> None:
    event_id = int(call.data.split(":")[1])
    db.update_event(event_id, status="departed")
    await call.answer("Omad! 🎬")
    await call.message.edit_reply_markup(reply_markup=None)
    await call.message.answer("Zo'r, yo'lingiz bexatar bo'lsin! S'yomkadan keyin montaj vaqtini rejalashtirishni unutmang.")


@dp.callback_query(F.data.startswith("done:"))
async def on_done(call: CallbackQuery) -> None:
    db.update_event(int(call.data.split(":")[1]), status="done")
    await call.answer("Bajarildi ✅")
    await call.message.edit_reply_markup(reply_markup=None)


@dp.callback_query(F.data.startswith("snooze:"))
async def on_snooze(call: CallbackQuery) -> None:
    event_id = int(call.data.split(":")[1])
    # Keyingi eslatma 15 daqiqadan keyin keladi
    db.set_last_nag(event_id, db.now() + timedelta(minutes=15 - config.SHOOT_NAG_EVERY))
    await call.answer("15 daqiqadan keyin yana eslataman")
    await call.message.edit_reply_markup(reply_markup=None)


@dp.callback_query(F.data.startswith("awake:"))
async def on_awake(call: CallbackQuery) -> None:
    reminders.ringing.pop(int(call.data.split(":")[1]), None)
    await call.answer("Xayrli tong! ☀️")
    await call.message.edit_reply_markup(reply_markup=None)
    await reminders.morning_briefing(call.bot)


async def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    bot = Bot(config.BOT_TOKEN)
    await caller.start()
    asyncio.create_task(reminders.run(bot))
    try:
        await bot.send_message(config.OWNER_ID, "✅ Yordamchi ishga tushdi. /yordam — nimalar qila olishim.")
    except Exception:  # noqa: BLE001 — egasi hali /start bosmagan bo'lsa ham bot ishlayversin
        log.warning("Egasiga xabar yuborib bo'lmadi. Botga /start yozing.")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
