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
        db_dir = os.path.dirname(self.db_path)
        if db_dir:
            os.makedirs(db_dir, exist_ok=True)
    
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
                    file_type TEXT DEFAULT 'file',
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

            await self._ensure_column(db, "confirmations", "file_type", "TEXT DEFAULT 'file'")
            await db.execute("""
                CREATE UNIQUE INDEX IF NOT EXISTS idx_confirmations_message_file
                ON confirmations(message_id, file_key)
            """)

            await db.execute("""
                CREATE TABLE IF NOT EXISTS processed_messages (
                    message_id TEXT PRIMARY KEY,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
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
    
    async def _ensure_column(self, db, table_name: str, column_name: str, column_sql: str):
        cursor = await db.execute(f"PRAGMA table_info({table_name})")
        columns = [row[1] for row in await cursor.fetchall()]
        if column_name not in columns:
            await db.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_sql}")

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
                cursor = await db.execute(
                    "SELECT 1 FROM processed_messages WHERE message_id = ? LIMIT 1",
                    (message_id,)
                )
            row = await cursor.fetchone()
            return row is not None
    
    async def mark_message_processed(self, message_id: str):
        """标记消息已处理（用于飞书重复推送去重）"""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                "INSERT OR IGNORE INTO processed_messages (message_id) VALUES (?)",
                (message_id,)
            )
            await db.commit()
    
    async def is_file_pending(self, message_id: str, file_key: str) -> bool:
        """检查文件是否已经在处理中（防止重复上传）"""
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(
                "SELECT 1 FROM confirmations WHERE message_id = ? AND file_key = ? AND status IN ('pending', 'confirmed', 'completed')",
                (message_id, file_key)
            )
            row = await cursor.fetchone()
            return row is not None
    
    async def create_confirmation(
        self,
        message_id: str,
        file_key: str,
        file_name: str,
        file_type: str,
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
                (message_id, file_key, file_name, file_type, folder_token, sender_id, chat_id, card_message_id, source_message_id)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                message_id,
                file_key,
                file_name,
                file_type,
                folder_token,
                sender_id,
                chat_id,
                card_message_id,
                source_message_id
            ))
            await db.commit()
            return cursor.lastrowid

    async def get_confirmation_by_id(self, confirmation_id: int) -> Optional[Dict[str, Any]]:
        """获取单个文件的确认记录"""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute("""
                SELECT * FROM confirmations WHERE id = ?
            """, (confirmation_id,))
            row = await cursor.fetchone()
            if row:
                return dict(row)
            return None

    async def update_confirmation_status_by_id(
        self,
        confirmation_id: int,
        status: str,
        card_message_id: Optional[str] = None
    ):
        """按确认记录 ID 更新单个文件状态"""
        async with aiosqlite.connect(self.db_path) as db:
            if status == "confirmed":
                await db.execute("""
                    UPDATE confirmations
                    SET status = ?, confirmed_at = CURRENT_TIMESTAMP, card_message_id = COALESCE(?, card_message_id)
                    WHERE id = ?
                """, (status, card_message_id, confirmation_id))
            elif status == "completed":
                await db.execute("""
                    UPDATE confirmations
                    SET status = ?, completed_at = CURRENT_TIMESTAMP
                    WHERE id = ?
                """, (status, confirmation_id))
            else:
                await db.execute("""
                    UPDATE confirmations
                    SET status = ?, card_message_id = COALESCE(?, card_message_id)
                    WHERE id = ?
                """, (status, card_message_id, confirmation_id))
            await db.commit()
    
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
