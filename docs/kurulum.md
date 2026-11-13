# Ahirena — kurulum ve çalıştırma (Aşama 1)

Hedef cihaz: Windows 10/11 x64. Kullanıcı düzeyinde çalışır. Yalnızca C++ Build Tools ve NVIDIA sürücüsü yönetici onayı ister.

## Gereksinimler

| Bileşen | Neden | Kurulum |
| --- | --- | --- |
| Ollama | Yerel model motoru | `winget install Ollama.Ollama --scope user` |
| NVIDIA sürücüsü (güncel) | GPU hızlandırma (CUDA veya Vulkan) | nvidia.com sürücü sayfası |
| uv | Python ortamı ve çekirdek bağımlılıkları | `winget install astral-sh.uv --scope user` |
| Node.js LTS | Arayüz derlemesi | nodejs.org |
| Rust (MSVC) | Tauri kabuğu | rustup.rs |
| VS 2022 C++ Build Tools | Rust MSVC bağlayıcısı | `winget install Microsoft.VisualStudio.2022.BuildTools` + "Desktop development with C++" |

Kurumsal AllSigned politikası `.ps1` dosyalarını engeller; bu yüzden yardımcı betikler `.cmd`'dir ve `npm`/`npx` yerine `npm.cmd`/`npx.cmd` çalışır.

## Ollama'yı Ahirena yönetir

Ollama'nın tepsi uygulaması sunucuyu kullanıcının ortam değişkenleriyle başlatır; model klasörü ve bulut ayarı tutarsız olabilir. Bu yüzden Ahirena kendi Ollama örneğini ayrı bir portta başlatır, uygulama kapanınca (çekirdek çökse bile) kapatır. Tepsi uygulamasının kendi sunucusu 11434'te çalışmaya devam edebilir; birbirine karışmazlar.

Ayarlar `%LOCALAPPDATA%\com.ahirena.desktop\config.json` dosyasındadır (ilk açılışta varsayılanlarla oluşur):

```json
{
  "ollama": {
    "manage": true,
    "host": "127.0.0.1:11435",
    "exe": null,
    "models_dir": "D:\\AI\\AhirenaData\\ollama-models",
    "backend": "vulkan"
  }
}
```

| Alan | Anlamı |
| --- | --- |
| `manage` | `true`: Ahirena sunucuyu başlatır. `false`: `host` adresinde zaten çalışan bir Ollama kullanılır. |
| `host` | Yalnızca `127.0.0.1` kabul edilir (yönetilen modda). |
| `exe` | `null` ise PATH ve `%LOCALAPPDATA%\Programs\Ollama` aranır. |
| `models_dir` | `null` ise Ollama varsayılanı (`%USERPROFILE%\.ollama\models`). |
| `backend` | `auto`: Ollama seçer (NVIDIA'da CUDA). `vulkan`: CUDA gizlenir, Vulkan kullanılır. |

Yönetilen sunucu her zaman `OLLAMA_NO_CLOUD=1` ile başlar; günlük `%LOCALAPPDATA%\com.ahirena.desktop\logs\ollama.log` dosyasındadır ve `Ollama cloud disabled: true` satırını içerir.

**Arka uç seçimi cihaza göre ölçülerek yapılmalı** (`scripts\olcum.cmd`). GTX 1650 4 GB + sürücü 621.01 ölçümünde Vulkan, gemma4 e2b'yi tamamen GPU'ya sığdırdı (48 tok/sn); CUDA aynı modelin %37'sini GPU'ya koydu (26 tok/sn).

## Modeller

Modeller yönetilen örnek üzerinden indirilir (sunucu gerekirse geçici başlatılır):

```
scripts\ollama.cmd pull gemma4:e2b-it-qat
scripts\ollama.cmd pull qwen3.5:4b-q4_K_M
scripts\ollama.cmd pull qwen3.5:9b-q4_K_M
scripts\ollama.cmd list
```

Etiketler nicemleme düzeyiyle sabitlenmiştir; `latest` kullanılmaz. `qwen3.5:2b` bu cihazda başkent ve çeviri denetimlerini geçemediği için tutulmaz.

## Komutlar (depo kökünden)

| Komut | İş |
| --- | --- |
| `scripts\test.cmd` | Çekirdek sözleşme testleri, arayüz tip denetimi, Rust testleri |
| `scripts\test.cmd ollama` | Gerçek yerel modelle uçtan uca test (yönetilen sunucu, bulut kapalı, sahipsiz süreç kalmaması) |
| `scripts\olcum.cmd [model ...]` | Hız ve bellek ölçümü; rapor `%LOCALAPPDATA%\com.ahirena.desktop\reports` |
| `scripts\ollama.cmd ...` | Ollama komutlarını Ahirena'nın örneğine karşı çalıştırır |
| `scripts\dev.cmd` | Geliştirme modu |
| `scripts\build.cmd` | Paketli sürüm: `Ahirena_*_x64-setup.exe` (yol komutun sonunda yazılır) |

## Yetenekler (Aşama 2)

Yetenek, `SKILL.md` ve uygulamaya özgü `capabilities.json` içeren bir klasördür. İçe aktarma çekirdek kodunu değiştirmez. Paket hangi aracı istediğini yazar; izin ayrı verilir. Betik çalıştırılmaz. Kaldırma kaydı ve veri klasöründeki paket kopyasını siler; MCP sunucusu da silinebilir. MCP araç izni geri alınabilir. Taslak aday silinince karantina klasörü de kalkar; içe aktarılınca aday `imported` olur. Tor SOCKS denetimi yalnızca yerel bağlantıyı dener, dış siteye gitmez. Ayarlar’daki dürüst durum özeti planlanan özellikleri açıkça gösterir; durum çubuğundan tüm model çalıştırmaları durdurulabilir.

Denetlenmiş araçlar: `clock.now`, `files.read` (seçilen klasörün içi), `sql.query` ve `sql.tables` (yalnızca SELECT, Windows kimliği, parola yok). SQL için çekirdek `pyodbc` taşır; makinede ODBC Driver 17 veya 18 for SQL Server kurulu olmalıdır. MCP sunucusu ayrı süreçte açılır, uygulamanın sırlarını almaz; araç listesi değişince eski izin düşer.

Örnek paket: `examples\skills\saat`. SQL sunucusu `%LOCALAPPDATA%\com.ahirena.desktop\config.json` içindeki `sql` alanındadır.

## Hafıza ve belgeler (Aşama 3)

Hafıza, kullanıcının kaynak belirterek yazdığı kayıttır. Sohbet kendiliğinden hafızaya geçmez. Yeni kayıt eskisinin üzerine yazılmaz; düzeltme ve silme ayrıdır.

Belgeler `.txt` ve `.md` olarak indekslenir. PDF, ofis ve görüntü ayrıştırılmaz. Arama sözcük indeksidir (`fts-1`); vektör indeksi yoktur ve varmış gibi skor üretilmez. Her kayıt bir çalışma alanına aittir, arama başka alanı getirmez. Belge silinince sözcük indeksi de silinir; diskteki dosya durur. Yarım kalan indeks, çekirdek açılışında sürdürülür. Belgeler ekranı açık/başarısız indeks işlerini gösterir; başarısızlar yeniden denenebilir. Model belleğe sığmazsa hata uzak modele geçmeden yerel çözüm önerir. Dosya ve klasör yolları için Windows yerel seçici kullanılabilir (yol elle de yazılabilir).

Sohbet, seçilen çalışma alanındaki hafıza ve belgeleri aday olarak modele verir. Yetkisiz alandaki kayıt gönderilmez. Yanıtın altında kullanılan kaynaklar görünür; kaynakta yoksa kesinlik üretilmez.

## Görevler ve ağ (Aşama 4)

Görev durumları kuyruk, çalışıyor, onay bekliyor, duraklatıldı, bitti, hata, iptal ve uzlaştırma gerektirir. Dosya yazımı her seferinde onay ister; içerik değişince eski onay düşer. Kesinti sonrası çalışan görev `needs_reconciliation` olur; dış işlemin olmadığı varsayılmaz. Zaman ve tekrar Görevler ekranından yazılır; işçi yalnızca çekirdek açıkken çalışır. Bitti/hata/iptal görevleri tek tek veya toplu silinebilir; aktif görev silinmez. Ağ politikası (`offline`, Tor SOCKS) `config.json` içinde `network` alanındadır.

Web okuma izinli alan adına bağlıdır. `127.0.0.1`, özel ağ ve bulut meta veri adresleri kapalıdır; yönlendirmeden sonra hedef yeniden denetlenir. Tor rotası SOCKS dinlemiyorsa iş başarısız biter, doğrudan internete düşülmez. Zamanlanmış görev yalnızca çekirdek açıkken işler; Windows açılış hizmeti kurulmaz. Playwright tarayıcı oturumu bu sürümde kapalıdır.

## Gelişmiş etkileşim (Aşama 5)

Görev dalı checkpoint’ten yeni görev açar; eski yazma onayı taşınmaz. Çevrimdışı oynatma kayıtlı doğrulanmış sonuçları okur, canlı araç çalıştırmaz. Yetenek taslağı karantinada aday üretir; izin ve içe aktarma olmadan etkinleşmez.

Görüntü eki yalnızca vision yetenekli modele gider ve güvenilmeyen kaynaktır. OCR, TTS ve sürekli mikrofon bu sürümde planlandı; whisper.cpp kurulu değilse ses girişi açık görünmez. Sürekli ekran izleme kapalıdır.

## Eğitim (Aşama 6)

Eğitim kaydı hedef davranış, temel model ve veri sürümünü tutar. Çalıştırıcı yokken `start=true` reddedilir; durum `planned` kalır. Adaptör otomatik etkinleşmez; kayıt etkinleştirme Ollama’ya PEFT yüklemez. Konuşmalar modeli eğitmez. Bu cihazda LoRA hattı doğrulanmadan eğitim başlamış gibi gösterilmez.

Ürün kapanışı: Eğitim ekranından holdout değerlendirme kümesi + koşu, ardından kabul matrisi (`/api/acceptance/run`). Matriste `failed=0` ve en az bir değerlendirme koşusu varsa Aşama 6 ürünü kapandı sayılır; LoRA çalıştırıcı planlandı kalır.

Sohbetteki asistan yanıtından **Düzeltme kaydet** ile sorun türü (kaynak, talimat, araç, model, eğitim, diğer) kaydedilir. Bu kayıt modeli eğitmez; Eğitim ekranında aday listesinde görünür. Belge kaynağı ve çıktı/yedek dosyası **Klasörde aç** ile Gezgin’de seçilir.

## Yedek ve dışa aktarım

Ayarlar ekranından SQLite yedeği veya kişisel dışa aktarım alınır. Çıktı `%LOCALAPPDATA%\com.ahirena.desktop\backups` veya `exports` altındadır. Token, parola ve model ağırlığı pakete girmez. Düzeltme adayları da dışa aktarıma girer. Arama indeksleri yeniden kurulabilir. Üretilen dosyalar **Çıktılar** ekranında görünür; diskte yoksa önizleme açılmaz. Veri sürücüsünde ~50 MiB’den az boş alan varsa yedek, dışa aktarım ve belge içe aktarma kontrollü hata verir; uzak modele geçilmez. Ağ politikası Ayarlar ve Görevler’den kaydedilir.

## Veri ve geri dönüş

- Konuşmalar: `%LOCALAPPDATA%\com.ahirena.desktop\data\ahirena.db` (SQLite). Yedek: uygulama kapalıyken dosyayı kopyalamak yeterlidir.
- Günlükler: `%LOCALAPPDATA%\com.ahirena.desktop\logs\core.log`, `ollama.log`.
- Program `%LOCALAPPDATA%\Ahirena` klasörüne, veriler `%LOCALAPPDATA%\com.ahirena.desktop` klasörüne yazılır. Eski sürümlerin `%LOCALAPPDATA%\Ahirena` içindeki verisi ilk açılışta bir kez taşınır.
- Veri klasörünü taşımak: `AHIRENA_DATA_DIR` ortam değişkeni (isteğe bağlı).
- Kaldırma: Windows "Uygulamalar" listesinden Ahirena'yı kaldırın. "Uygulama verisini sil" kutusu işaretlenmezse konuşmalar korunur; işaretlenirse `com.ahirena.desktop` klasörü silinir. Modeller her iki durumda da `models_dir` içinde kalır.
- Ollama'yı geri almak: `winget uninstall Ollama.Ollama`; modeller `models_dir` klasöründe kalır.
