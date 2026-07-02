"""飞书 SDK 客户端封装"""
import json
import os
import tempfile
from typing import Optional, Any, Dict
import lark_oapi as lark
from lark_oapi.api.im.v1 import *
from lark_oapi.api.drive.v1 import *
from lark_oapi.api.contact.v3 import *
import httpx
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
        direct_limit = settings.direct_upload_limit_mb * 1024 * 1024

        if file_size <= direct_limit:
            result = await self._upload_file_direct(folder_token, file_path, file_name, file_size)
            result["upload_method"] = "direct"
            return result

        result = await self._upload_file_multipart(folder_token, file_path, file_name, file_size)
        result["upload_method"] = "multipart"
        return result

    async def _upload_file_direct(
        self,
        folder_token: str,
        file_path: str,
        file_name: str,
        file_size: int
    ) -> dict:
        """20MB 以内文件使用直接上传。"""
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

    async def _upload_file_multipart(
        self,
        folder_token: str,
        file_path: str,
        file_name: str,
        file_size: int
    ) -> dict:
        """20MB 以上文件使用云空间分片上传。"""
        prepare_request = UploadPrepareFileRequest.builder() \
            .request_body(FileUploadInfo.builder()
                .file_name(file_name)
                .parent_type("explorer")
                .parent_node(folder_token)
                .size(file_size)
                .build()) \
            .build()

        prepare_response = self.client.drive.v1.file.upload_prepare(prepare_request)
        if not prepare_response.success():
            raise Exception(f"分片上传预处理失败: {prepare_response.msg}")

        upload_id = prepare_response.data.upload_id
        block_size = prepare_response.data.block_size
        block_num = prepare_response.data.block_num

        with open(file_path, "rb") as source:
            for seq in range(block_num):
                chunk = source.read(block_size)
                if not chunk:
                    break

                with tempfile.TemporaryFile() as part_file:
                    part_file.write(chunk)
                    part_file.seek(0)
                    part_request = UploadPartFileRequest.builder() \
                        .request_body(UploadPartFileRequestBody.builder()
                            .upload_id(upload_id)
                            .seq(seq)
                            .size(len(chunk))
                            .file(part_file)
                            .build()) \
                        .build()

                    part_response = self.client.drive.v1.file.upload_part(part_request)

                if not part_response.success():
                    raise Exception(f"分片上传第 {seq + 1}/{block_num} 片失败: {part_response.msg}")

        finish_request = UploadFinishFileRequest.builder() \
            .request_body(UploadFinishFileRequestBody.builder()
                .upload_id(upload_id)
                .block_num(block_num)
                .build()) \
            .build()

        finish_response = self.client.drive.v1.file.upload_finish(finish_request)
        if not finish_response.success():
            raise Exception(f"完成分片上传失败: {finish_response.msg}")

        return {
            "file_token": finish_response.data.file_token,
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
        import httpx
        
        token_resp = requests.post(
            'https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal',
            json={
                'app_id': settings.bot_app_id,
                'app_secret': settings.bot_app_secret
            }
        )
        access_token = token_resp.json().get('tenant_access_token', '')
        
        headers = {'Authorization': f'Bearer {access_token}'}
        resp = requests.get(
            f'https://open.feishu.cn/open-apis/drive/v1/files',
            headers=headers,
            params={
                'folder_token': folder_token,
                'page_size': 50
            }
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
