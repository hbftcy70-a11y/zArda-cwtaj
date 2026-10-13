# Claude Sohbet Botu

Gelen mesajlara Claude ile cevap veren ve sohbeti sürekli canlı tutan bir sohbet botu. Tek bir sohbet çekirdeği (`core.py`) birden fazla platforma bağlanır.

## Ne yapar?

- Her mesaja doyurucu bir cevap verir ve cevabı bir soru ya da yeni bir konuyla bitirir.
- Her sohbetin geçmişini hatırlar (`history.json`), önceki konulara geri döner.
- Kullanıcı `NUDGE_MINUTES` dakika yazmazsa kendiliğinden yeni bir mesaj atar (en fazla `MAX_NUDGES` kez üst üste).
- Kullanıcı sohbeti bitirmek isterse ısrar etmez; "bot musun?" diye sorulursa yapay zeka olduğunu söyler.

Komutlar (her platformda `/` ya da `!` ile): `start`, `sifirla` (geçmişi siler), `sessiz` (kendiliğinden mesajı kapatır).

## Kurulum

```bash
python3 -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env             # .env dosyasını doldur
```

Bir ya da birkaç platformu aynı anda başlat:

```bash
python main.py telegram
python main.py discord
python main.py http
python main.py telegram discord http
```

## Platformlar

| Platform | Gerekenler |
|---|---|
| Telegram | @BotFather'dan `/newbot` ile token → `TELEGRAM_BOT_TOKEN` |
| Discord | discord.com/developers'da uygulama + bot oluştur, **Message Content Intent**'i aç, token → `DISCORD_BOT_TOKEN`. DM'lere her zaman, sunucularda etiketlenince cevap verir. |
| HTTP API | `HTTP_API_TOKEN` belirle. Resmi bot/webhook desteği olan her uygulama bağlanabilir (aşağıya bak). |

### HTTP API ile başka bir uygulamaya bağlama

Uygulamanın resmi webhook'u gelen mesajı şu şekilde bota iletir:

```bash
curl -X POST http://SUNUCU:8080/message \
  -H "Authorization: Bearer $HTTP_API_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"chat_id": "kullanici-123", "text": "Merhaba"}'
# -> {"reply": "..."}
```

`reply` değerini uygulamanın resmi mesaj gönderme API'siyle kullanıcıya gönder. `CALLBACK_URL` ayarlıysa bot, kendiliğinden attığı mesajları o adrese `{"chat_id": ..., "text": ...}` olarak POST eder (aynı `Authorization` başlığıyla).

### Yeni platform ekleme

`adapters/` altına `run(engine)` fonksiyonu olan bir dosya ekle: gelen mesajı `await engine.handle("platform", chat_id, text)` ile işle, dönen cevabı gönder ve kendiliğinden mesajlar için `engine.register_sender("platform", gonder)` çağır. Sonra `main.py` içindeki `PLATFORMS` listesine ekle.

Bağlayıcılar yalnızca platformların resmi bot API'lerini kullanmalı. Kişisel hesabı ekran otomasyonuyla ya da uygulamayı taklit ederek yönetmek platform kurallarına aykırıdır ve hesabın kapatılmasına yol açabilir.

## Kişiliği değiştirme

`.env` içindeki `BOT_NAME` ve `BOT_PERSONA` değerlerini değiştir. Daha ayrıntılı kurallar için `core.py` içindeki `SYSTEM_PROMPT` metnini düzenle.
