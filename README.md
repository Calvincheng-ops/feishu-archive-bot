# 飞书群文件自动归档机器人

当群成员 @机器人 并发送含 "final 版本" 等关键词的带附件消息时，机器人自动识别、发送确认卡片、确认后上传至对应云盘文件夹。

## ✨ 功能特性

- ✅ 关键词自动识别（final 版本、最终版本、确认归档等）
- ✅ 交互式确认卡片（防止误操作）
- ✅ 引用消息附件检测（先发文件 → 引用 → @机器人）
- ✅ 文件自动下载和上传到飞书云盘
- ✅ 群-文件夹映射配置（支持多维表格管理）
- ✅ 子文件夹浏览和选择
- ✅ 操作权限控制（仅发起人可操作）
- ✅ 卡片状态更新（点击后按钮消失，显示状态）
- ✅ 操作日志审计
- ✅ 消息去重（防止飞书重发事件导致重复处理）

## 🏗️ 技术架构

```
┌──────────────┐     ┌───────────────────┐     ┌──────────────┐
│   飞书客户端   │────▶│  飞书开放平台       │────▶│  本服务       │
│  (群聊消息)   │     │  (事件订阅/卡片回调) │     │  (FastAPI)   │
└──────────────┘     └───────────────────┘     └──────┬───────┘
                                                       │
                     ┌───────────────────┐             │
                     │   飞书云盘         │◀────────────┘
                     │  (文件上传)        │
                     └───────────────────┘
```

**技术栈**: Python 3.11 + FastAPI + 飞书官方 SDK (lark-oapi) + SQLite + Pydantic

## 📁 项目结构

```
feishu-archive-bot/
├── app/
│   ├── __init__.py
│   ├── main.py                  # FastAPI 入口，事件/卡片回调路由
│   ├── config.py                # 配置管理（Pydantic Settings）
│   ├── event_handler.py         # 核心业务逻辑（消息处理 + 卡片回调分发）
│   ├── models/
│   │   └── __init__.py
│   ├── services/
│   │   ├── __init__.py
│   │   ├── card_builder.py      # 飞书交互卡片 JSON 构建器
│   │   ├── keyword_matcher.py   # 关键词匹配引擎（正则）
│   │   ├── file_transfer.py     # 文件下载/上传服务
│   │   ├── mapping_service.py   # 群-文件夹映射管理
│   │   └── state_manager.py     # SQLite 状态管理（确认记录 + 日志）
│   └── utils/
│       ├── __init__.py
│       └── lark_client.py       # 飞书 SDK 封装
├── data/
│   └── archive_bot.db           # SQLite 数据库（运行时自动创建）
├── .env.example                 # 环境变量模板
├── .gitignore
├── requirements.txt
├── Dockerfile
├── docker-compose.yml
├── feishu-archive-bot.service   # systemd 服务文件
└── README.md
```

## 🚀 快速开始

### 1. 环境准备

```bash
# 克隆项目
git clone <repo-url>
cd feishu-archive-bot

# 创建虚拟环境
python3 -m venv venv
source venv/bin/activate

# 安装依赖
pip install -r requirements.txt
```

### 2. 配置环境变量

```bash
cp .env.example .env
# 编辑 .env 文件，填入飞书应用凭证
```

最少需要配置：

```bash
BOT_APP_ID=cli_xxx
BOT_APP_SECRET=xxx
ENCRYPT_KEY=xxx
VERIFICATION_TOKEN=xxx
ARCHIVE_CHAT_ID=oc_xxx
ARCHIVE_FOLDER_TOKEN=fldcnxxx
ARCHIVE_FOLDER_NAME=归档文件夹
```

### 3. 飞书应用配置

#### 3.1 创建应用

1. 登录 [飞书开放平台](https://open.feishu.cn)
2. 创建「企业自建应用」
3. 记录 App ID 和 App Secret

#### 3.2 配置事件订阅

1. 进入「事件与回调」→「事件配置」
2. 请求地址：`https://your-domain.com/api/events`
3. 添加事件：`im.message.receive_v1`
4. 记录 Encrypt Key 和 Verification Token

#### 3.3 配置卡片回调

1. 进入「消息卡片」→「卡片回调」
2. 回调地址：`https://your-domain.com/api/card/callback`

#### 3.4 申请权限

| 权限 | 说明 |
|------|------|
| `im:message.group_at_msg:readonly` | 接收群聊中 @ 机器人的消息 |
| `im:message` | 发送消息/卡片 |
| `im:resource` | 下载资源文件 |
| `im:chat:read` | 读取群信息 |
| `space:document:retrieve` | 列出目标文件夹下的子文件夹 |
| `drive:file:upload` | 上传文件 |
| `contact:user.base:readonly` | 获取用户信息 |

#### 3.5 配置可用范围

1. 进入「版本管理与发布」→「可用范围」
2. 添加「全部员工」或指定部门/人员
3. 发布应用版本

### 4. 启动服务

```bash
# 开发模式
python -m app.main

# 或使用 uvicorn
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

# 生产模式（systemd）
sudo cp feishu-archive-bot.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable feishu-archive-bot
sudo systemctl start feishu-archive-bot
```

### 5. 配置反向代理（Nginx）

```nginx
server {
    listen 443 ssl;
    server_name bot.your-domain.com;

    ssl_certificate /etc/letsencrypt/live/bot.your-domain.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/bot.your-domain.com/privkey.pem;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

### 6. Docker 部署

```bash
docker build -t feishu-archive-bot .
docker-compose up -d
docker-compose logs -f
```

## 📖 使用方法

1. 将机器人添加到目标群
2. 先发送文件到群聊
3. 引用该文件消息，@机器人并说 "这是 final 版本"
4. 机器人会发送确认卡片
5. 选择上传到根目录或子文件夹
6. 点击「确认上传」
7. 文件自动上传到配置的云盘文件夹

**支持的关键词**:
- final 版本 / final版 / final
- 最终版本 / 最终版
- 定稿
- 正式版本 / 正式版
- 确认归档
- 请上传到云盘
- 归档文件

## ⚙️ 映射配置

### 方式一：环境变量（测试用）

在 `.env` 中配置：

```bash
ARCHIVE_CHAT_ID=oc_xxx
ARCHIVE_CHAT_NAME=测试群
ARCHIVE_FOLDER_TOKEN=fldcnxxx
ARCHIVE_FOLDER_NAME=测试文件夹
```

### 方式二：多维表格（生产推荐）

1. 创建飞书多维表格
2. 配置字段：`chat_id`, `chat_name`, `folder_token`, `folder_name`, `enabled`
3. 在 `.env` 中配置 `BITABLE_APP_TOKEN` 和 `BITABLE_TABLE_ID`

> 注意：多维表格动态读取目前仍是预留能力，当前可运行路径是环境变量映射。

## 🔌 API 接口

| 接口 | 方法 | 说明 |
|------|------|------|
| `/` | GET | 根路径 |
| `/health` | GET | 健康检查 |
| `/api/events` | POST | 飞书事件回调（消息 + 卡片） |
| `/api/card/callback` | POST | 飞书卡片按钮回调 |
| `/api/logs?limit=100` | GET | 操作日志 |
| `/api/mappings` | GET | 映射配置 |

## 🐛 踩坑记录 & 经验总结

### 1. 飞书事件加密是默认行为

**问题**: 飞书发送的事件数据默认是加密的，收到的是 `{"encrypt": "..."}` 格式，不是明文 JSON。

**解决**: 必须实现 AES-CBC 解密逻辑：

```python
from Crypto.Cipher import AES
import hashlib, base64, json

def decrypt_event(encrypted_data: str, encrypt_key: str) -> dict:
    key = hashlib.sha256(encrypt_key.encode('utf-8')).digest()
    decoded = base64.b64decode(encrypted_data)
    iv = decoded[:16]
    cipher = AES.new(key, AES.MODE_CBC, iv)
    decrypted = cipher.decrypt(decoded[16:])
    pad_len = decrypted[-1]
    decrypted = decrypted[:-pad_len]
    return json.loads(decrypted.decode('utf-8'))
```

**注意**: 需要安装 `pycryptodome` 依赖。

### 2. 系统环境变量覆盖项目 .env

**问题**: 系统中存在 `FEISHU_APP_ID` 和 `FEISHU_APP_SECRET` 环境变量（来自 Hermes Agent），会覆盖项目 `.env` 中的同名变量。

**解决**: 使用自定义变量名避免冲突：

```python
# .env
BOT_APP_ID=cli_xxx
BOT_APP_SECRET=xxx

# config.py
class Settings(BaseSettings):
    bot_app_id: str = ""
    bot_app_secret: str = ""
    model_config = {"env_file": ".env"}
```

### 3. 飞书不支持同时发送文件和文字

**问题**: 飞书消息 API 不支持在一条消息中同时发送文件和文字说明。

**解决**: 用户采用「先发文件 → 引用该文件 → @机器人说关键词」的工作流。机器人需要检查被引用消息的附件：

```python
# 获取引用消息
parent_id = message.get("parent_id", "")
root_id = message.get("root_id", "")
ref_message_id = parent_id or root_id

if ref_message_id:
    ref_msg = await lark_client.get_message(ref_message_id)
    files = file_transfer_service.extract_files_from_message(ref_msg)
```

### 4. 卡片回调返回值决定卡片更新

**问题**: 卡片按钮点击后，如果不返回新卡片 JSON，飞书客户端不会更新原卡片 UI。

**关键**: `/api/card/callback` 端点必须返回更新后的卡片 JSON，飞书会用它替换原卡片：

```python
# 正确做法：返回新卡片
return JSONResponse(updated_card_json)

# 错误做法：返回固定 code
return JSONResponse({"code": 0})  # 这样卡片不会更新！
```

### 5. 飞书事件重复发送

**问题**: 飞书可能会重发同一条消息事件，导致机器人重复处理（出现两张相同的确认卡片）。

**解决**: 添加消息去重逻辑：

```python
class EventHandler:
    def __init__(self):
        self._processed_messages = set()
    
    async def handle_message_event(self, event):
        message_id = message.get("message_id", "")
        if message_id in self._processed_messages:
            return  # 重复消息，跳过
        self._processed_messages.add(message_id)
        # ... 处理消息
```

**注意**: 生产环境建议使用 Redis 替代内存 Set，避免重启后去重失效。

### 6. 机器人无法访问用户云盘文件夹

**问题**: 机器人使用 `tenant_access_token`，无法直接访问用户个人云盘的文件夹（权限不足）。

**解决**: 让机器人自己创建文件夹，然后将文件夹分享给群聊：

```python
# 机器人创建自己的文件夹
# 使用 tenant_access_token 创建的文件夹属于应用本身
# 上传文件时使用相同的 token 即可
```

### 7. 获取用户信息需要可见范围

**问题**: 调用 `contact.v3.user.get` 获取用户姓名时报 `41050 - no user authority error`。

**原因**: 应用需要有 `contact:user.base:readonly` 权限，且用户必须在应用的可用范围内。

**解决**:
1. 在飞书开放平台添加权限
2. 配置应用可用范围（全部员工或指定人员）
3. 发布新版本

### 8. systemd 服务找不到 Python 模块

**问题**: 使用 systemd 启动服务时报 `No module named uvicorn`。

**原因**: systemd 使用系统 Python (`/usr/bin/python3`)，而依赖安装在虚拟环境中。

**解决**: 在 service 文件中使用虚拟环境的 Python 路径：

```ini
[Service]
ExecStart=/path/to/venv/bin/python3 -m uvicorn app.main:app --host 0.0.0.0 --port 8000
```

查找虚拟环境路径：
```bash
which python3
# 输出: /usr/local/lib/hermes-agent/venv/bin/python3
```

### 9. 端口被占用导致服务启动失败

**问题**: systemd 服务反复重启失败，日志显示 `address already in use`。

**解决**: 先清理占用端口的进程：

```bash
sudo lsof -ti:8000 | xargs kill -9
sudo systemctl restart feishu-archive-bot
```

### 10. 卡片回调 URL 验证

**问题**: 配置卡片回调地址时，飞书会发送 challenge 验证请求。

**解决**: 回调端点必须处理 challenge：

```python
@app.post("/api/card/callback")
async def handle_card_callback(request: Request):
    body = await request.json()
    
    # 处理加密
    if "encrypt" in body:
        body = decrypt_event(body["encrypt"], settings.encrypt_key)
    
    # URL 验证
    if "challenge" in body:
        return JSONResponse({"challenge": body["challenge"]})
    
    # ... 处理卡片回调
```

### 11. 飞书 SDK 使用 tenant_access_token

**问题**: 飞书 SDK 默认使用 `tenant_access_token`（应用身份），不是 `user_access_token`（用户身份）。

**影响**:
- 上传的文件属于应用，不是用户
- 无法访问用户的个人云盘
- 获取用户信息需要额外权限配置

### 12. 云盘文件夹 Token 获取方式

**获取文件夹 Token**:
1. 在浏览器中打开飞书云盘
2. 进入目标文件夹
3. URL 中的 `fldcnXXX` 即为 folder_token

**注意**: 不同身份（用户/应用）看到的文件夹 token 可能不同。

## 🔒 安全设计

1. **权限最小化**: 只申请上传权限，不申请删除/移动权限
2. **操作确认**: 必须通过卡片确认，防止误操作
3. **身份校验**: 只有消息发送人可以操作确认卡片
4. **加密通信**: 事件回调使用 AES 加密
5. **日志审计**: 所有操作记录到数据库

## 📝 开发排期

| 模块 | 工作量 | 状态 |
|------|--------|------|
| 事件订阅 + 消息解析 | 0.5 天 | ✅ |
| 关键词匹配逻辑 | 0.5 天 | ✅ |
| Interactive Card 模板 | 0.5 天 | ✅ |
| Card Callback 处理 | 0.5 天 | ✅ |
| 文件下载 + 上传 | 1 天 | ✅ |
| 群-文件夹映射管理 | 0.5 天 | ✅ |
| 权限控制 + 卡片状态更新 | 0.5 天 | ✅ |
| 引用消息附件检测 | 0.5 天 | ✅ |
| 错误处理 + 日志 | 0.5 天 | ✅ |
| **合计** | **5 天** | ✅ |

## 🚧 后续优化

- [ ] 智能识别：基于 LLM 自动判断文件是否为 final 版本
- [ ] 批量归档：支持一次归档多个文件
- [ ] 归档通知：上传后自动通知项目负责人
- [ ] 版本管理：自动检测同名文件，创建新版本
- [ ] 统计报表：按项目/时间维度统计归档情况
- [ ] 多维表格映射：从飞书多维表格动态读取映射配置
- [ ] 文件预览：上传前预览文件内容
- [ ] 审批流程：重要文件归档需要审批

## 📄 License

MIT
