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

def status_icon(active: bool) -> str:
    return "🟢" if active else "🔴"

PUNISHMENT_INFO = {
    "warn": ("⚠️ Só Aviso", "Apaga a mensagem e envia aviso temporário"),
    "warning": ("❗ Só Advertência", "Apaga e conta advertência (1/3, 2/3 -> Ban ao atingir 3)"),
    "ban": ("🔨 Ban Imediato", "Apaga a mensagem e bane o infrator na mesma hora")
}

PUNISHMENT_CYCLE = ["warn", "warning", "ban"]

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

# =====================================================================
# PÁGINAS PRINCIPAIS DO MENU (DESIGN MAESTRO BOT)
# =====================================================================

def generate_page_1(chat_title: str, cfg: dict):
    w_on = cfg.get("welcome", {}).get("enabled", True)
    s_on = cfg.get("antispam", {}).get("enabled", True)
    f_on = cfg.get("antiflood", {}).get("enabled", True)
    rec_count = len(cfg.get("recurring_messages", []))
    sched_count = len([x for x in cfg.get("scheduled_transmissions", []) if x.get("status") == "pending"])
    resp_count = len(cfg.get("auto_responses", []))
    lk_on = cfg.get("antispam", {}).get("block_links", True)
    grp_count = len(cfg.get("linked_groups", []))
    chn_count = len(cfg.get("linked_channels", []))
    acervo_on = cfg.get("acervo_group_auto_reply", False)

    text = (
        "🎼 ═══════════════════ 🎼\n"
        "   *MAESTRO BOT — PAINEL PRINCIPAL*\n"
        "🎼 ═══════════════════ 🎼\n\n"
        f"🏛️ *Chat Ativo:* `{chat_title}`\n"
        "✨ *Status Geral:* Sistema harmônico e operacional\n\n"
        "Toque em uma seção abaixo para orquestrar as configurações:"
    )

    keyboard = [
        [
            InlineKeyboardButton("📢 Nova Transmissão ▾", callback_data="cfg:wiz:start"),
            InlineKeyboardButton(f"🗓️ Agendados ({sched_count})", callback_data="cfg:sched:list")
        ],
        [
            InlineKeyboardButton("📜 Regras", callback_data="cfg:sub:rules"),
            InlineKeyboardButton(f"🛡️ Anti-Spam {status_icon(s_on)}", callback_data="cfg:sub:antispam")
        ],
        [
            InlineKeyboardButton(f"💬 Boas-Vindas {status_icon(w_on)}", callback_data="cfg:sub:welcome"),
            InlineKeyboardButton(f"🌊 Anti-Flood {status_icon(f_on)}", callback_data="cfg:sub:antiflood")
        ],
        [
            InlineKeyboardButton(f"🤖 Regex ({resp_count})", callback_data="cfg:resp:list"),
            InlineKeyboardButton(f"⏱️ Repetidas ({rec_count})", callback_data="cfg:rec:list")
        ],
        [
            InlineKeyboardButton(f"🔗 Bloquear Links {status_icon(lk_on)}", callback_data="cfg:toggle:links"),
            InlineKeyboardButton("🔤 Palavras Proibidas", callback_data="cfg:sub:banned")
        ],
        [
            InlineKeyboardButton(f"🌐 Chats ({grp_count}G/{chn_count}C)", callback_data="cfg:chats:list"),
            InlineKeyboardButton("🗑️ Limpar Chat", callback_data="cfg:sub:clean")
        ],
        [
            InlineKeyboardButton("🛡️ Whitelist & Links ▾", callback_data="cfg:sub:whitelist_hub"),
            InlineKeyboardButton(f"🎼 Acervo Musical {status_icon(acervo_on)}", callback_data="cfg:sub:acervo")
        ],
        [
            InlineKeyboardButton("🎛️ Avançado ▶", callback_data="cfg:page:2"),
            InlineKeyboardButton("✅ Concluir Orquestração", callback_data="cfg:close")
        ]
    ]

    return text, InlineKeyboardMarkup(keyboard)

def generate_page_2(chat_title: str, cfg: dict):
    inv_on = cfg.get("antispam", {}).get("block_telegram_invites", True)
    fwd_on = cfg.get("antispam", {}).get("block_forwards", True)
    del_serv = cfg.get("welcome", {}).get("delete_service_messages", True)
    del_w_sec = cfg.get("welcome", {}).get("delete_welcome_after_seconds", 600)
    rep_filter_on = cfg.get("antirepeat", {}).get("enabled", True)
    rep_hours = cfg.get("antirepeat", {}).get("time_window_hours", 2)
    rep_win_str = f"{rep_hours}h" if rep_hours >= 1 else "5 min"
    has_logs = bool(cfg.get("log_channel_id"))
    cap_on = cfg.get("captcha", {}).get("enabled", False)
    jr_on = cfg.get("join_requests", {}).get("auto_approve", False)
    clean_on = cfg.get("command_cleanup", {}).get("delete_admin_commands", True)
    tz_label = get_timezone_label(cfg)

    nm = cfg.get("night_mode", {})
    nm_on = nm.get("enabled", False)

    pin_serv = cfg.get("delete_pinned_service_messages", True)

    text = (
        "🎼 ═══════════════════ 🎼\n"
        "   *MAESTRO BOT — AVANÇADO (Pág. 2)*\n"
        "🎼 ═══════════════════ 🎼\n\n"
        f"🏛️ *Chat Ativo:* `{chat_title}`\n"
        f"🕒 *Fuso Ativo:* `{tz_label}`\n"
        f"⏱️ *Auto-Apagar Boas-Vindas:* `{format_time_label(del_w_sec)}`\n\n"
        "Módulos avançados de temporização, segurança e limpeza:"
    )

    keyboard = [
        [
            InlineKeyboardButton(f"🌙 Modo Noturno {status_icon(nm_on)}", callback_data="cfg:sub:nightmode"),
            InlineKeyboardButton(f"🧩 CAPTCHA {status_icon(cap_on)}", callback_data="cfg:toggle:captcha")
        ],
        [
            InlineKeyboardButton(f"📥 Auto-Aprovar {status_icon(jr_on)}", callback_data="cfg:toggle:join_req"),
            InlineKeyboardButton(f"🛡️ Anti-Repetição {status_icon(rep_filter_on)}", callback_data="cfg:toggle:user_repeat")
        ],
        [
            InlineKeyboardButton(f"⏱️ Auto-Apagar Boas-Vindas ({format_time_label(del_w_sec)}) ▾", callback_data="cfg:sub:wtime:general")
        ],
        [
            InlineKeyboardButton("🕒 Fuso Horário ▾", callback_data="cfg:sub:timezone"),
            InlineKeyboardButton(f"⏱️ Janela: {rep_win_str}", callback_data="cfg:cycle:repeat_window")
        ],
        [
            InlineKeyboardButton(f"🚪 Limpar Entradas {status_icon(del_serv)}", callback_data="cfg:toggle:service_msg"),
            InlineKeyboardButton(f"📌 Limpar Fixados {status_icon(pin_serv)}", callback_data="cfg:toggle:pin_service_msg")
        ],
        [
            InlineKeyboardButton(f"🧹 Limpar Comandos {status_icon(clean_on)}", callback_data="cfg:sub:cmd_clean"),
            InlineKeyboardButton(f"📡 Canal Logs {status_icon(has_logs)}", callback_data="cfg:sub:logs")
        ],
        [
            InlineKeyboardButton(f"📢 Travar Convites {status_icon(inv_on)}", callback_data="cfg:toggle:invites"),
            InlineKeyboardButton(f"⏩ Travar Encaminhados {status_icon(fwd_on)}", callback_data="cfg:toggle:forwards")
        ],
        [
            InlineKeyboardButton("◀ Voltar à Pág 1", callback_data="cfg:page:1"),
            InlineKeyboardButton("ℹ️ Versão & Docs", callback_data="cfg:sub:docs")
        ],
        [
            InlineKeyboardButton("✅ Concluir Orquestração", callback_data="cfg:close")
        ]
    ]

    return text, InlineKeyboardMarkup(keyboard)

def generate_chats_list_page(cfg: dict):
    groups = cfg.get("linked_groups", [])
    channels = cfg.get("linked_channels", [])
    main_grp = cfg.get("main_group_id")
    main_ch = cfg.get("main_channel_id")

    text = (
        "🌐 ═══════════════════ 🌐\n"
        "   *ORQUESTRAÇÃO: GRUPOS E CANAIS*\n"
        "🌐 ═══════════════════ 🌐\n\n"
        "Gerencie todas as salas vinculadas ao Maestro Bot em um único lugar!\n\n"
        f"• 👥 *Grupos Registrados:* `{len(groups)}`\n"
        f"• 📢 *Canais Registrados:* `{len(channels)}`\n\n"
        "👉 *Toque em um chat para abrir os detalhes e gerenciar:*"
    )

    kb = []
    if groups:
        kb.append([make_disabled_button("─── 👥 GRUPOS VINCULADOS ───")])
        for g in groups:
            gid = g.get("id")
            gtit = g.get("title", f"Grupo {gid}")
            if len(gtit) > 22:
                gtit = gtit[:20] + "…"
            is_m = " ⭐️ [Principal]" if gid == main_grp else ""
            kb.append([InlineKeyboardButton(f"👥 {gtit}{is_m}", callback_data=f"cfg:chat:info:grp:{gid}")])

    if channels:
        kb.append([make_disabled_button("─── 📢 CANAIS VINCULADOS ───")])
        for c in channels:
            cid = c.get("id")
            ctit = c.get("title", f"Canal {cid}")
            if len(ctit) > 22:
                ctit = ctit[:20] + "…"
            is_m = " ⭐️ [Principal]" if cid == main_ch else ""
            kb.append([InlineKeyboardButton(f"📢 {ctit}{is_m}", callback_data=f"cfg:chat:info:chn:{cid}")])

    kb.append([InlineKeyboardButton("➕ Como Vincular Novo Grupo ou Canal", callback_data="cfg:chats:how_to")])
    kb.append([InlineKeyboardButton("◀ Voltar ao Painel", callback_data="cfg:page:1")])
    return text, InlineKeyboardMarkup(kb)

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
        [InlineKeyboardButton("◀ Voltar ao Painel", callback_data="cfg:page:2")]
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


# =====================================================================
# SUB-MENU: MENSAGENS REPETIDAS / PROGRAMADAS (CRONOGRAMA)
# =====================================================================

def get_recurring_title(m: dict) -> str:
    custom = m.get("title")
    if custom and custom.strip():
        return custom.strip()
    raw = m.get("text", "")
    if raw:
        first = raw.strip().split("\n")[0].strip()
        clean = re.sub(r"[*_`~#\[\]]", "", first).strip()
        if clean:
            return clean[:32]
    return f"Mensagem #{m.get('id', 1)}"


def get_recurring_dest_label(m: dict, cfg: dict) -> str:
    tid = m.get("chat_id")
    if tid == "all":
        return "🌐 Todos"
    elif tid == "all_groups":
        return "👥 Todos os Grupos"
    elif tid == "all_channels":
        return "📢 Todos os Canais"
    elif tid:
        c = next((ch for ch in cfg.get("linked_channels", []) if ch.get("id") == tid), None)
        g = next((gr for gr in cfg.get("linked_groups", []) if gr.get("id") == tid), None)
        if c:
            return f"📢 {c.get('title', 'Canal')}"
        if g:
            return f"👥 {g.get('title', 'Grupo')}"
        return f"Chat {tid}"
    main_grp = cfg.get("main_group_id")
    if main_grp:
        g = next((gr for gr in cfg.get("linked_groups", []) if gr.get("id") == main_grp), None)
        if g:
            return f"👥 {g.get('title', 'Grupo Principal')}"
    return "👥 Grupo Principal"


def generate_recurring_list(chat_title: str, cfg: dict, page: int = 1, per_page: int = 5):
    rec_list = cfg.get("recurring_messages", [])
    total_items = len(rec_list)
    total_pages = max(1, math.ceil(total_items / per_page)) if total_items > 0 else 1
    page = max(1, min(page, total_pages))

    start_idx = (page - 1) * per_page
    end_idx = start_idx + per_page
    page_items = rec_list[start_idx:end_idx]

    now_str = datetime.now(get_timezone(cfg)).strftime("%d de %b. de %Y, %H:%M")
    tz_label = get_timezone_label(cfg)

    text = (
        "⏱️ *MENSAGENS REPETIDAS / PROGRAMADAS*\n"
        "Configure mensagens automáticas com texto, fotos e botões para seus grupos e canais.\n\n"
        f"🕐 *Hora atual:* `{now_str}` ({tz_label})\n"
    )

    if not rec_list:
        text += "\n_Nenhuma mensagem programada cadastrada no momento._\n_Clique em '➕ Adicionar Nova Mensagem' abaixo para criar!_"
    else:
        text += f"\n📋 *Mensagens Cadastradas ({total_items} no total)* — Página `{page}/{total_pages}`:\n"
        for m in page_items:
            m_id = m.get("id", 1)
            on = m.get("enabled", True)
            status_tag = "🟢 Ativado" if on else "🔴 Desativado"
            interval_str = format_interval_display(m)
            crono_str = format_cronograma_display(m)
            crono_tag = f" às {crono_str}" if crono_str != "Não definido" else ""
            title_str = get_recurring_title(m)
            dest_str = get_recurring_dest_label(m, cfg)

            badges = []
            btn_cnt = sum(len(r) for r in m.get("buttons", [])) if m.get("buttons") else 0
            if btn_cnt > 0:
                badges.append(f"🔘 {btn_cnt} botão(ões)")
            if m.get("photo"):
                badges.append("🖼️ Foto")
            if m.get("pin_message"):
                badges.append("📌 Fixar")
            if m.get("delete_previous"):
                badges.append("♻️ Auto-Limpar")
            badges_str = f" • {' | '.join(badges)}" if badges else ""

            raw_txt = m.get("text", "").replace("\n", " ").strip()
            preview = (raw_txt[:55] + "...") if len(raw_txt) > 55 else raw_txt

            text += f"\n*{m_id}. {status_tag} — {title_str}*\n"
            text += f"├ 🎯 *Destino:* {dest_str}\n"
            text += f"├ ⏰ *Horário:* {interval_str}{crono_tag}{badges_str}\n"
            if preview:
                text += f"└ 💬 _{preview}_\n"

    keyboard = [
        [
            InlineKeyboardButton("➕ Adicionar Nova Mensagem", callback_data=f"cfg:rec:add:{page}"),
            InlineKeyboardButton("🕒 Fuso Horário ▾", callback_data="cfg:sub:timezone")
        ]
    ]

    for m in page_items:
        m_id = m.get("id", 1)
        on = m.get("enabled", True)
        title_str = get_recurring_title(m)
        dest_str = get_recurring_dest_label(m, cfg)

        # Botão principal grande com ID, título e destino:
        btn_label = f"💬 #{m_id}: {title_str[:20]} ({dest_str[:12]})"
        keyboard.append([
            InlineKeyboardButton(btn_label, callback_data=f"cfg:rec:detail:{m_id}:{page}")
        ])
        # Linha de atalhos rápidos: Ligar/Desligar, Clonar/Copiar, Excluir
        keyboard.append([
            InlineKeyboardButton("🟢 Ativado" if on else "🔴 Desativado", callback_data=f"cfg:rec:toggle:{m_id}:{page}"),
            InlineKeyboardButton("📋 Copiar", callback_data=f"cfg:rec:clone:{m_id}:{page}"),
            InlineKeyboardButton("🗑️", callback_data=f"cfg:rec:del:{m_id}:{page}")
        ])

    # Barra de Paginação (se houver mais de 1 página)
    if total_pages > 1:
        nav_row = []
        if page > 1:
            nav_row.append(InlineKeyboardButton("◀️ Anterior", callback_data=f"cfg:rec:list:{page-1}"))
        else:
            nav_row.append(InlineKeyboardButton("◀️", callback_data="cfg:noop"))

        nav_row.append(InlineKeyboardButton(f"📄 {page} / {total_pages}", callback_data="cfg:noop"))

        if page < total_pages:
            nav_row.append(InlineKeyboardButton("Próxima ▶️", callback_data=f"cfg:rec:list:{page+1}"))
        else:
            nav_row.append(InlineKeyboardButton("▶️", callback_data="cfg:noop"))

        keyboard.append(nav_row)

    keyboard.append([InlineKeyboardButton("◀ Voltar ao Menu", callback_data="cfg:page:1")])
    return text, InlineKeyboardMarkup(keyboard)


def generate_recurring_detail(cfg: dict, msg_id: int, page: int = 1):
    rec_list = cfg.get("recurring_messages", [])
    msg_item = next((m for m in rec_list if m.get("id") == msg_id), None)
    if not msg_item:
        return "❌ Mensagem não encontrada.", InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Voltar", callback_data=f"cfg:rec:list:{page}")]])

    enabled = msg_item.get("enabled", True)
    crono_str = format_cronograma_display(msg_item)
    rep_str = format_interval_display(msg_item)
    pin = msg_item.get("pin_message", False)
    del_prev = msg_item.get("delete_previous", False)
    autodel = msg_item.get("auto_delete_seconds", 0)

    wday_str = format_weekdays_display(msg_item)
    mday_str = format_month_days_display(msg_item)
    title_str = get_recurring_title(msg_item)
    dest_str = get_recurring_dest_label(msg_item, cfg)

    raw_text = msg_item.get("text", "")
    preview_txt = raw_text[:200] + ("..." if len(raw_text) > 200 else "")
    buttons = msg_item.get("buttons", [])
    has_photo = bool(msg_item.get("photo"))

    text = (
        f"🕒 *Mensagem Programada #{msg_id}*\n"
        f"🏷️ *Nome/Identificador:* `{title_str}`\n\n"
        f"💡 *Situação:* {'🟢 Ativado ✓' if enabled else '🔴 Desativado'}\n"
        f"🎯 *Destino:* {dest_str}\n"
        f"⏰ *Cronograma:* `{crono_str}`\n"
        f"🔄 *Repetição:* `{rep_str}`\n"
        f"🖼️ *Foto / Banner:* {'🟢 Sim' if has_photo else '⚪ Nenhuma'}\n"
        f"🔘 *Botões com Links:* `{len(buttons)} linha(s) configurada(s)`\n"
    )

    if buttons:
        btn_lines = []
        for row in buttons:
            row_str = " | ".join([f"[{b.get('text', '')}]" for b in row if isinstance(b, dict)])
            if row_str:
                btn_lines.append(f"  └ {row_str}")
        if btn_lines:
            text += "• *Estrutura dos Botões:*\n" + "\n".join(btn_lines[:4]) + "\n"

    text += (
        f"\n📌 *Texto Atual:*\n_{preview_txt}_\n\n"
        f"📌 *Fixar:* {'✅ Sim' if pin else '❌ Não'} | ♻️ *Deletar anterior:* {'✅ Sim' if del_prev else '❌ Não'}\n"
    )

    if autodel > 0:
        text += f"⏳ Exclusão Cronometrada: `{format_autodel_display(autodel)}`\n"
    if wday_str != "Todos os dias":
        text += f"🗓️ Dias da semana: `{wday_str}`\n"
    if mday_str != "Todos os dias":
        text += f"📆 Dias do mês: `{mday_str}`\n"
    if msg_item.get("start_date"):
        text += f"📅 Início: `{msg_item.get('start_date')}`\n"
    if msg_item.get("end_date"):
        text += f"📅 Final: `{msg_item.get('end_date')}`\n"
    art_url = msg_item.get("article_url")
    if art_url:
        text += f"📄 Artigo (Telegraph): `{art_url}`\n"

    keyboard = [
        [
            InlineKeyboardButton("✏️ Personalizar (Texto/Foto/Botões)", callback_data=f"cfg:rec:edit:{msg_id}:{page}"),
            InlineKeyboardButton("👀 Ver Prévia", callback_data=f"cfg:rec:preview:{msg_id}")
        ],
        [
            InlineKeyboardButton("🎯 Destino (Canal / Grupo)", callback_data=f"cfg:rec:target_help:{msg_id}"),
            InlineKeyboardButton("📋 Duplicar / Copiar", callback_data=f"cfg:rec:clone:{msg_id}:{page}")
        ],
        [
            InlineKeyboardButton("⏰ Cronograma", callback_data=f"cfg:rec:hour_menu:{msg_id}"),
            InlineKeyboardButton("🔄 Repetição", callback_data=f"cfg:rec:rep_menu:{msg_id}")
        ],
        [
            InlineKeyboardButton("🗓️ Dias da semana", callback_data=f"cfg:rec:wday_menu:{msg_id}"),
            InlineKeyboardButton("📆 Dias do mês", callback_data=f"cfg:rec:mday_menu:{msg_id}")
        ],
        [
            InlineKeyboardButton("📅 Início", callback_data=f"cfg:rec:dstart:{msg_id}"),
            InlineKeyboardButton("📅 Final", callback_data=f"cfg:rec:dend:{msg_id}")
        ],
        [
            InlineKeyboardButton(f"📌 Fixar {'✅' if pin else '❌'}", callback_data=f"cfg:rec:pin:{msg_id}"),
            InlineKeyboardButton(f"♻️ Del. Anterior {'✅' if del_prev else '❌'}", callback_data=f"cfg:rec:delprev:{msg_id}")
        ],
        [
            InlineKeyboardButton("⏳ Exclusão Cronometrada", callback_data=f"cfg:rec:autodel_menu:{msg_id}"),
            InlineKeyboardButton("📄 Artigo Link", callback_data=f"cfg:rec:article:{msg_id}")
        ],
        [
            InlineKeyboardButton("🔴 Desativar" if enabled else "🟢 Ativar", callback_data=f"cfg:rec:toggle:{msg_id}"),
            InlineKeyboardButton("🚀 Testar Envio Agora", callback_data=f"cfg:rec:test:{msg_id}")
        ],
        [
            InlineKeyboardButton("🗑️ Apagar Mensagem", callback_data=f"cfg:rec:del:{msg_id}:{page}"),
            InlineKeyboardButton("🔙 Voltar à Lista", callback_data=f"cfg:rec:list:{page}")
        ]
    ]

    return text, InlineKeyboardMarkup(keyboard)


def generate_recurring_hour_menu(msg_id: int):
    """Tela de seleção de hora de início (0 a 23 em grade 5x5)."""
    text = (
        "🕒 *Mensagens Repetidas*\n\n"
        "👉 *Selecione a hora de início.*"
    )
    keyboard = []
    row = []
    for h in range(24):
        row.append(InlineKeyboardButton(str(h), callback_data=f"cfg:rec:set_h:{msg_id}:{h}"))
        if len(row) == 5:
            keyboard.append(row)
            row = []
    if row:
        keyboard.append(row)
    keyboard.append([InlineKeyboardButton("🔙 Voltar", callback_data=f"cfg:rec:detail:{msg_id}")])
    return text, InlineKeyboardMarkup(keyboard)


def generate_recurring_minute_menu(msg_id: int, selected_hour: int):
    """Tela de seleção do minuto inicial (0 a 59 em grade 5x12)."""
    text = (
        "🕒 *Mensagens Repetidas*\n\n"
        f"Hora selecionada: `{selected_hour:02d}:00`\n\n"
        "👉 *Selecione o minuto inicial.*"
    )
    keyboard = []
    row = []
    for m in range(60):
        row.append(InlineKeyboardButton(str(m), callback_data=f"cfg:rec:set_m:{msg_id}:{selected_hour}:{m}"))
        if len(row) == 5:
            keyboard.append(row)
            row = []
    if row:
        keyboard.append(row)
    keyboard.append([InlineKeyboardButton("🔙 Voltar", callback_data=f"cfg:rec:hour_menu:{msg_id}")])
    return text, InlineKeyboardMarkup(keyboard)


def generate_recurring_rep_menu(cfg: dict, msg_id: int):
    """Tela de frequência de repetição por horas ou minutos, ou botão para contagem de mensagens."""
    rec_list = cfg.get("recurring_messages", [])
    msg_item = next((m for m in rec_list if m.get("id") == msg_id), {})
    cur_rep = format_interval_display(msg_item)
    cur_type = msg_item.get("interval_type", "hours")
    cur_val = msg_item.get("interval_value")
    cur_mode = msg_item.get("repeat_mode", "interval")

    text = (
        "🕒 *Mensagens Repetidas*\n\n"
        f"🔄 *Repetição:* `{cur_rep}`\n\n"
        "👉 *Selecione com que frequência a mensagem deve ser repetida.*"
    )

    keyboard = [
        [make_disabled_button("• Horas •")]
    ]

    h_row1 = []
    for h in [1, 2, 3, 4]:
        label = f"{h} ✔️" if (cur_mode == "interval" and cur_type == "hours" and cur_val == h) else str(h)
        h_row1.append(InlineKeyboardButton(label, callback_data=f"cfg:rec:set_inth:{msg_id}:{h}"))
    keyboard.append(h_row1)

    h_row2 = []
    for h in [6, 8, 12, 24]:
        is_sel = (cur_mode == "interval" and cur_type == "hours" and cur_val == h) or (cur_mode == "interval" and not cur_val and h == 24 and msg_item.get("interval_minutes") == 1440)
        label = f"{h} ✔️" if is_sel else str(h)
        h_row2.append(InlineKeyboardButton(label, callback_data=f"cfg:rec:set_inth:{msg_id}:{h}"))
    keyboard.append(h_row2)

    keyboard.append([make_disabled_button("• Minutos •")])

    m_row1 = []
    for m in [1, 2, 3, 5]:
        label = f"{m} ✔️" if (cur_mode == "interval" and cur_type == "minutes" and cur_val == m) else str(m)
        m_row1.append(InlineKeyboardButton(label, callback_data=f"cfg:rec:set_intm:{msg_id}:{m}"))
    keyboard.append(m_row1)

    m_row2 = []
    for m in [10, 15, 20, 30]:
        label = f"{m} ✔️" if (cur_mode == "interval" and cur_type == "minutes" and cur_val == m) else str(m)
        m_row2.append(InlineKeyboardButton(label, callback_data=f"cfg:rec:set_intm:{msg_id}:{m}"))
    keyboard.append(m_row2)

    keyboard.append([InlineKeyboardButton("💬 Repetir a cada poucas mensagens 🆕", callback_data=f"cfg:rec:msg_menu:{msg_id}")])
    keyboard.append([InlineKeyboardButton("🔙 Voltar", callback_data=f"cfg:rec:detail:{msg_id}")])

    return text, InlineKeyboardMarkup(keyboard)


def generate_recurring_msg_menu(cfg: dict, msg_id: int):
    """Tela de repetição por contagem de mensagens enviadas no grupo."""
    rec_list = cfg.get("recurring_messages", [])
    msg_item = next((m for m in rec_list if m.get("id") == msg_id), {})
    cur_cnt = msg_item.get("messages_interval", 50)
    is_msg_mode = (msg_item.get("repeat_mode") == "messages")

    text = (
        "🕒 *Mensagens Repetidas*\n\n"
        f"💬 *Repetição por Mensagens:* `A cada {cur_cnt} mensagens`\n\n"
        "👉 *Selecione quantas mensagens enviadas no grupo acionam esta mensagem:*"
    )

    def lbl(n):
        return f"{n} msgs ✔️" if (is_msg_mode and cur_cnt == n) else f"{n} msgs"

    keyboard = [
        [
            InlineKeyboardButton(lbl(10), callback_data=f"cfg:rec:set_mcnt:{msg_id}:10"),
            InlineKeyboardButton(lbl(20), callback_data=f"cfg:rec:set_mcnt:{msg_id}:20")
        ],
        [
            InlineKeyboardButton(lbl(50), callback_data=f"cfg:rec:set_mcnt:{msg_id}:50"),
            InlineKeyboardButton(lbl(100), callback_data=f"cfg:rec:set_mcnt:{msg_id}:100")
        ],
        [
            InlineKeyboardButton(lbl(200), callback_data=f"cfg:rec:set_mcnt:{msg_id}:200"),
            InlineKeyboardButton(lbl(500), callback_data=f"cfg:rec:set_mcnt:{msg_id}:500")
        ],
        [InlineKeyboardButton("✏️ Digitar Quantidade Personalizada", callback_data=f"cfg:rec:in_mcnt:{msg_id}")],
        [InlineKeyboardButton("⏱️ Voltar para Intervalo de Tempo", callback_data=f"cfg:rec:rep_menu:{msg_id}")],
        [InlineKeyboardButton("🔙 Voltar", callback_data=f"cfg:rec:detail:{msg_id}")]
    ]
    return text, InlineKeyboardMarkup(keyboard)


def generate_recurring_wday_menu(cfg: dict, msg_id: int):
    """Tela de seleção dos dias da semana (Seg a Dom)."""
    rec_list = cfg.get("recurring_messages", [])
    msg_item = next((m for m in rec_list if m.get("id") == msg_id), {})
    weekdays = msg_item.get("weekdays")
    if weekdays is None:
        weekdays = [0, 1, 2, 3, 4, 5, 6]

    cur_str = format_weekdays_display(msg_item)
    text = (
        "🕒 *Mensagens Repetidas*\n\n"
        f"🗓️ *Dias da semana ativos:* `{cur_str}`\n\n"
        "👉 *Selecione os dias em que a mensagem será enviada:*"
    )

    names = ["Seg", "Ter", "Qua", "Qui", "Sex", "Sáb", "Dom"]
    row1 = []
    for i in range(4):
        mark = "✔️" if i in weekdays else "❌"
        row1.append(InlineKeyboardButton(f"{names[i]} {mark}", callback_data=f"cfg:rec:tog_wday:{msg_id}:{i}"))

    row2 = []
    for i in range(4, 7):
        mark = "✔️" if i in weekdays else "❌"
        row2.append(InlineKeyboardButton(f"{names[i]} {mark}", callback_data=f"cfg:rec:tog_wday:{msg_id}:{i}"))

    keyboard = [
        row1,
        row2,
        [
            InlineKeyboardButton("✅ Todos os Dias", callback_data=f"cfg:rec:wday_p:{msg_id}:all"),
            InlineKeyboardButton("💼 Dias Úteis", callback_data=f"cfg:rec:wday_p:{msg_id}:work")
        ],
        [
            InlineKeyboardButton("🏖️ Fins de Semana", callback_data=f"cfg:rec:wday_p:{msg_id}:weekend")
        ],
        [InlineKeyboardButton("🔙 Voltar", callback_data=f"cfg:rec:detail:{msg_id}")]
    ]
    return text, InlineKeyboardMarkup(keyboard)


def generate_recurring_mday_menu(cfg: dict, msg_id: int):
    """Tela de seleção dos dias do mês (1 a 31)."""
    rec_list = cfg.get("recurring_messages", [])
    msg_item = next((m for m in rec_list if m.get("id") == msg_id), {})
    mdays = msg_item.get("month_days", [])
    all_active = (not mdays or len(mdays) >= 31)

    cur_str = format_month_days_display(msg_item)
    text = (
        "🕒 *Mensagens Repetidas*\n\n"
        f"📆 *Dias do mês ativos:* `{cur_str}`\n\n"
        "👉 *Selecione em quais dias do mês a mensagem deve ser enviada:*"
    )

    keyboard = [
        [
            InlineKeyboardButton("✅ Todos os Dias", callback_data=f"cfg:rec:mday_p:{msg_id}:all"),
            InlineKeyboardButton("📅 Dias 1 e 15", callback_data=f"cfg:rec:mday_p:{msg_id}:1_15"),
            InlineKeyboardButton("📅 Só Dia 1", callback_data=f"cfg:rec:mday_p:{msg_id}:1")
        ]
    ]

    cur_row = []
    for d in range(1, 32):
        is_on = all_active or (d in mdays)
        mark = f"{d}✓" if is_on else str(d)
        cur_row.append(InlineKeyboardButton(mark, callback_data=f"cfg:rec:tog_mday:{msg_id}:{d}"))
        if len(cur_row) == 7:
            keyboard.append(cur_row)
            cur_row = []
    if cur_row:
        keyboard.append(cur_row)

    keyboard.append([InlineKeyboardButton("🔙 Voltar", callback_data=f"cfg:rec:detail:{msg_id}")])
    return text, InlineKeyboardMarkup(keyboard)


def generate_recurring_autodel_menu(cfg: dict, msg_id: int):
    """Tela de exclusão cronometrada (auto-deleção após X tempo)."""
    rec_list = cfg.get("recurring_messages", [])
    msg_item = next((m for m in rec_list if m.get("id") == msg_id), {})
    cur_sec = msg_item.get("auto_delete_seconds", 0)

    cur_str = format_autodel_display(cur_sec) if cur_sec > 0 else "Desativado"
    text = (
        "🕒 *Mensagens Repetidas*\n\n"
        f"⏳ *Exclusão Cronometrada:* `{cur_str}`\n\n"
        "👉 *Deseja que a mensagem seja apagada automaticamente após algum tempo?*"
    )

    def lbl(sec, txt):
        return f"{txt} ✔️" if cur_sec == sec else txt

    keyboard = [
        [InlineKeyboardButton(lbl(0, "❌ Não Apagar (Desativado)"), callback_data=f"cfg:rec:set_adel:{msg_id}:0")],
        [
            InlineKeyboardButton(lbl(300, "5 min"), callback_data=f"cfg:rec:set_adel:{msg_id}:300"),
            InlineKeyboardButton(lbl(900, "15 min"), callback_data=f"cfg:rec:set_adel:{msg_id}:900"),
            InlineKeyboardButton(lbl(1800, "30 min"), callback_data=f"cfg:rec:set_adel:{msg_id}:1800")
        ],
        [
            InlineKeyboardButton(lbl(3600, "1 hora"), callback_data=f"cfg:rec:set_adel:{msg_id}:3600"),
            InlineKeyboardButton(lbl(7200, "2 horas"), callback_data=f"cfg:rec:set_adel:{msg_id}:7200"),
            InlineKeyboardButton(lbl(21600, "6 horas"), callback_data=f"cfg:rec:set_adel:{msg_id}:21600")
        ],
        [InlineKeyboardButton("🔙 Voltar", callback_data=f"cfg:rec:detail:{msg_id}")]
    ]
    return text, InlineKeyboardMarkup(keyboard)


def generate_recurring_edit_menu(cfg: dict, msg_id: int, page: int = 1):
    """Sub-menu para personalizar texto, foto e botões da mensagem repetida."""
    rec_list = cfg.get("recurring_messages", [])
    msg_item = next((m for m in rec_list if m.get("id") == msg_id), {})
    has_photo = bool(msg_item.get("photo"))
    buttons = msg_item.get("buttons", [])
    text_content = msg_item.get("text", "")
    preview_txt = (text_content[:150] + "...") if len(text_content) > 150 else (text_content or "_(Nenhum texto definido)_")
    title_str = get_recurring_title(msg_item)
    dest_str = get_recurring_dest_label(msg_item, cfg)

    total_btns = sum(len(r) for r in buttons) if buttons else 0

    text = (
        f"✏️ *Personalizar Mensagem #{msg_id}*\n"
        f"🏷️ *Nome/Identificador:* `{title_str}`\n"
        f"🎯 *Destino:* {dest_str}\n\n"
        f"• *Foto / Imagem:* {'🟢 Configurada' if has_photo else '⚪ Nenhuma'}\n"
        f"• *Botões com Links:* `{total_btns} botão(ões) configurado(s)`\n"
    )

    if buttons:
        btn_lines = []
        for row in buttons:
            row_str = " | ".join([f"[{b.get('text', '')}]" for b in row if isinstance(b, dict)])
            if row_str:
                btn_lines.append(f"  └ {row_str}")
        if btn_lines:
            text += "\n🔘 *Botões Atuais:*\n" + "\n".join(btn_lines[:4]) + "\n"

    text += (
        f"\n📌 *Texto Atual:*\n_{preview_txt}_\n\n"
        "👉 *Escolha o que deseja editar:*"
    )

    keyboard = [
        [
            InlineKeyboardButton("🏷️ Nome / Título", callback_data=f"cfg:rec:title:{msg_id}"),
            InlineKeyboardButton("✏️ Alterar Texto", callback_data=f"cfg:rec:text:{msg_id}")
        ],
        [
            InlineKeyboardButton("🖼️ Foto / Banner", callback_data=f"cfg:rec:photo:{msg_id}"),
            InlineKeyboardButton("🔘 Configurar Botões", callback_data=f"cfg:rec:buttons:{msg_id}")
        ],
        [
            InlineKeyboardButton("👀 Ver Prévia Completa", callback_data=f"cfg:rec:preview:{msg_id}")
        ]
    ]

    cleanup_row = []
    if has_photo:
        cleanup_row.append(InlineKeyboardButton("🗑️ Remover Foto", callback_data=f"cfg:rec:delphoto:{msg_id}:{page}"))
    if buttons:
        cleanup_row.append(InlineKeyboardButton("🗑️ Remover Botões", callback_data=f"cfg:rec:delbuttons:{msg_id}:{page}"))
    if cleanup_row:
        keyboard.append(cleanup_row)

    keyboard.append([InlineKeyboardButton("🔙 Voltar à Mensagem", callback_data=f"cfg:rec:detail:{msg_id}:{page}")])
    return text, InlineKeyboardMarkup(keyboard)


def generate_recurring_date_menu(cfg: dict, msg_id: int, is_start: bool):
    """Menu para definir data de início ou data final."""
    rec_list = cfg.get("recurring_messages", [])
    msg_item = next((m for m in rec_list if m.get("id") == msg_id), {})
    field = "start_date" if is_start else "end_date"
    cur_val = msg_item.get(field) or "Não definida"

    title = "Data de Início" if is_start else "Data Final"
    text = (
        "🕒 *Mensagens Repetidas*\n\n"
        f"📅 *{title}:* `{cur_val}`\n\n"
        f"👉 Escolha uma opção ou digite a {title.lower()} (formato AAAA-MM-DD):"
    )

    pfx = "dstart" if is_start else "dend"
    keyboard = [
        [
            InlineKeyboardButton("📅 Hoje", callback_data=f"cfg:rec:{pfx}_today:{msg_id}"),
            InlineKeyboardButton("❌ Limpar Data", callback_data=f"cfg:rec:{pfx}_clear:{msg_id}")
        ],
        [InlineKeyboardButton("✏️ Digitar Data", callback_data=f"cfg:rec:{pfx}_input:{msg_id}")],
        [InlineKeyboardButton("🔙 Voltar", callback_data=f"cfg:rec:detail:{msg_id}")]
    ]
    return text, InlineKeyboardMarkup(keyboard)



# =====================================================================
# SUB-MENU: RESPOSTAS AUTOMÁTICAS (REGEX & PALAVRAS-CHAVE)
# =====================================================================

def generate_auto_responder_list(chat_title: str, cfg: dict):
    responders = cfg.get("auto_responses", [])

    text = (
        "🤖 *RESPOSTAS AUTOMÁTICAS (REGEX & PALAVRAS)*\n"
        "Configure respostas automáticas personalizadas quando alguém enviar palavras ou frases específicas.\n\n"
    )

    if not responders:
        text += "_Nenhuma resposta automática configurada no momento._\n_Clique em '➕ Nova Resposta' abaixo para criar!_"
    else:
        text += f"📋 *Respostas Cadastradas ({len(responders)}):*\n"
        for r in responders:
            r_id = r.get("id", 1)
            on = r.get("enabled", True)
            status_tag = "🟢 Ativo" if on else "🔴 Inativo"
            mode = "Regex" if r.get("is_regex", True) else "Palavra"
            title = r.get("title", f"Resposta #{r_id}")
            pat = r.get("pattern", "")[:35]
            text += f"\n*{r_id}. {title}* ({status_tag})\n├ *Gatilho [{mode}]:* `{pat}`\n└ *Cooldown:* `{r.get('cooldown_seconds', 30)}s`\n"

    keyboard = [
        [InlineKeyboardButton("➕ Nova Resposta Automática", callback_data="cfg:resp:add")]
    ]

    for r in responders:
        r_id = r.get("id")
        title = r.get("title", f"Resposta #{r_id}")
        on_icon = "🟢" if r.get("enabled", True) else "🔴"
        keyboard.append([
            InlineKeyboardButton(f"{on_icon} #{r_id} - {title[:28]}", callback_data=f"cfg:resp:detail:{r_id}")
        ])

    keyboard.append([
        InlineKeyboardButton("◀ Voltar ao Menu", callback_data="cfg:page:1")
    ])

    return text, InlineKeyboardMarkup(keyboard)


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


# =====================================================================
# WIZARD: GUIA DE TRANSMISSÃO & COMUNICADOS GUIADOS
# =====================================================================

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


def generate_wizard_dest_menu(cfg: dict):
    """Gera o Passo 1 do Assistente de Transmissão: Seleção de Destino."""
    linked_g = cfg.get("linked_groups", [])
    linked_c = cfg.get("linked_channels", [])

    text = (
        "📢 ══════════════════════ 📢\n"
        "   *GUIA DE TRANSMISSÃO — PASSO 1/4*\n"
        "📢 ══════════════════════ 📢\n\n"
        "🎯 *Para onde você deseja enviar este comunicado?*\n\n"
        "Escolha abaixo o canal, grupo ou lista de transmissão:"
    )

    keyboard = []

    # Canal Principal ou botão para vincular se não houver canais
    if linked_c:
        main_c = next((c for c in linked_c if c.get("id") == cfg.get("main_channel_id")), linked_c[0])
        c_title = main_c.get("title", "Canal")[:22]
        keyboard.append([
            InlineKeyboardButton(f"📢 Canal Principal: {c_title}", callback_data="cfg:wiz:dest:main_channel")
        ])
    else:
        keyboard.append([
            InlineKeyboardButton("⚠️ Nenhum Canal Vinculado (Toque para Conectar)", callback_data="cfg:wiz:add_channel")
        ])

    all_btn_text = f"🌐 Transmitir em TODOS ({len(linked_g)}G + {len(linked_c)}C)" if linked_c else f"🌐 Transmitir em TODOS ({len(linked_g)} Grupos)"
    keyboard.append([
        InlineKeyboardButton(f"👥 Todos os Grupos ({len(linked_g)})", callback_data="cfg:wiz:dest:all_groups"),
        InlineKeyboardButton(f"📢 Todos os Canais ({len(linked_c)})", callback_data="cfg:wiz:dest:all_channels")
    ])
    keyboard.append([
        InlineKeyboardButton(all_btn_text, callback_data="cfg:wiz:dest:all")
    ])

    chat_rows = []
    from config import normalize_chat_id
    for g in linked_g:
        g_id = normalize_chat_id(g.get("id"))
        g_title = g.get("title", f"Chat {g_id}")[:24]
        icon = "📢" if g.get("type") == "channel" else "👥"
        chat_rows.append([InlineKeyboardButton(f"{icon} {g_title}", callback_data=f"cfg:wiz:dest:grp:{g_id}")])
    for c in linked_c:
        c_id = normalize_chat_id(c.get("id"))
        c_title = c.get("title", f"Canal {c_id}")[:24]
        chat_rows.append([InlineKeyboardButton(f"📢 {c_title}", callback_data=f"cfg:wiz:dest:chn:{c_id}")])

    if chat_rows:
        keyboard.extend(chat_rows[:6])

    keyboard.append([
        InlineKeyboardButton("◀ Voltar ao Painel", callback_data="cfg:page:1")
    ])

    return text, InlineKeyboardMarkup(keyboard)


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


DELAY_PRESETS = [0, 2, 5, 10, 30]

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


def generate_scheduled_transmissions_menu(cfg: dict):
    """Gera o menu com a lista de transmissões agendadas pendentes."""
    sched_list = [x for x in cfg.get("scheduled_transmissions", []) if x.get("status") == "pending"]
    sched_list.sort(key=lambda x: x.get("schedule_timestamp", 0))

    if not sched_list:
        text = (
            "🗓️ ══════════════════════ 🗓️\n"
            "   *TRANSMISSÕES AGENDADAS*\n"
            "🗓️ ══════════════════════ 🗓️\n\n"
            "⚪ *Nenhuma transmissão agendada no momento.*\n\n"
            "💡 Você pode programar comunicados usando o comando `/comunicado` ou clicando em **Nova Transmissão** no painel!"
        )
        keyboard = [
            [
                InlineKeyboardButton("📢 Nova Transmissão", callback_data="cfg:wiz:start")
            ],
            [
                InlineKeyboardButton("◀ Voltar ao Painel", callback_data="cfg:page:1")
            ]
        ]
        return text, InlineKeyboardMarkup(keyboard)

    text = (
        "🗓️ ══════════════════════ 🗓️\n"
        "   *TRANSMISSÕES AGENDADAS*\n"
        "🗓️ ══════════════════════ 🗓️\n\n"
        f"Encontrei *{len(sched_list)} transmissão(ões) programada(s)*:\n\n"
    )

    keyboard = []
    for idx, item in enumerate(sched_list[:5], 1):
        target = item.get("target", "main_channel")
        dest_label = get_wizard_dest_label(target, cfg)
        time_str = item.get("schedule_display", "Horário programado")
        delay_sec = item.get("delay_seconds", 2)
        media_type = item.get("media_type")
        media_label = "🎥 Vídeo" if media_type == "video" else ("🖼️ Foto" if media_type == "photo" else "⚪ Texto")
        pin_label = "Sim 📌" if item.get("pin") else "Não"
        preview_text = item.get("text", "")[:45].replace("\n", " ")
        if len(item.get("text", "")) > 45:
            preview_text += "..."

        text += (
            f"*{idx}️⃣ Destino:* `{dest_label}`\n"
            f"• ⏰ *Horário:* `{time_str}`\n"
            f"• 🌊 *Distribuição:* `{delay_sec}s entre chats`\n"
            f"• 🖼️ *Mídia:* `{media_label}` | 📌 *Fixar:* `{pin_label}`\n"
            f"• 📝 _{preview_text}_\n\n"
        )
        item_id = item.get("id")
        keyboard.append([
            InlineKeyboardButton(f"🚀 Disparar Agora #{idx}", callback_data=f"cfg:sched:fire:{item_id}"),
            InlineKeyboardButton(f"🗑️ Cancelar #{idx}", callback_data=f"cfg:sched:cancel:{item_id}")
        ])

    keyboard.append([
        InlineKeyboardButton("📢 Nova Transmissão", callback_data="cfg:wiz:start"),
        InlineKeyboardButton("◀ Voltar ao Painel", callback_data="cfg:page:1")
    ])

    return text, InlineKeyboardMarkup(keyboard)


# =====================================================================
# SUB-MENU: PALAVRAS PROIBIDAS & PUNIÇÕES
# =====================================================================

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


# =====================================================================
# SUB-MENUS DEMAIS
# =====================================================================

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


# =====================================================================
# CLASSE PRINCIPAL DO PAINEL INTERATIVO
# =====================================================================

class PersistentPendingInputs(dict):
    """Dicionário que persiste automaticamente todas as alterações em config.json."""
    def __init__(self, panel_handler, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.panel_handler = panel_handler

    def __setitem__(self, key, value):
        super().__setitem__(key, value)
        if self.panel_handler:
            self.panel_handler._save_pending_inputs()

    def __delitem__(self, key):
        super().__delitem__(key)
        if self.panel_handler:
            self.panel_handler._save_pending_inputs()

    def pop(self, key, default=None):
        val = super().pop(key, default)
        if self.panel_handler:
            self.panel_handler._save_pending_inputs()
        return val

    def clear(self):
        super().clear()
        if self.panel_handler:
            self.panel_handler._save_pending_inputs()


class InteractivePanelHandler:
    def __init__(self, admin_cache: AdminCache, auto_responder_handler=None):
        self.admin_cache = admin_cache
        self.auto_responder_handler = auto_responder_handler
        self.last_received_private_messages = {}
        self.wizard_states = {}
        cfg = load_config()
        stored = {int(k): v for k, v in cfg.get("_pending_inputs", {}).items() if str(k).lstrip('-').isdigit() or isinstance(k, int)}
        self.pending_inputs = PersistentPendingInputs(self, stored)

    def _save_pending_inputs(self):
        try:
            cfg = load_config()
            cfg["_pending_inputs"] = {str(k): v for k, v in self.pending_inputs.items()}
            save_config(cfg)
        except Exception as e:
            logger.debug(f"Erro ao salvar _pending_inputs: {e}")

    async def _require_admin(self, update: Update) -> bool:
        chat = update.effective_chat
        user = update.effective_user
        if not chat or not user:
            return False
        if chat.type == "private":
            return True
        return await self.admin_cache.is_admin(chat, user.id)

    async def cmd_comunicado(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Inicia o Guia Interativo de Transmissão / Comunicado."""
        if not await self._require_admin(update):
            await update.effective_message.reply_text("⛔ Este comando é exclusivo para administradores.")
            return
        await self.start_wizard(update, context)

    def _get_or_create_wizard_state(self, user_id: int) -> dict:
        """Obtém o estado do assistente de transmissão de forma unificada e à prova de perda de dados."""
        st = self.wizard_states.get(user_id)
        if not st:
            st = {}
            self.wizard_states[user_id] = st

        # Sincroniza se pending_inputs tiver dados mais recentes ou texto salvo
        if user_id in self.pending_inputs:
            p = self.pending_inputs[user_id]
            if isinstance(p, dict):
                inner = p.get("state")
                if isinstance(inner, dict):
                    for k, v in inner.items():
                        if v is not None and v != "":
                            st[k] = v
                for k in ("text", "media_type", "media_id", "buttons", "pin", "target", "delay_seconds"):
                    if k in p and p[k] is not None and p[k] != "":
                        st[k] = p[k]
        return st

    def _save_wizard_state(self, user_id: int, state: dict, next_action: str = None):
        """Salva o estado do assistente de transmissão em memória e no pending_inputs simultaneamente."""
        self.wizard_states[user_id] = state
        if next_action:
            self.pending_inputs[user_id] = {
                "action": next_action,
                "state": state,
                "target": state.get("target"),
                "text": state.get("text", ""),
                "media_type": state.get("media_type"),
                "media_id": state.get("media_id"),
                "buttons": state.get("buttons", []),
                "pin": state.get("pin", False),
                "delay_seconds": state.get("delay_seconds", 2)
            }
            self._save_pending_inputs()

    async def start_wizard(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Abre o Passo 1 do Guia de Transmissão."""
        cfg = load_config()
        text, markup = generate_wizard_dest_menu(cfg)
        if update.callback_query:
            try:
                await update.callback_query.edit_message_text(text, reply_markup=markup, parse_mode=ParseMode.MARKDOWN)
            except Exception:
                await update.callback_query.edit_message_text(text, reply_markup=markup)
        elif update.effective_message:
            try:
                await update.effective_message.reply_text(text, reply_markup=markup, parse_mode=ParseMode.MARKDOWN)
            except Exception:
                await update.effective_message.reply_text(text, reply_markup=markup)

    async def show_wizard_preview(self, update: Update, context: ContextTypes.DEFAULT_TYPE, state: dict, user_id: int):
        """Envia a prévia idêntica de como a postagem ficará e os controles de envio."""
        cfg = load_config()
        bot = context.bot
        self._save_wizard_state(user_id, state)

        text = state.get("text", "")
        media_type = state.get("media_type")
        media_id = state.get("media_id")
        buttons = state.get("buttons", [])
        pin = state.get("pin", False)
        target = state.get("target", "main_channel")

        from modules.utils import build_rich_buttons_markup, smart_send_message, smart_send_photo, smart_send_video
        markup = build_rich_buttons_markup(buttons)

        # 1. Envia a prévia idêntica ao que será postado
        try:
            if media_type == "video" and media_id:
                await smart_send_video(bot, chat_id=user_id, video=media_id, caption=text, reply_markup=markup)
            elif media_type == "photo" and media_id:
                await smart_send_photo(bot, chat_id=user_id, photo=media_id, caption=text, reply_markup=markup)
            else:
                await smart_send_message(bot, chat_id=user_id, text=text or "📢 Comunicado Oficial", reply_markup=markup)
        except Exception as e_prev:
            logger.error(f"Erro ao gerar prévia da transmissão: {e_prev}")
            try:
                await bot.send_message(chat_id=user_id, text=f"⚠️ Falha ao exibir prévia formatada: {e_prev}")
            except Exception:
                pass

        # 2. Envia os controles de confirmação da transmissão
        dest_label = get_wizard_dest_label(target, cfg)
        media_label = "🎥 Vídeo" if media_type == "video" else ("🖼️ Foto" if media_type == "photo" else "⚪ Nenhuma (Somente Texto)")
        btns_count = sum(len(r) for r in buttons) if (buttons and isinstance(buttons[0], list)) else len(buttons)
        delay_sec = state.get("delay_seconds", 2)

        ctrl_text, ctrl_markup = generate_wizard_preview_controls(dest_label, media_label, btns_count, pin, delay_sec)
        try:
            await bot.send_message(chat_id=user_id, text=ctrl_text, reply_markup=ctrl_markup, parse_mode=ParseMode.MARKDOWN)
        except Exception:
            await bot.send_message(chat_id=user_id, text=ctrl_text, reply_markup=ctrl_markup)

    async def execute_wizard_send(self, update: Update, context: ContextTypes.DEFAULT_TYPE, user_id: int):
        """Dispara a transmissão para os chats selecionados com distribuição gradual e gera relatório detalhado."""
        state = self._get_or_create_wizard_state(user_id)
        if not state or (not state.get("text") and not state.get("media_id")):
            p = self.pending_inputs.get(user_id, {})
            if isinstance(p, dict):
                inner = p.get("state")
                if isinstance(inner, dict):
                    state.update(inner)
                for k in ("text", "media_type", "media_id", "buttons", "pin", "target", "delay_seconds"):
                    if k in p and p[k]:
                        state[k] = p[k]

        if not state:
            if update.callback_query:
                await update.callback_query.answer("⚠️ Nenhuma transmissão pendente encontrada.", show_alert=True)
            return

        cfg = load_config()
        bot = context.bot
        target = state.get("target", "main_channel")
        text = state.get("text", "")
        media_type = state.get("media_type")
        media_id = state.get("media_id")
        buttons = state.get("buttons", [])
        pin = state.get("pin", False)
        delay_sec = state.get("delay_seconds", 2)

        # Se texto estiver vazio mas não tem mídia, fallback para texto padrão
        if not text and not media_id:
            text = "📢 Comunicado Oficial"
            state["text"] = text

        targets = get_wizard_targets_list(target, cfg)
        if not targets:
            msg = update.effective_message
            if msg:
                await msg.reply_text("⚠️ Nenhum chat de destino encontrado para esse envio.")
            return

        if update.callback_query:
            try:
                await update.callback_query.edit_message_reply_markup(reply_markup=None)
            except Exception:
                pass

        from modules.utils import build_rich_buttons_markup, smart_send_message, smart_send_photo, smart_send_video
        import telegram.error
        markup = build_rich_buttons_markup(buttons)

        sent_count = 0
        fail_count = 0
        errors = []

        from config import normalize_chat_id
        all_chats_map = {}
        for x in cfg.get("linked_groups", []) + cfg.get("linked_channels", []):
            raw_id = x.get("id")
            norm_id = normalize_chat_id(raw_id)
            title = x.get("title") or f"Chat {norm_id}"
            all_chats_map[raw_id] = title
            all_chats_map[norm_id] = title
        all_chats_map[-1001806380183] = "HC Sibelius"
        delivered_names = []

        for i, raw_cid in enumerate(targets):
            if i > 0 and delay_sec > 0:
                await asyncio.sleep(delay_sec)

            cid = normalize_chat_id(raw_cid)
            if cid in (-1002071806380183, -2071806380183, 2071806380183):
                cid = -1001806380183
            c_title = all_chats_map.get(cid) or all_chats_map.get(raw_cid, str(cid))
            if "sibelius" in c_title.lower() or cid == -1001806380183:
                c_title = "HC Sibelius"
            logger.info(f"Transmitindo mensagem wizard para chat {cid} ({c_title})...")
            try:
                sent_msg = None
                if media_type == "video" and media_id:
                    sent_msg = await smart_send_video(bot, chat_id=cid, video=media_id, caption=text, reply_markup=markup)
                elif media_type == "photo" and media_id:
                    sent_msg = await smart_send_photo(bot, chat_id=cid, photo=media_id, caption=text, reply_markup=markup)
                else:
                    sent_msg = await smart_send_message(bot, chat_id=cid, text=text, reply_markup=markup)

                if sent_msg:
                    sent_count += 1
                    delivered_names.append(c_title)
                    logger.info(f"Sucesso ao entregar mensagem no chat {cid} ({c_title})")
                    if pin and hasattr(sent_msg, "pin"):
                        try:
                            await sent_msg.pin(disable_notification=False)
                        except Exception as e_pin:
                            logger.debug(f"Não foi possível fixar mensagem no chat {cid}: {e_pin}")
                    
                    real_id = getattr(getattr(sent_msg, "chat", None), "id", cid)
                    if real_id != raw_cid:
                        logger.info(f"Auto-corrigindo chat '{c_title}' de {raw_cid} para {real_id} no config!")
                        for g in cfg.get("linked_groups", []):
                            if g.get("id") == raw_cid:
                                g["id"] = real_id
                        for c in cfg.get("linked_channels", []):
                            if c.get("id") == raw_cid:
                                c["id"] = real_id
                        save_config(cfg)
                else:
                    fail_count += 1
                    errors.append(f"Chat {c_title} ({cid}): Falha no envio (sem confirmação do Telegram)")
                    logger.error(f"Falha ao enviar mensagem no chat {cid} ({c_title}): smart_send retornou None")
            except telegram.error.RetryAfter as e_retry:
                logger.warning(f"FloodWait de {e_retry.retry_after}s recebido no chat {cid} ({c_title}). Aguardando...")
                await asyncio.sleep(e_retry.retry_after + 1)
                try:
                    if media_type == "video" and media_id:
                        sent_msg = await smart_send_video(bot, chat_id=cid, video=media_id, caption=text, reply_markup=markup)
                    elif media_type == "photo" and media_id:
                        sent_msg = await smart_send_photo(bot, chat_id=cid, photo=media_id, caption=text, reply_markup=markup)
                    else:
                        sent_msg = await smart_send_message(bot, chat_id=cid, text=text, reply_markup=markup)
                    if sent_msg:
                        sent_count += 1
                        delivered_names.append(c_title)
                        logger.info(f"Sucesso ao entregar mensagem após retry no chat {cid} ({c_title})")
                        if pin and hasattr(sent_msg, "pin"):
                            try:
                                await sent_msg.pin(disable_notification=False)
                            except Exception:
                                pass
                except Exception as e_fail:
                    fail_count += 1
                    errors.append(f"Chat {c_title} ({cid}): {e_fail}")
                    logger.error(f"Erro ao entregar no chat {cid} ({c_title}) após retry: {e_fail}")
            except Exception as e_send:
                fail_count += 1
                errors.append(f"Chat {c_title} ({cid}): {e_send}")
                logger.error(f"Erro ao transmitir para chat {cid} ({c_title}): {e_send}")

        # Limpa o estado
        self.wizard_states.pop(user_id, None)
        if user_id in self.pending_inputs:
            del self.pending_inputs[user_id]
            self._save_pending_inputs()

        dest_label = get_wizard_dest_label(target, cfg)
        media_label = "🎥 Vídeo" if media_type == "video" else ("🖼️ Foto" if media_type == "photo" else "⚪ Texto")

        report = (
            "🎉 *TRANSMISSÃO CONCLUÍDA!*\n"
            "🎼 ══════════════════════ 🎼\n\n"
            f"• *Destino Escolhido:* `{dest_label}`\n"
            f"• *Sucesso:* `{sent_count}` chat(s)\n"
            f"• *Falhas:* `{fail_count}`\n"
            f"• *Distribuição:* `{delay_sec}s entre cada chat (Envio Suave 🌊)`\n"
            f"• *Fixado no Topo:* `{'Sim 📌' if pin else 'Não'}`\n"
            f"• *Mídia:* `{media_label}`\n\n"
        )
        if delivered_names:
            report += "📋 *Entregue com sucesso em:*\n" + "\n".join([f"  ✅ `{name}`" for name in delivered_names]) + "\n\n"

        if target in ("all", "all_channels", "main_channel") and not cfg.get("linked_channels"):
            report += "⚠️ *Aviso Importante:* O bot não possui canais vinculados no momento (`/canais`). Para conectar seu canal, use `/setcanal @seucanal`.\n\n"

        if errors:
            report += f"⚠️ *Detalhes das falhas:*\n" + "\n".join(errors[:3])

        final_markup = InlineKeyboardMarkup([
            [InlineKeyboardButton("📢 Nova Transmissão", callback_data="cfg:wiz:start")],
            [InlineKeyboardButton("🗓️ Ver Agendadas", callback_data="cfg:sched:list")],
            [InlineKeyboardButton("◀ Voltar ao Painel", callback_data="cfg:page:1")]
        ])

        try:
            await update.effective_message.reply_text(report, reply_markup=final_markup, parse_mode=ParseMode.MARKDOWN)
        except Exception:
            await update.effective_message.reply_text(report, reply_markup=final_markup)

        # Envia Log de Auditoria
        admin_user = update.effective_user
        if admin_user:
            adm_info = f"{admin_user.full_name} (@{admin_user.username})" if admin_user.username else admin_user.full_name
            import html
            await send_mod_log(
                bot=bot,
                event_type="say",
                title="Transmissão Guiada Realizada",
                user_info=f"Destino: <b>{html.escape(dest_label)}</b> ({sent_count} chats)",
                admin_info=f"<b>{html.escape(adm_info)}</b>",
                details=f"Fixado: {'Sim' if pin else 'Não'} | Mídia: {media_label} | Delay: {delay_sec}s"
            )

    async def cmd_agendados(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Exibe o menu de transmissões agendadas pendentes."""
        if not await self._require_admin(update):
            await update.effective_message.reply_text("⛔ Este comando é exclusivo para administradores.")
            return
        cfg = load_config()
        text, markup = generate_scheduled_transmissions_menu(cfg)
        try:
            await update.effective_message.reply_text(text, reply_markup=markup, parse_mode=ParseMode.MARKDOWN)
        except Exception:
            await update.effective_message.reply_text(text, reply_markup=markup)

    async def save_scheduled_transmission(self, update: Update, context: ContextTypes.DEFAULT_TYPE, state: dict, user_id: int, target_dt: datetime):
        """Salva a transmissão agendada no config.json e confirma para o administrador."""
        cfg = load_config()
        bot = context.bot
        target = state.get("target", "main_channel")
        text = state.get("text", "")
        media_type = state.get("media_type")
        media_id = state.get("media_id")
        buttons = state.get("buttons", [])
        pin = state.get("pin", False)
        delay_sec = state.get("delay_seconds", 2)
        dest_label = get_wizard_dest_label(target, cfg)
        targets = get_wizard_targets_list(target, cfg)

        user = update.effective_user
        admin_name = user.full_name if user else "Admin"

        item_id = int(time.time() * 1000)
        target_ts = target_dt.timestamp()
        display_str = target_dt.strftime("%d/%m/%Y às %H:%M")

        entry = {
            "id": item_id,
            "target": target,
            "text": text,
            "media_type": media_type,
            "media_id": media_id,
            "buttons": buttons,
            "pin": pin,
            "delay_seconds": delay_sec,
            "schedule_timestamp": target_ts,
            "schedule_display": display_str,
            "creator_id": user_id,
            "creator_name": admin_name,
            "status": "pending",
            "created_at": datetime.now().isoformat()
        }

        cfg.setdefault("scheduled_transmissions", []).append(entry)
        save_config(cfg)

        self.wizard_states.pop(user_id, None)
        if user_id in self.pending_inputs:
            del self.pending_inputs[user_id]
            self._save_pending_inputs()

        media_label = "🎥 Vídeo" if media_type == "video" else ("🖼️ Foto" if media_type == "photo" else "⚪ Texto")
        btns_count = sum(len(r) for r in buttons) if (buttons and isinstance(buttons[0], list)) else len(buttons)

        confirm_text = (
            "🗓️ *TRANSMISSÃO AGENDADA COM SUCESSO!*\n"
            "🎼 ══════════════════════ 🎼\n\n"
            f"• *Destino:* `{dest_label}` ({len(targets)} chats)\n"
            f"• ⏰ *Horário Programado:* `{display_str}`\n"
            f"• 🌊 *Distribuição:* `{delay_sec}s entre cada chat (Envio Suave)`\n"
            f"• 📌 *Fixar no Topo:* `{'Sim 📌' if pin else 'Não'}`\n"
            f"• 🖼️ *Mídia:* `{media_label}`\n"
            f"• 🔘 *Botões:* `{btns_count} configurado(s)`\n\n"
            "✅ O Maestro Bot efetuará o envio e a distribuição de forma 100% autônoma no horário agendado!\n"
            "Você receberá a confirmação completa aqui no seu privado assim que for disparada."
        )

        confirm_markup = InlineKeyboardMarkup([
            [InlineKeyboardButton("🗓️ Ver Agendadas", callback_data="cfg:sched:list")],
            [InlineKeyboardButton("📢 Nova Transmissão", callback_data="cfg:wiz:start")],
            [InlineKeyboardButton("◀ Voltar ao Painel", callback_data="cfg:page:1")]
        ])

        if update.callback_query:
            try:
                await update.callback_query.edit_message_text(confirm_text, reply_markup=confirm_markup, parse_mode=ParseMode.MARKDOWN)
            except Exception:
                await update.callback_query.edit_message_text(confirm_text, reply_markup=confirm_markup)
        elif update.effective_message:
            try:
                await update.effective_message.reply_text(confirm_text, reply_markup=confirm_markup, parse_mode=ParseMode.MARKDOWN)
            except Exception:
                await update.effective_message.reply_text(confirm_text, reply_markup=confirm_markup)

        # Log de Auditoria
        import html
        await send_mod_log(
            bot=bot,
            event_type="say",
            title="Transmissão Agendada Criada",
            user_info=f"Destino: <b>{html.escape(dest_label)}</b> ({len(targets)} chats)",
            admin_info=f"<b>{html.escape(admin_name)}</b>",
            details=f"Programado para: {display_str} | Delay: {delay_sec}s/chat"
        )

    async def cmd_config(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Envia o menu interativo de configurações."""
        chat = update.effective_chat
        if not await self._require_admin(update):
            await update.effective_message.reply_text("⛔ Este menu é exclusivo para administradores.")
            return

        cfg = load_config()
        title = chat.title or "Chat Privado"
        text, markup = generate_page_1(title, cfg)

        try:
            await update.effective_message.reply_text(
                text=text,
                reply_markup=markup,
                parse_mode=ParseMode.MARKDOWN
            )
        except Exception:
            await update.effective_message.reply_text(text=text, reply_markup=markup)

    async def cmd_cancelar(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Cancela qualquer edição pendente ou assistente de transmissão."""
        user = update.effective_user
        cancelled = False
        if user and user.id in self.wizard_states:
            self.wizard_states.pop(user.id, None)
            cancelled = True
        if user and user.id in self.pending_inputs:
            del self.pending_inputs[user.id]
            self._save_pending_inputs()
            cancelled = True
        if cancelled:
            await update.effective_message.reply_text("❌ Ação cancelada.")
        else:
            await update.effective_message.reply_text("Nenhuma ação pendente para cancelar.")

    async def _extract_message_content(self, msg, context: ContextTypes.DEFAULT_TYPE = None, user_id: int = None) -> tuple[str, str | None, list, int | None, int | None, int | None, int | None]:
        """
        Extrai o conteúdo de qualquer mensagem enviada ou encaminhada de forma 100% segura e instantânea:
        - raw_text: HTML formatado (msg.text_html, msg.caption_html, msg.text, msg.caption ou rich_message blocks)
        - photo_id: ID do arquivo de imagem se presente
        - extracted_buttons: Lista de linhas de botões (Inline Keyboard)
        - source_chat_id: ID do chat de onde a mensagem foi originada (canal ou chat privado)
        - source_message_id: ID da mensagem original
        - backup_chat_id: ID do chat privado como backup para copy_message
        - backup_message_id: ID da mensagem no chat privado como backup
        """
        raw_text = ""
        try:
            raw_text = msg.text_html or ""
        except Exception:
            pass
        if not raw_text:
            try:
                raw_text = msg.text or ""
            except Exception:
                pass
        if not raw_text:
            try:
                raw_text = msg.caption_html or ""
            except Exception:
                pass
        if not raw_text:
            try:
                raw_text = msg.caption or ""
            except Exception:
                pass

        photo_id = None
        try:
            if msg.photo:
                photo_id = msg.photo[-1].file_id
        except Exception:
            pass

        backup_chat_id = msg.chat.id if msg.chat else None
        backup_message_id = msg.message_id

        # 1. Detecta origem encaminhada (seja via novo forward_origin do Bot API 7.0+ ou forward_from_chat antigo)
        fwd_origin = getattr(msg, "forward_origin", None)
        fwd_chat_id = None
        fwd_msg_id = None
        try:
            if fwd_origin:
                c = getattr(fwd_origin, "chat", None)
                if c:
                    fwd_chat_id = c.id
                    fwd_msg_id = getattr(fwd_origin, "message_id", None)
            else:
                legacy_fwd = getattr(msg, "forward_from_chat", None)
                if legacy_fwd:
                    fwd_chat_id = getattr(legacy_fwd, "id", None)
                    fwd_msg_id = getattr(msg, "forward_from_message_id", None)
        except Exception:
            pass

        is_forwarded = bool(fwd_chat_id and fwd_msg_id and isinstance(fwd_chat_id, int) and fwd_chat_id < 0)
        source_chat_id = fwd_chat_id if is_forwarded else None
        source_message_id = fwd_msg_id if is_forwarded else None
        backup_chat_id = (msg.chat.id if msg.chat else None) if is_forwarded else None
        backup_message_id = msg.message_id if is_forwarded else None

        # 2. Se raw_text estiver vazio, tenta link_preview_options
        if not raw_text:
            try:
                lpo = getattr(msg, "link_preview_options", None)
                if lpo and getattr(lpo, "url", None):
                    raw_text = lpo.url
            except Exception:
                pass

        # 3. Se ainda assim estiver vazio, tenta extrair de blocos internos
        if not raw_text:
            try:
                d = msg.to_dict() if hasattr(msg, "to_dict") else {}
                rich = d.get("rich_message") or getattr(msg, "api_kwargs", {}).get("rich_message") or {}
                blocks = rich.get("blocks", [])
                texts = []
                for b in blocks:
                    if isinstance(b, dict):
                        if "text" in b:
                            texts.append(b["text"])
                        elif "caption" in b:
                            texts.append(b["caption"])
                if texts:
                    raw_text = "\n\n".join(texts)
            except Exception:
                pass

        # 4. Garante que raw_text nunca fique vazio
        if not raw_text:
            raw_text = "📢 Postagem da Comunidade"

        extracted_buttons = []

        # 5. Tenta obter botões diretamente do reply_markup da mensagem (se presente)
        try:
            if msg.reply_markup and getattr(msg.reply_markup, "inline_keyboard", None):
                for row in msg.reply_markup.inline_keyboard:
                    row_btns = []
                    for btn in row:
                        cb = getattr(btn, "callback_data", None)
                        if cb:
                            row_btns.append({"text": btn.text, "callback_data": cb})
                            continue
                        url = getattr(btn, "url", None)
                        if not url and getattr(btn, "web_app", None):
                            url = getattr(btn.web_app, "url", None)
                        if not url and getattr(btn, "login_url", None):
                            url = getattr(btn.login_url, "url", None)
                        if url:
                            row_btns.append({"text": btn.text, "url": url})
                    if row_btns:
                        extracted_buttons.append(row_btns)
        except Exception:
            pass

        # 6. Tenta extrair botões da sintaxe textual ([Texto - Link] ou [Texto](buttonurl:Link) ou Texto | Link)
        if not extracted_buttons and raw_text:
            try:
                parsed = self._parse_buttons(raw_text)
                if parsed:
                    extracted_buttons = parsed
                    lines = raw_text.split("\n")
                    clean_lines = [l for l in lines if not self._parse_buttons(l)]
                    raw_text = "\n".join(clean_lines).strip()
            except Exception:
                pass

        return raw_text, photo_id, extracted_buttons, source_chat_id, source_message_id, backup_chat_id, backup_message_id

    async def handle_pending_input(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
        """Intercepta entradas de administradores de forma resiliente, garantindo que o bot nunca fique mudo."""
        try:
            return await self._handle_pending_input_internal(update, context)
        except Exception as e:
            logger.error(f"Erro em handle_pending_input: {e}", exc_info=True)
            msg = update.effective_message
            if msg:
                try:
                    await msg.reply_text(
                        f"⚠️ Ocorreu um erro ao processar sua entrada: {e}\nPor favor envie novamente ou digite /cancelar."
                    )
                except Exception:
                    pass
            return True

    async def handle_unsolicited_private_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Oferece menu interativo quando o usuário envia mensagem no privado sem ação prévia."""
        msg = update.effective_message
        user = update.effective_user
        if not msg or not user:
            return

        try:
            raw_text, photo_id, extracted_buttons, src_chat_id, src_msg_id, bak_chat_id, bak_msg_id = await self._extract_message_content(msg, context, user.id)

            self.last_received_private_messages[user.id] = {
                "text": raw_text,
                "photo": photo_id,
                "buttons": extracted_buttons,
                "source_chat_id": src_chat_id,
                "source_message_id": src_msg_id,
                "backup_chat_id": bak_chat_id,
                "backup_message_id": bak_msg_id
            }

            kb = [
                [InlineKeyboardButton("⏱️ Salvar como Mensagem Programada #1", callback_data="cfg:quick_save_rec:1")],
                [InlineKeyboardButton("👋 Salvar como Boas-Vindas", callback_data="cfg:quick_save_welcome")],
                [InlineKeyboardButton("⚙️ Abrir Painel de Configurações", callback_data="cfg:page:1")]
            ]
            prompt = (
                "📥 *Postagem Recebida no Chat Privado!*\n\n"
                "Identifiquei o envio da sua mensagem com formato enriquecido / botões.\n"
                "👉 *Escolha abaixo o que deseja fazer com ela:*"
            )
            try:
                await msg.reply_text(prompt, reply_markup=InlineKeyboardMarkup(kb), parse_mode=ParseMode.MARKDOWN)
            except Exception:
                await msg.reply_text("📥 Postagem recebida! Escolha o que deseja fazer com ela:", reply_markup=InlineKeyboardMarkup(kb))
        except Exception as e_unsol:
            logger.error(f"Erro ao tratar mensagem privada não solicitada: {e_unsol}")

    async def _handle_pending_input_internal(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
        """Processamento interno das entradas pendentes."""
        user = update.effective_user
        msg = update.effective_message
        if not user or not msg or user.id not in self.pending_inputs:
            return False

        state = self.pending_inputs[user.id]
        action = state.get("action")
        cfg = load_config()

        # Cancelamento
        if msg.text and msg.text.strip().lower() in ("/cancelar", "cancelar"):
            del self.pending_inputs[user.id]
            await msg.reply_text("❌ Alteração cancelada.")
            return True

        # Whitelist & Links Permitidos (modules/whitelist.py)
        if await handle_whitelist_input(self, update, context):
            return True

        # -------------------------------------------------------------
        # 1. TEXTO / FOTO / BOTÕES DE BOAS-VINDAS (modules/welcome_ui.py)
        # -------------------------------------------------------------
        if action.startswith("welcome_"):
            return await handle_welcome_input(self, msg, context, user, state, action)

        # -------------------------------------------------------------
        # 2. TEXTO / FOTO / BOTÕES DE MENSAGEM REPETIDA (CRONOGRAMA)
        # -------------------------------------------------------------
        elif action == "rec_text":
            msg_id = state.get("msg_id", 1)
            raw_text, photo_id, extracted_buttons, src_chat_id, src_msg_id, bak_chat_id, bak_msg_id = await self._extract_message_content(msg, context, user.id)

            rec_list = cfg.setdefault("recurring_messages", [])
            target_item = next((m for m in rec_list if m.get("id") == msg_id), None)
            if not target_item:
                target_item = {
                    "id": msg_id,
                    "enabled": True,
                    "text": "📢 Postagem Programada",
                    "photo": None,
                    "buttons": [],
                    "repeat_mode": "interval",
                    "interval_type": "hours",
                    "interval_value": 24,
                    "interval_minutes": 1440,
                    "messages_interval": 50,
                    "messages_counter_last": 0,
                    "start_hour": None,
                    "start_minute": None,
                    "weekdays": [0, 1, 2, 3, 4, 5, 6],
                    "month_days": [],
                    "start_date": None,
                    "end_date": None,
                    "pin_message": False,
                    "delete_previous": False,
                    "auto_delete_seconds": 0,
                    "last_message_id": None,
                    "last_sent_timestamp": 0,
                    "chat_id": cfg.get("main_group_id")
                }
                rec_list.append(target_item)

            if raw_text:
                target_item["text"] = raw_text
            if photo_id:
                target_item["photo"] = photo_id
            if extracted_buttons:
                target_item["buttons"] = extracted_buttons
            if src_chat_id and src_msg_id and src_chat_id < 0:
                target_item["source_chat_id"] = src_chat_id
                target_item["source_message_id"] = src_msg_id
                target_item["backup_chat_id"] = bak_chat_id
                target_item["backup_message_id"] = bak_msg_id
            else:
                target_item.pop("source_chat_id", None)
                target_item.pop("source_message_id", None)
                target_item.pop("backup_chat_id", None)
                target_item.pop("backup_message_id", None)

            save_config(cfg)
            del self.pending_inputs[user.id]

            # Envia prévia visual da mensagem no chat privado
            try:
                await msg.reply_text("👁️ *Veja abaixo a prévia de como sua mensagem ficou:*", parse_mode=ParseMode.MARKDOWN)
                await send_single_recurring_message(context.bot, target_item, msg.chat.id, job_queue=context.job_queue)
            except Exception as e_pv:
                logger.warning(f"Erro ao exibir prévia no rec_text: {e_pv}")

            summary_items = ["• *Texto:* Salvo com sucesso"]
            if photo_id:
                summary_items.append("• *Foto:* Imagem salva")
            if extracted_buttons:
                total_btns = sum(len(r) for r in extracted_buttons)
                summary_items.append(f"• *Botões:* {total_btns} botão(ões) capturados")

            summary_str = "\n".join(summary_items)

            btns_exist = bool(target_item.get("buttons"))
            btn_action_label = "🔘 Alterar Botões com Links" if btns_exist else "🔘 Adicionar Botões com Links"
            photo_exist = bool(target_item.get("photo"))
            photo_action_label = "🖼️ Alterar Foto" if photo_exist else "🖼️ Adicionar Foto / Banner"

            markup = InlineKeyboardMarkup([
                [InlineKeyboardButton(btn_action_label, callback_data=f"cfg:rec:buttons:{msg_id}")],
                [
                    InlineKeyboardButton(photo_action_label, callback_data=f"cfg:rec:photo:{msg_id}"),
                    InlineKeyboardButton("🎯 Canal de Destino", callback_data=f"cfg:rec:target_help:{msg_id}")
                ],
                [
                    InlineKeyboardButton("⏰ Horário de Envio", callback_data=f"cfg:rec:hour_menu:{msg_id}"),
                    InlineKeyboardButton("👀 Ver Prévia", callback_data=f"cfg:rec:preview:{msg_id}")
                ],
                [
                    InlineKeyboardButton("⚙️ Menu Completo", callback_data=f"cfg:rec:detail:{msg_id}"),
                    InlineKeyboardButton("📋 Lista de Mensagens", callback_data="cfg:rec:list")
                ]
            ])
            confirm_msg = (
                f"✅ *Texto da Mensagem #{msg_id} salvo com sucesso!*\n\n{summary_str}\n\n"
                "👉 *Próximo passo:* Para adicionar botões com links (ex: canais/grupos), clique no botão abaixo:"
            )
            try:
                await msg.reply_text(
                    confirm_msg,
                    parse_mode=ParseMode.MARKDOWN,
                    reply_markup=markup
                )
            except Exception:
                await msg.reply_text(
                    confirm_msg.replace("*", "").replace("•", "-"),
                    reply_markup=markup
                )
            return True

        elif action == "rec_photo":
            msg_id = state.get("msg_id", 1)
            if not msg.photo:
                await msg.reply_text("⚠️ Envie uma imagem válida ou digite /cancelar.")
                return True

            file_id = msg.photo[-1].file_id
            rec_list = cfg.setdefault("recurring_messages", [])
            target_item = next((m for m in rec_list if m.get("id") == msg_id), None)
            if not target_item:
                target_item = {
                    "id": msg_id,
                    "enabled": True,
                    "text": "📢 Postagem Programada",
                    "photo": file_id,
                    "buttons": [],
                    "repeat_mode": "interval",
                    "interval_type": "hours",
                    "interval_value": 24,
                    "interval_minutes": 1440,
                    "messages_interval": 50,
                    "messages_counter_last": 0,
                    "start_hour": None,
                    "start_minute": None,
                    "weekdays": [0, 1, 2, 3, 4, 5, 6],
                    "month_days": [],
                    "start_date": None,
                    "end_date": None,
                    "pin_message": False,
                    "delete_previous": False,
                    "auto_delete_seconds": 0,
                    "last_message_id": None,
                    "last_sent_timestamp": 0,
                    "chat_id": cfg.get("main_group_id")
                }
                rec_list.append(target_item)
            else:
                target_item["photo"] = file_id

            target_item.pop("source_chat_id", None)
            target_item.pop("source_message_id", None)
            target_item.pop("backup_chat_id", None)
            target_item.pop("backup_message_id", None)

            save_config(cfg)
            del self.pending_inputs[user.id]

            try:
                await msg.reply_text("👁️ *Veja abaixo a prévia com a nova foto:*", parse_mode=ParseMode.MARKDOWN)
                await send_single_recurring_message(context.bot, target_item, msg.chat.id, job_queue=context.job_queue)
            except Exception as e_pv:
                logger.warning(f"Erro ao exibir prévia no rec_photo: {e_pv}")

            btns_exist = bool(target_item.get("buttons"))
            btn_action_label = "🔘 Alterar Botões" if btns_exist else "🔘 Adicionar Botões com Links"

            markup = InlineKeyboardMarkup([
                [InlineKeyboardButton(btn_action_label, callback_data=f"cfg:rec:buttons:{msg_id}")],
                [
                    InlineKeyboardButton("🎯 Canal de Destino", callback_data=f"cfg:rec:target_help:{msg_id}"),
                    InlineKeyboardButton("⏰ Horário de Envio", callback_data=f"cfg:rec:hour_menu:{msg_id}")
                ],
                [
                    InlineKeyboardButton("✏️ Editar Texto", callback_data=f"cfg:rec:text:{msg_id}"),
                    InlineKeyboardButton("👀 Ver Prévia", callback_data=f"cfg:rec:preview:{msg_id}")
                ],
                [
                    InlineKeyboardButton("⚙️ Menu Completo", callback_data=f"cfg:rec:detail:{msg_id}"),
                    InlineKeyboardButton("📋 Lista de Mensagens", callback_data="cfg:rec:list")
                ]
            ])
            try:
                await msg.reply_text(f"✅ *Foto da mensagem #{msg_id} atualizada com sucesso!*\n\n👉 Escolha o próximo passo abaixo:", parse_mode=ParseMode.MARKDOWN, reply_markup=markup)
            except Exception:
                await msg.reply_text(f"✅ Foto da mensagem #{msg_id} atualizada com sucesso!", reply_markup=markup)
            return True

        elif action == "rec_buttons":
            msg_id = state.get("msg_id", 1)
            raw_text, photo_id, extracted_buttons, src_chat_id, src_msg_id, bak_chat_id, bak_msg_id = await self._extract_message_content(msg, context, user.id)

            rec_list = cfg.setdefault("recurring_messages", [])
            target_item = next((m for m in rec_list if m.get("id") == msg_id), None)
            if not target_item:
                target_item = {
                    "id": msg_id,
                    "enabled": True,
                    "text": "📢 Postagem Programada",
                    "photo": None,
                    "buttons": [],
                    "repeat_mode": "interval",
                    "interval_type": "hours",
                    "interval_value": 24,
                    "interval_minutes": 1440,
                    "messages_interval": 50,
                    "messages_counter_last": 0,
                    "start_hour": None,
                    "start_minute": None,
                    "weekdays": [0, 1, 2, 3, 4, 5, 6],
                    "month_days": [],
                    "start_date": None,
                    "end_date": None,
                    "pin_message": False,
                    "delete_previous": False,
                    "auto_delete_seconds": 0,
                    "last_message_id": None,
                    "last_sent_timestamp": 0,
                    "chat_id": cfg.get("main_group_id")
                }
                rec_list.append(target_item)

            if raw_text and raw_text.strip().lower() in ("remover", "apagar", "nenhum"):
                target_item["buttons"] = []
                target_item.pop("source_chat_id", None)
                target_item.pop("source_message_id", None)
                target_item.pop("backup_chat_id", None)
                target_item.pop("backup_message_id", None)
                save_config(cfg)
                del self.pending_inputs[user.id]
                markup = InlineKeyboardMarkup([
                    [InlineKeyboardButton("⚙️ Voltar à Mensagem", callback_data=f"cfg:rec:detail:{msg_id}")],
                    [InlineKeyboardButton("📋 Lista de Mensagens", callback_data="cfg:rec:list")]
                ])
                await msg.reply_text(f"✅ *Botões da mensagem #{msg_id} removidos!*", parse_mode=ParseMode.MARKDOWN, reply_markup=markup)
                return True

            if extracted_buttons:
                target_item["buttons"] = extracted_buttons
                target_item.pop("source_chat_id", None)
                target_item.pop("source_message_id", None)
                target_item.pop("backup_chat_id", None)
                target_item.pop("backup_message_id", None)
            elif src_chat_id and src_msg_id and src_chat_id < 0:
                target_item["source_chat_id"] = src_chat_id
                target_item["source_message_id"] = src_msg_id
                target_item["backup_chat_id"] = bak_chat_id
                target_item["backup_message_id"] = bak_msg_id
            else:
                await msg.reply_text("⚠️ Nenhum botão detectado. Envie os botões no formato:\n`Texto do Botão | https://link.com`\n\nOu digite /cancelar.")
                return True

            save_config(cfg)
            del self.pending_inputs[user.id]

            # Envia prévia visual da mensagem no chat privado
            try:
                await msg.reply_text("👁️ *Veja abaixo como sua mensagem ficou com os botões:*", parse_mode=ParseMode.MARKDOWN)
                await send_single_recurring_message(context.bot, target_item, msg.chat.id, job_queue=context.job_queue)
            except Exception as e_pv:
                logger.warning(f"Erro ao exibir prévia no rec_buttons: {e_pv}")

            total_btns = sum(len(r) for r in extracted_buttons) if extracted_buttons else 0
            photo_exist = bool(target_item.get("photo"))
            photo_action_label = "🖼️ Alterar Foto" if photo_exist else "🖼️ Adicionar Foto / Banner"

            markup = InlineKeyboardMarkup([
                [
                    InlineKeyboardButton("🎯 Canal de Destino", callback_data=f"cfg:rec:target_help:{msg_id}"),
                    InlineKeyboardButton("⏰ Horário de Envio", callback_data=f"cfg:rec:hour_menu:{msg_id}")
                ],
                [
                    InlineKeyboardButton(photo_action_label, callback_data=f"cfg:rec:photo:{msg_id}"),
                    InlineKeyboardButton("✏️ Editar Texto", callback_data=f"cfg:rec:text:{msg_id}")
                ],
                [
                    InlineKeyboardButton("📋 Duplicar para outro canal", callback_data=f"cfg:rec:clone:{msg_id}"),
                    InlineKeyboardButton("👀 Ver Prévia", callback_data=f"cfg:rec:preview:{msg_id}")
                ],
                [
                    InlineKeyboardButton("⚙️ Menu Completo", callback_data=f"cfg:rec:detail:{msg_id}"),
                    InlineKeyboardButton("📋 Lista de Mensagens", callback_data="cfg:rec:list")
                ]
            ])
            reply_txt = f"✅ *{total_btns} botão(ões) em {len(extracted_buttons)} linha(s) configurados com sucesso na mensagem #{msg_id}!*"
            try:
                await msg.reply_text(reply_txt, parse_mode=ParseMode.MARKDOWN, reply_markup=markup)
            except Exception:
                await msg.reply_text(reply_txt.replace("*", ""), reply_markup=markup)
            return True

        elif action == "rec_title":
            msg_id = state.get("msg_id", 1)
            val = (msg.text or "").strip()
            if not val:
                await msg.reply_text("⚠️ Envie um texto válido para o nome ou /cancelar.")
                return True
            rec_list = cfg.setdefault("recurring_messages", [])
            target_item = next((m for m in rec_list if m.get("id") == msg_id), None)
            if target_item:
                if val.lower() in ("limpar", "padrao", "padrão", "remover"):
                    target_item.pop("title", None)
                else:
                    target_item["title"] = val
                save_config(cfg)
            del self.pending_inputs[user.id]

            new_title = get_recurring_title(target_item) if target_item else val
            markup = InlineKeyboardMarkup([
                [InlineKeyboardButton("⚙️ Voltar à Mensagem", callback_data=f"cfg:rec:detail:{msg_id}")],
                [InlineKeyboardButton("📋 Lista de Mensagens", callback_data="cfg:rec:list")]
            ])
            await msg.reply_text(
                f"✅ *Nome da Mensagem #{msg_id} atualizado para:* `{new_title}`",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=markup
            )
            return True

        elif action == "rec_article":
            msg_id = state.get("msg_id")
            if not msg.text:
                await msg.reply_text("⚠️ Envie um link válido ou digite /cancelar.")
                return True

            val = msg.text.strip()
            rec_list = cfg.get("recurring_messages", [])
            for item in rec_list:
                if item.get("id") == msg_id:
                    if val.lower() in ("remover", "apagar", "nenhum", "off"):
                        item["article_url"] = None
                    else:
                        if not (val.startswith("http://") or val.startswith("https://") or val.startswith("t.me/")):
                            val = "https://" + val
                        item["article_url"] = val
                    break
            save_config(cfg)
            del self.pending_inputs[user.id]

            markup = InlineKeyboardMarkup([
                [InlineKeyboardButton("⚙️ Voltar à Mensagem", callback_data=f"cfg:rec:detail:{msg_id}")],
                [InlineKeyboardButton("📋 Lista de Mensagens", callback_data="cfg:rec:list")]
            ])
            msg_txt = "✅ *Artigo removido com sucesso!*" if val.lower() in ("remover", "apagar", "nenhum", "off") else f"✅ *Artigo da Mensagem #{msg_id} salvo com sucesso!*\nLink: `{val}`\n\nA prévia do artigo será exibida no topo do envio!"
            await msg.reply_text(msg_txt, parse_mode=ParseMode.MARKDOWN, reply_markup=markup)
            return True

        elif action == "rec_msg_cnt":
            msg_id = state.get("msg_id")
            if not msg.text or not msg.text.strip().isdigit():
                await msg.reply_text("⚠️ Por favor, digite um número inteiro de mensagens (ex: 50) ou /cancelar.")
                return True
            cnt = int(msg.text.strip())
            if cnt <= 0:
                await msg.reply_text("⚠️ O número de mensagens deve ser maior que 0.")
                return True
            rec_list = cfg.get("recurring_messages", [])
            for item in rec_list:
                if item.get("id") == msg_id:
                    item["repeat_mode"] = "messages"
                    item["messages_interval"] = cnt
                    break
            save_config(cfg)
            del self.pending_inputs[user.id]
            text, markup = generate_recurring_msg_menu(cfg, msg_id)
            await msg.reply_text(f"✅ Repetição definida para a cada *{cnt} mensagens*!", parse_mode=ParseMode.MARKDOWN, reply_markup=markup)
            return True

        elif action in ("rec_dstart", "rec_dend"):
            msg_id = state.get("msg_id")
            field = "start_date" if action == "rec_dstart" else "end_date"
            raw = msg.text.strip()
            date_val = None
            try:
                if "/" in raw:
                    parts = raw.split("/")
                    if len(parts) == 3:
                        d, m, y = int(parts[0]), int(parts[1]), int(parts[2])
                        date_val = f"{y:04d}-{m:02d}-{d:02d}"
                elif "-" in raw:
                    parts = raw.split("-")
                    if len(parts) == 3:
                        y, m, d = int(parts[0]), int(parts[1]), int(parts[2])
                        date_val = f"{y:04d}-{m:02d}-{d:02d}"
            except Exception:
                pass

            if not date_val:
                await msg.reply_text("⚠️ Formato de data inválido. Use DD/MM/AAAA (ex: 25/12/2026) ou digite /cancelar.")
                return True

            rec_list = cfg.get("recurring_messages", [])
            for item in rec_list:
                if item.get("id") == msg_id:
                    item[field] = date_val
                    break
            save_config(cfg)
            del self.pending_inputs[user.id]
            title = "Data de Início" if field == "start_date" else "Data Final"
            text, markup = generate_recurring_detail(cfg, msg_id)
            await msg.reply_text(f"✅ *{title}* definida para `{date_val}`!", parse_mode=ParseMode.MARKDOWN, reply_markup=markup)
            return True

        # -------------------------------------------------------------
        # 3. ADICIONAR / REMOVER PALAVRAS PROIBIDAS
        # -------------------------------------------------------------
        elif action == "banned_add":
            if not msg.text:
                await msg.reply_text("⚠️ Envie as palavras separadas por vírgula ou /cancelar.")
                return True

            raw = msg.text.replace("\n", ",")
            new_items = [w.strip().lower() for w in raw.split(",") if w.strip()]
            if not new_items:
                await msg.reply_text("⚠️ Nenhuma palavra válida detectada. Digite /cancelar para desistir.")
                return True

            current = cfg.setdefault("antispam", {}).setdefault("banned_words", [])
            added_count = 0
            for w in new_items:
                if w not in current:
                    current.append(w)
                    added_count += 1

            save_config(cfg)
            del self.pending_inputs[user.id]

            markup = InlineKeyboardMarkup([
                [InlineKeyboardButton("🔤 Voltar a Palavras Proibidas", callback_data="cfg:sub:banned")]
            ])
            await msg.reply_text(
                f"✅ *{added_count} nova(s) palavra(s) adicionada(s) à lista negra com sucesso!*",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=markup
            )
            return True

        elif action == "banned_remove":
            if not msg.text:
                await msg.reply_text("⚠️ Envie as palavras a remover ou /cancelar.")
                return True

            raw = msg.text.replace("\n", ",")
            to_remove = [w.strip().lower() for w in raw.split(",") if w.strip()]
            current = cfg.setdefault("antispam", {}).setdefault("banned_words", [])

            removed_count = 0
            for w in to_remove:
                if w in current:
                    current.remove(w)
                    removed_count += 1

            save_config(cfg)
            del self.pending_inputs[user.id]

            markup = InlineKeyboardMarkup([
                [InlineKeyboardButton("🔤 Voltar a Palavras Proibidas", callback_data="cfg:sub:banned")]
            ])
            await msg.reply_text(
                f"✅ *{removed_count} palavra(s) removida(s) da lista negra!*",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=markup
            )
            return True

        # -------------------------------------------------------------
        # 4. CONFIGURAÇÃO DE RESPOSTAS AUTOMÁTICAS (REGEX & PALAVRAS)
        # -------------------------------------------------------------
        elif action == "resp_edit_text":
            item_id = state.get("item_id")
            raw_text, photo_id, extracted_buttons, src_chat_id, src_msg_id, bak_chat_id, bak_msg_id = await self._extract_message_content(msg, context, user.id)

            responders = cfg.setdefault("auto_responses", [])
            for item in responders:
                if item.get("id") == item_id:
                    if raw_text:
                        item["text"] = raw_text
                    if photo_id:
                        item["photo"] = photo_id
                    if extracted_buttons:
                        item["buttons"] = extracted_buttons
                    break
            save_config(cfg)
            if self.auto_responder_handler:
                self.auto_responder_handler.invalidate_cache(item_id)
            del self.pending_inputs[user.id]

            summary_items = ["• *Texto:* Atualizado com formatação rica"]
            if photo_id:
                summary_items.append("• *Foto:* Imagem salva com sucesso")
            if extracted_buttons:
                total_btns = sum(len(r) for r in extracted_buttons)
                summary_items.append(f"• *Botões:* {total_btns} botão(ões) capturados!")

            summary_str = "\n".join(summary_items)
            markup = InlineKeyboardMarkup([
                [InlineKeyboardButton("⚙️ Voltar à Resposta", callback_data=f"cfg:resp:detail:{item_id}")],
                [InlineKeyboardButton("📋 Lista de Respostas", callback_data="cfg:resp:list")]
            ])
            await msg.reply_text(f"✅ *Resposta #{item_id} atualizada com sucesso!*\n\n{summary_str}", parse_mode=ParseMode.MARKDOWN, reply_markup=markup)
            return True

        elif action == "resp_edit_pattern":
            item_id = state.get("item_id")
            if not msg.text:
                await msg.reply_text("⚠️ Envie o gatilho/expressão ou /cancelar.")
                return True

            new_pat = msg.text.strip()
            responders = cfg.setdefault("auto_responses", [])
            target = next((r for r in responders if r.get("id") == item_id), None)
            if target and target.get("is_regex", True):
                valid, err = validate_regex(new_pat)
                if not valid:
                    await msg.reply_text(
                        f"❌ *Expressão Regular (Regex) Inválida!*\n\nErro: `{err}`\n\n"
                        "💡 *Dicas de sintaxe:*\n"
                        "• Para palavras exatas: `(?i)\\b(pix|chave)\\b`\n"
                        "• Para alternativas: `(?i)ajuda|suporte|duvida`\n\n"
                        "Envie a regex corrigida ou digite /cancelar:",
                        parse_mode=ParseMode.MARKDOWN
                    )
                    return True

            if target:
                target["pattern"] = new_pat
            save_config(cfg)
            if self.auto_responder_handler:
                self.auto_responder_handler.invalidate_cache(item_id)
            del self.pending_inputs[user.id]

            markup = InlineKeyboardMarkup([
                [InlineKeyboardButton("⚙️ Voltar à Resposta", callback_data=f"cfg:resp:detail:{item_id}")],
                [InlineKeyboardButton("📋 Lista de Respostas", callback_data="cfg:resp:list")]
            ])
            await msg.reply_text(f"✅ *Gatilho da resposta #{item_id} atualizado para:* `{new_pat}`", parse_mode=ParseMode.MARKDOWN, reply_markup=markup)
            return True

        elif action == "resp_edit_title":
            item_id = state.get("item_id")
            if not msg.text:
                await msg.reply_text("⚠️ Envie um título ou /cancelar.")
                return True

            new_title = msg.text.strip()
            responders = cfg.setdefault("auto_responses", [])
            for item in responders:
                if item.get("id") == item_id:
                    item["title"] = new_title
                    break
            save_config(cfg)
            del self.pending_inputs[user.id]

            markup = InlineKeyboardMarkup([
                [InlineKeyboardButton("⚙️ Voltar à Resposta", callback_data=f"cfg:resp:detail:{item_id}")],
                [InlineKeyboardButton("📋 Lista de Respostas", callback_data="cfg:resp:list")]
            ])
            await msg.reply_text(f"✅ *Título alterado para:* `{new_title}`", parse_mode=ParseMode.MARKDOWN, reply_markup=markup)
            return True

        elif action == "resp_edit_photo":
            item_id = state.get("item_id")
            if not msg.photo:
                await msg.reply_text("⚠️ Por favor envie uma FOTO/IMAGEM ou digite /cancelar.")
                return True

            file_id = msg.photo[-1].file_id
            responders = cfg.setdefault("auto_responses", [])
            for item in responders:
                if item.get("id") == item_id:
                    item["photo"] = file_id
                    break
            save_config(cfg)
            del self.pending_inputs[user.id]

            markup = InlineKeyboardMarkup([
                [InlineKeyboardButton("⚙️ Voltar à Resposta", callback_data=f"cfg:resp:detail:{item_id}")],
                [InlineKeyboardButton("📋 Lista de Respostas", callback_data="cfg:resp:list")]
            ])
            await msg.reply_text(f"✅ *Foto da resposta #{item_id} configurada com sucesso!*", parse_mode=ParseMode.MARKDOWN, reply_markup=markup)
            return True

        elif action == "resp_edit_buttons":
            item_id = state.get("item_id")
            if not msg.text:
                await msg.reply_text("⚠️ Envie os botões ou /cancelar.")
                return True

            if msg.text.strip().lower() in ("remover", "limpar", "nenhum"):
                responders = cfg.setdefault("auto_responses", [])
                for item in responders:
                    if item.get("id") == item_id:
                        item["buttons"] = []
                        break
                save_config(cfg)
                del self.pending_inputs[user.id]
                markup = InlineKeyboardMarkup([[InlineKeyboardButton("⚙️ Voltar", callback_data=f"cfg:resp:detail:{item_id}")]])
                await msg.reply_text(f"✅ *Botões removidos da resposta #{item_id}!*", parse_mode=ParseMode.MARKDOWN, reply_markup=markup)
                return True

            new_buttons = self._parse_buttons(msg.text)
            if not new_buttons:
                await msg.reply_text("⚠️ Nenhum botão válido detectado.\nEnvie no formato: `Texto | https://link.com` ou /cancelar.", parse_mode=ParseMode.MARKDOWN)
                return True

            responders = cfg.setdefault("auto_responses", [])
            for item in responders:
                if item.get("id") == item_id:
                    item["buttons"] = new_buttons
                    break
            save_config(cfg)
            del self.pending_inputs[user.id]

            markup = InlineKeyboardMarkup([
                [InlineKeyboardButton("⚙️ Voltar à Resposta", callback_data=f"cfg:resp:detail:{item_id}")],
                [InlineKeyboardButton("📋 Lista de Respostas", callback_data="cfg:resp:list")]
            ])
            await msg.reply_text(f"✅ *{len(new_buttons)} botão(ões) configurado(s) na resposta #{item_id}!*", parse_mode=ParseMode.MARKDOWN, reply_markup=markup)
            return True

        # -------------------------------------------------------------
        # 5. CONFIGURAÇÃO DE CANAL DE LOGS
        # -------------------------------------------------------------
        elif action == "logs_set_id":
            if not msg.text:
                await msg.reply_text("⚠️ Envie o ID do canal ou /cancelar.")
                return True

            val = msg.text.strip()
            if val.lower() in ("desativar", "off", "remover"):
                cfg["log_channel_id"] = None
                save_config(cfg)
                del self.pending_inputs[user.id]
                markup = InlineKeyboardMarkup([[InlineKeyboardButton("📡 Voltar ao Menu de Logs", callback_data="cfg:sub:logs")]])
                await msg.reply_text("✅ *Canal de logs desativado!*", parse_mode=ParseMode.MARKDOWN, reply_markup=markup)
                return True

            try:
                channel_id = int(val)
                await context.bot.send_message(
                    chat_id=channel_id,
                    text="📡 *Canal de Logs Conectado via Painel!*\nRegistro de auditoria ativado com sucesso.",
                    parse_mode=ParseMode.MARKDOWN
                )
                cfg["log_channel_id"] = channel_id
                save_config(cfg)
                del self.pending_inputs[user.id]
                markup = InlineKeyboardMarkup([[InlineKeyboardButton("📡 Voltar ao Menu de Logs", callback_data="cfg:sub:logs")]])
                await msg.reply_text(f"✅ *Canal de logs conectado com sucesso!* (ID: `{channel_id}`)\nMensagem de teste enviada.", parse_mode=ParseMode.MARKDOWN, reply_markup=markup)
                return True
            except Exception as e:
                await msg.reply_text(
                    f"❌ *Erro ao conectar ao canal:* `{e}`\n\n"
                    "Certifique-se de que o bot foi adicionado como **Administrador** no canal e reenvie o ID ou digite /cancelar:",
                    parse_mode=ParseMode.MARKDOWN
                )
                return True

        # -------------------------------------------------------------
        # 6. CONFIGURAÇÃO DE TEMPO DE AUTO-APAGAR BOAS-VINDAS
        # -------------------------------------------------------------
        elif action == "welcome_autodel_time":
            target_gid = str(state.get("group_id", "general"))
            val_text = (msg.text or "").strip()
            sec = parse_time_string_to_seconds(val_text)

            if sec is None:
                await msg.reply_text(
                    "⚠️ *Tempo inválido!*\n\n"
                    "Envie um tempo entre *1 minuto (60s)* e *24 horas (86400s)*, ou `nunca` para desativar.\n\n"
                    "💡 *Exemplos válidos:*\n"
                    "• `5m` ou `5 min` ou `5` (5 minutos)\n"
                    "• `10m` ou `15m` ou `30m`\n"
                    "• `1h` ou `2h` ou `24h`\n"
                    "• `nunca` ou `0` (não apagar)\n\n"
                    "Tente novamente ou envie /cancelar:",
                    parse_mode=ParseMode.MARKDOWN
                )
                return True

            if target_gid in ("general", "0", ""):
                cfg.setdefault("welcome", {})["delete_welcome_after_seconds"] = sec
                ret_cb = "cfg:sub:wtime:general"
            else:
                from config import get_welcome_for_chat
                w_grp = cfg.setdefault("group_welcomes", {}).setdefault(target_gid, dict(get_welcome_for_chat(cfg, target_gid)))
                w_grp["delete_welcome_after_seconds"] = sec
                ret_cb = f"cfg:sub:wtime:{target_gid}"

            save_config(cfg)
            del self.pending_inputs[user.id]

            lbl = format_time_label(sec)
            desc = "nunca apagar (fica visível para sempre)" if sec == 0 else f"apagar após {lbl} ({sec}s)"
            markup = InlineKeyboardMarkup([
                [InlineKeyboardButton("⏱️ Voltar ao Menu de Tempo", callback_data=ret_cb)],
                [InlineKeyboardButton("💬 Voltar às Boas-Vindas", callback_data=f"cfg:welcome:cfg:{target_gid}")]
            ])
            await msg.reply_text(
                f"✅ *Tempo de auto-apagar atualizado com sucesso!*\nNovo tempo: *{desc}*.",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=markup
            )
            return True

        # -------------------------------------------------------------
        # 7. CONFIGURAÇÃO DE FUSO HORÁRIO PERSONALIZADO
        # -------------------------------------------------------------
        elif action == "custom_timezone":
            val_text = (msg.text or "").strip()
            from config import set_timezone
            success = set_timezone(cfg, val_text)
            if not success:
                await msg.reply_text(
                    "❌ *Fuso horário inválido!*\n\n"
                    "O fuso deve seguir o padrão IANA oficial (ex: `America/Sao_Paulo`, `America/Manaus`, `America/Fortaleza`, `America/Cuiaba`, `Europe/Lisbon`, `UTC`).\n\n"
                    "Por favor, verifique o nome e tente novamente ou envie /cancelar:",
                    parse_mode=ParseMode.MARKDOWN
                )
                return True

            del self.pending_inputs[user.id]
            from config import get_timezone_label
            markup = InlineKeyboardMarkup([
                [InlineKeyboardButton("🕒 Voltar ao Menu de Fuso", callback_data="cfg:sub:timezone")],
                [InlineKeyboardButton("◀ Voltar ao Painel Avançado", callback_data="cfg:page:2")]
            ])
            await msg.reply_text(
                f"✅ *Fuso horário alterado com sucesso para:* `{get_timezone_label(cfg)}`!",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=markup
            )
            return True

        # -------------------------------------------------------------
        # 7. ASSISTENTE DE TRANSMISSÃO GUIADA (WIZARD)
        # -------------------------------------------------------------
        elif action == "wiz_text":
            wiz_state = self._get_or_create_wizard_state(user.id)
            raw_text, photo_id, extracted_buttons, src_chat_id, src_msg_id, bak_chat_id, bak_msg_id = await self._extract_message_content(msg, context, user.id)
            video_id = msg.video.file_id if msg.video else None

            if not raw_text and not photo_id and not video_id:
                await msg.reply_text("⚠️ Por favor envie o texto do seu comunicado (ou uma foto/vídeo com legenda).")
                return True

            wiz_state["text"] = raw_text or ""
            if photo_id:
                wiz_state["media_type"] = "photo"
                wiz_state["media_id"] = photo_id
            elif video_id:
                wiz_state["media_type"] = "video"
                wiz_state["media_id"] = video_id

            if extracted_buttons:
                wiz_state["buttons"] = extracted_buttons

            dest_label = get_wizard_dest_label(wiz_state.get("target", "main_channel"), cfg)

            # Se já forneceu mídia e botões juntos na mensagem:
            if wiz_state.get("media_type") and wiz_state.get("buttons"):
                del self.pending_inputs[user.id]
                self._save_wizard_state(user.id, wiz_state)
                await self.show_wizard_preview(update, context, wiz_state, user.id)
                return True
            # Se forneceu mídia mas não botões:
            elif wiz_state.get("media_type"):
                wiz_state["step"] = "buttons"
                self._save_wizard_state(user.id, wiz_state, next_action="wiz_buttons")
                media_label = "🖼️ Foto" if wiz_state["media_type"] == "photo" else "🎥 Vídeo"
                p_text, p_markup = generate_wizard_buttons_prompt(dest_label, media_label)
                await msg.reply_text(p_text, reply_markup=p_markup, parse_mode=ParseMode.MARKDOWN)
                return True
            # Se não forneceu mídia: avança para o Passo 3 (Mídia)
            else:
                wiz_state["step"] = "media"
                self._save_wizard_state(user.id, wiz_state, next_action="wiz_media")
                p_text, p_markup = generate_wizard_media_prompt(dest_label, wiz_state["text"])
                await msg.reply_text(p_text, reply_markup=p_markup, parse_mode=ParseMode.MARKDOWN)
                return True

        elif action == "wiz_media":
            wiz_state = self._get_or_create_wizard_state(user.id)
            dest_label = get_wizard_dest_label(wiz_state.get("target", "main_channel"), cfg)

            if msg.photo:
                wiz_state["media_type"] = "photo"
                wiz_state["media_id"] = msg.photo[-1].file_id
            elif msg.video:
                wiz_state["media_type"] = "video"
                wiz_state["media_id"] = msg.video.file_id
            else:
                p_text, p_markup = generate_wizard_media_prompt(dest_label, wiz_state.get("text", ""))
                await msg.reply_text("⚠️ Envie uma **Foto** ou **Vídeo**, ou clique em **Pular Mídia** no botão abaixo:", reply_markup=p_markup, parse_mode=ParseMode.MARKDOWN)
                return True

            if wiz_state.get("buttons"):
                del self.pending_inputs[user.id]
                self._save_wizard_state(user.id, wiz_state)
                await self.show_wizard_preview(update, context, wiz_state, user.id)
            else:
                wiz_state["step"] = "buttons"
                self._save_wizard_state(user.id, wiz_state, next_action="wiz_buttons")
                media_label = "🖼️ Foto" if wiz_state.get("media_type") == "photo" else "🎥 Vídeo"
                p_text, p_markup = generate_wizard_buttons_prompt(dest_label, media_label)
                await msg.reply_text(p_text, reply_markup=p_markup, parse_mode=ParseMode.MARKDOWN)
            return True

        elif action == "wiz_buttons":
            wiz_state = self._get_or_create_wizard_state(user.id)
            raw_text = (msg.text or "").strip()
            if raw_text.lower() in ("pular", "nenhum", "remover", "off"):
                wiz_state["buttons"] = []
            else:
                extracted = self._parse_buttons(raw_text)
                if not extracted:
                    await msg.reply_text(
                        "⚠️ Não encontrei botões no formato correto.\n\n"
                        "Envie no modelo: `[Nome do Botão | https://link.com]`\n"
                        "Ou clique em **Pular Botões** abaixo:",
                        parse_mode=ParseMode.MARKDOWN,
                        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⏭️ Pular Botões", callback_data="cfg:wiz:skip_buttons")]])
                    )
                    return True
                wiz_state["buttons"] = extracted

            del self.pending_inputs[user.id]
            self._save_wizard_state(user.id, wiz_state)
            await self.show_wizard_preview(update, context, wiz_state, user.id)
            return True

        elif action == "wiz_sched_custom":
            val_text = (msg.text or "").strip()
            state = state or self.wizard_states.get(user.id, {})

            from config import get_timezone
            tz = get_timezone(cfg)
            now_dt = datetime.now(tz)

            target_dt = None

            # 1. Relativo: 10m, 45m, 2h, etc.
            m_rel = re.match(r'^(\d+)\s*(m|min|mins|minuto|minutos|h|hr|hrs|hora|horas)$', val_text, re.I)
            if m_rel:
                num = int(m_rel.group(1))
                unit = m_rel.group(2).lower()
                target_dt = now_dt + (timedelta(minutes=num) if unit.startswith('m') else timedelta(hours=num))

            # 2. Hora simples: 18:30 ou 18h30
            if not target_dt:
                val_clean = val_text.replace('h', ':').replace('H', ':')
                m_time = re.match(r'^(\d{1,2}):(\d{2})(?::(\d{2}))?$', val_clean)
                if m_time:
                    h = int(m_time.group(1))
                    m = int(m_time.group(2))
                    if 0 <= h <= 23 and 0 <= m <= 59:
                        cand = now_dt.replace(hour=h, minute=m, second=0, microsecond=0)
                        if cand <= now_dt:
                            cand += timedelta(days=1)
                        target_dt = cand

            # 3. Data e hora completas
            if not target_dt:
                for fmt in ('%d/%m/%Y %H:%M', '%d/%m %H:%M %Y', '%Y-%m-%d %H:%M'):
                    try:
                        to_parse = val_text if fmt != '%d/%m %H:%M %Y' else f"{val_text} {now_dt.year}"
                        dt = datetime.strptime(to_parse, fmt)
                        dt = dt.replace(tzinfo=tz)
                        if dt < now_dt and fmt == '%d/%m %H:%M %Y':
                            dt = dt.replace(year=now_dt.year + 1)
                        target_dt = dt
                        break
                    except ValueError:
                        pass

            if not target_dt or target_dt <= now_dt:
                await msg.reply_text(
                    "⚠️ *Não entendi o horário ou a data informada já passou.*\n\n"
                    "💡 *Exemplos válidos:*\n"
                    "• `18:30` ou `20:00` (hoje ou amanhã)\n"
                    "• `18/10 14:00` (dia/mês hora:minuto)\n"
                    "• `30m` ou `2h` (daqui a 30 minutos ou 2 horas)\n\n"
                    "Por favor envie novamente (ou digite /cancelar):",
                    parse_mode=ParseMode.MARKDOWN
                )
                return True

            del self.pending_inputs[user.id]
            await self.save_scheduled_transmission(update, context, state, user.id, target_dt)
            return True

        elif action == "wiz_link_channel":
            val_text = (msg.text or "").strip()
            from config import add_linked_channel
            tokens = [t.strip(",; \n\r") for t in val_text.split() if t.strip(",; \n\r")]
            if not tokens:
                await msg.reply_text("⚠️ Envie o `@username` ou ID do canal (ex: `@meucanal` ou múltiplos `@c1 @c2`), ou digite /cancelar.", parse_mode=ParseMode.MARKDOWN)
                return True

            success_channels = []
            errors = []
            for t in tokens:
                try:
                    target_chat = await context.bot.get_chat(t)
                    if target_chat.type not in ("channel", "supergroup", "group"):
                        errors.append(f"• `{t}`: chat inválido ({target_chat.type})")
                        continue

                    title = target_chat.title or f"Chat {target_chat.id}"
                    username = f"@{target_chat.username}" if target_chat.username else ""
                    add_linked_channel(cfg, target_chat.id, title, username)
                    success_channels.append((target_chat.id, title, username))
                except Exception as e:
                    errors.append(f"• `{t}`: {e}")

            if success_channels:
                del self.pending_inputs[user.id]
                self._save_pending_inputs()

                next_markup = InlineKeyboardMarkup([
                    [InlineKeyboardButton("📢 Continuar e Escolher Destino", callback_data="cfg:wiz:start")],
                    [InlineKeyboardButton("◀ Voltar ao Painel", callback_data="cfg:page:1")]
                ])

                if len(success_channels) == 1 and not errors:
                    cid, title, username = success_channels[0]
                    await msg.reply_text(
                        f"✅ *Canal '{title}' vinculado com sucesso!* 📢\n\n"
                        f"• ID: `{cid}`\n"
                        f"• Link: `{username or 'Privado'}`\n\n"
                        "O canal foi salvo nas configurações permanentes do bot.\n"
                        "Deseja iniciar sua transmissão para ele agora?",
                        parse_mode=ParseMode.MARKDOWN,
                        reply_markup=InlineKeyboardMarkup([
                            [InlineKeyboardButton("📢 Transmitir para Este Canal", callback_data=f"cfg:wiz:dest:chn:{cid}")],
                            [InlineKeyboardButton("◀ Voltar à Seleção de Destinos", callback_data="cfg:wiz:start")]
                        ])
                    )
                else:
                    lines = [f"✅ *{len(success_channels)} canal(is) vinculado(s) com sucesso!* 📢\n"]
                    for cid, title, username in success_channels:
                        u_str = f" ({username})" if username else ""
                        lines.append(f"• *{title}* (`{cid}`){u_str}")
                    if errors:
                        lines.append("\n⚠️ *Falhas encontradas:*")
                        lines.extend(errors)
                    lines.append("\nOs canais foram salvos permanentemente no bot.")
                    await msg.reply_text("\n".join(lines), parse_mode=ParseMode.MARKDOWN, reply_markup=next_markup)
                return True
            else:
                err_msg = "\n".join(errors) if errors else "Não foi possível conectar."
                await msg.reply_text(
                    f"❌ *Não foi possível conectar ao(s) canal(is):*\n{err_msg}\n\n"
                    "Certifique-se de que adicionou o bot como Administrador no canal com permissão de *Postar Mensagens* e tente novamente (ou digite /cancelar):",
                    parse_mode=ParseMode.MARKDOWN
                )
                return True

        return False

    def _parse_buttons(self, text: str) -> list:
        from modules.utils import parse_rich_buttons
        return parse_rich_buttons(text)

    async def preview_welcome(self, update: Update, context: ContextTypes.DEFAULT_TYPE, group_id: str = "general"):
        chat = update.effective_chat
        user = update.effective_user
        cfg = load_config()

        from config import get_welcome_for_chat
        target_cid = None if group_id in ("general", "0", "") else group_id
        w = get_welcome_for_chat(cfg, target_cid)

        target_chat = chat
        if target_cid:
            g_item = next((g for g in cfg.get("linked_groups", []) if str(g.get("id")) == str(target_cid)), None)
            if g_item:
                class FakeChat:
                    def __init__(self, cid, title):
                        self.id = cid
                        self.title = title
                        self.type = "supergroup"
                target_chat = FakeChat(int(target_cid) if (target_cid.startswith("-") or target_cid.isdigit()) else chat.id, g_item.get("title", "Grupo"))

        from modules.utils import format_placeholders, build_rich_buttons_markup
        template = w.get("message", "👋 Seja bem-vindo(a), {name} ao grupo *{group}*!")
        formatted_msg = format_placeholders(template, user, target_chat, cfg)

        markup = build_rich_buttons_markup(w.get("buttons", []))
        photo = w.get("photo")
        article_url = w.get("article_url")

        from telegram import LinkPreviewOptions
        lpo = None
        if article_url:
            lpo = LinkPreviewOptions(url=article_url, show_above_text=True, is_disabled=False)
        else:
            lpo = LinkPreviewOptions(show_above_text=True)

        from modules.utils import smart_send_message, smart_send_photo
        if photo:
            await smart_send_photo(bot=context.bot, chat_id=chat.id, photo=photo, caption=formatted_msg, reply_markup=markup)
        else:
            await smart_send_message(bot=context.bot, chat_id=chat.id, text=formatted_msg, reply_markup=markup, link_preview_options=lpo)

    async def handle_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Processa os cliques nos botões do painel interativo."""
        query = update.callback_query
        if not query or not query.data:
            return

        chat = update.effective_chat
        user = update.effective_user
        data = query.data

        if not await self._require_admin(update):
            await query.answer("⛔ Apenas administradores podem usar estes botões.", show_alert=True)
            return

        cfg = load_config()
        title = chat.title or "Grupo"

        # Delega callbacks de Boas-Vindas para modules/welcome_ui.py
        if await handle_welcome_callback(self, update, context):
            return

        # Delega callbacks de Whitelist & Links Permitidos para modules/whitelist.py
        if await handle_whitelist_callback(self, update, context):
            return

        # Fechar painel
        if data == "cfg:close":
            await query.answer("Configurações salvas!")
            try:
                await query.edit_message_text(
                    "✅ *Painel de Configurações Concluído!*\nTodas as alterações estão salvas e ativas.",
                    parse_mode=ParseMode.MARKDOWN
                )
            except Exception:
                await query.edit_message_text("✅ Painel concluído! Alterações salvas.")
            return

        # Acervo Musical (Inline)
        if data == "cfg:sub:acervo":
            await query.answer()
            from modules.inline_acervo import generate_acervo_dashboard_text_and_kb
            text, markup = generate_acervo_dashboard_text_and_kb()
            await query.edit_message_text(text, reply_markup=markup, parse_mode=ParseMode.HTML)
            return

        # Fuso Horário - Submenu & Ações
        if data == "cfg:sub:timezone":
            await query.answer()
            text, markup = generate_sub_timezone(cfg)
            await query.edit_message_text(text, reply_markup=markup, parse_mode=ParseMode.MARKDOWN)
            return

        if data.startswith("cfg:set:tz:"):
            tz_name = data[len("cfg:set:tz:"):]
            from config import set_timezone, get_timezone_label
            set_timezone(cfg, tz_name)
            await query.answer(f"Fuso alterado para: {get_timezone_label(cfg)}!")
            text, markup = generate_sub_timezone(cfg)
            await query.edit_message_text(text, reply_markup=markup, parse_mode=ParseMode.MARKDOWN)
            return

        if data == "cfg:input:tz":
            self.pending_inputs[user.id] = {"action": "custom_timezone", "chat_id": chat.id}
            await query.answer()
            prompt = (
                "🕒 *Digite o Nome do Fuso Horário (Formato IANA):*\n\n"
                "Exemplos:\n"
                "• `America/Sao_Paulo`\n"
                "• `America/Manaus`\n"
                "• `America/Fortaleza`\n"
                "• `America/Belem`\n"
                "• `America/Cuiaba`\n"
                "• `America/Rio_Branco`\n"
                "• `Europe/Lisbon`\n"
                "• `UTC`\n\n"
                "_Envie o nome agora (ou digite /cancelar):_"
            )
            await chat.send_message(prompt, parse_mode=ParseMode.MARKDOWN)
            return

        if data == "cfg:cycle:timezone":
            new_tz = cycle_timezone(cfg)
            tz_lbl = get_timezone_label(cfg)
            await query.answer(f"Fuso horário alterado para: {tz_lbl}")
            # Atualiza a página onde o usuário estava
            text, markup = generate_page_2(title, cfg)
            await query.edit_message_text(text, reply_markup=markup, parse_mode=ParseMode.MARKDOWN)
            return

        # Auto-Apagar Boas-Vindas - Submenu & Ações
        if data.startswith("cfg:sub:wtime:"):
            gid = data.split(":")[-1] if len(data.split(":")) > 3 else "general"
            try:
                await query.answer()
            except Exception:
                pass
            text, markup = generate_sub_welcome_time(cfg, gid)
            try:
                await query.edit_message_text(text, reply_markup=markup, parse_mode=ParseMode.HTML)
            except Exception:
                try:
                    await query.edit_message_text(text, reply_markup=markup)
                except Exception:
                    pass
            return

        if data.startswith("cfg:set:wtime:"):
            parts = data.split(":")
            val1 = parts[3] if len(parts) > 3 else "general"
            val2 = parts[4] if len(parts) > 4 else "60"

            if val1 == "general":
                gid = "general"
                try:
                    sec = int(val2)
                except Exception:
                    sec = 60
            elif val2 == "general":
                gid = "general"
                try:
                    sec = int(val1)
                except Exception:
                    sec = 60
            else:
                try:
                    n1 = int(val1)
                    n2 = int(val2)
                    if n1 < 0:
                        gid = str(n1)
                        sec = n2
                    elif n2 < 0:
                        gid = str(n2)
                        sec = n1
                    elif n1 in (0, 30, 60, 120, 300, 600, 900, 1800, 3600) or (n1 <= 86400 < n2):
                        sec = n1
                        gid = str(n2)
                    else:
                        gid = str(n1)
                        sec = n2
                except Exception:
                    gid = val1
                    try:
                        sec = int(val2)
                    except Exception:
                        sec = 60

            if gid in ("general", "0", ""):
                cfg.setdefault("welcome", {})["delete_welcome_after_seconds"] = sec
            else:
                from config import get_welcome_for_chat
                w_grp = cfg.setdefault("group_welcomes", {}).setdefault(str(gid), dict(get_welcome_for_chat(cfg, gid)))
                w_grp["delete_welcome_after_seconds"] = sec
            save_config(cfg)
            lbl = format_time_label(sec)
            desc = "nunca apagar" if sec == 0 else f"apagar após {lbl}"
            try:
                await query.answer(f"Tempo definido: {desc}!", show_alert=False)
            except Exception:
                pass
            text, markup = generate_sub_welcome_time(cfg, gid)
            try:
                await query.edit_message_text(text, reply_markup=markup, parse_mode=ParseMode.HTML)
            except Exception:
                try:
                    await query.edit_message_text(text, reply_markup=markup)
                except Exception:
                    pass
            return

        if data.startswith("cfg:input:wtime:"):
            gid = data.split(":")[-1] if len(data.split(":")) > 3 else "general"
            self.pending_inputs[user.id] = {"action": "welcome_autodel_time", "group_id": gid, "chat_id": chat.id}
            await query.answer()
            prompt = (
                "⏱️ *Digite o Tempo para Auto-Apagar as Boas-Vindas:*\n\n"
                "Você pode digitar de *1 minuto a 24 horas* (ou `nunca`).\n\n"
                "💡 *Exemplos:*\n"
                "• `10m` ou `10 min` ou `10` (10 minutos)\n"
                "• `30m` (30 minutos)\n"
                "• `1h` (1 hora)\n"
                "• `2h` ou `2 horas`\n"
                "• `12h` ou `24h`\n"
                "• `nunca` ou `0` (não apagar)\n\n"
                "_Envie o tempo desejado agora (ou digite /cancelar):_"
            )
            await chat.send_message(prompt, parse_mode=ParseMode.MARKDOWN)
            return

        # =============================================================
        # ASSISTENTE DE TRANSMISSÃO GUIADA (WIZARD)
        # =============================================================
        if data == "cfg:wiz:start":
            await query.answer()
            text, markup = generate_wizard_dest_menu(cfg)
            try:
                await query.edit_message_text(text, reply_markup=markup, parse_mode=ParseMode.MARKDOWN)
            except Exception:
                await query.edit_message_text(text, reply_markup=markup)
            return

        if data == "cfg:wiz:add_channel":
            self.pending_inputs[user.id] = {"action": "wiz_link_channel"}
            self._save_pending_inputs()
            await query.answer()
            prompt = (
                "📢 *Vincular Canal ao Bot:*\n\n"
                "1. Adicione o bot como *Administrador* no seu Canal com permissão de *Postar Mensagens*.\n"
                "2. Digite aqui no privado o `@username` do canal (ex: `@meucanal`) ou o ID numérico (ex: `-1001234567890`).\n\n"
                "_Envie o canal agora (ou digite /cancelar):_"
            )
            await chat.send_message(prompt, parse_mode=ParseMode.MARKDOWN)
            return

        if data.startswith("cfg:wiz:dest:"):
            target = data.replace("cfg:wiz:dest:", "")
            linked_c = cfg.get("linked_channels", [])
            if target in ("main_channel", "all_channels") and not linked_c:
                self.pending_inputs[user.id] = {"action": "wiz_link_channel"}
                self._save_pending_inputs()
                await query.answer("⚠️ Nenhum canal vinculado ao bot ainda!", show_alert=True)
                prompt = (
                    "📢 *Nenhum Canal Vinculado Ainda!*\n\n"
                    "Para o bot poder postar no seu canal:\n"
                    "1. Adicione o bot como *Administrador* no Canal com permissão de *Postar Mensagens*.\n"
                    "2. Envie aqui no privado o `@username` do canal (ex: `@meucanal`) ou o ID numérico (ex: `-1001234567890`).\n\n"
                    "_Envie o canal agora (ou digite /cancelar):_"
                )
                await chat.send_message(prompt, parse_mode=ParseMode.MARKDOWN)
                return

            state = self._get_or_create_wizard_state(user.id)
            state.update({
                "step": "text",
                "target": target,
                "text": "",
                "media_type": None,
                "media_id": None,
                "buttons": [],
                "pin": False,
                "delay_seconds": 2
            })
            self._save_wizard_state(user.id, state, next_action="wiz_text")
            dest_label = get_wizard_dest_label(target, cfg)
            text, markup = generate_wizard_text_prompt(dest_label)
            await query.answer()
            try:
                await query.edit_message_text(text, reply_markup=markup, parse_mode=ParseMode.MARKDOWN)
            except Exception:
                await query.edit_message_text(text, reply_markup=markup)
            return

        if data == "cfg:wiz:edit_text":
            state = self._get_or_create_wizard_state(user.id)
            state["step"] = "text"
            self._save_wizard_state(user.id, state, next_action="wiz_text")
            dest_label = get_wizard_dest_label(state.get("target", "main_channel"), cfg)
            text, markup = generate_wizard_text_prompt(dest_label)
            await query.answer()
            try:
                await query.edit_message_text(text, reply_markup=markup, parse_mode=ParseMode.MARKDOWN)
            except Exception:
                await query.edit_message_text(text, reply_markup=markup)
            return

        if data == "cfg:wiz:skip_media":
            state = self._get_or_create_wizard_state(user.id)
            state["media_type"] = None
            state["media_id"] = None
            state["step"] = "buttons"
            self._save_wizard_state(user.id, state, next_action="wiz_buttons")
            dest_label = get_wizard_dest_label(state.get("target", "main_channel"), cfg)
            text, markup = generate_wizard_buttons_prompt(dest_label, "⚪ Nenhuma (Somente Texto)")
            await query.answer()
            try:
                await query.edit_message_text(text, reply_markup=markup, parse_mode=ParseMode.MARKDOWN)
            except Exception:
                await query.edit_message_text(text, reply_markup=markup)
            return

        if data == "cfg:wiz:edit_media":
            state = self._get_or_create_wizard_state(user.id)
            state["step"] = "media"
            self._save_wizard_state(user.id, state, next_action="wiz_media")
            dest_label = get_wizard_dest_label(state.get("target", "main_channel"), cfg)
            text, markup = generate_wizard_media_prompt(dest_label, state.get("text", ""))
            await query.answer()
            try:
                await query.edit_message_text(text, reply_markup=markup, parse_mode=ParseMode.MARKDOWN)
            except Exception:
                await query.edit_message_text(text, reply_markup=markup)
            return

        if data == "cfg:wiz:skip_buttons":
            state = self._get_or_create_wizard_state(user.id)
            state["buttons"] = []
            if user.id in self.pending_inputs:
                del self.pending_inputs[user.id]
                self._save_pending_inputs()
            self._save_wizard_state(user.id, state)
            await query.answer()
            await self.show_wizard_preview(update, context, state, user.id)
            return

        if data == "cfg:wiz:edit_buttons":
            state = self._get_or_create_wizard_state(user.id)
            state["step"] = "buttons"
            self._save_wizard_state(user.id, state, next_action="wiz_buttons")
            dest_label = get_wizard_dest_label(state.get("target", "main_channel"), cfg)
            media_label = "🎥 Vídeo" if state.get("media_type") == "video" else ("🖼️ Foto" if state.get("media_type") == "photo" else "⚪ Nenhuma")
            text, markup = generate_wizard_buttons_prompt(dest_label, media_label)
            await query.answer()
            try:
                await query.edit_message_text(text, reply_markup=markup, parse_mode=ParseMode.MARKDOWN)
            except Exception:
                await query.edit_message_text(text, reply_markup=markup)
            return

        if data == "cfg:wiz:toggle_pin":
            state = self._get_or_create_wizard_state(user.id)
            state["pin"] = not state.get("pin", False)
            self._save_wizard_state(user.id, state)
            dest_label = get_wizard_dest_label(state.get("target", "main_channel"), cfg)
            media_label = "🎥 Vídeo" if state.get("media_type") == "video" else ("🖼️ Foto" if state.get("media_type") == "photo" else "⚪ Nenhuma")
            btns = state.get("buttons", [])
            btns_count = sum(len(r) for r in btns) if (btns and isinstance(btns[0], list)) else len(btns)
            delay_sec = state.get("delay_seconds", 2)
            ctrl_text, ctrl_markup = generate_wizard_preview_controls(dest_label, media_label, btns_count, state["pin"], delay_sec)
            await query.answer(f"Fixar no topo: {'Ativado 📌' if state['pin'] else 'Desativado'}")
            try:
                await query.edit_message_text(ctrl_text, reply_markup=ctrl_markup, parse_mode=ParseMode.MARKDOWN)
            except Exception:
                await query.edit_message_text(ctrl_text, reply_markup=ctrl_markup)
            return

        if data == "cfg:wiz:toggle_delay":
            state = self._get_or_create_wizard_state(user.id)
            cur_delay = state.get("delay_seconds", 2)
            presets = [0, 2, 5, 10, 30]
            idx = presets.index(cur_delay) if cur_delay in presets else 0
            new_delay = presets[(idx + 1) % len(presets)]
            state["delay_seconds"] = new_delay
            self._save_wizard_state(user.id, state)
            dest_label = get_wizard_dest_label(state.get("target", "main_channel"), cfg)
            media_label = "🎥 Vídeo" if state.get("media_type") == "video" else ("🖼️ Foto" if state.get("media_type") == "photo" else "⚪ Nenhuma")
            btns = state.get("buttons", [])
            btns_count = sum(len(r) for r in btns) if (btns and isinstance(btns[0], list)) else len(btns)
            ctrl_text, ctrl_markup = generate_wizard_preview_controls(dest_label, media_label, btns_count, state.get("pin", False), new_delay)
            await query.answer(f"Distribuição: {get_delay_label(new_delay)}")
            try:
                await query.edit_message_text(ctrl_text, reply_markup=ctrl_markup, parse_mode=ParseMode.MARKDOWN)
            except Exception:
                await query.edit_message_text(ctrl_text, reply_markup=ctrl_markup)
            return

        if data == "cfg:wiz:sched_menu":
            state = self.wizard_states.get(user.id, {})
            text, markup = generate_wizard_schedule_menu(cfg, state)
            await query.answer()
            try:
                await query.edit_message_text(text, reply_markup=markup, parse_mode=ParseMode.MARKDOWN)
            except Exception:
                await query.edit_message_text(text, reply_markup=markup)
            return

        if data == "cfg:wiz:back_preview":
            state = self.wizard_states.get(user.id, {})
            dest_label = get_wizard_dest_label(state.get("target", "main_channel"), cfg)
            media_label = "🎥 Vídeo" if state.get("media_type") == "video" else ("🖼️ Foto" if state.get("media_type") == "photo" else "⚪ Nenhuma")
            btns = state.get("buttons", [])
            btns_count = sum(len(r) for r in btns) if (btns and isinstance(btns[0], list)) else len(btns)
            delay_sec = state.get("delay_seconds", 2)
            ctrl_text, ctrl_markup = generate_wizard_preview_controls(dest_label, media_label, btns_count, state.get("pin", False), delay_sec)
            await query.answer()
            try:
                await query.edit_message_text(ctrl_text, reply_markup=ctrl_markup, parse_mode=ParseMode.MARKDOWN)
            except Exception:
                await query.edit_message_text(ctrl_text, reply_markup=ctrl_markup)
            return

        if data.startswith("cfg:wiz:set_rel:"):
            mins = int(data.split(":")[-1])
            state = self.wizard_states.get(user.id, {})
            from config import get_timezone
            tz = get_timezone(cfg)
            target_dt = datetime.now(tz) + timedelta(minutes=mins)
            await query.answer("⏰ Agendando...")
            await self.save_scheduled_transmission(update, context, state, user.id, target_dt)
            return

        if data.startswith("cfg:wiz:set_time:"):
            tspec = data.replace("cfg:wiz:set_time:", "")
            state = self.wizard_states.get(user.id, {})
            from config import get_timezone
            tz = get_timezone(cfg)
            now_dt = datetime.now(tz)
            if tspec == "tomorrow_09:00":
                target_dt = (now_dt + timedelta(days=1)).replace(hour=9, minute=0, second=0, microsecond=0)
            else:
                h, m = map(int, tspec.split(":"))
                cand = now_dt.replace(hour=h, minute=m, second=0, microsecond=0)
                if cand <= now_dt:
                    cand += timedelta(days=1)
                target_dt = cand
            await query.answer("⏰ Agendando...")
            await self.save_scheduled_transmission(update, context, state, user.id, target_dt)
            return

        if data == "cfg:wiz:set_custom":
            state = self.wizard_states.get(user.id, {})
            self.pending_inputs[user.id] = {"action": "wiz_sched_custom", "state": state}
            await query.answer()
            prompt = (
                "🕒 *Digite a Data e Hora para o Agendamento:*\n\n"
                "💡 *Exemplos válidos:*\n"
                "• `18:30` ou `20:00` (hoje ou amanhã se já tiver passado)\n"
                "• `18/10 14:00` (dia/mês hora:minuto)\n"
                "• `30m` ou `2h` (daqui a 30 minutos ou 2 horas)\n\n"
                "_Envie a data/hora agora (ou digite /cancelar):_"
            )
            await chat.send_message(prompt, parse_mode=ParseMode.MARKDOWN)
            return

        # Gerenciamento de Transmissões Agendadas
        if data == "cfg:sched:list":
            await query.answer()
            text, markup = generate_scheduled_transmissions_menu(cfg)
            try:
                await query.edit_message_text(text, reply_markup=markup, parse_mode=ParseMode.MARKDOWN)
            except Exception:
                await query.edit_message_text(text, reply_markup=markup)
            return

        if data.startswith("cfg:sched:cancel:"):
            item_id = int(data.split(":")[-1])
            sched_list = cfg.get("scheduled_transmissions", [])
            item = next((x for x in sched_list if x.get("id") == item_id), None)
            if item:
                item["status"] = "cancelled"
                save_config(cfg)
                await query.answer("🗑️ Agendamento cancelado!", show_alert=True)
            else:
                await query.answer("⚠️ Agendamento não encontrado.", show_alert=True)
            text, markup = generate_scheduled_transmissions_menu(cfg)
            try:
                await query.edit_message_text(text, reply_markup=markup, parse_mode=ParseMode.MARKDOWN)
            except Exception:
                await query.edit_message_text(text, reply_markup=markup)
            return

        if data.startswith("cfg:sched:fire:"):
            item_id = int(data.split(":")[-1])
            sched_list = cfg.get("scheduled_transmissions", [])
            item = next((x for x in sched_list if x.get("id") == item_id), None)
            if item and item.get("status") == "pending":
                item["status"] = "sending"
                save_config(cfg)
                from modules.recurring import _execute_scheduled_transmission
                asyncio.create_task(_execute_scheduled_transmission(context.bot, item))
                await query.answer("🚀 Transmissão disparada imediatamente!", show_alert=True)
            else:
                await query.answer("⚠️ Transmissão já executada ou cancelada.", show_alert=True)
            text, markup = generate_scheduled_transmissions_menu(cfg)
            try:
                await query.edit_message_text(text, reply_markup=markup, parse_mode=ParseMode.MARKDOWN)
            except Exception:
                await query.edit_message_text(text, reply_markup=markup)
            return

        if data == "cfg:wiz:send":
            await query.answer("🚀 Enviando transmissão...")
            await self.execute_wizard_send(update, context, user.id)
            return

        if data == "cfg:wiz:cancel":
            self.wizard_states.pop(user.id, None)
            if user.id in self.pending_inputs:
                del self.pending_inputs[user.id]
                self._save_pending_inputs()
            await query.answer("Transmissão cancelada.")
            text, markup = generate_page_1(title, cfg)
            try:
                await query.edit_message_text(text, reply_markup=markup, parse_mode=ParseMode.MARKDOWN)
            except Exception:
                await query.edit_message_text(text, reply_markup=markup)
            return

        # Navegação de páginas
        if data == "cfg:page:1":
            await query.answer()
            text, markup = generate_page_1(title, cfg)
            await query.edit_message_text(text, reply_markup=markup, parse_mode=ParseMode.MARKDOWN)
            return

        if data == "cfg:page:2":
            await query.answer()
            text, markup = generate_page_2(title, cfg)
            await query.edit_message_text(text, reply_markup=markup, parse_mode=ParseMode.MARKDOWN)
            return

        # Sub-menus padrões
        if data == "cfg:sub:rules":
            await query.answer()
            text, markup = generate_sub_rules(cfg)
            await query.edit_message_text(text, reply_markup=markup, parse_mode=ParseMode.MARKDOWN)
            return

        if data == "cfg:sub:cmd_clean":
            await query.answer()
            text, markup = generate_sub_cmd_clean(cfg)
            await query.edit_message_text(text, reply_markup=markup, parse_mode=ParseMode.MARKDOWN)
            return

        if data == "cfg:sub:antispam":
            await query.answer()
            text, markup = generate_sub_antispam(cfg)
            await query.edit_message_text(text, reply_markup=markup, parse_mode=ParseMode.MARKDOWN)
            return

        if data == "cfg:sub:antiflood":
            await query.answer()
            text, markup = generate_sub_antiflood(cfg)
            await query.edit_message_text(text, reply_markup=markup, parse_mode=ParseMode.MARKDOWN)
            return

        if data == "cfg:sub:banned":
            await query.answer()
            text, markup = generate_sub_banned(cfg)
            await query.edit_message_text(text, reply_markup=markup, parse_mode=ParseMode.MARKDOWN)
            return

        if data == "cfg:sub:clean":
            await query.answer("Use o comando /limpar [quantidade] no chat (ex: /limpar 10)", show_alert=True)
            return

        if data == "cfg:sub:logs":
            await query.answer()
            text, markup = generate_sub_logs(cfg)
            await query.edit_message_text(text, reply_markup=markup, parse_mode=ParseMode.MARKDOWN)
            return

        if data == "cfg:sub:nightmode":
            await query.answer()
            text, markup = generate_sub_nightmode(cfg)
            await query.edit_message_text(text, reply_markup=markup, parse_mode=ParseMode.MARKDOWN)
            return

        if data == "cfg:sub:docs":
            await query.answer()
            text, markup = generate_sub_docs()
            await query.edit_message_text(text, reply_markup=markup, parse_mode=ParseMode.MARKDOWN)
            return

        if data == "cfg:toggle:nightmode":
            nm = cfg.setdefault("night_mode", {})
            nm["enabled"] = not nm.get("enabled", False)
            if nm["enabled"]:
                if chat.type in ("group", "supergroup"):
                    c_list = nm.setdefault("enabled_chats", [])
                    if chat.id not in c_list:
                        c_list.append(chat.id)
                elif cfg.get("main_group_id"):
                    c_list = nm.setdefault("enabled_chats", [])
                    if cfg["main_group_id"] not in c_list:
                        c_list.append(cfg["main_group_id"])
            save_config(cfg)
            st = "Ativado" if nm["enabled"] else "Desativado"
            await query.answer(f"Modo Noturno: {st}")
            text, markup = generate_sub_nightmode(cfg)
            await query.edit_message_text(text, reply_markup=markup, parse_mode=ParseMode.MARKDOWN)
            return

        if data == "cfg:toggle:nightmode_ann":
            nm = cfg.setdefault("night_mode", {})
            cur = nm.get("announce_start", True) and nm.get("announce_end", True)
            nm["announce_start"] = not cur
            nm["announce_end"] = not cur
            save_config(cfg)
            st = "Ativados" if not cur else "Desativados"
            await query.answer(f"Avisos: {st}")
            text, markup = generate_sub_nightmode(cfg)
            await query.edit_message_text(text, reply_markup=markup, parse_mode=ParseMode.MARKDOWN)
            return

        if data in ("cfg:test:nightmode_start", "cfg:test:nightmode_end"):
            is_start = data == "cfg:test:nightmode_start"
            nm = cfg.get("night_mode", {})
            s = nm.get("start", "23:00")
            e = nm.get("end", "07:00")
            if is_start:
                txt = (
                    "🌙 *Silêncio Noturno Iniciado!*\n\n"
                    f"O Modo Noturno acabou de começar (das *{s}* às *{e}*).\n"
                    "O envio de mensagens comuns foi temporariamente pausado para mantermos o descanso e a tranquilidade de todos.\n\n"
                    "Tenham uma excelente e abençoada noite! 😴🎹✨"
                )
            else:
                txt = (
                    "☀️ *Bom Dia! Silêncio Noturno Encerrado!*\n\n"
                    f"O horário de silêncio chegou ao fim (das *{s}* às *{e}*).\n"
                    "O chat do grupo está oficialmente aberto para mensagens, novidades e partituras!\n\n"
                    "Desejamos a todos um ótimo e produtivo dia! 🎼☕✨"
                )

            # Envia para os grupos monitorados se existirem
            target_chats = set()
            main_id = cfg.get("main_group_id")
            if main_id and isinstance(main_id, int) and main_id < 0:
                target_chats.add(main_id)
            for cid in nm.get("enabled_chats", []):
                if cid and isinstance(cid, int) and cid < 0:
                    target_chats.add(cid)

            sent_count = 0
            for cid in target_chats:
                try:
                    await context.bot.send_message(chat_id=cid, text=txt, parse_mode=ParseMode.MARKDOWN)
                    sent_count += 1
                except Exception:
                    pass

            await query.answer(f"Aviso de teste disparado ({sent_count} grupo(s))!")
            if sent_count > 0:
                await chat.send_message(f"✅ Aviso de {'início' if is_start else 'término'} enviado para o(s) grupo(s)!")
            else:
                await chat.send_message(f"📢 *Prévia do aviso de {'início' if is_start else 'término'}:*\n\n{txt}\n\n💡 *Dica:* Para enviar direto ao grupo, vincule-o usando /setgrupo no grupo!", parse_mode=ParseMode.MARKDOWN)
            return

        if data == "cfg:logs:set_id":
            self.pending_inputs[user.id] = {"action": "logs_set_id", "chat_id": chat.id}
            await query.answer()
            prompt = (
                "📡 *Configurar Canal de Logs & Auditoria:*\n\n"
                "1. Crie um canal ou grupo privado no Telegram.\n"
                "2. Adicione este bot como **Administrador** lá.\n"
                "3. Envie o **ID do Canal** aqui (ex: `-1001234567890`).\n"
                "_(Para descobrir o ID, use o comando /chatinfo dentro do canal/grupo)_\n\n"
                "_Envie o ID agora ou digite /cancelar:_"
            )
            await chat.send_message(prompt, parse_mode=ParseMode.MARKDOWN)
            return

        if data == "cfg:logs:test":
            channel_id = cfg.get("log_channel_id")
            if not channel_id:
                await query.answer("Nenhum canal configurado ainda. Defina o ID primeiro!", show_alert=True)
                return
            success = await send_mod_log(
                bot=context.bot,
                event_type="config",
                title="Teste de Conexão com Canal de Logs",
                user_info=f"{user.first_name} (<code>{user.id}</code>)",
                details="O canal de logs está funcionando perfeitamente! 🚀"
            )
            if success:
                await query.answer("Log de teste enviado com sucesso!", show_alert=True)
            else:
                await query.answer("Erro ao enviar. Verifique se o bot é Admin no canal!", show_alert=True)
            return

        if data == "cfg:logs:clear":
            cfg["log_channel_id"] = None
            save_config(cfg)
            await query.answer("Canal de logs desativado!")
            text, markup = generate_sub_logs(cfg)
            await query.edit_message_text(text, reply_markup=markup, parse_mode=ParseMode.MARKDOWN)
            return

        if data.startswith("cfg:logs:toggle:"):
            ev_key = data.split(":")[-1]
            events = cfg.setdefault("log_events", {})
            events[ev_key] = not events.get(ev_key, True)
            save_config(cfg)
            status_lbl = "Ativado" if events[ev_key] else "Desativado"
            await query.answer(f"Log de {ev_key}: {status_lbl}")
            text, markup = generate_sub_logs(cfg)
            await query.edit_message_text(text, reply_markup=markup, parse_mode=ParseMode.MARKDOWN)
            return

        # -------------------------------------------------------------
        # SEÇÃO: PALAVRAS PROIBIDAS (AÇÕES INTERATIVAS)
        # -------------------------------------------------------------
        if data == "cfg:banned:cycle_action":
            cur_action = cfg.setdefault("antispam", {}).get("banned_words_action", "warn")
            idx = PUNISHMENT_CYCLE.index(cur_action) if cur_action in PUNISHMENT_CYCLE else 0
            new_action = PUNISHMENT_CYCLE[(idx + 1) % len(PUNISHMENT_CYCLE)]
            cfg["antispam"]["banned_words_action"] = new_action
            save_config(cfg)
            new_title = PUNISHMENT_INFO[new_action][0]
            await query.answer(f"Punição alterada para: {new_title}")
            text, markup = generate_sub_banned(cfg)
            await query.edit_message_text(text, reply_markup=markup, parse_mode=ParseMode.MARKDOWN)
            return

        if data == "cfg:banned:add":
            self.pending_inputs[user.id] = {"action": "banned_add", "chat_id": chat.id}
            await query.answer()
            prompt = (
                "✏️ *Adicionar Palavras Proibidas:*\n\n"
                "Envie os termos que deseja bloquear (separados por vírgula ou um por linha).\n\n"
                "Exemplo:\n"
                "`golpe, robô do pix, pirataria, hack`\n\n"
                "_Envie sua lista agora ou digite /cancelar:_"
            )
            await chat.send_message(prompt, parse_mode=ParseMode.MARKDOWN)
            return

        if data == "cfg:banned:remove":
            self.pending_inputs[user.id] = {"action": "banned_remove", "chat_id": chat.id}
            await query.answer()
            prompt = (
                "🗑️ *Remover Palavras Proibidas:*\n\n"
                "Envie os termos que deseja retirar da lista negra (separados por vírgula ou um por linha).\n\n"
                "_Envie agora ou digite /cancelar:_"
            )
            await chat.send_message(prompt, parse_mode=ParseMode.MARKDOWN)
            return

        if data == "cfg:banned:view_all":
            banned_list = cfg.get("antispam", {}).get("banned_words", [])
            await query.answer()
            if not banned_list:
                msg_text = "🔤 *Lista de Palavras Proibidas:*\n_Nenhum termo cadastrado no momento._"
            else:
                formatted = "\n".join(f"• `{w}`" for w in banned_list)
                msg_text = f"🔤 *Lista Completa de Palavras Proibidas ({len(banned_list)}):*\n\n{formatted}"

            markup = InlineKeyboardMarkup([[InlineKeyboardButton("◀ Voltar", callback_data="cfg:sub:banned")]])
            await query.edit_message_text(msg_text, reply_markup=markup, parse_mode=ParseMode.MARKDOWN)
            return

        if data == "cfg:banned:clear_all":
            cfg.setdefault("antispam", {})["banned_words"] = []
            save_config(cfg)
            await query.answer("Todas as palavras proibidas foram apagadas!")
            text, markup = generate_sub_banned(cfg)
            await query.edit_message_text(text, reply_markup=markup, parse_mode=ParseMode.MARKDOWN)
            return

        # -------------------------------------------------------------
        # SEÇÃO: MENSAGENS REPETIDAS / PROGRAMADAS (CRONOGRAMA)
        # -------------------------------------------------------------
        if data == "cfg:rec:list" or data.startswith("cfg:rec:list:"):
            parts = data.split(":")
            page = int(parts[-1]) if len(parts) >= 4 and parts[-1].isdigit() else 1
            await query.answer()
            text, markup = generate_recurring_list(title, cfg, page=page)
            try:
                await query.edit_message_text(text, reply_markup=markup, parse_mode=ParseMode.MARKDOWN)
            except Exception:
                await query.edit_message_text(text, reply_markup=markup)
            return

        if data == "cfg:noop":
            await query.answer()
            return

        if data == "cfg:rec:add" or data.startswith("cfg:rec:add:"):
            parts = data.split(":")
            page = int(parts[-1]) if len(parts) >= 4 and parts[-1].isdigit() else 1
            rec_list = cfg.setdefault("recurring_messages", [])
            new_id = (max([m.get("id", 0) for m in rec_list] or [0])) + 1
            main_target = chat.id if chat.type in ("group", "supergroup") else cfg.get("main_group_id")
            new_item = {
                "id": new_id,
                "enabled": True,
                "text": "📢 Esta é uma mensagem programada automática! Personalize este texto como desejar.",
                "photo": None,
                "buttons": [],
                "repeat_mode": "interval",
                "interval_type": "hours",
                "interval_value": 24,
                "interval_minutes": 1440,
                "messages_interval": 50,
                "messages_counter_last": 0,
                "start_hour": None,
                "start_minute": None,
                "weekdays": [0, 1, 2, 3, 4, 5, 6],
                "month_days": [],
                "start_date": None,
                "end_date": None,
                "pin_message": False,
                "delete_previous": False,
                "auto_delete_seconds": 0,
                "last_message_id": None,
                "last_sent_timestamp": 0,
                "chat_id": main_target
            }
            rec_list.append(new_item)
            save_config(cfg)
            await query.answer(f"Mensagem #{new_id} criada!")
            text, markup = generate_recurring_detail(cfg, new_id, page=page)
            await query.edit_message_text(text, reply_markup=markup, parse_mode=ParseMode.MARKDOWN)
            return

        if data.startswith("cfg:rec:detail:"):
            parts = data.split(":")
            msg_id = int(parts[3])
            page = int(parts[4]) if len(parts) > 4 and parts[4].isdigit() else 1
            await query.answer()
            text, markup = generate_recurring_detail(cfg, msg_id, page=page)
            await query.edit_message_text(text, reply_markup=markup, parse_mode=ParseMode.MARKDOWN)
            return

        if data.startswith("cfg:rec:toggle:"):
            parts = data.split(":")
            msg_id = int(parts[3])
            page = int(parts[4]) if len(parts) > 4 and parts[4].isdigit() else None
            rec_list = cfg.get("recurring_messages", [])
            for m in rec_list:
                if m.get("id") == msg_id:
                    m["enabled"] = not m.get("enabled", True)
                    if not m.get("chat_id") or (isinstance(m.get("chat_id"), int) and m.get("chat_id") > 0):
                        m["chat_id"] = chat.id if chat.type in ("group", "supergroup") else cfg.get("main_group_id")
                    save_config(cfg)
                    await query.answer(f"Mensagem #{msg_id}: {'Ativada' if m['enabled'] else 'Desativada'}")
                    break
            if page is not None:
                text, markup = generate_recurring_list(title, cfg, page=page)
            else:
                text, markup = generate_recurring_detail(cfg, msg_id, page=1)
            await query.edit_message_text(text, reply_markup=markup, parse_mode=ParseMode.MARKDOWN)
            return

        if data.startswith("cfg:rec:del:"):
            parts = data.split(":")
            msg_id = int(parts[3])
            page = int(parts[4]) if len(parts) > 4 and parts[4].isdigit() else 1
            rec_list = cfg.get("recurring_messages", [])
            cfg["recurring_messages"] = [m for m in rec_list if m.get("id") != msg_id]
            save_config(cfg)
            await query.answer(f"Mensagem #{msg_id} apagada!")
            text, markup = generate_recurring_list(title, cfg, page=page)
            await query.edit_message_text(text, reply_markup=markup, parse_mode=ParseMode.MARKDOWN)
            return

        if data.startswith("cfg:rec:clone:"):
            parts = data.split(":")
            msg_id = int(parts[3])
            page = int(parts[4]) if len(parts) > 4 and parts[4].isdigit() else 1
            rec_list = cfg.setdefault("recurring_messages", [])
            orig_item = next((m for m in rec_list if m.get("id") == msg_id), None)
            if not orig_item:
                await query.answer("Mensagem não encontrada!", show_alert=True)
                return
            new_item = copy.deepcopy(orig_item)
            new_id = (max([m.get("id", 0) for m in rec_list] or [0])) + 1
            new_item["id"] = new_id
            orig_title = get_recurring_title(orig_item)
            new_item["title"] = f"{orig_title} (Cópia)"
            new_item["enabled"] = False  # Começa pausada para o admin escolher canal e horário
            new_item["last_message_id"] = None
            new_item["last_sent_timestamp"] = 0
            new_item["messages_counter_last"] = 0
            rec_list.append(new_item)
            save_config(cfg)
            await query.answer(f"📋 Mensagem duplicada com sucesso como #{new_id}!", show_alert=True)
            text, markup = generate_recurring_detail(cfg, new_id, page=page)
            await query.edit_message_text(text, reply_markup=markup, parse_mode=ParseMode.MARKDOWN)
            return

        if data.startswith("cfg:rec:preview:"):
            msg_id = int(data.split(":")[-1])
            rec_list = cfg.get("recurring_messages", [])
            msg_item = next((m for m in rec_list if m.get("id") == msg_id), None)
            if not msg_item:
                await query.answer("Mensagem não encontrada!", show_alert=True)
                return
            await query.answer("Enviando prévia no chat...")
            await chat.send_message("👁️ *Prévia da Mensagem Programada:*", parse_mode=ParseMode.MARKDOWN)
            try:
                await send_single_recurring_message(context.bot, msg_item, chat.id, job_queue=context.job_queue)
            except Exception as e_prev:
                await chat.send_message(f"❌ Não foi possível exibir a prévia: {e_prev}")
            return

        if data.startswith("cfg:rec:title:"):
            msg_id = int(data.split(":")[-1])
            self.pending_inputs[user.id] = {"action": "rec_title", "msg_id": msg_id, "chat_id": chat.id}
            await query.answer()
            prompt = (
                f"🏷️ *Definir Nome/Identificador para a Mensagem #{msg_id}:*\n\n"
                "Envie agora o nome que deseja dar a esta mensagem para identificá-la facilmente na lista "
                "(ex: `Aviso Canais VIP`, `Lembrete Semanal`, `Promoção Sibelius`):\n\n"
                "_(Ou envie 'limpar' para restaurar o nome padrão, ou /cancelar)_"
            )
            await chat.send_message(prompt, parse_mode=ParseMode.MARKDOWN)
            return

        if data.startswith("cfg:rec:pin:"):
            msg_id = int(data.split(":")[-1])
            rec_list = cfg.get("recurring_messages", [])
            for m in rec_list:
                if m.get("id") == msg_id:
                    m["pin_message"] = not m.get("pin_message", False)
                    save_config(cfg)
                    await query.answer(f"Fixar mensagem: {'Sim' if m['pin_message'] else 'Não'}")
                    break
            text, markup = generate_recurring_detail(cfg, msg_id)
            await query.edit_message_text(text, reply_markup=markup, parse_mode=ParseMode.MARKDOWN)
            return

        if data.startswith("cfg:rec:delprev:"):
            msg_id = int(data.split(":")[-1])
            rec_list = cfg.get("recurring_messages", [])
            for m in rec_list:
                if m.get("id") == msg_id:
                    m["delete_previous"] = not m.get("delete_previous", False)
                    save_config(cfg)
                    await query.answer(f"Deletar anterior: {'Sim' if m['delete_previous'] else 'Não'}")
                    break
            text, markup = generate_recurring_detail(cfg, msg_id)
            await query.edit_message_text(text, reply_markup=markup, parse_mode=ParseMode.MARKDOWN)
            return

        if data.startswith("cfg:rec:hour_menu:"):
            msg_id = int(data.split(":")[-1])
            await query.answer()
            text, markup = generate_recurring_hour_menu(msg_id)
            await query.edit_message_text(text, reply_markup=markup, parse_mode=ParseMode.MARKDOWN)
            return

        if data.startswith("cfg:rec:set_h:"):
            parts = data.split(":")
            msg_id = int(parts[3])
            hour = int(parts[4])
            await query.answer()
            text, markup = generate_recurring_minute_menu(msg_id, hour)
            await query.edit_message_text(text, reply_markup=markup, parse_mode=ParseMode.MARKDOWN)
            return

        if data.startswith("cfg:rec:set_m:"):
            parts = data.split(":")
            msg_id = int(parts[3])
            hour = int(parts[4])
            minute = int(parts[5])
            rec_list = cfg.get("recurring_messages", [])
            for m in rec_list:
                if m.get("id") == msg_id:
                    m["start_hour"] = hour
                    m["start_minute"] = minute
                    m["last_fired_slot"] = None
                    m["last_sent_timestamp"] = 0
                    break
            save_config(cfg)
            await query.answer(f"Horário de início definido para {hour:02d}:{minute:02d}!")
            text, markup = generate_recurring_detail(cfg, msg_id)
            await query.edit_message_text(text, reply_markup=markup, parse_mode=ParseMode.MARKDOWN)
            return

        if data.startswith("cfg:rec:rep_menu:"):
            msg_id = int(data.split(":")[-1])
            await query.answer()
            text, markup = generate_recurring_rep_menu(cfg, msg_id)
            await query.edit_message_text(text, reply_markup=markup, parse_mode=ParseMode.MARKDOWN)
            return

        if data.startswith("cfg:rec:set_inth:"):
            parts = data.split(":")
            msg_id = int(parts[3])
            h = int(parts[4])
            rec_list = cfg.get("recurring_messages", [])
            for m in rec_list:
                if m.get("id") == msg_id:
                    m["repeat_mode"] = "interval"
                    m["interval_type"] = "hours"
                    m["interval_value"] = h
                    m["interval_minutes"] = h * 60
                    break
            save_config(cfg)
            await query.answer(f"Repetição: A cada {h} hora{'s' if h > 1 else ''}!")
            text, markup = generate_recurring_rep_menu(cfg, msg_id)
            await query.edit_message_text(text, reply_markup=markup, parse_mode=ParseMode.MARKDOWN)
            return

        if data.startswith("cfg:rec:set_intm:"):
            parts = data.split(":")
            msg_id = int(parts[3])
            m_val = int(parts[4])
            rec_list = cfg.get("recurring_messages", [])
            for m in rec_list:
                if m.get("id") == msg_id:
                    m["repeat_mode"] = "interval"
                    m["interval_type"] = "minutes"
                    m["interval_value"] = m_val
                    m["interval_minutes"] = m_val
                    break
            save_config(cfg)
            await query.answer(f"Repetição: A cada {m_val} minuto{'s' if m_val > 1 else ''}!")
            text, markup = generate_recurring_rep_menu(cfg, msg_id)
            await query.edit_message_text(text, reply_markup=markup, parse_mode=ParseMode.MARKDOWN)
            return

        if data.startswith("cfg:rec:msg_menu:"):
            msg_id = int(data.split(":")[-1])
            await query.answer()
            text, markup = generate_recurring_msg_menu(cfg, msg_id)
            await query.edit_message_text(text, reply_markup=markup, parse_mode=ParseMode.MARKDOWN)
            return

        if data.startswith("cfg:rec:set_mcnt:"):
            parts = data.split(":")
            msg_id = int(parts[3])
            cnt = int(parts[4])
            rec_list = cfg.get("recurring_messages", [])
            for m in rec_list:
                if m.get("id") == msg_id:
                    m["repeat_mode"] = "messages"
                    m["messages_interval"] = cnt
                    break
            save_config(cfg)
            await query.answer(f"Repetição: A cada {cnt} mensagens!")
            text, markup = generate_recurring_msg_menu(cfg, msg_id)
            await query.edit_message_text(text, reply_markup=markup, parse_mode=ParseMode.MARKDOWN)
            return

        if data.startswith("cfg:rec:in_mcnt:"):
            msg_id = int(data.split(":")[-1])
            self.pending_inputs[user.id] = {"action": "rec_msg_cnt", "msg_id": msg_id, "chat_id": chat.id}
            await query.answer()
            prompt = (
                f"💬 *Digite a quantidade de mensagens no grupo para acionar a Mensagem #{msg_id}:*\n\n"
                "Exemplo: `50` para postar a cada 50 mensagens enviadas no grupo.\n"
                "_Envie o número agora (ou digite /cancelar para desistir):_"
            )
            await chat.send_message(prompt, parse_mode=ParseMode.MARKDOWN)
            return

        if data.startswith("cfg:rec:wday_menu:"):
            msg_id = int(data.split(":")[-1])
            await query.answer()
            text, markup = generate_recurring_wday_menu(cfg, msg_id)
            await query.edit_message_text(text, reply_markup=markup, parse_mode=ParseMode.MARKDOWN)
            return

        if data.startswith("cfg:rec:tog_wday:"):
            parts = data.split(":")
            msg_id = int(parts[3])
            idx = int(parts[4])
            rec_list = cfg.get("recurring_messages", [])
            for m in rec_list:
                if m.get("id") == msg_id:
                    wd = m.setdefault("weekdays", [0, 1, 2, 3, 4, 5, 6])
                    if idx in wd:
                        wd.remove(idx)
                    else:
                        wd.append(idx)
                    wd.sort()
                    break
            save_config(cfg)
            await query.answer()
            text, markup = generate_recurring_wday_menu(cfg, msg_id)
            await query.edit_message_text(text, reply_markup=markup, parse_mode=ParseMode.MARKDOWN)
            return

        if data.startswith("cfg:rec:wday_p:"):
            parts = data.split(":")
            msg_id = int(parts[3])
            preset = parts[4]
            rec_list = cfg.get("recurring_messages", [])
            for m in rec_list:
                if m.get("id") == msg_id:
                    if preset == "all":
                        m["weekdays"] = [0, 1, 2, 3, 4, 5, 6]
                    elif preset == "work":
                        m["weekdays"] = [0, 1, 2, 3, 4]
                    elif preset == "weekend":
                        m["weekdays"] = [5, 6]
                    break
            save_config(cfg)
            await query.answer("Dias da semana atualizados!")
            text, markup = generate_recurring_wday_menu(cfg, msg_id)
            await query.edit_message_text(text, reply_markup=markup, parse_mode=ParseMode.MARKDOWN)
            return

        if data.startswith("cfg:rec:mday_menu:"):
            msg_id = int(data.split(":")[-1])
            await query.answer()
            text, markup = generate_recurring_mday_menu(cfg, msg_id)
            await query.edit_message_text(text, reply_markup=markup, parse_mode=ParseMode.MARKDOWN)
            return

        if data.startswith("cfg:rec:tog_mday:"):
            parts = data.split(":")
            msg_id = int(parts[3])
            d = int(parts[4])
            rec_list = cfg.get("recurring_messages", [])
            for m in rec_list:
                if m.get("id") == msg_id:
                    md = m.get("month_days")
                    if md is None or len(md) >= 31 or not md:
                        md = list(range(1, 32))
                    if d in md:
                        md.remove(d)
                    else:
                        md.append(d)
                    md.sort()
                    m["month_days"] = md
                    break
            save_config(cfg)
            await query.answer()
            text, markup = generate_recurring_mday_menu(cfg, msg_id)
            await query.edit_message_text(text, reply_markup=markup, parse_mode=ParseMode.MARKDOWN)
            return

        if data.startswith("cfg:rec:mday_p:"):
            parts = data.split(":")
            msg_id = int(parts[3])
            preset = parts[4]
            rec_list = cfg.get("recurring_messages", [])
            for m in rec_list:
                if m.get("id") == msg_id:
                    if preset == "all":
                        m["month_days"] = []
                    elif preset == "1_15":
                        m["month_days"] = [1, 15]
                    elif preset == "1":
                        m["month_days"] = [1]
                    break
            save_config(cfg)
            await query.answer("Dias do mês atualizados!")
            text, markup = generate_recurring_mday_menu(cfg, msg_id)
            await query.edit_message_text(text, reply_markup=markup, parse_mode=ParseMode.MARKDOWN)
            return

        if data.startswith("cfg:rec:autodel_menu:"):
            msg_id = int(data.split(":")[-1])
            await query.answer()
            text, markup = generate_recurring_autodel_menu(cfg, msg_id)
            await query.edit_message_text(text, reply_markup=markup, parse_mode=ParseMode.MARKDOWN)
            return

        if data.startswith("cfg:rec:set_adel:"):
            parts = data.split(":")
            msg_id = int(parts[3])
            sec = int(parts[4])
            rec_list = cfg.get("recurring_messages", [])
            for m in rec_list:
                if m.get("id") == msg_id:
                    m["auto_delete_seconds"] = sec
                    break
            save_config(cfg)
            lbl = format_autodel_display(sec) if sec > 0 else "Desativado"
            await query.answer(f"Exclusão cronometrada: {lbl}")
            text, markup = generate_recurring_autodel_menu(cfg, msg_id)
            await query.edit_message_text(text, reply_markup=markup, parse_mode=ParseMode.MARKDOWN)
            return

        if data.startswith("cfg:rec:edit:"):
            parts = data.split(":")
            msg_id = int(parts[3])
            page = int(parts[4]) if len(parts) > 4 and parts[4].isdigit() else 1
            await query.answer()
            text, markup = generate_recurring_edit_menu(cfg, msg_id, page=page)
            await query.edit_message_text(text, reply_markup=markup, parse_mode=ParseMode.MARKDOWN)
            return

        if data.startswith("cfg:rec:dstart:"):
            msg_id = int(data.split(":")[-1])
            await query.answer()
            text, markup = generate_recurring_date_menu(cfg, msg_id, is_start=True)
            await query.edit_message_text(text, reply_markup=markup, parse_mode=ParseMode.MARKDOWN)
            return

        if data.startswith("cfg:rec:dend:"):
            msg_id = int(data.split(":")[-1])
            await query.answer()
            text, markup = generate_recurring_date_menu(cfg, msg_id, is_start=False)
            await query.edit_message_text(text, reply_markup=markup, parse_mode=ParseMode.MARKDOWN)
            return

        if data.startswith("cfg:rec:dstart_today:"):
            msg_id = int(data.split(":")[-1])
            today_str = datetime.now().strftime("%Y-%m-%d")
            for m in cfg.get("recurring_messages", []):
                if m.get("id") == msg_id:
                    m["start_date"] = today_str
                    break
            save_config(cfg)
            await query.answer(f"Data de início: {today_str}")
            text, markup = generate_recurring_date_menu(cfg, msg_id, is_start=True)
            await query.edit_message_text(text, reply_markup=markup, parse_mode=ParseMode.MARKDOWN)
            return

        if data.startswith("cfg:rec:dend_today:"):
            msg_id = int(data.split(":")[-1])
            today_str = datetime.now().strftime("%Y-%m-%d")
            for m in cfg.get("recurring_messages", []):
                if m.get("id") == msg_id:
                    m["end_date"] = today_str
                    break
            save_config(cfg)
            await query.answer(f"Data final: {today_str}")
            text, markup = generate_recurring_date_menu(cfg, msg_id, is_start=False)
            await query.edit_message_text(text, reply_markup=markup, parse_mode=ParseMode.MARKDOWN)
            return

        if data.startswith("cfg:rec:dstart_clear:"):
            msg_id = int(data.split(":")[-1])
            for m in cfg.get("recurring_messages", []):
                if m.get("id") == msg_id:
                    m["start_date"] = None
                    break
            save_config(cfg)
            await query.answer("Data de início limpa!")
            text, markup = generate_recurring_date_menu(cfg, msg_id, is_start=True)
            await query.edit_message_text(text, reply_markup=markup, parse_mode=ParseMode.MARKDOWN)
            return

        if data.startswith("cfg:rec:dend_clear:"):
            msg_id = int(data.split(":")[-1])
            for m in cfg.get("recurring_messages", []):
                if m.get("id") == msg_id:
                    m["end_date"] = None
                    break
            save_config(cfg)
            await query.answer("Data final limpa!")
            text, markup = generate_recurring_date_menu(cfg, msg_id, is_start=False)
            await query.edit_message_text(text, reply_markup=markup, parse_mode=ParseMode.MARKDOWN)
            return

        if data.startswith("cfg:rec:dstart_input:"):
            msg_id = int(data.split(":")[-1])
            self.pending_inputs[user.id] = {"action": "rec_dstart", "msg_id": msg_id, "chat_id": chat.id}
            await query.answer()
            prompt = (
                f"📅 *Digite a Data de Início para a Mensagem #{msg_id}:*\n\n"
                "Formato: `DD/MM/AAAA` (Ex: `15/10/2026`)\n"
                "_Envie a data agora (ou digite /cancelar para desistir):_"
            )
            await chat.send_message(prompt, parse_mode=ParseMode.MARKDOWN)
            return

        if data.startswith("cfg:rec:dend_input:"):
            msg_id = int(data.split(":")[-1])
            self.pending_inputs[user.id] = {"action": "rec_dend", "msg_id": msg_id, "chat_id": chat.id}
            await query.answer()
            prompt = (
                f"📅 *Digite a Data Final para a Mensagem #{msg_id}:*\n\n"
                "Formato: `DD/MM/AAAA` (Ex: `31/12/2026`)\n"
                "_Envie a data agora (ou digite /cancelar para desistir):_"
            )
            await chat.send_message(prompt, parse_mode=ParseMode.MARKDOWN)
            return

        if data.startswith("cfg:rec:test:"):
            msg_id = int(data.split(":")[-1])
            rec_list = cfg.get("recurring_messages", [])
            msg_item = next((m for m in rec_list if m.get("id") == msg_id), None)
            if msg_item:
                target_chat_id = msg_item.get("chat_id")
                main_group_id = cfg.get("main_group_id")
                if (not target_chat_id or (isinstance(target_chat_id, int) and target_chat_id > 0)) and main_group_id:
                    target_chat_id = main_group_id
                elif not target_chat_id:
                    target_chat_id = chat.id

                try:
                    await query.answer("Disparando teste...")

                    # 1. Envia uma cópia de teste AQUI MESMO no chat privado para o admin ver o resultado!
                    await chat.send_message("👁️ *Prévia da Mensagem (Como será exibida):*", parse_mode=ParseMode.MARKDOWN)
                    await send_single_recurring_message(context.bot, msg_item, chat.id, job_queue=context.job_queue)

                    # 2. Se houver grupo vinculado (diferente do chat privado), envia para o grupo também!
                    if target_chat_id and target_chat_id != chat.id:
                        await send_single_recurring_message(context.bot, msg_item, target_chat_id, job_queue=context.job_queue)
                        await chat.send_message(f"✅ Mensagem de teste #{msg_id} enviada com sucesso para o grupo vinculado!")
                    else:
                        await chat.send_message(f"✅ Teste concluído com sucesso!")
                except Exception as e:
                    await chat.send_message(f"❌ Erro ao enviar mensagem de teste #{msg_id}: {e}")
            return

        if data.startswith("cfg:quick_save_rec:"):
            msg_id = int(data.split(":")[-1])
            captured = self.last_received_private_messages.get(user.id)
            if not captured:
                await query.answer("Nenhuma mensagem recente encontrada.", show_alert=True)
                return

            rec_list = cfg.setdefault("recurring_messages", [])
            target_item = next((m for m in rec_list if m.get("id") == msg_id), None)
            if not target_item:
                target_item = {
                    "id": msg_id,
                    "enabled": True,
                    "text": captured.get("text") or "📢 Postagem Programada",
                    "photo": captured.get("photo"),
                    "buttons": captured.get("buttons") or [],
                    "repeat_mode": "interval",
                    "interval_type": "hours",
                    "interval_value": 24,
                    "interval_minutes": 1440,
                    "messages_interval": 50,
                    "messages_counter_last": 0,
                    "start_hour": None,
                    "start_minute": None,
                    "weekdays": [0, 1, 2, 3, 4, 5, 6],
                    "month_days": [],
                    "start_date": None,
                    "end_date": None,
                    "pin_message": False,
                    "delete_previous": False,
                    "auto_delete_seconds": 0,
                    "last_message_id": None,
                    "last_sent_timestamp": 0,
                    "chat_id": cfg.get("main_group_id")
                }
                rec_list.append(target_item)
            else:
                if captured.get("text") and captured.get("text") != "📢 Postagem da Comunidade":
                    target_item["text"] = captured["text"]
                if captured.get("photo"):
                    target_item["photo"] = captured["photo"]
                if captured.get("buttons"):
                    target_item["buttons"] = captured["buttons"]
                    target_item.pop("source_chat_id", None)
                    target_item.pop("source_message_id", None)
                    target_item.pop("backup_chat_id", None)
                    target_item.pop("backup_message_id", None)
                elif captured.get("source_chat_id") and captured.get("source_message_id") and captured.get("source_chat_id") < 0:
                    target_item["source_chat_id"] = captured["source_chat_id"]
                    target_item["source_message_id"] = captured["source_message_id"]
                    target_item["backup_chat_id"] = captured.get("backup_chat_id")
                    target_item["backup_message_id"] = captured.get("backup_message_id")

            save_config(cfg)
            await query.answer(f"Mensagem #{msg_id} salva com sucesso!")
            markup = InlineKeyboardMarkup([
                [InlineKeyboardButton("⚙️ Voltar à Mensagem", callback_data=f"cfg:rec:detail:{msg_id}")],
                [InlineKeyboardButton("🚀 Testar Envio Agora", callback_data=f"cfg:rec:test:{msg_id}")],
                [InlineKeyboardButton("📋 Lista de Mensagens", callback_data="cfg:rec:list")]
            ])
            try:
                await query.edit_message_text(
                    f"✅ *Mensagem Programada #{msg_id} configurada e pronta para envio!*\n\n"
                    "O texto, artigo expansível, mídias e botões foram vinculados com perfeição.",
                    parse_mode=ParseMode.MARKDOWN,
                    reply_markup=markup
                )
            except Exception:
                await query.edit_message_text(
                    f"✅ Mensagem Programada #{msg_id} configurada e pronta para envio!",
                    reply_markup=markup
                )
            return

        if data == "cfg:quick_save_welcome":
            captured = self.last_received_private_messages.get(user.id)
            if not captured:
                await query.answer("Nenhuma mensagem recente encontrada.", show_alert=True)
                return

            w_cfg = cfg.setdefault("welcome", {})
            if captured.get("text"):
                w_cfg["message"] = captured["text"]
            if captured.get("photo"):
                w_cfg["photo"] = captured["photo"]
            if captured.get("buttons"):
                w_cfg["buttons"] = captured["buttons"]

            save_config(cfg)
            await query.answer("Boas-vindas atualizadas com sucesso!")
            markup = InlineKeyboardMarkup([
                [InlineKeyboardButton("👁️ Visualizar Boas-Vindas", callback_data="cfg:preview:welcome")],
                [InlineKeyboardButton("🔙 Menu Boas-Vindas", callback_data="cfg:sub:welcome")]
            ])
            try:
                await query.edit_message_text(
                    "✅ *Boas-Vindas atualizadas com sucesso!*\n\nA nova postagem rica foi definida.",
                    parse_mode=ParseMode.MARKDOWN,
                    reply_markup=markup
                )
            except Exception:
                await query.edit_message_text(
                    "✅ Boas-Vindas atualizadas com sucesso!",
                    reply_markup=markup
                )
            return

        if data == "cfg:chats:list":
            text, markup = generate_chats_list_page(cfg)
            await query.edit_message_text(text, reply_markup=markup, parse_mode=ParseMode.MARKDOWN)
            return

        if data == "cfg:chats:how_to":
            await query.answer()
            help_text = (
                "🌐 ═══════════════════ 🌐\n"
                "   *COMO VINCULAR GRUPOS E CANAIS*\n"
                "🌐 ═══════════════════ 🌐\n\n"
                "👥 *Para Vincular um Grupo:*\n"
                "1. Adicione o Maestro Bot no grupo.\n"
                "2. Promova o bot a *Administrador* com permissões padrão.\n"
                "3. Envie o comando `/setgrupo` dentro do grupo.\n"
                "4. Pronto! O grupo estará registrado na orquestração.\n\n"
                "📢 *Para Vincular um Canal:*\n"
                "1. Adicione o Maestro Bot no seu canal como *Administrador*.\n"
                "2. No privado do bot, envie:\n"
                "   `/setcanal @seucanal`\n"
                "   ou pelo ID: `/setcanal -1001234567890`\n"
                "3. Pronto! O canal estará pronto para transmissões.\n\n"
                "💡 *Dica:* Você pode vincular quantos grupos e canais desejar!"
            )
            markup = InlineKeyboardMarkup([
                [InlineKeyboardButton("◀ Voltar à Lista de Chats", callback_data="cfg:chats:list")]
            ])
            await query.edit_message_text(help_text, reply_markup=markup, parse_mode=ParseMode.MARKDOWN)
            return

        if data.startswith("cfg:chat:info:") or data.startswith("cfg:chats:info:"):
            parts = data.split(":")
            chat_type = parts[3]
            target_id = parts[4]
            await query.answer()
            text, markup = generate_sub_chat_info(cfg, chat_type, target_id)
            await query.edit_message_text(text, reply_markup=markup, parse_mode=ParseMode.MARKDOWN)
            return

        if data.startswith("cfg:chat:set_main:"):
            parts = data.split(":")
            chat_type = parts[3]
            target_id = int(parts[4])
            if chat_type == "grp":
                cfg["main_group_id"] = target_id
                save_config(cfg)
                await query.answer("⭐️ Grupo definido como Principal!", show_alert=True)
            else:
                cfg["main_channel_id"] = target_id
                save_config(cfg)
                await query.answer("⭐️ Canal definido como Principal!", show_alert=True)
            text, markup = generate_sub_chat_info(cfg, chat_type, target_id)
            await query.edit_message_text(text, reply_markup=markup, parse_mode=ParseMode.MARKDOWN)
            return

        if data.startswith("cfg:chat:unlink:"):
            parts = data.split(":")
            chat_type = parts[3]
            target_id = int(parts[4])
            if chat_type == "grp":
                from config import remove_linked_group
                remove_linked_group(cfg, target_id)
                await query.answer("Grupo desvinculado com sucesso!", show_alert=True)
            else:
                from config import remove_linked_channel
                remove_linked_channel(cfg, target_id)
                await query.answer("Canal desvinculado com sucesso!", show_alert=True)
            text, markup = generate_chats_list_page(cfg)
            await query.edit_message_text(text, reply_markup=markup, parse_mode=ParseMode.MARKDOWN)
            return

        if data.startswith("cfg:chat:post_prompt:"):
            cid = data.split(":")[-1]
            await query.answer()
            prompt = (
                f"📢 *Como Enviar Mensagem para o Canal (`{cid}`):*\n\n"
                "Envie o comando no chat privado:\n"
                "`/canal [Sua mensagem aqui]`\n\n"
                "✨ *Suporta Formatação Total:*\n"
                "• **Negrito**, *itálico*, `código`, ||spoiler||\n"
                "• Citações expansíveis com `>>`\n"
                "• Botões com links em colunas: `[Site - https://...] [Canal - https://...]`\n"
                "• Fotos com legenda formatada!"
            )
            markup = InlineKeyboardMarkup([
                [InlineKeyboardButton("◀ Voltar ao Canal", callback_data=f"cfg:chat:info:chn:{cid}")]
            ])
            await chat.send_message(prompt, parse_mode=ParseMode.MARKDOWN, reply_markup=markup)
            return

        if data.startswith("cfg:rec:target_help:"):
            msg_id = int(data.split(":")[-1])
            rec_list = cfg.get("recurring_messages", [])
            msg_item = next((m for m in rec_list if m.get("id") == msg_id), None)
            target_chat_id = msg_item.get("chat_id") if msg_item else None
            topic_id = msg_item.get("message_thread_id") if msg_item else None

            groups = cfg.get("linked_groups", [])
            channels = cfg.get("linked_channels", [])

            help_text = (
                f"🎯 *Destino da Mensagem Recorrente #{msg_id}*\n\n"
                f"Selecione abaixo em qual grupo ou canal você deseja que esta postagem programada seja enviada automaticamente:\n\n"
                f"• *Destino atual:* `{target_chat_id or 'Grupo Principal'}`\n"
                f"• *Tópico do fórum:* `{topic_id or 'Geral'}`"
            )

            kb = []
            kb.append([
                InlineKeyboardButton("🌐 Todos (Grupos + Canais)", callback_data=f"cfg:rec:set_target:{msg_id}:all"),
            ])
            if groups and channels:
                kb.append([
                    InlineKeyboardButton("👥 Todos os Grupos", callback_data=f"cfg:rec:set_target:{msg_id}:all_groups"),
                    InlineKeyboardButton("📢 Todos os Canais", callback_data=f"cfg:rec:set_target:{msg_id}:all_channels")
                ])

            for g in groups:
                gid = g.get("id")
                gtit = g.get("title", f"Grupo {gid}")
                sel = " ✅" if target_chat_id == gid else ""
                kb.append([InlineKeyboardButton(f"👥 {gtit}{sel}", callback_data=f"cfg:rec:set_target:{msg_id}:{gid}")])

            for c in channels:
                cid = c.get("id")
                ctit = c.get("title", f"Canal {cid}")
                sel = " ✅" if target_chat_id == cid else ""
                kb.append([InlineKeyboardButton(f"📢 {ctit}{sel}", callback_data=f"cfg:rec:set_target:{msg_id}:{cid}")])

            kb.append([InlineKeyboardButton("🔙 Voltar", callback_data=f"cfg:rec:detail:{msg_id}")])
            await query.edit_message_text(help_text, reply_markup=InlineKeyboardMarkup(kb), parse_mode=ParseMode.MARKDOWN)
            await query.answer()
            return

        if data.startswith("cfg:rec:set_target:"):
            parts = data.split(":")
            msg_id = int(parts[3])
            target_val = parts[4]
            if target_val.startswith("-") or target_val.isdigit():
                target_val = int(target_val)
            rec_list = cfg.setdefault("recurring_messages", [])
            for m in rec_list:
                if m.get("id") == msg_id:
                    m["chat_id"] = target_val
                    save_config(cfg)
                    break
            await query.answer("🎯 Destino atualizado com sucesso!")
            text, markup = generate_recurring_detail(cfg, msg_id)
            await query.edit_message_text(text, reply_markup=markup, parse_mode=ParseMode.MARKDOWN)
            return

        if data.startswith("cfg:rec:text:"):
            msg_id = int(data.split(":")[-1])
            self.pending_inputs[user.id] = {"action": "rec_text", "msg_id": msg_id, "chat_id": chat.id}
            await query.answer()
            prompt = (
                f"✏️ *Digite o texto da Mensagem Programada #{msg_id}:*\n\n"
                "_Envie sua mensagem agora (ou digite /cancelar para desistir):_"
            )
            await chat.send_message(prompt, parse_mode=ParseMode.MARKDOWN)
            return

        if data.startswith("cfg:rec:photo:"):
            msg_id = int(data.split(":")[-1])
            self.pending_inputs[user.id] = {"action": "rec_photo", "msg_id": msg_id, "chat_id": chat.id}
            await query.answer()
            prompt = (
                f"🖼️ *Envie a foto ou imagem para a Mensagem Programada #{msg_id}:*\n\n"
                "_Envie a foto pelo chat agora (ou digite /cancelar para desistir):_"
            )
            await chat.send_message(prompt, parse_mode=ParseMode.MARKDOWN)
            return

        if data.startswith("cfg:rec:delphoto:"):
            parts = data.split(":")
            msg_id = int(parts[3])
            page = int(parts[4]) if len(parts) > 4 and parts[4].isdigit() else 1
            rec_list = cfg.get("recurring_messages", [])
            for m in rec_list:
                if m.get("id") == msg_id:
                    m["photo"] = None
                    save_config(cfg)
                    await query.answer("Foto removida!")
                    break
            text, markup = generate_recurring_edit_menu(cfg, msg_id, page=page)
            await query.edit_message_text(text, reply_markup=markup, parse_mode=ParseMode.MARKDOWN)
            return

        if data.startswith("cfg:rec:buttons:"):
            msg_id = int(data.split(":")[-1])
            self.pending_inputs[user.id] = {"action": "rec_buttons", "msg_id": msg_id, "chat_id": chat.id}
            await query.answer()
            prompt = (
                f"🔘 *Configure os Botões para a Mensagem Programada #{msg_id}:*\n\n"
                "💡 *Suporta Múltiplas Colunas (Lado a Lado):*\n"
                "• *Na mesma linha (Colunas):*\n"
                "`[Botão 1 - https://link1.com] [Botão 2 - https://link2.com]`\n"
                "`[Banda Sinfônica - link] [Bases Cifradas - link] [Big & Band - link]`\n\n"
                "• *Ou com && na mesma linha:*\n"
                "`Botão 1 | link1 && Botão 2 | link2`\n\n"
                "• *Um embaixo do outro:*\n"
                "`Botão 1 | https://link1.com`\n"
                "`Botão 2 | https://link2.com`\n\n"
                "_(Envie a lista agora, ou digite 'remover' para limpar todos, ou /cancelar)_"
            )
            await chat.send_message(prompt, parse_mode=ParseMode.MARKDOWN)
            return

        if data.startswith("cfg:rec:article:"):
            msg_id = int(data.split(":")[-1])
            self.pending_inputs[user.id] = {"action": "rec_article", "msg_id": msg_id, "chat_id": chat.id}
            await query.answer()
            prompt = (
                f"📄 *Definir Artigo / Instant View para a Mensagem #{msg_id}:*\n\n"
                "Envie o link do artigo (ex: Telegraph ou página web):\n"
                "`https://telegra.ph/Principais-Canais-e-Grupos...`\n\n"
                "O bot exibirá a prévia do artigo no topo da mensagem programada!\n\n"
                "_(Envie o link agora, ou 'remover' para limpar, ou /cancelar)_"
            )
            await chat.send_message(prompt, parse_mode=ParseMode.MARKDOWN)
            return

        if data.startswith("cfg:rec:delbuttons:"):
            parts = data.split(":")
            msg_id = int(parts[3])
            page = int(parts[4]) if len(parts) > 4 and parts[4].isdigit() else 1
            rec_list = cfg.get("recurring_messages", [])
            for m in rec_list:
                if m.get("id") == msg_id:
                    m["buttons"] = []
                    save_config(cfg)
                    await query.answer("Botões removidos!")
                    break
            text, markup = generate_recurring_edit_menu(cfg, msg_id, page=page)
            await query.edit_message_text(text, reply_markup=markup, parse_mode=ParseMode.MARKDOWN)
            return

        # -------------------------------------------------------------
        # SEÇÃO: RESPOSTAS AUTOMÁTICAS (REGEX & PALAVRAS)
        # -------------------------------------------------------------
        if data == "cfg:resp:list":
            await query.answer()
            text, markup = generate_auto_responder_list(title, cfg)
            await query.edit_message_text(text, reply_markup=markup, parse_mode=ParseMode.MARKDOWN)
            return

        if data == "cfg:resp:add":
            responders = cfg.setdefault("auto_responses", [])
            new_id = (max([r.get("id", 0) for r in responders] or [0])) + 1
            new_item = {
                "id": new_id,
                "title": f"Resposta #{new_id}",
                "pattern": "(?i)ajuda|duvida",
                "is_regex": True,
                "text": "👋 Olá, {name}! Como posso te ajudar hoje no grupo {group}?",
                "photo": None,
                "buttons": [],
                "cooldown_seconds": 30,
                "reply_to": True,
                "delete_trigger": False,
                "enabled": True
            }
            responders.append(new_item)
            save_config(cfg)
            if self.auto_responder_handler:
                self.auto_responder_handler.invalidate_cache(new_id)
            await query.answer(f"Resposta #{new_id} criada!")
            text, markup = generate_auto_responder_detail(cfg, new_id)
            await query.edit_message_text(text, reply_markup=markup, parse_mode=ParseMode.MARKDOWN)
            return

        if data.startswith("cfg:resp:detail:"):
            resp_id = int(data.split(":")[-1])
            await query.answer()
            text, markup = generate_auto_responder_detail(cfg, resp_id)
            await query.edit_message_text(text, reply_markup=markup, parse_mode=ParseMode.MARKDOWN)
            return

        if data.startswith("cfg:resp:toggle:"):
            resp_id = int(data.split(":")[-1])
            responders = cfg.get("auto_responses", [])
            for r in responders:
                if r.get("id") == resp_id:
                    r["enabled"] = not r.get("enabled", True)
                    save_config(cfg)
                    await query.answer(f"Resposta #{resp_id}: {'Ativada' if r['enabled'] else 'Desativada'}")
                    break
            text, markup = generate_auto_responder_detail(cfg, resp_id)
            await query.edit_message_text(text, reply_markup=markup, parse_mode=ParseMode.MARKDOWN)
            return

        if data.startswith("cfg:resp:del:"):
            resp_id = int(data.split(":")[-1])
            responders = cfg.get("auto_responses", [])
            cfg["auto_responses"] = [r for r in responders if r.get("id") != resp_id]
            save_config(cfg)
            if self.auto_responder_handler:
                self.auto_responder_handler.invalidate_cache(resp_id)
            await query.answer(f"Resposta #{resp_id} excluída!")
            text, markup = generate_auto_responder_list(title, cfg)
            await query.edit_message_text(text, reply_markup=markup, parse_mode=ParseMode.MARKDOWN)
            return

        if data.startswith("cfg:resp:cycle_cd:"):
            resp_id = int(data.split(":")[-1])
            responders = cfg.get("auto_responses", [])
            for r in responders:
                if r.get("id") == resp_id:
                    cur_cd = r.get("cooldown_seconds", 30)
                    cycle = [5, 10, 15, 30, 60, 120]
                    next_cd = cycle[(cycle.index(cur_cd) + 1) % len(cycle)] if cur_cd in cycle else 30
                    r["cooldown_seconds"] = next_cd
                    save_config(cfg)
                    await query.answer(f"Cooldown: {next_cd}s")
                    break
            text, markup = generate_auto_responder_detail(cfg, resp_id)
            await query.edit_message_text(text, reply_markup=markup, parse_mode=ParseMode.MARKDOWN)
            return

        if data.startswith("cfg:resp:cycle_delay:"):
            resp_id = int(data.split(":")[-1])
            responders = cfg.get("auto_responses", [])
            for r in responders:
                if r.get("id") == resp_id:
                    cur_delay = r.get("delay_seconds", 0)
                    cycle = [0, 5, 10, 15, 20, 30]
                    next_delay = cycle[(cycle.index(cur_delay) + 1) % len(cycle)] if cur_delay in cycle else 0
                    r["delay_seconds"] = next_delay
                    save_config(cfg)
                    delay_msg = f"{next_delay}s" if next_delay > 0 else "Imediato (0s)"
                    await query.answer(f"Espera / Delay: {delay_msg}")
                    break
            text, markup = generate_auto_responder_detail(cfg, resp_id)
            await query.edit_message_text(text, reply_markup=markup, parse_mode=ParseMode.MARKDOWN)
            return

        if data.startswith("cfg:resp:toggle_regex:"):
            resp_id = int(data.split(":")[-1])
            responders = cfg.get("auto_responses", [])
            for r in responders:
                if r.get("id") == resp_id:
                    r["is_regex"] = not r.get("is_regex", True)
                    save_config(cfg)
                    if self.auto_responder_handler:
                        self.auto_responder_handler.invalidate_cache(resp_id)
                    mode_label = "Regex" if r["is_regex"] else "Palavra Simples"
                    await query.answer(f"Modo: {mode_label}")
                    break
            text, markup = generate_auto_responder_detail(cfg, resp_id)
            await query.edit_message_text(text, reply_markup=markup, parse_mode=ParseMode.MARKDOWN)
            return

        if data.startswith("cfg:resp:toggle_reply:"):
            resp_id = int(data.split(":")[-1])
            responders = cfg.get("auto_responses", [])
            for r in responders:
                if r.get("id") == resp_id:
                    r["reply_to"] = not r.get("reply_to", True)
                    save_config(cfg)
                    await query.answer(f"Responder citando: {'Sim' if r['reply_to'] else 'Não'}")
                    break
            text, markup = generate_auto_responder_detail(cfg, resp_id)
            await query.edit_message_text(text, reply_markup=markup, parse_mode=ParseMode.MARKDOWN)
            return

        if data.startswith("cfg:resp:toggle_del_trig:"):
            resp_id = int(data.split(":")[-1])
            responders = cfg.get("auto_responses", [])
            for r in responders:
                if r.get("id") == resp_id:
                    r["delete_trigger"] = not r.get("delete_trigger", False)
                    save_config(cfg)
                    await query.answer(f"Apagar gatilho do usuário: {'Sim' if r['delete_trigger'] else 'Não'}")
                    break
            text, markup = generate_auto_responder_detail(cfg, resp_id)
            await query.edit_message_text(text, reply_markup=markup, parse_mode=ParseMode.MARKDOWN)
            return

        if data.startswith("cfg:resp:test:"):
            resp_id = int(data.split(":")[-1])
            if self.auto_responder_handler:
                await query.answer("Enviando teste de resposta...")
                await self.auto_responder_handler.test_responder(update, context, resp_id)
            else:
                await query.answer("Handler de teste não configurado.", show_alert=True)
            return

        if data.startswith("cfg:resp:edit_text:"):
            resp_id = int(data.split(":")[-1])
            self.pending_inputs[user.id] = {"action": "resp_edit_text", "item_id": resp_id, "chat_id": chat.id}
            await query.answer()
            prompt = (
                f"✏️ *Digite a mensagem da Resposta Automática #{resp_id}:*\n\n"
                "Variáveis disponíveis:\n"
                "• `{name}` - Nome do usuário\n"
                "• `{username}` - @username\n"
                "• `{group}` - Nome do grupo\n"
                "• `{id}` - ID do usuário\n"
                "• `{date}` - Data atual\n"
                "• `{hora}` - Hora atual\n\n"
                "_Envie o texto agora ou digite /cancelar:_"
            )
            await chat.send_message(prompt, parse_mode=ParseMode.MARKDOWN)
            return

        if data.startswith("cfg:resp:edit_pattern:"):
            resp_id = int(data.split(":")[-1])
            self.pending_inputs[user.id] = {"action": "resp_edit_pattern", "item_id": resp_id, "chat_id": chat.id}
            await query.answer()
            prompt = (
                f"🎯 *Digite o Gatilho / Expressão da Resposta #{resp_id}:*\n\n"
                "💡 *Exemplos:*\n"
                "• Palavra simples: `pix` ou `partituras`\n"
                "• Regex flexível: `(?i)\\b(pix|chave\\s*pix|manda\\s*pix)\\b`\n\n"
                "_Envie o novo gatilho agora ou digite /cancelar:_"
            )
            await chat.send_message(prompt, parse_mode=ParseMode.MARKDOWN)
            return

        if data.startswith("cfg:resp:edit_title:"):
            resp_id = int(data.split(":")[-1])
            self.pending_inputs[user.id] = {"action": "resp_edit_title", "item_id": resp_id, "chat_id": chat.id}
            await query.answer()
            prompt = f"🏷️ *Digite o novo Título da Resposta #{resp_id} (ou /cancelar):*"
            await chat.send_message(prompt, parse_mode=ParseMode.MARKDOWN)
            return

        if data.startswith("cfg:resp:edit_photo:"):
            resp_id = int(data.split(":")[-1])
            self.pending_inputs[user.id] = {"action": "resp_edit_photo", "item_id": resp_id, "chat_id": chat.id}
            await query.answer()
            prompt = f"🖼️ *Envie a foto ou imagem para a Resposta #{resp_id} (ou /cancelar):*"
            await chat.send_message(prompt, parse_mode=ParseMode.MARKDOWN)
            return

        if data.startswith("cfg:resp:del_photo:"):
            resp_id = int(data.split(":")[-1])
            responders = cfg.get("auto_responses", [])
            for r in responders:
                if r.get("id") == resp_id:
                    r["photo"] = None
                    save_config(cfg)
                    await query.answer("Foto removida!")
                    break
            text, markup = generate_auto_responder_detail(cfg, resp_id)
            await query.edit_message_text(text, reply_markup=markup, parse_mode=ParseMode.MARKDOWN)
            return

        if data.startswith("cfg:resp:edit_buttons:"):
            resp_id = int(data.split(":")[-1])
            self.pending_inputs[user.id] = {"action": "resp_edit_buttons", "item_id": resp_id, "chat_id": chat.id}
            await query.answer()
            prompt = (
                f"🔘 *Configure os Botões para a Resposta #{resp_id}:*\n\n"
                "Envie no formato: `Texto | https://link.com`\n"
                "Exemplo:\n"
                "`Chave PIX Copia e Cola | https://partituras.com/pix`\n\n"
                "_(Envie agora, ou 'remover' para limpar todos, ou /cancelar)_"
            )
            await chat.send_message(prompt, parse_mode=ParseMode.MARKDOWN)
            return

        if data.startswith("cfg:resp:del_buttons:"):
            resp_id = int(data.split(":")[-1])
            responders = cfg.get("auto_responses", [])
            for r in responders:
                if r.get("id") == resp_id:
                    r["buttons"] = []
                    save_config(cfg)
                    await query.answer("Botões removidos!")
                    break
            text, markup = generate_auto_responder_detail(cfg, resp_id)
            await query.edit_message_text(text, reply_markup=markup, parse_mode=ParseMode.MARKDOWN)
            return

        # -------------------------------------------------------------
        # TOGGLES GERAIS
        # -------------------------------------------------------------
        if data == "cfg:toggle:antispam":
            cur = cfg.setdefault("antispam", {}).get("enabled", True)
            cfg["antispam"]["enabled"] = not cur
            save_config(cfg)
            await query.answer(f"Anti-spam: {'Ativado' if not cur else 'Desativado'}")
            text, markup = generate_sub_antispam(cfg)
            await query.edit_message_text(text, reply_markup=markup, parse_mode=ParseMode.MARKDOWN)
            return

        if data == "cfg:toggle:links":
            cur = cfg.setdefault("antispam", {}).get("block_links", True)
            cfg["antispam"]["block_links"] = not cur
            save_config(cfg)
            await query.answer(f"Bloqueio de links: {'Ativado' if not cur else 'Desativado'}")
            text, markup = generate_page_1(title, cfg)
            await query.edit_message_text(text, reply_markup=markup, parse_mode=ParseMode.MARKDOWN)
            return

        if data == "cfg:toggle:invites":
            cur = cfg.setdefault("antispam", {}).get("block_telegram_invites", True)
            cfg["antispam"]["block_telegram_invites"] = not cur
            save_config(cfg)
            await query.answer(f"Bloqueio de convites: {'Ativado' if not cur else 'Desativado'}")
            text, markup = generate_page_2(title, cfg)
            await query.edit_message_text(text, reply_markup=markup, parse_mode=ParseMode.MARKDOWN)
            return

        if data == "cfg:toggle:forwards":
            cur = cfg.setdefault("antispam", {}).get("block_forwards", True)
            cfg["antispam"]["block_forwards"] = not cur
            save_config(cfg)
            await query.answer(f"Bloqueio de encaminhamentos: {'Ativado' if not cur else 'Desativado'}")
            text, markup = generate_page_2(title, cfg)
            await query.edit_message_text(text, reply_markup=markup, parse_mode=ParseMode.MARKDOWN)
            return

        if data == "cfg:toggle:user_repeat":
            cur = cfg.setdefault("antirepeat", {}).get("enabled", True)
            cfg["antirepeat"]["enabled"] = not cur
            save_config(cfg)
            await query.answer(f"Filtro anti-repetição de membros: {'Ativado' if not cur else 'Desativado'}")
            text, markup = generate_page_2(title, cfg)
            await query.edit_message_text(text, reply_markup=markup, parse_mode=ParseMode.MARKDOWN)
            return

        if data == "cfg:toggle:flood":
            cur = cfg.setdefault("antiflood", {}).get("enabled", True)
            cfg["antiflood"]["enabled"] = not cur
            save_config(cfg)
            await query.answer(f"Anti-flood: {'Ativado' if not cur else 'Desativado'}")
            text, markup = generate_sub_antiflood(cfg)
            await query.edit_message_text(text, reply_markup=markup, parse_mode=ParseMode.MARKDOWN)
            return

        if data == "cfg:toggle:service_msg":
            cur = cfg.setdefault("welcome", {}).get("delete_service_messages", True)
            cfg["welcome"]["delete_service_messages"] = not cur
            save_config(cfg)
            await query.answer(f"Limpar msg de entrada: {'Ativado' if not cur else 'Desativado'}")
            text, markup = generate_page_2(title, cfg)
            await query.edit_message_text(text, reply_markup=markup, parse_mode=ParseMode.MARKDOWN)
            return

        if data == "cfg:toggle:pin_service_msg":
            cur = cfg.get("delete_pinned_service_messages", True)
            cfg["delete_pinned_service_messages"] = not cur
            save_config(cfg)
            await query.answer(f"Limpar avisos de fixado: {'Ativado' if not cur else 'Desativado'}", show_alert=True)
            text, markup = generate_page_2(title, cfg)
            await query.edit_message_text(text, reply_markup=markup, parse_mode=ParseMode.MARKDOWN)
            return

        if data == "cfg:toggle:captcha":
            cur = cfg.setdefault("captcha", {}).get("enabled", False)
            cfg["captcha"]["enabled"] = not cur
            save_config(cfg)
            await query.answer(f"Anti-Bot CAPTCHA: {'Ativado' if not cur else 'Desativado'}")
            text, markup = generate_page_2(title, cfg)
            await query.edit_message_text(text, reply_markup=markup, parse_mode=ParseMode.MARKDOWN)
            return

        if data == "cfg:toggle:join_req":
            cur = cfg.setdefault("join_requests", {}).get("auto_approve", False)
            cfg["join_requests"]["auto_approve"] = not cur
            save_config(cfg)
            await query.answer(f"Auto-aprovação de entrada: {'Ativada' if not cur else 'Desativada'}")
            text, markup = generate_page_2(title, cfg)
            await query.edit_message_text(text, reply_markup=markup, parse_mode=ParseMode.MARKDOWN)
            return

        if data == "cfg:toggle:cmd_clean":
            cur = cfg.setdefault("command_cleanup", {}).get("delete_admin_commands", True)
            cfg["command_cleanup"]["delete_admin_commands"] = not cur
            cfg["command_cleanup"]["delete_non_admin_commands"] = not cur
            save_config(cfg)
            await query.answer(f"Limpeza de comandos: {'Ativada' if not cur else 'Desativada'}")
            text, markup = generate_sub_cmd_clean(cfg)
            await query.edit_message_text(text, reply_markup=markup, parse_mode=ParseMode.MARKDOWN)
            return

        if data == "cfg:toggle:clean_admin":
            cc = cfg.setdefault("command_cleanup", {})
            cur = cc.get("delete_admin_commands", True)
            cc["delete_admin_commands"] = not cur
            save_config(cfg)
            await query.answer(f"Comandos de Admin: {'Ativado' if not cur else 'Desativado'}")
            text, markup = generate_sub_cmd_clean(cfg)
            await query.edit_message_text(text, reply_markup=markup, parse_mode=ParseMode.MARKDOWN)
            return

        if data == "cfg:toggle:clean_user":
            cc = cfg.setdefault("command_cleanup", {})
            cur = cc.get("delete_non_admin_commands", True)
            cc["delete_non_admin_commands"] = not cur
            save_config(cfg)
            await query.answer(f"Comandos de Membros: {'Ativado' if not cur else 'Desativado'}")
            text, markup = generate_sub_cmd_clean(cfg)
            await query.edit_message_text(text, reply_markup=markup, parse_mode=ParseMode.MARKDOWN)
            return

        if data == "cfg:cycle:clean_notice":
            cc = cfg.setdefault("command_cleanup", {})
            cur = cc.get("bot_notice_delete_seconds", 10)
            seq = [0, 5, 10, 15, 30]
            idx = seq.index(cur) if cur in seq else 0
            new_val = seq[(idx + 1) % len(seq)]
            cc["bot_notice_delete_seconds"] = new_val
            save_config(cfg)
            lbl = f"{new_val}s" if new_val > 0 else "Nunca apagar"
            await query.answer(f"Tempo do aviso do bot: {lbl}")
            text, markup = generate_sub_cmd_clean(cfg)
            await query.edit_message_text(text, reply_markup=markup, parse_mode=ParseMode.MARKDOWN)
            return

        if data == "cfg:cycle:repeat_window":
            cur = cfg.setdefault("antirepeat", {}).get("time_window_hours", 2)
            next_hours = {1: 2, 2: 4, 4: 6, 6: 12, 12: 24, 24: 1}
            new_h = next_hours.get(cur, 2)
            cfg["antirepeat"]["time_window_hours"] = new_h
            cfg["antirepeat"]["time_window_seconds"] = int(new_h * 3600)
            save_config(cfg)
            await query.answer(f"Janela de repetição: {new_h} hora(s)")
            text, markup = generate_page_2(title, cfg)
            await query.edit_message_text(text, reply_markup=markup, parse_mode=ParseMode.MARKDOWN)
            return

        # Ciclos de valores numéricos
        if data.startswith("cfg:cycle:welcome_time"):
            gid = data.split(":")[-1] if len(data.split(":")) > 3 else "general"
            if gid in ("general", "0", ""):
                cur = cfg.setdefault("welcome", {}).get("delete_welcome_after_seconds", 60)
            else:
                from config import get_welcome_for_chat
                w_grp = cfg.setdefault("group_welcomes", {}).setdefault(str(gid), dict(get_welcome_for_chat(cfg, gid)))
                cur = w_grp.get("delete_welcome_after_seconds", 60)

            next_vals = {0: 30, 30: 60, 60: 120, 120: 300, 300: 600, 600: 1800, 1800: 0}
            new_val = next_vals.get(cur, 60)

            if gid in ("general", "0", ""):
                cfg["welcome"]["delete_welcome_after_seconds"] = new_val
            else:
                w_grp["delete_welcome_after_seconds"] = new_val

            save_config(cfg)
            label = format_time_label(new_val)
            try:
                await query.answer(f"Tempo de boas-vindas: {label}")
            except Exception:
                pass
            if query.message and query.message.text and "Página 2" in query.message.text:
                text, markup = generate_page_2(title, cfg)
                pm = ParseMode.MARKDOWN
            else:
                text, markup = generate_sub_welcome(cfg, gid)
                pm = ParseMode.HTML
            try:
                await query.edit_message_text(text, reply_markup=markup, parse_mode=pm)
            except Exception:
                try:
                    await query.edit_message_text(text, reply_markup=markup)
                except Exception:
                    pass
            return

        if data == "cfg:cycle:flood_mute":
            cur = cfg.setdefault("antiflood", {}).get("mute_duration_minutes", 5)
            next_vals = {5: 15, 15: 30, 30: 60, 60: 5}
            new_val = next_vals.get(cur, 5)
            cfg["antiflood"]["mute_duration_minutes"] = new_val
            save_config(cfg)
            await query.answer(f"Punição: silenciar por {new_val} min")
            text, markup = generate_sub_antiflood(cfg)
            await query.edit_message_text(text, reply_markup=markup, parse_mode=ParseMode.MARKDOWN)
            return

        await query.answer()
