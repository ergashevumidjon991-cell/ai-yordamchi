import asyncio
import logging
import tempfile
from pathlib import Path

from aiogram import Bot, Dispatcher, F
from aiogram.enums import ChatAction
from aiogram.filters import Command, CommandStart
from aiogram.types import CallbackQuery, FSInputFile, Message

from . import actions, ai, config, db, notify, reminders, userchat, voice
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
    await message.answer(userchat.alarms_text())


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
    files = actions.knowledge_files()
    # Nomlarni <code> ichiga olamiz, aks holda Telegram ".md" ni sayt havolasi deb o'ylaydi
    text = "📚 Bilim bazasi (serverda saqlanadi):\n" + "\n".join(f"• <code>{f}</code>" for f in files)
    await message.answer(text if files else "Bilim bazasi bo'sh.", parse_mode="HTML")


@dp.message(F.document)
async def on_document(message: Message) -> None:
    """Egasi yuborgan .md/.txt faylni bilim bazasiga qo'shadi (faqat serverda saqlanadi)."""
    target = actions.knowledge_target(message.document.file_name or "")
    if target is None:
        await message.answer("Bilim bazasiga faqat .md yoki .txt fayl qo'shiladi.")
        return
    if message.document.file_size and message.document.file_size > 200_000:
        await message.answer("Fayl juda katta (200 KB dan ko'p). Uni qisqaroq konspekt qilib yuboring.")
        return
    await message.bot.download(message.document, destination=target)
    await message.answer(f"📚 Bilim bazasiga qo'shildi: {target.name}\nEndi maslahatlarimda shuni ham hisobga olaman.")


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
    actions.depart(event_id)
    await call.answer("Omad! 🎬")
    await call.message.edit_reply_markup(reply_markup=None)
    await call.message.answer("Zo'r, yo'lingiz bexatar bo'lsin! S'yomkadan keyin montaj vaqtini rejalashtirishni unutmang.")


@dp.callback_query(F.data.startswith("done:"))
async def on_done(call: CallbackQuery) -> None:
    actions.done(int(call.data.split(":")[1]))
    await call.answer("Bajarildi ✅")
    await call.message.edit_reply_markup(reply_markup=None)


@dp.callback_query(F.data.startswith("snooze:"))
async def on_snooze(call: CallbackQuery) -> None:
    event_id = int(call.data.split(":")[1])
    actions.snooze(event_id)
    await call.answer("15 daqiqadan keyin yana eslataman")
    await call.message.edit_reply_markup(reply_markup=None)


@dp.callback_query(F.data.startswith("awake:"))
async def on_awake(call: CallbackQuery) -> None:
    actions.awake(int(call.data.split(":")[1]))
    await call.answer("Xayrli tong! ☀️")
    await call.message.edit_reply_markup(reply_markup=None)
    await reminders.morning_briefing()


async def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    bot = Bot(config.BOT_TOKEN)
    notify.bot = bot
    try:
        await caller.start()
    except Exception:  # noqa: BLE001 — ikkinchi akkaunt ishlamasa ham bot ishlayversin
        log.exception("Ikkinchi akkauntni ishga tushirib bo'lmadi")
        caller.enabled = False
    if caller.chat_enabled:
        userchat.setup()
        log.info("Suhbat va eslatmalar ikkinchi akkaunt orqali")
    asyncio.create_task(reminders.run())
    try:
        await notify.text("✅ Yordamchi ishga tushdi. /yordam — nimalar qila olishim.")
    except Exception:  # noqa: BLE001 — egasi hali /start bosmagan bo'lsa ham bot ishlayversin
        log.warning("Egasiga xabar yuborib bo'lmadi. Botga /start yozing.")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
