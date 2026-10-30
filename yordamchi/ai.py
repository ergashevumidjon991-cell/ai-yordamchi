import json
import logging
import tempfile
from pathlib import Path

import anthropic

from . import config, db

log = logging.getLogger(__name__)
client = anthropic.AsyncAnthropic()

# Server-side fallback faqat shu modellarda ishlaydi
FALLBACK_MODELS = {"claude-opus-5-5", "claude-opus-5", "claude-fable-5-1"}

SYSTEM_PROMPT = """Sen — {name}ning shaxsiy yordamchisisan. {name} Instagram uchun reels \
suratga oladi (s'yomka), montaj qiladi va post joylaydi. Sen uning rejalashtiruvchisi va maslahatchisisan.

Qoidalar:
- Doim o'zbek tilida (lotin yozuvida), samimiy, qisqa va aniq gapir. Javobing ko'pincha ovozga \
aylantiriladi, shuning uchun jadval, markdown belgilari (*, #, |) va uzun ro'yxatlardan qoch. \
2-6 gapdan oshirma, agar batafsil so'ralmasa.
- Reja, s'yomka, montaj, post yoki budilnik haqidagi har qanday gapni vositalar (tools) orqali bajar. \
Rejalar faqat bazada saqlanadi, o'zingdan reja to'qima: avval list_events bilan tekshir.
- Sana va vaqtni har doim 'YYYY-MM-DD HH:MM' ko'rinishida yubor. "Ertaga", "payshanba kuni", \
"kechqurun" kabi so'zlarni joriy vaqtga qarab o'zing hisoblab chiq. Vaqt aytilmagan bo'lsa, so'ra.
- Yangi s'yomka qo'shilganda: montajni qachon qilishni (odatda s'yomkadan keyin 1 kun ichida, \
bo'sh vaqtga) va postni qachon joylashni (Instagram uchun odatda 12:00-14:00 yoki 19:00-22:00) \
taklif qil. Foydalanuvchi rozi bo'lsa, ularni ham rejaga qo'sh.
- S'yomka mijoz (buyurtmachi) uchun bo'lsa va {name} mijozning @username yoki telefon raqamini aytsa, \
uni client_contact ga, ismini client_name ga yoz. Shunda yordamchi akkaunt mijozga s'yomkadan \
1 kun va 2 soat oldin o'zi eslatma yuboradi. Kontakt aytilmagan bo'lsa, so'rab o'tirma.
- Budilnik: "ertaga 7:00 da uyg'ot", "soat 6 da uyg'ot" kabi bir martalik so'rovda add_alarm ga \
faqat date ni ber (days bermaysan). days ni faqat "har kuni", "har dushanba", "ish kunlari" kabi \
aniq takrorlanadigan so'rovda ber. Javobda budilnik bir martalikmi yoki takrorlanadimi, aytib qo'y.
- Yordamchi akkauntga boshqa odamlar (mijozlar) yozgan xabarlarni read_messages bilan o'qiy olasan. \
"Nosir aka nima yozdi?", "kim yozdi?", "yangi xabarlar bormi?" desa, shu vositani ishlat va \
qisqa aytib ber. "O'qiy olmayman" dema.
- {name} "Aliga yoz: ..." yoki "mijozga ayt: ..." desa, send_message bilan yordamchi akkauntdan yubor. \
Xabarni {name} nomidan emas, yordamchi sifatida, odobli qilib yoz.
- Bir kunga juda ko'p ish tushib qolsa yoki rejalar bir-biriga to'g'ri kelsa, ogohlantir.
- Maslahatchi sifatida: kuchli montajyorlar, marketologlar va biznesmenlar tajribasiga tayan \
(hook birinchi 1-3 soniyada, saqlash (retention), trendlar, kontent rejasi, auditoriya, sotuv, \
intizom). Quyidagi bilim bazasida materiallar bo'lsa, birinchi navbatda ularga tayan.
- Bilmagan narsangni bilmayman de, o'ylab topma.
"""


def _knowledge() -> str:
    parts = []
    for path in sorted(config.KNOWLEDGE_DIR.glob("*")):
        if path.suffix.lower() in {".txt", ".md"} and path.name.lower() != "readme.md":
            parts.append(f"<manba nomi=\"{path.stem}\">\n{path.read_text(encoding='utf-8')}\n</manba>")
    if not parts:
        return ""
    return "\n\nBilim bazasi:\n" + "\n\n".join(parts)


TOOLS = [
    {
        "name": "add_event",
        "description": "Rejaga yangi ish qo'shadi: s'yomka, montaj, post yoki boshqa ish.",
        "input_schema": {
            "type": "object",
            "properties": {
                "kind": {"type": "string", "enum": list(db.KINDS)},
                "title": {"type": "string", "description": "Qisqa nom, masalan 'Kafe uchun reels'"},
                "start_at": {"type": "string", "description": "Boshlanish vaqti, 'YYYY-MM-DD HH:MM'"},
                "location": {"type": "string"},
                "notes": {"type": "string"},
                "client_name": {"type": "string", "description": "Mijoz (buyurtmachi) ismi, s'yomka uchun"},
                "client_contact": {"type": "string", "description": "Mijozning Telegram @username yoki telefon raqami (+998...). Berilsa, mijozga s'yomkadan oldin eslatma yuboriladi."},
            },
            "required": ["kind", "title", "start_at"],
        },
    },
    {
        "name": "list_events",
        "description": "Berilgan sanalar oralig'idagi rejalarni ko'rsatadi (ikkala sana ham kiradi).",
        "input_schema": {
            "type": "object",
            "properties": {
                "date_from": {"type": "string", "description": "'YYYY-MM-DD'"},
                "date_to": {"type": "string", "description": "'YYYY-MM-DD'"},
                "include_finished": {"type": "boolean", "description": "Bajarilgan va bekor qilinganlarni ham ko'rsatish"},
            },
            "required": ["date_from", "date_to"],
        },
    },
    {
        "name": "update_event",
        "description": "Mavjud rejani o'zgartiradi. Faqat o'zgaradigan maydonlarni yubor. "
                       "status: done (bajarildi), cancelled (bekor), active.",
        "input_schema": {
            "type": "object",
            "properties": {
                "id": {"type": "integer"},
                "kind": {"type": "string", "enum": list(db.KINDS)},
                "title": {"type": "string"},
                "start_at": {"type": "string"},
                "location": {"type": "string"},
                "notes": {"type": "string"},
                "client_name": {"type": "string", "description": "Mijoz (buyurtmachi) ismi, s'yomka uchun"},
                "client_contact": {"type": "string", "description": "Mijozning Telegram @username yoki telefon raqami (+998...). Berilsa, mijozga s'yomkadan oldin eslatma yuboriladi."},
                "status": {"type": "string", "enum": ["active", "done", "cancelled"]},
            },
            "required": ["id"],
        },
    },
    {
        "name": "delete_event",
        "description": "Rejani butunlay o'chiradi.",
        "input_schema": {
            "type": "object",
            "properties": {"id": {"type": "integer"}},
            "required": ["id"],
        },
    },
    {
        "name": "add_alarm",
        "description": "Uyg'otish budilnigi qo'shadi. Belgilangan vaqtda Telegram orqali qo'ng'iroq qiladi. "
                       "Bir martalik bo'lsa (masalan 'ertaga 7:00') faqat date ber. days ni faqat "
                       "'har kuni', 'har dushanba' kabi takrorlanadigan so'rovda ber. "
                       "Ikkalasi ham berilmasa, eng yaqin shu vaqtga bir martalik qo'yiladi.",
        "input_schema": {
            "type": "object",
            "properties": {
                "time": {"type": "string", "description": "'HH:MM'"},
                "days": {"type": "string", "description": "FAQAT takrorlanadigan budilnik uchun: hafta kunlari raqamlari, 0=dushanba ... 6=yakshanba. Har kuni '0123456', ish kunlari '01234'. Bir martalikda bermang."},
                "date": {"type": "string", "description": "Bir martalik budilnik sanasi: 'YYYY-MM-DD' (masalan ertaga uchun ertangi sana)"},
                "label": {"type": "string"},
            },
            "required": ["time"],
        },
    },
    {
        "name": "send_message",
        "description": "Yordamchi Telegram akkauntidan boshqa odamga (mijozga) xabar yuboradi. "
                       "Faqat egasi aniq so'raganda ishlat.",
        "input_schema": {
            "type": "object",
            "properties": {
                "to": {"type": "string", "description": "@username, +998... raqam yoki avval yozishgan odamning ismi"},
                "text": {"type": "string", "description": "Yuboriladigan xabar matni"},
            },
            "required": ["to", "text"],
        },
    },
    {
        "name": "read_messages",
        "description": "Yordamchi Telegram akkauntiga boshqa odamlar yozgan xabarlarni o'qiydi. "
                       "who bo'sh bo'lsa, oxirgi yozishgan odamlar ro'yxati va o'qilmagan xabarlar soni. "
                       "who berilsa, o'sha odam bilan oxirgi xabarlar.",
        "input_schema": {
            "type": "object",
            "properties": {
                "who": {"type": "string", "description": "Ism, @username yoki telefon raqami (masalan 'Nosir')"},
            },
        },
    },
    {
        "name": "list_alarms",
        "description": "Barcha faol budilniklarni ko'rsatadi.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "delete_alarm",
        "description": "Budilnikni o'chiradi.",
        "input_schema": {
            "type": "object",
            "properties": {"id": {"type": "integer"}},
            "required": ["id"],
        },
    },
]


async def _send_message(to: str, text: str) -> str:
    from .caller import caller

    if caller._client is None:
        return "Yordamchi akkaunt ulanmagan, yubora olmayman"
    to = to.strip()
    plain = to.lstrip("+").replace(" ", "").replace("-", "")
    known = None if (to.startswith("@") or plain.isdigit()) else db.find_contact(to)
    if known:
        await caller.send_to_id(known["tg_id"], text)
        return f"Yuborildi: {known['name'] or known['contact']}"
    if not (to.startswith("@") or plain.isdigit()):
        match = _find_dialog(await _dialogs(), to)
        if match is None:
            return "Bu odam topilmadi. @username yoki telefon raqamini so'ra"
        await caller._client.send_message(match.entity, text)
        db.save_contact(match.id, match.name)
        return f"Yuborildi: {match.name}"
    tg_id = await caller.send_to(to, text)
    db.save_contact(tg_id, contact=to)
    return f"Yuborildi: {to}"


async def _dialogs() -> list:
    """Yordamchi akkauntning shaxsiy suhbatlari (egasi, botlar va Telegram xizmatisiz)."""
    from .caller import caller

    return [d for d in await caller._client.get_dialogs(limit=40)
            if d.is_user and d.id != config.OWNER_ID and not getattr(d.entity, "bot", False)
            and d.id != 777000]


def _find_dialog(dialogs: list, who: str):
    q = who.strip().lstrip("@+").lower()
    words = [w for w in q.replace("aka", "").replace("opa", "").split() if w]
    for d in dialogs:
        hay = " ".join(str(x or "") for x in (d.name, getattr(d.entity, "username", ""),
                                              getattr(d.entity, "phone", ""))).lower()
        if q in hay or (words and all(w in hay for w in words)):
            return d
    return None


async def _read_messages(who: str = "") -> str:
    from . import voice
    from .caller import caller

    if caller._client is None:
        return "Yordamchi akkaunt ulanmagan"
    dialogs = await _dialogs()
    if not who.strip():
        return json.dumps([{"ism": d.name, "username": getattr(d.entity, "username", None),
                            "o'qilmagan": d.unread_count,
                            "oxirgi": (d.message.message or "[ovoz/fayl]")[:100] if d.message else ""}
                           for d in dialogs[:15]], ensure_ascii=False)
    match = _find_dialog(dialogs, who)
    if match is None:
        return f"'{who}' bilan yozishma topilmadi. Bor suhbatlar: " + ", ".join(d.name for d in dialogs[:15])
    lines, voices = [], 0
    async for m in caller._client.iter_messages(match.entity, limit=15):
        text = m.message or ""
        if m.voice and voices < 3 and not m.out:
            voices += 1
            try:
                path = Path(tempfile.mkdtemp()) / "x.ogg"
                await m.download_media(file=str(path))
                text = "[ovozli] " + (await voice.speech_to_text(path) or "")
            except Exception:  # noqa: BLE001
                text = "[ovozli xabar, tushunib bo'lmadi]"
        lines.append(f"{m.date.astimezone(config.TZ):%d.%m %H:%M} "
                     f"{'Yordamchi' if m.out else match.name}: {text or '[rasm/fayl]'}")
    try:
        await caller._client.send_read_acknowledge(match.entity)
    except Exception:  # noqa: BLE001
        pass
    return "\n".join(reversed(lines))


async def _run_tool(name: str, args: dict) -> str:
    try:
        if name == "read_messages":
            return await _read_messages(args.get("who", ""))
        if name == "send_message":
            return await _send_message(args["to"], args["text"])
        if name == "add_event":
            result = db.add_event(**args)
        elif name == "list_events":
            result = db.list_events(**args)
        elif name == "update_event":
            event_id = args.pop("id")
            result = db.update_event(event_id, **args) or "Bunday reja topilmadi"
        elif name == "delete_event":
            result = "o'chirildi" if db.delete_event(args["id"]) else "topilmadi"
        elif name == "add_alarm":
            result = db.add_alarm(**args)
        elif name == "list_alarms":
            result = db.list_alarms()
        elif name == "delete_alarm":
            result = "o'chirildi" if db.delete_alarm(args["id"]) else "topilmadi"
        else:
            return f"Noma'lum vosita: {name}"
    except Exception as e:  # noqa: BLE001 — xatoni modelga qaytaramiz, u tuzatadi
        log.exception("Tool error")
        return f"Xato: {e}"
    return json.dumps(result, ensure_ascii=False, default=str)


WEEKDAYS = ["dushanba", "seshanba", "chorshanba", "payshanba", "juma", "shanba", "yakshanba"]


def _now_note() -> str:
    n = db.now()
    return f"[Hozirgi vaqt: {n:%Y-%m-%d %H:%M}, {WEEKDAYS[n.weekday()]}]"


async def chat(system: str, messages: list[dict]) -> str:
    """Vositalarsiz oddiy javob (mijozlar bilan suhbat uchun). Xato bo'lsa bo'sh qator."""
    if config.AI_PROVIDER == "gemini":
        from . import gemini_ai

        return await gemini_ai.chat(system, messages)
    extra = {}
    if config.CLAUDE_MODEL in FALLBACK_MODELS:
        extra = {"betas": ["server-side-fallback-2026-07-01"], "fallbacks": "default"}
    try:
        response = await client.beta.messages.create(
            model=config.CLAUDE_MODEL,
            max_tokens=4000,
            system=system,
            messages=messages,
            output_config={"effort": config.CLAUDE_EFFORT},
            **extra,
        )
    except anthropic.APIError:
        log.exception("Claude API error (mijoz suhbati)")
        return ""
    if response.stop_reason == "refusal":
        return ""
    return "".join(b.text for b in response.content if b.type == "text").strip()


async def ask(user_text: str, remember: bool = True, provider: str = "") -> str:
    """Foydalanuvchi xabariga javob beradi, kerak bo'lsa rejalarni o'zgartiradi.

    provider bo'sh bo'lsa AI_PROVIDER ishlatiladi (qo'ng'iroqda CALL_AI_PROVIDER beriladi).
    """
    if (provider or config.AI_PROVIDER) == "gemini":
        from . import gemini_ai

        return await gemini_ai.ask(user_text, remember)
    history = db.get_history() if remember else []
    # Vaqt eslatmasi xabar ichiga qo'yiladi, system prompt o'zgarmay keshda qoladi
    messages = history + [{"role": "user", "content": f"{_now_note()}\n{user_text}"}]
    system = SYSTEM_PROMPT.format(name=config.OWNER_NAME) + _knowledge()

    extra = {}
    if config.CLAUDE_MODEL in FALLBACK_MODELS:
        extra = {"betas": ["server-side-fallback-2026-07-01"], "fallbacks": "default"}

    reply = ""
    for _ in range(8):
        try:
            response = await client.beta.messages.create(
                model=config.CLAUDE_MODEL,
                max_tokens=16000,
                system=system,
                tools=TOOLS,
                messages=messages,
                cache_control={"type": "ephemeral"},
                output_config={"effort": config.CLAUDE_EFFORT},
                **extra,
            )
        except anthropic.RateLimitError:
            return "Hozir so'rovlar ko'payib ketdi, bir daqiqadan keyin qayta yozing."
        except anthropic.AuthenticationError:
            return "Claude API kaliti noto'g'ri. .env faylini tekshiring."
        except (anthropic.APIConnectionError, anthropic.InternalServerError):
            return "Claude bilan aloqa uzildi, birozdan keyin qayta urinib ko'ring."
        except anthropic.APIStatusError as e:
            log.error("Claude API error: %s", e)
            detail = getattr(e, "message", "") or str(e)
            if "credit balance" in detail.lower():
                return ("Claude API hisobida pul tugadi. console.anthropic.com → Billing bo'limida "
                        "hisobni to'ldiring, keyin yana yozing.")
            return f"Claude xato qaytardi ({e.status_code}): {detail[:300]}"

        text = "".join(b.text for b in response.content if b.type == "text").strip()
        if text:
            reply = text
        if response.stop_reason == "refusal":
            reply = reply or "Bu so'rovga javob bera olmayman."
            break
        if response.stop_reason != "tool_use":
            break

        messages.append({"role": "assistant", "content": response.content})
        results = [
            {"type": "tool_result", "tool_use_id": b.id, "content": await _run_tool(b.name, dict(b.input))}
            for b in response.content
            if b.type == "tool_use"
        ]
        messages.append({"role": "user", "content": results})

    reply = reply or "Bajarildi."
    if remember:
        db.add_history("user", user_text)
        db.add_history("assistant", reply)
    return reply
