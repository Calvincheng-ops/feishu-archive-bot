"""应用配置管理"""
from pydantic_settings import BaseSettings
from typing import Optional


class Settings(BaseSettings):
    """应用配置"""
    # 飞书应用凭证（用户提供的新应用）
    # 注意：不能用 FEISHU_APP_ID/FEISHU_APP_SECRET，会被 Hermes 环境变量覆盖
    bot_app_id: str = ""
    bot_app_secret: str = ""
    
    # 事件订阅配置
    encrypt_key: str = ""  # 需要在飞书后台配置
    verification_token: str = ""  # 需要在飞书后台配置
    
    # 映射配置（多维表格）
    bitable_app_token: str = ""  # 多维表格 token
    bitable_table_id: str = ""  # 数据表 ID
    
    # 应用配置
    max_file_size_mb: int = 100  # 最大文件大小（MB）
    cache_refresh_interval: int = 300  # 映射缓存刷新间隔（秒）
    log_level: str = "INFO"
    feishu_tenant_domain: str = ""  # 飞书租户域名（如 westoeast.feishu.cn），用于拼文件链接
    
    # 数据库
    db_path: str = "./data/archive_bot.db"
    
    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


settings = Settings()
