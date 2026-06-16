import os
from datetime import datetime
from zoneinfo import ZoneInfo
from pydantic import BaseModel
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from supabase import create_client, Client

app = FastAPI(title="하루마켓 흑석점 실전 API 서버")

# 손님 화면(Vercel)과 파이썬 서버(Render)가 서로 자유롭게 통신할 수 있도록 잠금 해제하는 설정
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# [중요] Supabase 금고와 연결하기 위한 주소와 열쇠 설정
# 일단 기본값으로 세팅해 두고, 나중에 렌더(Render) 사이트에 진짜 값을 심어줄 거야!
SUPABASE_URL = os.getenv("SUPABASE_URL", "https://your-supabase-url.supabase.co")
SUPABASE_KEY = os.getenv("SUPABASE_KEY", "your-supabase-anon-key")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "12345") # 사촌형의 사장님 모드 기본 비밀번호

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# --- 손님이 보낸 주문 데이터가 올바른 형식인지 검사하는 필터 ---
class OrderSubmit(BaseModel):
    name: str
    phone: str
    fruit_index: int
    qty: int
    method: str
    time_str: str

class SettingsUpdate(BaseModel):
    notice: str
    account: str
    owner: str
    hours: str
    notice_img: str = ""

class FruitStockUpdate(BaseModel):
    stock: int
    max_stock: int

class FruitCreate(BaseModel):
    name: str
    price: int
    stock: int
    img: str = ""

# --- 진짜 일하는 기능들 (API 엔드포인트) ---

# 1. 화면 처음 켰을 때: DB에서 과일 리스트랑 공지사항 싹 다 가져오기
@app.get("/api/init-data")
def get_initial_data():
    meta = supabase.table("store_meta").select("*").eq("id", 1).execute().data[0]
    fruits = supabase.table("fruit_items").select("*").order("id", desc=False).execute().data
    return {"meta": meta, "fruits": fruits}

# 2. 사장님 모드 켰을 때: 비번 검증하고 실시간 주문서 전부 다 긁어오기
@app.get("/api/admin/orders")
def get_admin_orders(password: str):
    if password != ADMIN_PASSWORD:
        raise HTTPException(status_code=401, detail="비밀번호가 틀렸습니다.")
    
    all_orders = supabase.table("orders").select("*").order("id", desc=True).execute().data
    pending = [o for o in all_orders if o["status"] != "판매완료"]
    completed = [o for o in all_orders if o["status"] == "판매완료"]
    return {"pending": pending, "completed": completed}

# 3. 손님이 예약 버튼 눌렀을 때: 재고 남아있는지 확인하고, 재고 깎고, 주문서 DB에 저장하기
@app.post("/api/orders")
def submit_order(order: OrderSubmit):
    fruits = supabase.table("fruit_items").select("*").order("id", desc=False).execute().data

    if order.fruit_index >= len(fruits):
        raise HTTPException(status_code=400, detail="존재하지 않는 과일입니다.")

    target_fruit = fruits[order.fruit_index]

    if target_fruit["stock"] < order.qty:
        raise HTTPException(status_code=400, detail="앗! 그새 재고가 부족해졌습니다.")

    # 재고 차감
    new_stock = target_fruit["stock"] - order.qty

    supabase.table("fruit_items").update({
        "stock": new_stock
    }).eq("id", target_fruit["id"]).execute()

    total_price = target_fruit["price"] * order.qty
    fruit_detail_str = f"{target_fruit['name']} ({total_price:,}원)"
    initial_status = "입금대기" if order.method == "계좌이체" else "카드대기"

    # 프론트에서 보내준 한국시간 저장
    new_order = {
        "time_str": order.time_str,
        "name": order.name,
        "phone": order.phone,
        "fruit": fruit_detail_str,
        "qty": order.qty,
        "method": order.method,
        "status": initial_status
    }

    supabase.table("orders").insert(new_order).execute()

    return {"status": "success"}

# 4. 사장님이 입금확인/수령완료 버튼 눌렀을 때 주문 상태 업데이트하기
@app.put("/api/admin/orders/{order_id}")
def update_order_status(order_id: int, status: str, password: str):
    if password != ADMIN_PASSWORD:
        raise HTTPException(status_code=401, detail="권한이 없습니다.")
    supabase.table("orders").update({"status": status}).eq("id", order_id).execute()
    return {"status": "success"}

# 5. 사장님이 주문 취소 눌렀을 때: 주문 삭제하고 깎였던 과일 재고 다시 원상복구 시키기
@app.delete("/api/admin/orders/{order_id}")
def delete_order(order_id: int, password: str):
    if password != ADMIN_PASSWORD:
        raise HTTPException(status_code=401, detail="권한이 없습니다.")
    
    order_data = supabase.table("orders").select("*").eq("id", order_id).execute().data
    if order_data:
        order = order_data[0]
        if order["status"] != "판매완료":
            fruits = supabase.table("fruit_items").select("*").execute().data
            for f in fruits:
                if f["name"] in order["fruit"]:
                    supabase.table("fruit_items").update({"stock": f["stock"] + order["qty"]}).eq("id", f["id"]).execute()
                    break
                    
    supabase.table("orders").delete().eq("id", order_id).execute()
    return {"status": "success"}

# 6. 사장님이 매장 공지사항이나 계좌번호 수정했을 때
@app.put("/api/admin/settings")
def update_settings(settings: SettingsUpdate, password: str):
    if password != ADMIN_PASSWORD:
        raise HTTPException(status_code=401, detail="권한이 없습니다.")
    supabase.table("store_meta").update(settings.dict()).eq("id", 1).execute()
    return {"status": "success"}

# 7. 사장님이 과일 재고 숫자를 직접 수정했을 때
@app.put("/api/admin/fruits/{fruit_id}/stock")
def update_fruit_stock(fruit_id: int, stock_data: FruitStockUpdate, password: str):
    if password != ADMIN_PASSWORD:
        raise HTTPException(status_code=401, detail="권한이 없습니다.")
    supabase.table("fruit_items").update({"stock": stock_data.stock, "max_stock": stock_data.max_stock}).eq("id", fruit_id).execute()
    return {"status": "success"}

# 8. 사장님이 새로운 신상 과일을 추가했을 때
@app.post("/api/admin/fruits")
def add_new_fruit(fruit: FruitCreate, password: str):
    if password != ADMIN_PASSWORD:
        raise HTTPException(status_code=401, detail="권한이 없습니다.")
    new_item = {
        "name": fruit.name,
        "price": fruit.price,
        "stock": fruit.stock,
        "max_stock": fruit.stock,
        "img": fruit.img
    }
    supabase.table("fruit_items").insert(new_item).execute()
    return {"status": "success"}

# 9. 사장님이 과일 품목을 아예 삭제했을 때
@app.delete("/api/admin/fruits/{fruit_id}")
def delete_fruit(fruit_id: int, password: str):
    if password != ADMIN_PASSWORD:
        raise HTTPException(status_code=401, detail="권한이 없습니다.")
    supabase.table("fruit_items").delete().eq("id", fruit_id).execute()
    return {"status": "success"}