"""Ikkinchi Telegram akkauntga (yordamchi akkaunt) bir marta kirish.

Ishga tushiring:  python login_userbot.py
Telefon raqam va Telegram yuborgan kodni so'raydi. Keyin sessiya data/ papkasida saqlanadi.
"""
import asyncio
from pathlib import Path

from telethon import TelegramClient

from yordamchi import config

SESSION_FILE = Path(config.USERBOT_SESSION + ".session")


def ask_phone() -> str:
    while True:
        phone = input("Yangi akkauntning telefon raqami (+998... ko'rinishida): ").strip().replace(" ", "")
        if phone.startswith("+") and phone[1:].isdigit():
            return phone
        print("  Bu yerga bot tokeni emas, telefon raqam yoziladi. Masalan: +998901234567")


async def main() -> None:
    if not (config.USERBOT_API_ID and config.USERBOT_API_HASH):
        raise SystemExit(".env faylida USERBOT_API_ID va USERBOT_API_HASH ni to'ldiring")
    client = TelegramClient(config.USERBOT_SESSION, int(config.USERBOT_API_ID), config.USERBOT_API_HASH)
    await client.connect()
    if await client.is_user_authorized() and (await client.get_me()).bot:
        # Avval xato bilan bot ulangan bo'lsa, eski sessiyani o'chirib, qaytadan kiramiz
        await client.disconnect()
        SESSION_FILE.unlink(missing_ok=True)
        client = TelegramClient(config.USERBOT_SESSION, int(config.USERBOT_API_ID), config.USERBOT_API_HASH)
    await client.start(phone=ask_phone)
    me = await client.get_me()
    await client.disconnect()
    if me.bot:
        SESSION_FILE.unlink(missing_ok=True)
        raise SystemExit("Bu bot ekan. Qaytadan ishga tushiring va yangi akkaunt telefon raqamini yozing.")
    print(f"Tayyor! Yordamchi akkaunt: {me.first_name} (+{me.phone})")
    print("Endi asosiy akkauntingizdan shu akkauntga bir marta oddiy xabar yozing.")


if __name__ == "__main__":
    asyncio.run(main())
