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
scripts\ollama.cmd pull qwen3.5:2b-q4_K_M
scripts\ollama.cmd list
```

Etiketler nicemleme düzeyiyle sabitlenmiştir; `latest` kullanılmaz.

## Komutlar (depo kökünden)

| Komut | İş |
| --- | --- |
| `scripts\test.cmd` | Çekirdek sözleşme testleri, arayüz tip denetimi, Rust testleri |
| `scripts\test.cmd ollama` | Gerçek yerel modelle uçtan uca test (yönetilen sunucu, bulut kapalı, sahipsiz süreç kalmaması) |
| `scripts\olcum.cmd [model ...]` | Hız ve bellek ölçümü; rapor `%LOCALAPPDATA%\com.ahirena.desktop\reports` |
| `scripts\ollama.cmd ...` | Ollama komutlarını Ahirena'nın örneğine karşı çalıştırır |
| `scripts\dev.cmd` | Geliştirme modu |
| `scripts\build.cmd` | Paketli sürüm: `Ahirena_*_x64-setup.exe` (yol komutun sonunda yazılır) |

## Veri ve geri dönüş

- Konuşmalar: `%LOCALAPPDATA%\com.ahirena.desktop\data\ahirena.db` (SQLite). Yedek: uygulama kapalıyken dosyayı kopyalamak yeterlidir.
- Günlükler: `%LOCALAPPDATA%\com.ahirena.desktop\logs\core.log`, `ollama.log`.
- Program `%LOCALAPPDATA%\Ahirena` klasörüne, veriler `%LOCALAPPDATA%\com.ahirena.desktop` klasörüne yazılır. Eski sürümlerin `%LOCALAPPDATA%\Ahirena` içindeki verisi ilk açılışta bir kez taşınır.
- Veri klasörünü taşımak: `AHIRENA_DATA_DIR` ortam değişkeni (isteğe bağlı).
- Kaldırma: Windows "Uygulamalar" listesinden Ahirena'yı kaldırın. "Uygulama verisini sil" kutusu işaretlenmezse konuşmalar korunur; işaretlenirse `com.ahirena.desktop` klasörü silinir. Modeller her iki durumda da `models_dir` içinde kalır.
- Ollama'yı geri almak: `winget uninstall Ollama.Ollama`; modeller `models_dir` klasöründe kalır.
