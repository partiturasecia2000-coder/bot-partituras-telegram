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



def get_wizard_dest_label(target: str, cfg: dict) -> str:
    """Retorna o rótulo legível do destino escolhido no assistente de transmissão."""
    if target == "main_channel":
        mc_id = cfg.get("main_channel_id")
        linked_ch = cfg.get("linked_channels", [])
        ch_obj = next((c for c in linked_ch if c.get("id") == mc_id), None) if mc_id else (linked_ch[0] if linked_ch else None)
        title = ch_obj.get("title", "Canal Principal") if ch_obj else "Canal Principal"
        return f"📢 {title}"
    elif target == "all_channels":
        count = len(cfg.get("linked_channels", []))
        return f"📢 Todos os Canais Vinculados ({count})"
    elif target == "all_groups":
        count = len(cfg.get("linked_groups", []))
        return f"👥 Todos os Grupos Vinculados ({count})"
    elif target == "all":
        cg = len(cfg.get("linked_groups", []))
        cc = len(cfg.get("linked_channels", []))
        return f"🌐 Todos os Chats ({cg} Grupos / {cc} Canais)"
    elif str(target).startswith("grp:"):
        from config import normalize_chat_id
        gid = normalize_chat_id(target.split(":")[-1])
        if gid in (-1002071806380183, -2071806380183, 2071806380183):
            gid = -1001806380183
        g = next((x for x in cfg.get("linked_groups", []) if normalize_chat_id(x.get("id")) == gid), None)
        if not g:
            g = next((x for x in cfg.get("linked_channels", []) if normalize_chat_id(x.get("id")) == gid), None)
        if g:
            is_ch = g.get("type") == "channel" or "username" in g or gid == -1001806380183
            icon = "📢" if is_ch else "👥"
            lbl = "Canal" if is_ch else "Grupo"
            return f"{icon} {lbl}: {g.get('title', str(gid))}"
        return f"👥 Grupo {gid}"
    elif str(target).startswith("chn:"):
        from config import normalize_chat_id
        cid = normalize_chat_id(target.split(":")[-1])
        if cid in (-1002071806380183, -2071806380183, 2071806380183):
            cid = -1001806380183
        c = next((x for x in cfg.get("linked_channels", []) if normalize_chat_id(x.get("id")) == cid), None)
        if not c:
            c = next((x for x in cfg.get("linked_groups", []) if normalize_chat_id(x.get("id")) == cid), None)
        if c:
            is_ch = c.get("type") == "channel" or "username" in c or cid == -1001806380183
            icon = "📢" if is_ch else "👥"
            lbl = "Canal" if is_ch else "Grupo"
            return f"{icon} {lbl}: {c.get('title', str(cid))}"
        return f"📢 Canal {cid}"
    return str(target)


def get_wizard_targets_list(target: str, cfg: dict) -> list[int]:
    """Retorna a lista de IDs numéricos de chats destino da transmissão."""
    from config import normalize_chat_id
    targets = []
    if target == "main_channel":
        if cfg.get("main_channel_id"):
            targets.append(normalize_chat_id(cfg["main_channel_id"]))
        elif cfg.get("linked_channels"):
            targets.append(normalize_chat_id(cfg["linked_channels"][0]["id"]))
    elif target == "all_channels":
        for c in cfg.get("linked_channels", []):
            cid = normalize_chat_id(c.get("id"))
            if cid and cid not in targets:
                targets.append(cid)
    elif target == "all_groups":
        for g in cfg.get("linked_groups", []):
            gid = normalize_chat_id(g.get("id"))
            if gid and gid not in targets:
                targets.append(gid)
        if cfg.get("main_group_id"):
            mgid = normalize_chat_id(cfg["main_group_id"])
            if mgid not in targets:
                targets.append(mgid)
    elif target == "all":
        for g in cfg.get("linked_groups", []):
            gid = normalize_chat_id(g.get("id"))
            if gid and gid not in targets:
                targets.append(gid)
        if cfg.get("main_group_id"):
            mgid = normalize_chat_id(cfg["main_group_id"])
            if mgid not in targets:
                targets.append(mgid)
        for c in cfg.get("linked_channels", []):
            cid = normalize_chat_id(c.get("id"))
            if cid and cid not in targets:
                targets.append(cid)
    elif str(target).startswith("grp:"):
        t_id = normalize_chat_id(target.split(":")[-1])
        if t_id in (-1002071806380183, -2071806380183, 2071806380183):
            t_id = -1001806380183
        targets.append(t_id)
    elif str(target).startswith("chn:"):
        t_id = normalize_chat_id(target.split(":")[-1])
        if t_id in (-1002071806380183, -2071806380183, 2071806380183):
            t_id = -1001806380183
        targets.append(t_id)
    elif str(target).lstrip("-").isdigit():
        t_id = normalize_chat_id(target)
        if t_id in (-1002071806380183, -2071806380183, 2071806380183):
            t_id = -1001806380183
        targets.append(t_id)
    return targets


def generate_wizard_dest_menu(cfg, page=1):
    from modules.panel_lists import wizard_destinations
    return wizard_destinations(cfg, page)



def generate_wizard_text_prompt(dest_label: str):
    """Gera o Passo 2 do Assistente de Transmissão: Digitação do Texto."""
    text = (
        "📢 ══════════════════════ 📢\n"
        "   *GUIA DE TRANSMISSÃO — PASSO 2/4*\n"
        "📢 ══════════════════════ 📢\n\n"
        f"🎯 *Destino Selecionado:* `{dest_label}`\n\n"
        "✍️ *Digite ou cole agora o texto do seu comunicado.*\n\n"
        "💡 *Dicas de Formatação:*\n"
        "• *Negrito*, _itálico_, `código` ou ||spoiler||\n"
        "• Citação expansível (artigo): comece linhas com `>>`\n"
        "• *(Dica: Se preferir, já pode mandar uma foto ou vídeo com legenda que eu capturo tudo junto!)*\n\n"
        "Envie sua mensagem abaixo:"
    )
    keyboard = [
        [
            InlineKeyboardButton("◀ Mudar Destino", callback_data="cfg:wiz:start"),
            InlineKeyboardButton("❌ Cancelar", callback_data="cfg:wiz:cancel")
        ]
    ]
    return text, InlineKeyboardMarkup(keyboard)


def generate_wizard_media_prompt(dest_label: str, text_preview: str):
    """Gera o Passo 3 do Assistente de Transmissão: Envio de Mídia (Foto ou Vídeo)."""
    preview = text_preview[:120] + ("..." if len(text_preview) > 120 else "")
    text = (
        "📢 ══════════════════════ 📢\n"
        "   *GUIA DE TRANSMISSÃO — PASSO 3/4*\n"
        "📢 ══════════════════════ 📢\n\n"
        f"🎯 *Destino:* `{dest_label}`\n"
        f"📝 *Texto:* _{preview}_\n\n"
        "🖼️ *Deseja adicionar uma FOTO ou VÍDEO?*\n\n"
        "• **Envie uma Foto ou Vídeo** agora neste chat, OU\n"
        "• Clique no botão abaixo para **Pular Mídia** (enviar somente texto):"
    )
    keyboard = [
        [
            InlineKeyboardButton("⏭️ Pular Mídia (Somente Texto)", callback_data="cfg:wiz:skip_media")
        ],
        [
            InlineKeyboardButton("✏️ Alterar Texto", callback_data="cfg:wiz:edit_text"),
            InlineKeyboardButton("❌ Cancelar", callback_data="cfg:wiz:cancel")
        ]
    ]
    return text, InlineKeyboardMarkup(keyboard)


def generate_wizard_buttons_prompt(dest_label: str, media_label: str):
    """Gera o Passo 4 do Assistente de Transmissão: Adição de Botões."""
    text = (
        "📢 ══════════════════════ 📢\n"
        "   *GUIA DE TRANSMISSÃO — PASSO 4/4*\n"
        "📢 ══════════════════════ 📢\n\n"
        f"🎯 *Destino:* `{dest_label}`\n"
        f"🖼️ *Mídia:* `{media_label}`\n\n"
        "🔘 *Deseja adicionar Botões Interativos com Link?*\n\n"
        "Envie os botões no formato:\n"
        "`[Nome do Botão | https://link.com]`\n\n"
        "• **Lado a lado:** `[Botão 1 | link1] [Botão 2 | link2]`\n"
        "• **Em linhas separadas:** pule uma linha entre eles\n\n"
        "Ou clique em **Pular Botões** se não precisar:"
    )
    keyboard = [
        [
            InlineKeyboardButton("⏭️ Pular Botões", callback_data="cfg:wiz:skip_buttons")
        ],
        [
            InlineKeyboardButton("🖼️/🎥 Alterar Mídia", callback_data="cfg:wiz:edit_media"),
            InlineKeyboardButton("❌ Cancelar", callback_data="cfg:wiz:cancel")
        ]
    ]
    return text, InlineKeyboardMarkup(keyboard)


def get_delay_label(delay_sec: int) -> str:
    if delay_sec == 0:
        return "⚡ Instantâneo (0s)"
    elif delay_sec == 2:
        return "🌊 Suave (2s/chat)"
    elif delay_sec == 5:
        return "⏳ Moderado (5s/chat)"
    elif delay_sec == 10:
        return "🐢 Espaçado (10s/chat)"
    elif delay_sec == 30:
        return "🕒 Gradual (30s/chat)"
    return f"⏱️ {delay_sec}s/chat"


def generate_wizard_preview_controls(dest_label: str, media_label: str, buttons_count: int, pin: bool, delay_seconds: int = 2):
    """Gera os controles de confirmação da Prévia da Transmissão."""
    delay_lbl = get_delay_label(delay_seconds)
    text = (
        "📋 ══════════════════════ 📋\n"
        "   *PRÉVIA DA TRANSMISSÃO ACIMA* 👆\n"
        "📋 ══════════════════════ 📋\n\n"
        f"🎯 *Destino:* `{dest_label}`\n"
        f"🌊 *Distribuição:* `{delay_lbl}`\n"
        f"📌 *Fixar no Topo (PIN):* `{'🟢 Sim' if pin else '🔴 Não'}`\n"
        f"🖼️ *Mídia:* `{media_label}`\n"
        f"🔘 *Botões com Link:* `{buttons_count} botão(ões)`\n\n"
        "Confira a mensagem de prévia gerada logo acima.\n"
        "Selecione **🚀 ENVIAR AGORA** para disparo imediato ou **⏰ AGENDAR** para programar o envio:"
    )
    keyboard = [
        [
            InlineKeyboardButton("🚀 ENVIAR AGORA", callback_data="cfg:wiz:send"),
            InlineKeyboardButton("⏰ AGENDAR ENVIO", callback_data="cfg:wiz:sched_menu")
        ],
        [
            InlineKeyboardButton(f"🌊 Distribuição: {delay_lbl}", callback_data="cfg:wiz:toggle_delay"),
            InlineKeyboardButton(f"📌 Fixar: {'🟢 Sim' if pin else '🔴 Não'}", callback_data="cfg:wiz:toggle_pin")
        ],
        [
            InlineKeyboardButton("🎯 Mudar Destino", callback_data="cfg:wiz:start"),
            InlineKeyboardButton("✏️ Alterar Texto", callback_data="cfg:wiz:edit_text")
        ],
        [
            InlineKeyboardButton("🖼️/🎥 Alterar Mídia", callback_data="cfg:wiz:edit_media"),
            InlineKeyboardButton("🔘 Alterar Botões", callback_data="cfg:wiz:edit_buttons")
        ],
        [
            InlineKeyboardButton("❌ Cancelar Transmissão", callback_data="cfg:wiz:cancel")
        ]
    ]
    return text, InlineKeyboardMarkup(keyboard)


def generate_wizard_schedule_menu(cfg: dict, state: dict):
    """Gera o menu de agendamento de horário para a transmissão."""
    from config import get_timezone, get_timezone_label
    tz = get_timezone(cfg)
    tz_lbl = get_timezone_label(cfg)
    now_dt = datetime.now(tz)
    cur_time_str = now_dt.strftime("%H:%M")

    text = (
        "⏰ ══════════════════════ ⏰\n"
        "   *PROGRAMAR HORÁRIO DE ENVIO*\n"
        "⏰ ══════════════════════ ⏰\n\n"
        f"🕒 *Horário Atual do Bot:* `{cur_time_str}` ({tz_lbl})\n"
        "Escolha quando o Maestro Bot deve disparar esta transmissão:"
    )
    keyboard = [
        [
            InlineKeyboardButton("⏱️ Em 15 minutos", callback_data="cfg:wiz:set_rel:15"),
            InlineKeyboardButton("⏱️ Em 30 minutos", callback_data="cfg:wiz:set_rel:30")
        ],
        [
            InlineKeyboardButton("⏱️ Em 1 hora", callback_data="cfg:wiz:set_rel:60"),
            InlineKeyboardButton("⏱️ Em 2 horas", callback_data="cfg:wiz:set_rel:120")
        ],
        [
            InlineKeyboardButton("🌅 Hoje às 18:00", callback_data="cfg:wiz:set_time:18:00"),
            InlineKeyboardButton("🌙 Hoje às 21:00", callback_data="cfg:wiz:set_time:21:00")
        ],
        [
            InlineKeyboardButton("☀️ Amanhã às 09:00", callback_data="cfg:wiz:set_time:tomorrow_09:00"),
            InlineKeyboardButton("🎯 Digitar Data / Hora", callback_data="cfg:wiz:set_custom")
        ],
        [
            InlineKeyboardButton("◀ Voltar à Prévia", callback_data="cfg:wiz:back_preview")
        ]
    ]
    return text, InlineKeyboardMarkup(keyboard)


def generate_scheduled_transmissions_menu(cfg, page=1):
    from modules.panel_lists import transmissions_page
    return transmissions_page(cfg, page)

