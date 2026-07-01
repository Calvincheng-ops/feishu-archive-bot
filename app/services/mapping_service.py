"""群-文件夹映射管理"""
import time
from typing import Optional, Dict, Any
from dataclasses import dataclass

from app.config import settings
from app.utils.lark_client import lark_client


@dataclass
class FolderMapping:
    """文件夹映射"""
    chat_id: str
    chat_name: str
    folder_token: str
    folder_name: str
    enabled: bool


class MappingService:
    """管理群 chat_id 到云盘文件夹的映射"""
    
    def __init__(self):
        self._cache: Dict[str, FolderMapping] = {}
        self._last_refresh: float = 0
        # 临时硬编码映射（后续改为从多维表格读取）
        self._hardcoded_mappings: Dict[str, FolderMapping] = {}
    
    async def get_folder_mapping(self, chat_id: str) -> Optional[FolderMapping]:
        """
        获取群对应的文件夹映射
        
        Args:
            chat_id: 群 ID
            
        Returns:
            FolderMapping 或 None
        """
        # 检查缓存是否需要刷新
        if time.time() - self._last_refresh > settings.cache_refresh_interval:
            await self._refresh_cache()
        
        return self._cache.get(chat_id)
    
    async def _refresh_cache(self):
        """刷新映射缓存"""
        # 如果配置了多维表格，从表格读取
        if settings.bitable_app_token and settings.bitable_table_id:
            try:
                await self._load_from_bitable()
            except Exception as e:
                print(f"从多维表格加载映射失败: {e}")
                # 如果加载失败且缓存为空，使用硬编码映射
                if not self._cache:
                    self._cache = self._hardcoded_mappings.copy()
        else:
            # 没有配置多维表格，使用硬编码映射
            self._cache = self._hardcoded_mappings.copy()
        
        self._last_refresh = time.time()
    
    async def _load_from_bitable(self):
        """从多维表格加载映射配置"""
        import httpx
        
        # 使用飞书 API 获取多维表格数据
        # 这里需要使用 bitable API，暂时简化处理
        # 实际实现需要调用 lark_client 的 bitable 相关接口
        pass
    
    def add_hardcoded_mapping(
        self,
        chat_id: str,
        chat_name: str,
        folder_token: str,
        folder_name: str,
        enabled: bool = True
    ):
        """添加硬编码映射（用于测试）"""
        self._hardcoded_mappings[chat_id] = FolderMapping(
            chat_id=chat_id,
            chat_name=chat_name,
            folder_token=folder_token,
            folder_name=folder_name,
            enabled=enabled
        )
    
    async def get_all_mappings(self) -> list:
        """获取所有映射"""
        if time.time() - self._last_refresh > settings.cache_refresh_interval:
            await self._refresh_cache()
        return list(self._cache.values())


# 全局映射服务实例
mapping_service = MappingService()
