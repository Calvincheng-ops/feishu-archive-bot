"""状态管理 - SQLite"""
import aiosqlite
import os
from datetime import datetime
from typing import Optional, List, Dict, Any

from app.config import settings


class StateManager:
    """管理确认状态和操作日志"""
    
    def __init__(self):
        self.db_path = settings.db_path
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
    
    async def init_db(self):
        """初始化数据库"""
        async with aiosqlite.connect(self.db_path) as db:
            # 确认状态表
            await db.execute("""
                CREATE TABLE IF NOT EXISTS confirmations (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    message_id TEXT NOT NULL,
                    file_key TEXT NOT NULL,
                    file_name TEXT NOT NULL,
                    folder_token TEXT NOT NULL,
                    sender_id TEXT NOT NULL,
                    chat_id TEXT NOT NULL,
                    source_message_id TEXT,
                    card_message_id TEXT,
                    status TEXT DEFAULT 'pending',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    confirmed_at TIMESTAMP,
                    completed_at TIMESTAMP
                )
            """)
            
            # 操作日志表
            await db.execute("""
                CREATE TABLE IF NOT EXISTS operation_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    chat_id TEXT NOT NULL,
                    sender_id TEXT NOT NULL,
                    file_name TEXT NOT NULL,
                    folder_token TEXT NOT NULL,
                    status TEXT NOT NULL,
                    error_msg TEXT,
                    details TEXT
                )
            """)
            
            await db.commit()
    
    async def is_message_processed(self, message_id: str, file_key: str = None) -> bool:
        """
        检查消息是否已处理过（用于去重）
        
        Args:
            message_id: 消息 ID
            file_key: 文件 key（可选，如果提供则检查具体的文件）
        """
        async with aiosqlite.connect(self.db_path) as db:
            if file_key:
                # 检查具体的文件是否已处理
                cursor = await db.execute(
                    "SELECT 1 FROM confirmations WHERE message_id = ? AND file_key = ? LIMIT 1",
                    (message_id, file_key)
                )
            else:
                # 检查消息是否已经开始处理（任意文件）
                cursor = await db.execute(
                    "SELECT 1 FROM confirmations WHERE message_id = ? LIMIT 1",
                    (message_id,)
                )
            row = await cursor.fetchone()
            return row is not None
    
    async def mark_message_processed(self, message_id: str):
        """标记消息已处理（用于去重，实际由 create_confirmation 完成）"""
        pass  # create_confirmation 时已自动记录
    
    async def is_file_pending(self, message_id: str, file_key: str) -> bool:
        """检查文件是否已经在处理中（防止重复上传）"""
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(
                "SELECT 1 FROM confirmations WHERE message_id = ? AND file_key = ? AND status IN ('pending', 'confirmed')",
                (message_id, file_key)
            )
            row = await cursor.fetchone()
            return row is not None
    
    async def create_confirmation(
        self,
        message_id: str,
        file_key: str,
        file_name: str,
        folder_token: str,
        sender_id: str,
        chat_id: str,
        card_message_id: Optional[str] = None,
        source_message_id: Optional[str] = None
    ) -> int:
        """创建确认记录"""
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute("""
                INSERT INTO confirmations 
                (message_id, file_key, file_name, folder_token, sender_id, chat_id, card_message_id, source_message_id)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (message_id, file_key, file_name, folder_token, sender_id, chat_id, card_message_id, source_message_id))
            await db.commit()
            return cursor.lastrowid
    
    async def update_confirmation_status(
        self,
        message_id: str,
        status: str,
        card_message_id: Optional[str] = None
    ):
        """更新确认状态"""
        async with aiosqlite.connect(self.db_path) as db:
            if status == "confirmed":
                await db.execute("""
                    UPDATE confirmations 
                    SET status = ?, confirmed_at = CURRENT_TIMESTAMP, card_message_id = COALESCE(?, card_message_id)
                    WHERE message_id = ?
                """, (status, card_message_id, message_id))
            elif status == "completed":
                await db.execute("""
                    UPDATE confirmations 
                    SET status = ?, completed_at = CURRENT_TIMESTAMP
                    WHERE message_id = ?
                """, (status, message_id))
            else:
                await db.execute("""
                    UPDATE confirmations 
                    SET status = ?, card_message_id = COALESCE(?, card_message_id)
                    WHERE message_id = ?
                """, (status, card_message_id, message_id))
            await db.commit()
    
    async def get_confirmation(self, message_id: str) -> Optional[Dict[str, Any]]:
        """获取确认记录"""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute("""
                SELECT * FROM confirmations WHERE message_id = ?
            """, (message_id,))
            row = await cursor.fetchone()
            if row:
                return dict(row)
            return None
    
    async def log_operation(
        self,
        chat_id: str,
        sender_id: str,
        file_name: str,
        folder_token: str,
        status: str,
        error_msg: Optional[str] = None,
        details: Optional[str] = None
    ):
        """记录操作日志"""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("""
                INSERT INTO operation_logs 
                (chat_id, sender_id, file_name, folder_token, status, error_msg, details)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (chat_id, sender_id, file_name, folder_token, status, error_msg, details))
            await db.commit()
    
    async def get_recent_logs(self, limit: int = 100) -> List[Dict[str, Any]]:
        """获取最近的操作日志"""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute("""
                SELECT * FROM operation_logs 
                ORDER BY timestamp DESC 
                LIMIT ?
            """, (limit,))
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]


# 全局状态管理器实例
state_manager = StateManager()
