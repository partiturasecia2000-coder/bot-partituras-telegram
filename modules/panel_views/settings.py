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

from .common import format_time_label, status_icon

def generate_page_1(chat_title: str, cfg: dict):
    from modules.menu_screens import main_menu
    return main_menu(chat_title,cfg)



def generate_page_2(chat_title: str, cfg: dict):
    """Redirecionamento transparente de links legados para a central de sistema."""
    return generate_hub_system(cfg)


def generate_hub_clean(cfg: dict):
    from modules.menu_screens import clean_menu
    return clean_menu(cfg)



def generate_hub_security(cfg: dict):
    from modules.menu_screens import security_menu
    return security_menu(cfg)



def generate_hub_welcome(cfg: dict):
    from modules.menu_screens import welcome_menu
    return welcome_menu(cfg)



def generate_hub_messages(cfg: dict):
    from modules.menu_screens import messages_menu
    return messages_menu(cfg)



def generate_hub_system(cfg: dict):
    from modules.menu_screens import system_menu
    return system_menu(cfg)



def generate_sub_clean_help():
    from modules.menu_screens import clean_help
    return clean_help()



def generate_chats_list_page(cfg, page=1):
    from modules.panel_lists import chats_page
    return chats_page(cfg, page)



def generate_sub_chat_info(cfg: dict, chat_type: str, target_id: int | str):
    target_id_int = int(target_id) if (str(target_id).startswith("-") or str(target_id).isdigit()) else target_id
    main_grp = cfg.get("main_group_id")
    main_ch = cfg.get("main_channel_id")

    if chat_type == "grp":
        item = next((g for g in cfg.get("linked_groups", []) if g.get("id") == target_id_int), None)
        title = item.get("title", f"Grupo {target_id}") if item else f"Grupo {target_id}"
        linked_at = item.get("linked_at", "Não informada") if item else "Não informada"
        is_main = (target_id_int == main_grp)
        gw = cfg.get("group_welcomes", {})
        has_custom_welcome = str(target_id) in gw
        nm = cfg.get("night_mode", {})
        nm_chats = nm.get("enabled_chats", [])
        is_nm = target_id_int in nm_chats or (is_main and target_id_int == main_grp and nm.get("enabled", False))

        text = (
            "🎼 ═══════════════════ 🎼\n"
            "   *GERENCIAR GRUPO VINCULADO*\n"
            "🎼 ═══════════════════ 🎼\n\n"
            f"👥 *Nome:* `{title}`\n"
            f"🆔 *ID:* `{target_id_int}`\n"
            f"⭐️ *Papel:* {'⭐️ Grupo Principal' if is_main else '👥 Grupo Secundário Vinculado'}\n"
            f"📅 *Vinculado em:* `{linked_at}`\n"
            f"💬 *Boas-Vindas:* {'✨ Personalizada deste grupo' if has_custom_welcome else '⚪ Usando Padrão Geral'}\n"
            f"🌙 *Modo Noturno:* {'🟢 Ativo neste grupo' if is_nm else '⚪ Não monitorado'}\n\n"
            "Escolha uma ação para este grupo abaixo:"
        )

        kb = []
        if not is_main:
            kb.append([InlineKeyboardButton("⭐️ Definir como Grupo Principal", callback_data=f"cfg:chat:set_main:grp:{target_id_int}")])
        else:
            kb.append([make_disabled_button("⭐️ Grupo Principal Ativo")])

        kb.append([
            InlineKeyboardButton("💬 Configurar Boas-Vindas", callback_data=f"cfg:welcome:cfg:{target_id}"),
            InlineKeyboardButton("⏱️ Auto-Apagar Msg", callback_data=f"cfg:sub:wtime:{target_id}")
        ])
        kb.append([
            InlineKeyboardButton("🗑️ Desvincular Grupo", callback_data=f"cfg:chat:unlink:grp:{target_id_int}")
        ])
        kb.append([
            InlineKeyboardButton("◀ Voltar à Lista de Chats", callback_data="cfg:chats:list")
        ])
        return text, InlineKeyboardMarkup(kb)

    else:
        item = next((c for c in cfg.get("linked_channels", []) if c.get("id") == target_id_int), None)
        title = item.get("title", f"Canal {target_id}") if item else f"Canal {target_id}"
        uname = item.get("username", "") if item else ""
        linked_at = item.get("linked_at", "Não informada") if item else "Não informada"
        is_main = (target_id_int == main_ch)
        uname_str = f"@{uname}" if uname else "Privado (sem @username)"

        text = (
            "🎼 ═══════════════════ 🎼\n"
            "   *GERENCIAR CANAL VINCULADO*\n"
            "🎼 ═══════════════════ 🎼\n\n"
            f"📢 *Nome:* `{title}`\n"
            f"🆔 *ID:* `{target_id_int}`\n"
            f"🔗 *Username:* `{uname_str}`\n"
            f"⭐️ *Papel:* {'⭐️ Canal Principal' if is_main else '📢 Canal Secundário Vinculado'}\n"
            f"📅 *Vinculado em:* `{linked_at}`\n\n"
            "O Maestro Bot pode postar comunicados, fotos e mensagens programadas neste canal com formatação total!\n\n"
            "Escolha uma ação para este canal abaixo:"
        )

        kb = []
        if not is_main:
            kb.append([InlineKeyboardButton("⭐️ Definir como Canal Principal", callback_data=f"cfg:chat:set_main:chn:{target_id_int}")])
        else:
            kb.append([make_disabled_button("⭐️ Canal Principal Ativo")])

        kb.append([
            InlineKeyboardButton("📢 Como Postar no Canal", callback_data=f"cfg:chat:post_prompt:{target_id_int}")
        ])
        kb.append([
            InlineKeyboardButton("🗑️ Desvincular Canal", callback_data=f"cfg:chat:unlink:chn:{target_id_int}")
        ])
        kb.append([
            InlineKeyboardButton("◀ Voltar à Lista de Chats", callback_data="cfg:chats:list")
        ])
        return text, InlineKeyboardMarkup(kb)


def generate_sub_timezone(cfg: dict):
    from modules.menu_screens import timezone_menu
    return timezone_menu(cfg)



def generate_sub_docs():
    from modules.menu_screens import about_menu
    return about_menu()



def generate_sub_nightmode(cfg: dict):
    from modules.menu_screens import night_menu
    return night_menu(cfg)



def generate_sub_logs(cfg: dict):
    from modules.menu_screens import logs_menu
    return logs_menu(cfg)



def generate_sub_cmd_clean(cfg: dict):
    from modules.menu_screens import command_clean_menu
    return command_clean_menu(cfg)



def generate_auto_responder_list(chat_title, cfg, page=1):
    from modules.panel_lists import responders_page
    return responders_page(chat_title, cfg, page)



def generate_auto_responder_detail(cfg: dict, item_id: int):
    responders = cfg.get("auto_responses", [])
    item = next((r for r in responders if r.get("id") == item_id), None)
    if not item:
        return "⚠️ Resposta automática não encontrada.", InlineKeyboardMarkup([
            [InlineKeyboardButton("◀ Voltar à Lista", callback_data="cfg:resp:list")]
        ])

    on = item.get("enabled", True)
    title = item.get("title", f"Resposta #{item_id}")
    pattern = item.get("pattern", "")
    is_regex = item.get("is_regex", True)
    cooldown = item.get("cooldown_seconds", 30)
    delay = item.get("delay_seconds", 0)
    delay_str = f"{delay}s" if delay > 0 else "Imediato (0s)"
    reply_to = item.get("reply_to", True)
    del_trigger = item.get("delete_trigger", False)
    has_photo = bool(item.get("photo"))
    buttons_count = len(item.get("buttons", []))
    text_preview = item.get("text", "")
    if len(text_preview) > 140:
        text_preview = text_preview[:140] + "..."

    text = (
        f"🤖 *DETALHES DA RESPOSTA #{item_id}*\n\n"
        f"• *Título:* `{title}`\n"
        f"• *Status:* {'🟢 Ativado' if on else '🔴 Desativado'}\n"
        f"• *Modo:* {'🎯 Expressão Regular (Regex)' if is_regex else '🔤 Palavra-chave simples'}\n"
        f"• *Gatilho:* `{pattern}`\n"
        f"• *Cooldown (anti-spam):* `{cooldown}s`\n"
        f"• *Tempo de Espera (Delay):* `{delay_str}`\n"
        f"• *Responder citando:* {'🟢 Sim' if reply_to else '🔴 Não'}\n"
        f"• *Apagar gatilho do usuário:* {'🟢 Sim' if del_trigger else '🔴 Não'}\n"
        f"• *Foto / Imagem:* {'🟢 Configurada' if has_photo else '⚪ Nenhuma'}\n"
        f"• *Botões com Link:* `{buttons_count} botão(ões)`\n\n"
        f"📌 *Texto da resposta:*\n_{text_preview}_\n"
    )

    keyboard = [
        [
            InlineKeyboardButton("📝 Alterar Texto", callback_data=f"cfg:resp:edit_text:{item_id}"),
            InlineKeyboardButton("🎯 Alterar Gatilho", callback_data=f"cfg:resp:edit_pattern:{item_id}")
        ],
        [
            InlineKeyboardButton("🏷️ Alterar Título", callback_data=f"cfg:resp:edit_title:{item_id}"),
            InlineKeyboardButton("🖼️ Alterar Foto", callback_data=f"cfg:resp:edit_photo:{item_id}")
        ],
        [
            InlineKeyboardButton("🔘 Configurar Botões", callback_data=f"cfg:resp:edit_buttons:{item_id}"),
            InlineKeyboardButton(f"⏳ Espera ({delay_str})", callback_data=f"cfg:resp:cycle_delay:{item_id}")
        ],
        [
            InlineKeyboardButton(f"⏱️ Cooldown ({cooldown}s)", callback_data=f"cfg:resp:cycle_cd:{item_id}"),
            InlineKeyboardButton("Modo: Regex 🎯" if is_regex else "Modo: Simples 🔤", callback_data=f"cfg:resp:toggle_regex:{item_id}")
        ],
        [
            InlineKeyboardButton(f"Citar: {'🟢 Sim' if reply_to else '🔴 Não'}", callback_data=f"cfg:resp:toggle_reply:{item_id}"),
            InlineKeyboardButton(f"🗑️ Apagar Msg: {'🟢 Sim' if del_trigger else '🔴 Não'}", callback_data=f"cfg:resp:toggle_del_trig:{item_id}")
        ],
        [
            InlineKeyboardButton("🧪 Testar Resposta", callback_data=f"cfg:resp:test:{item_id}")
        ]
    ]

    cleanup_row = []
    if has_photo:
        cleanup_row.append(InlineKeyboardButton("🗑️ Remover Foto", callback_data=f"cfg:resp:del_photo:{item_id}"))
    if buttons_count > 0:
        cleanup_row.append(InlineKeyboardButton("🗑️ Remover Botões", callback_data=f"cfg:resp:del_buttons:{item_id}"))
    if cleanup_row:
        keyboard.append(cleanup_row)

    keyboard.append([
        InlineKeyboardButton("🔴 Desativar" if on else "🟢 Ativar", callback_data=f"cfg:resp:toggle:{item_id}"),
        InlineKeyboardButton("❌ Excluir", callback_data=f"cfg:resp:del:{item_id}")
    ])
    keyboard.append([
        InlineKeyboardButton("◀ Voltar à Lista", callback_data="cfg:resp:list")
    ])

    return text, InlineKeyboardMarkup(keyboard)


def generate_sub_banned(cfg: dict):
    s = cfg.get("antispam", {})
    banned = s.get("banned_words", [])
    action = s.get("banned_words_action", "warn")
    action_title, action_desc = PUNISHMENT_INFO.get(action, PUNISHMENT_INFO["warn"])

    total = len(banned)
    if total > 0:
        preview = ", ".join(f"`{w}`" for w in banned[:8])
        if total > 8:
            preview += f" ... e mais {total - 8} termos."
    else:
        preview = "_Nenhuma palavra cadastrada ainda._"

    text = (
        "🔤 *CONFIGURAÇÃO: PALAVRAS PROIBIDAS*\n\n"
        f"• *Total de termos cadastrados:* `{total}`\n"
        f"• *Punição ativa:* *{action_title}*\n"
        f"  └ _{action_desc}_\n\n"
        f"📋 *Amostra:* {preview}\n"
    )

    keyboard = [
        [
            InlineKeyboardButton("➕ Adicionar Palavras", callback_data="cfg:banned:add"),
            InlineKeyboardButton("🗑️ Remover Palavras", callback_data="cfg:banned:remove")
        ],
        [
            InlineKeyboardButton(f"⚖️ Punição: {action_title}", callback_data="cfg:banned:cycle_action")
        ],
        [
            InlineKeyboardButton("📜 Ver Lista Completa", callback_data="cfg:banned:view_all"),
            InlineKeyboardButton("🗑️ Limpar Todas", callback_data="cfg:banned:clear_all")
        ],
        [
            InlineKeyboardButton("◀ Voltar ao Menu", callback_data="cfg:page:1")
        ]
    ]
    return text, InlineKeyboardMarkup(keyboard)


def generate_sub_antispam(cfg: dict):
    from modules.menu_screens import spam_menu
    return spam_menu(cfg)



def generate_sub_antiflood(cfg: dict):
    from modules.menu_screens import flood_menu
    return flood_menu(cfg)



def generate_sub_rules(cfg: dict):
    rules = cfg.get("rules", "Sem regras definidas.")
    text = f"📜 *REGRAS ATUAIS DO GRUPO:*\n\n{rules}"
    keyboard = [
        [InlineKeyboardButton("◀ Voltar ao Menu", callback_data="cfg:page:1")]
    ]
    return text, InlineKeyboardMarkup(keyboard)


def generate_sub_youtube(cfg: dict):
    yt_cfg = cfg.get("youtube_notifications", {})
    enabled = yt_cfg.get("enabled", True)
    target_chat = yt_cfg.get("target_chat") or cfg.get("main_group_id") or "@partiturasecia"
    channels = yt_cfg.get("channels", [])
    interval = yt_cfg.get("check_interval_minutes", 5)

    status_str = "🟢 Ativado" if enabled else "🔴 Desativado"
    toggle_btn_text = "🎬 Notificador: 🟢 Ativado" if enabled else "🎬 Notificador: 🔴 Desativado"

    lines = [
        "🎬 *NOTIFICADOR DO YOUTUBE*\n",
        "Monitore canais do YouTube e receba novos vídeos automaticamente no grupo!\n",
        f"• ⚙️ *Status Geral:* {status_str}",
        f"• 🎯 *Destino das Postagens:* `{target_chat}`",
        f"• ⏱️ *Intervalo de Varredura:* `A cada {interval} min`",
        f"• 📺 *Canais Monitorados:* `{len(channels)}`\n"
    ]

    if channels:
        lines.append("📋 *Canais Ativos no Monitoramento:*")
        for i, ch in enumerate(channels[:5], 1):
            name = ch.get("name", "Canal")
            handle_or_url = ch.get("input") or ch.get("url") or ""
            lines.append(f"{i}. *{name}* (`{handle_or_url}`)")
        lines.append("\n💡 Novos vídeos postados nestes canais serão anunciados automaticamente no grupo!")
    else:
        lines.append("⚠️ _Nenhum canal do YouTube cadastrado no momento._\nToque no botão abaixo para adicionar o primeiro canal!")

    text = "\n".join(lines)

    kb = [
        [InlineKeyboardButton(toggle_btn_text, callback_data="cfg:toggle:youtube")],
        [
            InlineKeyboardButton("➕ Adicionar Canal", callback_data="cfg:youtube:add"),
            InlineKeyboardButton(f"🗑️ Remover Canal ({len(channels)})", callback_data="cfg:youtube:del")
        ],
        [
            InlineKeyboardButton("🎯 Alterar Grupo Destino", callback_data="cfg:youtube:target"),
            InlineKeyboardButton("🚀 Testar Envio Imediato", callback_data="cfg:youtube:test")
        ],
        [InlineKeyboardButton("◀ Voltar a Mensagens", callback_data="cfg:hub:messages")]
    ]
    return text, InlineKeyboardMarkup(kb)


def generate_sub_youtube_delete(cfg, page=1):
    from modules.panel_lists import youtube_channels
    return youtube_channels(cfg, page)

