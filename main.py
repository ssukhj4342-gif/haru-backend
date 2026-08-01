from fastapi import FastAPI, HTTPException, Query, Body
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional, List
import os
from datetime import datetime
import pytz
from supabase import create_client, Client

app = FastAPI(title="Haru Market API")

# CORS 설정 (프론트엔드 연동)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Supabase 연결
SUPABASE_URL = os.getenv("SUPABASE_URL", "")
SUPABASE_KEY = os.getenv("SUPABASE_KEY", "")

if not SUPABASE_URL or not SUPABASE_KEY:
    print("⚠️ Supabase 환경변수가 설정되지 않았습니다.")

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
ADMIN_PASS = "13157"

# 한국 시간 구하기
def get_kST_time():
    tz = pytz.timezone('Asia/Seoul')
    return datetime.now(tz)

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
    hide_stock: Optional[bool] = False

class FruitCreate(BaseModel):
    name: str
    price: int
    stock: int
    img: Optional[str] = ""
    description: Optional[str] = ""

class StockUpdate(BaseModel):
    stock: int
    max_stock: Optional[int] = None

class OrderCreate(BaseModel):
    order_type: str # '픽업' 또는 '배달'
    kakao_nickname: str
    name: str
    phone: str
    address: Optional[str] = ""
    fruit_index: int
    qty: int
    method: str
    time_str: Optional[str] = ""

# --- Endpoints ---

# 1. 초기 데이터 로드 (손님/사장님 공통)
@app.get("/api/init-data")
def get_initial_data():
    try:
        meta_res = supabase.table("store_meta").select("*").eq("id", 1).execute()
        meta = meta_res.data[0] if meta_res.data else {}

        fruits_res = supabase.table("fruit_items").select("*").order("id", desc=False).execute()
        fruits = fruits_res.data or []

        # 한국시간 기준 오후 12시 이전 여부 확인
        now_kst = get_kST_time()
        is_delivery_available = now_kst.hour < 12

        return {
            "meta": meta,
            "fruits": fruits,
            "is_delivery_available": is_delivery_available
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# 2. 사장님 기본 설정 저장
@app.put("/api/admin/settings")
def update_settings(data: SettingsUpdate, password: str = Query(...)):
    if password != ADMIN_PASS:
        raise HTTPException(status_code=401, detail="비밀번호가 일치하지 않습니다.")
    try:
        update_data = data.dict(exclude_unset=True)
        update_data["updated_at"] = get_kST_time().isoformat()
        res = supabase.table("store_meta").update(update_data).eq("id", 1).execute()
        return {"status": "success", "data": res.data}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# 3. 과일 품목 추가
@app.post("/api/admin/fruits")
def add_fruit(item: FruitCreate, password: str = Query(...)):
    if password != ADMIN_PASS:
        raise HTTPException(status_code=401, detail="비밀번호가 일치하지 않습니다.")
    try:
        new_item = {
            "name": item.name,
            "price": item.price,
            "stock": item.stock,
            "max_stock": item.stock,
            "img": item.img,
            "description": item.description
        }
        res = supabase.table("fruit_items").insert(new_item).execute()
        return {"status": "success", "data": res.data}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# 4. 과일 재고 수정
@app.put("/api/admin/fruits/{fruit_id}/stock")
def update_fruit_stock(fruit_id: int, data: StockUpdate, password: str = Query(...)):
    if password != ADMIN_PASS:
        raise HTTPException(status_code=401, detail="비밀번호가 일치하지 않습니다.")
    try:
        update_dict = {"stock": data.stock}
        if data.max_stock is not None:
            update_dict["max_stock"] = data.max_stock
        res = supabase.table("fruit_items").update(update_dict).eq("id", fruit_id).execute()
        return {"status": "success", "data": res.data}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# 5. 과일 품목 삭제
@app.delete("/api/admin/fruits/{fruit_id}")
def delete_fruit(fruit_id: int, password: str = Query(...)):
    if password != ADMIN_PASS:
        raise HTTPException(status_code=401, detail="비밀번호가 일치하지 않습니다.")
    try:
        res = supabase.table("fruit_items").delete().eq("id", fruit_id).execute()
        return {"status": "success", "data": res.data}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# 6. 손님 과일 예약 / 배달 주문 신청
@app.post("/api/orders")
def create_order(order: OrderCreate):
    try:
        # 배달 시간 검증 (오후 12시 이후 금지)
        now_kst = get_kST_time()
        if order.order_type == "배달" and now_kst.hour >= 12:
            raise HTTPException(status_code=400, detail="금일 배달 주문이 마감되었습니다. (오후 12시까지 가능)")

        # 과일 목록 가져오기
        fruits_res = supabase.table("fruit_items").select("*").order("id", desc=False).execute()
        fruits = fruits_res.data or []

        if order.fruit_index < 0 or order.fruit_index >= len(fruits):
            raise HTTPException(status_code=400, detail="유효하지 않은 과일 품목입니다.")

        target_fruit = fruits[order.fruit_index]
        
        # 재고 확인
        if target_fruit["stock"] < order.qty:
            raise HTTPException(status_code=400, detail=f"재고가 부족합니다. (현재 남은 재고: {target_fruit['stock']}개)")

        # 금액 및 배달비 계산
        fruit_total = target_fruit["price"] * order.qty
        delivery_fee = 3000 if order.order_type == "배달" else 0
        total_price = fruit_total + delivery_fee

        order_time = order.time_str if order.time_str else get_kST_time_str()

        # 주문 데이터 생성
        new_order = {
            "order_type": order.order_type,
            "kakao_nickname": order.kakao_nickname.strip(),
            "name": order.name.strip(),
            "phone": order.phone.strip(),
            "address": order.address.strip() if order.address else "",
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

        # 차감 재고 업데이트
        new_stock = target_fruit["stock"] - order.qty
        supabase.table("fruit_items").update({"stock": new_stock}).eq("id", target_fruit["id"]).execute()

        return {"status": "success", "data": order_res.data}
    except HTTPException as he:
        raise he
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# 7. 손님 전용 '내 주문 조회'
@app.get("/api/my-orders")
def get_my_orders(kakao_nickname: str = Query(...), name: str = Query(...)):
    try:
        nickname_clean = kakao_nickname.strip()
        name_clean = name.strip()

        orders_res = supabase.table("orders").select("*").eq("kakao_nickname", nickname_clean).eq("name", name_clean).order("id", desc=True).execute()
        return {"orders": orders_res.data or []}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# 8. 손님 직접 주문 취소 (입금대기/접수완료 상태만)
@app.delete("/api/my-orders/{order_id}")
def cancel_my_order(order_id: int, kakao_nickname: str = Query(...), name: str = Query(...)):
    try:
        nickname_clean = kakao_nickname.strip()
        name_clean = name.strip()

        # 주문 존재 여부 확인
        order_res = supabase.table("orders").select("*").eq("id", order_id).eq("kakao_nickname", nickname_clean).eq("name", name_clean).execute()
        if not order_res.data:
            raise HTTPException(status_code=404, detail="해당 주문을 찾을 수 없습니다.")

        order_data = order_res.data[0]

        if order_data["status"] not in ["입금대기", "접수완료"]:
            raise HTTPException(status_code=400, detail="이미 처리되었거나 판매완료된 주문은 취소할 수 없습니다. 매장에 문의해 주세요.")

        # 재고 복구
        fruit_name = order_data.get("fruit_name")
        qty = order_data.get("qty", 1)
        
        if fruit_name:
            f_res = supabase.table("fruit_items").select("*").eq("name", fruit_name).execute()
            if f_res.data:
                fruit_item = f_res.data[0]
                restored_stock = fruit_item["stock"] + qty
                supabase.table("fruit_items").update({"stock": restored_stock}).eq("id", fruit_item["id"]).execute()

        # 주문 삭제
        supabase.table("orders").delete().eq("id", order_id).execute()
        return {"status": "success", "message": "주문이 정상적으로 취소되고 재고가 복구되었습니다."}
    except HTTPException as he:
        raise he
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# 9. 사장님 주문 관리 데이터 조회 (일반 예약 + 배달 주문 구분)
@app.get("/api/admin/orders")
def get_admin_orders(password: str = Query(...)):
    if password != ADMIN_PASS:
        raise HTTPException(status_code=401, detail="비밀번호가 일치하지 않습니다.")
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

# 10. 사장님 주문 상태 변경
@app.put("/api/admin/orders/{order_id}")
def update_order_status(order_id: int, status: str = Query(...), password: str = Query(...)):
    if password != ADMIN_PASS:
        raise HTTPException(status_code=401, detail="비밀번호가 일치하지 않습니다.")
    try:
        now_time_str = get_kST_time_str()
        update_data = {
            "status": status,
            "status_changed_time": now_time_str
        }
        res = supabase.table("orders").update(update_data).eq("id", order_id).execute()
        return {"status": "success", "data": res.data}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# 11. 사장님 주문 삭제/취소 (재고 복구 포함)
@app.delete("/api/admin/orders/{order_id}")
def delete_admin_order(order_id: int, password: str = Query(...)):
    if password != ADMIN_PASS:
        raise HTTPException(status_code=401, detail="비밀번호가 일치하지 않습니다.")
    try:
        order_res = supabase.table("orders").select("*").eq("id", order_id).execute()
        if order_res.data:
            order_data = order_res.data[0]
            # 판매완료건이 아닌 경우에만 재고 복구
            if order_data.get("status") != "판매완료":
                fruit_name = order_data.get("fruit_name")
                qty = order_data.get("qty", 1)
                if fruit_name:
                    f_res = supabase.table("fruit_items").select("*").eq("name", fruit_name).execute()
                    if f_res.data:
                        fruit_item = f_res.data[0]
                        supabase.table("fruit_items").update({"stock": fruit_item["stock"] + qty}).eq("id", fruit_item["id"]).execute()

        res = supabase.table("orders").delete().eq("id", order_id).execute()
        return {"status": "success", "data": res.data}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
