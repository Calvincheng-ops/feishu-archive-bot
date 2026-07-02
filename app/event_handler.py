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
        self._operator_name_cache: Dict[str, str] = {}  # open_id -> name cache

    async def handle_message_event(self, event: Dict[str, Any]):
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

            # 消息去重 - 使用 SQLite 持久化
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
            source_message_id = message_id

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

            # 缓存发送人名称（后续权限卡片从缓存读取，不调 API）
            if sender_id:
                self._operator_name_cache[sender_id] = sender_name

            # 检查是否有子文件夹
            subfolders = await lark_client.list_folder_children(mapping.folder_token)
            has_subfolders = len(subfolders) > 0

            # 对每个文件发送选择卡片
            for file_info in files:
                # 检查文件是否已经在处理中
                if await state_manager.is_file_pending(message_id, file_info.file_key):
                    print(f"[EVENT] 文件已在处理中，跳过: {file_info.file_name}", flush=True)
                    continue

                # 创建确认记录
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
        """处理卡片回调事件"""
        try:
            action = callback.get("action", {})
            value = action.get("value", {})
            operator = callback.get("operator", {})

            action_type = value.get("action", "")

            # 统一提取 operator_id（兼容两种回调格式）
            # 卡片回调: operator.open_id
            # 事件订阅: operator.operator_id.open_id
            operator_id = (
                operator.get("open_id", "") or
                operator.get("operator_id", {}).get("open_id", "")
            )

            print(f"[CARD] action={action_type}, operator_id={operator_id}", flush=True)

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
        chat_id = callback.get("open_chat_id", "")
        if not chat_id:
            chat_id = callback.get("context", {}).get("open_chat_id", "")
        return chat_id

    async def _check_sender_permission(self, message_id: str, operator_id: str) -> bool:
        """检查操作人是否是发送人"""
        if not message_id or not operator_id:
            return False
        confirmation = await state_manager.get_confirmation(message_id)
        if not confirmation:
            return False
        return operator_id == confirmation.get("sender_id", "")

    async def _get_cached_operator_name(self, operator_id: str) -> Optional[str]:
        """
        从内存缓存读取操作人名称（O(1)，不调飞书 API）

        名称在 handle_message_event 获取发送人信息时预缓存。
        未命中说明此人不是初始发送人，返回 None（build_no_permission_card 会显示通用提示）。
        """
        return self._operator_name_cache.get(operator_id)

    async def _handle_browse_folders(self, value: Dict, operator_id: str, callback: Dict):
        """处理浏览子文件夹"""
        file_key = value.get("file_key", "")
        folder_token = value.get("folder_token", "")
        message_id = value.get("message_id", "")
        file_name = value.get("file_name", "")
        sender_name = value.get("sender_name", "")
        chat_id = self._get_chat_id_from_callback(callback)

        # 权限检查（从缓存读操作人名称，不调 API）
        if message_id and not await self._check_sender_permission(message_id, operator_id):
            print(f"[BROWSE] 权限不足: operator={operator_id}", flush=True)
            operator_name = await self._get_cached_operator_name(operator_id)
            return card_builder.build_no_permission_card(operator_name)

        # 获取子文件夹列表
        subfolders = await lark_client.list_folder_children(folder_token)
        print(f"[BROWSE] 子文件夹列表: {subfolders}", flush=True)

        if not subfolders:
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

            return card_builder.build_selected_card(file_name, "根目录")
        else:
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
            operator_name = await self._get_cached_operator_name(operator_id)
            return card_builder.build_no_permission_card(operator_name)

        subfolders = await lark_client.list_folder_children(folder_token)

        if subfolders:
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

            return card_builder.build_selected_card(file_name, folder_name)
        else:
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

            return card_builder.build_selected_card(file_name, folder_name)

    async def _handle_confirm_upload(self, value: Dict, operator_id: str, callback: Dict):
        """处理确认上传"""
        message_id = value.get("message_id", "")
        if message_id and not await self._check_sender_permission(message_id, operator_id):
            print(f"[CONFIRM] 权限不足: operator={operator_id}", flush=True)
            operator_name = await self._get_cached_operator_name(operator_id)
            return card_builder.build_no_permission_card(operator_name)

        file_key = value.get("file_key", "")
        folder_token = value.get("folder_token", "")
        folder_name = value.get("folder_name", "")
        file_name = value.get("file_name", "")
        chat_id = self._get_chat_id_from_callback(callback)

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

        return card_builder.build_selected_card(file_name, folder_name)

    async def _handle_do_upload(self, value: Dict, operator_id: str, callback: Dict):
        """执行文件上传"""
        file_key = value.get("file_key", "")
        folder_token = value.get("folder_token", "")
        message_id = value.get("message_id", "")
        file_name = value.get("file_name", "")
        chat_id = self._get_chat_id_from_callback(callback)

        print(f"[UPLOAD] 开始上传: file={file_name}, folder={folder_token}, operator={operator_id}", flush=True)

        is_permitted = await self._check_sender_permission(message_id, operator_id)
        print(f"[UPLOAD] 权限检查: {is_permitted}, message_id={message_id}", flush=True)

        if not is_permitted:
            print(f"[UPLOAD] 权限不足", flush=True)
            operator_name = await self._get_cached_operator_name(operator_id)
            return card_builder.build_no_permission_card(operator_name)

        confirmation = await state_manager.get_confirmation(message_id)
        print(f"[UPLOAD] 确认记录: {confirmation}", flush=True)

        if not confirmation:
            print(f"[UPLOAD] 未找到确认记录，message_id={message_id}", flush=True)
            return card_builder.build_error_card(
                file_name=file_name,
                error_msg="未找到上传确认记录，请重新发起"
            )

        await state_manager.update_confirmation_status(message_id, "confirmed")

        source_message_id = confirmation.get("source_message_id", message_id)
        print(f"[UPLOAD] 源消息ID: {source_message_id}", flush=True)

        asyncio.create_task(self._do_upload_background(
            chat_id=chat_id,
            message_id=message_id,
            source_message_id=source_message_id,
            file_key=file_key,
            file_name=file_name,
            folder_token=folder_token,
            operator_id=operator_id
        ))

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

        if message_id and not await self._check_sender_permission(message_id, operator_id):
            print(f"[GO_BACK] 权限不足: operator={operator_id}", flush=True)
            operator_name = await self._get_cached_operator_name(operator_id)
            return card_builder.build_no_permission_card(operator_name)

        subfolders = await lark_client.list_folder_children(folder_token)
        print(f"[GO_BACK] 返回到文件夹: {folder_name}, 子文件夹: {subfolders}", flush=True)

        if subfolders:
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
        message_id = value.get("message_id", "")

        if message_id:
            is_permitted = await self._check_sender_permission(message_id, operator_id)
            if not is_permitted:
                print(f"[CANCEL] 权限不足: operator={operator_id}", flush=True)
                operator_name = await self._get_cached_operator_name(operator_id)
                return card_builder.build_no_permission_card(operator_name)

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
