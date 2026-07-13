"""Discord webhook'una kategori bazlı embed'lerle bülten gönderimi.

Discord sınırlarına uyulur: mesaj başına ≤ 10 embed, embed açıklaması ≤ 4096
karakter. Sığmayan içerik yeni embed'lere / mesajlara bölünür ve ardışık
POST'lar arasına ~1 sn beklenir. 429 yanıtında retry_after kadar beklenip
yeniden denenir.
"""

import logging
import time
from datetime import datetime, timezone

import httpx

from .models import Article

logger = logging.getLogger(__name__)

# Discord sınırları (güvenlik payları ile)
_EMBED_ACIKLAMA_SINIRI = 4096
_MESAJ_EMBED_SINIRI = 10
_MESAJ_TOPLAM_KARAKTER = 5500  # mesaj genelindeki 6000 karakter sınırına pay
_BASLIK_SINIRI = 200
_TIMEOUT = 20.0
_DENEME_SAYISI = 5


def _madde(makale: Article) -> str:
    """Tek içeriğin bültendeki satırı: **[Başlık](url)** · Kaynak + özet."""
    # Köşeli parantezler markdown linkini bozacağından dönüştürülür
    baslik = makale.title.replace("[", "(").replace("]", ")")
    if len(baslik) > _BASLIK_SINIRI:
        baslik = baslik[:_BASLIK_SINIRI] + "…"
    ozet = makale.display_summary or "(özet yok)"
    return f"**[{baslik}]({makale.url})** · {makale.source}\n{ozet}\n"


def _embedleri_olustur(makaleler: list[Article], renk: int) -> list[dict]:
    """Kategoriye göre gruplar; her kategori için (gerekirse birden çok) embed üretir."""
    gruplar: dict[str, list[Article]] = {}
    for m in makaleler:  # feed sırası korunur → kategoriler config sırasında çıkar
        gruplar.setdefault(m.category, []).append(m)

    embedler: list[dict] = []
    for kategori, grup in gruplar.items():
        aciklama = ""
        for m in grup:
            satir = _madde(m) + "\n"
            if aciklama and len(aciklama) + len(satir) > _EMBED_ACIKLAMA_SINIRI:
                # Bu embed doldu; aynı kategori için yenisini aç
                embedler.append({"title": kategori, "description": aciklama.strip(), "color": renk})
                aciklama = ""
            aciklama += satir
        if aciklama.strip():
            embedler.append({"title": kategori, "description": aciklama.strip(), "color": renk})
    return embedler


def _mesajlara_bol(embedler: list[dict]) -> list[list[dict]]:
    """Embed'leri Discord'un mesaj başına sınırlarına göre paketler."""
    mesajlar: list[list[dict]] = []
    aktif: list[dict] = []
    karakter = 0
    for e in embedler:
        boyut = len(e.get("title", "")) + len(e.get("description", ""))
        if aktif and (len(aktif) >= _MESAJ_EMBED_SINIRI or karakter + boyut > _MESAJ_TOPLAM_KARAKTER):
            mesajlar.append(aktif)
            aktif, karakter = [], 0
        aktif.append(e)
        karakter += boyut
    if aktif:
        mesajlar.append(aktif)
    return mesajlar


def _gonder(client: httpx.Client, webhook_url: str, govde: dict) -> None:
    """Tek POST; 429 dönerse retry_after kadar bekleyip yeniden dener."""
    for _ in range(_DENEME_SAYISI):
        yanit = client.post(webhook_url, json=govde)
        if yanit.status_code == 429:
            try:
                bekle = float(yanit.json().get("retry_after", 1.0))
            except Exception:
                bekle = float(yanit.headers.get("Retry-After", 1.0))
            logger.info("Discord 429 döndü; %.1f sn bekleniyor...", bekle)
            time.sleep(bekle + 0.5)
            continue
        yanit.raise_for_status()
        return
    raise RuntimeError(f"Discord hız sınırı aşılamadı ({_DENEME_SAYISI} deneme yapıldı).")


def send_digest(makaleler: list[Article], discord_cfg: dict, webhook_url: str) -> None:
    """Bülteni oluşturup webhook'a gönderir. Hiç makale yoksa hiçbir şey yapmaz."""
    if not makaleler:
        return

    embedler = _embedleri_olustur(makaleler, discord_cfg.get("embed_color", 2201331))
    mesajlar = _mesajlara_bol(embedler)
    kullanici = discord_cfg.get("username", "Günlük Bülten")
    tarih = datetime.now(timezone.utc).strftime("%d.%m.%Y")

    with httpx.Client(timeout=_TIMEOUT) as client:
        for i, paket in enumerate(mesajlar):
            govde: dict = {"username": kullanici, "embeds": paket}
            if i == 0:
                govde["content"] = f"📬 **Günlük Bülten — {tarih}** · {len(makaleler)} içerik"
            _gonder(client, webhook_url, govde)
            if i < len(mesajlar) - 1:
                time.sleep(1.0)  # ardışık POST'lar arasında kısa bekleme

    logger.info("Discord'a %d mesajda %d embed gönderildi.", len(mesajlar), len(embedler))
