"""Ikkinchi Telegram akkaunt (userbot): qo'ng'iroq qilish va egasi bilan yozishish."""
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

    @property
    def chat_enabled(self) -> bool:
        """Suhbat va eslatmalar ikkinchi akkaunt orqali ketadimi."""
        return self.enabled and self._client is not None and config.CHAT_VIA != "bot"

    async def start(self) -> None:
        if not self.enabled:
            log.info("Userbot sozlanmagan, qo'ng'iroq o'rniga ovozli xabarlar ishlatiladi")
            return
        if not Path(config.USERBOT_SESSION + ".session").exists():
            log.warning("Userbot sessiyasi yo'q. Avval: python login_userbot.py")
            self.enabled = False
            return
        from telethon import TelegramClient

        self._client = TelegramClient(config.USERBOT_SESSION, int(config.USERBOT_API_ID), config.USERBOT_API_HASH)
        await self._client.start()
        if (await self._client.get_me()).bot:
            log.error("Ikkinchi akkaunt o'rniga bot ulangan. Qayta ulang: python login_userbot.py")
            await self._client.disconnect()
            self._client = None
            self.enabled = False
            return
        # Egasini topa olishimiz uchun suhbatlar ro'yxatini yuklaymiz (avval egasi bir marta yozgan bo'lishi kerak)
        try:
            await self._client.get_dialogs()
        except Exception:  # noqa: BLE001
            log.exception("Suhbatlar ro'yxatini yuklab bo'lmadi")
        try:
            from pytgcalls import PyTgCalls

            self._calls = PyTgCalls(self._client)
            await self._calls.start()
            log.info("Userbot ishga tushdi, qo'ng'iroqlar yoqilgan")
        except Exception:  # noqa: BLE001 — qo'ng'iroq ishlamasa ham yozishish ishlasin
            log.exception("Qo'ng'iroq modulini ishga tushirib bo'lmadi")
            self._calls = None

    def on_owner_message(self, handler) -> None:
        """Egasidan kelgan shaxsiy xabarlarni handler(event) ga uzatadi."""
        from telethon import events

        @self._client.on(events.NewMessage(incoming=True, from_users=config.OWNER_ID))
        async def _wrap(event) -> None:
            if not event.is_private:
                return
            try:
                await handler(event)
            except Exception:  # noqa: BLE001 — bitta xato suhbatni to'xtatmasin
                log.exception("Userbot handler error")
                await self.send_text("Kechirasiz, xatolik bo'ldi. Qaytadan yozib ko'ring.")

    async def send_text(self, text: str) -> None:
        await self._client.send_message(config.OWNER_ID, text)

    async def send_voice(self, ogg: Path, caption: str = "") -> None:
        await self._client.send_file(config.OWNER_ID, str(ogg), voice_note=True, caption=caption[:1000])

    def typing(self, voice: bool = False):
        """async with caller.typing(): ... — "yozmoqda"/"ovoz yozmoqda" holatini ko'rsatadi."""
        return self._client.action(config.OWNER_ID, "record-audio" if voice else "typing")

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
