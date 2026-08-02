from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional, List
import os
from datetime import datetime
from zoneinfo import ZoneInfo
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
ADMIN_PASS = "788599"

def get_kST_time():
    return datetime.now(ZoneInfo("Asia/Seoul"))

def get_kST_time_str():
    now = get_kST_time()
    return now.strftime("%Y. %m. %d. %p %I:%M").replace("AM", "오전").replace("PM", "오후")

# --- Request Models ---
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
    detail_imgs: Optional[List[str]] = []
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

class CartItem(BaseModel):
    fruit_id: int
    fruit_name: str
    price: int
    qty: int

class OrderCreate(BaseModel):
    order_type: str
    kakao_nickname: str
    name: str
    address: Optional[str] = ""
    door_password: Optional[str] = ""
    items: List[CartItem]
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

        if not order.items:
            raise HTTPException(status_code=400, detail="주문할 품목이 선택되지 않았습니다.")

        fruits_res = supabase.table("fruit_items").select("*").execute()
        db_fruits = {f["id"]: f for f in (fruits_res.data or [])}

        fruit_summary_list = []
        total_fruit_price = 0
        total_qty = 0

        for cart_item in order.items:
            f_id = cart_item.fruit_id
            if f_id not in db_fruits:
                raise HTTPException(status_code=400, detail=f"'{cart_item.fruit_name}' 품목을 찾을 수 없습니다.")
            
            db_f = db_fruits[f_id]
            if db_f["stock"] < cart_item.qty:
                raise HTTPException(status_code=400, detail=f"'{db_f['name']}'의 재고가 부족합니다. (남은 재고: {db_f['stock']}개)")

            item_total = db_f["price"] * cart_item.qty
            total_fruit_price += item_total
            total_qty += cart_item.qty
            fruit_summary_list.append(f"{db_f['name']} x{cart_item.qty}개")

            supabase.table("fruit_items").update({"stock": db_f["stock"] - cart_item.qty}).eq("id", f_id).execute()

        delivery_fee = 3000 if order.order_type == "배달" else 0
        total_price = total_fruit_price + delivery_fee
        order_time = get_kST_time_str()
        fruit_summary_str = ", ".join(fruit_summary_list)

        new_order = {
            "order_type": order.order_type,
            "kakao_nickname": order.kakao_nickname.strip(),
            "name": order.name.strip(),
            "phone": "",
            "address": order.address.strip() if order.address else "",
            "door_password": order.door_password.strip() if order.door_password else "",
            "fruit": fruit_summary_str,
            "fruit_name": fruit_summary_str,
            "qty": total_qty,
            "quantity": total_qty,
            "price": total_fruit_price,
            "total_price": total_price,
            "delivery_fee": delivery_fee,
            "method": order.method,
            "pay_method": order.method,
            "status": "입금대기",
            "time_str": order_time
        }

        order_res = supabase.table("orders").insert(new_order).execute()
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
        res = supabase.table("orders").delete().eq("id", order_id).execute()
        return {"status": "success", "data": res.data}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
