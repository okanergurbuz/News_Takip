"""Feed çekme, ayrıştırma, tarih süzgeci ve dedupe işlemleri."""

import logging
import re
from datetime import datetime, timedelta, timezone
from html.parser import HTMLParser

import feedparser
import httpx

from .models import Article

logger = logging.getLogger(__name__)

# Bazı siteler tanımsız User-Agent'lı istekleri reddettiği için basit bir kimlik veriyoruz
_HEADERS = {"User-Agent": "haber-ozetleyici/1.0 (gunluk RSS bulteni)"}
_TIMEOUT = 20.0
_OZET_KARAKTER_SINIRI = 300


class _EtiketAyiklayici(HTMLParser):
    """HTML etiketlerini atıp yalnızca düz metni biriktirir.

    Satır içi etiketler (<b>, <a>...) metni bölmesin diye parçalar bitişik
    birleştirilir; blok etiketleri (<p>, <br>, <li>...) kelimeler yapışmasın
    diye araya boşluk koyar.
    """

    _BLOK_ETIKETLER = {"p", "div", "br", "li", "ul", "ol", "tr", "td", "h1",
                       "h2", "h3", "h4", "h5", "h6", "blockquote", "section"}

    def __init__(self):
        super().__init__()
        self.parcalar: list[str] = []

    def handle_data(self, data: str) -> None:
        self.parcalar.append(data)

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag in self._BLOK_ETIKETLER:
            self.parcalar.append(" ")

    def handle_endtag(self, tag: str) -> None:
        if tag in self._BLOK_ETIKETLER:
            self.parcalar.append(" ")


def html_temizle(metin: str) -> str:
    """HTML'i düz metne çevirir, boşlukları sadeleştirir, ~300 karaktere kırpar."""
    if not metin:
        return ""
    ayiklayici = _EtiketAyiklayici()
    try:
        ayiklayici.feed(metin)
        duz = "".join(ayiklayici.parcalar)
    except Exception:
        duz = metin
    duz = re.sub(r"\s+", " ", duz).strip()
    if len(duz) > _OZET_KARAKTER_SINIRI:
        duz = duz[:_OZET_KARAKTER_SINIRI].rsplit(" ", 1)[0] + "…"
    return duz


def _girdi_tarihi(girdi) -> datetime | None:
    """Girdinin yayın tarihini UTC datetime'a çevirir; tarih yoksa None döner."""
    for alan in ("published_parsed", "updated_parsed"):
        yapi = girdi.get(alan)
        if yapi:
            return datetime(*yapi[:6], tzinfo=timezone.utc)
    return None


def fetch_all(
    feeds_cfg: list[dict],
    filter_cfg: dict,
    seen: set[str],
) -> tuple[list[Article], set[str]]:
    """Tüm feed'leri tarar; (bültene girecek makaleler, yeni görülen ID'ler) döner.

    - Hatalı feed atlanır, diğerleri işlenmeye devam eder.
    - Yeni ID kümesi, max_per_feed / max_items_total limitleri yüzünden bültene
      giremeyen içerikleri de kapsar; böylece aynı içerik ertesi gün tekrarlanmaz.
    """
    lookback = timedelta(hours=filter_cfg.get("lookback_hours", 24))
    esik = datetime.now(timezone.utc) - lookback
    max_toplam = filter_cfg.get("max_items_total", 30)
    max_feed_basi = filter_cfg.get("max_per_feed", 8)

    secilenler: list[Article] = []
    yeni_idler: set[str] = set()

    with httpx.Client(headers=_HEADERS, timeout=_TIMEOUT, follow_redirects=True) as client:
        for feed in feeds_cfg:
            ad = feed.get("name", feed.get("url", "?"))
            url = feed["url"]
            kategori = feed.get("category", "Genel")

            try:
                yanit = client.get(url)
                yanit.raise_for_status()
                belge = feedparser.parse(yanit.content)
            except Exception as hata:
                # Tek feed'in hatası tüm süreci durdurmasın
                logger.warning("Feed atlandı (%s): %s", ad, hata)
                continue

            feed_makaleleri: list[Article] = []
            for girdi in belge.entries:
                makale_id = girdi.get("id") or girdi.get("link")
                if not makale_id or makale_id in seen or makale_id in yeni_idler:
                    continue

                tarih = _girdi_tarihi(girdi)
                # Tarih süzgeci: pencere dışındakiler alınmaz. Tarihi olmayan
                # girdiler dahil edilir (bir kez görülür, sonra seen'e girer).
                if tarih is not None and tarih < esik:
                    continue

                yeni_idler.add(makale_id)
                feed_makaleleri.append(Article(
                    id=makale_id,
                    title=(girdi.get("title") or "(başlıksız)").strip(),
                    url=girdi.get("link") or makale_id,
                    source=ad,
                    category=kategori,
                    raw_summary=html_temizle(girdi.get("summary") or girdi.get("description") or ""),
                    published=tarih.isoformat() if tarih else None,
                ))

            secilenler.extend(feed_makaleleri[:max_feed_basi])
            logger.info(
                "%s: %d yeni girdi (%d tanesi bülten adayı).",
                ad, len(feed_makaleleri), min(len(feed_makaleleri), max_feed_basi),
            )

    return secilenler[:max_toplam], yeni_idler
