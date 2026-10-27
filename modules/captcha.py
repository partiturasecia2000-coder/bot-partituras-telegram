import html
import time
import logging
from telegram import Update, ChatPermissions, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode
from telegram.ext import ContextTypes
from config import load_config
from modules.utils import safe_delete_message, schedule_message_deletion
from modules.logger_channel import send_mod_log

logger = logging.getLogger("CaptchaModule")

class CaptchaHandler:
    def __init__(self):
        # (chat_id, user_id): {"message_id": int, "join_time": float, "timeout_seconds": int}
        self.pending = {}

    def is_enabled(self) -> bool:
        cfg = load_config()
        return bool(cfg.get("captcha", {}).get("enabled", False))

    async def challenge_member(self, chat, member, context: ContextTypes.DEFAULT_TYPE) -> bool:
        """Restringe o novo membro e envia o botão de verificação humana."""
        if not self.is_enabled() or member.is_bot:
            return False

        cfg = load_config()
        cap_cfg = cfg.get("captcha", {})
        timeout_sec = cap_cfg.get("timeout_seconds", 180)
        kick_on_timeout = cap_cfg.get("kick_on_timeout", True)

        # 1. Restringe o usuário temporariamente
        try:
            await chat.restrict_member(
                user_id=member.id,
                permissions=ChatPermissions(
                    can_send_messages=False,
                    can_send_media_messages=False,
                    can_send_other_messages=False,
                    can_add_web_page_previews=False
                )
            )
        except Exception as e:
            logger.warning(f"Não foi possível aplicar restrição de captcha para {member.id}: {e}")

        # 2. Envia a mensagem do Captcha com botão inline
        minutos = max(1, timeout_sec // 60)
        text = (
            f"👋 Olá, <b>{html.escape(member.first_name)}</b>!\n\n"
            f"🎵 <b>Bem-vindo(a) ao grupo {html.escape(chat.title or '')}!</b>\n\n"
            f"🛡️ Para manter nossa comunidade segura contra robôs de spam, por favor clique no botão musical abaixo "
            f"em até <b>{minutos} minuto(s)</b> para liberar seu acesso às mensagens:"
        )

        keyboard = [
            [
                InlineKeyboardButton("🎵 Sou Humano / Entrar no Grupo", callback_data=f"captcha:v:{member.id}")
            ]
        ]

        try:
            sent_msg = await chat.send_message(
                text=text,
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode=ParseMode.HTML
            )
            key = (chat.id, member.id)
            self.pending[key] = {
                "message_id": sent_msg.message_id,
                "join_time": time.time(),
                "timeout_seconds": timeout_sec
            }

            # Agenda timeout de expulsão
            if context.job_queue and kick_on_timeout:
                context.job_queue.run_once(
                    self._timeout_callback,
                    when=timeout_sec,
                    data={
                        "chat_id": chat.id,
                        "user_id": member.id,
                        "message_id": sent_msg.message_id,
                        "user_name": member.first_name
                    },
                    name=f"captcha_to_{chat.id}_{member.id}"
                )
            return True
        except Exception as e:
            logger.error(f"Erro ao enviar desafio de captcha: {e}")
            return False

    async def _timeout_callback(self, context: ContextTypes.DEFAULT_TYPE):
        data = context.job.data
        chat_id = data["chat_id"]
        user_id = data["user_id"]
        message_id = data["message_id"]
        user_name = data.get("user_name", "Usuário")

        key = (chat_id, user_id)
        if key not in self.pending:
            return  # Já verificado

        del self.pending[key]

        # Apaga mensagem de captcha
        await safe_delete_message(context.bot, chat_id, message_id)

        # Expulsa o membro
        try:
            chat = await context.bot.get_chat(chat_id)
            await chat.unban_member(user_id)
            logger.info(f"Membro {user_id} expulso por timeout de captcha no chat {chat_id}")

            await send_mod_log(
                bot=context.bot,
                event_type="kick",
                title="Captcha Expirado (Anti-Bot)",
                user_info=f"{html.escape(user_name)} (<code>{user_id}</code>)",
                reason="Não confirmou o botão humano no tempo limite"
            )
        except Exception as e:
            logger.debug(f"Falha ao expulsar por timeout de captcha: {e}")

    async def handle_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        user = query.from_user
        chat = update.effective_chat
        data = query.data

        if not data.startswith("captcha:v:"):
            return

        target_id_str = data.split(":")[-1]
        if not target_id_str.isdigit():
            return

        target_user_id = int(target_id_str)

        # Se não for o próprio usuário
        if user.id != target_user_id:
            await query.answer("⛔ Este botão de verificação é exclusivo para o novo membro que acabou de entrar!", show_alert=True)
            return

        key = (chat.id, user.id)
        info = self.pending.pop(key, None)

        # Libera todas as permissões no grupo
        try:
            await chat.restrict_member(
                user_id=user.id,
                permissions=ChatPermissions(
                    can_send_messages=True,
                    can_send_media_messages=True,
                    can_send_other_messages=True,
                    can_add_web_page_previews=True
                )
            )
        except Exception as e:
            logger.warning(f"Erro ao remover restrições de captcha para {user.id}: {e}")

        # Remove o alerta de captcha
        if info:
            await safe_delete_message(context.bot, chat.id, info["message_id"])
        else:
            await safe_delete_message(context.bot, chat.id, query.message.message_id)

        await query.answer("✅ Verificação concluída com sucesso! Seja bem-vindo(a)!", show_alert=False)

        await send_mod_log(
            bot=context.bot,
            event_type="join",
            title="Captcha Concluído",
            user_info=f"{html.escape(user.first_name)} (<code>{user.id}</code>)",
            details="Identidade confirmada com sucesso"
        )

        # Dispara as boas-vindas oficiais
        from modules.welcome import send_welcome_message
        await send_welcome_message(chat, user, context)
