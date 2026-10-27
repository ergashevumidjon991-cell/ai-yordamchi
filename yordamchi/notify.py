"""Egasiga xabar yuborish: ikkinchi akkaunt ulangan bo'lsa o'sha orqali, aks holda bot orqali.

Ikkinchi akkauntda tugmalar ishlamaydi, shuning uchun tugma o'rniga "hint" matni qo'shiladi
(masalan: Javob yozing: «chiqdim»).
"""
import logging
from pathlib import Path

from aiogram import Bot
from aiogram.types import FSInputFile

from . import config, voice
from .caller import caller

log = logging.getLogger(__name__)

bot: Bot | None = None


def _join(text: str, hint: str) -> str:
    return f"{text}\n\n{hint}" if hint else text


async def text(msg: str, markup=None, hint: str = "") -> None:
    if caller.chat_enabled:
        await caller.send_text(_join(msg, hint))
    else:
        await bot.send_message(config.OWNER_ID, msg, reply_markup=markup)


async def voice_file(ogg: Path, caption: str, markup=None, hint: str = "") -> None:
    if caller.chat_enabled:
        await caller.send_voice(ogg, _join(caption, hint))
    else:
        await bot.send_voice(config.OWNER_ID, FSInputFile(ogg), caption=caption[:1000], reply_markup=markup)


async def say(msg: str, markup=None, hint: str = "") -> None:
    """Matnni ovozga aylantirib yuboradi. Ovoz ishlamasa matn yetib boradi."""
    try:
        ogg = await voice.text_to_speech(msg)
    except Exception:  # noqa: BLE001
        log.exception("TTS error")
        await text(msg, markup, hint)
        return
    await voice_file(ogg, msg, markup, hint)
