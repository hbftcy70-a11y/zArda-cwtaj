"""Telegram bağlayıcısı (resmi Bot API)."""

import asyncio
import os

from telegram import Update
from telegram.ext import Application, ContextTypes, MessageHandler, filters

from core import ChatEngine


async def run(engine: ChatEngine) -> None:
    app = Application.builder().token(os.environ["TELEGRAM_BOT_TOKEN"]).build()

    async def on_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        chat_id = update.effective_chat.id
        await context.bot.send_chat_action(chat_id=chat_id, action="typing")
        reply = await engine.handle("telegram", str(chat_id), update.message.text)
        await update.message.reply_text(reply)

    async def send(chat_id: str, text: str) -> None:
        await app.bot.send_message(chat_id=int(chat_id), text=text)

    app.add_handler(MessageHandler(filters.TEXT, on_message))
    engine.register_sender("telegram", send)

    async with app:
        await app.start()
        await app.updater.start_polling()
        try:
            await asyncio.Event().wait()
        finally:
            await app.updater.stop()
            await app.stop()
