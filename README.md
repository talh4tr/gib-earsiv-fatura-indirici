# GİB e-Arşiv Fatura İndirici ve PDF Dönüştürücü

<div align="center">
  <!-- Ziyaretçi Sayacı -->
  <img src="https://komarev.com/ghpvc/?username=talh4tr&repo=gib-earsiv-fatura-indirici&label=Ziyaretçi&color=3b82f6&style=for-the-badge" alt="Ziyaretçi Sayacı">

  <!-- Repo Rozetleri -->
  <img src="https://img.shields.io/github/stars/talh4tr/gib-earsiv-fatura-indirici?style=for-the-badge&color=f43f5e" alt="Stars">
  <img src="https://img.shields.io/github/forks/talh4tr/gib-earsiv-fatura-indirici?style=for-the-badge&color=10b981" alt="Forks">
  <img src="https://img.shields.io/github/license/talh4tr/gib-earsiv-fatura-indirici?style=for-the-badge&color=8b5cf6" alt="License">
</div>

---

**GİB e-Arşiv Portal** kullanıcıları için geliştirilmiş, faturalarınızı otomatik olarak çeken, Playwright entegrasyonu ile aslına uygun PDF formatına dönüştüren ve organize bir ZIP paketi olarak arşivlemenizi sağlayan yüksek performanslı bir otomasyon sistemidir.

## 🚀 Temel Özellikler

* **Hızlı ve Toplu İndirme:** GİB e-Arşiv portalı üzerinden belirlediğiniz tarih aralığındaki tüm faturaları tek seferde indirin.
* **Haftalık Bölme Protokolü:** GİB sistem limitlerine takılmamak ve veri kaybını önlemek için geniş tarih aralıklarını akıllıca 7 günlük alt parçalara böler.
* **Eş Zamanlı Render (Concurrency):** Playwright Chromium kullanarak aynı anda 4 faturayı birden izole context'lerde işleyerek PDF'e dönüştürür.
* **İptal Filigranı:** İptal edilmiş faturalarınızın düzenini bozmadan, üzerine otomatik olarak şeffaf "İPTAL EDİLMİŞTİR" filigranı ekler.
* **Akıllı Raporlama:** İndirilemeyen veya sistem hatası veren faturaları `_INDIRILEMEYEN_FATURALAR_RAPORU.txt` dosyasıyla raporlar, süreç takibini kolaylaştırır.

## 🛠️ Kurulum ve Başlatma

### Gereksinimler

* Python 3.10+
* PHP 8.1+ & Composer
* Node.js (Playwright bağımlılıkları için)

### Adım 1: Bağımlılıkların Kurulması

Terminalde proje dizinine giderek kurulumları başlatın:

```bash
# PHP paketlerini yükleyin
composer install

# Python kütüphanelerini yükleyin
pip install fastapi uvicorn pydantic playwright beautifulsoup4

# Playwright tarayıcı sürücülerini indirin
playwright install chromium
```

### Adım 2: Çalıştırma

Uygulamayı FastAPI üzerinden başlatın:

```bash
python -m uvicorn main:app --host 127.0.0.1 --port 8000
```

Tarayıcınızdan `http://127.0.0.1:8000` adresine giderek arayüze ulaşabilirsiniz.

## 💡 Neden Bu Aracı Kullanmalısınız?

Muhasebe süreçlerini dijitalleştirmek, fatura arşivlemeyi otomatize etmek ve GİB portalının yavaşlığıyla vakit kaybetmek istemeyen işletmeler ve geliştiriciler için mükemmel bir çözüm.

## 📄 Lisans ve Kullanım Şartları

Bu proje PolyForm Noncommercial 1.0.0 lisansı altında korunmaktadır.

Kişisel ve eğitim amaçlı kullanım serbesttir.

**TİCARİ AMAÇLA KULLANILMASI, SATILMASI VEYA ÜCRETLİ SERVİS (SaaS) OLARAK SUNULMASI KESİNLİKLE YASAKTIR.**

## ⚠️ Yasal Uyarı (DMCA)

Bu projenin kodları veya mimarisi izinsiz olarak ticari bir yapıya (ücretli panel, SaaS, entegrasyon hizmeti vb.) dahil edildiği takdirde, ihlali gerçekleştiren kurumun sunucu sağlayıcısına (Hosting/Cloud Provider) derhal DMCA Yayından Kaldırma (Takedown) ihtarnamesi gönderilecektir. Emeğe saygı gösterin.

## 👨‍💻 Geliştirici Bilgileri

**Talha Muhammed Çiftci**

* GitHub: [@talh4tr](https://github.com/talh4tr)
* Telegram: [@talh4ciftci](https://t.me/talh4ciftci)
* E-Posta: talhamuhammedciftci@gmail.com

**Anahtar Kelimeler:** GİB e-Arşiv fatura indirme, e-fatura otomasyonu, fatura PDF dönüştürücü, e-Arşiv portal, GİB otomatik fatura çekme, Playwright fatura