"""
Multi-PK overlay server.
Features kept:
- TikTok Live connection / gift scoring
- Idol management
- Timer
- Multi-PK 3 / 4 / 5 players
- Rank overlay + PK overlay

Run:
    pip install -r requirements.txt
    python server.py
"""
import asyncio
import json
import uuid
import logging
import re
from html import unescape
from typing import Optional
from urllib.parse import quote
from urllib.request import Request, urlopen

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from TikTokLive import TikTokLiveClient
from TikTokLive.events import ConnectEvent, DisconnectEvent, GiftEvent

logging.getLogger("TikTokLive").setLevel(logging.CRITICAL)

app = FastAPI()
app.mount("/static", StaticFiles(directory="static"), name="static")

state = {
    "room": None,
    "connected": False,
    "last_error": None,
    "idols": [],
    "timer": {
        "duration": 120,
        "remaining": 120,
        "running": False,
        "finished": False,
    },
    "pk": {
        "enabled": False,
        "num_positions": 3,
        "round": 1,
        "status": "standby",  # standby | running | paused | finished
        "positions": [],
        "assignments": {},
    },
    "accepting_gifts": False,
    "gift_catalog": [],
    "gift_catalog_username": "",
    "gift_catalog_error": None,
    "last_gift_debug": {},
}

sockets: list[WebSocket] = []
current_client: Optional[TikTokLiveClient] = None
current_task: Optional[asyncio.Task] = None
# MultiPK dùng DUY NHẤT một phòng TikTok Live.
# Mỗi user trong phòng được "khóa" vào một vị trí sau khi gửi gift_id kích hoạt.
pk_assignments: dict[str, dict] = {}
# Theo dõi streak để không bỏ mất gift đầu tiên và không cộng trùng các event lặp.
pk_gift_streaks: dict[tuple[str, str], int] = {}


def default_pk_position(index: int) -> dict:
    return {
        "id": uuid.uuid4().hex[:8],
        "idol_id": "",
        "name": f"Player {index + 1}",
        "tiktok_id": "",
        "avatar": "",
        "gift_id": "",
        "gift_img": "",
        "score": 0,
    }


def make_pk_positions(n: int, old=None) -> list[dict]:
    old = old or []
    result = []
    for i in range(n):
        p = dict(old[i]) if i < len(old) else default_pk_position(i)
        p["id"] = p.get("id") or uuid.uuid4().hex[:8]
        p["name"] = p.get("name") or f"Player {i + 1}"
        p["tiktok_id"] = str(p.get("tiktok_id") or "")
        p["avatar"] = p.get("avatar") or ""
        p["gift_id"] = str(p.get("gift_id") or "")
        p["gift_img"] = p.get("gift_img") or ""
        p["score"] = max(0, int(p.get("score", 0)))
        result.append(p)
    return result


state["pk"]["positions"] = make_pk_positions(3)


async def broadcast_state():
    sync_pk_from_idols()
    payload = json.dumps({"type": "state", "data": state}, ensure_ascii=False)
    dead = []
    for ws in sockets:
        try:
            await ws.send_text(payload)
        except Exception:
            dead.append(ws)
    for ws in dead:
        if ws in sockets:
            sockets.remove(ws)


def get_idol(idol_id: str):
    return next((i for i in state["idols"] if i["id"] == idol_id), None)


def get_active_idol():
    return next((i for i in state["idols"] if i.get("active")), None)


def sync_pk_from_idols():
    """PK positions reference the shared Idol records; refresh display fields from them."""
    for pos in state["pk"].get("positions", []):
        idol = get_idol(pos.get("idol_id", "")) if pos.get("idol_id") else None
        if idol:
            pos["name"] = idol.get("name", pos.get("name", ""))
            pos["tiktok_id"] = normalize_tiktok_id(idol.get("tiktok_id", pos.get("tiktok_id", ""))) if "normalize_tiktok_id" in globals() else str(idol.get("tiktok_id", pos.get("tiktok_id", "")))
            pos["avatar"] = idol.get("avatar", pos.get("avatar", "")) or pos.get("avatar", "")


def add_pk_points(index: int, points: int):
    if 0 <= index < len(state["pk"]["positions"]) and points != 0:
        pos = state["pk"]["positions"][index]
        pos["score"] = max(0, int(pos.get("score", 0)) + int(points))
        idol_id = pos.get("idol_id")
        idol = get_idol(idol_id) if idol_id else None
        if idol and points > 0:
            idol["score"] = max(0, int(idol.get("score", 0)) + int(points))


# --------------------------------------------------------------------------
# TikTok Live
# --------------------------------------------------------------------------

async def disconnect_room():
    global current_client, current_task
    if current_client is not None:
        try:
            await current_client.disconnect()
        except Exception:
            pass
    if current_task is not None:
        current_task.cancel()
    current_client = None
    current_task = None
    state["connected"] = False
    reset_pk_assignments() if "pk_assignments" in globals() else None


def reset_pk_assignments():
    pk_assignments.clear()
    pk_gift_streaks.clear()
    state["pk"]["assignments"] = {}


def get_gift_id(event: GiftEvent) -> str:
    """Lấy gift_id ổn định từ nhiều phiên bản TikTokLive."""
    gift = getattr(event, "gift", None)
    candidates = [
        getattr(gift, "id", None),
        getattr(gift, "gift_id", None),
        getattr(gift, "giftId", None),
        getattr(event, "gift_id", None),
        getattr(event, "giftId", None),
    ]
    for value in candidates:
        if value is not None and str(value).strip():
            return str(value).strip()
    return ""


def get_gift_diamonds(event: GiftEvent) -> int:
    """Lấy giá trị xu/gift, tương thích các object GiftEvent khác nhau."""
    gift = getattr(event, "gift", None)
    for obj, attr in ((gift, "diamond_count"), (gift, "diamondCount"), (event, "diamond_count"), (event, "diamondCount")):
        value = getattr(obj, attr, None) if obj is not None else None
        if value is not None:
            try:
                return max(0, int(value))
            except (TypeError, ValueError):
                pass
    return 0


def get_sender_key(event: GiftEvent) -> str:
    user = getattr(event, "user", None)
    # unique_id ổn định và dễ đọc; user_id là fallback nếu thư viện không có unique_id.
    for attr in ("unique_id", "user_id", "id"):
        value = getattr(user, attr, None) if user is not None else None
        if value:
            return str(value)
    return "unknown"


def get_sender_name(event: GiftEvent) -> str:
    user = getattr(event, "user", None)
    for attr in ("nickname", "unique_id", "user_id"):
        value = getattr(user, attr, None) if user is not None else None
        if value:
            return str(value)
    return "Unknown"


def find_position_by_trigger_gift(gift_id: str) -> Optional[int]:
    if not gift_id:
        return None
    for idx, pos in enumerate(state["pk"]["positions"]):
        if str(pos.get("gift_id") or "") == gift_id:
            return idx
    return None


def route_pk_gift(event: GiftEvent) -> Optional[int]:
    """
    Luật PK: một phòng Live duy nhất, nhưng nhiều người chơi song song.

    1) Nếu user gửi một gift_id đang được cấu hình ở thanh PK, gift đó là
       "gift chọn phe" và user được gán/chuyển ngay vào vị trí tương ứng.
    2) Gift chọn phe VẪN TÍNH ĐIỂM cho vị trí vừa được chọn.
    3) Sau khi được gán, mọi gift tiếp theo của user (bất kể giá trị/gift_id)
       đều cộng cho vị trí đó.
    4) Nếu user gửi một gift_id chọn phe khác, user chuyển sang vị trí mới;
       chính gift chuyển phe đó cũng tính điểm cho vị trí mới.
    5) Gift không phải gift chọn phe của user chưa được gán thì bỏ qua.
    """
    if state["pk"]["status"] != "running":
        return None

    sender_key = get_sender_key(event)
    sender_name = get_sender_name(event)
    gift_id = get_gift_id(event)
    trigger_index = find_position_by_trigger_gift(gift_id)

    # Gift nhỏ trên thanh PK dùng để chọn/chuyển người nhận điểm.
    if trigger_index is not None:
        assignment = {
            "position": trigger_index,
            "user_id": sender_key,
            "user": sender_name,
            "trigger_gift_id": gift_id,
        }
        pk_assignments[sender_key] = assignment
        state["pk"]["assignments"] = dict(pk_assignments)
        # Gift dùng để chọn/chuyển phe cũng là một gift bình thường và
        # phải được cộng điểm cho phe vừa chọn.
        return trigger_index

    assignment = pk_assignments.get(sender_key)
    if not assignment:
        return None
    return int(assignment["position"])


def clear_pk_connections_state():
    state["connected"] = False
    state["last_error"] = None


async def disconnect_pk_rooms():
    """PK không có room riêng: chỉ xóa mapping user -> vị trí."""
    reset_pk_assignments()
    for pos in state["pk"]["positions"]:
        pos["connected"] = False
        pos["live_error"] = None


async def connect_room(unique_id: str):
    # Legacy single-room connection vẫn giữ lại cho khu vực TikTok Live cũ.
    global current_client, current_task
    await disconnect_room()

    client = TikTokLiveClient(unique_id=unique_id)

    @client.on(ConnectEvent)
    async def on_connect(_event):
        state["connected"] = True
        state["last_error"] = None
        # If gift metadata was fetched during connect, expose it to the UI
        # immediately so the control panel can use the live room catalog.
        raw_catalog = getattr(client, "gift_info", None) or getattr(client, "available_gifts", None)
        catalog = _normalize_gift_catalog(raw_catalog) if raw_catalog else []
        if catalog:
            state["gift_catalog"] = catalog
            state["gift_catalog_username"] = normalize_tiktok_id(unique_id)
            state["gift_catalog_error"] = None
        await broadcast_state()

    @client.on(DisconnectEvent)
    async def on_disconnect(_event):
        state["connected"] = False
        if state["pk"]["status"] == "running":
            state["accepting_gifts"] = False
        await broadcast_state()

    @client.on(GiftEvent)
    async def on_gift(event: GiftEvent):
        if not state["accepting_gifts"]:
            return

        gift_id = get_gift_id(event)
        sender_key = get_sender_key(event)
        repeat_count = max(1, int(getattr(event, "repeat_count", 1) or 1))
        diamond_count = get_gift_diamonds(event)
        streaking = bool(getattr(event, "streaking", False))

        # TikTok có thể gửi nhiều GiftEvent cho cùng một streak.
        # Chỉ cộng phần repeat_count tăng thêm; event cuối có cùng repeat_count
        # sẽ không bị cộng lại.
        streak_key = (sender_key, gift_id or "unknown")
        previous_repeat = pk_gift_streaks.get(streak_key, 0)
        if repeat_count > previous_repeat:
            effective_repeat = repeat_count - previous_repeat
            pk_gift_streaks[streak_key] = repeat_count
        else:
            effective_repeat = 0

        # Nếu một gift không streak được gửi lại, repeat_count thường quay về 1.
        # Khi đó reset bộ đếm để lần gửi mới vẫn được tính.
        if not streaking and effective_repeat == 0:
            pk_gift_streaks[streak_key] = 1
            effective_repeat = 1

        diamonds = effective_repeat * diamond_count
        user = getattr(event, "user", None)
        state["last_gift_debug"] = {
            "gift_id": gift_id,
            "diamonds": diamonds,
            "raw_diamonds": diamond_count,
            "repeat_count": repeat_count,
            "streaking": streaking,
            "user": get_sender_name(event),
            "pk_status": state["pk"].get("status"),
            "accepting": state["accepting_gifts"],
        }

        if diamonds <= 0:
            await broadcast_state()
            return

        # PK đang chạy: một room duy nhất, route theo user đã kích hoạt
        # bằng gift_id. Gift kích hoạt chính nó cũng được cộng điểm.
        if state["pk"]["status"] == "running":
            index = route_pk_gift(event)
            if index is None:
                await broadcast_state()
                return
            add_pk_points(index, diamonds)
            await broadcast_state()
            return

        # Ngoài PK: giữ hành vi cũ, gift cộng cho idol active.
        active = get_active_idol()
        if active:
            active["score"] = max(0, int(active.get("score", 0)) + diamonds)
        await broadcast_state()


    current_client = client
    state["room"] = unique_id
    state["last_error"] = None
    current_task = asyncio.create_task(_run_client(client))
    await broadcast_state()


async def _run_client(client: TikTokLiveClient):
    try:
        try:
            await client.start(fetch_gift_info=True)
        except TypeError:
            await client.start()
    except asyncio.CancelledError:
        raise
    except Exception as e:
        state["connected"] = False
        state["last_error"] = str(e)
        await broadcast_state()


# --------------------------------------------------------------------------
# Timer
# --------------------------------------------------------------------------

async def timer_loop():
    while True:
        await asyncio.sleep(1)
        t = state["timer"]
        if not t["running"] or t["remaining"] <= 0:
            continue

        t["remaining"] -= 1
        if t["remaining"] <= 0:
            t["remaining"] = 0
            t["running"] = False
            t["finished"] = True
            state["accepting_gifts"] = False
            if state["pk"]["status"] == "running":
                state["pk"]["status"] = "finished"
                state["pk"]["enabled"] = True
                await disconnect_pk_rooms()
        await broadcast_state()


@app.on_event("startup")
async def on_startup():
    asyncio.create_task(timer_loop())


# --------------------------------------------------------------------------
# Pages
# --------------------------------------------------------------------------

@app.get("/health")
async def health():
    return {"ok": True}


@app.get("/overlay/rank")
async def overlay_rank_page():
    return FileResponse("static/overlay_rank.html")


@app.get("/overlay/pk")
async def overlay_pk_page():
    return FileResponse("static/overlay_pk.html")


@app.get("/control")
async def control_page():
    return FileResponse("static/control.html")


# --------------------------------------------------------------------------
# WebSocket
# --------------------------------------------------------------------------

@app.websocket("/ws")
async def ws_endpoint(websocket: WebSocket):
    await websocket.accept()
    sockets.append(websocket)
    await websocket.send_text(json.dumps({"type": "state", "data": state}, ensure_ascii=False))
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        if websocket in sockets:
            sockets.remove(websocket)


# --------------------------------------------------------------------------
# API models
# --------------------------------------------------------------------------

class RoomIn(BaseModel):
    unique_id: str


class IdolIn(BaseModel):
    name: str
    avatar: str = ""
    tiktok_id: str = ""


class BatchIdolIn(BaseModel):
    names: list[str]


class PointsIn(BaseModel):
    delta: int


class SetScoreIn(BaseModel):
    score: int


class DurationIn(BaseModel):
    seconds: int


class PKPositionIn(BaseModel):
    idol_id: str = ""
    name: str = ""
    tiktok_id: str = ""
    avatar: str = ""
    gift_id: str = ""
    gift_img: str = ""


class PKSetupIn(BaseModel):
    num_positions: int
    positions: list[PKPositionIn]


class PKPointsIn(BaseModel):
    index: int
    delta: int


class PKSelectIn(BaseModel):
    num_positions: int
    positions: list[PKPositionIn]


# --------------------------------------------------------------------------
# Room
# --------------------------------------------------------------------------

@app.get("/api/state")
async def api_get_state():
    return state


@app.post("/api/room")
async def api_connect_room(body: RoomIn):
    await connect_room(body.unique_id.strip())
    return {"ok": True}


@app.post("/api/room/disconnect")
async def api_disconnect_room():
    await disconnect_room()
    state["room"] = None
    await broadcast_state()
    return {"ok": True}


# --------------------------------------------------------------------------
# TikTok gift catalog
# --------------------------------------------------------------------------

def _obj_value(obj, *names, default=None):
    if obj is None:
        return default
    if isinstance(obj, dict):
        for name in names:
            if name in obj and obj[name] is not None:
                return obj[name]
        return default
    for name in names:
        try:
            value = getattr(obj, name, None)
        except Exception:
            value = None
        if value is not None:
            return value
    return default


def _gift_image_url(gift):
    image = _obj_value(gift, "image", "gift_image", "icon", default=None)
    if image is None:
        image = _obj_value(gift, "details", default=None)
        image = _obj_value(image, "image", "gift_image", "icon", default=None)
    urls = _obj_value(image, "url_list", "urlList", "urls", default=None)
    if isinstance(urls, (list, tuple)) and urls:
        return str(urls[0])
    if isinstance(urls, str):
        return urls
    if isinstance(image, str) and image.startswith("http"):
        return image
    return str(_obj_value(gift, "icon_url", "image_url", default="") or "")


def _normalize_gift_catalog(raw):
    if raw is None:
        return []
    values = list(raw.values()) if isinstance(raw, dict) else list(raw) if isinstance(raw, (list, tuple, set)) else []
    result = []
    seen = set()
    for gift in values:
        gid = _obj_value(gift, "id", "gift_id", "giftId", default="")
        if not gid:
            details = _obj_value(gift, "details", default=None)
            gid = _obj_value(details, "id", "gift_id", "giftId", default="")
        if not gid:
            continue
        gid = str(gid)
        if gid in seen:
            continue
        seen.add(gid)
        name = str(_obj_value(gift, "name", "gift_name", "giftName", default="Gift") or "Gift")
        diamonds = _obj_value(gift, "diamond_count", "diamondCount", "cost", default=0)
        try:
            diamonds = int(diamonds or 0)
        except Exception:
            diamonds = 0
        result.append({
            "id": gid,
            "name": name,
            "diamonds": diamonds,
            "img": _gift_image_url(gift),
        })
    result.sort(key=lambda x: (x["diamonds"], x["name"].lower(), int(x["id"]) if x["id"].isdigit() else 0))
    return result


async def fetch_gift_catalog_for_user(username: str):
    username = normalize_tiktok_id(username)
    if not username:
        raise ValueError("Thiếu TikTok ID")
    client = TikTokLiveClient(unique_id=username)
    try:
        # Current TikTokLive exposes retrieve_available_gifts(); older builds
        # expose the same data through available_gifts after the call.
        method = getattr(client, "retrieve_available_gifts", None)
        if callable(method):
            raw = await method()
            catalog = _normalize_gift_catalog(raw)
            if catalog:
                return catalog
            raw = getattr(client, "gift_info", None) or getattr(client, "available_gifts", None)
            return _normalize_gift_catalog(raw)

        # Compatibility with versions where gift metadata is populated during
        # connection via fetch_gift_info=True.
        await client.start(fetch_gift_info=True)
        for _ in range(30):
            raw = getattr(client, "gift_info", None) or getattr(client, "available_gifts", None)
            if raw:
                return _normalize_gift_catalog(raw)
            await asyncio.sleep(0.1)
        raw = getattr(client, "gift_info", None) or getattr(client, "available_gifts", None)
        return _normalize_gift_catalog(raw)
    finally:
        try:
            await client.disconnect()
        except Exception:
            try:
                await client.stop()
            except Exception:
                pass


@app.get("/api/tiktok/gifts")
async def api_tiktok_gifts(username: str):
    username = normalize_tiktok_id(username)
    if not username:
        return {"ok": False, "error": "Thiếu TikTok ID"}
    try:
        gifts = await fetch_gift_catalog_for_user(username)
        state["gift_catalog"] = gifts
        state["gift_catalog_username"] = username
        state["gift_catalog_error"] = None
        await broadcast_state()
        return {"ok": True, "username": username, "count": len(gifts), "gifts": gifts}
    except Exception as exc:
        logging.warning("TikTok gift catalog lookup failed for @%s: %s", username, exc)
        state["gift_catalog_error"] = str(exc)
        await broadcast_state()
        return {"ok": False, "username": username, "error": "Không lấy được gift catalog. Hãy kiểm tra tài khoản có đang LIVE và phiên bản TikTokLive."}


# --------------------------------------------------------------------------
# TikTok profile avatar lookup
# --------------------------------------------------------------------------

def normalize_tiktok_id(value: str) -> str:
    value = (value or "").strip()
    value = value.split("?")[0].rstrip("/")
    if "/@" in value:
        value = value.split("/@", 1)[1]
    elif value.startswith("@"):
        value = value[1:]
    elif value.startswith("https://www.tiktok.com/"):
        value = value.rsplit("/", 1)[-1]
    return value.lstrip("@").strip()


def fetch_tiktok_avatar(tiktok_id: str) -> str:
    username = normalize_tiktok_id(tiktok_id)
    if not username:
        return ""
    url = f"https://www.tiktok.com/@{quote(username)}"
    req = Request(url, headers={
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/150 Safari/537.36",
        "Accept-Language": "en-US,en;q=0.9",
    })
    with urlopen(req, timeout=8) as response:
        html = response.read().decode("utf-8", "ignore")

    # TikTok currently exposes the profile image in several places.
    patterns = [
        r'<meta[^>]+property=["\']og:image["\'][^>]+content=["\']([^"\']+)',
        r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']og:image',
        r'"avatarLarger":"(https?:\\/\\/[^"\]+)',
        r'"avatarMedium":"(https?:\\/\\/[^"\]+)',
    ]
    for pattern in patterns:
        m = re.search(pattern, html, re.I)
        if m:
            avatar = unescape(m.group(1)).replace("\\/", "/")
            if avatar.startswith("http"):
                return avatar
    return ""


@app.get("/api/tiktok/avatar")
async def api_tiktok_avatar(username: str):
    username = normalize_tiktok_id(username)
    if not username:
        return {"ok": False, "error": "Thiếu TikTok ID"}
    try:
        avatar = await asyncio.to_thread(fetch_tiktok_avatar, username)
        if not avatar:
            return {"ok": False, "error": "Không tìm thấy avatar từ TikTok", "username": username}
        return {"ok": True, "username": username, "avatar": avatar}
    except Exception as exc:
        logging.warning("TikTok avatar lookup failed for @%s: %s", username, exc)
        return {"ok": False, "error": "TikTok không cho phép truy cập avatar lúc này", "username": username}


# --------------------------------------------------------------------------
# Idols
# --------------------------------------------------------------------------

@app.post("/api/idol")
async def api_add_idol(body: IdolIn):
    name = body.name.strip()
    if not name:
        return {"ok": False}
    idol = {
        "id": uuid.uuid4().hex[:8],
        "name": name,
        "tiktok_id": normalize_tiktok_id(body.tiktok_id),
        "avatar": body.avatar.strip(),
        "score": 0,
        "active": len(state["idols"]) == 0,
        "eliminated": False,
    }
    state["idols"].append(idol)
    await broadcast_state()
    return idol


@app.post("/api/idol/batch")
async def api_add_batch(body: BatchIdolIn):
    added = []
    for name in body.names:
        name = name.strip()
        if not name or any(i["name"].lower() == name.lower() for i in state["idols"]):
            continue
        tiktok_id = ""
        avatar = ""
        if "|" in name:
            name, raw_id = name.split("|", 1)
            name = name.strip()
            tiktok_id = normalize_tiktok_id(raw_id)
        elif name.startswith("@"):
            tiktok_id = normalize_tiktok_id(name)
            name = tiktok_id
        if tiktok_id:
            try:
                avatar = await asyncio.to_thread(fetch_tiktok_avatar, tiktok_id)
            except Exception:
                avatar = ""
        if not name:
            continue
        idol = {
            "id": uuid.uuid4().hex[:8],
            "name": name,
            "tiktok_id": tiktok_id,
            "avatar": avatar,
            "score": 0,
            "active": len(state["idols"]) == 0 and not added,
            "eliminated": False,
        }
        state["idols"].append(idol)
        added.append(idol)
    await broadcast_state()
    return {"added": len(added)}


@app.delete("/api/idol/all")
async def api_delete_all_idols():
    state["idols"] = []
    await broadcast_state()
    return {"ok": True}


@app.delete("/api/idol/{idol_id}")
async def api_remove_idol(idol_id: str):
    state["idols"] = [i for i in state["idols"] if i["id"] != idol_id]
    for pos in state["pk"].get("positions", []):
        if pos.get("idol_id") == idol_id:
            pos["idol_id"] = ""
            pos["name"] = ""
            pos["tiktok_id"] = ""
            pos["avatar"] = ""
    if state["idols"] and not any(i["active"] for i in state["idols"]):
        state["idols"][0]["active"] = True
    await broadcast_state()
    return {"ok": True}


@app.post("/api/idol/{idol_id}/active")
async def api_set_active(idol_id: str):
    for i in state["idols"]:
        i["active"] = i["id"] == idol_id
    await broadcast_state()
    return {"ok": True}


@app.post("/api/idol/{idol_id}/points")
async def api_add_points(idol_id: str, body: PointsIn):
    idol = get_idol(idol_id)
    if idol:
        idol["score"] = max(0, idol["score"] + body.delta)
        await broadcast_state()
    return {"ok": True}


@app.post("/api/idol/{idol_id}/set_score")
async def api_set_score(idol_id: str, body: SetScoreIn):
    idol = get_idol(idol_id)
    if idol:
        idol["score"] = max(0, body.score)
        await broadcast_state()
    return {"ok": True}


@app.post("/api/idol/{idol_id}/reset")
async def api_reset_idol(idol_id: str):
    idol = get_idol(idol_id)
    if idol:
        idol["score"] = 0
        await broadcast_state()
    return {"ok": True}


# --------------------------------------------------------------------------
# Timer
# --------------------------------------------------------------------------

@app.post("/api/timer/duration")
async def api_set_duration(body: DurationIn):
    seconds = max(1, min(int(body.seconds), 24 * 60 * 60))
    t = state["timer"]
    t["duration"] = seconds
    t["remaining"] = seconds
    t["running"] = False
    t["finished"] = False

    # Đặt thời gian = bắt đầu một hiệp PK mới:
    # - Chỉ reset điểm của thanh MultiPK và mapping user -> phe.
    # - KHÔNG reset điểm Idol trong bảng Rank; điểm Rank là tổng tích lũy.
    await disconnect_pk_rooms()
    for pos in state["pk"].get("positions", []):
        pos["score"] = 0
    state["pk"]["status"] = "standby"
    state["pk"]["round"] = int(state["pk"].get("round", 1)) + 1
    state["accepting_gifts"] = False
    await broadcast_state()
    return {"ok": True}


@app.post("/api/timer/start")
async def api_timer_start():
    t = state["timer"]
    if t["remaining"] <= 0:
        t["remaining"] = t["duration"]
    t["running"] = True
    t["finished"] = False
    await broadcast_state()
    return {"ok": True}


@app.post("/api/timer/pause")
async def api_timer_pause():
    state["timer"]["running"] = False
    if state["pk"]["status"] == "running":
        state["pk"]["status"] = "paused"
    state["accepting_gifts"] = False
    await broadcast_state()
    return {"ok": True}


@app.post("/api/timer/reset")
async def api_timer_reset():
    await disconnect_pk_rooms()
    t = state["timer"]
    t["remaining"] = t["duration"]
    t["running"] = False
    t["finished"] = False
    state["accepting_gifts"] = False
    state["pk"]["status"] = "standby"
    state["pk"]["round"] = 1
    for p in state["pk"]["positions"]:
        p["score"] = 0
    await broadcast_state()
    return {"ok": True}


@app.post("/api/timer/finish")
async def api_timer_finish():
    await disconnect_pk_rooms()
    t = state["timer"]
    t["running"] = False
    t["finished"] = True
    state["accepting_gifts"] = False
    if state["pk"]["enabled"]:
        state["pk"]["status"] = "finished"
    await broadcast_state()
    return {"ok": True}


# --------------------------------------------------------------------------
# Multi-PK
# --------------------------------------------------------------------------

@app.post("/api/pk/setup")
async def api_pk_setup(body: PKSetupIn):
    n = max(3, min(5, int(body.num_positions)))
    selected_ids = [body.positions[i].idol_id.strip() for i in range(min(n, len(body.positions))) if body.positions[i].idol_id.strip()]
    if len(selected_ids) != len(set(selected_ids)):
        return {"ok": False, "error": "Không thể chọn cùng một idol cho nhiều vị trí PK"}
    gift_ids = [body.positions[i].gift_id.strip() for i in range(min(n, len(body.positions))) if body.positions[i].gift_id.strip()]
    if len(gift_ids) != len(set(gift_ids)):
        return {"ok": False, "error": "Mỗi vị trí PK phải dùng một gift_id kích hoạt khác nhau"}
    await disconnect_pk_rooms()
    positions = []
    for i in range(n):
        incoming = body.positions[i] if i < len(body.positions) else PKPositionIn()
        idol = get_idol(incoming.idol_id.strip()) if incoming.idol_id else None
        positions.append({
            "id": uuid.uuid4().hex[:8],
            "idol_id": idol["id"] if idol else "",
            "name": (idol["name"] if idol else incoming.name.strip()) or f"Player {i + 1}",
            "tiktok_id": normalize_tiktok_id(idol.get("tiktok_id") if idol else incoming.tiktok_id),
            "avatar": (idol.get("avatar") if idol and idol.get("avatar") else incoming.avatar.strip()),
            "gift_id": incoming.gift_id.strip(),
            "gift_img": incoming.gift_img.strip(),
            "score": 0,
            "connected": False,
            "live_error": None,
        })

    state["pk"]["num_positions"] = n
    state["pk"]["positions"] = positions
    state["pk"]["enabled"] = True
    state["pk"]["status"] = "standby"
    state["pk"]["round"] = 1

    t = state["timer"]
    t["running"] = False
    t["finished"] = False
    t["remaining"] = t["duration"]
    state["accepting_gifts"] = False

    await broadcast_state()
    return {"ok": True, "positions": positions}


@app.post("/api/pk/select")
async def api_pk_select(body: PKSelectIn):
    n = max(3, min(5, int(body.num_positions)))
    if state["pk"]["status"] == "running":
        return {"ok": False, "error": "Không thể đổi thành viên khi PK đang chạy."}

    selected_ids = [body.positions[i].idol_id.strip() for i in range(min(n, len(body.positions))) if body.positions[i].idol_id.strip()]
    if len(selected_ids) != len(set(selected_ids)):
        return {"ok": False, "error": "Không thể chọn cùng một idol cho nhiều vị trí PK"}

    old = state["pk"].get("positions", [])
    positions = []
    for i in range(n):
        incoming = body.positions[i] if i < len(body.positions) else PKPositionIn()
        previous = old[i] if i < len(old) else {}
        idol = get_idol(incoming.idol_id.strip()) if incoming.idol_id else None
        positions.append({
            "id": previous.get("id") or uuid.uuid4().hex[:8],
            "idol_id": idol["id"] if idol else "",
            "name": idol["name"] if idol else (previous.get("name") or f"Player {i+1}"),
            "tiktok_id": normalize_tiktok_id(idol.get("tiktok_id") if idol else previous.get("tiktok_id", "")),
            "avatar": idol.get("avatar") if idol and idol.get("avatar") else previous.get("avatar", ""),
            "gift_id": incoming.gift_id.strip() if incoming.gift_id else previous.get("gift_id", ""),
            "gift_img": incoming.gift_img.strip() if incoming.gift_img else previous.get("gift_img", ""),
            "score": int(previous.get("score", 0)),
            "connected": bool(state.get("connected")),
            "live_error": state.get("last_error"),
        })

    state["pk"]["num_positions"] = n
    state["pk"]["positions"] = positions
    state["pk"]["enabled"] = True
    if state["pk"]["status"] not in ("paused", "finished"):
        state["pk"]["status"] = "standby"
    await broadcast_state()
    return {"ok": True, "positions": positions}


@app.post("/api/pk/start")
async def api_pk_start():
    positions = state["pk"]["positions"]
    if len(positions) < 3:
        return {"ok": False, "error": "PK cần ít nhất 3 vị trí"}
    missing = [i + 1 for i, p in enumerate(positions) if not p.get("idol_id")]
    if missing:
        return {"ok": False, "error": "Hãy chọn idol trong danh sách cho vị trí: " + ", ".join(map(str, missing))}
    missing_gifts = [i + 1 for i, p in enumerate(positions) if not p.get("gift_id")]
    if missing_gifts:
        return {"ok": False, "error": "Hãy nhập gift_id kích hoạt cho vị trí: " + ", ".join(map(str, missing_gifts))}
    if not state.get("room") or not state.get("connected"):
        return {"ok": False, "error": "Hãy kết nối và chờ 1 phòng TikTok Live báo Đã kết nối trước khi Bắt đầu PK."}

    reset_pk_assignments()
    state["pk"]["enabled"] = True
    state["pk"]["status"] = "running"
    state["timer"]["running"] = True
    state["timer"]["finished"] = False
    if state["timer"]["remaining"] <= 0:
        state["timer"]["remaining"] = state["timer"]["duration"]
    state["accepting_gifts"] = True
    for pos in positions:
        pos["connected"] = bool(state["connected"])
        pos["live_error"] = state["last_error"]
    await broadcast_state()
    return {"ok": True}


@app.post("/api/pk/pause")
async def api_pk_pause():
    state["pk"]["status"] = "paused"
    state["timer"]["running"] = False
    state["accepting_gifts"] = False
    await broadcast_state()
    return {"ok": True}


@app.post("/api/pk/end")
async def api_pk_end():
    await disconnect_pk_rooms()
    state["pk"]["status"] = "finished"
    state["timer"]["running"] = False
    state["timer"]["finished"] = True
    state["timer"]["remaining"] = 0
    state["accepting_gifts"] = False
    await broadcast_state()
    return {"ok": True}


@app.post("/api/pk/reset")
async def api_pk_reset():
    await disconnect_pk_rooms()
    state["pk"]["status"] = "standby"
    state["pk"]["round"] = 1
    state["timer"]["remaining"] = state["timer"]["duration"]
    state["timer"]["running"] = False
    state["timer"]["finished"] = False
    state["accepting_gifts"] = False
    for p in state["pk"]["positions"]:
        p["score"] = 0
    await broadcast_state()
    return {"ok": True}


@app.post("/api/pk/points")
async def api_pk_points(body: PKPointsIn):
    if 0 <= body.index < len(state["pk"]["positions"]):
        add_pk_points(body.index, int(body.delta))
        await broadcast_state()
    return {"ok": True}


if __name__ == "__main__":
    import os
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
