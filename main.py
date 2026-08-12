import os
import re
from typing import List, Optional, Any
from datetime import datetime, timedelta, timezone
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from supabase import create_client, Client

app = FastAPI(title="하루마켓 흑석점 API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

SUPABASE_URL = os.getenv("SUPABASE_URL", "https://fohjmqpxjoetpgeigcsj.supabase.co")
SUPABASE_KEY = os.getenv("SUPABASE_KEY", "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...") 
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

ADMIN_PASSWORD = "788599"

def get_kst_time_str():
    kst = timezone(timedelta(hours=9))
    now = datetime.now(kst)
    return now.strftime("%Y. %m. %d. %p %I:%M").replace("AM", "오전").replace("PM", "오후")

class FruitItem(BaseModel):
    id: Optional[int] = None
    name: str
    price: int
    event_price: Optional[int] = 0
    is_event: Optional[bool] = False
    stock: int
    max_stock: Optional[int] = None
    available_day: Optional[str] = "today"
    img: Optional[str] = ""
    detail_imgs: Optional[Any] = []
    description: Optional[str] = ""
    hide_stock: Optional[bool] = False
    is_hidden: Optional[bool] = False

class FruitUpdate(BaseModel):
    name: Optional[str] = None
    price: Optional[int] = None
    event_price: Optional[int] = None
    is_event: Optional[bool] = None
    stock: Optional[int] = None
    max_stock: Optional[int] = None
    available_day: Optional[str] = None
    img: Optional[str] = None
    detail_imgs: Optional[Any] = None
    description: Optional[str] = None
    hide_stock: Optional[bool] = None
    is_hidden: Optional[bool] = None

class OrderItemInput(BaseModel):
    fruit_id: int
    fruit_name: str
    price: int
    qty: int
    available_day: Optional[str] = "today"

class OrderCreate(BaseModel):
    order_type: str
    kakao_nickname: str
    name: str
    address: Optional[str] = ""
    door_password: Optional[str] = ""
    method: Optional[str] = "계좌이체"
    items: List[OrderItemInput]

class StoreMetaUpdate(BaseModel):
    notice: Optional[str] = None
    account: Optional[str] = None
    owner: Optional[str] = None
    hours: Optional[str] = None
    notice_img: Optional[str] = None
    delivery_cutoff: Optional[str] = None

def restore_order_stock(order_id: int):
    try:
        o_res = supabase.table("orders").select("*").eq("id", order_id).execute()
        if not o_res.data:
            return
        order = o_res.data[0]
        raw_fruit_str = order.get("fruit", "")
        if not raw_fruit_str:
            return

        items_str_list = [s.strip() for s in raw_fruit_str.split(",") if s.strip()]
        for item_str in items_str_list:
            qty_match = re.search(r'x(\d+)개', item_str)
            item_qty = int(qty_match.group(1)) if qty_match else 1
            pure_name = re.sub(r'\s*x\d+개.*', '', item_str).strip()
            # [수령일자] 태그 제거 후 순수 과일명만 파싱
            pure_name = re.sub(r'\[.*?\]\s*', '', pure_name).strip()

            f_res = supabase.table("fruit_items").select("id, stock").eq("name", pure_name).execute()
            if f_res.data:
                f_id = f_res.data[0]["id"]
                curr_stock = f_res.data[0]["stock"]
                supabase.table("fruit_items").update({"stock": curr_stock + item_qty}).eq("id", f_id).execute()
    except Exception as e:
        print(f"재고 복구 오류: {str(e)}")

# ==================== [API] ====================

@app.get("/")
def read_root():
    return {"status": "ok", "message": "하루마켓 API 가동 중"}

@app.get("/api/init-data")
def get_init_data():
    try:
        fruits_res = supabase.table("fruit_items").select("*").order("id", desc=False).execute()
        meta_res = supabase.table("store_meta").select("*").eq("id", 1).execute()
        
        meta_data = meta_res.data[0] if meta_res.data else {
            "notice": "오늘도 신선한 과일 준비되어 있습니다 🍊",
            "account": "새마을금고 9003-3009-5914-9",
            "owner": "하루마켓(손현모)",
            "hours": "10:00 - 21:30",
            "notice_img": ""
        }
        
        return {
            "fruits": fruits_res.data or [],
            "meta": meta_data,
            "is_delivery_available": True
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# 💡 [핵심 수령 일자별 주문서 분할 생성 처리]
@app.post("/api/orders")
def create_order(order: OrderCreate):
    try:
        # 1. 수령 일자별로 아이템 그룹핑 (Grouping by available_day)
        items_by_day = {}
        for item in order.items:
            day_key = item.available_day or "today"
            if day_key not in items_by_day:
                items_by_day[day_key] = []
            items_by_day[day_key].append(item)

        created_orders = []
        is_first_order = True

        for day_key, group_items in items_by_day.items():
            total_fruit_price = sum(item.price * item.qty for item in group_items)
            
            # 첫 번째 주문서에만 배달비 부과 (배달 중복 청구 방지)
            delivery_fee = (2500 if order.order_type == "배달" else 0) if is_first_order else 0
            is_first_order = False
            
            final_total_price = total_fruit_price + delivery_fee

            # 수령 일자 명시 태그 추가
            day_tag = " [오늘 수령]" if day_key == "today" else f" [{day_key} 수령]"
            fruit_summary_list = [f"{item.fruit_name} x{item.qty}개" for item in group_items]
            fruit_summary_str = ", ".join(fruit_summary_list) + day_tag

            new_order = {
                "order_type": order.order_type,
                "kakao_nickname": order.kakao_nickname,
                "name": order.name,
                "address": order.address,
                "door_password": order.door_password,
                "fruit": fruit_summary_str,
                "total_price": final_total_price,
                "delivery_fee": delivery_fee,
                "method": order.method,
                "status": "입금대기" if order.method == "계좌이체" else "접수완료",
                "time_str": get_kst_time_str()
            }

            res = supabase.table("orders").insert(new_order).execute()
            if res.data:
                created_orders.append(res.data[0])

            # 재고 차감
            for item in group_items:
                f_res = supabase.table("fruit_items").select("stock").eq("id", item.fruit_id).execute()
                if f_res.data:
                    curr_stock = f_res.data[0]["stock"]
                    new_stock = max(0, curr_stock - item.qty)
                    supabase.table("fruit_items").update({"stock": new_stock}).eq("id", item.fruit_id).execute()

        return {"message": "주문 접수 완료 (일자별 분할 생성)", "orders": created_orders}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"주문 처리 실패: {str(e)}")

@app.get("/api/my-orders")
def get_my_orders(kakao_nickname: str = Query(...), name: str = Query(...)):
    try:
        res = supabase.table("orders").select("*").eq("kakao_nickname", kakao_nickname).eq("name", name).order("id", desc=True).execute()
        return {"orders": res.data or []}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.delete("/api/my-orders/{order_id}")
def cancel_my_order(order_id: int, kakao_nickname: str = Query(...), name: str = Query(...)):
    try:
        o_res = supabase.table("orders").select("*").eq("id", order_id).execute()
        if not o_res.data:
            raise HTTPException(status_code=404, detail="주문을 찾을 수 없습니다.")
        order = o_res.data[0]
        
        if order["kakao_nickname"] != kakao_nickname or order["name"] != name:
            raise HTTPException(status_code=403, detail="본인 주문만 취소 가능합니다.")
            
        if order["status"] not in ["입금대기", "접수완료"]:
            raise HTTPException(status_code=400, detail="이미 처리된 주문은 취소할 수 없습니다.")

        restore_order_stock(order_id)
        supabase.table("orders").delete().eq("id", order_id).execute()
        return {"message": "주문 취소 및 재고 복구 완료"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/admin/orders")
def get_admin_orders(password: str = Query(...)):
    if password != ADMIN_PASSWORD:
        raise HTTPException(status_code=401, detail="비밀번호 오류")
    try:
        pending_res = supabase.table("orders").select("*").neq("status", "판매완료").order("id", desc=True).execute()
        completed_res = supabase.table("orders").select("*").eq("status", "판매완료").order("id", desc=True).execute()
        
        all_pending = pending_res.data or []
        pickup_pending = [o for o in all_pending if o.get("order_type") != "배달"]
        delivery_pending = [o for o in all_pending if o.get("order_type") == "배달"]

        return {
            "pending": pickup_pending,
            "delivery_orders": delivery_pending,
            "completed": completed_res.data or []
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.put("/api/admin/orders/{order_id}")
def update_order_status(order_id: int, status: str = Query(...), password: str = Query(...)):
    if password != ADMIN_PASSWORD:
        raise HTTPException(status_code=401, detail="비밀번호 오류")
    try:
        update_payload = {"status": status}
        if status == "판매완료":
            update_payload["status_changed_time"] = get_kst_time_str()
            
        res = supabase.table("orders").update(update_payload).eq("id", order_id).execute()
        return {"message": "상태 변경 완료", "order": res.data}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.delete("/api/admin/orders/{order_id}")
def delete_admin_order(order_id: int, password: str = Query(...)):
    if password != ADMIN_PASSWORD:
        raise HTTPException(status_code=401, detail="비밀번호 오류")
    try:
        restore_order_stock(order_id)
        supabase.table("orders").delete().eq("id", order_id).execute()
        return {"message": "주문 취소 및 재고 복구 완료"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# 🛡️ available_day DB 컬럼 유무 대비 예외안전 품목 추가 API
@app.post("/api/admin/fruits")
def create_fruit_item(item: FruitItem, password: str = Query(...)):
    if password != ADMIN_PASSWORD:
        raise HTTPException(status_code=401, detail="비밀번호 오류")
    try:
        new_item = {
            "name": item.name,
            "price": item.price,
            "event_price": item.event_price or 0,
            "is_event": item.is_event or False,
            "stock": item.stock,
            "max_stock": item.stock,
            "available_day": item.available_day or "today",
            "img": item.img,
            "detail_imgs": item.detail_imgs,
            "description": item.description,
            "hide_stock": item.hide_stock or False,
            "is_hidden": item.is_hidden or False
        }
        try:
            res = supabase.table("fruit_items").insert(new_item).execute()
        except Exception:
            # DB에 available_day 컬럼이 아직 없을 경우 자동으로 제외하고 재시도하는 안전장치!
            new_item.pop("available_day", None)
            res = supabase.table("fruit_items").insert(new_item).execute()

        return {"message": "새 품목 추가 완료", "data": res.data}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.put("/api/admin/fruits/{fruit_id}")
def update_fruit_item(fruit_id: int, item_data: FruitUpdate, password: str = Query(...)):
    if password != ADMIN_PASSWORD:
        raise HTTPException(status_code=401, detail="비밀번호 오류")
    try:
        update_dict = {k: v for k, v in item_data.dict().items() if v is not None}
        if not update_dict:
            return {"message": "수정 내용 없음"}
            
        try:
            res = supabase.table("fruit_items").update(update_dict).eq("id", fruit_id).execute()
        except Exception:
            update_dict.pop("available_day", None)
            res = supabase.table("fruit_items").update(update_dict).eq("id", fruit_id).execute()

        return {"message": "품목 수정 완료", "data": res.data}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.delete("/api/admin/fruits/{fruit_id}")
def delete_fruit_item(fruit_id: int, password: str = Query(...)):
    if password != ADMIN_PASSWORD:
        raise HTTPException(status_code=401, detail="비밀번호 오류")
    try:
        supabase.table("fruit_items").delete().eq("id", fruit_id).execute()
        return {"message": "품목 삭제 완료"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.put("/api/admin/settings")
def update_store_settings(meta: StoreMetaUpdate, password: str = Query(...)):
    if password != ADMIN_PASSWORD:
        raise HTTPException(status_code=401, detail="비밀번호 오류")
    try:
        update_dict = {k: v for k, v in meta.dict().items() if v is not None}
        res = supabase.table("store_meta").update(update_dict).eq("id", 1).execute()
        return {"message": "설정 저장 완료", "data": res.data}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
