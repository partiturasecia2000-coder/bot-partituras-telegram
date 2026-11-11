"""Autorização para operações administrativas no privado."""
import logging
import os

from telegram.constants import ChatMemberStatus

from config import load_config

logger = logging.getLogger(__name__)


async def can_manage_private_chat(chat, user_id: int) -> bool:
    """Usa IDs explícitos ou verifica administração nos chats já vinculados."""
    cfg = load_config()
    configured_ids = os.getenv('BOT_ADMIN_IDS', '').strip()
    allowed = configured_ids.split(',') if configured_ids else cfg.get('panel_admin_ids', [])
    if allowed:
        return str(user_id) in {str(value).strip() for value in allowed}
    candidates = [cfg.get('main_group_id'), cfg.get('main_channel_id')]
    candidates += [item.get('id') for item in cfg.get('linked_groups', [])]
    candidates += [item.get('id') for item in cfg.get('linked_channels', [])]
    for chat_id in dict.fromkeys(value for value in candidates if value):
        try:
            member = await chat.get_bot().get_chat_member(chat_id, user_id)
            if member.status in (ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.OWNER):
                return True
        except Exception:
            # Falha de rede ou ausência de acesso não concede permissão.
            logger.debug('Não foi possível verificar administração no chat %s', chat_id)
    return False


async def require_management_access(update) -> bool:
    """Protege comandos/callbacks do acervo sem restringir a busca pública."""
    from modules.utils import AdminCache

    user = update.effective_user
    if user and await AdminCache().is_admin(update.effective_chat, user.id):
        return True
    if update.callback_query:
        await update.callback_query.answer('⛔ Apenas administradores.', show_alert=True)
    elif update.effective_message:
        await update.effective_message.reply_text('⛔ Apenas administradores podem executar esta ação.')
    return False
