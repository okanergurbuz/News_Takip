"""Görülen içerik ID'lerinin saklanması.

Faz 1: repoya commit'lenen data/seen.json dosyası (JSONStorage).
Faz 2: Supabase (iskelet olarak SupabaseStorage; detay README'de).
"""

import json
from pathlib import Path
from typing import Protocol


class Storage(Protocol):
    """Depolama arayüzü: Faz 2'de Supabase'e geçiş bu arayüzü bozmadan yapılır."""

    def load_seen(self) -> set[str]: ...
    def save_seen(self, ids: set[str]) -> None: ...


class JSONStorage:
    """Görülen ID'leri tek bir JSON dosyasında tutar.

    Dosya sınırsız büyümesin diye en son MAX_ID kadar ID saklanır;
    taşma olursa en eski ID'ler atılır (FIFO).
    """

    MAX_ID = 2000

    def __init__(self, path: str = "data/seen.json"):
        self.path = Path(path)
        self._sirali: list[str] = []  # dosyadaki ekleniş sırası (FIFO kırpma için)

    def load_seen(self) -> set[str]:
        if not self.path.exists():
            self._sirali = []
            return set()
        try:
            veri = json.loads(self.path.read_text(encoding="utf-8"))
            self._sirali = [str(i) for i in veri.get("seen", [])]
        except (json.JSONDecodeError, OSError):
            # Bozuk dosya: sıfırdan başla, süreci çökertme
            self._sirali = []
        return set(self._sirali)

    def save_seen(self, ids: set[str]) -> None:
        # Eski ID'lerin sırası korunur, yeniler sona eklenir; sınır aşılırsa
        # listenin başından (en eskiden) kırpılır.
        eski = [i for i in self._sirali if i in ids]
        yeniler = sorted(ids - set(eski))
        tumu = (eski + yeniler)[-self.MAX_ID:]
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps({"seen": tumu}, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        self._sirali = tumu


class SupabaseStorage:
    """Faz 2 iskeleti: kalıcı ve birikimli depolama için Supabase.

    Tablo şeması:

        create table seen_articles (
            id      text primary key,
            seen_at timestamptz default now()
        );

    Etkinleştirmek için SUPABASE_URL ve SUPABASE_KEY ortam değişkenleri
    tanımlanmalı ve bu sınıf doldurulmalıdır (README → "Faz 2: Supabase").
    """

    def __init__(self, url: str, key: str):
        self.url = url
        self.key = key
        raise NotImplementedError(
            "Faz 2: Supabase entegrasyonu henüz etkin değil. README'deki "
            "'Faz 2: Supabase' bölümüne bakın."
        )

    def load_seen(self) -> set[str]:  # pragma: no cover - iskelet
        raise NotImplementedError

    def save_seen(self, ids: set[str]) -> None:  # pragma: no cover - iskelet
        raise NotImplementedError
