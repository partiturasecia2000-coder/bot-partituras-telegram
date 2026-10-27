import html
import logging
from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes
from config import load_config
from modules.logger_channel import send_mod_log

logger = logging.getLogger("JoinRequestsModule")

async def handle_chat_join_request(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Manipula solicitações de entrada com aprovação em canais e grupos (Join Requests)."""
    req = update.chat_join_request
    if not req:
        return

    chat = req.chat
    user = req.from_user
    cfg = load_config()
    jr_cfg = cfg.get("join_requests", {})

    is_channel = chat.type == "channel"
    chat_type_label = "Canal" if is_channel else "Grupo"
    chat_title = chat.title or chat_type_label

    auto_approve = jr_cfg.get("auto_approve", True)
    user_name = user.first_name or "Usuário"
    user_handle = f" (@{user.username})" if user.username else ""
    user_id_str = str(user.id)

    if auto_approve:
        try:
            await req.approve()
            logger.info(f"Solicitação de entrada aprovada automaticamente para {user.id} no {chat_type_label} {chat.id} ({chat_title})")

            # Envia mensagem acolhedora no privado se configurado
            if jr_cfg.get("send_welcome_dm", True):
                dm_template = jr_cfg.get(
                    "dm_message",
                    "👋 Olá, {name}!\n\nSua solicitação de entrada no {tipo} *{group}* foi aprovada com sucesso! 🎵\nSeja muito bem-vindo(a) à nossa comunidade musical!"
                )
                tipo_str = "canal" if is_channel else "grupo"
                dm_text = dm_template.format(name=user_name, group=chat_title, tipo=tipo_str)
                try:
                    await context.bot.send_message(chat_id=user.id, text=dm_text, parse_mode=ParseMode.MARKDOWN)
                except Exception as e:
                    logger.debug(f"Não foi possível enviar DM para {user.id}: {e}")

            # Dispara as boas-vindas oficiais no grupo se não for canal
            if not is_channel:
                try:
                    from modules.welcome import handle_member_join
                    await handle_member_join(chat, user, context, captcha_handler=None)
                except Exception as e_w:
                    logger.debug(f"Erro ao disparar boas-vindas após aprovação: {e_w}")

            # Log de auditoria
            await send_mod_log(
                bot=context.bot,
                event_type="join",
                title=f"Inscrição Aprovada no {chat_type_label}" if is_channel else "Entrada Aprovada no Grupo",
                user_info=f"<b>{html.escape(user_name)}</b>{user_handle} [ID: <code>{user_id_str}</code>]",
                details=f"📍 <b>Local:</b> {html.escape(chat_title)}"
            )
        except Exception as e:
            logger.error(f"Erro ao aprovar solicitação de {user.id} no {chat_type_label}: {e}")
    else:
        # Se não for auto-aprovação, registra solicitação pendente no canal de auditoria
        await send_mod_log(
            bot=context.bot,
            event_type="join",
            title=f"Solicitação Pendente no {chat_type_label}",
            user_info=f"<b>{html.escape(user_name)}</b>{user_handle} [ID: <code>{user_id_str}</code>]",
            details=f"Aguardando aprovação manual no {chat_type_label} <b>{html.escape(chat_title)}</b>"
        )
