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
