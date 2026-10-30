"""Gemini orqali javob berish (AI_PROVIDER=gemini bo'lsa). Vositalar (tools) ai.py dagi bilan bir xil."""
import asyncio
import logging

from google import genai
from google.genai import errors as genai_errors
from google.genai import types

from . import ai, config, db

log = logging.getLogger(__name__)

_client: genai.Client | None = None


async def _generate(contents, cfg, model: str = ""):
    """Gemini band bo'lsa (503/429) bir necha marta qayta urinadi."""
    delay = 2
    for attempt in range(4):
        try:
            return await _gemini().aio.models.generate_content(
                model=model or config.GEMINI_MODEL, contents=contents, config=cfg)
        except genai_errors.APIError as e:
            if e.code not in (429, 503) or attempt == 3:
                raise
            log.warning("Gemini band (%s), %s soniyadan keyin qayta urinaman", e.code, delay)
            await asyncio.sleep(delay)
            delay *= 2


def _gemini() -> genai.Client:
    global _client
    if _client is None:
        # Har bir so'rov 30 soniyadan oshmasin, aks holda javob daqiqalab kutiladi
        _client = genai.Client(api_key=config.GEMINI_API_KEY,
                               http_options=types.HttpOptions(timeout=30_000))
    return _client


def _declarations() -> list[types.FunctionDeclaration]:
    return [types.FunctionDeclaration(name=t["name"], description=t["description"],
                                      parameters_json_schema=t["input_schema"]) for t in ai.TOOLS]


def _config(system: str, with_tools: bool) -> types.GenerateContentConfig:
    return types.GenerateContentConfig(
        system_instruction=system,
        max_output_tokens=4000,
        temperature=0.7,
        # Ichki o'ylash o'chirilgan: javob tezroq keladi (ovozli xabarga o'xshash qisqa javoblar uchun)
        thinking_config=types.ThinkingConfig(thinking_budget=0),
        tools=[types.Tool(function_declarations=_declarations())] if with_tools else None,
    )


def _text(response) -> str:
    return (response.text or "").strip()


async def chat(system: str, messages: list[dict]) -> str:
    """Vositalarsiz javob (mijozlar bilan suhbat). Xato bo'lsa bo'sh qator."""
    contents = [types.Content(role="model" if m["role"] == "assistant" else "user",
                              parts=[types.Part(text=m["content"])]) for m in messages]
    try:
        response = await _generate(contents, _config(system, with_tools=False))
    except Exception:  # noqa: BLE001
        log.exception("Gemini error (mijoz suhbati)")
        return ""
    return _text(response)


async def ask(user_text: str, remember: bool = True) -> str:
    """Egasining xabariga javob beradi, kerak bo'lsa vositalar bilan rejani o'zgartiradi."""
    history = db.get_history() if remember else []
    contents = [types.Content(role="model" if m["role"] == "assistant" else "user",
                              parts=[types.Part(text=m["content"])]) for m in history]
    contents.append(types.Content(role="user", parts=[types.Part(text=f"{ai._now_note()}\n{user_text}")]))
    system = ai.SYSTEM_PROMPT.format(name=config.OWNER_NAME) + ai._knowledge()
    cfg = _config(system, with_tools=True)

    reply = ""
    for _ in range(8):
        try:
            response = await _generate(contents, cfg)
        except Exception as e:  # noqa: BLE001
            log.exception("Gemini error")
            return f"Gemini xato qaytardi: {str(e)[:200]}"
        if not response.candidates:
            return "Gemini javob bermadi. Qaytadan yozib ko'ring."
        text = _text(response)
        if text:
            reply = text
        calls = response.function_calls or []
        if not calls:
            break
        contents.append(response.candidates[0].content)
        parts = []
        for call in calls:
            result = await ai._run_tool(call.name, dict(call.args or {}))
            parts.append(types.Part.from_function_response(name=call.name, response={"result": result}))
        contents.append(types.Content(role="user", parts=parts))

    reply = reply or "Bajarildi."
    if remember:
        db.add_history("user", user_text)
        db.add_history("assistant", reply)
    return reply


# --- Ovoz: VOICE_PROVIDER=gemini bo'lsa ---

STT_PROMPT = ("Bu audioda o'zbekcha gap bor. Aytilgan so'zlarni o'zbek lotin yozuvida aynan yozib ber. "
              "Hech narsa qo'shma, izoh berma. Gap eshitilmasa, bo'sh javob qaytar.")
AUDIO_TYPES = {".ogg": "audio/ogg", ".oga": "audio/ogg", ".wav": "audio/wav", ".mp3": "audio/mp3"}


async def speech_to_text(audio_path) -> str:
    mime = AUDIO_TYPES.get(audio_path.suffix.lower(), "audio/ogg")
    contents = [types.Part.from_bytes(data=audio_path.read_bytes(), mime_type=mime), STT_PROMPT]
    cfg = types.GenerateContentConfig(temperature=0, thinking_config=types.ThinkingConfig(thinking_budget=0))
    response = await _generate(contents, cfg, config.GEMINI_STT_MODEL or config.GEMINI_MODEL)
    return _text(response)


async def text_to_speech_pcm(text: str) -> bytes:
    """Matnni ovozga aylantiradi: 24 kHz, 16-bit, mono PCM qaytaradi."""
    cfg = types.GenerateContentConfig(
        response_modalities=["AUDIO"],
        speech_config=types.SpeechConfig(voice_config=types.VoiceConfig(
            prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name=config.GEMINI_TTS_VOICE))),
    )
    prompt = f"O'zbek tilida, samimiy va xotirjam ohangda o'qi: {text}"
    response = await _generate(prompt, cfg, config.GEMINI_TTS_MODEL)
    for part in response.candidates[0].content.parts:
        if part.inline_data and part.inline_data.data:
            return part.inline_data.data
    raise RuntimeError("Gemini ovoz qaytarmadi")
