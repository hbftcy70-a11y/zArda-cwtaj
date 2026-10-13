"""Genel HTTP bağlayıcısı.

Resmi bir bot/webhook API'si olan herhangi bir uygulama buraya bağlanabilir:

    POST /message
    Authorization: Bearer <HTTP_API_TOKEN>
    {"chat_id": "kullanici-123", "text": "Merhaba"}
    -> {"reply": "..."}

CALLBACK_URL ayarlıysa, bot kendiliğinden attığı mesajları oraya
{"chat_id": ..., "text": ...} olarak POST eder.
"""

import asyncio
import hmac
import logging
import os

import aiohttp
from aiohttp import web

from core import ChatEngine

log = logging.getLogger("http")


async def run(engine: ChatEngine) -> None:
    api_token = os.environ["HTTP_API_TOKEN"]
    callback_url = os.getenv("CALLBACK_URL")
    host = os.getenv("HTTP_HOST", "0.0.0.0")
    port = int(os.getenv("HTTP_PORT", "8080"))

    async def on_message(request: web.Request) -> web.Response:
        auth = request.headers.get("Authorization", "")
        if not hmac.compare_digest(auth, f"Bearer {api_token}"):
            return web.json_response({"error": "yetkisiz"}, status=401)
        try:
            data = await request.json()
            chat_id, text = str(data["chat_id"]), str(data["text"])
        except (ValueError, KeyError, TypeError):
            return web.json_response(
                {"error": "gövde {\"chat_id\": ..., \"text\": ...} olmalı"}, status=400
            )
        reply = await engine.handle("http", chat_id, text)
        return web.json_response({"reply": reply})

    app = web.Application()
    app.router.add_post("/message", on_message)

    if callback_url:
        session = aiohttp.ClientSession(headers={"Authorization": f"Bearer {api_token}"})

        async def send(chat_id: str, text: str) -> None:
            async with session.post(
                callback_url, json={"chat_id": chat_id, "text": text}
            ) as resp:
                resp.raise_for_status()

        engine.register_sender("http", send)

    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, host, port).start()
    log.info("HTTP API %s:%s adresinde dinliyor", host, port)
    try:
        await asyncio.Event().wait()
    finally:
        if callback_url:
            await session.close()
        await runner.cleanup()
