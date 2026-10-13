"""Discord bağlayıcısı (resmi bot API).

Özel mesajlara (DM) her zaman, sunucu kanallarında ise yalnızca bot
etiketlendiğinde cevap verir. Kendiliğinden mesajları sadece DM'de atar.
"""

import os

import discord

from core import ChatEngine

DISCORD_LIMIT = 2000


def _chunks(text: str) -> list[str]:
    return [text[i : i + DISCORD_LIMIT] for i in range(0, len(text), DISCORD_LIMIT)]


async def run(engine: ChatEngine) -> None:
    intents = discord.Intents.default()
    intents.message_content = True
    client = discord.Client(intents=intents)

    @client.event
    async def on_message(message: discord.Message) -> None:
        if message.author.bot:
            return
        is_dm = isinstance(message.channel, discord.DMChannel)
        if not is_dm and client.user not in message.mentions:
            return
        text = message.content.replace(f"<@{client.user.id}>", "").strip()
        if not text:
            return
        async with message.channel.typing():
            reply = await engine.handle(
                "discord", str(message.channel.id), text, allow_nudge=is_dm
            )
        for part in _chunks(reply):
            await message.channel.send(part)

    async def send(chat_id: str, text: str) -> None:
        channel = client.get_channel(int(chat_id)) or await client.fetch_channel(int(chat_id))
        for part in _chunks(text):
            await channel.send(part)

    engine.register_sender("discord", send)
    await client.start(os.environ["DISCORD_BOT_TOKEN"])
