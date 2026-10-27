import asyncio
import logging
import re
import tempfile
from pathlib import Path

import edge_tts
import httpx

from . import config

log = logging.getLogger(__name__)


ELEVEN_URL = "https://api.elevenlabs.io/v1"


async def speech_to_text(audio_path: Path) -> str:
    """Ovozli xabarni matnga aylantiradi: ElevenLabs Scribe, bo'lmasa Whisper."""
    if config.ELEVEN_API_KEY:
        try:
            return await _eleven_stt(audio_path)
        except Exception as e:  # noqa: BLE001 — kredit tugasa zaxira Whisper'ga o'tamiz
            if not config.STT_API_KEY:
                raise
            log.warning("ElevenLabs STT ishlamadi (%s), Whisper ishlatiladi", e)
    if not config.STT_API_KEY:
        raise RuntimeError("ELEVEN_API_KEY ham, STT_API_KEY ham ko'rsatilmagan")
    async with httpx.AsyncClient(timeout=120) as http:
        with audio_path.open("rb") as f:
            resp = await http.post(
                f"{config.STT_BASE_URL}/audio/transcriptions",
                headers={"Authorization": f"Bearer {config.STT_API_KEY}"},
                files={"file": (audio_path.name, f, "audio/ogg")},
                data={"model": config.STT_MODEL, "language": "uz", "response_format": "json"},
            )
    resp.raise_for_status()
    return resp.json().get("text", "").strip()


async def _eleven_stt(audio_path: Path) -> str:
    async with httpx.AsyncClient(timeout=120) as http:
        with audio_path.open("rb") as f:
            resp = await http.post(
                f"{ELEVEN_URL}/speech-to-text",
                headers={"xi-api-key": config.ELEVEN_API_KEY},
                files={"file": (audio_path.name, f, "audio/ogg")},
                data={"model_id": config.ELEVEN_STT_MODEL, "language_code": "uz"},
            )
    resp.raise_for_status()
    return resp.json().get("text", "").strip()


def _clean_for_speech(text: str) -> str:
    text = re.sub(r"[*_#`|>]", "", text)
    text = re.sub(r"https?://\S+", "", text)
    return text.strip()


async def text_to_speech(text: str) -> Path:
    """Matnni erkak ovozida o'qiydi va Telegram uchun .ogg (opus) fayl qaytaradi."""
    tmp = Path(tempfile.mkdtemp())
    mp3 = tmp / "javob.mp3"
    ogg = tmp / "javob.ogg"
    text = _clean_for_speech(text)
    try:
        if not config.ELEVEN_API_KEY:
            raise RuntimeError("ElevenLabs sozlanmagan")
        await _eleven_tts(text, mp3)
    except Exception as e:  # noqa: BLE001 — kredit tugasa yoki xato bo'lsa bepul ovozga o'tamiz
        if config.ELEVEN_API_KEY:
            log.warning("ElevenLabs TTS ishlamadi (%s), bepul ovoz ishlatiladi", e)
        await edge_tts.Communicate(text, config.TTS_VOICE).save(str(mp3))
    await _ffmpeg("-i", str(mp3), "-c:a", "libopus", "-b:a", "48k", str(ogg))
    return ogg


async def _eleven_tts(text: str, dst: Path) -> None:
    async with httpx.AsyncClient(timeout=120) as http:
        resp = await http.post(
            f"{ELEVEN_URL}/text-to-speech/{config.ELEVEN_VOICE_ID}",
            params={"output_format": "mp3_44100_128"},
            headers={"xi-api-key": config.ELEVEN_API_KEY},
            json={"text": text, "model_id": config.ELEVEN_TTS_MODEL, "language_code": "uz"},
        )
    resp.raise_for_status()
    dst.write_bytes(resp.content)


async def to_call_audio(src: Path) -> Path:
    """Qo'ng'iroqda ijro etish uchun audio faylni tayyorlaydi (48 kHz stereo)."""
    dst = src.with_suffix(".call.mp3")
    await _ffmpeg("-i", str(src), "-ar", "48000", "-ac", "2", str(dst))
    return dst


async def _ffmpeg(*args: str) -> None:
    proc = await asyncio.create_subprocess_exec(
        "ffmpeg", "-y", "-loglevel", "error", *args,
        stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE,
    )
    _, err = await proc.communicate()
    if proc.returncode != 0:
        raise RuntimeError(f"ffmpeg xatosi: {err.decode(errors='ignore')}")
