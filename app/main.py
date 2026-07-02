"""飞书群文件自动归档机器人 - FastAPI 入口"""
import json
import hashlib
import base64
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.config import settings
from app.event_handler import event_handler
from app.services.state_manager import state_manager
from app.services.mapping_service import mapping_service

from Crypto.Cipher import AES


def decrypt_event(encrypted_data: str, encrypt_key: str) -> dict:
    """解密飞书加密事件"""
    key = hashlib.sha256(encrypt_key.encode('utf-8')).digest()
    decoded = base64.b64decode(encrypted_data)
    iv = decoded[:16]
    cipher = AES.new(key, AES.MODE_CBC, iv)
    decrypted = cipher.decrypt(decoded[16:])
    pad_len = decrypted[-1]
    decrypted = decrypted[:-pad_len]
    return json.loads(decrypted.decode('utf-8'))


def verify_callback_token(body: dict) -> bool:
    """Validate Feishu verification token when configured."""
    if not settings.verification_token:
        return True

    candidates = [
        body.get("token"),
        body.get("header", {}).get("token"),
        body.get("event", {}).get("token"),
    ]
    return settings.verification_token in candidates


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理"""
    print("正在初始化应用...")
    await state_manager.init_db()
    print("数据库初始化完成")

    if settings.archive_chat_id and settings.archive_folder_token:
        mapping_service.add_hardcoded_mapping(
            chat_id=settings.archive_chat_id,
            chat_name=settings.archive_chat_name or settings.archive_chat_id,
            folder_token=settings.archive_folder_token,
            folder_name=settings.archive_folder_name
        )

    print("应用初始化完成")
    yield
    print("应用关闭")


app = FastAPI(
    title="飞书群文件自动归档机器人",
    description="当群成员 @机器人并发送含 final 版本等关键词的带附件消息时，自动归档到云盘",
    version="1.0.0",
    lifespan=lifespan
)


@app.get("/")
async def root():
    return {
        "name": "飞书群文件自动归档机器人",
        "version": "1.0.0",
        "status": "running"
    }


@app.get("/health")
async def health():
    return {
        "status": "ok",
        "version": "1.0.0"
    }


@app.post("/api/events")
async def handle_events(request: Request):
    """处理飞书事件回调"""
    try:
        body = await request.json()

        print(f"[EVENT] 收到请求: {list(body.keys())}", flush=True)

        if "encrypt" in body:
            print(f"[EVENT] 解密事件...", flush=True)
            body = decrypt_event(body["encrypt"], settings.encrypt_key)
            print(f"[EVENT] 解密完成: {list(body.keys())}", flush=True)

        if not verify_callback_token(body):
            print("[EVENT] verification token mismatch", flush=True)
            return JSONResponse({"code": 403, "msg": "invalid token"}, status_code=403)

        if "challenge" in body:
            print(f"[EVENT] URL验证 challenge", flush=True)
            return JSONResponse({
                "challenge": body["challenge"]
            })

        header = body.get("header", {})
        event_type = header.get("event_type", "")
        event = body.get("event", {})

        print(f"[EVENT] 事件类型: {event_type}", flush=True)

        if event_type == "im.message.receive_v1":
            print(f"[EVENT] 处理消息事件...", flush=True)
            await event_handler.handle_message_event(event)
            print(f"[EVENT] 消息事件处理完成", flush=True)

        elif event_type == "card.action.trigger":
            # 卡片回调事件 - 忽略，由 /api/card/callback 处理
            print(f"[EVENT] 卡片回调事件，忽略（由 /api/card/callback 处理）", flush=True)
            return JSONResponse({"code": 0})

        return JSONResponse({"code": 0})

    except Exception as e:
        print(f"处理事件失败: {e}")
        import traceback
        traceback.print_exc()
        return JSONResponse({"code": 0})


@app.post("/api/card/callback")
async def handle_card_callback(request: Request):
    """处理卡片回调（直接回调格式）"""
    try:
        body = await request.json()

        print(f"[CARD] 收到卡片回调: {list(body.keys())}", flush=True)

        if "encrypt" in body:
            body = decrypt_event(body["encrypt"], settings.encrypt_key)
            print(f"[CARD] 解密完成: {list(body.keys())}", flush=True)
        else:
            # 明文格式 - 直接返回空响应，不处理
            # 明文格式的 open_id 不是真正的操作人，忽略
            print(f"[CARD] 明文回调，忽略", flush=True)
            return JSONResponse({})

        if not verify_callback_token(body):
            print("[CARD] verification token mismatch", flush=True)
            return JSONResponse({"code": 403, "msg": "invalid token"}, status_code=403)

        if "challenge" in body:
            print(f"[CARD] URL验证 challenge", flush=True)
            return JSONResponse({"challenge": body["challenge"]})

        event_data = body.get("event", {})
        callback = {
            "action": event_data.get("action", {}),
            "operator": event_data.get("operator", {}),
            "open_chat_id": event_data.get("context", {}).get("open_chat_id", ""),
            "context": event_data.get("context", {})
        }

        action_type = callback["action"].get("value", {}).get("action", "")
        operator = callback["operator"]
        operator_id = operator.get("open_id", "")
        print(f"[CARD] action={action_type}, operator_id={operator_id}", flush=True)

        updated_card = await event_handler.handle_card_callback(callback)

        if updated_card:
            print(f"[CARD] 返回更新卡片: {json.dumps(updated_card, ensure_ascii=False)[:200]}...", flush=True)
        else:
            print(f"[CARD] 返回空响应（不更新卡片）", flush=True)

        if updated_card:
            return JSONResponse(updated_card)

        return JSONResponse({})

    except Exception as e:
        print(f"[CARD] 处理卡片回调失败: {e}", flush=True)
        import traceback
        traceback.print_exc()
        return JSONResponse({"code": 0})


@app.get("/api/logs")
async def get_logs(limit: int = 100):
    logs = await state_manager.get_recent_logs(limit)
    return {"logs": logs}


@app.get("/api/mappings")
async def get_mappings():
    mappings = await mapping_service.get_all_mappings()
    return {
        "mappings": [
            {
                "chat_id": m.chat_id,
                "chat_name": m.chat_name,
                "folder_token": m.folder_token,
                "folder_name": m.folder_name,
                "enabled": m.enabled
            }
            for m in mappings
        ]
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        log_level=settings.log_level.lower()
    )
