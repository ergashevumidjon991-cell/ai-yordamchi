import asyncio
import logging
import re
import tempfile
from pathlib import Path

import edge_tts
import httpx

from . import config

log = logging.getLogger(__name__)


async def speech_to_text(audio_path: Path) -> str:
    """Ovozli xabarni matnga aylantiradi (Whisper, OpenAI-mos API orqali)."""
    if not config.STT_API_KEY:
        raise RuntimeError("STT_API_KEY ko'rsatilmagan")
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


def _clean_for_speech(text: str) -> str:
    text = re.sub(r"[*_#`|>]", "", text)
    text = re.sub(r"https?://\S+", "", text)
    return text.strip()


async def text_to_speech(text: str) -> Path:
    """Matnni erkak ovozida o'qiydi va Telegram uchun .ogg (opus) fayl qaytaradi."""
    tmp = Path(tempfile.mkdtemp())
    mp3 = tmp / "javob.mp3"
    ogg = tmp / "javob.ogg"
    await edge_tts.Communicate(_clean_for_speech(text), config.TTS_VOICE).save(str(mp3))
    await _ffmpeg("-i", str(mp3), "-c:a", "libopus", "-b:a", "48k", str(ogg))
    return ogg


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
