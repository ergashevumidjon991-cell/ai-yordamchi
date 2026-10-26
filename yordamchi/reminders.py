"""Har 30 soniyada rejalarni tekshirib, eslatma va budilniklarni yuboradi."""
import asyncio
import json
import logging
from datetime import timedelta

from aiogram import Bot
from aiogram.types import FSInputFile, InlineKeyboardButton, InlineKeyboardMarkup

from . import ai, config, db, voice
from .caller import caller

log = logging.getLogger(__name__)

KIND_NAMES = {"syomka": "S'yomka", "montaj": "Montaj", "post": "Post joylash", "boshqa": "Ish"}

# Hozir jiringlayotgan budilniklar: alarm_id -> urinishlar soni
ringing: dict[int, int] = {}


def _event_buttons(event: dict) -> InlineKeyboardMarkup:
    if event["kind"] == "syomka":
        return InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="🚗 Yo'lga chiqdim", callback_data=f"depart:{event['id']}"),
            InlineKeyboardButton(text="⏰ 15 daqiqadan keyin", callback_data=f"snooze:{event['id']}"),
        ]])
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="✅ Bajarildi", callback_data=f"done:{event['id']}"),
    ]])


def _alarm_buttons(alarm_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="☀️ Turdim", callback_data=f"awake:{alarm_id}"),
    ]])


def _when_text(minutes: int) -> str:
    if minutes >= 24 * 60:
        return "Ertaga"
    if minutes >= 60:
        return f"{minutes // 60} soatdan keyin"
    if minutes > 0:
        return f"{minutes} daqiqadan keyin"
    if minutes < 0:
        return f"{-minutes} daqiqa kechikyapsiz"
    return "Hozir"


def _event_text(event: dict, minutes_left: int) -> str:
    start = db.parse_dt(event["start_at"])
    lines = [f"🔔 {_when_text(minutes_left)}: {KIND_NAMES[event['kind']]} — {event['title']}",
             f"🕒 {start:%d.%m %H:%M}"]
    if event["location"]:
        lines.append(f"📍 {event['location']}")
    if event["notes"]:
        lines.append(f"📝 {event['notes']}")
    return "\n".join(lines)


async def _send_voice(bot: Bot, text: str, markup=None) -> None:
    try:
        ogg = await voice.text_to_speech(text)
        await bot.send_voice(config.OWNER_ID, FSInputFile(ogg), caption=text[:1000], reply_markup=markup)
    except Exception:  # noqa: BLE001 — ovoz ishlamasa ham matn yetib borsin
        log.exception("TTS error")
        await bot.send_message(config.OWNER_ID, text, reply_markup=markup)


async def check_events(bot: Bot) -> None:
    now = db.now()
    for event in db.active_events():
        start = db.parse_dt(event["start_at"])
        minutes_left = int((start - now).total_seconds() // 60)
        stages = config.SHOOT_REMINDERS if event["kind"] == "syomka" else config.TASK_REMINDERS
        sent = json.loads(event["sent"] or "[]")

        # Vaqti kelgan, hali yuborilmagan eslatmalardan faqat eng oxirgisini yuboramiz
        due = [m for m in stages if minutes_left <= m and m not in sent]
        if due and minutes_left >= -15:
            await _send_voice(bot, _event_text(event, minutes_left), _event_buttons(event))
            db.mark_sent(event["id"], sorted(set(sent + due)))
            db.set_last_nag(event["id"], now)
            continue
        if due:
            db.mark_sent(event["id"], sorted(set(sent + due)))

        # S'yomka: oxirgi eslatmadan keyin "Yo'lga chiqdim" bosilmaguncha qayta-qayta eslatamiz
        if event["kind"] == "syomka" and min(stages) in sent:
            if minutes_left < -config.SHOOT_NAG_UNTIL_AFTER:
                continue
            last = db.parse_dt(event["last_nag"]) if event["last_nag"] else None
            if last is None or now - last >= timedelta(minutes=config.SHOOT_NAG_EVERY):
                text = _event_text(event, minutes_left)
                text += "\n\nYo'lga chiqqan bo'lsangiz, tugmani bosing. Bosmaguningizcha eslatib turaman."
                await _send_voice(bot, text, _event_buttons(event))
                db.set_last_nag(event["id"], now)


async def check_alarms(bot: Bot) -> None:
    now = db.now()
    stamp = now.strftime("%Y-%m-%d %H:%M")
    for alarm in db.list_alarms():
        if alarm["time"] != now.strftime("%H:%M") or alarm["last_fired"] == stamp:
            continue
        if alarm["date"] and alarm["date"] != now.strftime("%Y-%m-%d"):
            continue
        if not alarm["date"] and str(now.weekday()) not in alarm["days"]:
            continue
        db.alarm_fired(alarm, now)
        ringing[alarm["id"]] = 0
        asyncio.create_task(_ring_loop(bot, alarm))


async def _ring_loop(bot: Bot, alarm: dict) -> None:
    text = f"Assalomu alaykum, {config.OWNER_NAME}! Turish vaqti bo'ldi, soat {alarm['time']}."
    if alarm["label"]:
        text += f" {alarm['label']}."
    try:
        ogg = await voice.text_to_speech(text + " Turing, bugun ko'p ishimiz bor!")
        call_audio = await voice.to_call_audio(ogg)
    except Exception:  # noqa: BLE001
        log.exception("Alarm TTS error")
        ogg = call_audio = None

    while alarm["id"] in ringing and ringing[alarm["id"]] < config.ALARM_MAX_TRIES:
        ringing[alarm["id"]] += 1
        if ogg:
            await bot.send_voice(config.OWNER_ID, FSInputFile(ogg), caption="⏰ " + text,
                                 reply_markup=_alarm_buttons(alarm["id"]))
        else:
            await bot.send_message(config.OWNER_ID, "⏰ " + text, reply_markup=_alarm_buttons(alarm["id"]))
        if call_audio:
            await caller.ring(call_audio)
        for _ in range(config.ALARM_REPEAT_EVERY * 60 // 5):
            if alarm["id"] not in ringing:
                return
            await asyncio.sleep(5)
    ringing.pop(alarm["id"], None)


async def morning_briefing(bot: Bot) -> None:
    """Uyg'ongandan keyin bugungi rejani ovoz bilan aytib beradi."""
    reply = await ai.ask(
        "Men hozir uyg'ondim. Bugungi rejalarimni qisqa aytib ber va kunga bitta foydali maslahat ber.",
        remember=False,
    )
    await _send_voice(bot, reply)


async def run(bot: Bot) -> None:
    while True:
        try:
            await check_alarms(bot)
            await check_events(bot)
        except Exception:  # noqa: BLE001 — bitta xato butun rejalashtiruvchini to'xtatmasin
            log.exception("Scheduler error")
        await asyncio.sleep(30)
