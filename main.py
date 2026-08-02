import os
from typing import List, Optional, Any
from datetime import datetime, timedelta, timezone
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from supabase import create_client, Client

app = FastAPI(title="하루마켓 흑석점 API")

# CORS 설정 (프론트엔드 통신 허용)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Supabase 연결 설정 (환경변수 또는 기본값)
SUPABASE_URL = os.getenv("SUPABASE_URL", "https://fohjmqpxjoetpgeigcsj.supabase.co")
SUPABASE_KEY = os.getenv("SUPABASE_KEY", "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...") # 실제 키 자동 적용
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# 관리자 비밀번호
ADMIN_PASSWORD = "788599"

# 한국 표준시(KST) 변환 함수
def get_kst_time_str():
    kst = timezone(timedelta(hours=9))
    now = datetime.now(kst)
    return now.strftime("%Y. %m. %d. %p %I:%M").replace("AM", "오전").replace("PM", "오후")

# Pydantic 데이터 모델 정의
class FruitItem(BaseModel):
    id: Optional[int] = None
    name: str
    price: int
    event_price: Optional[int] = 0
    is_event: Optional[bool] = False
    stock: int
    max_stock: Optional[int] = None
    img: Optional[str] = ""
    detail_imgs: Optional[Any] = []
    description: Optional[str] = ""
    hide_stock: Optional[bool] = False

class FruitUpdate(BaseModel):
    name: Optional[str] = None
    price: Optional[int] = None
    event_price: Optional[int] = None
    is_event: Optional[bool] = None
    stock: Optional[int] = None
    max_stock: Optional[int] = None
    img: Optional[str] = None
    detail_imgs: Optional[Any] = None
    description: Optional[str] = None
    hide_stock: Optional[bool] = None

class OrderItemInput(BaseModel):
    fruit_id: int
    fruit_name: str
    price: int
    qty: int

class OrderCreate(BaseModel):
    order_type: str  # "픽업" 또는 "배달"
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

# ==================== [API 엔드포인트] ====================

@app.get("/")
def read_root():
    return {"status": "ok", "message": "하루마켓 흑석점 백엔드가 가동 중입니다. 🍊"}

# 1. 초기 데이터 불어오기 (손님/사장님 공통)
@app.get("/api/init-data")
def get_init_data():
    try:
        fruits_res = supabase.table("fruit_items").select("*").order("id", desc=False).execute()
        meta_res = supabase.table("store_meta").select("*").eq("id", 1).execute()
        
        meta_data = meta_res.data[0] if meta_res.data else {
            "notice": "오늘도 신선한 과일 준비되어 있습니다 🍊",
            "account": "카카오뱅크 1111-22-3333333",
            "owner": "김혁진",
            "hours": "09:00 - 20:00",
            "notice_img": ""
        }
        
        return {
            "fruits": fruits_res.data or [],
            "meta": meta_data,
            "is_delivery_available": True
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# 2. 주문 등록 (손님)
@app.post("/api/orders")
def create_order(order: OrderCreate):
    try:
        total_fruit_price = sum(item.price * item.qty for item in order.items)
        delivery_fee = 3000 if order.order_type == "배달" else 0
        final_total_price = total_fruit_price + delivery_fee

        fruit_summary_list = [f"{item.fruit_name} x{item.qty}개" for item in order.items]
        fruit_summary_str = ", ".join(fruit_summary_list)

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

        # 주문 DB 차곡차곡 저장
        res = supabase.table("orders").insert(new_order).execute()

        # 재고 차감 처리
        for item in order.items:
            f_res = supabase.table("fruit_items").select("stock").eq("id", item.fruit_id).execute()
            if f_res.data:
                curr_stock = f_res.data[0]["stock"]
                new_stock = max(0, curr_stock - item.qty)
                supabase.table("fruit_items").update({"stock": new_stock}).eq("id", item.fruit_id).execute()

        return {"message": "주문 접수 완료", "order": res.data[0] if res.data else {}}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"주문 처리 실패: {str(e)}")

# 3. 내 주문 내역 조회 (손님)
@app.get("/api/my-orders")
def get_my_orders(kakao_nickname: str = Query(...), name: str = Query(...)):
    try:
        res = supabase.table("orders").select("*").eq("kakao_nickname", kakao_nickname).eq("name", name).order("id", desc=True).execute()
        return {"orders": res.data or []}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# 4. 내 주문 취소 (손님)
@app.delete("/api/my-orders/{order_id}")
def cancel_my_order(order_id: int, kakao_nickname: str = Query(...), name: str = Query(...)):
    try:
        o_res = supabase.table("orders").select("*").eq("id", order_id).execute()
        if not o_res.data:
            raise HTTPException(status_code=404, detail="주문을 찾을 수 없습니다.")
        order = o_res.data[0]
        
        if order["kakao_nickname"] != kakao_nickname or order["name"] != name:
            raise HTTPException(status_code=403, detail="본인의 주문만 취소할 수 있습니다.")
            
        if order["status"] not in ["입금대기", "접수완료"]:
            raise HTTPException(status_code=400, detail="이미 처리 중이거나 완료된 주문은 취소할 수 없습니다.")

        supabase.table("orders").delete().eq("id", order_id).execute()
        return {"message": "주문이 취소되었습니다."}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# ==================== [사장님 전용 API] ====================

# 5. 사장님 주문 현황 목록 조회
@app.get("/api/admin/orders")
def get_admin_orders(password: str = Query(...)):
    if password != ADMIN_PASSWORD:
        raise HTTPException(status_code=401, detail="비밀번호가 틀렸습니다.")
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

# 6. 사장님 주문 상태 변경 (입금확인 / 완료 등)
@app.put("/api/admin/orders/{order_id}")
def update_order_status(order_id: int, status: str = Query(...), password: str = Query(...)):
    if password != ADMIN_PASSWORD:
        raise HTTPException(status_code=401, detail="비밀번호가 틀렸습니다.")
    try:
        update_payload = {"status": status}
        if status == "판매완료":
            update_payload["status_changed_time"] = get_kst_time_str()
            
        res = supabase.table("orders").update(update_payload).eq("id", order_id).execute()
        return {"message": "상태 변경 완료", "order": res.data}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# 7. 사장님 주문 취소/삭제
@app.delete("/api/admin/orders/{order_id}")
def delete_admin_order(order_id: int, password: str = Query(...)):
    if password != ADMIN_PASSWORD:
        raise HTTPException(status_code=401, detail="비밀번호가 틀렸습니다.")
    try:
        supabase.table("orders").delete().eq("id", order_id).execute()
        return {"message": "주문 삭제 완료"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# 8. 사장님 과일 품목 신규 추가
@app.post("/api/admin/fruits")
def create_fruit_item(item: FruitItem, password: str = Query(...)):
    if password != ADMIN_PASSWORD:
        raise HTTPException(status_code=401, detail="비밀번호가 틀렸습니다.")
    try:
        new_item = {
            "name": item.name,
            "price": item.price,
            "event_price": item.event_price or 0,
            "is_event": item.is_event or False,
            "stock": item.stock,
            "max_stock": item.stock,
            "img": item.img,
            "detail_imgs": item.detail_imgs,
            "description": item.description,
            "hide_stock": item.hide_stock or False
        }
        res = supabase.table("fruit_items").insert(new_item).execute()
        return {"message": "새 품목 추가 완료", "data": res.data}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# 9. 사장님 과일 품목 정보 수정 (★ 2단계 요청부분: 이벤트/재고/가격 수정 핵심!)
@app.put("/api/admin/fruits/{fruit_id}")
def update_fruit_item(fruit_id: int, item_data: FruitUpdate, password: str = Query(...)):
    if password != ADMIN_PASSWORD:
        raise HTTPException(status_code=401, detail="비밀번호가 틀렸습니다.")
    try:
        update_dict = {k: v for k, v in item_data.dict().items() if v is not None}
        if not update_dict:
            return {"message": "수정할 데이터가 없습니다."}
            
        res = supabase.table("fruit_items").update(update_dict).eq("id", fruit_id).execute()
        return {"message": "품목 수정 완료", "data": res.data}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# 10. 사장님 과일 품목 영구 삭제
@app.delete("/api/admin/fruits/{fruit_id}")
def delete_fruit_item(fruit_id: int, password: str = Query(...)):
    if password != ADMIN_PASSWORD:
        raise HTTPException(status_code=401, detail="비밀번호가 틀렸습니다.")
    try:
        supabase.table("fruit_items").delete().eq("id", fruit_id).execute()
        return {"message": "품목 삭제 완료"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# 11. 사장님 매장 기본 설정 수정 (공지, 계좌, 영업시간 등)
@app.put("/api/admin/settings")
def update_store_settings(meta: StoreMetaUpdate, password: str = Query(...)):
    if password != ADMIN_PASSWORD:
        raise HTTPException(status_code=401, detail="비밀번호가 틀렸습니다.")
    try:
        update_dict = {k: v for k, v in meta.dict().items() if v is not None}
        res = supabase.table("store_meta").update(update_dict).eq("id", 1).execute()
        return {"message": "설정 저장 완료", "data": res.data}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
