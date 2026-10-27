import re
import html
import time
import urllib.parse
from datetime import datetime, timedelta, timezone
import logging
from telegram import Update, ChatPermissions
from telegram.constants import MessageEntityType, ParseMode
from telegram.ext import ContextTypes
from config import load_config
from modules.utils import AdminCache, safe_delete_message, schedule_message_deletion, send_ephemeral_or_temporary_warning
from modules.logger_channel import send_mod_log

logger = logging.getLogger("AntispamModule")

# Regex para links gerais e links específicos do Telegram
URL_REGEX = re.compile(r"(?:https?://|www\.)[^\s]+|[a-zA-Z0-9-]+\.(?:com|org|net|io|me|xyz|app|site|online|top|live)[^\s]*", re.IGNORECASE)
TG_INVITE_REGEX = re.compile(r"(?:https?://)?(?:t\.me|telegram\.me)/(?:\+|joinchat/|[a-zA-Z0-9_]+)", re.IGNORECASE)


def is_url_whitelisted(url_str: str, allowed_patterns: list, raw_text: str = "") -> bool:
    """
    Verifica se uma URL, trecho de link ou domínio está liberado na lista branca.
    Permite domínios (drive.google.com), links completos ou qualquer trecho/pasta (drive.google.com/drive/folders/...).
    """
    if not allowed_patterns:
        return False

    clean_url = re.sub(r"^https?://", "", str(url_str).lower().strip()).rstrip("/")
    clean_url = re.sub(r"^www\.", "", clean_url)
    clean_unquoted = urllib.parse.unquote(clean_url)

    clean_raw = re.sub(r"^https?://", "", str(raw_text).lower().strip()).rstrip("/")
    clean_raw = re.sub(r"^www\.", "", clean_raw)

    for pat in allowed_patterns:
        if not pat:
            continue
        clean_pat = re.sub(r"^https?://", "", str(pat).lower().strip()).rstrip("/")
        clean_pat = re.sub(r"^www\.", "", clean_pat)
        if not clean_pat:
            continue

        if clean_pat in clean_url or clean_pat in clean_unquoted or (clean_raw and clean_pat in clean_raw):
            return True

    return False

class AntispamHandler:
    def __init__(self, admin_cache: AdminCache):
        self.admin_cache = admin_cache
        # Armazena timestamps para detecção de flood: { (chat_id, user_id): [timestamp1, timestamp2, ...] }
        self._user_flood_history = {}
        # Armazena advertências por usuário: { (chat_id, user_id): int }
        self.user_warnings = {}

    def _cleanup_flood_history(self, chat_id: int, user_id: int, window: int):
        now = time.time()
        key = (chat_id, user_id)
        if key in self._user_flood_history:
            self._user_flood_history[key] = [t for t in self._user_flood_history[key] if now - t <= window]
            if not self._user_flood_history[key]:
                del self._user_flood_history[key]

    async def check_flood(self, update: Update, context: ContextTypes.DEFAULT_TYPE, config: dict) -> bool:
        """Verifica se o usuário está enviando mensagens rápido demais (flood). Retorna True se violou."""
        flood_cfg = config.get("antiflood", {})
        if not flood_cfg.get("enabled", True):
            return False

        message = update.effective_message
        user = update.effective_user
        chat = update.effective_chat

        from config import is_user_whitelisted
        if user and is_user_whitelisted(config, user.id):
            return False

        max_msgs = flood_cfg.get("max_messages", 5)
        window = flood_cfg.get("time_window_seconds", 5)
        mute_min = flood_cfg.get("mute_duration_minutes", 5)
        warn_del_sec = flood_cfg.get("warn_delete_after_seconds", 8)

        now = time.time()
        key = (chat.id, user.id)
        timestamps = self._user_flood_history.setdefault(key, [])
        timestamps.append(now)

        # Filtra timestamps recentes
        self._cleanup_flood_history(chat.id, user.id, window)
        timestamps = self._user_flood_history.get(key, [])

        if len(timestamps) > max_msgs:
            # Apaga mensagem atual
            await safe_delete_message(context.bot, chat.id, message.message_id)

            # Silencia o usuário
            until_date = datetime.now(timezone.utc) + timedelta(minutes=mute_min)
            try:
                await chat.restrict_member(
                    user_id=user.id,
                    permissions=ChatPermissions(can_send_messages=False),
                    until_date=until_date
                )
                user_mention = f"@{user.username}" if user.username else user.first_name
                warn_text = (
                    f"🔇 {user_mention} foi silenciado(a) por *{mute_min} minutos* "
                    f"devido ao envio excessivo de mensagens (Flood)."
                )
                await send_ephemeral_or_temporary_warning(
                    bot=context.bot,
                    chat_id=chat.id,
                    user_id=user.id,
                    text=warn_text,
                    context=context,
                    delete_after_seconds=warn_del_sec,
                    parse_mode=ParseMode.MARKDOWN
                )
                logger.warning(f"Usuário {user.id} silenciado por flood no chat {chat.id}")
                await send_mod_log(
                    bot=context.bot,
                    event_type="mute",
                    title=f"Membro Silenciado por Flood ({mute_min} min)",
                    user_info=f"{html.escape(user.first_name)} (<code>{user.id}</code>)",
                    reason=f"Mais de {max_msgs} mensagens em {window} segundos",
                    details=f"Silenciado por {mute_min} minutos."
                )
            except Exception as e:
                logger.error(f"Não foi possível silenciar usuário {user.id} por flood: {e}")

            # Limpa histórico para evitar silenciar repetidamente no mesmo bloco
            self._user_flood_history.pop(key, None)
            return True

        return False

    async def handle_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
        """Processa a mensagem para antispam, flood e palavras proibidas. Retorna True se a mensagem foi tratada/apagada."""
        message = update.effective_message
        user = update.effective_user
        chat = update.effective_chat

        if not message or not user or not chat:
            return False

        # Não analisa mensagens de chats privados
        if chat.type == "private":
            return False

        # Administradores e Usuários Livres (Whitelist) não sofrem restrições
        if await self.admin_cache.is_admin(chat, user.id):
            return False

        config = load_config()
        from config import is_user_whitelisted
        if is_user_whitelisted(config, user.id):
            return False
        antispam_cfg = config.get("antispam", {})
        warn_del_sec = antispam_cfg.get("warn_delete_after_seconds", 8)
        user_mention = f"@{user.username}" if user.username else user.first_name

        # 1. Verificação de Flood
        if await self.check_flood(update, context, config):
            return True

        if not antispam_cfg.get("enabled", True):
            return False

        text = message.text or message.caption or ""
        text_lower = text.lower()

        # 2. Bloqueio de Mensagens Encaminhadas de Canais/Outros Chats
        if antispam_cfg.get("block_forwards", True):
            is_forwarded = False
            # Suporte para PTB 20+ e PTB 22+ (forward_origin ou forward_date)
            if hasattr(message, "forward_origin") and message.forward_origin is not None:
                is_forwarded = True
            elif hasattr(message, "forward_date") and message.forward_date is not None:
                is_forwarded = True

            if is_forwarded:
                await safe_delete_message(context.bot, chat.id, message.message_id)
                warn = f"⚠️ {user_mention}, o envio de mensagens encaminhadas é proibido neste grupo."
                await send_ephemeral_or_temporary_warning(
                    bot=context.bot,
                    chat_id=chat.id,
                    user_id=user.id,
                    text=warn,
                    context=context,
                    delete_after_seconds=warn_del_sec
                )
                logger.info(f"Encaminhamento apagado de {user.id} no chat {chat.id}")
                await send_mod_log(
                    bot=context.bot,
                    event_type="spam",
                    title="Encaminhamento Bloqueado",
                    user_info=f"{html.escape(user.first_name)} (<code>{user.id}</code>)",
                    reason="Mensagem encaminhada de canal/chat externo"
                )
                return True

        # 3. Bloqueio de Links de Convite do Telegram
        if antispam_cfg.get("block_telegram_invites", True):
            if TG_INVITE_REGEX.search(text):
                allowed_domains = antispam_cfg.get("allowed_domains", [])
                is_allowed_invite = False
                for domain in allowed_domains:
                    clean_pattern = re.sub(r"^https?://", "", str(domain).lower().strip()).rstrip("/")
                    clean_pattern = re.sub(r"^www\.", "", clean_pattern)
                    if clean_pattern and clean_pattern in text_lower:
                        is_allowed_invite = True
                        break
                if not is_allowed_invite:
                    await safe_delete_message(context.bot, chat.id, message.message_id)
                    warn = f"⚠️ {user_mention}, convites para outros canais ou grupos do Telegram não são permitidos."
                    await send_ephemeral_or_temporary_warning(
                        bot=context.bot,
                        chat_id=chat.id,
                        user_id=user.id,
                        text=warn,
                        context=context,
                        delete_after_seconds=warn_del_sec
                    )
                    logger.info(f"Convite telegram apagado de {user.id} no chat {chat.id}")
                    await send_mod_log(
                        bot=context.bot,
                        event_type="spam",
                        title="Convite do Telegram Bloqueado",
                        user_info=f"{html.escape(user.first_name)} (<code>{user.id}</code>)",
                        reason="Link de convite t.me detectado",
                        details=f"Conteúdo: <i>{html.escape(text[:120])}</i>"
                    )
                    return True

        # 4. Bloqueio Geral de Links
        if antispam_cfg.get("block_links", True):
            has_link = False
            allowed_domains = antispam_cfg.get("allowed_domains", [])

            # Verifica entidades de mensagem (URL explícito ou link em texto)
            entities = (message.entities or ()) + (message.caption_entities or ())
            for entity in entities:
                if entity.type in (MessageEntityType.URL, MessageEntityType.TEXT_LINK):
                    url_val = entity.url if entity.url else text[entity.offset:entity.offset + entity.length]
                    if not is_url_whitelisted(url_val, allowed_domains, raw_text=text):
                        has_link = True
                        break

            # Checa também regex no texto bruto
            if not has_link and URL_REGEX.search(text):
                found_urls = URL_REGEX.findall(text)
                for raw_url in found_urls:
                    if not is_url_whitelisted(raw_url, allowed_domains, raw_text=text):
                        has_link = True
                        break

            if has_link:
                await safe_delete_message(context.bot, chat.id, message.message_id)
                warn = f"⚠️ {user_mention}, o envio de links não é permitido neste grupo."
                await send_ephemeral_or_temporary_warning(
                    bot=context.bot,
                    chat_id=chat.id,
                    user_id=user.id,
                    text=warn,
                    context=context,
                    delete_after_seconds=warn_del_sec
                )
                logger.info(f"Link bloqueado de {user.id} no chat {chat.id}")
                await send_mod_log(
                    bot=context.bot,
                    event_type="spam",
                    title="Link Externo Bloqueado",
                    user_info=f"{html.escape(user.first_name)} (<code>{user.id}</code>)",
                    reason="Link externo não autorizado",
                    details=f"Conteúdo: <i>{html.escape(text[:120])}</i>"
                )
                return True

        # 5. Palavras Proibidas (Blacklist) com Punição Configurável
        banned_words = antispam_cfg.get("banned_words", [])
        action = antispam_cfg.get("banned_words_action", "warn")  # "warn", "warning", "ban"

        for word in banned_words:
            if word and word.lower() in text_lower:
                await safe_delete_message(context.bot, chat.id, message.message_id)

                safe_user = html.escape(user_mention)
                spoiler_word = f"<tg-spoiler>{html.escape(word)}</tg-spoiler>"

                if action == "ban":
                    # Punição: Ban imediato
                    try:
                        await chat.ban_member(user_id=user.id)
                        notice = f"🔨 {safe_user} foi <b>banido(a)</b> por usar o termo proibido {spoiler_word}."
                    except Exception as e:
                        logger.error(f"Erro ao banir usuário por palavra proibida: {e}")
                        notice = f"⚠️ {safe_user}, sua mensagem continha o termo proibido {spoiler_word} e foi removida."

                elif action == "warning":
                    # Punição: Só Advertência com contagem (3 advertências = ban)
                    w_key = (chat.id, user.id)
                    curr_warns = self.user_warnings.get(w_key, 0) + 1
                    self.user_warnings[w_key] = curr_warns

                    if curr_warns >= 3:
                        try:
                            await chat.ban_member(user_id=user.id)
                            notice = f"🔨 {safe_user} atingiu o limite de <b>3 advertências</b> pelo termo {spoiler_word} e foi banido(a) do grupo."
                        except Exception:
                            notice = f"⚠️ {safe_user} atingiu 3 advertências pelo termo {spoiler_word}."
                        self.user_warnings.pop(w_key, None)
                    else:
                        notice = f"❗ {safe_user}, você recebeu uma advertência (<b>{curr_warns}/3</b>) pelo termo proibido {spoiler_word}! Sua mensagem foi removida."

                else:
                    # Punição: Só Aviso simples (sem contagem nem ban)
                    notice = f"⚠️ {safe_user}, o termo {spoiler_word} é proibido neste grupo. Sua mensagem foi removida."

                try:
                    await send_ephemeral_or_temporary_warning(
                        bot=context.bot,
                        chat_id=chat.id,
                        user_id=user.id,
                        text=notice,
                        context=context,
                        delete_after_seconds=warn_del_sec,
                        parse_mode=ParseMode.HTML
                    )
                except Exception:
                    await send_ephemeral_or_temporary_warning(
                        bot=context.bot,
                        chat_id=chat.id,
                        user_id=user.id,
                        text=f"⚠️ {user_mention}, sua mensagem continha um termo proibido e foi removida.",
                        context=context,
                        delete_after_seconds=warn_del_sec
                    )

                logger.info(f"Palavra proibida '{word}' detectada de {user.id} no chat {chat.id} (Punição: {action})")
                await send_mod_log(
                    bot=context.bot,
                    event_type="spam",
                    title="Termo Proibido Detectado",
                    user_info=f"{html.escape(user.first_name)} (<code>{user.id}</code>)",
                    reason=f"Palavra proibida: {word}",
                    details=f"Punição: {action}. Conteúdo: <i>{html.escape(text[:120])}</i>"
                )
                return True

        return False
