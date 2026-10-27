# Shaxsiy AI yordamchi

Telegram ichida ishlaydigan shaxsiy yordamchi:

- S'yomka, montaj va Instagram post rejalarini ovozli yoki yozma xabardan tushunib, bazaga yozadi.
- S'yomkadan **1 kun**, **1 soat** va **30 daqiqa** oldin eslatadi, keyin «🚗 Yo'lga chiqdim» tugmasi
  bosilmaguncha har 5 daqiqada eslatib turadi.
- Montaj va post uchun 1 soat oldin va vaqtida eslatadi.
- Budilnik vaqtida ikkinchi Telegram akkaunt orqali **qo'ng'iroq qilib** uyg'otadi, «☀️ Turdim»
  bosilmaguncha har 3 daqiqada qayta qo'ng'iroq qiladi, keyin bugungi rejani ovoz bilan aytib beradi.
- Ovozli xabarga erkak ovozida (o'zbekcha) ovozli javob qaytaradi.
- Montaj, marketing va biznes bo'yicha maslahat beradi, `knowledge/` papkadagi materiallarga tayanadi.

## Qanday ishlaydi

| Qism | Nima ishlatiladi | Narxi |
|---|---|---|
| Interfeys | Telegram bot (aiogram) | bepul |
| "Miya" | Claude API | ~$1–10/oy (modelga qarab) |
| Ovozni matnga | ElevenLabs Scribe (zaxira: Whisper, Groq orqali) | bepul tarif: 10 000 kredit/oy |
| Matnni ovozga | ElevenLabs Eleven v4 (zaxira: Microsoft `uz-UZ-SardorNeural`) | bepul tarif, kerak bo'lsa $6/oy |
| Qo'ng'iroq | Ikkinchi Telegram akkaunt + py-tgcalls | bepul |
| Server | Hetzner CX22 yoki shunga o'xshash VPS | ~$5–7/oy |
| Rejalar bazasi | SQLite (server ichida) | bepul |

## O'rnatish

### 1. Telegram bot yarating
1. Telegramda [@BotFather](https://t.me/BotFather) ga `/newbot` yozing, nom bering.
2. Bergan **token**ni saqlab qo'ying (`BOT_TOKEN`).
3. [@userinfobot](https://t.me/userinfobot) ga yozing va o'z **ID** raqamingizni oling (`OWNER_ID`).

### 2. Claude API kaliti
1. [console.anthropic.com](https://console.anthropic.com) da ro'yxatdan o'ting.
2. Billing bo'limida $5–10 to'ldiring.
3. API Keys → Create Key (`ANTHROPIC_API_KEY`).

### 3. ElevenLabs kaliti (ovoz uchun)
1. [elevenlabs.io](https://elevenlabs.io) da ro'yxatdan o'ting (bepul tarif yetadi).
2. Profil → **API Keys** → Create (`ELEVEN_API_KEY`).
3. Xohlasangiz **Voices** bo'limidan yoqqan erkak ovozni tanlab, ID sini `ELEVEN_VOICE_ID` ga yozing.

Kredit tugasa, bot o'zi bepul Microsoft ovoziga o'tadi. Zaxira sifatida
[console.groq.com](https://console.groq.com) dan bepul kalit olib, `STT_API_KEY` ga yozib qo'ysangiz,
ovozni tanish ham to'xtab qolmaydi.

### 4. Server
[Hetzner Cloud](https://www.hetzner.com/cloud) da **CX22** (yoki eng arzon) server oling, tizim: **Ubuntu 24.04**.
Serverga kiring va:

```bash
git clone https://github.com/<login>/<repo>.git /opt/ai-yordamchi
cd /opt/ai-yordamchi
bash deploy/install.sh
nano .env          # 1–3 qadamdagi kalitlarni yozing
systemctl restart ai-yordamchi
```

Botga `/start` yozing. Javob bersa, hammasi ishlayapti.

### 5. Qo'ng'iroq qiladigan ikkinchi akkaunt
1. Ikkinchi raqam bilan Telegram akkaunt oching.
2. [my.telegram.org](https://my.telegram.org) ga shu raqam bilan kiring → **API development tools** →
   `api_id` va `api_hash` ni oling va `.env` ga `USERBOT_API_ID`, `USERBOT_API_HASH` qilib yozing.
3. Serverda bir marta kiring (telefon raqam va kod so'raydi):
   ```bash
   cd /opt/ai-yordamchi && venv/bin/python login_userbot.py
   systemctl restart ai-yordamchi
   ```
4. Ikkinchi akkauntdan asosiy akkauntingizga bitta xabar yozing va uni kontaktlarga qo'shing.
5. Botga `/test_qongiroq` yozing, telefon jiringlashi kerak.

Agar bu qadam bajarilmasa, bot qo'ng'iroq o'rniga ovozli xabarlar bilan uyg'otadi.

## Foydalanish

Oddiy gapiring yoki yozing:
- «Ertaga soat 10 da Chilonzorda kafe uchun s'yomka bor»
- «Shu s'yomkaning montajini qachon qilay?»
- «Bugungi rejalarim qanaqa?»
- «Har kuni ish kunlari 6:30 da uyg'ot»
- «Reelsning birinchi 3 soniyasini qanday qilsam ko'proq ko'rishadi?»

Buyruqlar: `/bugun`, `/ertaga`, `/hafta`, `/budilnik`, `/yangi`, `/test_qongiroq`.

## Sozlash

- Model: `.env` da `CLAUDE_MODEL`. `claude-opus-5-5` eng aqlli maslahatchi, `claude-haiku-5-5` ancha arzon.
- Eslatma vaqtlari: `yordamchi/config.py` dagi `SHOOT_REMINDERS`, `TASK_REMINDERS` va boshqalar.
- Bilim bazasi: `knowledge/` papkasiga `.md`/`.txt` fayl qo'shing (qarang: `knowledge/README.md`).

## Foydali buyruqlar (serverda)

```bash
systemctl status ai-yordamchi      # ishlayaptimi
journalctl -u ai-yordamchi -f      # loglar
cd /opt/ai-yordamchi && git pull && systemctl restart ai-yordamchi   # yangilash
```
