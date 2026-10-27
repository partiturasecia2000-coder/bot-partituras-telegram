import html
import logging
from datetime import datetime
from telegram import Bot
from telegram.constants import ParseMode
from config import load_config, get_timezone

logger = logging.getLogger("LogChannel")

async def send_mod_log(
    bot: Bot,
    event_type: str,
    title: str,
    user_info: str,
    admin_info: str = None,
    reason: str = None,
    details: str = None,
    extra_lines: list = None
) -> bool:
    """
    Envia um registro de auditoria / moderação para o canal de logs configurado.
    
    event_type: 'ban', 'kick', 'mute', 'warn', 'spam', 'join', 'say', 'config'
    """
    cfg = load_config()
    log_channel_id = cfg.get("log_channel_id")
    if not log_channel_id:
        return False

    # Verifica se esse tipo de evento está ativado nos logs
    log_events = cfg.get("log_events", {})
    event_map = {
        "ban": "bans",
        "kick": "bans",
        "mute": "mutes",
        "warn": "warns",
        "spam": "spam",
        "join": "joins",
        "leave": "leaves"
    }
    config_key = event_map.get(event_type)
    if config_key and not log_events.get(config_key, True):
        return False

    now_tz = datetime.now(get_timezone(cfg))
    timestamp_str = now_tz.strftime("%d/%m/%Y às %H:%M:%S")

    # Emojis temáticos por tipo de evento
    icon_map = {
        "ban": "🔨",
        "kick": "👢",
        "mute": "🔇",
        "unmute": "🔊",
        "warn": "❗",
        "unwarn": "✅",
        "spam": "🛡️",
        "join": "🟢",
        "leave": "🔴",
        "say": "📢",
        "config": "⚙️"
    }
    icon = icon_map.get(event_type, "📋")
    header_label = "REGISTRO DE MEMBROS" if event_type in ("join", "leave") else "REGISTRO DE MODERAÇÃO"

    log_lines = [
        f"{icon} <b>[{header_label}]</b>",
        f"📅 <i>{timestamp_str}</i>\n",
        f"<b>Ação:</b> {html.escape(title)}"
    ]

    if user_info:
        log_lines.append(f"<b>Usuário:</b> {user_info}")

    if admin_info:
        log_lines.append(f"<b>Administrador:</b> {admin_info}")

    if reason:
        log_lines.append(f"<b>Motivo:</b> <i>{html.escape(reason)}</i>")

    if details:
        log_lines.append(f"<b>Detalhes:</b>\n{details}")

    if extra_lines:
        for line in extra_lines:
            log_lines.append(line)

    full_message = "\n".join(log_lines)

    try:
        await bot.send_message(
            chat_id=log_channel_id,
            text=full_message,
            parse_mode=ParseMode.HTML
        )
        logger.info(f"Log de moderação '{title}' enviado com sucesso para o canal {log_channel_id}")
        return True
    except Exception as e:
        logger.warning(f"Não foi possível enviar log para o canal {log_channel_id}: {e}")
        return False
