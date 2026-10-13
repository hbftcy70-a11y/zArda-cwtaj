"""Platformdan bağımsız sohbet motoru.

Bağlayıcılar (Telegram, Discord, HTTP ...) gelen mesajı `engine.handle()`'a
verir, dönen cevabı kendi platformunda gönderir. Kendiliğinden atılan
mesajlar için bağlayıcı `engine.register_sender()` ile bir gönderme
fonksiyonu kaydeder.
"""

import asyncio
import json
import logging
import os
from pathlib import Path
from typing import Awaitable, Callable

import anthropic

log = logging.getLogger("core")

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

SYSTEM_PROMPT = f"""Senin adın {BOT_NAME}. İnsanlarla mesajlaşan bir yapay zeka asistanısın.
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

WELCOME = (
    f"Merhaba! Ben {BOT_NAME}, yapay zeka destekli bir sohbet botuyum. 🤖\n"
    "Bana istediğin her şeyi yazabilirsin.\n\n"
    "/sifirla - sohbeti baştan başlatır\n"
    "/sessiz - kendiliğimden mesaj atmayı bırakırım"
)
FALLBACK_REPLY = "Şu an kafam biraz karıştı 😅 Birazdan tekrar yazar mısın?"

Sender = Callable[[str, str], Awaitable[None]]


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


class ChatEngine:
    def __init__(self) -> None:
        self.client = anthropic.AsyncAnthropic()
        self.histories: dict[str, list[dict]] = self._load()
        self.nudge_counts: dict[str, int] = {}
        self.muted: set[str] = set()
        self.senders: dict[str, Sender] = {}
        self.nudge_tasks: dict[str, asyncio.Task] = {}

    # --- Kayıt ------------------------------------------------------------

    def register_sender(self, platform: str, sender: Sender) -> None:
        """`sender(chat_id, text)`: bu platformda kendiliğinden mesaj gönderir."""
        self.senders[platform] = sender

    # --- Geçmiş -----------------------------------------------------------

    def _load(self) -> dict[str, list[dict]]:
        if HISTORY_FILE.exists():
            try:
                return json.loads(HISTORY_FILE.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                log.warning("%s okunamadı, boş geçmişle başlanıyor", HISTORY_FILE)
        return {}

    def _save(self) -> None:
        HISTORY_FILE.write_text(
            json.dumps(self.histories, ensure_ascii=False, indent=1), encoding="utf-8"
        )

    def _append(self, key: str, role: str, text: str) -> None:
        history = self.histories.setdefault(key, [])
        history.append({"role": role, "content": text})
        del history[:-MAX_HISTORY]
        self._save()

    # --- Claude -----------------------------------------------------------

    async def _ask_claude(self, messages: list[dict]) -> str | None:
        try:
            response = await self.client.beta.messages.create(
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

    # --- Mesaj işleme -----------------------------------------------------

    async def handle(
        self, platform: str, chat_id: str, text: str, allow_nudge: bool = True
    ) -> str:
        """Gelen mesaja cevap döndürür. Komutları (/start, /sifirla, /sessiz) da işler."""
        key = f"{platform}:{chat_id}"
        command = text.strip().lower()
        if command[:1] in ("/", "!"):
            reply = self._command(key, command[1:].split("@")[0])
            if reply is not None:
                return reply

        self._append(key, "user", text)
        self.nudge_counts[key] = 0
        reply = await self._ask_claude(build_messages(self.histories[key]))
        if not reply:
            return FALLBACK_REPLY
        self._append(key, "assistant", reply)
        if allow_nudge:
            self._schedule_nudge(key)
        return reply

    def _command(self, key: str, name: str) -> str | None:
        if name == "start":
            self.muted.discard(key)
            return WELCOME
        if name == "sifirla":
            self.histories.pop(key, None)
            self.nudge_counts.pop(key, None)
            self._save()
            return "Sohbet geçmişini sildim, baştan başlayalım!"
        if name == "sessiz":
            self.muted.add(key)
            self._cancel_nudge(key)
            return "Tamam, sen yazmadıkça mesaj atmayacağım. Tekrar açmak için /start yaz."
        return None

    # --- Kendiliğinden mesaj ----------------------------------------------

    def _cancel_nudge(self, key: str) -> None:
        task = self.nudge_tasks.pop(key, None)
        if task and task is not asyncio.current_task():
            task.cancel()

    def _schedule_nudge(self, key: str) -> None:
        self._cancel_nudge(key)
        platform = key.split(":", 1)[0]
        if (
            NUDGE_MINUTES <= 0
            or platform not in self.senders
            or key in self.muted
            or self.nudge_counts.get(key, 0) >= MAX_NUDGES
        ):
            return
        self.nudge_tasks[key] = asyncio.create_task(self._nudge_later(key))

    async def _nudge_later(self, key: str) -> None:
        await asyncio.sleep(NUDGE_MINUTES * 60)
        messages = build_messages(self.histories.get(key, []))
        if not messages:
            return
        # Not geçmişe kaydedilmez, yalnızca bu istekte kullanılır.
        if messages[-1]["role"] == "user":
            messages[-1]["content"] += "\n\n" + NUDGE_NOTE
        else:
            messages.append({"role": "user", "content": NUDGE_NOTE})

        reply = await self._ask_claude(messages)
        if not reply:
            return
        platform, chat_id = key.split(":", 1)
        try:
            await self.senders[platform](chat_id, reply)
        except Exception:
            log.exception("%s için kendiliğinden mesaj gönderilemedi", key)
            return
        self._append(key, "assistant", reply)
        self.nudge_counts[key] = self.nudge_counts.get(key, 0) + 1
        self._schedule_nudge(key)
