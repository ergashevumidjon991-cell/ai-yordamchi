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
        self._conv = None
        self._lock = asyncio.Lock()

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
            self._register_call_handlers()
            log.info("Userbot ishga tushdi, qo'ng'iroqlar yoqilgan")
        except Exception:  # noqa: BLE001 — qo'ng'iroq ishlamasa ham yozishish ishlasin
            log.exception("Qo'ng'iroq modulini ishga tushirib bo'lmadi")
            self._calls = None

    def _register_call_handlers(self) -> None:
        from pytgcalls import filters
        from pytgcalls.types import ChatUpdate, Direction

        @self._calls.on_update(filters.stream_frame(Direction.INCOMING))
        async def _frames(_, update) -> None:
            if self._conv is not None and update.chat_id == config.OWNER_ID:
                for frame in update.frames:
                    self._conv.feed(frame.frame)

        @self._calls.on_update(filters.chat_update(ChatUpdate.Status.LEFT_CALL | ChatUpdate.Status.INCOMING_CALL
                                                   | ChatUpdate.Status.MIGRATE_TO_CONFERENCE_CALL))
        async def _log_status(_, update) -> None:
            log.info("Qo'ng'iroq holati: %s", update.status)

        @self._calls.on_update(filters.stream_end())
        async def _stream_end(_, update) -> None:
            log.info("Ovoz ijrosi tugadi: %s %s", update.stream_type, update.device)

        @self._calls.on_update(filters.chat_update(ChatUpdate.Status.LEFT_CALL))
        async def _ended(_, update) -> None:
            if self._conv is not None and update.chat_id == config.OWNER_ID:
                self._conv.ended.set()

        @self._calls.on_update(filters.chat_update(ChatUpdate.Status.INCOMING_CALL))
        async def _incoming(_, update) -> None:
            if update.chat_id == config.OWNER_ID:
                asyncio.create_task(self.converse(f"Eshitaman, {config.OWNER_NAME}!", incoming=True))

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

    async def _silence(self) -> Path:
        """Qo'ng'iroqni boshlash uchun 1 soniyalik jim audio."""
        path = config.DATA_DIR / "silence.mp3"
        if not path.exists():
            from . import voice

            await voice._ffmpeg("-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo", "-t", "1", str(path))
        return path

    async def play_in_call(self, audio: Path) -> None:
        await self._calls.play(config.OWNER_ID, str(audio))

    async def converse(self, greeting: str, seconds: int = 45, incoming: bool = False) -> bool:
        """Egasiga qo'ng'iroq qiladi (yoki uning qo'ng'irog'ini oladi) va jonli gaplashadi.

        Javob berilsa True. Gap telefon ko'tarilgandan keyin boshlanadi.
        """
        if not self.enabled or self._calls is None:
            return False
        if self._lock.locked():
            return False
        from pytgcalls.types import CallConfig, RecordStream
        from pytgcalls.types.raw import AudioParameters

        from .livecall import RATE, Conversation

        async with self._lock:
            try:
                await self._calls.play(config.OWNER_ID, str(await self._silence()),
                                       config=CallConfig(timeout=seconds))
            except Exception as e:  # noqa: BLE001 — rad etilsa/javob berilmasa ham davom etamiz
                log.info("Qo'ng'iroqqa javob berilmadi: %s", e.__class__.__name__)
                return False
            self._conv = Conversation(greeting)
            try:
                await self._calls.record(config.OWNER_ID,
                                         RecordStream(audio=True, audio_parameters=AudioParameters(RATE, 1)))
                log.info("Qo'ng'iroqdagi ovozni eshitish yoqildi")
            except Exception:  # noqa: BLE001 — eshita olmasak ham hech bo'lmasa gapiramiz
                log.exception("Qo'ng'iroqdagi ovozni yozib bo'lmadi")
            try:
                await self._conv.run()
            finally:
                self._conv = None
                try:
                    await self._calls.leave_call(config.OWNER_ID)
                except Exception:  # noqa: BLE001
                    pass
            return True


caller = Caller()
