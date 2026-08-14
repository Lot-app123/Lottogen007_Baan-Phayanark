import io
import random
import zipfile
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from typing import Annotated, Optional
from urllib.parse import quote

from fastapi import Cookie, Depends, FastAPI, Form, HTTPException, Request, Response, status
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from jose import JWTError, jwt
from PIL import Image, ImageDraw, ImageFont
from zoneinfo import ZoneInfo

# ─── App setup ───────────────────────────────────────────────────────────────

app = FastAPI()
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

# ─── Auth config (เปลี่ยน SECRET_KEY ก่อน deploy!) ───────────────────────────

SECRET_KEY = "change-me-before-deploy-use-openssl-rand-hex-32"
ALGORITHM  = "HS256"
TOKEN_EXPIRE_HOURS = 8

USERS = {"admin": "1234"}  # TODO: ใช้ DB + bcrypt จริง ๆ ใน production

# Mapping สำหรับรูปธง (อัปเดตตามชื่อที่มีการรวมรอบ + VIP และ เช้า/บ่าย)
FLAG_MAPPING = {
    # 🇱🇦 ลาว (Laos)
    "ลาว EXTRA": "static/flags/laos.png",
    "ลาว TV": "static/flags/laos.png",
    "ลาวพิเศษรอบเที่ยง": "static/flags/laos.png",
    "ลาว HD": "static/flags/laos.png",
    "ลาวสตาร์": "static/flags/laos.png",
    "หวยลาวสามัคคี": "static/flags/laos.png", # ปรับตามชื่อใหม่
    "ลาวพัฒนา": "static/flags/laos.png",
    "ลาวอาเซียน": "static/flags/laos.png",
    "ลาว VIP": "static/flags/laos.png",
    "ลาวสามัคคี VIP": "static/flags/laos.png",
    "ลาว STAR VIP": "static/flags/laos.png",
    "ลาวกาชาด": "static/flags/laos.png",

    # 🇻🇳 เวียดนาม (Vietnam)
    "ฮานอยอาเซียน": "static/flags/vietnam.png",
    "ฮานอย HD": "static/flags/vietnam.png",
    "ฮานอยสตาร์": "static/flags/vietnam.png",
    "ฮานอย TV": "static/flags/vietnam.png",
    "ฮานอยกาชาด": "static/flags/vietnam.png",
    "ฮานอยพิเศษ": "static/flags/vietnam.png",
    "ฮานอยสามัคคี": "static/flags/vietnam.png",
    "ฮานอย": "static/flags/vietnam.png", # ปรับตามชื่อใหม่
    "ฮานอย VIP": "static/flags/vietnam.png",
    "ฮานอยพัฒนา": "static/flags/vietnam.png",
    "ฮานอย EXTRA": "static/flags/vietnam.png",

    # 🇯🇵 ญี่ปุ่น (Japan)
    "นิเคอิ(เช้า) + VIP": "static/flags/japan.png",
    "นิเคอิ(บ่าย) + VIP": "static/flags/japan.png",

    # 🇨🇳 จีน (China)
    "จีน(เช้า) + VIP": "static/flags/china.png",
    "จีน(บ่าย) + VIP": "static/flags/china.png",

    # 🇭🇰 ฮ่องกง (Hong Kong)
    "ฮั่งเส็ง(เช้า) + VIP": "static/flags/hongkong.png",
    "ฮั่งเส็ง(บ่าย) + VIP": "static/flags/hongkong.png",

    # 🇹🇼 ไต้หวัน (Taiwan)
    "ไต้หวัน + VIP": "static/flags/taiwan.png",

    # 🇰🇷 เกาหลีใต้ (South Korea)
    "เกาหลี + VIP": "static/flags/korea.png",

    # 🇺🇸 สหรัฐอเมริกา (USA)
    "ดาวโจนส์ + VIP": "static/flags/usa.png",
    "ดาวโจนส์ STAR": "static/flags/usa.png",

    # 🇬🇧 อังกฤษ (United Kingdom)
    "อังกฤษ + VIP": "static/flags/uk.png",

    # 🇩🇪 เยอรมนี (Germany)
    "เยอรมัน + VIP": "static/flags/germany.png",

    # 🇷🇺 รัสเซีย (Russia)
    "รัสเซีย + VIP": "static/flags/russia.png",

    # 🇸🇬 สิงคโปร์ (Singapore)
    "สิงคโปร์ + VIP": "static/flags/singapore.png",

    # 🇹🇭 ไทย (Thailand)
    "ไทยเช้า": "static/flags/thailand.png",
    "ไทยเที่ยง": "static/flags/thailand.png",
    "ไทยบ่าย": "static/flags/thailand.png",
    "ไทยเย็น": "static/flags/thailand.png",
    "ไทย": "static/flags/thailand.png",
    "ออมสิน": "static/flags/thailand.png",
    "ธกส": "static/flags/thailand.png",
    "รัฐบาล": "static/flags/thailand.png",

    # 🇮🇳 อินเดีย (India)
    "อินเดีย": "static/flags/india.png",

    # 🇲🇾 มาเลเซีย (Malaysia)
    "มาเลย์": "static/flags/malaysia.png",

    # 🇪🇬 อียิปต์ (Egypt)
    "อียิปต์": "static/flags/egypt.png",

    # 🇪🇺 ยุโรป (Europe)
    "ยูโร": "static/flags/eu.png"
}


def create_token(username: str) -> str:
    expire = datetime.now(timezone.utc) + timedelta(hours=TOKEN_EXPIRE_HOURS)
    return jwt.encode({"sub": username, "exp": expire}, SECRET_KEY, algorithm=ALGORITHM)


def get_current_user(token: str = Cookie(default=None, alias="access_token")) -> str:
    if not token:
        raise HTTPException(status_code=status.HTTP_307_TEMPORARY_REDIRECT, headers={"Location": "/login"})
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        return payload["sub"]
    except JWTError:
        raise HTTPException(status_code=status.HTTP_307_TEMPORARY_REDIRECT, headers={"Location": "/login"})


CurrentUser = Annotated[str, Depends(get_current_user)]


# ─── Image/font cache (โหลดครั้งเดียวตอน startup) ───────────────────────────

@lru_cache(maxsize=1)
def _load_bg() -> Image.Image:
    """โหลดภาพพื้นหลังครั้งเดียว แล้ว cache ไว้ใน RAM"""
    return Image.open("static/Baan-1.jpg").convert("RGBA")


@lru_cache(maxsize=16) # เพิ่มขนาด cache เผื่อโหลดหลายฟอนต์
def _load_font(size: int, font_path: str = "static/Anton-Regular.ttf") -> ImageFont.FreeTypeFont:
    """Cache แต่ละขนาดและไฟล์ฟอนต์แยกกัน (ค่าเริ่มต้นคือ Anton สำหรับตัวเลข)"""
    return ImageFont.truetype(font_path, size)


def _get_auto_font(draw: ImageDraw.ImageDraw, text: str, max_width: int,
                   start: int = 50, min_size: int = 20, 
                   font_path: str = "static/Anton-Regular.ttf") -> ImageFont.FreeTypeFont:
    for size in range(start, min_size - 1, -1):
        font = _load_font(size, font_path)
        w = draw.textbbox((0, 0), text, font=font)[2]
        if w <= max_width:
            return font
    return _load_font(min_size, font_path)


def _bold_text(draw: ImageDraw.ImageDraw, xy: tuple[int, int], text: str,
               font: ImageFont.FreeTypeFont, fill: str = "#ffca08", boldness: int = 1) -> None:
    x, y = xy
    for dx in range(-boldness, boldness + 1):
        for dy in range(-boldness, boldness + 1):
            draw.text((x + dx, y + dy), text, font=font, fill=fill)


def create_image_bytes(
    lottery_type: str, 
    main1: Optional[str] = None, 
    main2: Optional[str] = None,
    pair1: Optional[str] = None,
    pair2: Optional[str] = None,
    pair3: Optional[str] = None,
    win_num: Optional[str] = None
) -> bytes:
    # deepcopy เพื่อไม่ให้แก้ไข cached image โดยตรง
    image = deepcopy(_load_bg()).convert("RGB")
    draw  = ImageDraw.Draw(image)

    # ─── วันที่และหัวข้อ ──────────────────────────────────────────────────
    # ปรับ format วันที่เป็น วัน/เดือน (DD/MM) ตามแบบในภาพ image_7a769f.png
    text_font_path = "static/Sriracha-Regular.ttf"
    date_text = datetime.now(ZoneInfo("Asia/Bangkok")).strftime("%d/%m")
    draw.text((850, 3 ), date_text, font=_load_font(40 ,text_font_path), fill="#000000") # อาจต้องปรับพิกัด x,y ตามพื้นหลังจริง

    # ชื่อประเภทหวย (auto-fit)
    font_auto = _get_auto_font(draw, lottery_type, image.width - 400, start=48, font_path=text_font_path)
    bbox = draw.textbbox((0, 0), lottery_type, font=font_auto)
    x_pos = (image.width - (bbox[2] - bbox[0])) // 2
    _bold_text(draw, (x_pos + 50, 55), lottery_type, font_auto, fill="#000000")

    flag_path = FLAG_MAPPING.get(lottery_type)
    if flag_path:
        try:
            # โหลดรูปธง
            flag_img = Image.open(flag_path).convert("RGBA")
            
            # 1. กำหนดขนาดธง (ปรับความกว้าง ตัวแปรความสูงจะปรับตามสัดส่วนอัตโนมัติ)
            target_flag_width = 80   # ⬅️ ปรับขนาดความกว้างของธงที่นี่
            w_ratio = target_flag_width / flag_img.width
            target_flag_height = int(flag_img.height * w_ratio)
            flag_img = flag_img.resize((target_flag_width, target_flag_height), Image.Resampling.LANCZOS)
            
            # 2. กำหนดตำแหน่งที่วางธงอิสระ
            flag_x = 740  # ⬅️ ปรับแกน X (เลื่อนซ้าย-ขวา)
            flag_y = 50  # ⬅️ ปรับแกน Y (เลื่อนขึ้น-ลง)
            
            # วางรูปธงทับลงไป
            image.paste(flag_img, (flag_x, flag_y), flag_img)
            
        except FileNotFoundError:
            pass # ถ้าหาไฟล์รูปธงไม่เจอ ให้ข้ามการวาดธงไปเลย

    # ─── สุ่มเลขตามเงื่อนไขใหม่ ──────────────────────────────────────────────
    # 1. จัดการตัวแปรที่รับมาจากผู้ใช้
    m1 = main1 if main1 and len(main1) == 1 and main1.isdigit() else None
    m2 = main2 if main2 and len(main2) == 2 and main2.isdigit() else None

    # --- กำหนดค่า num1 ---
    if m1:
        num1 = m1
    else:
        num1 = str(random.choice(range(10)))

    # --- กำหนดค่า num2 (รับค่ามาจาก main 2 โดยตรง) ---
    if m2:
        num2 = m2
    else:
        # ถ้าไม่ได้กรอกมา ให้สุ่มเลข 2 ตัวที่มี num1 เป็นส่วนประกอบ
        other_digit = random.choice([str(i) for i in range(10) if str(i) != num1])
        num2 = f"{num1}{other_digit}"
        if random.random() > 0.5: num2 = num2[::-1]

    # เงื่อนไขที่ 1: num1 = เบิ้ลเป็น 3 ตัว (เช่น 5 -> 555)
    triple_num = f"{num1}{num1}{num1}"
    
    # เงื่อนไขที่ 2: num2 = ก็แค่รับค่ามาจาก main 2 โดยตรงเลย
    main_pair = num2

    # --- 2. จัดการ เลขคู่ 3 ชุด ---
    def get_or_random_pair(user_input, default_format):
        if user_input and len(user_input) == 2 and user_input.isdigit():
            return user_input
        return default_format

    # เอาเลข num1 เป็นหลัก แล้วสุ่มเพิ่มอีก 1 ตัว (0-9) โดยที่:
    # 1. ห้ามเป็นตัวเดียวกับ num1 (กันเลขเบิ้ล)
    # 2. ห้ามทำให้ผลลัพธ์ไปซ้ำกับ num2 (main_pair)
    avail_pair_digits = [str(i) for i in range(10) if str(i) != num1 and f"{num1}{i}" != num2 and f"{i}{num1}" != num2]
    
    # สุ่มเลข 3 ตัวแบบไม่ซ้ำกันเลย
    if len(avail_pair_digits) >= 3:
        r1, r2, r3 = random.sample(avail_pair_digits, 3)
    else:
        # สำรองกรณีที่มีเลขให้สุ่มไม่พอ (เช่น เผลอตัดออกมากไป) ก็จะสุ่มจาก 0-9 ธรรมดาแทน
        r1, r2, r3 = random.sample([str(i) for i in range(10)], 3)
    
    pairs_list = [
        get_or_random_pair(pair1, f"{num1}{r1}"),
        get_or_random_pair(pair2, f"{num1}{r2}"),
        get_or_random_pair(pair3, f"{num1}{r3}")
    ]
    # รวม List ให้เป็น String คั่นด้วยช่องว่าง เพื่อให้วาดรูปลงข้อความได้
    pairs_text = "   ".join(pairs_list)

    # --- 3. จัดการเลขฟัน 3 ตัวท้าย (win_num) ---
    def get_or_random_triple(user_input, default_format):
        if user_input and len(user_input) == 3 and user_input.isdigit():
            return user_input
        return default_format

    # เงื่อนไขที่ 4: เอาเลข main2 มาและสุ่มเลขเพิ่มอีก 1 ตัว... ห้ามซ้ำกับ main2
    # กรองเอาเลข 0-9 เฉพาะตัวที่ไม่ได้อยู่ใน num2 (main2) มาสุ่มใส่ด้านหน้า
    avail_front_digits = [str(i) for i in range(10) if str(i) not in num2]
    front_digit = random.choice(avail_front_digits)
    
    # สังเกตว่าดึงตัวแปร win_num ที่ส่งมาจากหน้าเว็บตรงๆ เพื่อมาใช้เช็ค
    triple_val = get_or_random_triple(win_num, f"{front_digit}{num2}")

    # ─── วาดผลลัพธ์ลงบนภาพ ────────────────────────────────────────────────
    # ปรับขนาดฟอนต์ให้เข้ากับแต่ละกล่อง
    f_large  = _load_font(160)
    f_medium = _load_font(150)
    f_small  = _load_font(100)

    # หมายเหตุ: พิกัด (x, y) เป็นค่าประมาณการอ้างอิงจากโครงสร้างภาพ image_7a769f.png
    # หากตำแหน่งเบี้ยว คุณสามารถปรับตัวเลข x (แนวนอน) และ y (แนวตั้ง) ด้านล่างนี้ได้เลย
    
    # รูดเน้น 3 ตัว (สีแดง)
    _bold_text(draw, (610, 135), triple_num, f_large, fill="#ff0000") 
    
    # เม็ดเดียว 2 ตัว (สีแดง)
    _bold_text(draw, (670, 350), main_pair, f_medium, fill="#ff0000")   
    
    # เลขคู่ 3 คู่ (สีขาว เพื่อให้อ่านง่ายบนพื้นเขียว)
    _bold_text(draw, (400, 580), pairs_text, f_small, fill="#ffffff")  
    
    # ฟัน 3 ตัวท้าย (สีแดง)
    _bold_text(draw, (440, 720), triple_val, f_medium, fill="#ff0000") 

    # ─── คืนค่าเป็น bytes (ไม่เซฟไฟล์) ────────────────────────────────────
    buf = io.BytesIO()
    image.save(buf, format="JPEG", quality=85, optimize=True)
    buf.seek(0)
    return buf.read()

# ─── Routes ──────────────────────────────────────────────────────────────────

# 1. ตัวที่ทำให้เกิด Error 405 คือตัวนี้หายไป (สำหรับโหลดหน้าเว็บเข้าสู่ระบบ)
@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    return templates.TemplateResponse("login.html", {"request": request})

# 2. สำหรับกดปุ่มเข้าสู่ระบบ (เช็ครหัสผ่าน)
@app.post("/login")
async def login(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
):
    if USERS.get(username) != password:
        return templates.TemplateResponse(
            "login.html", 
            {"request": request, "error": "ชื่อผู้ใช้หรือรหัสผ่านไม่ถูกต้อง"},
            status_code=400
        )
    
    response = RedirectResponse(url="/", status_code=status.HTTP_303_SEE_OTHER)
    response.set_cookie(
        key="access_token",
        value=create_token(username),
        httponly=True,
        samesite="lax",
        max_age=TOKEN_EXPIRE_HOURS * 3600,
    )
    return response

# 3. สำหรับออกจากระบบ
@app.get("/logout")
async def logout():
    response = RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)
    response.delete_cookie("access_token")
    return response


@app.get("/", response_class=HTMLResponse)
async def lottery_page(request: Request, user: CurrentUser):
    return templates.TemplateResponse("index.html", {"request": request, "user": user})


@app.post("/")
async def lottery_generate(
    user: CurrentUser,
    lottery_type: list[str] = Form(...),
    main1: Optional[str] = Form(None), 
    main2: Optional[str] = Form(None),
    pair1: Optional[str] = Form(None), 
    pair2: Optional[str] = Form(None), 
    pair3: Optional[str] = Form(None), 
    win_num: Optional[str] = Form(None), 
):
    # ... โค้ดเดิมของคุณที่ใช้รับค่าและสร้างรูปภาพ ...
    if not lottery_type:
        raise HTTPException(status_code=400, detail="กรุณาเลือกประเภทหวยอย่างน้อย 1 รายการ")

    # --- เริ่มต้นส่วนตรวจสอบเงื่อนไขตัวเลข (Backend Validation) ---
    if main2 and len(main2) == 2:
        if not main1:
            raise HTTPException(status_code=400, detail="กรุณาระบุ รูดเน้น ก่อน")
        if main1 not in main2:
            raise HTTPException(status_code=400, detail=f"เน้นพิเศษ ({main2}) ต้องมีเลขจาก รูดเน้น ({main1})")

    seen_pairs = set()
    for i, p in enumerate([pair1, pair2, pair3], 1):
        if p and len(p) == 2:
            if not main1 or main1 not in p:
                raise HTTPException(status_code=400, detail=f"เลขคู่ชุดที่ {i} ต้องมีเลขจาก รูดเน้น")
            # --- กฎใหม่: ห้ามซ้ำกับเน้นพิเศษ ---
            if main2 and p == main2:
                raise HTTPException(status_code=400, detail=f"เลขคู่ชุดที่ {i} ห้ามซ้ำกับเม็ดเดียว ({main2})")
            # --- กฎใหม่: ห้ามซ้ำกันเอง ---
            if p in seen_pairs:
                raise HTTPException(status_code=400, detail=f"เลขคู่ซ้ำกัน กรุณาเปลี่ยนเลขใหม่")
            seen_pairs.add(p)
            
    if win_num and len(win_num) == 3:
        if not main2 or len(main2) < 2:
            raise HTTPException(status_code=400, detail="กรุณาระบุ เม็ดเดียว ก่อนพิมพ์เลขฟัน")
        for d in main2:
            if d not in win_num:
                raise HTTPException(status_code=400, detail=f"เลขฟันต้องมีตัวเลขจาก เม็ดเดียว ({main2})")
    # --- สิ้นสุดส่วนตรวจสอบเงื่อนไขตัวเลข ---

    parsed_items = []
    for lt_data in lottery_type:
        time_str, name_str = lt_data.split("|", 1) if "|" in lt_data else ("", lt_data)
        parsed_items.append({
            "time": time_str, 
            "name": name_str
        })
    
    parsed_items.sort(key=lambda x: x["time"] if x["time"] else "99:99")

    if len(parsed_items) == 1:
        item = parsed_items[0]
        time_str = item["time"]
        name_str = item["name"]
        
        filename = f"{time_str.replace(':', '.')}_{name_str}.jpg" if time_str else f"{name_str}.jpg"
        encoded_filename = quote(filename)
        
        img_bytes = create_image_bytes(name_str, main1, main2, pair1, pair2, pair3, win_num)
        return StreamingResponse(
            io.BytesIO(img_bytes),
            media_type="image/jpeg",
            headers={"Content-Disposition": f"attachment; filename*=utf-8''{encoded_filename}"},
        )

    zip_buf = io.BytesIO()
    with zipfile.ZipFile(zip_buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for index, item in enumerate(parsed_items, start=1):
            time_str = item["time"]
            name_str = item["name"]
            
            prefix = f"{index:02d}_" 
            time_part = f"{time_str.replace(':', '.')}_" if time_str else ""
            filename = f"{prefix}{time_part}{name_str}.jpg"
            
            zf.writestr(filename, create_image_bytes(name_str, main1, main2, pair1, pair2, pair3, win_num))
    zip_buf.seek(0)

    return StreamingResponse(
        zip_buf,
        media_type="application/zip",
        headers={"Content-Disposition": 'attachment; filename="lottery_results.zip"'},
    )

# ─── Entrypoint ──────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import os
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=int(os.getenv("PORT", 8000)), reload=False)
