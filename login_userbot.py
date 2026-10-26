"""Qo'ng'iroq qiladigan ikkinchi Telegram akkauntga bir marta kirish.

Ishga tushiring:  python login_userbot.py
Telefon raqam va Telegram yuborgan kodni so'raydi. Keyin sessiya data/ papkasida saqlanadi.
"""
import asyncio

from telethon import TelegramClient

from yordamchi import config


async def main() -> None:
    if not (config.USERBOT_API_ID and config.USERBOT_API_HASH):
        raise SystemExit(".env faylida USERBOT_API_ID va USERBOT_API_HASH ni to'ldiring")
    client = TelegramClient(config.USERBOT_SESSION, int(config.USERBOT_API_ID), config.USERBOT_API_HASH)
    await client.start()
    me = await client.get_me()
    print(f"Tayyor! Qo'ng'iroq akkaunti: {me.first_name} (+{me.phone})")
    print("Muhim: shu akkauntdan asosiy akkauntingizga bir marta oddiy xabar yozing, "
          "aks holda Telegram qo'ng'iroqqa ruxsat bermasligi mumkin.")
    await client.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
