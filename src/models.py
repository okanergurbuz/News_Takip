"""Veri modeli: bültendeki tek bir içeriği temsil eden Article dataclass'ı."""

from dataclasses import dataclass


@dataclass
class Article:
    id: str                        # guid ya da link (dedupe bu alanla yapılır)
    title: str
    url: str
    source: str                    # örn. "The Verge"
    category: str                  # örn. "Teknoloji"
    raw_summary: str               # feed'den gelen ham özet (HTML'den arındırılmış)
    published: str | None          # ISO 8601 tarih ya da None
    llm_summary: str | None = None # LLM özeti (üretilmişse)

    @property
    def display_summary(self) -> str:
        """Bültende gösterilecek özet: LLM özeti varsa o, yoksa ham özet."""
        return self.llm_summary or self.raw_summary
