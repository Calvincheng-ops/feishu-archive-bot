"""事件订阅处理 - 支持多步骤卡片交互"""
import json
import asyncio
from typing import Dict, Any, Optional

from app.services.keyword_matcher import match_keywords
from app.services.file_transfer import file_transfer_service, FileInfo
from app.services.card_builder import card_builder
from app.services.mapping_service import mapping_service
from app.services.state_manager import state_manager
from app.utils.lark_client import lark_client


class EventHandler:
    """处理飞书事件"""
    
    def __init__(self):
        pass
    
    async def handle_message_event(self, event: Dict[str, Any]):
        """
        处理消息接收事件
        
        流程：
        1. 用户引用文件消息 + @机器人 + "final版本"
        2. 机器人检测到文件，发送卡片让用户选择目标文件夹
        3. 用户选择文件夹后，发送确认卡片
        4. 用户确认后，执行上传
        """
        try:
            message = event.get("message", {})
            sender = event.get("sender", {})
            
            message_id = message.get("message_id", "")
            chat_id = message.get("chat_id", "")
            chat_type = message.get("chat_type", "")
            message_type = message.get("message_type", "")
            content = message.get("content", "{}")
            sender_id = sender.get("sender_id", {}).get("open_id", "")
            
            print(f"[EVENT] msg_id={message_id}, chat={chat_id}, type={message_type}, sender={sender_id}", flush=True)
            
            # 消息去重 - 使用 SQLite 持久化（重启后也能去重）
            if await state_manager.is_message_processed(message_id):
                print(f"[EVENT] 消息已在处理中，检查是否有新文件: {message_id}", flush=True)
            await state_manager.mark_message_processed(message_id)
            
            # 只处理群聊消息
            if chat_type != "group":
                return
            
            # 检查是否被 @
            mentions = message.get("mentions", [])
            bot_mentioned = any(
                m.get("key") == "@_user_1" or m.get("id", {}).get("open_id", "") == "bot"
                for m in mentions
            )
            
            if not bot_mentioned:
                return
            
            # 提取文本内容
            text = ""
            if isinstance(content, str):
                try:
                    content_obj = json.loads(content)
                except:
                    content_obj = {}
            else:
                content_obj = content
            
            text = content_obj.get("text", "")
            
            # 检查附件 - 当前消息或被引用的消息
            files = file_transfer_service.extract_files_from_message(message)
            source_message_id = message_id  # 记录文件来源的消息ID
            
            # 如果当前消息没有附件，检查是否引用了其他消息
            if not files:
                parent_id = message.get("parent_id", "")
                root_id = message.get("root_id", "")
                ref_message_id = parent_id or root_id
                
                if ref_message_id:
                    print(f"[EVENT] 当前消息无附件，检查引用消息: {ref_message_id}", flush=True)
                    try:
                        ref_msg = await lark_client.get_message(ref_message_id)
                        if ref_msg:
                            files = file_transfer_service.extract_files_from_message(ref_msg)
                            if files:
                                source_message_id = ref_message_id
                                print(f"[EVENT] 从引用消息中找到 {len(files)} 个附件", flush=True)
                    except Exception as e:
                        print(f"[EVENT] 获取引用消息失败: {e}", flush=True)
            
            if not files:
                await lark_client.send_card(
                    chat_id=chat_id,
                    card_json=card_builder.build_no_attachment_card()
                )
                return
            
            # 关键词匹配
            match_result = match_keywords(text)
            
            if not match_result.matched:
                return
            
            # 查询群-文件夹映射
            mapping = await mapping_service.get_folder_mapping(chat_id)
            
            if not mapping:
                try:
                    chat_info = await lark_client.get_chat_info(chat_id)
                    chat_name = chat_info.get("name", "未知群")
                except:
                    chat_name = "未知群"
                
                await lark_client.send_card(
                    chat_id=chat_id,
                    card_json=card_builder.build_no_mapping_card(chat_name)
                )
                return
            
            # 获取发送人信息
            user_info = await lark_client.get_user_info(sender_id)
            sender_name = user_info.get("name", "未知用户")
            
            # 检查是否有子文件夹
            subfolders = await lark_client.list_folder_children(mapping.folder_token)
            has_subfolders = len(subfolders) > 0
            
            # 对每个文件发送选择卡片
            for file_info in files:
                # 检查文件是否已经在处理中（防止重复上传）
                if await state_manager.is_file_pending(message_id, file_info.file_key):
                    print(f"[EVENT] 文件已在处理中，跳过: {file_info.file_name}", flush=True)
                    continue
                
                # 创建确认记录（保存发送人信息，用于后续校验）
                await state_manager.create_confirmation(
                    message_id=message_id,
                    file_key=file_info.file_key,
                    file_name=file_info.file_name,
                    folder_token=mapping.folder_token,
                    sender_id=sender_id,
                    chat_id=chat_id,
                    source_message_id=source_message_id
                )
                
                # 发送文件检测卡片
                card_json = card_builder.build_file_detected_card(
                    file_name=file_info.file_name,
                    folder_name=mapping.folder_name,
                    sender_name=sender_name,
                    file_key=file_info.file_key,
                    folder_token=mapping.folder_token,
                    message_id=message_id,
                    has_subfolders=has_subfolders
                )
                
                await lark_client.send_card(chat_id=chat_id, card_json=card_json)
            
        except Exception as e:
            print(f"[EVENT] 处理消息事件失败: {e}", flush=True)
            import traceback
            traceback.print_exc()
    
    async def handle_card_callback(self, callback: Dict[str, Any]) -> Dict[str, Any]:
        """
        处理卡片回调事件
        
        支持的 action:
        - browse_folders: 查看子文件夹
        - select_folder: 选择某个子文件夹
        - confirm_upload: 确认上传（直接上传到根目录或选定的子文件夹）
        - do_upload: 执行上传
        - go_back: 返回上一级
        - cancel: 取消
        
        返回: 卡片 JSON（用于更新原卡片）或 None
        """
        try:
            action = callback.get("action", {})
            value = action.get("value", {})
            operator = callback.get("operator", {})
            
            action_type = value.get("action", "")
            operator_id = operator.get("open_id", "")
            
            print(f"[CARD] action={action_type}, operator={operator_id}", flush=True)
            
            if action_type == "browse_folders":
                return await self._handle_browse_folders(value, operator_id, callback)
            elif action_type == "select_folder":
                return await self._handle_select_folder(value, operator_id, callback)
            elif action_type == "confirm_upload":
                return await self._handle_confirm_upload(value, operator_id, callback)
            elif action_type == "do_upload":
                return await self._handle_do_upload(value, operator_id, callback)
            elif action_type == "go_back":
                return await self._handle_go_back(value, operator_id, callback)
            elif action_type == "cancel":
                return await self._handle_cancel(value, operator_id, callback)
                
        except Exception as e:
            print(f"[CARD] 处理卡片回调失败: {e}", flush=True)
            import traceback
            traceback.print_exc()
        
        return None
    
    def _get_chat_id_from_callback(self, callback: Dict[str, Any]) -> str:
        """从回调中获取 chat_id"""
        # 优先从 open_chat_id 获取
        chat_id = callback.get("open_chat_id", "")
        if not chat_id:
            # 从 context 获取
            chat_id = callback.get("context", {}).get("open_chat_id", "")
        return chat_id
    
    async def _check_sender_permission(self, message_id: str, operator_id: str) -> bool:
        """检查操作人是否是发送人"""
        confirmation = await state_manager.get_confirmation(message_id)
        if not confirmation:
            return False
        return operator_id == confirmation.get("sender_id", "")
    
    async def _get_operator_name(self, operator_id: str) -> str:
        """获取操作人名称"""
        try:
            operator_info = await lark_client.get_user_info(operator_id)
            return operator_info.get("name", "未知用户")
        except Exception as e:
            print(f"[CARD] 获取操作人名称失败: {e}", flush=True)
            return "未知用户"
    
    async def _handle_browse_folders(self, value: Dict, operator_id: str, callback: Dict):
        """处理浏览子文件夹"""
        file_key = value.get("file_key", "")
        folder_token = value.get("folder_token", "")
        message_id = value.get("message_id", "")
        file_name = value.get("file_name", "")
        sender_name = value.get("sender_name", "")
        chat_id = self._get_chat_id_from_callback(callback)
        
        # 权限检查
        if message_id and not await self._check_sender_permission(message_id, operator_id):
            print(f"[BROWSE] 权限不足: operator={operator_id}", flush=True)
            operator_name = await self._get_operator_name(operator_id)
            return card_builder.build_no_permission_card(operator_name)
        
        # 获取子文件夹列表
        subfolders = await lark_client.list_folder_children(folder_token)
        print(f"[BROWSE] 子文件夹列表: {subfolders}", flush=True)
        
        if not subfolders:
            # 没有子文件夹，发送确认卡片（新卡片）
            confirm_card = card_builder.build_confirm_upload_card(
                file_name=file_name,
                folder_name="根目录",
                parent_folder_name="",
                sender_name=sender_name,
                file_key=file_key,
                folder_token=folder_token,
                message_id=message_id
            )
            if chat_id:
                await lark_client.send_card(chat_id=chat_id, card_json=confirm_card)
            
            # 更新原卡片为"已选择文件夹"状态
            return card_builder.build_selected_card(file_name, "根目录")
        else:
            # 有子文件夹，发送子文件夹列表卡片（新卡片）
            mapping = await mapping_service.get_folder_mapping(chat_id)
            parent_name = mapping.folder_name if mapping else "归档文件夹"
            
            folder_list_card = card_builder.build_folder_list_card(
                file_name=file_name,
                file_key=file_key,
                message_id=message_id,
                parent_folder_token=folder_token,
                parent_folder_name=parent_name,
                folders=subfolders,
                sender_name=sender_name
            )
            if chat_id:
                await lark_client.send_card(chat_id=chat_id, card_json=folder_list_card)
            
            # 更新原卡片为"已查看子文件夹"状态（无按钮）
            return card_builder.build_browse_done_card(file_name, parent_name)
    
    async def _handle_select_folder(self, value: Dict, operator_id: str, callback: Dict):
        """处理选择子文件夹"""
        file_key = value.get("file_key", "")
        folder_token = value.get("folder_token", "")
        folder_name = value.get("folder_name", "")
        parent_folder_name = value.get("parent_folder_name", "")
        message_id = value.get("message_id", "")
        file_name = value.get("file_name", "")
        sender_name = value.get("sender_name", "")
        chat_id = self._get_chat_id_from_callback(callback)
        
        # 权限检查
        if message_id and not await self._check_sender_permission(message_id, operator_id):
            print(f"[SELECT] 权限不足: operator={operator_id}", flush=True)
            operator_name = await self._get_operator_name(operator_id)
            return card_builder.build_no_permission_card(operator_name)
        
        # 检查选中的文件夹是否还有子文件夹
        subfolders = await lark_client.list_folder_children(folder_token)
        
        if subfolders:
            # 还有子文件夹，发送新的子文件夹列表卡片
            new_folder_card = card_builder.build_folder_list_card(
                file_name=file_name,
                file_key=file_key,
                message_id=message_id,
                parent_folder_token=folder_token,
                parent_folder_name=folder_name,
                folders=subfolders,
                sender_name=sender_name
            )
            if chat_id:
                await lark_client.send_card(chat_id=chat_id, card_json=new_folder_card)
            
            # 更新原卡片为"已选择文件夹"状态（无按钮）
            return card_builder.build_selected_card(file_name, folder_name)
        else:
            # 没有子文件夹了，发送确认卡片（新卡片）
            confirm_card = card_builder.build_confirm_upload_card(
                file_name=file_name,
                folder_name=folder_name,
                parent_folder_name=parent_folder_name,
                sender_name=sender_name,
                file_key=file_key,
                folder_token=folder_token,
                message_id=message_id
            )
            if chat_id:
                await lark_client.send_card(chat_id=chat_id, card_json=confirm_card)
            
            # 更新原卡片为"已选择文件夹"状态（无按钮）
            return card_builder.build_selected_card(file_name, folder_name)
    
    async def _handle_confirm_upload(self, value: Dict, operator_id: str, callback: Dict):
        """处理确认上传（从文件检测卡片直接上传到根目录或选定的文件夹）"""
        # 校验操作人
        message_id = value.get("message_id", "")
        if message_id and not await self._check_sender_permission(message_id, operator_id):
            print(f"[CONFIRM] 权限不足: operator={operator_id}", flush=True)
            operator_name = await self._get_operator_name(operator_id)
            return card_builder.build_no_permission_card(operator_name)
        
        file_key = value.get("file_key", "")
        folder_token = value.get("folder_token", "")
        folder_name = value.get("folder_name", "")
        file_name = value.get("file_name", "")
        chat_id = self._get_chat_id_from_callback(callback)
        
        # 发送新卡片显示确认上传
        confirm_card = card_builder.build_confirm_upload_card(
            file_name=file_name,
            folder_name=folder_name,
            parent_folder_name="",
            sender_name="",
            file_key=file_key,
            folder_token=folder_token,
            message_id=message_id
        )
        
        if chat_id:
            await lark_client.send_card(chat_id=chat_id, card_json=confirm_card)
        
        # 更新原卡片为"已选择"状态
        return card_builder.build_selected_card(file_name, folder_name)
    
    async def _handle_do_upload(self, value: Dict, operator_id: str, callback: Dict):
        """执行文件上传"""
        file_key = value.get("file_key", "")
        folder_token = value.get("folder_token", "")
        message_id = value.get("message_id", "")
        file_name = value.get("file_name", "")
        chat_id = self._get_chat_id_from_callback(callback)
        
        print(f"[UPLOAD] 开始上传: file={file_name}, folder={folder_token}, operator={operator_id}", flush=True)
        
        # 校验操作人是否是发送人
        is_permitted = await self._check_sender_permission(message_id, operator_id)
        print(f"[UPLOAD] 权限检查: {is_permitted}, message_id={message_id}", flush=True)
        
        if not is_permitted:
            print(f"[UPLOAD] 权限不足", flush=True)
            operator_name = await self._get_operator_name(operator_id)
            return card_builder.build_no_permission_card(operator_name)
        
        # 获取确认记录
        confirmation = await state_manager.get_confirmation(message_id)
        print(f"[UPLOAD] 确认记录: {confirmation}", flush=True)
        
        if not confirmation:
            print(f"[UPLOAD] 未找到确认记录，message_id={message_id}", flush=True)
            return card_builder.build_error_card(
                file_name=file_name,
                error_msg="未找到上传确认记录，请重新发起"
            )
        
        # 更新状态为已确认
        await state_manager.update_confirmation_status(message_id, "confirmed")
        
        # 获取源消息ID（用于下载文件）
        source_message_id = confirmation.get("source_message_id", message_id)
        print(f"[UPLOAD] 源消息ID: {source_message_id}", flush=True)
        
        # 先启动后台任务执行实际上传
        asyncio.create_task(self._do_upload_background(
            chat_id=chat_id,
            message_id=message_id,
            source_message_id=source_message_id,
            file_key=file_key,
            file_name=file_name,
            folder_token=folder_token,
            operator_id=operator_id
        ))
        
        # 返回上传中卡片（更新原卡片）
        return card_builder.build_uploading_card(file_name)
    
    async def _do_upload_background(
        self,
        chat_id: str,
        message_id: str,
        source_message_id: str,
        file_key: str,
        file_name: str,
        folder_token: str,
        operator_id: str
    ):
        """后台执行文件上传"""
        try:
            # 执行文件传输
            print(f"[UPLOAD] 开始下载并上传文件...", flush=True)
            result = await file_transfer_service.download_and_upload(
                message_id=source_message_id,
                file_key=file_key,
                file_name=file_name,
                folder_token=folder_token
            )
            print(f"[UPLOAD] 上传结果: {result}", flush=True)
            
            if result["success"]:
                await state_manager.update_confirmation_status(message_id, "completed")
                await state_manager.log_operation(
                    chat_id=chat_id,
                    sender_id=operator_id,
                    file_name=file_name,
                    folder_token=folder_token,
                    status="success"
                )
                
                if chat_id:
                    # 获取文件夹名称
                    mapping = await mapping_service.get_folder_mapping(chat_id)
                    folder_display_name = mapping.folder_name if mapping else "归档文件夹"
                    print(f"[UPLOAD] 文件夹显示名称: {folder_display_name}, chat_id={chat_id}", flush=True)
                    
                    await lark_client.send_card(
                        chat_id=chat_id,
                        card_json=card_builder.build_success_card(
                            file_name=file_name,
                            folder_name=folder_display_name
                        )
                    )
            else:
                await state_manager.update_confirmation_status(message_id, "failed")
                await state_manager.log_operation(
                    chat_id=chat_id,
                    sender_id=operator_id,
                    file_name=file_name,
                    folder_token=folder_token,
                    status="failed",
                    error_msg=result.get("error", "未知错误")
                )
                
                if chat_id:
                    await lark_client.send_card(
                        chat_id=chat_id,
                        card_json=card_builder.build_error_card(
                            file_name=file_name,
                            error_msg=result.get("error", "未知错误")
                        )
                    )
        except Exception as e:
            print(f"[UPLOAD] 后台上传任务失败: {e}", flush=True)
            import traceback
            traceback.print_exc()
    
    async def _handle_go_back(self, value: Dict, operator_id: str, callback: Dict):
        """返回上一级文件夹"""
        file_key = value.get("file_key", "")
        folder_token = value.get("folder_token", "")
        folder_name = value.get("folder_name", "")
        message_id = value.get("message_id", "")
        file_name = value.get("file_name", "")
        sender_name = value.get("sender_name", "")
        chat_id = self._get_chat_id_from_callback(callback)
        
        # 权限检查
        if message_id and not await self._check_sender_permission(message_id, operator_id):
            print(f"[GO_BACK] 权限不足: operator={operator_id}", flush=True)
            operator_name = await self._get_operator_name(operator_id)
            return card_builder.build_no_permission_card(operator_name)
        
        # 获取目标文件夹的子文件夹列表
        subfolders = await lark_client.list_folder_children(folder_token)
        print(f"[GO_BACK] 返回到文件夹: {folder_name}, 子文件夹: {subfolders}", flush=True)
        
        if subfolders:
            # 有子文件夹，显示子文件夹列表
            return card_builder.build_folder_list_card(
                file_name=file_name,
                file_key=file_key,
                message_id=message_id,
                parent_folder_token=folder_token,
                parent_folder_name=folder_name,
                folders=subfolders,
                sender_name=sender_name
            )
        else:
            # 没有子文件夹，显示文件检测卡片（允许直接上传到根目录）
            return card_builder.build_file_detected_card(
                file_name=file_name,
                folder_name=folder_name,
                sender_name=sender_name,
                file_key=file_key,
                folder_token=folder_token,
                message_id=message_id,
                has_subfolders=False
            )
    
    async def _handle_cancel(self, value: Dict, operator_id: str, callback: Dict):
        """取消上传 - 只有发起人可以取消"""
        # 从 value 中获取 message_id 用于权限检查
        message_id = value.get("message_id", "")
        
        if message_id:
            # 检查操作人是否是发起人
            is_permitted = await self._check_sender_permission(message_id, operator_id)
            if not is_permitted:
                print(f"[CANCEL] 权限不足: operator={operator_id}", flush=True)
                operator_name = await self._get_operator_name(operator_id)
                return card_builder.build_no_permission_card(operator_name)
            
            # 检查是否已经完成上传
            confirmation = await state_manager.get_confirmation(message_id)
            if confirmation and confirmation.get("status") in ["completed", "confirmed"]:
                print(f"[CANCEL] 文件已上传，忽略取消操作", flush=True)
                return card_builder.build_error_card(
                    file_name=confirmation.get("file_name", ""),
                    error_msg="文件已上传成功，无法取消"
                )
        
        print(f"[CANCEL] 取消上传: operator={operator_id}", flush=True)
        return card_builder.build_cancel_card()


# 全局事件处理器实例
event_handler = EventHandler()
