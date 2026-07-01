"""确认卡片构建器 - 支持多步骤交互"""
import json
from typing import List, Dict, Any


class CardBuilder:
    """构建飞书交互卡片"""
    
    @staticmethod
    def build_file_detected_card(
        file_name: str,
        folder_name: str,
        sender_name: str,
        file_key: str,
        folder_token: str,
        message_id: str,
        confirmation_id: int = None,
        has_subfolders: bool = True
    ) -> Dict[str, Any]:
        """
        步骤1: 检测到文件卡片 - 选择上传方式
        
        用户可以选择：
        - 查看子文件夹（如果有）
        - 直接上传到根目录
        """
        actions = []
        
        if has_subfolders:
            actions.append({
                "tag": "button",
                "text": {"tag": "plain_text", "content": "📂 查看子文件夹"},
                "type": "primary",
                "value": {
                    "action": "browse_folders",
                    "file_key": file_key,
                    "folder_token": folder_token,
                    "message_id": message_id,
                    "confirmation_id": confirmation_id,
                    "file_name": file_name,
                    "sender_name": sender_name
                }
            })
        
        actions.append({
            "tag": "button",
            "text": {"tag": "plain_text", "content": "⬆️ 直接上传到根目录"},
            "type": "default",
            "value": {
                "action": "confirm_upload",
                "file_key": file_key,
                "folder_token": folder_token,
                "folder_name": folder_name,
                "message_id": message_id,
                "confirmation_id": confirmation_id,
                "file_name": file_name
            }
        })
        
        actions.append({
            "tag": "button",
            "text": {"tag": "plain_text", "content": "❌ 取消"},
            "type": "danger",
            "value": {"action": "cancel", "message_id": message_id, "confirmation_id": confirmation_id}
        })
        
        return {
            "config": {"wide_screen_mode": True},
            "header": {
                "title": {"tag": "plain_text", "content": "📁 检测到 Final 版本文件"},
                "template": "blue"
            },
            "elements": [
                {
                    "tag": "div",
                    "text": {
                        "tag": "lark_md",
                        "content": (
                            f"**文件名**：{file_name}\n"
                            f"**目标文件夹**：{folder_name}\n"
                            f"**发送人**：{sender_name}"
                        )
                    }
                },
                {"tag": "hr"},
                {
                    "tag": "note",
                    "elements": [{"tag": "plain_text", "content": "⚠️ 仅发送人可操作"}]
                },
                {"tag": "action", "actions": actions}
            ]
        }
    
    @staticmethod
    def build_folder_list_card(
        file_name: str,
        file_key: str,
        message_id: str,
        confirmation_id: int,
        parent_folder_token: str,
        parent_folder_name: str,
        folders: List[Dict[str, str]],
        sender_name: str
    ) -> Dict[str, Any]:
        """
        步骤2: 子文件夹列表卡片
        
        显示子文件夹供用户选择
        增加"上传到当前文件夹"按钮
        """
        actions = []
        
        # 添加"上传到当前文件夹"按钮
        actions.append({
            "tag": "button",
            "text": {"tag": "plain_text", "content": f"⬆️ 上传到「{parent_folder_name}」"},
            "type": "primary",
            "value": {
                "action": "confirm_upload",
                "file_key": file_key,
                "folder_token": parent_folder_token,
                "folder_name": parent_folder_name,
                "message_id": message_id,
                "confirmation_id": confirmation_id,
                "file_name": file_name
            }
        })
        
        for folder in folders[:10]:  # 最多显示10个
            actions.append({
                "tag": "button",
                "text": {"tag": "plain_text", "content": f"📁 {folder['name']}"},
                "type": "default",
                "value": {
                    "action": "select_folder",
                    "file_key": file_key,
                    "folder_token": folder['token'],
                    "folder_name": folder['name'],
                    "parent_folder_name": parent_folder_name,
                    "message_id": message_id,
                    "confirmation_id": confirmation_id,
                    "file_name": file_name,
                    "sender_name": sender_name
                }
            })
        
        # 添加返回按钮
        actions.append({
            "tag": "button",
            "text": {"tag": "plain_text", "content": "⬅️ 返回"},
            "type": "default",
            "value": {
                "action": "go_back",
                "file_key": file_key,
                "folder_token": parent_folder_token,
                "folder_name": parent_folder_name,
                "message_id": message_id,
                "confirmation_id": confirmation_id,
                "file_name": file_name,
                "sender_name": sender_name
            }
        })
        
        return {
            "config": {"wide_screen_mode": True},
            "header": {
                "title": {"tag": "plain_text", "content": f"📂 选择子文件夹 — {parent_folder_name}"},
                "template": "blue"
            },
            "elements": [
                {
                    "tag": "div",
                    "text": {
                        "tag": "lark_md",
                        "content": f"**文件**：{file_name}\n请选择要上传到的子文件夹："
                    }
                },
                {"tag": "hr"},
                {"tag": "action", "actions": actions}
            ]
        }
    
    @staticmethod
    def build_confirm_upload_card(
        file_name: str,
        folder_name: str,
        parent_folder_name: str,
        sender_name: str,
        file_key: str,
        folder_token: str,
        message_id: str,
        confirmation_id: int = None
    ) -> Dict[str, Any]:
        """
        步骤3: 确认上传卡片
        
        显示完整路径，用户确认后上传
        """
        full_path = f"{parent_folder_name} / {folder_name}" if parent_folder_name and parent_folder_name != folder_name else folder_name
        
        return {
            "config": {"wide_screen_mode": True},
            "header": {
                "title": {"tag": "plain_text", "content": "📋 确认上传"},
                "template": "orange"
            },
            "elements": [
                {
                    "tag": "div",
                    "text": {
                        "tag": "lark_md",
                        "content": (
                            f"**文件名**：{file_name}\n"
                            f"**目标路径**：{full_path}\n"
                            f"**发送人**：{sender_name}"
                        )
                    }
                },
                {"tag": "hr"},
                {
                    "tag": "note",
                    "elements": [{"tag": "plain_text", "content": "⚠️ 仅发送人可操作确认"}]
                },
                {
                    "tag": "action",
                    "actions": [
                        {
                            "tag": "button",
                            "text": {"tag": "plain_text", "content": "✅ 确认上传"},
                            "type": "primary",
                            "value": {
                                "action": "do_upload",
                                "file_key": file_key,
                                "folder_token": folder_token,
                                "message_id": message_id,
                                "confirmation_id": confirmation_id,
                                "file_name": file_name
                            }
                        },
                        {
                            "tag": "button",
                            "text": {"tag": "plain_text", "content": "❌ 取消"},
                            "type": "danger",
                            "value": {"action": "cancel", "message_id": message_id, "confirmation_id": confirmation_id}
                        }
                    ]
                }
            ]
        }
    
    @staticmethod
    def build_uploading_card(file_name: str) -> Dict[str, Any]:
        """上传中卡片"""
        return {
            "config": {"wide_screen_mode": True},
            "header": {
                "title": {"tag": "plain_text", "content": "⏳ 上传中..."},
                "template": "wathet"
            },
            "elements": [
                {
                    "tag": "div",
                    "text": {
                        "tag": "lark_md",
                        "content": f"正在上传 **{file_name}**，请稍候..."
                    }
                }
            ]
        }
    
    @staticmethod
    def build_success_card(
        file_name: str,
        folder_name: str,
        file_url: str = ""
    ) -> Dict[str, Any]:
        """上传成功卡片"""
        content = f"✅ **文件上传成功**\n\n**文件名**：{file_name}\n**目标文件夹**：{folder_name}"
        if file_url:
            content += f"\n\n[点击查看文件]({file_url})"
        
        return {
            "config": {"wide_screen_mode": True},
            "header": {
                "title": {"tag": "plain_text", "content": "✅ 上传成功"},
                "template": "green"
            },
            "elements": [
                {
                    "tag": "div",
                    "text": {"tag": "lark_md", "content": content}
                }
            ]
        }
    
    @staticmethod
    def build_error_card(file_name: str, error_msg: str) -> Dict[str, Any]:
        """上传失败卡片"""
        return {
            "config": {"wide_screen_mode": True},
            "header": {
                "title": {"tag": "plain_text", "content": "❌ 上传失败"},
                "template": "red"
            },
            "elements": [
                {
                    "tag": "div",
                    "text": {
                        "tag": "lark_md",
                        "content": (
                            f"**文件名**：{file_name}\n\n"
                            f"**失败原因**：{error_msg}\n\n"
                            f"请联系管理员或手动上传。"
                        )
                    }
                }
            ]
        }
    
    @staticmethod
    def build_cancel_card() -> Dict[str, Any]:
        """取消上传卡片"""
        return {
            "config": {"wide_screen_mode": True},
            "header": {
                "title": {"tag": "plain_text", "content": "ℹ️ 已取消"},
                "template": "grey"
            },
            "elements": [
                {
                    "tag": "div",
                    "text": {"tag": "lark_md", "content": "文件上传已取消。"}
                }
            ]
        }
    
    @staticmethod
    def build_browse_done_card(file_name: str, folder_name: str) -> Dict[str, Any]:
        """已查看子文件夹卡片 - 更新原卡片"""
        return {
            "config": {"wide_screen_mode": True},
            "header": {
                "title": {"tag": "plain_text", "content": "📂 已查看子文件夹"},
                "template": "grey"
            },
            "elements": [
                {
                    "tag": "div",
                    "text": {
                        "tag": "lark_md",
                        "content": (
                            f"**文件**：{file_name}\n"
                            f"**目标文件夹**：{folder_name}\n\n"
                            f"子文件夹列表已发送，请在下方卡片中选择目标文件夹。"
                        )
                    }
                }
            ]
        }
    
    @staticmethod
    def build_selected_card(file_name: str, folder_name: str) -> Dict[str, Any]:
        """已选择文件夹卡片 - 更新原卡片"""
        return {
            "config": {"wide_screen_mode": True},
            "header": {
                "title": {"tag": "plain_text", "content": "✅ 已选择文件夹"},
                "template": "grey"
            },
            "elements": [
                {
                    "tag": "div",
                    "text": {
                        "tag": "lark_md",
                        "content": (
                            f"**文件**：{file_name}\n"
                            f"**目标文件夹**：{folder_name}\n\n"
                            f"确认上传卡片已发送，请确认上传。"
                        )
                    }
                }
            ]
        }
    
    @staticmethod
    def build_no_mapping_card(chat_name: str) -> Dict[str, Any]:
        """未配置映射提示卡片"""
        return {
            "config": {"wide_screen_mode": True},
            "header": {
                "title": {"tag": "plain_text", "content": "⚠️ 未配置归档目标"},
                "template": "orange"
            },
            "elements": [
                {
                    "tag": "div",
                    "text": {
                        "tag": "lark_md",
                        "content": (
                            f"当前群 **{chat_name}** 尚未配置归档目标文件夹。\n\n"
                            f"请联系管理员在映射配置表中添加本群的配置。"
                        )
                    }
                }
            ]
        }
    
    @staticmethod
    def build_no_attachment_card() -> Dict[str, Any]:
        """未检测到附件提示卡片"""
        return {
            "config": {"wide_screen_mode": True},
            "header": {
                "title": {"tag": "plain_text", "content": "⚠️ 未检测到附件"},
                "template": "orange"
            },
            "elements": [
                {
                    "tag": "div",
                    "text": {
                        "tag": "lark_md",
                        "content": (
                            "您的消息中未检测到文件或图片附件。\n\n"
                            "**使用方法**：\n"
                            "1. 先发送文件到群聊\n"
                            "2. 引用该文件消息，@机器人并说明这是 final 版本"
                        )
                    }
                }
            ]
        }
    
    @staticmethod
    def build_no_permission_card(operator_name: str = None) -> Dict[str, Any]:
        """
        无权限操作卡片
        
        Args:
            operator_name: 操作人名称（可选，如果提供则显示谁没有权限）
        """
        if operator_name:
            content = f"**{operator_name}**，你没有权限执行此操作。\n\n只有发送文件指令的人才能执行此操作。"
        else:
            content = "只有发送文件指令的人才能执行此操作。"
        
        return {
            "config": {"wide_screen_mode": True},
            "header": {
                "title": {"tag": "plain_text", "content": "⚠️ 无权操作"},
                "template": "red"
            },
            "elements": [
                {
                    "tag": "div",
                    "text": {
                        "tag": "lark_md",
                        "content": content
                    }
                }
            ]
        }


# 全局卡片构建器实例
card_builder = CardBuilder()
