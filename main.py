"""Botu bir ya da birden fazla platformda başlatır.

    python main.py telegram
    python main.py discord http
"""

import asyncio
import logging
import sys

from dotenv import load_dotenv

load_dotenv()
logging.basicConfig(
    format="%(asctime)s %(levelname)s %(name)s: %(message)s", level=logging.INFO
)

from core import MODEL, ChatEngine  # noqa: E402  (.env yüklendikten sonra)

PLATFORMS = ("telegram", "discord", "http")


async def main(platforms: list[str]) -> None:
    engine = ChatEngine()
    runners = []
    for name in platforms:
        if name == "telegram":
            from adapters import telegram_adapter as adapter
        elif name == "discord":
            from adapters import discord_adapter as adapter
        else:
            from adapters import http_adapter as adapter
        runners.append(adapter.run(engine))
    logging.info("Başlatılıyor: %s (model: %s)", ", ".join(platforms), MODEL)
    await asyncio.gather(*runners)


if __name__ == "__main__":
    chosen = sys.argv[1:] or ["telegram"]
    unknown = [p for p in chosen if p not in PLATFORMS]
    if unknown:
        sys.exit(f"Bilinmeyen platform: {', '.join(unknown)}. Seçenekler: {', '.join(PLATFORMS)}")
    try:
        asyncio.run(main(chosen))
    except KeyboardInterrupt:
        pass
