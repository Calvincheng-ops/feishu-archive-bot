"""飞书 SDK 客户端封装"""
import json
import os
from typing import Optional, Dict, Any
import lark_oapi as lark
from lark_oapi.api.im.v1 import *
from lark_oapi.api.drive.v1 import *
from lark_oapi.api.contact.v3 import *
import requests

from app.config import settings


class LarkClient:
    """飞书 API 客户端"""
    
    def __init__(self):
        self.client = lark.Client.builder() \
            .app_id(settings.bot_app_id) \
            .app_secret(settings.bot_app_secret) \
            .log_level(lark.LogLevel.INFO) \
            .build()
    
    async def download_resource(
        self, 
        message_id: str, 
        file_key: str, 
        save_path: str,
        resource_type: str = "file"
    ) -> str:
        """下载消息中的资源文件"""
        if resource_type == "file":
            # 下载文件
            request = GetMessageResourceRequest.builder() \
                .message_id(message_id) \
                .file_key(file_key) \
                .type("file") \
                .build()
            response = self.client.im.v1.message_resource.get(request)
            
            if not response.success():
                raise Exception(f"下载文件失败: {response.msg}")
            
            # 保存文件
            with open(save_path, "wb") as f:
                f.write(response.file.read())
        
        elif resource_type == "image":
            # 下载图片
            request = GetMessageResourceRequest.builder() \
                .message_id(message_id) \
                .file_key(file_key) \
                .type("image") \
                .build()
            response = self.client.im.v1.message_resource.get(request)
            
            if not response.success():
                raise Exception(f"下载图片失败: {response.msg}")
            
            with open(save_path, "wb") as f:
                f.write(response.file.read())
        
        return save_path
    
    async def upload_file(
        self, 
        folder_token: str, 
        file_path: str, 
        file_name: str
    ) -> dict:
        """上传文件到云盘指定文件夹"""
        file_size = os.path.getsize(file_path)
        
        with open(file_path, "rb") as file_obj:
            request = UploadAllFileRequest.builder() \
                .request_body(UploadAllFileRequestBody.builder()
                    .file_name(file_name)
                    .parent_type("explorer")
                    .parent_node(folder_token)
                    .size(file_size)
                    .file(file_obj)
                    .build()) \
                .build()

            response = self.client.drive.v1.file.upload_all(request)
        
        if not response.success():
            raise Exception(f"上传文件失败: {response.msg}")
        
        return {
            "file_token": response.data.file_token,
            "file_name": file_name,
            "size": file_size
        }
    
    async def send_message(
        self, 
        chat_id: str, 
        msg_type: str, 
        content: str
    ) -> dict:
        """发送消息到群"""
        request = CreateMessageRequest.builder() \
            .receive_id_type("chat_id") \
            .request_body(CreateMessageRequestBody.builder()
                .receive_id(chat_id)
                .msg_type(msg_type)
                .content(content)
                .build()) \
            .build()
        
        response = self.client.im.v1.message.create(request)
        
        if not response.success():
            raise Exception(f"发送消息失败: {response.msg}")
        
        return {"message_id": response.data.message_id}
    
    async def send_card(
        self, 
        chat_id: str, 
        card_json: dict
    ) -> dict:
        """发送卡片消息"""
        content = json.dumps(card_json, ensure_ascii=False)
        return await self.send_message(chat_id, "interactive", content)
    
    async def update_card(
        self, 
        message_id: str, 
        card_json: dict
    ) -> dict:
        """更新卡片消息"""
        content = json.dumps(card_json, ensure_ascii=False)
        
        request = PatchMessageRequest.builder() \
            .message_id(message_id) \
            .request_body(PatchMessageRequestBody.builder()
                .content(content)
                .build()) \
            .build()
        
        response = self.client.im.v1.message.patch(request)
        
        if not response.success():
            raise Exception(f"更新卡片失败: {response.msg}")
        
        return {"message_id": message_id}
    
    async def get_message(self, message_id: str) -> Optional[Dict[str, Any]]:
        """获取单条消息内容"""
        request = GetMessageRequest.builder() \
            .message_id(message_id) \
            .build()
        
        response = self.client.im.v1.message.get(request)
        
        if not response.success():
            print(f"[LARK] 获取消息失败: {response.code} - {response.msg}", flush=True)
            return None
        
        items = response.data.items
        if not items:
            return None
        
        msg = items[0]
        return {
            "message_id": msg.message_id,
            "message_type": msg.msg_type,
            "content": msg.body.content if msg.body else "{}"
        }
    
    async def list_folder_children(self, folder_token: str) -> list:
        """列出云盘文件夹下的子文件夹"""
        token_resp = requests.post(
            'https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal',
            json={
                'app_id': settings.bot_app_id,
                'app_secret': settings.bot_app_secret
            },
            timeout=10
        )
        access_token = token_resp.json().get('tenant_access_token', '')
        if not access_token:
            print(f"[LARK] 获取 tenant_access_token 失败: {token_resp.text}", flush=True)
            return []
        
        headers = {'Authorization': f'Bearer {access_token}'}
        resp = requests.get(
            f'https://open.feishu.cn/open-apis/drive/v1/files',
            headers=headers,
            params={
                'folder_token': folder_token,
                'page_size': 50
            },
            timeout=10
        )
        data = resp.json()
        if data.get('code') != 0:
            print(f"[LARK] 列出文件夹失败: {data}", flush=True)
            return []
        
        files = data.get('data', {}).get('files', [])
        folders = [f for f in files if f.get('type') == 'folder']
        return [
            {
                'token': f.get('token', ''),
                'name': f.get('name', '未知文件夹')
            }
            for f in folders
        ]

    async def get_chat_info(self, chat_id: str) -> dict:
        """获取群信息"""
        request = GetChatRequest.builder() \
            .chat_id(chat_id) \
            .build()
        
        response = self.client.im.v1.chat.get(request)
        
        if not response.success():
            raise Exception(f"获取群信息失败: {response.msg}")
        
        return {
            "chat_id": chat_id,
            "name": response.data.name,
            "description": response.data.description
        }
    
    async def get_user_info(self, open_id: str) -> dict:
        """获取用户信息"""
        if not open_id:
            return {"name": "未知用户", "open_id": ""}
        
        try:
            request = GetUserRequest.builder() \
                .user_id(open_id) \
                .user_id_type("open_id") \
                .build()
            
            response = self.client.contact.v3.user.get(request)
            
            if not response.success():
                print(f"[LARK] 获取用户信息失败: {response.code} - {response.msg}", flush=True)
                return {"name": "未知用户", "open_id": open_id}
            
            name = response.data.user.name if response.data and response.data.user else "未知用户"
            return {
                "open_id": open_id,
                "name": name or "未知用户"
            }
        except Exception as e:
            print(f"[LARK] 获取用户信息异常: {e}", flush=True)
            return {"name": "未知用户", "open_id": open_id}


# 全局客户端实例
lark_client = LarkClient()
