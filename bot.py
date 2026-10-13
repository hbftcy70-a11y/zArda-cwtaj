"""Claude destekli Telegram sohbet botu.

Gelen mesajlara cevap verir, her cevabı sohbeti devam ettirecek şekilde
bitirir ve kullanıcı bir süre sessiz kalırsa kendiliğinden yeni bir mesaj atar.
"""

import json
import logging
import os
from pathlib import Path

import anthropic
from dotenv import load_dotenv
from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

load_dotenv()

TELEGRAM_BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
MODEL = os.getenv("CLAUDE_MODEL", "claude-opus-5-5")
BOT_NAME = os.getenv("BOT_NAME", "Asistan")
BOT_PERSONA = os.getenv(
    "BOT_PERSONA",
    "Samimi, meraklı ve esprili bir sohbet arkadaşısın.",
)
NUDGE_MINUTES = float(os.getenv("NUDGE_MINUTES", "30"))
MAX_NUDGES = int(os.getenv("MAX_NUDGES", "2"))
MAX_HISTORY = int(os.getenv("MAX_HISTORY", "40"))
HISTORY_FILE = Path(os.getenv("HISTORY_FILE", "history.json"))

SYSTEM_PROMPT = f"""Senin adın {BOT_NAME}. Telegram üzerinden insanlarla sohbet eden bir yapay zeka asistanısın.
{BOT_PERSONA}

Amacın sohbeti canlı tutmak ve karşındaki kişinin konuşmaya devam etmek istemesini sağlamak:
- Karşındaki kişinin yazdıklarıyla gerçekten ilgilen; detayları hatırla ve sonra geri dön.
- Cevaplarını doyurucu yaz: kendi düşünceni, küçük bir anekdot ya da ilginç bir bilgi ekle. Ama mesajı okunmaz hale getirecek kadar uzatma; birkaç kısa paragrafı geçme.
- Her mesajı sohbeti ilerletecek bir şeyle bitir: açık uçlu bir soru, yeni bir konu önerisi ya da kişinin fikrini isteyen bir yorum.
- Konu tıkandığında kişinin daha önce bahsettiği ilgi alanlarına geçiş yap.
- Karşındaki kişi hangi dilde yazıyorsa o dilde, doğal ve günlük bir üslupla yaz. Emoji kullanabilirsin ama abartma.
- Kişi sohbeti bitirmek istediğini açıkça söylerse ısrar etme, kibarca vedalaş.
- Biri sana bot ya da yapay zeka olup olmadığını sorarsa dürüstçe yapay zeka olduğunu söyle. Gerçek bir insan olduğunu iddia etme.
- Para, şifre, kişisel belge gibi hassas bilgiler isteme."""

NUDGE_NOTE = (
    "[Sistem notu: Kullanıcı bir süredir cevap vermedi. Ona sohbeti yeniden "
    "başlatacak kısa ve doğal bir mesaj yaz. Önceki konulardan birine dön ya da "
    "ilgisini çekebilecek yeni bir şey sor. Bu notu mesajında anma.]"
)

logging.basicConfig(
    format="%(asctime)s %(levelname)s %(name)s: %(message)s", level=logging.INFO
)
log = logging.getLogger("bot")

client = anthropic.AsyncAnthropic()


# --- Sohbet geçmişi -------------------------------------------------------

def load_histories() -> dict[str, list[dict]]:
    if HISTORY_FILE.exists():
        try:
            return json.loads(HISTORY_FILE.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            log.warning("%s okunamadı, boş geçmişle başlanıyor", HISTORY_FILE)
    return {}


histories = load_histories()
nudge_counts: dict[str, int] = {}
muted: set[str] = set()


def save_histories() -> None:
    HISTORY_FILE.write_text(
        json.dumps(histories, ensure_ascii=False, indent=1), encoding="utf-8"
    )


def append(chat_id: str, role: str, text: str) -> None:
    history = histories.setdefault(chat_id, [])
    history.append({"role": role, "content": text})
    del history[:-MAX_HISTORY]
    save_histories()


def build_messages(history: list[dict]) -> list[dict]:
    """Ardışık aynı roldeki mesajları birleştirir ve listeyi kullanıcıyla başlatır."""
    messages: list[dict] = []
    for msg in history:
        if messages and messages[-1]["role"] == msg["role"]:
            messages[-1]["content"] += "\n\n" + msg["content"]
        else:
            messages.append(dict(msg))
    while messages and messages[0]["role"] != "user":
        messages.pop(0)
    return messages


# --- Claude ---------------------------------------------------------------

async def ask_claude(messages: list[dict]) -> str | None:
    try:
        response = await client.beta.messages.create(
            model=MODEL,
            max_tokens=16000,
            system=SYSTEM_PROMPT,
            messages=messages,
            output_config={"effort": "low"},
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
        )
    except anthropic.RateLimitError:
        log.warning("Claude API hız sınırına takıldı")
        return None
    except anthropic.APIStatusError as e:
        log.error("Claude API hatası (%s): %s", e.status_code, e.message)
        return None
    except anthropic.APIConnectionError:
        log.error("Claude API'ye bağlanılamadı")
        return None

    if response.stop_reason == "refusal":
        log.info("Claude bu isteği reddetti")
        return None
    text = "".join(b.text for b in response.content if b.type == "text").strip()
    return text or None


# --- Telegram -------------------------------------------------------------

def schedule_nudge(context: ContextTypes.DEFAULT_TYPE, chat_id: str) -> None:
    if context.job_queue is None or NUDGE_MINUTES <= 0:
        return
    for job in context.job_queue.get_jobs_by_name(chat_id):
        job.schedule_removal()
    if chat_id in muted or nudge_counts.get(chat_id, 0) >= MAX_NUDGES:
        return
    context.job_queue.run_once(
        send_nudge, NUDGE_MINUTES * 60, chat_id=int(chat_id), name=chat_id
    )


async def send_nudge(context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = str(context.job.chat_id)
    messages = build_messages(histories.get(chat_id, []))
    if not messages:
        return
    # Not geçmişe kaydedilmez, yalnızca bu istekte kullanılır.
    if messages[-1]["role"] == "user":
        messages[-1]["content"] += "\n\n" + NUDGE_NOTE
    else:
        messages.append({"role": "user", "content": NUDGE_NOTE})

    reply = await ask_claude(messages)
    if not reply:
        return
    await context.bot.send_message(chat_id=int(chat_id), text=reply)
    append(chat_id, "assistant", reply)
    nudge_counts[chat_id] = nudge_counts.get(chat_id, 0) + 1
    schedule_nudge(context, chat_id)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = str(update.effective_chat.id)
    muted.discard(chat_id)
    await update.message.reply_text(
        f"Merhaba! Ben {BOT_NAME}, yapay zeka destekli bir sohbet botuyum. 🤖\n"
        "Bana istediğin her şeyi yazabilirsin.\n\n"
        "/sifirla - sohbeti baştan başlatır\n"
        "/sessiz - kendiliğimden mesaj atmayı bırakırım"
    )


async def reset(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = str(update.effective_chat.id)
    histories.pop(chat_id, None)
    nudge_counts.pop(chat_id, None)
    save_histories()
    await update.message.reply_text("Sohbet geçmişini sildim, baştan başlayalım!")


async def mute(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = str(update.effective_chat.id)
    muted.add(chat_id)
    schedule_nudge(context, chat_id)  # bekleyen hatırlatmayı iptal eder
    await update.message.reply_text(
        "Tamam, sen yazmadıkça mesaj atmayacağım. Tekrar açmak için /start yaz."
    )


async def on_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = str(update.effective_chat.id)
    append(chat_id, "user", update.message.text)
    nudge_counts[chat_id] = 0

    await context.bot.send_chat_action(chat_id=int(chat_id), action="typing")
    reply = await ask_claude(build_messages(histories[chat_id]))
    if not reply:
        reply = "Şu an kafam biraz karıştı 😅 Birazdan tekrar yazar mısın?"
        await update.message.reply_text(reply)
        return

    await update.message.reply_text(reply)
    append(chat_id, "assistant", reply)
    schedule_nudge(context, chat_id)


def main() -> None:
    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("sifirla", reset))
    app.add_handler(CommandHandler("sessiz", mute))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_message))
    log.info("Bot çalışıyor (model: %s)", MODEL)
    app.run_polling()


if __name__ == "__main__":
    main()
