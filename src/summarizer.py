"""Anthropic Messages API ile kısa Türkçe özet üretimi (SDK'sız, düz HTTP).

LLM özeti tamamen opsiyonel bir katmandır: summary.enabled=false ise ya da
ANTHROPIC_API_KEY tanımlı değilse hiç API çağrısı yapılmaz ve sistem feed'in
ham özetiyle eksiksiz çalışır.
"""

import logging
import os

import httpx

from .models import Article

logger = logging.getLogger(__name__)

_API_URL = "https://api.anthropic.com/v1/messages"
_API_SURUMU = "2023-06-01"
_GIRDI_SINIRI = 1500  # token tasarrufu: girdi metni bu uzunlukta kırpılır
_TIMEOUT = 30.0


def summarize_articles(makaleler: list[Article], ozet_cfg: dict) -> None:
    """Makalelere yerinde (in-place) LLM özeti ekler.

    Herhangi bir makale için hata/timeout/refusal oluşursa o makale sessizce
    ham özetine düşer; süreç asla çökmez.
    """
    if not ozet_cfg.get("enabled", False):
        logger.info("LLM özeti kapalı; ham özetler kullanılacak.")
        return

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        logger.info("ANTHROPIC_API_KEY tanımlı değil; ham özetler kullanılacak.")
        return

    model = ozet_cfg.get("model", "claude-haiku-4-5-20251001")
    limit = ozet_cfg.get("max_articles", 25)  # maliyet kontrolü
    dil = ozet_cfg.get("language", "Türkçe")
    cumle = ozet_cfg.get("sentences", "2-3")

    system = (
        f"Sen bir haber özetleyicisin. Verilen başlık ve metni {cumle} cümlelik "
        f"akıcı {dil} özete indir. Abartı ve tıklama tuzağı kullanma; sadece özü ver. "
        "Sadece özeti yaz, ön/son söz ekleme."
    )
    headers = {
        "x-api-key": api_key,
        "anthropic-version": _API_SURUMU,
        "content-type": "application/json",
    }

    sayac = 0
    with httpx.Client(timeout=_TIMEOUT) as client:
        # API çağrıları sıralı yapılır (paralellik yok: basit ve hız sınırına saygılı)
        for makale in makaleler[:limit]:
            govde = {
                "model": model,
                "max_tokens": 300,
                "system": system,
                "messages": [
                    {
                        "role": "user",
                        "content": (
                            f"Başlık: {makale.title}\n\n"
                            f"Metin: {makale.raw_summary[:_GIRDI_SINIRI]}"
                        ),
                    }
                ],
            }
            try:
                yanit = client.post(_API_URL, headers=headers, json=govde)
                yanit.raise_for_status()
                veri = yanit.json()

                # stop_reason == "refusal": model içeriği reddetti → ham özete düş
                if veri.get("stop_reason") == "refusal":
                    logger.info("Özet reddedildi, ham özet kullanılacak: %s", makale.title)
                    continue

                # content bir blok listesidir; type == "text" bloklarını birleştir
                metin = "".join(
                    blok.get("text", "")
                    for blok in veri.get("content", [])
                    if blok.get("type") == "text"
                ).strip()
                if metin:
                    makale.llm_summary = metin
                    sayac += 1
            except Exception as hata:
                # Hata/timeout: bu makale için sessizce ham özete düş
                logger.warning("Özet alınamadı (%s): %s", makale.title, hata)

    logger.info("%d makale için LLM özeti üretildi.", sayac)
