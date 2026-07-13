# 📬 Haber / Blog Özetleyici Bülten

Takip ettiğiniz siteleri (RSS/Atom feed'leri üzerinden) **günde bir kez** tarayıp
yeni yayınlanan içerikleri toplayan; her içerik için isteğe bağlı olarak Claude ile
**2-3 cümlelik Türkçe özet** üreten ve sonucu bir **Discord kanalına** düzenli bülten
olarak gönderen, **sunucusuz** (GitHub Actions üzerinde çalışan) bir sistem.

## Nasıl çalışır?

```
GitHub Actions (cron, her gün 06:00 UTC = İzmir 09:00)
        │
        ▼
   main.py çalışır
        ├─ config.yaml oku (feed listesi, ayarlar)
        ├─ data/seen.json'dan görülen ID'leri yükle
        ├─ Her feed'i çek ve ayrıştır (son 24 saat + dedupe)
        ├─ (opsiyonel) Claude ile 2-3 cümlelik Türkçe özet
        ├─ Kategoriye göre gruplu Discord embed'leri oluştur ve gönder
        └─ Yeni ID'leri seen.json'a ekle → Actions geri commit'ler
```

## Kurulum

### 1. Depoyu GitHub'a aktarın

Bu klasörü bir GitHub reposu olarak yayınlayın (workflow'un çalışması için
`.github/workflows/digest.yml` repo kökünde olmalıdır — bu depoda öyledir).

```bash
git init
git add .
git commit -m "ilk sürüm"
git remote add origin <repo-url>
git push -u origin main
```

### 2. Discord webhook'u oluşturun

Discord'da hedef kanal → **Kanal Ayarları → Entegrasyonlar → Webhook'lar →
Yeni Webhook** → adresi kopyalayın.

### 3. GitHub secret'larını ekleyin

Repo → **Settings → Secrets and variables → Actions → New repository secret**:

| Secret | Zorunlu mu? | Açıklama |
|---|---|---|
| `DISCORD_WEBHOOK_URL` | ✅ Evet | Discord webhook adresi |
| `ANTHROPIC_API_KEY` | ❌ Hayır | LLM özeti için. Yoksa/`summary.enabled: false` ise bülten feed'lerin kendi özetleriyle gönderilir |

### 4. Bitti 🎉

Workflow her gün **06:00 UTC**'de otomatik çalışır. Beklemeden denemek için:
repo → **Actions → gunluk-bulten → Run workflow**.

> **Saat dilimi notu:** GitHub Actions cron'u **UTC** ile çalışır. `0 6 * * *`
> ifadesi İzmir'de (UTC+3) **09:00**'a denk gelir. Farklı bir saat isterseniz
> `.github/workflows/digest.yml` içindeki cron ifadesini UTC'ye göre düzenleyin.

## Yerelde çalıştırma

```bash
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env             # DISCORD_WEBHOOK_URL ve (ops.) ANTHROPIC_API_KEY doldurun
python main.py
```

`.env` dosyası `python-dotenv` ile otomatik yüklenir ve `.gitignore`'dadır —
sırlar asla commit'lenmez.

## Yapılandırma (`config.yaml`)

Tüm ayarlar `config.yaml`'dan okunur; kodda gömülü feed/eşik yoktur.

- **`feeds`** — takip edilecek siteler. Yeni satır ekleyerek feed ekleyin,
  başına `#` koyarak devre dışı bırakın. `category` alanı bültendeki
  gruplamayı belirler; kategori adına emoji koyarsanız embed başlığında
  görünür (ör. `category: "🔋 EV / Otomotiv"`).
- **`filter.lookback_hours`** — son kaç saatte yayınlanan içerikler alınır (varsayılan 24).
- **`filter.max_items_total` / `max_per_feed`** — bülten boyut sınırları.
- **`summary.enabled`** — `false` yapılırsa LLM hiç çağrılmaz.
- **`summary.model`** — `claude-haiku-4-5-20251001` (hızlı ve ucuz; bu iş için doğru tercih).
- **`summary.max_articles`** — maliyet kontrolü: en fazla kaç içeriğe özet çıkarılır;
  fazlası ham özetle gönderilir.
- **`discord.username` / `embed_color`** — bültenin görünümü.

## Dosya yapısı

```
├── main.py                     # Giriş noktası, akışı orkestra eder
├── config.yaml                 # Feed listesi + ayarlar
├── requirements.txt
├── .env.example                # Ortam değişkeni şablonu
├── data/
│   └── seen.json               # Görülen içerik ID'leri (Actions commit'ler)
├── src/
│   ├── feeds.py                # Feed çekme + ayrıştırma + tarih/dedupe süzgeci
│   ├── summarizer.py           # Anthropic API ile Türkçe özet (düz HTTP)
│   ├── discord_notifier.py     # Embed oluşturma + webhook POST
│   ├── storage.py              # Storage arayüzü + JSONStorage (+ Supabase iskeleti)
│   └── models.py               # dataclass: Article
└── .github/workflows/digest.yml  # Günlük cron workflow'u
```

## Davranış notları (yapılan makul varsayımlar)

- **Dedupe:** İçerik kimliği olarak girdinin `id`/`guid`'i, yoksa `link`'i
  kullanılır. `data/seen.json` en son **2000 ID**'yi FIFO düzeninde tutar;
  sınırsız büyümez.
- **Limit dışı kalan içerikler de "görüldü" sayılır:** `max_per_feed` /
  `max_items_total` nedeniyle bültene giremeyen içerikler seen'e yazılır ki
  ertesi gün bülteni şişirmesinler.
- **Gönderim başarısız olursa** `seen.json` güncellenmez; içerikler bir sonraki
  çalıştırmada yeniden denenir.
- **Hiç yeni içerik yoksa** bülten gönderilmez (sessizce çıkılır).
- **Tarihi olmayan girdiler** ilk görüşte dahil edilir, sonra seen'e girer.
- **Bir feed hata verirse** (ağ, 4xx/5xx, bozuk XML) o feed atlanır, kalanlar
  işlenir; süreç çökmez.
- **Discord sınırları:** mesaj başına ≤ 10 embed, embed açıklaması ≤ 4096
  karakter. Sığmayan bülten birden fazla mesaja bölünür (arada ~1 sn bekleme);
  429 yanıtında `retry_after` kadar beklenip yeniden denenir.
- **LLM reddi (`stop_reason: "refusal"`)** ya da API hatası durumunda o içerik
  feed'in ham özetiyle gönderilir.

## Faz 2: Supabase (opsiyonel, henüz etkin değil)

`src/storage.py` içindeki `Storage` protokolü sayesinde JSON depolama,
Faz 1'i bozmadan Supabase ile değiştirilebilir. `SupabaseStorage` iskeleti
hazırdır; etkinleştirmek için:

1. Supabase projesinde tabloyu oluşturun:

   ```sql
   create table seen_articles (
       id      text primary key,
       seen_at timestamptz default now()
   );
   ```

2. `SUPABASE_URL` ve `SUPABASE_KEY` secret'larını ekleyin.
3. `SupabaseStorage.load_seen` / `save_seen` metodlarını Supabase REST
   uçlarına (`/rest/v1/seen_articles`) `httpx` ile bağlayın ve `main.py`'de
   `JSONStorage` yerine kullanın.

Böylece geçmiş silinmeden birikir ve ileride arşiv/dashboard kurulabilir.

## Gelecek fikirleri

- RSS'i olmayan siteler için scraping (`httpx` + `selectolax`/`beautifulsoup4`).
- Supabase'e geçiş + Next.js/Tailwind arşiv sayfası (aranabilir geçmiş bülten).
- Kategori bazında ayrı Discord kanalı/thread.
- Anahtar kelime filtresi (ör. sadece "Ioniq", "EV şarj" geçen haberler).
- Günün en önemli 3 haberini LLM'e seçtirip başa koyma.
- E-posta seçeneği (notifier arayüzünü soyutlama).
- Haftalık "en çok okunan/öne çıkan" derlemesi.
