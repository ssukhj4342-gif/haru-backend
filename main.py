from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional, List
import os
from datetime import datetime
import pytz
from supabase import create_client, Client

app = FastAPI(title="Haru Market API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

SUPABASE_URL = os.getenv("SUPABASE_URL", "")
SUPABASE_KEY = os.getenv("SUPABASE_KEY", "")

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
ADMIN_PASS = "13157"

def get_kST_time():
    tz = pytz.timezone('Asia/Seoul')
    return datetime.now(tz)

def get_kST_time_str():
    now = get_kST_time()
    return now.strftime("%Y. %m. %d. %p %I:%M").replace("AM", "오전").replace("PM", "오후")

# --- Models ---
class SettingsUpdate(BaseModel):
    notice: Optional[str] = ""
    notice_img: Optional[str] = ""
    account: Optional[str] = ""
    owner: Optional[str] = ""
    hours: Optional[str] = ""

class FruitCreate(BaseModel):
    name: str
    price: int
    stock: int
    img: Optional[str] = ""
    detail_imgs: Optional[List[str]] = [] # 다중 상세 이미지
    description: Optional[str] = ""
    hide_stock: Optional[bool] = False

class FruitUpdate(BaseModel):
    name: Optional[str] = None
    price: Optional[int] = None
    stock: Optional[int] = None
    img: Optional[str] = None
    detail_imgs: Optional[List[str]] = None
    description: Optional[str] = None
    hide_stock: Optional[bool] = None

class OrderCreate(BaseModel):
    order_type: str
    kakao_nickname: str
    name: str
    phone: str
    address: Optional[str] = ""
    door_password: Optional[str] = ""
    fruit_index: int
    qty: int
    method: str

# --- Endpoints ---
@app.get("/api/init-data")
def get_initial_data():
    try:
        meta_res = supabase.table("store_meta").select("*").eq("id", 1).execute()
        meta = meta_res.data[0] if meta_res.data else {}

        fruits_res = supabase.table("fruit_items").select("*").order("id", desc=False).execute()
        fruits = fruits_res.data or []

        now_kst = get_kST_time()
        is_delivery_available = now_kst.hour < 12

        return {
            "meta": meta,
            "fruits": fruits,
            "is_delivery_available": is_delivery_available
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.put("/api/admin/settings")
def update_settings(data: SettingsUpdate, password: str = Query(...)):
    if password != ADMIN_PASS:
        raise HTTPException(status_code=401, detail="비밀번호가 틀렸습니다.")
    try:
        update_data = data.dict(exclude_unset=True)
        update_data["updated_at"] = get_kST_time().isoformat()
        res = supabase.table("store_meta").update(update_data).eq("id", 1).execute()
        return {"status": "success", "data": res.data}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/admin/fruits")
def add_fruit(item: FruitCreate, password: str = Query(...)):
    if password != ADMIN_PASS:
        raise HTTPException(status_code=401, detail="비밀번호가 틀렸습니다.")
    try:
        new_item = {
            "name": item.name,
            "price": item.price,
            "stock": item.stock,
            "max_stock": item.stock,
            "img": item.img,
            "detail_imgs": item.detail_imgs or [],
            "description": item.description,
            "hide_stock": item.hide_stock
        }
        res = supabase.table("fruit_items").insert(new_item).execute()
        return {"status": "success", "data": res.data}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.put("/api/admin/fruits/{fruit_id}")
def update_fruit(fruit_id: int, item: FruitUpdate, password: str = Query(...)):
    if password != ADMIN_PASS:
        raise HTTPException(status_code=401, detail="비밀번호가 틀렸습니다.")
    try:
        update_data = item.dict(exclude_none=True)
        res = supabase.table("fruit_items").update(update_data).eq("id", fruit_id).execute()
        return {"status": "success", "data": res.data}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.delete("/api/admin/fruits/{fruit_id}")
def delete_fruit(fruit_id: int, password: str = Query(...)):
    if password != ADMIN_PASS:
        raise HTTPException(status_code=401, detail="비밀번호가 틀렸습니다.")
    try:
        res = supabase.table("fruit_items").delete().eq("id", fruit_id).execute()
        return {"status": "success", "data": res.data}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/orders")
def create_order(order: OrderCreate):
    try:
        now_kst = get_kST_time()
        if order.order_type == "배달" and now_kst.hour >= 12:
            raise HTTPException(status_code=400, detail="금일 배달 주문이 마감되었습니다. (오후 12시까지 가능)")

        fruits_res = supabase.table("fruit_items").select("*").order("id", desc=False).execute()
        fruits = fruits_res.data or []

        if order.fruit_index < 0 or order.fruit_index >= len(fruits):
            raise HTTPException(status_code=400, detail="유효하지 않은 과일 품목입니다.")

        target_fruit = fruits[order.fruit_index]
        
        if target_fruit["stock"] < order.qty:
            raise HTTPException(status_code=400, detail=f"재고가 부족합니다. (현재 남은 재고: {target_fruit['stock']}개)")

        fruit_total = target_fruit["price"] * order.qty
        delivery_fee = 3000 if order.order_type == "배달" else 0
        total_price = fruit_total + delivery_fee

        order_time = get_kST_time_str()

        new_order = {
            "order_type": order.order_type,
            "kakao_nickname": order.kakao_nickname.strip(),
            "name": order.name.strip(),
            "phone": order.phone.strip(),
            "address": order.address.strip() if order.address else "",
            "door_password": order.door_password.strip() if order.door_password else "",
            "fruit": f"{target_fruit['name']} ({target_fruit['price']:,}원)",
            "fruit_name": target_fruit["name"],
            "fruit_index": order.fruit_index,
            "qty": order.qty,
            "quantity": order.qty,
            "price": target_fruit["price"],
            "total_price": total_price,
            "delivery_fee": delivery_fee,
            "method": order.method,
            "pay_method": order.method,
            "status": "입금대기",
            "time_str": order_time
        }

        order_res = supabase.table("orders").insert(new_order).execute()

        new_stock = target_fruit["stock"] - order.qty
        supabase.table("fruit_items").update({"stock": new_stock}).eq("id", target_fruit["id"]).execute()

        return {"status": "success", "data": order_res.data}
    except HTTPException as he:
        raise he
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/my-orders")
def get_my_orders(kakao_nickname: str = Query(...), name: str = Query(...)):
    try:
        orders_res = supabase.table("orders").select("*").eq("kakao_nickname", kakao_nickname.strip()).eq("name", name.strip()).order("id", desc=True).execute()
        return {"orders": orders_res.data or []}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.delete("/api/my-orders/{order_id}")
def cancel_my_order(order_id: int, kakao_nickname: str = Query(...), name: str = Query(...)):
    try:
        order_res = supabase.table("orders").select("*").eq("id", order_id).eq("kakao_nickname", kakao_nickname.strip()).eq("name", name.strip()).execute()
        if not order_res.data:
            raise HTTPException(status_code=404, detail="주문을 찾을 수 없습니다.")

        order_data = order_res.data[0]
        if order_data["status"] not in ["입금대기", "접수완료"]:
            raise HTTPException(status_code=400, detail="처리완료건은 취소 불가능합니다.")

        fruit_name = order_data.get("fruit_name")
        qty = order_data.get("qty", 1)
        if fruit_name:
            f_res = supabase.table("fruit_items").select("*").eq("name", fruit_name).execute()
            if f_res.data:
                supabase.table("fruit_items").update({"stock": f_res.data[0]["stock"] + qty}).eq("id", f_res.data[0]["id"]).execute()

        supabase.table("orders").delete().eq("id", order_id).execute()
        return {"status": "success"}
    except HTTPException as he:
        raise he
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/admin/orders")
def get_admin_orders(password: str = Query(...)):
    if password != ADMIN_PASS:
        raise HTTPException(status_code=401, detail="비밀번호 오류")
    try:
        res = supabase.table("orders").select("*").order("id", desc=True).execute()
        all_orders = res.data or []

        pending = [o for o in all_orders if o.get("status") != "판매완료"]
        completed = [o for o in all_orders if o.get("status") == "판매완료"]
        delivery_orders = [o for o in all_orders if o.get("order_type") == "배달" and o.get("status") != "판매완료"]

        return {
            "pending": pending,
            "completed": completed,
            "delivery_orders": delivery_orders
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.put("/api/admin/orders/{order_id}")
def update_order_status(order_id: int, status: str = Query(...), password: str = Query(...)):
    if password != ADMIN_PASS:
        raise HTTPException(status_code=401, detail="비밀번호 오류")
    try:
        update_data = {"status": status, "status_changed_time": get_kST_time_str()}
        res = supabase.table("orders").update(update_data).eq("id", order_id).execute()
        return {"status": "success", "data": res.data}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.delete("/api/admin/orders/{order_id}")
def delete_admin_order(order_id: int, password: str = Query(...)):
    if password != ADMIN_PASS:
        raise HTTPException(status_code=401, detail="비밀번호 오류")
    try:
        order_res = supabase.table("orders").select("*").eq("id", order_id).execute()
        if order_res.data and order_res.data[0].get("status") != "판매완료":
            fruit_name = order_res.data[0].get("fruit_name")
            qty = order_res.data[0].get("qty", 1)
            if fruit_name:
                f_res = supabase.table("fruit_items").select("*").eq("name", fruit_name).execute()
                if f_res.data:
                    supabase.table("fruit_items").update({"stock": f_res.data[0]["stock"] + qty}).eq("id", f_res.data[0]["id"]).execute()

        res = supabase.table("orders").delete().eq("id", order_id).execute()
        return {"status": "success", "data": res.data}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
