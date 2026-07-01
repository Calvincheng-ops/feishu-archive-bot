"""文件传输服务"""
import os
import tempfile
from typing import Optional, Dict, Any
from dataclasses import dataclass

from app.config import settings
from app.utils.lark_client import lark_client


@dataclass
class FileInfo:
    """文件信息"""
    file_key: str
    file_name: str
    file_type: str  # "file" 或 "image"
    size: Optional[int] = None


class FileTransferService:
    """处理文件下载和上传"""
    
    async def download_and_upload(
        self,
        message_id: str,
        file_key: str,
        file_name: str,
        folder_token: str,
        file_type: str = "file"
    ) -> Dict[str, Any]:
        """
        下载消息中的附件并上传到云盘
        
        Args:
            message_id: 消息 ID
            file_key: 文件 key
            file_name: 文件名
            folder_token: 目标文件夹 token
            file_type: 文件类型 ("file" 或 "image")
            
        Returns:
            上传结果
        """
        # 创建临时目录
        with tempfile.TemporaryDirectory() as temp_dir:
            local_path = os.path.join(temp_dir, file_name)
            
            try:
                # 1. 下载附件
                await lark_client.download_resource(
                    message_id=message_id,
                    file_key=file_key,
                    save_path=local_path,
                    resource_type=file_type
                )
                
                # 2. 检查文件大小
                file_size = os.path.getsize(local_path)
                max_size = settings.max_file_size_mb * 1024 * 1024
                
                if file_size > max_size:
                    raise FileTooLargeError(file_size, max_size)
                
                # 3. 上传到云盘
                result = await lark_client.upload_file(
                    folder_token=folder_token,
                    file_path=local_path,
                    file_name=file_name
                )
                
                return {
                    "success": True,
                    "file_token": result.get("file_token"),
                    "file_name": file_name,
                    "size": file_size
                }
                
            except FileTooLargeError as e:
                return {
                    "success": False,
                    "error": str(e),
                    "error_type": "file_too_large"
                }
            except Exception as e:
                return {
                    "success": False,
                    "error": str(e),
                    "error_type": "transfer_error"
                }
    
    def extract_files_from_message(self, message: Dict[str, Any]) -> list:
        """
        从消息中提取文件信息
        
        Args:
            message: 消息体
            
        Returns:
            文件信息列表
        """
        files = []
        message_type = message.get("message_type", "")
        content = message.get("content", "{}")
        
        if isinstance(content, str):
            import json
            try:
                content = json.loads(content)
            except:
                content = {}
        
        if message_type == "file":
            files.append(FileInfo(
                file_key=content.get("file_key", ""),
                file_name=content.get("file_name", "未知文件"),
                file_type="file"
            ))
        elif message_type == "image":
            files.append(FileInfo(
                file_key=content.get("image_key", ""),
                file_name=f"image_{content.get('image_key', 'unknown')}.png",
                file_type="image"
            ))
        elif message_type == "post":
            # 富文本消息可能包含多个文件
            for item in content.get("content", []):
                for element in item:
                    if element.get("tag") == "file":
                        files.append(FileInfo(
                            file_key=element.get("file_key", ""),
                            file_name=element.get("file_name", "未知文件"),
                            file_type="file"
                        ))
                    elif element.get("tag") == "img":
                        files.append(FileInfo(
                            file_key=element.get("image_key", ""),
                            file_name=f"image_{element.get('image_key', 'unknown')}.png",
                            file_type="image"
                        ))
        
        return files


class FileTooLargeError(Exception):
    """文件过大异常"""
    def __init__(self, file_size: int, max_size: int):
        self.file_size = file_size
        self.max_size = max_size
        super().__init__(
            f"文件大小 {file_size / 1024 / 1024:.1f}MB 超过限制 {max_size / 1024 / 1024:.1f}MB"
        )


# 全局文件传输服务实例
file_transfer_service = FileTransferService()
