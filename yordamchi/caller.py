"""Ikkinchi Telegram akkaunt orqali haqiqiy qo'ng'iroq qilish (userbot)."""
import asyncio
import logging
from pathlib import Path

from . import config

log = logging.getLogger(__name__)


class Caller:
    def __init__(self) -> None:
        self.enabled = bool(config.USERBOT_API_ID and config.USERBOT_API_HASH)
        self._client = None
        self._calls = None

    async def start(self) -> None:
        if not self.enabled:
            log.info("Userbot sozlanmagan, qo'ng'iroq o'rniga ovozli xabarlar ishlatiladi")
            return
        if not Path(config.USERBOT_SESSION + ".session").exists():
            log.warning("Userbot sessiyasi yo'q. Avval: python login_userbot.py")
            self.enabled = False
            return
        from pytgcalls import PyTgCalls
        from telethon import TelegramClient

        self._client = TelegramClient(config.USERBOT_SESSION, int(config.USERBOT_API_ID), config.USERBOT_API_HASH)
        await self._client.start()
        self._calls = PyTgCalls(self._client)
        await self._calls.start()
        log.info("Userbot ishga tushdi, qo'ng'iroqlar yoqilgan")

    async def ring(self, audio: Path, seconds: int = 45) -> bool:
        """Egasiga qo'ng'iroq qiladi va audio faylni ijro etadi. Javob berilsa True."""
        if not self.enabled or self._calls is None:
            return False
        from pytgcalls.types import CallConfig

        try:
            await self._calls.play(config.OWNER_ID, str(audio), config=CallConfig(timeout=seconds))
        except Exception as e:  # noqa: BLE001 — rad etilsa/javob berilmasa ham davom etamiz
            log.info("Qo'ng'iroqqa javob berilmadi: %s", e.__class__.__name__)
            return False
        await asyncio.sleep(seconds)
        try:
            await self._calls.leave_call(config.OWNER_ID)
        except Exception:  # noqa: BLE001
            pass
        return True


caller = Caller()
