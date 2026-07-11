# ==============================================================================
#  GİB Portal Arşiv - Fatura İndirme ve PDF Dönüştürme Aracı
#  Developed by: talh4tr (https://github.com/talh4tr)
#  License: MIT
# ==============================================================================
import os
import re
import json
import time
import shutil
import tempfile
import zipfile
import asyncio
import urllib.parse
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException, BackgroundTasks, Request
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from typing import Optional, List
from playwright.async_api import async_playwright
from bs4 import BeautifulSoup

# Setup Logs Directory
project_dir = os.path.dirname(os.path.abspath(__file__))
logs_dir = os.path.join(project_dir, "logs")
os.makedirs(logs_dir, exist_ok=True)
log_file_path = os.path.join(logs_dir, "gib_arsiv.log")

# Tüm geçici dosyaları tek bir yerde topla (yetim dosya temizliği için taranabilir)
TEMP_ROOT = os.path.join(project_dir, "temp")
os.makedirs(TEMP_ROOT, exist_ok=True)

# PDF render işlemi için eş zamanlılık sınırı (Playwright render limiti)
PDF_RENDER_CONCURRENCY = 4

# Setup logging formatter and logger
logger = logging.getLogger("gib_arsiv")
logger.setLevel(logging.ERROR)

class CustomFormatter(logging.Formatter):
    def format(self, record):
        fatura_no = getattr(record, 'fatura_no', 'Sistem')
        asctime = self.formatTime(record, self.datefmt)
        return f"[{asctime}] - Hata: [{fatura_no}] - [{record.getMessage()}]"

# Clean up handlers if already defined
logger.handlers = []
file_handler = logging.FileHandler(log_file_path, encoding="utf-8")
file_handler.setLevel(logging.ERROR)
formatter = CustomFormatter(datefmt="%Y-%m-%d %H:%M:%S")
file_handler.setFormatter(formatter)
logger.addHandler(file_handler)

def log_error(fatura_no: str, message: str):
    logger.error(message, extra={"fatura_no": fatura_no})

def cleanup_stale_temp_dirs(max_age_hours: int = 6):
    """TEMP_ROOT altında max_age_hours'tan eski tüm klasörleri sil."""
    now = time.time()
    if not os.path.exists(TEMP_ROOT):
        return
    for name in os.listdir(TEMP_ROOT):
        path = os.path.join(TEMP_ROOT, name)
        try:
            if os.path.isdir(path):
                age_hours = (now - os.path.getmtime(path)) / 3600
                if age_hours > max_age_hours:
                    shutil.rmtree(path)
                    print(f"[GIB Arşiv] Yetim temp klasör temizlendi: {path} (yaş: {age_hours:.1f} saat)")
        except Exception as e:
            print(f"[GIB Arşiv] Temp klasör temizlenirken hata ({path}): {e}")

async def periodic_cleanup_loop():
    """Her saat başı eski temp klasörlerini temizle."""
    try:
        while True:
            await asyncio.sleep(3600)
            cleanup_stale_temp_dirs(max_age_hours=6)
    except asyncio.CancelledError:
        pass

# Playwright Lifespan — tek bir browser instance başlatıp uygulama kapanana kadar açık tutar
# + Startup'ta yetim temp klasör temizliği + periyodik temizlik döngüsü
@asynccontextmanager
async def lifespan(app: FastAPI):
    # --- Startup ---
    # Eski/yetim temp klasörlerini temizle (önceki crash'lerden kalanlar)
    cleanup_stale_temp_dirs(max_age_hours=6)

    # Periyodik temizlik döngüsünü başlat
    cleanup_task = asyncio.create_task(periodic_cleanup_loop())
    app.state.cleanup_task = cleanup_task

    # Playwright browser başlat
    pw = await async_playwright().start()
    browser = await pw.chromium.launch(headless=True)
    app.state.playwright = pw
    app.state.browser = browser
    print("[GIB Arşiv] Playwright Chromium başlatıldı (tek instance).")

    yield

    # --- Shutdown ---
    # Periyodik temizlik döngüsünü durdur
    cleanup_task.cancel()
    try:
        await cleanup_task
    except asyncio.CancelledError:
        pass

    # Playwright browser kapat
    await browser.close()
    await pw.stop()
    print("[GIB Arşiv] Playwright Chromium kapatıldı.")

# Setup FastAPI App
app = FastAPI(
    title="GİB Portal Arşiv",
    description="GİB E-Arşiv Portal Fatura İndirme ve PDF Dönüştürme Aracı",
    lifespan=lifespan,
)

print("="*60)
print(" GİB E-Arşiv Fatura İndirici - CORE SYSTEM ACTIVATED")
print(" Developed by: @talh4tr")
print(" License: PolyForm Noncommercial 1.0.0")
print(" WARNING: Commercial use, SaaS integration, or resale")
print(" is STRICTLY PROHIBITED. All rights reserved.")
print("="*60)

# Global progress state
progress_state = {"status": "Bekleniyor...", "percent": 0}

@app.get("/api/progress")
def get_progress():
    return progress_state

class DownloadRequest(BaseModel):
    username: str
    password: str
    startDate: str  # Format: DD/MM/YYYY
    endDate: str    # Format: DD/MM/YYYY
    testMode: bool
    filterType: Optional[str] = None
    filterTypes: Optional[List[str]] = None
    direction: Optional[str] = "outgoing"  # 'outgoing' or 'incoming'

def validate_filters(filters: Optional[List[str]]) -> None:
    if not filters:
        return
    allowed = {"signed", "deleted", "objected"}
    for f in filters:
        if f not in allowed:
            raise ValueError("Invalid filter value provided.")

async def convert_html_to_pdf(html_content: str, pdf_path: str, browser, fatura_no: str = "Bilinmiyor", is_cancelled: bool = False):
    # GİB'in orijinal CSS'ine müdahale etme — sadece karakter kodlaması için meta tag ekle
    meta_tag = '<meta http-equiv="Content-Type" content="text/html; charset=utf-8" />'

    if "<head>" in html_content:
        html_content = html_content.replace("<head>", f"<head>{meta_tag}")
    else:
        html_content = f"<html><head>{meta_tag}</head><body>" + html_content + "</body></html>"

    # Filigranı sayfa akışından kopararak (position:fixed) fatura düzenini bozmadan ekle
    if is_cancelled:
        iptal_watermark = """
<div style="position:fixed; top:35%; left:0; width:100%; text-align:center; transform:rotate(-45deg); 
            color:rgba(210,0,0,0.18); font-size:75px; font-weight:bold; z-index:999999; 
            pointer-events:none; white-space:nowrap; font-family:sans-serif;">
    İPTAL EDİLMİŞTİR
</div>
"""
        # Body etiketini bulup hemen sonrasına ekle
        if "<body>" in html_content:
            html_content = html_content.replace("<body>", f"<body>{iptal_watermark}", 1)
        elif "<body " in html_content.lower():
            html_content = re.sub(
                r'(<body[^>]*>)',
                rf'\1{iptal_watermark}',
                html_content,
                count=1,
                flags=re.IGNORECASE
            )
        
    temp_html_path = pdf_path.replace(".pdf", ".html")
    context = None
    try:
        with open(temp_html_path, 'w', encoding='utf-8') as f:
            f.write(html_content)
        
        # Paylaşılan browser'dan izole bir context aç — her istek kendi context'inde çalışır
        context = await browser.new_context()
        page = await context.new_page()
        # Tarayıcı penceresini faturanın sığacağı standart bir genişliğe zorla
        await page.set_viewport_size({"width": 1024, "height": 768})
        await page.goto(f"file:///{os.path.abspath(temp_html_path)}")
        await page.emulate_media(media='print')
        await page.add_style_tag(content="""
            @page { size: A4 portrait; margin: 0; }
            body { -webkit-print-color-adjust: exact !important; background-color: white !important; }
            /* GİB'in faturayı bölmesini engelle */
            * { page-break-after: avoid !important; page-break-before: avoid !important; page-break-inside: avoid !important; }
        """)
        await page.pdf(
            path=pdf_path,
            print_background=True,
            prefer_css_page_size=True,  # GİB'in kendi sayfa boyutlandırma CSS'ini dinle
            margin={"top": "0", "bottom": "0", "left": "0", "right": "0"}
        )
        return True
    except Exception as e:
        print(f"Playwright PDF dönüştürme hatası: {e}")
        log_error(fatura_no, f"PDF render hatası: {str(e)}")
        return False
    finally:
        # Context'i kapat (page de otomatik kapanır) — browser'ı KAPATMA
        if context:
            try:
                await context.close()
            except Exception:
                pass
        if os.path.exists(temp_html_path):
            try:
                os.remove(temp_html_path)
            except Exception as e:
                print(f"Geçici HTML silinemedi: {e}")

def cleanup_temp_dir(temp_dir: str):
    try:
        if os.path.exists(temp_dir):
            shutil.rmtree(temp_dir)
            print(f"Geçici dizin temizlendi: {temp_dir}")
    except Exception as e:
        print(f"Geçici dizin temizlenirken hata oluştu: {e}")

@app.post("/api/download")
async def download_invoices(req: DownloadRequest, request: Request, background_tasks: BackgroundTasks):
    global progress_state
    # Validate date formats roughly (DD/MM/YYYY)
    date_regex = re.compile(r'^\d{2}/\d{2}/\d{4}$')
    if not date_regex.match(req.startDate) or not date_regex.match(req.endDate):
        raise HTTPException(status_code=400, detail="Tarihler DD/MM/YYYY formatında olmalıdır.")
        
    # Create unique temp directories for process isolation
    temp_dir = tempfile.mkdtemp(dir=TEMP_ROOT)
    
    # Prepare params based on direction and filters
    php_filter_type = req.filterType
    php_filter_types = req.filterTypes

    if req.direction == "incoming":
        php_filter_type = None
        php_filter_types = None
    elif req.direction == "outgoing":
        if php_filter_types is not None:
            try:
                validate_filters(php_filter_types)
            except ValueError as ve:
                raise HTTPException(status_code=400, detail=str(ve))
            if php_filter_type is None:
                php_filter_type = ",".join(php_filter_types)
        elif php_filter_type is not None:
            # Validate legacy filterType string to ensure 400 is returned on invalid values
            if php_filter_type == "both":
                legacy_list = ["signed", "deleted"]
            elif php_filter_type == "all":
                legacy_list = ["signed", "deleted", "objected"]
            else:
                legacy_list = [t.strip() for t in re.split(r'[,|]', php_filter_type) if t.strip()]
            try:
                validate_filters(legacy_list)
            except ValueError as ve:
                raise HTTPException(status_code=400, detail=str(ve))
        else:
            raise HTTPException(status_code=400, detail="Filtre tipi belirtilmelidir.")
        
    # Prepare params for PHP helper
    php_params = {
        "username": req.username,
        "password": req.password,
        "startDate": req.startDate,
        "endDate": req.endDate,
        "testMode": req.testMode,
        "filterType": php_filter_type,
        "filterTypes": php_filter_types,
        "direction": req.direction,
        "outputDir": temp_dir
    }
    
    # Path to gib_helper.php in current working directory
    helper_path = os.path.join(os.path.dirname(__file__), "gib_helper.php")
    if not os.path.exists(helper_path):
        cleanup_temp_dir(temp_dir)
        log_error("Sistem", "GİB yardımcı entegrasyon dosyası (gib_helper.php) bulunamadı.")
        raise HTTPException(status_code=500, detail="GİB yardımcı entegrasyon dosyası (gib_helper.php) bulunamadı.")
        
    try:
        progress_state = {"status": "GİB'den faturalar çekiliyor...", "percent": 10}
        failed_invoices = []
        # Run php helper (asenkron — event loop bloklanmaz)
        proc = await asyncio.create_subprocess_exec(
            "php", helper_path,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout_bytes, stderr_bytes = await asyncio.wait_for(
                proc.communicate(input=json.dumps(php_params).encode("utf-8")),
                timeout=120,
            )
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            cleanup_temp_dir(temp_dir)
            log_error("Sistem", "GİB PHP helper zaman aşımına uğradı.")
            raise HTTPException(status_code=504, detail="GİB portalından yanıt alınamadı (zaman aşımı).")
        
        stdout = stdout_bytes.decode("utf-8", errors="replace")
        stderr = stderr_bytes.decode("utf-8", errors="replace")
        
        # Check process exit code
        if proc.returncode != 0:
            err_msg = stdout or stderr or "Bilinmeyen PHP hatası"
            try:
                err_json = json.loads(err_msg)
                err_msg = err_json.get("error", err_msg)
            except:
                pass
            cleanup_temp_dir(temp_dir)
            log_error("Sistem", f"GİB Portal Hatası: {err_msg}")
            raise HTTPException(status_code=400, detail=f"GİB Portal Hatası: {err_msg}")
            
        # Parse output
        try:
            res = json.loads(stdout)
        except json.JSONDecodeError:
            cleanup_temp_dir(temp_dir)
            log_error("Sistem", f"PHP çıktısı JSON olarak ayrıştırılamadı. Ham çıktı: {stdout[:500]}")
            raise HTTPException(
                status_code=502,
                detail="GİB portalından beklenmeyen bir yanıt alındı. Lütfen daha sonra tekrar deneyin."
            )
        if "error" in res:
            cleanup_temp_dir(temp_dir)
            log_error("Sistem", f"GİB Portal Hatası: {res['error']}")
            raise HTTPException(status_code=400, detail=f"GİB Portal Hatası: {res['error']}")
            
        downloaded_zips = res.get("downloaded", [])
        failed_invoices = res.get("failed", [])
        
        # GİB şüpheli limit uyarılarını oku ve rapora/loglara ekle
        suspicious_warnings = res.get("suspiciousWarnings", [])
        for warning in suspicious_warnings:
            log_error("Sistem", warning)
            failed_invoices.append({
                "belgeNumarasi": "SISTEM_UYARISI_LIMIT",
                "uuid": "-",
                "message": warning
            })
        
        # Toplam sayı doğrulaması — PHP'nin GİB'den bulduğu fatura sayısı ile
        # Python'ın işleyebildiği sayıyı karşılaştır
        total_found = res.get("totalFound")
        if total_found is not None:
            total_accounted = len(downloaded_zips) + len(failed_invoices)
            if total_accounted != total_found:
                missing_count = total_found - total_accounted
                log_error(
                    "Sistem",
                    f"SAYI TUTARSIZLIĞI: GİB {total_found} fatura buldu, "
                    f"ancak sadece {total_accounted} tanesi işlendi/raporlandı. "
                    f"{missing_count} fatura kaynağı belirsiz şekilde kayboldu."
                )
                failed_invoices.append({
                    "belgeNumarasi": "SISTEM_UYARISI",
                    "uuid": "-",
                    "message": (
                        f"GİB portalı {total_found} fatura buldu ancak sistem sadece "
                        f"{total_accounted} tanesini işleyebildi. {missing_count} fatura "
                        f"muhtemelen indirme aşamasında sessizce kayboldu. Lütfen GİB "
                        f"portalını manuel kontrol edin."
                    )
                })
            
        # Log download failures
        for failed in failed_invoices:
            belge_no = failed.get("belgeNumarasi") or failed.get("uuid") or "Bilinmiyor"
            msg = failed.get("message") or "Bilinmeyen Hata"
            log_error(belge_no, msg)
            
        if not downloaded_zips and not failed_invoices:
            cleanup_temp_dir(temp_dir)
            raise HTTPException(status_code=404, detail="Belirtilen tarihlerde indirilecek fatura bulunamadı.")
            
        # Create output master ZIP
        master_zip_path = os.path.join(temp_dir, "gib_portal_faturalar.zip")
        
        # Phase A - Preparation: Extract HTML and run validation checks
        render_queue = []
        for item in downloaded_zips:
            zip_path = item.get("zipPath")
            status_type = item.get("type")  # 'signed' or 'deleted'
            belge_no = item.get("belgeNumarasi", item.get("uuid"))
            belge_tarihi = item.get("belgeTarihi", "bilinmeyen-tarih").replace("/", "-").replace(".", "-")
            
            if not zip_path or not os.path.exists(zip_path):
                failed_invoices.append({
                    "belgeNumarasi": belge_no,
                    "uuid": item.get("uuid", "Bilinmiyor"),
                    "message": "ZIP dosyası diskte bulunamadı (indirme başarısız olmuş olabilir)."
                })
                log_error(belge_no, "ZIP dosyası diskte bulunamadı.")
                continue
                
            # Extract HTML content from individual zip file
            html_content = None
            try:
                with zipfile.ZipFile(zip_path, 'r') as invoice_zip:
                    for name in invoice_zip.namelist():
                        if name.endswith('.html'):
                            html_content = invoice_zip.read(name).decode('utf-8')
                            break
            except Exception as e:
                failed_invoices.append({
                    "belgeNumarasi": belge_no,
                    "uuid": item.get("uuid", "Bilinmiyor"),
                    "message": f"Fatura zip dosyası açılamadı: {str(e)}"
                })
                print(f"Fatura zip açma hatası ({belge_no}): {e}")
                log_error(belge_no, f"Fatura zip açma hatası: {str(e)}")
                continue
                
            if not html_content:
                failed_invoices.append({
                    "belgeNumarasi": belge_no,
                    "uuid": item.get("uuid", "Bilinmiyor"),
                    "message": "Fatura ZIP'i içinde HTML dosyası bulunamadı."
                })
                log_error(belge_no, "HTML içeriği bulunamadı.")
                continue
                
            # Akıllı GİB Hata Kontrolü
            try:
                soup = BeautifulSoup(html_content, "html.parser")
                text = soup.get_text()
                text_lower = text.lower()
                error_keywords = [
                    "Aradığınız kriterlere uygun fatura bulunamadı",
                    "Sistem hatası",
                    "aradığınız kriterlere uygun fatura bulunamadı",
                    "sistem hatası",
                    "sistem hatasi",
                    "aradiniz kriterlere uygun fatura bulunamadi"
                ]
                if any(kw in text for kw in error_keywords) or any(kw in text_lower for kw in error_keywords):
                    log_error(belge_no, "Fatura içeriği geçersiz (GİB Hatası)")
                    failed_invoices.append({
                        "belgeNumarasi": belge_no,
                        "uuid": item.get("uuid", "Bilinmiyor"),
                        "message": "Fatura içeriği geçersiz (GİB Hatası)"
                    })
                    continue
            except Exception as e:
                log_error(belge_no, f"HTML parse hatası: {str(e)}")
                
            # Folder structure in master ZIP: 'Gelen_Faturalar', 'Itiraz_Edilen_Faturalar' or ('Imzali'/'Iptal')
            if req.direction == "incoming":
                sub_folder = "Gelen_Faturalar"
            elif status_type == "objected":
                sub_folder = "Itiraz_Edilen_Faturalar"
            else:
                sub_folder = "Imzali" if status_type == "signed" else "Iptal"
            temp_pdf_path = os.path.join(temp_dir, f"{belge_no}.pdf")
            is_cancelled = (sub_folder == "Iptal")
            
            short_uuid = item.get("uuid", "nouuid")[:8]
            archive_name = f"{sub_folder}/{belge_no}_{belge_tarihi}_{short_uuid}.pdf"
            
            render_queue.append((belge_no, html_content, temp_pdf_path, is_cancelled, item, sub_folder, archive_name))

        # Phase B - Parallel PDF rendering using Semaphore
        render_semaphore = asyncio.Semaphore(PDF_RENDER_CONCURRENCY)
        rendered_count = 0
        total_to_render = len(render_queue)
        
        async def render_one(task):
            nonlocal rendered_count
            belge_no, html_content, temp_pdf_path, is_cancelled, item, sub_folder, archive_name = task
            async with render_semaphore:
                success = await convert_html_to_pdf(
                    html_content, temp_pdf_path, request.app.state.browser,
                    belge_no, is_cancelled=is_cancelled
                )
            
            rendered_count += 1
            percent = 10 + int(80 * (rendered_count / total_to_render)) if total_to_render > 0 else 90
            progress_state["status"] = f"PDF'ler oluşturuluyor ({rendered_count}/{total_to_render})..."
            progress_state["percent"] = percent
            
            return (task, success)
        
        if total_to_render > 0:
            progress_state = {"status": f"PDF'ler oluşturuluyor (0/{total_to_render})...", "percent": 10}
            render_results = await asyncio.gather(*[render_one(t) for t in render_queue])
        else:
            render_results = []
            
        progress_state = {"status": "ZIP dosyası hazırlanıyor...", "percent": 95}
        
        # Phase C - Sequential ZIP writing
        with zipfile.ZipFile(master_zip_path, 'w') as master_zip:
            for task, success in render_results:
                belge_no, html_content, temp_pdf_path, is_cancelled, item, sub_folder, archive_name = task
                if success and os.path.exists(temp_pdf_path):
                    master_zip.write(temp_pdf_path, arcname=archive_name)
                    # Clean up temp PDF
                    try:
                        os.remove(temp_pdf_path)
                    except Exception as e:
                        log_error(belge_no, f"Geçici PDF silinemedi: {str(e)}")
                else:
                    failed_invoices.append({
                        "belgeNumarasi": belge_no,
                        "uuid": item.get("uuid", "Bilinmiyor"),
                        "message": "PDF dönüştürme işlemi başarısız oldu (Playwright render hatası)."
                    })
            
            # If there are failed invoices, add the physical report txt
            if failed_invoices:
                report_lines = [
                    "İNDİRİLEMEYEN FATURALAR RAPORU",
                    "==============================",
                    "Aşağıdaki faturalar portal üzerinden indirilirken hata oluştu:",
                    ""
                ]
                for idx, failed in enumerate(failed_invoices, 1):
                    belge_no = failed.get("belgeNumarasi") or "Bilinmiyor"
                    uuid = failed.get("uuid") or "Bilinmiyor"
                    msg = failed.get("message") or "Bilinmeyen Hata"
                    report_lines.append(f"{idx}. Belge Numarası: {belge_no}")
                    report_lines.append(f"   UUID: {uuid}")
                    report_lines.append(f"   Hata Mesajı: {msg}")
                    report_lines.append("   ----------------------------------------")
                
                report_content = "\n".join(report_lines)
                master_zip.writestr("_INDIRILEMEYEN_FATURALAR_RAPORU.txt", report_content.encode('utf-8'))
                        
        # Register temp directory cleanup background task
        background_tasks.add_task(cleanup_temp_dir, temp_dir)
        
        # Build custom response headers
        headers = {}
        if failed_invoices:
            failed_json = json.dumps(failed_invoices)
            headers["X-Failed-Invoices"] = urllib.parse.quote(failed_json)
            headers["Access-Control-Expose-Headers"] = "X-Failed-Invoices"
            
        return FileResponse(
            master_zip_path, 
            media_type="application/zip", 
            filename="gib_portal_faturalar.zip",
            headers=headers
        )
        
    except HTTPException:
        raise
    except Exception as e:
        cleanup_temp_dir(temp_dir)
        log_error("Sistem", f"Sistem Hatası: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Sistem Hatası: {str(e)}")
    finally:
        progress_state = {"status": "Bekleniyor...", "percent": 0}

# Serve Frontend static and index.html
@app.get("/")
def read_index():
    index_path = os.path.join(os.path.dirname(__file__), "index.html")
    if os.path.exists(index_path):
        with open(index_path, 'r', encoding='utf-8') as f:
            return HTMLResponse(content=f.read())
    return HTMLResponse(content="<h3>GİB Arşiv - index.html bulunamadı.</h3>", status_code=404)
