"""Telefon qo'ng'irog'ida jonli suhbat: egasi gapiradi, yordamchi eshitib, ovoz bilan javob beradi.

Ishlash tartibi: qo'ng'iroqdan kelgan ovozni (PCM) yig'amiz, gap tugaganini jimlikdan bilamiz,
keyin ovozni matnga aylantiramiz, AI javob beradi va javob qo'ng'iroqda ijro etiladi.
"""
import asyncio
import logging
import tempfile
import time
import wave
from array import array
from pathlib import Path

from . import actions, ai, config, voice
from .caller import caller

log = logging.getLogger(__name__)

RATE = 48000                 # qo'ng'iroqdan keladigan ovoz chastotasi
SILENCE_END = 0.9            # shuncha soniya jim tursa, gap tugadi deb hisoblaymiz
MIN_SPEECH = 0.4             # bundan qisqa ovoz (yo'tal, shovqin) e'tiborga olinmaydi
MAX_UTTERANCE = 25           # bitta gap eng ko'pi bilan shuncha soniya
IDLE_HANGUP = 60             # shuncha vaqt hech narsa demasa, qo'ng'iroqni tugatadi
MAX_CALL = 15 * 60           # qo'ng'iroq eng ko'pi bilan 15 daqiqa
BYE_WORDS = ("xayr", "bo'ldi rahmat", "boldi rahmat", "tamom", "qo'ng'iroqni tugat", "hayr")

CALL_NOTE = ("(Telefon orqali jonli gaplashyapmiz. Javobing ovozga aylantiriladi: 1-3 ta qisqa gap, "
             "ro'yxat, belgi va emoji ishlatma, so'zlashuv tilida gapir.)\n")


def _level(pcm: bytes) -> float:
    """Ovoz balandligi (o'rtacha amplituda)."""
    samples = array("h", pcm[: len(pcm) // 2 * 2])
    if not samples:
        return 0.0
    return sum(map(abs, samples[::4])) / (len(samples) / 4)


class Conversation:
    def __init__(self, greeting: str) -> None:
        self.greeting = greeting
        self.ended = asyncio.Event()
        self.started = time.monotonic()
        self.last_activity = time.monotonic()
        self.speaking_until = 0.0     # yordamchi gapirayotgan payt — mikrofonni eshitmaymiz
        self.busy = False             # javob tayyorlanmoqda
        self.noise = 150.0            # fon shovqini darajasi (o'zi moslashadi)
        self.buffer = bytearray()
        self.speech_time = 0.0
        self.silence_time = 0.0
        self.bye = False

    # --- ovoz kelishi ---
    def feed(self, pcm: bytes) -> None:
        if self.ended.is_set() or self.busy or time.monotonic() < self.speaking_until:
            return
        seconds = len(pcm) / 2 / RATE
        level = _level(pcm)
        loud = level > max(self.noise * 3, 400)
        if not loud and not self.buffer:
            self.noise = self.noise * 0.98 + level * 0.02
            return
        self.buffer += pcm
        if loud:
            self.speech_time += seconds
            self.silence_time = 0.0
        else:
            self.silence_time += seconds
        total = len(self.buffer) / 2 / RATE
        if self.silence_time >= SILENCE_END or total >= MAX_UTTERANCE:
            pcm_all, speech = bytes(self.buffer), self.speech_time
            self.buffer.clear()
            self.speech_time = self.silence_time = 0.0
            log.info("Qo'ng'iroqda gap yozildi: %.1f s (shundan ovoz %.1f s, shovqin %.0f)", total, speech, self.noise)
            if speech >= MIN_SPEECH:
                self.busy = True
                asyncio.create_task(self._answer(pcm_all))

    # --- javob berish ---
    async def say(self, text: str) -> None:
        try:
            ogg = await voice.text_to_speech(text)
            audio = await voice.to_call_audio(ogg)
            duration = await _duration(audio)
            self.speaking_until = time.monotonic() + duration + 0.8
            await caller.play_in_call(audio)
            await asyncio.sleep(duration + 0.3)
        except Exception:  # noqa: BLE001
            log.exception("Qo'ng'iroqda gapirib bo'lmadi")
        self.last_activity = time.monotonic()

    async def _answer(self, pcm: bytes) -> None:
        try:
            path = Path(tempfile.mkdtemp()) / "gap.wav"
            with wave.open(str(path), "wb") as w:
                w.setnchannels(1)
                w.setsampwidth(2)
                w.setframerate(RATE)
                w.writeframes(pcm)
            text = (await voice.speech_to_text(path)).strip()
            if not text:
                return
            log.info("Qo'ng'iroqda eshitildi: %s", text)
            self.last_activity = time.monotonic()
            low = text.lower()
            if any(w in low for w in BYE_WORDS):
                await self.say(f"Xayr, {config.OWNER_NAME}! Ishlaringizga omad.")
                self.bye = True
                self.ended.set()
                return
            quick = actions.quick_reply(text)
            if quick:
                result, reply = quick
                await self.say(_plain(reply))
                if result == "awake":
                    briefing = await ai.ask(CALL_NOTE + "Men hozir uyg'ondim. Bugungi rejalarimni qisqa aytib ber.",
                                            remember=False)
                    await self.say(briefing)
                return
            reply = await ai.ask(CALL_NOTE + text)
            await self.say(reply)
        except Exception:  # noqa: BLE001
            log.exception("Qo'ng'iroqdagi gapni qayta ishlab bo'lmadi")
            await self.say("Kechirasiz, tushunmadim. Qaytadan ayting.")
        finally:
            self.busy = False

    async def run(self) -> None:
        await self.say(self.greeting)
        while not self.ended.is_set():
            now = time.monotonic()
            if not self.busy and now - self.last_activity > IDLE_HANGUP:
                await self.say("Gapirmayapsiz, qo'ng'iroqni tugataman. Kerak bo'lsa, o'zingiz qo'ng'iroq qiling.")
                break
            if now - self.started > MAX_CALL:
                await self.say("Qo'ng'iroq uzoq cho'zildi, hozircha tugataman.")
                break
            try:
                await asyncio.wait_for(self.ended.wait(), timeout=1)
            except asyncio.TimeoutError:
                pass
        self.ended.set()


def _plain(text: str) -> str:
    return "".join(c for c in text if c.isalnum() or c in " ,.!?'‘’-\n").strip()


async def _duration(path: Path) -> float:
    proc = await asyncio.create_subprocess_exec(
        "ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path),
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
    )
    out, _ = await proc.communicate()
    try:
        return float(out.decode().strip())
    except ValueError:
        return 5.0
