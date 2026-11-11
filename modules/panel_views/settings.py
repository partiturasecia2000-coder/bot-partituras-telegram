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
    acervo_on = cfg.get("acervo_group_auto_reply", False)

    lines = [
        "🎼 *MAESTRO BOT — PAINEL PRINCIPAL*\n",
        f"🏛️ *Chat Ativo:* `{chat_title}`",
        "✨ *Status Geral:* Sistema harmônico e operacional\n",
        "Toque em uma central temática abaixo para orquestrar as configurações:"
    ]
    text = "\n".join(lines)

    keyboard = [
        [
            InlineKeyboardButton("🧹 Central de Limpeza ▾", callback_data="cfg:hub:clean"),
            InlineKeyboardButton("🛡️ Segurança & Moderação ▾", callback_data="cfg:hub:security")
        ],
        [
            InlineKeyboardButton("👋 Boas-Vindas & Entrada ▾", callback_data="cfg:hub:welcome"),
            InlineKeyboardButton(f"🎼 Acervo Musical {status_icon(acervo_on)} ▾", callback_data="cfg:sub:acervo")
        ],
        [
            InlineKeyboardButton("📢 Mensagens & Transmissões ▾", callback_data="cfg:hub:messages"),
            InlineKeyboardButton("⚙️ Sistema & Comunidade ▾", callback_data="cfg:hub:system")
        ],
        [
            InlineKeyboardButton("✅ Concluir Orquestração", callback_data="cfg:close")
        ]
    ]

    return text, InlineKeyboardMarkup(keyboard)


def generate_page_2(chat_title: str, cfg: dict):
    """Redirecionamento transparente de links legados para a central de sistema."""
    return generate_hub_system(cfg)


def generate_hub_clean(cfg: dict):
    del_serv = cfg.get("welcome", {}).get("delete_service_messages", True)
    pin_serv = cfg.get("delete_pinned_service_messages", True)
    cc = cfg.get("command_cleanup", {})
    clean_admin = cc.get("delete_admin_commands", True)
    clean_user = cc.get("delete_non_admin_commands", True)
    clean_all = clean_admin and clean_user

    lines = [
        "🧹 *CENTRAL DE LIMPEZA E FAXINA*\n",
        "Mantenha seus grupos 100% limpos e livres de poluição visual:\n",
        f"• 🚪 *Limpar Entradas/Saídas:* {status_icon(del_serv)}",
        f"• 📌 *Limpar Avisos de Fixados:* {status_icon(pin_serv)}",
        f"• 🧹 *Limpar Comandos (/):* {status_icon(clean_all)}",
        "• 🗑️ *Faxina Rápida de Mensagens do Chat*\n",
        "Toque nos botões abaixo para alternar ou configurar:"
    ]
    text = "\n".join(lines)

    kb = [
        [
            InlineKeyboardButton(f"🚪 Limpar Entradas {status_icon(del_serv)}", callback_data="cfg:toggle:service_msg"),
            InlineKeyboardButton(f"📌 Limpar Fixados {status_icon(pin_serv)}", callback_data="cfg:toggle:pin_service_msg")
        ],
        [
            InlineKeyboardButton("🧹 Limpeza de Comandos (/comando) ▾", callback_data="cfg:sub:cmd_clean")
        ],
        [
            InlineKeyboardButton("🗑️ Faxina Rápida de Chat (/limpar) ▾", callback_data="cfg:sub:clean_help")
        ],
        [
            InlineKeyboardButton("◀ Voltar ao Painel", callback_data="cfg:page:1")
        ]
    ]
    return text, InlineKeyboardMarkup(kb)


def generate_hub_security(cfg: dict):
    s = cfg.get("antispam", {})
    enabled = s.get("enabled", True)
    links = s.get("block_links", True)
    invites = s.get("block_telegram_invites", True)
    forwards = s.get("block_forwards", True)
    banned_list = s.get("banned_words", [])
    action = s.get("banned_words_action", "warn")
    action_label = "Ban Imediato" if action == "ban" else ("3 Advertências" if action == "warning" else "Aviso")

    flood_on = cfg.get("antiflood", {}).get("enabled", True)
    rep_filter_on = cfg.get("antirepeat", {}).get("enabled", True)
    cap_on = cfg.get("captcha", {}).get("enabled", False)

    lines = [
        "🛡️ *SEGURANÇA & MODERAÇÃO*\n",
        "Proteção contra invasores, spammers, links e mensagens proibidas:\n",
        f"• 🛡️ *Anti-Spam Geral:* {status_icon(enabled)}",
        f"• 🔗 *Bloquear Links Web:* {status_icon(links)}",
        f"• 📢 *Travar Convites Telegram (t.me):* {status_icon(invites)}",
        f"• ⏩ *Travar Encaminhados de Canais:* {status_icon(forwards)}",
        f"• 🔤 *Palavras Proibidas:* `{len(banned_list)}` termos ({action_label})",
        f"• 🌊 *Anti-Flood:* {status_icon(flood_on)}",
        f"• 🔁 *Anti-Repetição:* {status_icon(rep_filter_on)}",
        f"• 🧩 *CAPTCHA de Entrada:* {status_icon(cap_on)}\n"
    ]
    text = "\n".join(lines)

    kb = [
        [
            InlineKeyboardButton(f"🛡️ Anti-Spam {status_icon(enabled)}", callback_data="cfg:toggle:antispam"),
            InlineKeyboardButton(f"🔗 Bloquear Links {status_icon(links)}", callback_data="cfg:toggle:links")
        ],
        [
            InlineKeyboardButton(f"📢 Travar Convites {status_icon(invites)}", callback_data="cfg:toggle:invites"),
            InlineKeyboardButton(f"⏩ Encaminhados {status_icon(forwards)}", callback_data="cfg:toggle:forwards")
        ],
        [
            InlineKeyboardButton(f"🔤 Palavras Proibidas ({len(banned_list)}) ▾", callback_data="cfg:sub:banned"),
            InlineKeyboardButton(f"🌊 Anti-Flood {status_icon(flood_on)} ▾", callback_data="cfg:sub:antiflood")
        ],
        [
            InlineKeyboardButton(f"🔁 Anti-Repetição {status_icon(rep_filter_on)}", callback_data="cfg:toggle:user_repeat"),
            InlineKeyboardButton(f"🧩 CAPTCHA {status_icon(cap_on)}", callback_data="cfg:toggle:captcha")
        ],
        [
            InlineKeyboardButton("🛡️ Whitelist & Links Autorizados ▾", callback_data="cfg:sub:whitelist_hub")
        ],
        [
            InlineKeyboardButton("◀ Voltar ao Painel", callback_data="cfg:page:1")
        ]
    ]
    return text, InlineKeyboardMarkup(kb)


def generate_hub_welcome(cfg: dict):
    w_on = cfg.get("welcome", {}).get("enabled", True)
    del_w_sec = cfg.get("welcome", {}).get("delete_welcome_after_seconds", 600)
    jr_on = cfg.get("join_requests", {}).get("auto_approve", False)
    cap_on = cfg.get("captcha", {}).get("enabled", False)

    lines = [
        "👋 *BOAS-VINDAS & ENTRADA DE MEMBROS*\n",
        "Recepcione novos membros com mensagens personalizadas e aprove inscrições:\n",
        f"• 👋 *Mensagem de Boas-Vindas:* {status_icon(w_on)}",
        f"• ⏱️ *Auto-Apagar Boas-Vindas:* `{format_time_label(del_w_sec)}`",
        f"• 📥 *Auto-Aprovar Solicitações:* {status_icon(jr_on)}",
        f"• 🧩 *CAPTCHA Anti-Bot:* {status_icon(cap_on)}\n"
    ]
    text = "\n".join(lines)

    kb = [
        [
            InlineKeyboardButton(f"💬 Boas-Vindas {status_icon(w_on)}", callback_data="cfg:toggle:welcome"),
            InlineKeyboardButton("✏️ Personalizar Mensagem ▾", callback_data="cfg:sub:welcome")
        ],
        [
            InlineKeyboardButton(f"⏱️ Auto-Apagar ({format_time_label(del_w_sec)}) ▾", callback_data="cfg:sub:wtime:general")
        ],
        [
            InlineKeyboardButton(f"📥 Auto-Aprovar Entradas {status_icon(jr_on)}", callback_data="cfg:toggle:join_req"),
            InlineKeyboardButton(f"🧩 CAPTCHA {status_icon(cap_on)}", callback_data="cfg:toggle:captcha")
        ],
        [
            InlineKeyboardButton("◀ Voltar ao Painel", callback_data="cfg:page:1")
        ]
    ]
    return text, InlineKeyboardMarkup(kb)


def generate_hub_messages(cfg: dict):
    sched_count = len([x for x in cfg.get("scheduled_transmissions", []) if x.get("status") == "pending"])
    rec_count = len(cfg.get("recurring_messages", []))
    resp_count = len(cfg.get("auto_responses", []))
    yt_cfg = cfg.get("youtube_notifications", {})
    yt_enabled = yt_cfg.get("enabled", True)
    yt_channels = yt_cfg.get("channels", [])
    yt_count = len(yt_channels)
    yt_status = "🟢" if yt_enabled and yt_count > 0 else ("🟡" if yt_enabled else "🔴")

    lines = [
        "📢 *MENSAGENS & COMUNICAÇÃO*\n",
        "Envie comunicados, agende transmissões e configure respostas automáticas:\n",
        f"• 📢 *Transmissões Agendadas:* `{sched_count}` pendente(s)",
        f"• ⏱️ *Mensagens Recorrentes:* `{rec_count}` ativa(s)",
        f"• 🤖 *Auto-Respostas (Regex):* `{resp_count}` cadastrada(s)",
        f"• 🎬 *Notificador YouTube:* {yt_status} `{yt_count}` canal(is) cadastrado(s)",
        "• 📜 *Regras Oficiais do Grupo*\n"
    ]
    text = "\n".join(lines)

    kb = [
        [
            InlineKeyboardButton("📢 Nova Transmissão ▾", callback_data="cfg:wiz:start"),
            InlineKeyboardButton(f"🗓️ Agendados ({sched_count})", callback_data="cfg:sched:list")
        ],
        [
            InlineKeyboardButton(f"⏱️ Repetidas / Cronograma ({rec_count})", callback_data="cfg:rec:list"),
            InlineKeyboardButton(f"🤖 Auto-Respostas ({resp_count})", callback_data="cfg:resp:list")
        ],
        [
            InlineKeyboardButton("📜 Regras do Grupo ▾", callback_data="cfg:sub:rules"),
            InlineKeyboardButton(f"🎬 YouTube ({yt_count}) ▾", callback_data="cfg:sub:youtube")
        ],
        [
            InlineKeyboardButton("◀ Voltar ao Painel", callback_data="cfg:page:1")
        ]
    ]
    return text, InlineKeyboardMarkup(kb)


def generate_hub_system(cfg: dict):
    groups = cfg.get("linked_groups", [])
    channels = cfg.get("linked_channels", [])
    has_logs = bool(cfg.get("log_channel_id"))
    nm = cfg.get("night_mode", {})
    nm_on = nm.get("enabled", False)
    tz_label = get_timezone_label(cfg)
    b_cfg = cfg.get("backup_system", {})
    bkp_on = b_cfg.get("enabled", True) and (b_cfg.get("daily_backup_enabled", True) or b_cfg.get("weekly_report_enabled", True))
    bkp_dest = b_cfg.get("channel_id", -1004462851433)

    lines = [
        "⚙️ *SISTEMA & COMUNIDADE*\n",
        "Gerencie as salas integradas, auditoria, backups e preferências gerais:\n",
        f"• 👥 *Grupos Vinculados:* `{len(groups)}` | 📢 *Canais:* `{len(channels)}`",
        f"• 💾 *Backups & Relatórios:* {status_icon(bkp_on)} (Canal `{bkp_dest}`)",
        f"• 🌙 *Modo Noturno (Silêncio):* {status_icon(nm_on)}",
        f"• 📡 *Canal de Logs de Auditoria:* {status_icon(has_logs)}",
        f"• 🕒 *Fuso Horário:* `{tz_label}`\n"
    ]
    text = "\n".join(lines)

    kb = [
        [
            InlineKeyboardButton(f"🌐 Chats ({len(groups)}G/{len(channels)}C) ▾", callback_data="cfg:chats:list"),
            InlineKeyboardButton("🛡️ Whitelist & Links ▾", callback_data="cfg:sub:whitelist_hub")
        ],
        [
            InlineKeyboardButton(f"💾 Backups & Relatórios {status_icon(bkp_on)} ▾", callback_data="cfg:sub:backup"),
            InlineKeyboardButton(f"📡 Logs {status_icon(has_logs)} ▾", callback_data="cfg:sub:logs")
        ],
        [
            InlineKeyboardButton(f"🌙 Modo Noturno {status_icon(nm_on)} ▾", callback_data="cfg:sub:nightmode"),
            InlineKeyboardButton(f"🕒 Fuso Horário ({tz_label}) ▾", callback_data="cfg:sub:timezone")
        ],
        [
            InlineKeyboardButton("ℹ️ Versão & Docs", callback_data="cfg:sub:docs"),
            InlineKeyboardButton("◀ Voltar ao Painel", callback_data="cfg:page:1")
        ]
    ]
    return text, InlineKeyboardMarkup(kb)


def generate_sub_clean_help():
    lines = [
        "🗑️ *FAXINA RÁPIDA DE MENSAGENS NO CHAT*\n",
        "Para apagar mensagens em lote no grupo rapidamente, utilize o comando `/limpar` diretamente no grupo:\n",
        "• `/limpar 10` — Apaga as últimas 10 mensagens",
        "• `/limpar 50` — Apaga as últimas 50 mensagens",
        "• `/limpar 100` — Apaga as últimas 100 mensagens\n",
        "💡 *Como funciona:*",
        "Apenas administradores podem acionar esse comando. O bot apaga as mensagens instantaneamente e depois apaga o próprio comando!"
    ]
    text = "\n".join(lines)
    kb = [
        [InlineKeyboardButton("◀ Voltar à Central de Limpeza", callback_data="cfg:hub:clean")]
    ]
    return text, InlineKeyboardMarkup(kb)


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
    from config import TIMEZONE_LIST, get_timezone, get_timezone_label
    tz = get_timezone(cfg)
    cur_tz_name = cfg.get("timezone", "America/Sao_Paulo")
    now_local = datetime.now(tz)
    now_str = now_local.strftime("%d/%m/%Y às %H:%M:%S")
    cur_label = get_timezone_label(cfg)

    text = (
        "🕒 ═══════════════════ 🕒\n"
        "     *FUSO HORÁRIO DO MAESTRO*\n"
        "🕒 ═══════════════════ 🕒\n\n"
        f"🌐 *Fuso Ativo:* `{cur_label}`\n"
        f"🕒 *Hora Atual:* `{now_str}`\n\n"
        "💡 *Importância do Fuso Horário:*\n"
        "• Determina o início e o fim do *Modo Noturno (Silêncio)*.\n"
        "• Garante a pontualidade dos disparos de *Mensagens Programadas*.\n"
        "• Registra horários exatos nos relatórios e auditoria.\n\n"
        "👇 *Selecione o fuso da sua região ou digite um novo:*"
    )

    kb = []
    row = []
    for tz_key, tz_title in TIMEZONE_LIST:
        is_cur = (tz_key == cur_tz_name)
        short_title = tz_title.split("/")[0].strip()
        btn_label = f"✅ {short_title}" if is_cur else short_title
        row.append(InlineKeyboardButton(btn_label, callback_data=f"cfg:set:tz:{tz_key}"))
        if len(row) == 2:
            kb.append(row)
            row = []
    if row:
        kb.append(row)

    kb.append([
        InlineKeyboardButton("✍️ Digitar Fuso IANA (ex: America/Recife)", callback_data="cfg:input:tz")
    ])
    kb.append([
        InlineKeyboardButton("◀ Voltar ao Avançado", callback_data="cfg:page:2")
    ])

    return text, InlineKeyboardMarkup(kb)


def generate_sub_docs():
    text = (
        "ℹ️ *MAESTRO BOT ENTERPRISE* — `v2.5.0`\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "Sistema Avançado e Autônomo de Gerenciamento, Moderação e Transmissão para Grupos e Canais do Telegram.\n\n"
        "✨ *Principais Módulos & Recursos:*\n"
        "• *Múltiplos Grupos & Canais:* Suporte ilimitado a grupos e canais vinculados.\n"
        "• *Formatação Total:* Negrito, Itálico, Spoiler, Citações expansíveis (`>>`) e Botões em grade (`[Texto | link]`).\n"
        "• *Mensagens Programadas:* Disparo por intervalo, horário fixo ou contagem de mensagens com seletor de destino.\n"
        "• *Proteções Ativas:* CAPTCHA interativo, Anti-Spam, Anti-Repetição inteligente e Modo Noturno programado.\n"
        "• *Backup & Restauração:* Baixe e recupere todas as suas configurações via JSON em 1 clique.\n\n"
        "📖 *Documentação Completa:* Acesse o arquivo `DOCUMENTACAO.md` ou use `/ajuda`."
    )
    markup = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🎓 Central de Tutoriais", callback_data="tut:main"),
            InlineKeyboardButton("📋 Ver Todos Comandos", callback_data="help:cat:all")
        ],
        [InlineKeyboardButton("◀ Voltar à Central de Limpeza", callback_data="cfg:hub:clean")]
    ])
    return text, markup


def generate_sub_nightmode(cfg: dict):
    nm = cfg.setdefault("night_mode", {
        "enabled": False,
        "start": "23:00",
        "end": "07:00",
        "warn_delete_after_seconds": 8,
        "announce_start": True,
        "announce_end": True,
        "current_state": None,
        "enabled_chats": []
    })
    nm_on = nm.get("enabled", False)
    s = nm.get("start", "23:00")
    e = nm.get("end", "07:00")
    ann_s = nm.get("announce_start", True)
    ann_e = nm.get("announce_end", True)
    ann_str = "🔔 Ativados" if (ann_s and ann_e) else ("🔕 Desativados" if (not ann_s and not ann_e) else "🔔 Parcial")

    cur_st = nm.get("current_state") or "day"
    cur_lbl = "🌙 Noite (Silêncio)" if cur_st == "night" else "☀️ Dia (Liberado)"

    text = (
        "🌙 *CONFIGURAÇÃO: MODO NOTURNO (SILÊNCIO PROGRAMADO)*\n\n"
        f"• *Status:* {status_icon(nm_on)} {'Ativado' if nm_on else 'Desativado'}\n"
        f"• *Horário de Silêncio:* das `{s}` às `{e}`\n"
        f"• *Estado Atual:* `{cur_lbl}`\n"
        f"• *Avisos no Grupo (Início e Fim):* {ann_str}\n\n"
        "Durante o horário de silêncio, apenas administradores podem enviar mensagens no grupo. "
        "O bot envia avisos amigáveis no início e término do silêncio!"
    )

    toggle_lbl = "🔴 Desativar Noturno" if nm_on else "🟢 Ativar Noturno"
    ann_lbl = "🔕 Desligar Avisos" if (ann_s and ann_e) else "🔔 Ligar Avisos"

    keyboard = [
        [
            InlineKeyboardButton(toggle_lbl, callback_data="cfg:toggle:nightmode"),
            InlineKeyboardButton(ann_lbl, callback_data="cfg:toggle:nightmode_ann")
        ],
        [
            InlineKeyboardButton("🚀 Testar Aviso Início", callback_data="cfg:test:nightmode_start"),
            InlineKeyboardButton("🚀 Testar Aviso Fim", callback_data="cfg:test:nightmode_end")
        ],
        [
            InlineKeyboardButton("◀ Voltar", callback_data="cfg:page:2")
        ]
    ]
    return text, InlineKeyboardMarkup(keyboard)


def generate_sub_logs(cfg: dict):
    channel_id = cfg.get("log_channel_id")
    has_channel = bool(channel_id)
    ev = cfg.get("log_events", {})

    status_str = f"🟢 Ativo (ID: `{channel_id}`)" if has_channel else "🔴 Desativado (Nenhum canal configurado)"

    text = (
        "📡 *CONFIGURAÇÃO: CANAL DE LOGS & AUDITORIA*\n\n"
        "O canal de logs registra em tempo real todas as punições e ações do bot (estilo Group Help / Rose).\n\n"
        f"• *Status:* {status_str}\n\n"
        "🔔 *Eventos Monitorados:*\n"
        f"• 🔨 Bans & Kicks: {'🟢 Sim' if ev.get('bans', True) else '🔴 Não'}\n"
        f"• 🔇 Silenciamentos (Mutes): {'🟢 Sim' if ev.get('mutes', True) else '🔴 Não'}\n"
        f"• ❗ Advertências (Warns): {'🟢 Sim' if ev.get('warns', True) else '🔴 Não'}\n"
        f"• 🛡️ Anti-Spam (Links/Palavras): {'🟢 Sim' if ev.get('spam', True) else '🔴 Não'}\n"
        f"• 🚪 Entradas de Membros: {'🟢 Sim' if ev.get('joins', True) else '🔴 Não'}\n"
    )

    keyboard = [
        [
            InlineKeyboardButton("📡 Definir ID do Canal", callback_data="cfg:logs:set_id"),
            InlineKeyboardButton("🧪 Testar Envio", callback_data="cfg:logs:test")
        ],
        [
            InlineKeyboardButton(f"🔨 Bans: {'🟢' if ev.get('bans', True) else '🔴'}", callback_data="cfg:logs:toggle:bans"),
            InlineKeyboardButton(f"🔇 Mutes: {'🟢' if ev.get('mutes', True) else '🔴'}", callback_data="cfg:logs:toggle:mutes")
        ],
        [
            InlineKeyboardButton(f"❗ Warns: {'🟢' if ev.get('warns', True) else '🔴'}", callback_data="cfg:logs:toggle:warns"),
            InlineKeyboardButton(f"🛡️ Spam: {'🟢' if ev.get('spam', True) else '🔴'}", callback_data="cfg:logs:toggle:spam")
        ],
        [
            InlineKeyboardButton(f"🚪 Entradas: {'🟢' if ev.get('joins', True) else '🔴'}", callback_data="cfg:logs:toggle:joins")
        ]
    ]

    if has_channel:
        keyboard.append([
            InlineKeyboardButton("🗑️ Desativar Canal de Logs", callback_data="cfg:logs:clear")
        ])

    keyboard.append([
        InlineKeyboardButton("◀ Voltar à Página 2", callback_data="cfg:page:2")
    ])

    return text, InlineKeyboardMarkup(keyboard)


def generate_sub_cmd_clean(cfg: dict):
    cc = cfg.get("command_cleanup", {})
    admin_del = cc.get("delete_admin_commands", True)
    user_del = cc.get("delete_non_admin_commands", True)
    notice_sec = cc.get("bot_notice_delete_seconds", 10)

    notice_label = f"{notice_sec}s" if notice_sec > 0 else "Nunca apagar"

    text = (
        "🧹 *CONFIGURAÇÃO: AUTO-LIMPEZA DE COMANDOS*\n\n"
        "Configure se o bot deve apagar automaticamente as mensagens de comandos acionadas no grupo, mantendo o chat 100% limpo e sem poluição visual.\n\n"
        f"• *Apagar Comandos de Administradores:* {'🟢 Ativado (/falar, /ban, /mute...)' if admin_del else '🔴 Desativado'}\n"
        f"• *Apagar Comandos de Membros Comuns:* {'🟢 Ativado (comandos não autorizados)' if user_del else '🔴 Desativado'}\n"
        f"• *Apagar Avisos/Respostas do Bot:* `{notice_label}`\n\n"
        "💡 *Como funciona:*\n"
        "Assim que você ou um membro envia `/falar`, `/ban`, `/mute`, `/warn`, `/limpar`, `/pin`, etc., o bot executa a ação e **apaga o comando acionado imediatamente**!"
    )

    kb = [
        [
            InlineKeyboardButton(f"Comandos de Admin: {'🟢 Ativado' if admin_del else '🔴 Desativado'}", callback_data="cfg:toggle:clean_admin")
        ],
        [
            InlineKeyboardButton(f"Comandos de Membros: {'🟢 Ativado' if user_del else '🔴 Desativado'}", callback_data="cfg:toggle:clean_user")
        ],
        [
            InlineKeyboardButton(f"⏱️ Tempo Aviso Bot: {notice_label}", callback_data="cfg:cycle:clean_notice")
        ],
        [
            InlineKeyboardButton("◀ Voltar ao Painel", callback_data="cfg:page:2")
        ]
    ]
    return text, InlineKeyboardMarkup(kb)


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
    s = cfg.get("antispam", {})
    enabled = s.get("enabled", True)
    links = s.get("block_links", True)
    invites = s.get("block_telegram_invites", True)
    forwards = s.get("block_forwards", True)

    text = (
        "🛡️ *CONFIGURAÇÃO: ANTI-SPAM*\n\n"
        f"• *Status Geral:* {'🟢 Ativado' if enabled else '🔴 Desativado'}\n"
        f"• *Bloquear Links da Web:* {'🟢 Sim' if links else '🔴 Não'}\n"
        f"• *Bloquear Convites Telegram (t.me):* {'🟢 Sim' if invites else '🔴 Não'}\n"
        f"• *Bloquear Encaminhamentos de Canais:* {'🟢 Sim' if forwards else '🔴 Não'}\n"
    )

    keyboard = [
        [
            InlineKeyboardButton("🔴 Desativar Geral" if enabled else "🟢 Ativar Geral", callback_data="cfg:toggle:antispam")
        ],
        [
            InlineKeyboardButton(f"Links: {'ON' if links else 'OFF'}", callback_data="cfg:toggle:links"),
            InlineKeyboardButton(f"Convites: {'ON' if invites else 'OFF'}", callback_data="cfg:toggle:invites")
        ],
        [
            InlineKeyboardButton(f"Encaminhados: {'ON' if forwards else 'OFF'}", callback_data="cfg:toggle:forwards"),
            InlineKeyboardButton("🌐 Links Permitidos", callback_data="cfg:sub:allowed_links")
        ],
        [
            InlineKeyboardButton("👤 Usuários Livres (Whitelist)", callback_data="cfg:sub:whitelist_users")
        ],
        [
            InlineKeyboardButton("◀ Voltar ao Menu", callback_data="cfg:page:1")
        ]
    ]

    return text, InlineKeyboardMarkup(keyboard)


def generate_sub_antiflood(cfg: dict):
    f = cfg.get("antiflood", {})
    enabled = f.get("enabled", True)
    max_m = f.get("max_messages", 5)
    win = f.get("time_window_seconds", 5)
    mute = f.get("mute_duration_minutes", 5)

    text = (
        "🌊 *CONFIGURAÇÃO: ANTI-FLOOD*\n\n"
        f"• *Status:* {'🟢 Ativado' if enabled else '🔴 Desativado'}\n"
        f"• *Gatilho:* Mais de `{max_m}` mensagens em `{win}s`.\n"
        f"• *Penalidade:* Silêncio de `{mute}` minutos.\n"
    )

    keyboard = [
        [
            InlineKeyboardButton("🔴 Desativar" if enabled else "🟢 Ativar", callback_data="cfg:toggle:flood")
        ],
        [
            InlineKeyboardButton(f"Punição: {mute} min", callback_data="cfg:cycle:flood_mute")
        ],
        [
            InlineKeyboardButton("◀ Voltar ao Menu", callback_data="cfg:page:1")
        ]
    ]

    return text, InlineKeyboardMarkup(keyboard)


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

