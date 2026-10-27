import hashlib
import time
import logging
from telegram import Update
from telegram.ext import ContextTypes
from config import load_config
from modules.utils import AdminCache, safe_delete_message, schedule_message_deletion, send_ephemeral_or_temporary_warning

logger = logging.getLogger("AntirepeatModule")

class AntirepeatHandler:
    def __init__(self, admin_cache: AdminCache):
        self.admin_cache = admin_cache
        # Histórico de mensagens por usuário: { (chat_id, user_id): [ (msg_hash, timestamp), ... ] }
        self._user_messages = {}

    def _get_content_identifier(self, message) -> str:
        """Gera um hash ou identificador do conteúdo da mensagem (texto, sticker, imagem, etc.)."""
        # Se for texto
        if message.text:
            normalized = " ".join(message.text.strip().lower().split())
            if len(normalized) > 3:  # Ignora palavras monossilábicas como 'oi', 'ok', 'sim'
                return hashlib.sha256(normalized.encode("utf-8")).hexdigest()

        # Se for legenda de mídia
        if message.caption:
            normalized = " ".join(message.caption.strip().lower().split())
            if len(normalized) > 3:
                return hashlib.sha256(normalized.encode("utf-8")).hexdigest()

        # Se for figurinha / sticker
        if message.sticker:
            return f"sticker_{message.sticker.file_unique_id}"

        # Se for animação (GIF)
        if message.animation:
            return f"anim_{message.animation.file_unique_id}"

        # Se for foto
        if message.photo:
            # Pega o maior tamanho da foto
            return f"photo_{message.photo[-1].file_unique_id}"

        return ""

    def _cleanup_history(self, chat_id: int, user_id: int, window: int):
        now = time.time()
        key = (chat_id, user_id)
        if key in self._user_messages:
            self._user_messages[key] = [
                (h, t) for (h, t) in self._user_messages[key] if (now - t) <= window
            ]
            if not self._user_messages[key]:
                del self._user_messages[key]

    async def handle_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
        """Verifica se a mensagem atual é uma repetição de uma mensagem recente do mesmo usuário.
        Retorna True se for repetição e tiver sido apagada."""
        message = update.effective_message
        user = update.effective_user
        chat = update.effective_chat

        if not message or not user or not chat:
            return False

        if chat.type == "private":
            return False

        # Administradores e Usuários Livres (Whitelist) não sofrem bloqueio de repetição
        if await self.admin_cache.is_admin(chat, user.id):
            return False

        config = load_config()
        from config import is_user_whitelisted
        if is_user_whitelisted(config, user.id):
            return False
        repeat_cfg = config.get("antirepeat", {})
        if not repeat_cfg.get("enabled", True):
            return False

        content_id = self._get_content_identifier(message)
        if not content_id:
            return False

        # Suporta janela em horas (ex: 2h = 7200s) ou em segundos
        window = repeat_cfg.get("time_window_seconds", 7200)
        if "time_window_hours" in repeat_cfg and repeat_cfg["time_window_hours"]:
            window = int(float(repeat_cfg["time_window_hours"]) * 3600)

        max_repeated = repeat_cfg.get("max_repeated", 2)
        warn_del_sec = repeat_cfg.get("warn_delete_after_seconds", 8)

        now = time.time()
        key = (chat.id, user.id)

        # Limpa registros antigos
        self._cleanup_history(chat.id, user.id, window)

        history = self._user_messages.setdefault(key, [])

        # Conta quantas vezes este conteúdo idêntico foi enviado nesta janela de tempo
        same_count = sum(1 for (h, _) in history if h == content_id)

        # Adiciona a mensagem atual ao histórico
        history.append((content_id, now))

        # Se atingiu ou ultrapassou o limite de repetições permitidas
        if same_count >= (max_repeated - 1):
            await safe_delete_message(context.bot, chat.id, message.message_id)

            if window >= 3600:
                h_val = window / 3600
                time_label = f"{int(h_val)} hora(s)" if h_val.is_integer() else f"{h_val:.1f} horas"
            else:
                time_label = f"{window // 60} minuto(s)" if window >= 60 else f"{window}s"

            user_mention = f"@{user.username}" if user.username else user.first_name
            warn_text = (
                f"⚠️ {user_mention}, esta mensagem ou arquivo já foi enviado recentemente "
                f"(limite de repetição em {time_label}). Evite repetições no grupo!"
            )
            await send_ephemeral_or_temporary_warning(
                bot=context.bot,
                chat_id=chat.id,
                user_id=user.id,
                text=warn_text,
                context=context,
                delete_after_seconds=warn_del_sec
            )

            logger.info(f"Mensagem repetida apagada de {user.id} no chat {chat.id} (janela {time_label})")

            try:
                import html
                from modules.logger_channel import send_mod_log
                await send_mod_log(
                    bot=context.bot,
                    event_type="spam",
                    title="Mensagem Repetida Removida",
                    user_info=f"{html.escape(user.first_name)} (<code>{user.id}</code>)",
                    reason=f"Repetiu mensagem/mídia na janela de {time_label}"
                )
            except Exception as e:
                logger.debug(f"Falha ao enviar log de repetição: {e}")

            return True

        return False
