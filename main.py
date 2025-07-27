import httpx
import asyncio
from fastapi import FastAPI, Request, Query
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse, JSONResponse
import logging
import time
from urllib.parse import quote
import os  # <<<< ماژول os برای کار با مسیرها اضافه شد

# ===== بخش جدید و کلیدی برای پیدا کردن مسیر درست =====
# پیدا کردن مسیر پوشه‌ای که main.py در آن قرار دارد
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(BASE_DIR, "static")
TEMPLATES_DIR = os.path.join(BASE_DIR, "templates")
# ======================================================

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

BASE_URL = "https://phand3api.shizucdn.com/api/v3"
HEADERS = {
    "Host": "phand3api.shizucdn.com", "User-Agent": "okhttp/4.6.0",
    "Authorization": "Bearer eyJhbGciOiUzI1NiIsInR5cCI6IkpXVCJ9.eyJpZCI6MTExOTA2NywiZXhwIjoxNzUzNzg5NDcyfQ.inl9ACHXyctT87fNS_sasCWnyKtl66retDdExTCtYpc",
    "version": "4.7.7.1"
}

app = FastAPI(title="فیلم‌بین")

# حالا از مسیرهای مطلق و دقیق استفاده می‌کنیم
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
templates = Jinja2Templates(directory=TEMPLATES_DIR)

# --- بخش‌های مدیریت کش و وظایف (بدون تغییر) ---
home_page_cache = { "data": None, "last_updated": 0 }
CACHE_TTL = 86400
active_search_tasks = {}
# ---------------------------------------------

async def fetch_api_data(url: str):
    """این تابع وظیفه گرفتن داده از API را به صورت زنده دارد."""
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(url, headers=HEADERS)
            response.raise_for_status()
            logger.info(f"درخواست زنده به API زده شد: {url}")
            return response.json()
    except Exception as e:
        logger.error(f"خطا در دریافت اطلاعات از {url}: {e}")
        return None

@app.get("/", response_class=HTMLResponse)
async def read_root(request: Request):
    """این تابع از منطق کش برای صفحه اصلی استفاده می‌کند."""
    logger.info("درخواست برای صفحه اصلی دریافت شد.")
    current_time = time.time()
    if home_page_cache["data"] is None or (current_time - home_page_cache["last_updated"]) > CACHE_TTL:
        logger.info("کش صفحه اصلی منقضی شده. در حال دریافت اطلاعات جدید...")
        data = await fetch_api_data(f"{BASE_URL}/first")
        if not data:
            return templates.TemplateResponse("error.html", {"request": request, "message": "سرور اصلی در دسترس نیست."})
        home_page_cache["data"] = data
        home_page_cache["last_updated"] = current_time
        logger.info("کش صفحه اصلی آپدیت شد.")
    else:
        logger.info("در حال استفاده از کش برای صفحه اصلی.")
        data = home_page_cache["data"]
    valid_genres = [g for g in data.get("genres", []) if g and g.get("title") and g.get("posters")]
    valid_slides = [s for s in data.get("slides", []) if s.get("type") == '4' and s.get("poster")]
    return templates.TemplateResponse("index.html", {"request": request, "slides": valid_slides, "genres": valid_genres})

@app.get("/media/{item_type}/{item_id}", response_class=HTMLResponse)
async def read_item(request: Request, item_type: str, item_id: int):
    """این تابع به درستی از fetch_api_data برای گرفتن اطلاعات زنده استفاده می‌کند."""
    logger.info(f"درخواست زنده برای جزئیات {item_type} با شناسه {item_id}")
    url = f"{BASE_URL}/{item_type}/by/{item_id}"
    details = await fetch_api_data(url)
    if not details:
         return templates.TemplateResponse("error.html", {"request": request, "message": "محتوای مورد نظر یافت نشد."})
    return templates.TemplateResponse("movie.html", {"request": request, "item": details, "item_type": item_type})

@app.get("/api/search")
async def search_media(request: Request, q: str = Query(..., min_length=2)):
    client_ip = request.client.host
    if client_ip in active_search_tasks:
        logger.warning(f"درخواست جدید از {client_ip} دریافت شد. در حال لغو وظیفه جستجوی قبلی...")
        active_search_tasks[client_ip].cancel()
    async def do_search():
        encoded_query = quote(q)
        # ===== این خط هم اصلاح شد تا با مستندات API شما بخواند =====
        search_url = f"{BASE_URL}/search/name/{encoded_query}"
        logger.info(f"شروع وظیفه جستجو برای '{q}' از {client_ip}")
        return await fetch_api_data(search_url)

    task = asyncio.create_task(do_search())
    active_search_tasks[client_ip] = task
    try:
        search_results = await task
        if search_results and "posters" in search_results:
            return JSONResponse(content=search_results)
        else:
            return JSONResponse(content={"posters": []})
    except asyncio.CancelledError:
        logger.info(f"وظیفه جستجو برای {client_ip} با موفقیت لغو شد.")
        return JSONResponse(content={"posters": []})
    finally:
        if client_ip in active_search_tasks and active_search_tasks[client_ip] is task:
            del active_search_tasks[client_ip]
#python -m uvicorn app.main:app --reload