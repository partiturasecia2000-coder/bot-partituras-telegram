import logging
import re
import time
import asyncio
import copy
import math
from datetime import datetime, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode
from telegram.ext import ContextTypes
from config import (
    load_config,
    save_config,
    get_timezone,
    get_timezone_label,
    set_timezone,
    cycle_timezone,
    TIMEZONE_LIST,
    remove_linked_group,
    remove_linked_channel
)
from modules.welcome_ui import (
    generate_welcome_groups_selector,
    generate_sub_welcome,
    generate_sub_welcome_time,
    handle_welcome_callback,
    handle_welcome_input
)
from modules.whitelist import (
    generate_whitelist_hub,
    generate_whitelist_users_page,
    generate_allowed_links_page,
    handle_whitelist_callback,
    handle_whitelist_input
)
from modules.utils import AdminCache, make_disabled_button
from modules.youtube_notifier import (
    add_youtube_channel,
    remove_youtube_channel,
    send_youtube_test_card,
    fetch_youtube_channel_videos
)
from modules.backup_manager import (
    generate_sub_backup,
    send_daily_backup,
    send_weekly_report
)
from modules.recurring import (
    format_interval,
    format_interval_display,
    format_cronograma_display,
    format_weekdays_display,
    format_month_days_display,
    format_autodel_display,
    send_single_recurring_message
)
from modules.auto_responder import validate_regex
from modules.logger_channel import send_mod_log

logger = logging.getLogger("PanelModule")


PUNISHMENT_INFO = {
    "warn": ("⚠️ Só Aviso", "Apaga a mensagem e envia aviso temporário"),
    "warning": ("❗ Só Advertência", "Apaga e conta advertência (1/3, 2/3 -> Ban ao atingir 3)"),
    "ban": ("🔨 Ban Imediato", "Apaga a mensagem e bane o infrator na mesma hora")
}

PUNISHMENT_CYCLE = ["warn", "warning", "ban"]

DELAY_PRESETS = [0, 2, 5, 10, 30]



def status_icon(active: bool) -> str:
    return "🟢" if active else "🔴"


def format_time_label(seconds: int) -> str:
    if seconds <= 0:
        return "Nunca"
    elif seconds < 60:
        return f"{seconds}s"
    elif seconds < 3600:
        m = seconds // 60
        s = seconds % 60
        return f"{m} min" if s == 0 else f"{m}m {s}s"
    elif seconds < 86400:
        h = seconds // 3600
        m = (seconds % 3600) // 60
        return f"{h}h" if m == 0 else f"{h}h {m}m"
    else:
        d = seconds // 86400
        h = (seconds % 86400) // 3600
        return f"{d}d" if h == 0 else f"{d}d {h}h"


def parse_time_string_to_seconds(text: str) -> int | None:
    """Converte strings como '10m', '1 hora', '24h', '300s', '0', 'nunca' em segundos.
    Retorna 0 para nunca apagar.
    Retorna segundos inteiros se válido (limite de 5s a 86400s / 24 horas).
    Retorna None se inválido.
    """
    if not text:
        return None
    cleaned = text.strip().lower()
    if cleaned in ("0", "nunca", "off", "desativar", "nenhum", "nao", "não", "sempre", "desligar"):
        return 0

    import re
    cleaned = cleaned.replace("minutos", "m").replace("minuto", "m").replace("min", "m")
    cleaned = cleaned.replace("horas", "h").replace("hora", "h").replace("hrs", "h").replace("hr", "h")
    cleaned = cleaned.replace("segundos", "s").replace("segundo", "s").replace("seg", "s")
    cleaned = cleaned.replace("dias", "d").replace("dia", "d")

    # Se for número puro (ex: '10' -> 10 minutos)
    if cleaned.isdigit():
        val = int(cleaned)
        if val == 0:
            return 0
        sec = val * 60
        return sec if 5 <= sec <= 86400 else None

    # Número + unidade (ex: '10m', '2h', '30s')
    pattern = r"^(\d+(?:\.\d+)?)\s*([smhd])$"
    match = re.match(pattern, cleaned)
    if match:
        val = float(match.group(1))
        unit = match.group(2)
        if unit == "s":
            sec = int(val)
        elif unit == "m":
            sec = int(val * 60)
        elif unit == "h":
            sec = int(val * 3600)
        elif unit == "d":
            sec = int(val * 86400)
        else:
            return None
        return sec if 5 <= sec <= 86400 else None

    # Combinação de unidades (ex: '1h 30m')
    combo = re.findall(r"(\d+(?:\.\d+)?)\s*([smhd])", cleaned)
    if combo:
        total = 0
        for val_s, unit in combo:
            v = float(val_s)
            if unit == "s":
                total += int(v)
            elif unit == "m":
                total += int(v * 60)
            elif unit == "h":
                total += int(v * 3600)
            elif unit == "d":
                total += int(v * 86400)
        return total if 5 <= total <= 86400 else None

    return None
