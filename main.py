"""Günlük haber / blog bülteni — giriş noktası.

Akış:
    config.yaml oku → seen.json yükle → feed'leri tara (süz + dedupe)
    → (opsiyonel) LLM ile Türkçe özet → Discord webhook'una gönder
    → yeni ID'leri seen.json'a yaz.

Gönderim başarısız olursa seen.json güncellenmez; böylece aynı içerikler
bir sonraki çalıştırmada yeniden denenir.
"""

import logging
import os
import sys

import yaml
from dotenv import load_dotenv

from src.discord_notifier import send_digest
from src.feeds import fetch_all
from src.storage import JSONStorage
from src.summarizer import summarize_articles

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("bulten")


def main() -> int:
    load_dotenv()  # yerel geliştirmede .env dosyasını yükler (Actions'ta secrets kullanılır)

    webhook_url = os.environ.get("DISCORD_WEBHOOK_URL")
    if not webhook_url:
        logger.error(
            "DISCORD_WEBHOOK_URL tanımlı değil. Yerelde .env dosyasına, "
            "GitHub'da ise repo secret'larına ekleyin."
        )
        return 1

    with open("config.yaml", encoding="utf-8") as f:
        cfg = yaml.safe_load(f)

    storage = JSONStorage("data/seen.json")
    seen = storage.load_seen()
    logger.info("%d görülmüş ID yüklendi.", len(seen))

    makaleler, yeni_idler = fetch_all(cfg.get("feeds", []), cfg.get("filter", {}), seen)
    if not makaleler:
        logger.info("Yeni içerik yok; bülten gönderilmeyecek.")
        return 0
    logger.info("Bültene %d içerik girecek (%d yeni ID görüldü).", len(makaleler), len(yeni_idler))

    summarize_articles(makaleler, cfg.get("summary", {}))

    send_digest(makaleler, cfg.get("discord", {}), webhook_url)

    # Gönderim başarılı: yeni ID'leri kalıcılaştır
    storage.save_seen(seen | yeni_idler)
    logger.info("seen.json güncellendi.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
