"""LLM ile kısa Türkçe özet üretimi (SDK'sız, düz HTTP).

İki sağlayıcı desteklenir (config.yaml → summary.provider):
  - "gemini"    : Google Gemini API (ücretsiz katmanı vardır) — GEMINI_API_KEY gerekir
  - "anthropic" : Anthropic Claude API — ANTHROPIC_API_KEY gerekir

LLM özeti tamamen opsiyonel bir katmandır: summary.enabled=false ise ya da
seçili sağlayıcının API anahtarı tanımlı değilse hiç API çağrısı yapılmaz ve
sistem feed'in ham özetiyle eksiksiz çalışır.
"""

import logging
import os
import time

import httpx

from .models import Article

logger = logging.getLogger(__name__)

_ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"
_ANTHROPIC_SURUM = "2023-06-01"
_GEMINI_KOK = "https://generativelanguage.googleapis.com/v1beta"

_GIRDI_SINIRI = 1500  # token tasarrufu: girdi metni bu uzunlukta kırpılır
_TIMEOUT = 30.0
# Gemini ücretsiz katmanının dakikadaki istek sınırına (RPM) takılmamak için
# ardışık çağrılar arasında beklenir (~15 RPM ≈ 4 sn aralık).
_GEMINI_ARALIK = 4.0

_ANAHTAR_ADLARI = {
    "anthropic": "ANTHROPIC_API_KEY",
    "gemini": "GEMINI_API_KEY",
}
# Gemini'de sürümlü adlar (örn. gemini-2.5-flash-lite) zamanla emekliye ayrılıp
# 404 verebildiği için her zaman güncel modele işaret eden "-latest" takma adı kullanılır.
_VARSAYILAN_MODELLER = {
    "anthropic": "claude-haiku-4-5-20251001",
    "gemini": "gemini-flash-lite-latest",
}


def _anthropic_ozet(client: httpx.Client, api_key: str, model: str,
                    system: str, metin: str) -> str | None:
    """Tek makale için Anthropic Messages API çağrısı; özet üretilemezse None."""
    yanit = client.post(
        _ANTHROPIC_URL,
        headers={
            "x-api-key": api_key,
            "anthropic-version": _ANTHROPIC_SURUM,
            "content-type": "application/json",
        },
        json={
            "model": model,
            "max_tokens": 300,
            "system": system,
            "messages": [{"role": "user", "content": metin}],
        },
    )
    yanit.raise_for_status()
    veri = yanit.json()

    # stop_reason == "refusal": model içeriği reddetti → ham özete düş
    if veri.get("stop_reason") == "refusal":
        return None

    # content bir blok listesidir; type == "text" bloklarını birleştir
    return "".join(
        blok.get("text", "")
        for blok in veri.get("content", [])
        if blok.get("type") == "text"
    ).strip() or None


def _gemini_ozet(client: httpx.Client, api_key: str, model: str,
                 system: str, metin: str) -> str | None:
    """Tek makale için Google Gemini generateContent çağrısı; üretilemezse None."""
    yanit = client.post(
        f"{_GEMINI_KOK}/models/{model}:generateContent",
        headers={
            "x-goog-api-key": api_key,
            "content-type": "application/json",
        },
        json={
            "system_instruction": {"parts": [{"text": system}]},
            "contents": [{"role": "user", "parts": [{"text": metin}]}],
            "generationConfig": {"maxOutputTokens": 1024},
        },
    )
    yanit.raise_for_status()
    veri = yanit.json()

    # Aday yoksa içerik güvenlik filtresine takılmıştır → ham özete düş
    adaylar = veri.get("candidates") or []
    if not adaylar:
        return None
    parcalar = adaylar[0].get("content", {}).get("parts", [])
    return "".join(p.get("text", "") for p in parcalar if "text" in p).strip() or None


def _dene(cagri, *args) -> str | None:
    """Çağrıyı yapar; 429 (hız sınırı) dönerse bir kez bekleyip yeniden dener."""
    try:
        return cagri(*args)
    except httpx.HTTPStatusError as hata:
        if hata.response.status_code == 429:
            logger.info("Hız sınırı (429); 20 sn bekleyip yeniden denenecek.")
            time.sleep(20)
            return cagri(*args)
        raise


def summarize_articles(makaleler: list[Article], ozet_cfg: dict) -> None:
    """Makalelere yerinde (in-place) LLM özeti ekler.

    Herhangi bir makale için hata/timeout/red oluşursa o makale sessizce
    ham özetine düşer; süreç asla çökmez.
    """
    if not ozet_cfg.get("enabled", False):
        logger.info("LLM özeti kapalı; ham özetler kullanılacak.")
        return

    saglayici = (ozet_cfg.get("provider") or "anthropic").lower()
    anahtar_adi = _ANAHTAR_ADLARI.get(saglayici)
    if anahtar_adi is None:
        logger.warning("Bilinmeyen özet sağlayıcısı: %r; ham özetler kullanılacak.", saglayici)
        return

    api_key = os.environ.get(anahtar_adi)
    if not api_key:
        logger.info("%s tanımlı değil; ham özetler kullanılacak.", anahtar_adi)
        return

    model = ozet_cfg.get("model") or _VARSAYILAN_MODELLER[saglayici]
    limit = ozet_cfg.get("max_articles", 25)  # maliyet/kota kontrolü
    dil = ozet_cfg.get("language", "Türkçe")
    cumle = ozet_cfg.get("sentences", "2-3")

    system = (
        f"Sen bir haber özetleyicisin. Verilen başlık ve metni {cumle} cümlelik "
        f"akıcı {dil} özete indir. Abartı ve tıklama tuzağı kullanma; sadece özü ver. "
        "Sadece özeti yaz, ön/son söz ekleme."
    )
    cagri = _gemini_ozet if saglayici == "gemini" else _anthropic_ozet

    sayac = 0
    with httpx.Client(timeout=_TIMEOUT) as client:
        # API çağrıları sıralı yapılır (paralellik yok: basit ve hız sınırına saygılı)
        for i, makale in enumerate(makaleler[:limit]):
            if saglayici == "gemini" and i > 0:
                time.sleep(_GEMINI_ARALIK)

            metin = (
                f"Başlık: {makale.title}\n\n"
                f"Metin: {makale.raw_summary[:_GIRDI_SINIRI]}"
            )
            try:
                ozet = _dene(cagri, client, api_key, model, system, metin)
                if ozet:
                    makale.llm_summary = ozet
                    sayac += 1
                else:
                    logger.info(
                        "Özet üretilmedi (red/filtre), ham özet kullanılacak: %s",
                        makale.title,
                    )
            except Exception as hata:
                # Hata/timeout: bu makale için sessizce ham özete düş
                logger.warning("Özet alınamadı (%s): %s", makale.title, hata)

    logger.info("%d makale için LLM özeti üretildi (sağlayıcı: %s, model: %s).",
                sayac, saglayici, model)
