# Claude Sohbet Botu (Telegram)

Gelen mesajlara Claude ile cevap veren ve sohbeti sürekli canlı tutan bir Telegram botu.

## Ne yapar?

- Her mesaja doyurucu bir cevap verir ve cevabı bir soru ya da yeni bir konuyla bitirir.
- Her sohbetin geçmişini hatırlar (`history.json`), önceki konulara geri döner.
- Kullanıcı `NUDGE_MINUTES` dakika yazmazsa bot kendiliğinden yeni bir mesaj atar. Bunu en fazla `MAX_NUDGES` kez üst üste yapar.
- Kullanıcı sohbeti bitirmek isterse ısrar etmez. "Bot musun?" diye sorulursa yapay zeka olduğunu söyler.

Komutlar: `/start`, `/sifirla` (geçmişi siler), `/sessiz` (kendiliğinden mesaj atmayı kapatır).

## Kurulum

1. Telegram'da **@BotFather**'a `/newbot` yaz ve token'ı al.
2. https://console.anthropic.com adresinden bir API anahtarı al.
3. Kur ve çalıştır:

```bash
python3 -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env             # .env dosyasına token ve anahtarı yaz
python bot.py
```

Bot, `python bot.py` çalıştığı sürece aktif kalır. 7/24 çalışması için bir sunucuda (VPS, Railway, Render vb.) çalıştırabilirsin.

## Kişiliği değiştirme

`.env` dosyasındaki `BOT_NAME` ve `BOT_PERSONA` değerlerini değiştir. Daha ayrıntılı kurallar için `bot.py` içindeki `SYSTEM_PROMPT` metnini düzenleyebilirsin.
