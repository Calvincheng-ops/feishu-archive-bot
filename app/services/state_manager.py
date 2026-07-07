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
            await db.execute("""
                CREATE UNIQUE INDEX IF NOT EXISTS idx_confirmations_message_file
                ON confirmations(message_id, file_key)
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
    
    async def is_file_processed(self, message_id: str, file_key: str) -> bool:
        """检查文件是否已经创建过归档流程（防止重复卡片和重复上传）"""
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(
                """
                SELECT 1 FROM confirmations
                WHERE message_id = ? AND file_key = ?
                  AND status IN ('pending', 'confirmed', 'completed')
                LIMIT 1
                """,
                (message_id, file_key)
            )
            row = await cursor.fetchone()
            return row is not None

    async def is_file_pending(self, message_id: str, file_key: str) -> bool:
        """向后兼容旧调用名。"""
        return await self.is_file_processed(message_id, file_key)
    
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
    ) -> Optional[int]:
        """创建确认记录。若同一 message_id + file_key 已存在，则返回 None。"""
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute("""
                INSERT OR IGNORE INTO confirmations
                (message_id, file_key, file_name, folder_token, sender_id, chat_id, card_message_id, source_message_id)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (message_id, file_key, file_name, folder_token, sender_id, chat_id, card_message_id, source_message_id))
            await db.commit()
            if cursor.rowcount == 0:
                return None
            return cursor.lastrowid
    
    async def update_confirmation_status(
        self,
        message_id: str,
        status: str,
        file_key: Optional[str] = None,
        card_message_id: Optional[str] = None
    ):
        """更新确认状态"""
        async with aiosqlite.connect(self.db_path) as db:
            params = [status]
            where = "message_id = ?"
            where_params = [message_id]
            if file_key:
                where += " AND file_key = ?"
                where_params.append(file_key)

            if status == "confirmed":
                await db.execute("""
                    UPDATE confirmations 
                    SET status = ?, confirmed_at = CURRENT_TIMESTAMP, card_message_id = COALESCE(?, card_message_id)
                    WHERE """ + where, (*params, card_message_id, *where_params))
            elif status == "completed":
                await db.execute("""
                    UPDATE confirmations 
                    SET status = ?, completed_at = CURRENT_TIMESTAMP
                    WHERE """ + where, (*params, *where_params))
            else:
                await db.execute("""
                    UPDATE confirmations 
                    SET status = ?, card_message_id = COALESCE(?, card_message_id)
                    WHERE """ + where, (*params, card_message_id, *where_params))
            await db.commit()

    async def mark_confirmation_confirmed(self, message_id: str, file_key: str) -> bool:
        """原子地把 pending 记录改为 confirmed，返回是否成功。"""
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute("""
                UPDATE confirmations
                SET status = 'confirmed', confirmed_at = CURRENT_TIMESTAMP
                WHERE message_id = ? AND file_key = ? AND status = 'pending'
            """, (message_id, file_key))
            await db.commit()
            return cursor.rowcount == 1
    
    async def get_confirmation(self, message_id: str, file_key: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """获取确认记录"""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            if file_key:
                cursor = await db.execute("""
                    SELECT * FROM confirmations
                    WHERE message_id = ? AND file_key = ?
                """, (message_id, file_key))
            else:
                cursor = await db.execute("""
                    SELECT * FROM confirmations WHERE message_id = ?
                    ORDER BY id DESC
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

    async def get_recent_confirmations(self, limit: int = 50) -> List[Dict[str, Any]]:
        """获取最近的归档确认记录"""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute("""
                SELECT * FROM confirmations
                ORDER BY created_at DESC
                LIMIT ?
            """, (limit,))
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]


# 全局状态管理器实例
state_manager = StateManager()
