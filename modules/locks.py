import html
import logging
from telegram import Update
from telegram.constants import ParseMode, MessageEntityType
from telegram.ext import ContextTypes
from config import load_config, save_config
from modules.utils import AdminCache, safe_delete_message, schedule_message_deletion, safe_reply, send_ephemeral_or_temporary_warning
from modules.logger_channel import send_mod_log

logger = logging.getLogger("LocksModule")

LOCK_NAMES = {
    "sticker": "Figurinhas / Stickers",
    "gif": "GIFs / Animações",
    "audio": "Arquivos de Áudio",
    "voice": "Mensagens de Voz",
    "video": "Vídeos",
    "videonote": "Vídeos Redondos (Vídeo Notas)",
    "document": "Documentos e Arquivos",
    "contact": "Compartilhamento de Contatos",
    "poll": "Enquetes",
    "forward": "Mensagens Encaminhadas",
    "link": "Links e URLs Externos"
}

ALIAS_MAP = {
    "stickers": "sticker",
    "figurinha": "sticker",
    "figurinhas": "sticker",
    "animation": "gif",
    "animations": "gif",
    "gifs": "gif",
    "audios": "audio",
    "musica": "audio",
    "voz": "voice",
    "videos": "video",
    "videonotes": "videonote",
    "round": "videonote",
    "doc": "document",
    "docs": "document",
    "arquivo": "document",
    "arquivos": "document",
    "contato": "contact",
    "contatos": "contact",
    "enquete": "poll",
    "enquetes": "poll",
    "polls": "poll",
    "encaminhamento": "forward",
    "encaminhamentos": "forward",
    "forwards": "forward",
    "links": "link",
    "url": "link",
    "urls": "link"
}

class LocksHandler:
    def __init__(self, admin_cache: AdminCache):
        self.admin_cache = admin_cache

    async def _require_admin(self, update: Update) -> bool:
        chat = update.effective_chat
        user = update.effective_user
        if not chat or not user:
            return False
        if chat.type == "private":
            return True
        return await self.admin_cache.is_admin(chat, user.id)

    async def _clean_trigger(self, update: Update):
        """Apaga o comando no grupo caso ativado na configuração."""
        chat = update.effective_chat
        msg = update.effective_message
        if chat and chat.type != "private" and msg:
            cfg = load_config()
            if cfg.get("command_cleanup", {}).get("delete_admin_commands", True):
                try:
                    await safe_delete_message(update.get_bot(), chat.id, msg.message_id)
                except Exception:
                    pass

    async def cmd_lock(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Bloqueia um tipo específico de mídia no grupo (Estilo Rose Bot)."""
        chat = update.effective_chat
        if not await self._require_admin(update):
            await safe_reply(update, "⛔ Apenas administradores podem gerenciar bloqueios de mídia.")
            return

        await self._clean_trigger(update)

        if not context.args:
            types_list = ", ".join([f"`{k}`" for k in LOCK_NAMES.keys()])
            sent = await safe_reply(
                update,
                f"🔒 *Como usar o /lock (Estilo Rose Bot):*\n\n"
                f"Uso: `/lock <tipo>`\n\n"
                f"*Tipos disponíveis:*\n{types_list}\n\n"
                f"_Exemplo:_ `/lock sticker` ou `/lock audio`\n"
                f"Para ver todos os bloqueios ativos: `/locks`",
                parse_mode=ParseMode.MARKDOWN
            )
            return

        raw_type = context.args[0].lower().strip()
        lock_type = ALIAS_MAP.get(raw_type, raw_type)

        if lock_type not in LOCK_NAMES:
            await safe_reply(update, f"❌ Tipo `{raw_type}` não reconhecido. Use `/locks` para ver os tipos suportados.", parse_mode=ParseMode.MARKDOWN)
            return

        cfg = load_config()
        locks = cfg.setdefault("locks", {})
        locks[lock_type] = True
        save_config(cfg)

        label = LOCK_NAMES[lock_type]
        sent = await safe_reply(update, f"🔒 *Bloqueado com Sucesso!*\nO envio de *{label}* foi bloqueado para membros comuns.", parse_mode=ParseMode.MARKDOWN)
        del_sec = cfg.get("command_cleanup", {}).get("bot_notice_delete_seconds", 10)
        if del_sec > 0 and chat and chat.type != "private" and sent:
            schedule_message_deletion(context, chat.id, sent.message_id, del_sec)

    async def cmd_unlock(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Desbloqueia um tipo específico de mídia no grupo."""
        chat = update.effective_chat
        if not await self._require_admin(update):
            await safe_reply(update, "⛔ Apenas administradores podem gerenciar bloqueios de mídia.")
            return

        await self._clean_trigger(update)

        if not context.args:
            await safe_reply(update, "Uso: `/unlock <tipo>` (ex: `/unlock sticker`)", parse_mode=ParseMode.MARKDOWN)
            return

        raw_type = context.args[0].lower().strip()
        lock_type = ALIAS_MAP.get(raw_type, raw_type)

        if lock_type not in LOCK_NAMES:
            await safe_reply(update, f"❌ Tipo `{raw_type}` não reconhecido.", parse_mode=ParseMode.MARKDOWN)
            return

        cfg = load_config()
        locks = cfg.setdefault("locks", {})
        locks[lock_type] = False
        save_config(cfg)

        label = LOCK_NAMES[lock_type]
        sent = await safe_reply(update, f"🔓 *Desbloqueado com Sucesso!*\nO envio de *{label}* agora está permitido.", parse_mode=ParseMode.MARKDOWN)
        del_sec = cfg.get("command_cleanup", {}).get("bot_notice_delete_seconds", 10)
        if del_sec > 0 and chat and chat.type != "private" and sent:
            schedule_message_deletion(context, chat.id, sent.message_id, del_sec)

    async def cmd_locks(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Exibe o painel visual com o status de todos os bloqueios ativos no grupo."""
        await self._clean_trigger(update)
        cfg = load_config()
        locks = cfg.get("locks", {})

        text = "🛡️ *Painel de Bloqueios de Mídia (/locks)*\n\n"
        text += "Status atual das permissões de mídia para membros:\n\n"

        for k, name in LOCK_NAMES.items():
            is_locked = locks.get(k, False)
            icon = "🔒 *Bloqueado*" if is_locked else "🔓 Liberado"
            text += f"• `{k}`: {icon} ({name})\n"

        text += (
            "\n💡 *Para alterar:* Use `/lock <tipo>` para bloquear ou `/unlock <tipo>` para liberar."
        )

        await safe_reply(update, text, parse_mode=ParseMode.MARKDOWN)

    async def check_locks(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
        """Verifica se a mensagem enviada viola algum lock ativo. Retorna True se foi bloqueada e apagada."""
        msg = update.effective_message
        user = update.effective_user
        chat = update.effective_chat

        if not msg or not user or not chat or chat.type == "private":
            return False

        # Admins e Usuários Livres (Whitelist) não sofrem bloqueios
        if await self.admin_cache.is_admin(chat, user.id):
            return False

        cfg = load_config()
        from config import is_user_whitelisted
        if is_user_whitelisted(cfg, user.id):
            return False
        locks = cfg.get("locks", {})
        if not locks:
            return False

        violated_type = None

        if locks.get("sticker") and msg.sticker:
            violated_type = "sticker"
        elif locks.get("gif") and msg.animation:
            violated_type = "gif"
        elif locks.get("audio") and msg.audio:
            violated_type = "audio"
        elif locks.get("voice") and msg.voice:
            violated_type = "voice"
        elif locks.get("video") and msg.video:
            violated_type = "video"
        elif locks.get("videonote") and msg.video_note:
            violated_type = "videonote"
        elif locks.get("document") and msg.document:
            violated_type = "document"
        elif locks.get("contact") and msg.contact:
            violated_type = "contact"
        elif locks.get("poll") and msg.poll:
            violated_type = "poll"
        elif locks.get("forward"):
            is_forward = False
            if hasattr(msg, "forward_origin") and msg.forward_origin is not None:
                is_forward = True
            elif hasattr(msg, "forward_date") and msg.forward_date is not None:
                is_forward = True
            if is_forward:
                violated_type = "forward"
        elif locks.get("link"):
            entities = (msg.entities or ()) + (msg.caption_entities or ())
            for entity in entities:
                if entity.type in (MessageEntityType.URL, MessageEntityType.TEXT_LINK):
                    violated_type = "link"
                    break

        if violated_type:
            await safe_delete_message(context.bot, chat.id, msg.message_id)
            label = LOCK_NAMES.get(violated_type, violated_type)
            user_mention = f"@{user.username}" if user.username else user.first_name
            warn_text = f"🔒 {user_mention}, o envio de *{label}* está temporariamente bloqueado neste grupo."
            
            try:
                await send_ephemeral_or_temporary_warning(
                    bot=context.bot,
                    chat_id=chat.id,
                    user_id=user.id,
                    text=warn_text,
                    context=context,
                    delete_after_seconds=8,
                    parse_mode=ParseMode.MARKDOWN
                )
            except Exception:
                pass

            logger.info(f"Lock violado ({violated_type}) por {user.id} no chat {chat.id}")
            await send_mod_log(
                bot=context.bot,
                event_type="spam",
                title=f"Mídia Bloqueada ({label})",
                user_info=f"{html.escape(user.first_name)} (<code>{user.id}</code>)",
                reason=f"Envio de {label} com lock ativado"
            )
            return True

        return False
