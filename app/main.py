"""飞书群文件自动归档机器人 - FastAPI 入口"""
import json
import hashlib
import base64
from typing import Dict, Any
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse

from app.config import settings
from app.event_handler import event_handler
from app.services.state_manager import state_manager
from app.services.mapping_service import mapping_service

from Crypto.Cipher import AES


def _wrap_raw_card(card_json: Dict[str, Any]) -> Dict[str, Any]:
    """包装新版 card.action.trigger 回调响应。"""
    return {
        "card": {
            "type": "raw",
            "data": card_json
        }
    }


def _build_card_response(handler_result: dict) -> JSONResponse:
    """根据 handler 返回值类型组装 HTTP 响应

    handler 返回协议：
    - {"_type": "card", "card": {...}} → 更新卡片（全群可见）
    - {"_type": "toast", "toast": {...}} → Toast 提示（仅点击者可见）
    - None / {} → 空响应
    """
    if not handler_result:
        return JSONResponse({})
    typ = handler_result.get("_type", "")
    if typ == "toast":
        print(f"[RESP] 返回 Toast: {handler_result['toast'].get('content', '')[:50]}", flush=True)
        return JSONResponse({"toast": handler_result["toast"]})
    if typ == "card":
        card = handler_result["card"]
        print(f"[RESP] 返回卡片更新: {json.dumps(card, ensure_ascii=False)[:100]}...", flush=True)
        return JSONResponse(_wrap_raw_card(card))
    # 兼容旧格式：直接返回卡片 dict
    print(f"[RESP] 返回旧格式卡片", flush=True)
    return JSONResponse(_wrap_raw_card(handler_result))


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


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理"""
    print("正在初始化应用...")
    await state_manager.init_db()
    print("数据库初始化完成")

    mapping_service.add_hardcoded_mapping(
        chat_id="oc_ef1aa1409f9068ff12c892a42f32e73d",
        chat_name="文件归档测试",
        folder_token="PPb3f4FwTl6hmJd95UXc4H7anDf",
        folder_name="归档文件夹"
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
            # 打印原始 event 数据用于调试
            print(f"[EVENT] card.action.trigger raw event keys: {list(event.keys())}", flush=True)
            if "action" in event:
                act = event["action"]
                print(f"[EVENT] action keys: {list(act.keys()) if isinstance(act, dict) else type(act)}", flush=True)
                if isinstance(act, dict) and "value" in act:
                    print(f"[EVENT] action.value keys: {list(act['value'].keys())}", flush=True)
            if "operator" in event:
                op = event["operator"]
                print(f"[EVENT] operator keys: {list(op.keys()) if isinstance(op, dict) else type(op)}", flush=True)

            # 标准化为统一的 callback dict 格式（与 /api/card/callback 一致）
            callback = {
                "action": event.get("action", {}),
                "operator": event.get("operator", {}),
                "open_chat_id": event.get("context", {}).get("open_chat_id", ""),
                "context": event.get("context", {})
            }
            resp = await event_handler.handle_card_callback(callback)
            return _build_card_response(resp)

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
            print(f"[CARD] 解密后完整数据: {json.dumps(body, ensure_ascii=False)}", flush=True)

        if "challenge" in body:
            print(f"[CARD] URL验证 challenge", flush=True)
            return JSONResponse({"challenge": body["challenge"]})

        event_data = body.get("event", {})
        callback = {
            "action": event_data.get("action", body.get("action", {})),
            "operator": event_data.get("operator", body.get("operator", {})),
            "open_chat_id": event_data.get("context", {}).get("open_chat_id", body.get("open_chat_id", "")),
            "context": event_data.get("context", body.get("context", {}))
        }

        action_type = callback["action"].get("value", {}).get("action", "")
        operator = callback["operator"]
        operator_id = operator.get("open_id", "") or operator.get("operator_id", {}).get("open_id", "")
        print(f"[CARD] action={action_type}, operator_id={operator_id}", flush=True)

        resp = await event_handler.handle_card_callback(callback)
        return _build_card_response(resp)

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


@app.get("/api/confirmations")
async def get_confirmations(limit: int = 50):
    """获取最近的归档确认记录"""
    records = await state_manager.get_recent_confirmations(limit)
    return {"confirmations": records}


@app.get("/api/services")
async def get_services_status():
    """获取服务状态"""
    import subprocess
    services = ["feishu-archive-bot", "feishu-mail-monitor"]
    status = {}
    for svc in services:
        try:
            result = subprocess.run(
                ["systemctl", "is-active", f"{svc}.service"],
                capture_output=True,
                text=True,
                timeout=3
            )
            status[svc] = {
                "status": result.stdout.strip(),
                "active": result.returncode == 0
            }
        except Exception as e:
            status[svc] = {"status": "unknown", "active": False, "error": str(e)}
    return status


@app.get("/api/mail-monitor/logs")
async def get_mail_monitor_logs(lines: int = 50):
    """读取 mail-monitor 日志"""
    import os
    log_path = "/root/feishu-mail-monitor/monitor.log"
    if not os.path.exists(log_path):
        return {"logs": [], "error": "日志文件不存在"}
    try:
        with open(log_path, "r", encoding="utf-8") as f:
            all_lines = f.readlines()
            return {"logs": all_lines[-lines:]}
    except Exception as e:
        return {"logs": [], "error": str(e)}


@app.post("/api/services/{service_name}/restart")
async def restart_service(service_name: str):
    """重启服务（需要 sudo 配置）"""
    import subprocess
    allowed = ["feishu-archive-bot", "feishu-mail-monitor"]
    if service_name not in allowed:
        return JSONResponse({"error": "不允许的服务名"}, status_code=400)
    try:
        result = subprocess.run(
            ["sudo", "systemctl", "restart", f"{service_name}.service"],
            capture_output=True,
            text=True,
            timeout=10
        )
        if result.returncode == 0:
            return {"success": True, "message": f"{service_name} 重启成功"}
        else:
            return JSONResponse(
                {"error": result.stderr or "重启失败"},
                status_code=500
            )
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@app.get("/admin")
async def admin_panel():
    """管理面板前端"""
    html = """
<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>飞书自动化管理面板</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <script defer src="https://cdn.jsdelivr.net/npm/alpinejs@3.x.x/dist/cdn.min.js"></script>
</head>
<body class="bg-gray-50" x-data="dashboard()" x-init="init()">
    <div class="min-h-screen p-6">
        <div class="max-w-7xl mx-auto">
            <div class="flex justify-between items-center mb-8">
                <h1 class="text-3xl font-bold text-gray-900">飞书自动化管理面板</h1>
                <button @click="refresh()" class="px-4 py-2 bg-blue-600 text-white rounded hover:bg-blue-700">
                    <span x-show="!loading">刷新</span>
                    <span x-show="loading">加载中...</span>
                </button>
            </div>

            <!-- 服务状态卡片 -->
            <div class="grid grid-cols-1 md:grid-cols-2 gap-6 mb-8">
                <div class="bg-white rounded-lg shadow p-6">
                    <div class="flex items-center justify-between mb-4">
                        <h2 class="text-xl font-semibold text-gray-800">归档机器人</h2>
                        <span :class="services['feishu-archive-bot']?.active ? 'bg-green-100 text-green-800' : 'bg-red-100 text-red-800'"
                              class="px-3 py-1 rounded-full text-sm font-medium">
                            <span x-text="services['feishu-archive-bot']?.status || '未知'"></span>
                        </span>
                    </div>
                    <button @click="restartService('feishu-archive-bot')"
                            class="w-full px-4 py-2 bg-gray-100 hover:bg-gray-200 rounded text-gray-700">
                        重启服务
                    </button>
                </div>

                <div class="bg-white rounded-lg shadow p-6">
                    <div class="flex items-center justify-between mb-4">
                        <h2 class="text-xl font-semibold text-gray-800">邮件监控</h2>
                        <span :class="services['feishu-mail-monitor']?.active ? 'bg-green-100 text-green-800' : 'bg-red-100 text-red-800'"
                              class="px-3 py-1 rounded-full text-sm font-medium">
                            <span x-text="services['feishu-mail-monitor']?.status || '未知'"></span>
                        </span>
                    </div>
                    <div class="space-y-2">
                        <button @click="restartService('feishu-mail-monitor')"
                                class="w-full px-4 py-2 bg-gray-100 hover:bg-gray-200 rounded text-gray-700">
                            重启服务
                        </button>
                        <button @click="showMailLogs = !showMailLogs"
                                class="w-full px-4 py-2 bg-blue-100 hover:bg-blue-200 rounded text-blue-700">
                            <span x-text="showMailLogs ? '隐藏日志' : '查看日志'"></span>
                        </button>
                    </div>
                </div>
            </div>

            <!-- 邮件监控日志 -->
            <div x-show="showMailLogs" class="bg-white rounded-lg shadow p-6 mb-8">
                <h2 class="text-xl font-semibold text-gray-800 mb-4">邮件监控日志（最新50条）</h2>
                <div class="bg-gray-900 text-green-400 p-4 rounded font-mono text-sm overflow-x-auto max-h-96 overflow-y-auto">
                    <template x-for="line in mailLogs" :key="line">
                        <div x-text="line"></div>
                    </template>
                    <div x-show="mailLogs.length === 0" class="text-gray-500">暂无日志</div>
                </div>
            </div>

            <!-- 归档记录 -->
            <div class="bg-white rounded-lg shadow overflow-hidden mb-8">
                <div class="px-6 py-4 border-b border-gray-200">
                    <h2 class="text-xl font-semibold text-gray-800">最近归档记录</h2>
                </div>
                <div class="overflow-x-auto">
                    <table class="min-w-full divide-y divide-gray-200">
                        <thead class="bg-gray-50">
                            <tr>
                                <th class="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase">文件名</th>
                                <th class="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase">状态</th>
                                <th class="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase">群聊</th>
                                <th class="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase">创建时间</th>
                                <th class="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase">完成时间</th>
                            </tr>
                        </thead>
                        <tbody class="bg-white divide-y divide-gray-200">
                            <template x-for="record in confirmations" :key="record.id">
                                <tr>
                                    <td class="px-6 py-4 whitespace-nowrap text-sm text-gray-900" x-text="record.file_name"></td>
                                    <td class="px-6 py-4 whitespace-nowrap">
                                        <span :class="{
                                            'bg-yellow-100 text-yellow-800': record.status === 'pending',
                                            'bg-blue-100 text-blue-800': record.status === 'confirmed',
                                            'bg-green-100 text-green-800': record.status === 'completed',
                                            'bg-red-100 text-red-800': record.status === 'failed'
                                        }" class="px-2 py-1 rounded text-xs font-medium" x-text="record.status"></span>
                                    </td>
                                    <td class="px-6 py-4 whitespace-nowrap text-sm text-gray-500" x-text="record.chat_id.substring(0, 20) + '...'"></td>
                                    <td class="px-6 py-4 whitespace-nowrap text-sm text-gray-500" x-text="record.created_at"></td>
                                    <td class="px-6 py-4 whitespace-nowrap text-sm text-gray-500" x-text="record.completed_at || '-'"></td>
                                </tr>
                            </template>
                            <tr x-show="confirmations.length === 0">
                                <td colspan="5" class="px-6 py-4 text-center text-gray-500">暂无记录</td>
                            </tr>
                        </tbody>
                    </table>
                </div>
            </div>

            <!-- 操作日志（折叠） -->
            <div class="bg-white rounded-lg shadow overflow-hidden">
                <button @click="showOpLogs = !showOpLogs" class="w-full px-6 py-4 flex justify-between items-center hover:bg-gray-50">
                    <h2 class="text-xl font-semibold text-gray-800">操作日志</h2>
                    <span x-text="showOpLogs ? '▼' : '▶'" class="text-gray-500"></span>
                </button>
                <div x-show="showOpLogs" class="overflow-x-auto">
                    <table class="min-w-full divide-y divide-gray-200">
                        <thead class="bg-gray-50">
                            <tr>
                                <th class="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase">时间</th>
                                <th class="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase">文件名</th>
                                <th class="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase">状态</th>
                                <th class="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase">详情</th>
                            </tr>
                        </thead>
                        <tbody class="bg-white divide-y divide-gray-200">
                            <template x-for="log in opLogs" :key="log.id">
                                <tr>
                                    <td class="px-6 py-4 whitespace-nowrap text-sm text-gray-500" x-text="log.timestamp"></td>
                                    <td class="px-6 py-4 whitespace-nowrap text-sm text-gray-900" x-text="log.file_name"></td>
                                    <td class="px-6 py-4 whitespace-nowrap text-sm" x-text="log.status"></td>
                                    <td class="px-6 py-4 text-sm text-gray-500" x-text="log.error_msg || log.details || '-'"></td>
                                </tr>
                            </template>
                        </tbody>
                    </table>
                </div>
            </div>
        </div>
    </div>

    <script>
        function dashboard() {
            return {
                loading: false,
                services: {},
                confirmations: [],
                opLogs: [],
                mailLogs: [],
                showMailLogs: false,
                showOpLogs: false,

                async init() {
                    await this.refresh();
                    setInterval(() => this.refresh(), 10000);
                },

                async refresh() {
                    this.loading = true;
                    try {
                        await Promise.all([
                            this.fetchServices(),
                            this.fetchConfirmations(),
                            this.fetchOpLogs(),
                            this.fetchMailLogs()
                        ]);
                    } finally {
                        this.loading = false;
                    }
                },

                async fetchServices() {
                    const res = await fetch('/api/services');
                    this.services = await res.json();
                },

                async fetchConfirmations() {
                    const res = await fetch('/api/confirmations?limit=50');
                    const data = await res.json();
                    this.confirmations = data.confirmations || [];
                },

                async fetchOpLogs() {
                    const res = await fetch('/api/logs?limit=50');
                    const data = await res.json();
                    this.opLogs = data.logs || [];
                },

                async fetchMailLogs() {
                    const res = await fetch('/api/mail-monitor/logs?lines=50');
                    const data = await res.json();
                    this.mailLogs = data.logs || [];
                },

                async restartService(name) {
                    if (!confirm(`确定要重启 ${name} 吗？`)) return;
                    try {
                        const res = await fetch(`/api/services/${name}/restart`, {method: 'POST'});
                        const data = await res.json();
                        if (data.success) {
                            alert('重启成功');
                            await this.fetchServices();
                        } else {
                            alert('重启失败: ' + (data.error || '未知错误'));
                        }
                    } catch (e) {
                        alert('请求失败: ' + e.message);
                    }
                }
            }
        }
    </script>
</body>
</html>
    """
    from fastapi.responses import HTMLResponse
    return HTMLResponse(content=html)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        log_level=settings.log_level.lower()
    )
