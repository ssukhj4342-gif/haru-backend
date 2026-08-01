# --- Request Models 수정/추가 ---
class FruitCreate(BaseModel):
    name: str
    price: int
    stock: int
    img: Optional[str] = ""
    detail_img: Optional[str] = ""  # 상세설명용 사진 추가
    description: Optional[str] = ""
    hide_stock: Optional[bool] = False # 개별 재고 숨김 여부 추가

class FruitUpdate(BaseModel):
    name: Optional[str] = None
    price: Optional[int] = None
    stock: Optional[int] = None
    img: Optional[str] = None
    detail_img: Optional[str] = None
    description: Optional[str] = None
    hide_stock: Optional[bool] = None

class OrderCreate(BaseModel):
    order_type: str # '픽업' 또는 '배달'
    kakao_nickname: str
    name: str
    phone: str
    address: Optional[str] = ""
    door_password: Optional[str] = "" # 공동현관 비밀번호 추가
    fruit_index: int
    qty: int
    method: str
    time_str: Optional[str] = ""

# --- 품목 추가 API 수정 ---
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
            "detail_img": item.detail_img,
            "description": item.description,
            "hide_stock": item.hide_stock
        }
        res = supabase.table("fruit_items").insert(new_item).execute()
        return {"status": "success", "data": res.data}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# --- 품목 정보/재고/숨김 상태 수정 통합 API ---
@app.put("/api/admin/fruits/{fruit_id}")
def update_fruit(fruit_id: int, item: FruitUpdate, password: str = Query(...)):
    if password != ADMIN_PASS:
        raise HTTPException(status_code=401, detail="비밀번호가 일치하지 않습니다.")
    try:
        update_data = item.dict(exclude_unset=True)
        res = supabase.table("fruit_items").update(update_data).eq("id", fruit_id).execute()
        return {"status": "success", "data": res.data}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# --- 주문 생성 API 내 new_order 부분에 door_password 추가 ---
# (new_order 사전 객체 안에 아래 줄 추가)
# "door_password": order.door_password.strip() if order.door_password else "",
