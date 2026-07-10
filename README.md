# GİB Portal Arşiv - GİB E-Arşiv Fatura İndirme Portalı

GİB E-Arşiv Portalına bağlanarak belirlediğiniz tarih aralığındaki imzalı veya iptal edilmiş faturaları otomatik olarak çeken, Playwright entegrasyonu ile fatura düzenini bozmadan aslına uygun A4 PDF'e dönüştüren ve bunları organize bir ZIP paketi olarak sunan açık kaynaklı bir sistemdir.

## 🚀 Özellikler
* **Haftalık Bölme Protokolü:** GİB'in sessizce veri kırpma riskine karşı geniş tarih aralıklarını otomatik olarak 7 günlük alt parçalara böler.
* **Eş Zamanlı Render (Concurrency):** Playwright Chromium kullanarak aynı anda 4 faturayı birden izole context'lerde hızlıca PDF'e dönüştürür.
* **İptal Filigranı:** İptal edilen faturaların arkasına faturanın orijinal görsel düzenini bozmayan yarı şeffaf "İPTAL EDİLMİŞTİR" filigranı basar.
* **Hata Raporlama:** İndirilemeyen veya GİB kaynaklı hata dönen faturalar için ZIP içerisine otomatik bir rapor (`_INDIRILEMEYEN_FATURALAR_RAPORU.txt`) ekler.

## 🛠️ Kurulum ve Çalıştırma

### Gereksinimler
* Python 3.10+
* PHP 8.1+ (ve Composer)
* Node.js (Playwright bağımlılıkları için)

### 1. PHP Bağımlılıklarının Kurulması
Proje kök dizininde terminali açın ve PHP paketlerini yükleyin:
```bash
composer install
```

### 2. Python Bağımlılıklarının Kurulması
Gerekli Python kütüphanelerini yükleyin:

```bash
pip install fastapi uvicorn pydantic playwright beautifulsoup4
```

Playwright tarayıcı sürücülerini indirin:

```bash
playwright install chromium
```

### 3. Uygulamayı Başlatma
FastAPI sunucusunu ayağa kaldırın:

```bash
python -m uvicorn main:app --host 127.0.0.1 --port 8000
```

Tarayıcınızdan http://127.0.0.1:8000 adresine giderek arayüze erişebilirsiniz.

👨‍💻 Geliştirici Bilgileri
Bu proje Talha Muhammed Çiftci tarafından geliştirilmiştir.

GitHub: @talh4tr

Telegram: @talh4ciftci

E-Posta: talhamuhammedciftci@gmail.com

📄 Lisans
Bu proje [PolyForm Noncommercial 1.0.0](LICENSE) lisansı altında korunmaktadır. Kişisel ve eğitim amaçlı kullanım serbesttir; ancak TİCARİ AMAÇLA KULLANILMASI VE SATILMASI KESİNLİKLE YASAKTIR.

### ⚠️ Yasal Uyarı ve DMCA (Telif Hakkı İhlali)
Bu projenin kodları veya mimarisi izinsiz olarak ticari bir yapıya (ücretli panel, SaaS, entegrasyon hizmeti vb.) dahil edildiği takdirde, ihlali gerçekleştiren kurumun sunucu sağlayıcısına (Hosting/Cloud Provider) ve ilgili platformlara derhal **DMCA Yayından Kaldırma (Takedown)** ihtarnamesi çekilecektir. Emeğe saygı gösterin ve ticari işleriniz için kendi çözümlerinizi üretin.
