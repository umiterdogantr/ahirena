# Ahirena – ajan çalışma kuralları

Ürün şartnamesi: `Cursor_Kisisel_AI_Teknik_Sartname.md`. Aşama sırası ve kabul koşulları oradadır; onaylanmamış aşamaya geçme.

## Ortam
- Windows 10 Pro 22H2, i9-12900KF, 32 GB RAM, GTX 1650 (4 GB VRAM).
- Grup İlkesi (UserPolicy) PowerShell AllSigned: `.ps1` dosyaları çalışmaz. Ajan kabuğu Cursor "Legacy Terminal Tool" ile Windows PowerShell 5.1'dir: `&&` yok, `;` kullan. `npm` yerine `npm.cmd`, `npx` yerine `npx.cmd` çağır. Projede `.ps1` başlatıcı kullanma, `.cmd` veya `.exe` kullan.
- Çalışma verisi depo dışında tutulur. Uygulama verisi (SQLite, loglar, ölçüm raporları, `config.json`): `%LOCALAPPDATA%\com.ahirena.desktop`, `AHIRENA_DATA_DIR` ile değiştirilebilir. C: sürücüsünde yer az olduğu için büyük dosyalar D: altında: Ollama modelleri `D:\AI\AhirenaData\ollama-models`, kurulum dosyaları `D:\AI\AhirenaData\installers`.
- Ollama'yı çekirdek yönetir (`ollama_runtime.py`): `config.json` ayarlarıyla 127.0.0.1:11435'te, `OLLAMA_NO_CLOUD=1` ile başlatır; Windows iş nesnesiyle çekirdekle birlikte kapanır. Tepsi uygulamasının 11434'teki sunucusuna güvenme. Model indirme: `scripts\ollama.cmd pull <etiket>`.
- Bu cihazda GPU arka ucu Vulkan (sürücü 621.01 ile ölçüldü; CUDA gemma4'ü GPU'ya sığdıramadı). Arka uç değişikliğinden önce `scripts\olcum.cmd` ile ölç.
- Makinede kurumsal uç nokta güvenlik yazılımı var: imzasız yeni `.exe` dosyalarını karantinaya alabilir. Kurulum ve proje klasörleri için BT istisnası tanımlıdır. Güvenlik yazılımını devre dışı bırakmaya veya atlatmaya çalışma; istisna/imza kullanıcı veya BT kararıdır.
- Ajan kabuğunda `CARGO_TARGET_DIR` farklı bir önbellek klasörüne işaret edebilir; derleme çıktısını orada ara.

## Değişmez kurallar
- Yerel çalışma esastır. Uzak sağlayıcıya sessiz geçiş yok; uzak model yalnızca kullanıcı açınca kullanılır.
- Model, araç ve depolama erişimi adaptör arkasındadır; uygulama mantığına sağlayıcı SDK'sı yayılmaz.
- SQL Server / ERP: varsayılan salt okunur. Yazma işlemi her seferinde açık kullanıcı onayı ister.
- Sahte yanıt, boş işlem gövdesi veya çalışmayan aktif düğme yok. Planlanan özellik "planlandı" olarak görünür.
- Sırlar, kişisel veri, model ağırlıkları ve eğitim verisi depoya girmez.
- Yeni bağımlılıkta lisans, bakım durumu ve Windows uyumunu kontrol et; sürümleri kilit dosyasına sabitle.
- Çalıştırılmamış veya başarısız testi geçmiş gibi raporlama.
- Kullanıcıya yanıtlar Türkçe.
