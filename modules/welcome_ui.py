import html
import logging
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update, LinkPreviewOptions
from telegram.constants import ParseMode
from telegram.ext import ContextTypes
from config import (
    load_config,
    save_config,
    get_welcome_for_chat,
    get_welcome_mode_for_chat,
    set_custom_welcome_for_chat,
    set_inherited_welcome_for_chat,
    disable_welcome_for_chat
)
from modules.welcome import test_welcome_message

logger = logging.getLogger("WelcomeUI")


def format_time_label(seconds: int) -> str:
    """Formata segundos em texto legível para botões e descrições."""
    if seconds <= 0:
        return "Nunca apagar"
    if seconds < 60:
        return f"{seconds}s"
    if seconds % 3600 == 0:
        h = seconds // 3600
        return f"{h}h" if h > 1 else "1 hora"
    m = seconds // 60
    return f"{m} min"


def generate_welcome_groups_selector(cfg: dict):
    """
    Central de Boas-Vindas por Grupo (Estilo Group Help):
    Selecione o grupo para editar o texto, foto e botões diretamente dele.
    """
    groups = cfg.get("linked_groups", [])

    text = (
        "💬 ══════════════════════ 💬\n"
        "   <b>BOAS-VINDAS POR GRUPO</b>\n"
        "💬 ══════════════════════ 💬\n\n"
        "Toque no grupo que deseja configurar as Boas-Vindas:\n\n"
    )

    kb = []
    if groups:
        for g in groups:
            gid = str(g.get("id"))
            gtit = g.get("title", f"Grupo {gid}")
            w = get_welcome_for_chat(cfg, gid)
            st = "🟢 Ativo" if w.get("enabled", True) else "🔴 Off"
            text += f"• <b>{html.escape(gtit)}:</b> <code>{st}</code>\n"
            kb.append([InlineKeyboardButton(f"👥 {gtit[:25]} [{st}]", callback_data=f"cfg:welcome:cfg:{gid}")])
        text += "\n👇 <i>Selecione o grupo abaixo para abrir suas Boas-Vindas:</i>"
    else:
        text += "<i>Nenhum grupo vinculado ainda. Use /setgrupo dentro do grupo para vinculá-lo!</i>\n"
        kb.append([InlineKeyboardButton("⭐️ Configurar Padrão", callback_data="cfg:welcome:cfg:general")])

    kb.append([InlineKeyboardButton("◀ Voltar à Seleção de Grupos", callback_data="cfg:hub")])
    return text, InlineKeyboardMarkup(kb)


def generate_sub_welcome(cfg: dict, target_group_id: str = "general"):
    """
    Painel de configuração de Boas-Vindas DIRETO E DESCOMPLICADO:
    Todas as ferramentas de edição ficam liberadas imediatamente, sem travas ou heranças confusas.
    """
    target_group_id = str(target_group_id)
    is_general = (target_group_id in ("general", "0", ""))

    if is_general:
        w = cfg.get("welcome", {})
        title_label = "Padrão Geral (Todos os Grupos)"
    else:
        g_item = next((g for g in cfg.get("linked_groups", []) if str(g.get("id")) == target_group_id), None)
        title_label = f"Grupo: {g_item.get('title', 'Grupo')}" if g_item else f"Grupo {target_group_id}"
        # Garante que o grupo tenha sua configuração editável na hora
        gw = cfg.setdefault("group_welcomes", {})
        if target_group_id not in gw:
            gw[target_group_id] = dict(cfg.get("welcome", {}))
            save_config(cfg)
        w = gw[target_group_id]

    enabled = w.get("enabled", True)
    sec = w.get("delete_welcome_after_seconds", 600)
    del_srv = w.get("delete_service_messages", True)
    has_photo = bool(w.get("photo"))
    buttons_count = len(w.get("buttons", []))
    art_url = w.get("article_url")
    msg_preview = w.get("message", "")
    if len(msg_preview) > 160:
        msg_preview = msg_preview[:160] + "..."

    status_tag = "🟢 Ativado" if enabled else "🔴 Desativado"

    text = (
        "<b>BOAS-VINDAS</b>\n"
        f"<b>{html.escape(title_label)}</b>\n\n"
        f"• <b>Status no Grupo:</b> <code>{status_tag}</code>\n"
        f"• <b>Banner / Foto:</b> <code>{'Configurada' if has_photo else 'Nenhuma'}</code>\n"
        f"• <b>Botões Interativos:</b> <code>{buttons_count} linha(s) configurada(s)</code>\n"
        f"• <b>Tempo de Auto-Apagar:</b> <code>{format_time_label(sec)}</code>\n"
        f"• <b>Limpar Aviso do Telegram:</b> <code>{'🟢 Sim' if del_srv else '🔴 Não'}</code>\n\n"
        f"📌 <b>Texto das Boas-Vindas:</b>\n<i>{html.escape(msg_preview)}</i>\n\n"
        "<i>Toque nas opções abaixo para personalizar:</i>"
    )

    kb = [
        [
            InlineKeyboardButton("📝 Alterar Texto", callback_data=f"cfg:edit:welcome_text:{target_group_id}"),
            InlineKeyboardButton("🖼️ Alterar Foto", callback_data=f"cfg:edit:welcome_photo:{target_group_id}")
        ],
        [
            InlineKeyboardButton("🔘 Configurar Botões", callback_data=f"cfg:edit:welcome_buttons:{target_group_id}"),
            InlineKeyboardButton(f"⏱️ Auto-Apagar ({format_time_label(sec)})", callback_data=f"cfg:sub:wtime:{target_group_id}")
        ],
        [
            InlineKeyboardButton("🔴 Desativar" if enabled else "🟢 Ativar", callback_data=f"cfg:toggle:welcome:{target_group_id}"),
            InlineKeyboardButton("👀 Ver Prévia", callback_data=f"cfg:preview:welcome:{target_group_id}")
        ]
    ]

    cleanup_row = []
    if has_photo:
        cleanup_row.append(InlineKeyboardButton("🗑️ Remover Foto", callback_data=f"cfg:del:welcome_photo:{target_group_id}"))
    if buttons_count > 0:
        cleanup_row.append(InlineKeyboardButton("🗑️ Remover Botões", callback_data=f"cfg:del:welcome_buttons:{target_group_id}"))
    if art_url:
        cleanup_row.append(InlineKeyboardButton("🗑️ Remover Artigo", callback_data=f"cfg:del:welcome_article:{target_group_id}"))
    if cleanup_row:
        kb.append(cleanup_row)

    if not is_general:
        kb.append([
            InlineKeyboardButton("🚀 Testar Disparo no Grupo Agora", callback_data=f"cfg:welcome:test:{target_group_id}")
        ])
        kb.append([
            InlineKeyboardButton("◀ Voltar ao Painel do Grupo", callback_data=f"cfg:grp:select:{target_group_id}")
        ])
    else:
        kb.append([
            InlineKeyboardButton("◀ Voltar à Seleção de Grupos", callback_data="cfg:hub")
        ])

    return text, InlineKeyboardMarkup(kb)

    return text, InlineKeyboardMarkup(kb)


def generate_sub_welcome_time(cfg: dict, target_group_id: str = "general"):
    """Menu para escolha de tempo de auto-apagar das boas-vindas."""
    target_group_id = str(target_group_id)
    is_general = (target_group_id in ("general", "0", ""))

    if is_general:
        w = cfg.get("welcome", {})
        title_label = "⭐️ Padrão Geral"
    else:
        g_item = next((g for g in cfg.get("linked_groups", []) if str(g.get("id")) == target_group_id), None)
        title_label = f"👥 {g_item.get('title', 'Grupo')}" if g_item else f"👥 Grupo {target_group_id}"
        w = get_welcome_for_chat(cfg, target_group_id)

    cur_sec = w.get("delete_welcome_after_seconds", 600)

    text = (
        "⏱️ <b>TEMPO DE AUTO-APAGAR BOAS-VINDAS</b>\n\n"
        f"🎯 <b>Destino:</b> {html.escape(title_label)}\n"
        f"⏱️ <b>Tempo Atual:</b> <code>{format_time_label(cur_sec)}</code>\n\n"
        "Escolha após quanto tempo a mensagem de boas-vindas será apagada do chat automaticamente para não poluir o grupo:"
    )

    times = [
        (30, "30 seg"),
        (60, "1 min"),
        (120, "2 min"),
        (300, "5 min"),
        (600, "10 min"),
        (900, "15 min"),
        (1800, "30 min"),
        (3600, "1 hora"),
        (0, "Nunca apagar")
    ]

    kb = []
    row = []
    for sec, lbl in times:
        is_cur = " (Ativo)" if sec == cur_sec else ""
        row.append(InlineKeyboardButton(f"{lbl}{is_cur}", callback_data=f"cfg:set:wtime:{target_group_id}:{sec}"))
        if len(row) == 3:
            kb.append(row)
            row = []
    if row:
        kb.append(row)

    kb.append([InlineKeyboardButton("◀ Voltar às Boas-Vindas", callback_data=f"cfg:welcome:cfg:{target_group_id}")])
    return text, InlineKeyboardMarkup(kb)


async def handle_welcome_callback(panel, update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Controlador central de callbacks de Boas-Vindas."""
    query = update.callback_query
    if not query:
        return False

    data = query.data
    user = update.effective_user
    chat = update.effective_chat
    cfg = load_config()

    if data in ("cfg:sub:welcome", "cfg:welcome:select"):
        await query.answer()
        text, markup = generate_welcome_groups_selector(cfg)
        try:
            await query.edit_message_text(text, reply_markup=markup, parse_mode=ParseMode.HTML)
        except Exception:
            await query.message.reply_text(text, reply_markup=markup, parse_mode=ParseMode.HTML)
        return True

    if data.startswith("cfg:welcome:cfg:"):
        gid = data.split(":")[-1]
        await query.answer()
        text, markup = generate_sub_welcome(cfg, gid)
        try:
            await query.edit_message_text(text, reply_markup=markup, parse_mode=ParseMode.HTML)
        except Exception:
            await query.message.reply_text(text, reply_markup=markup, parse_mode=ParseMode.HTML)
        return True

    if data.startswith("cfg:welcome:copy:"):
        gid = data.split(":")[-1]
        set_custom_welcome_for_chat(cfg, gid)
        await query.answer("✨ Mensagem própria criada! Agora você pode editar texto, foto e botões exclusivos deste grupo.", show_alert=True)
        text, markup = generate_sub_welcome(cfg, gid)
        try:
            await query.edit_message_text(text, reply_markup=markup, parse_mode=ParseMode.HTML)
        except Exception:
            pass
        return True

    if data.startswith("cfg:welcome:reset:"):
        gid = data.split(":")[-1]
        set_inherited_welcome_for_chat(cfg, gid)
        await query.answer("🔗 Grupo voltou a herdar o Padrão Geral automaticamente!", show_alert=True)
        text, markup = generate_sub_welcome(cfg, gid)
        try:
            await query.edit_message_text(text, reply_markup=markup, parse_mode=ParseMode.HTML)
        except Exception:
            pass
        return True

    if data.startswith("cfg:welcome:disable:"):
        gid = data.split(":")[-1]
        disable_welcome_for_chat(cfg, gid)
        await query.answer("🔴 Boas-vindas desativadas neste grupo!", show_alert=True)
        text, markup = generate_sub_welcome(cfg, gid)
        try:
            await query.edit_message_text(text, reply_markup=markup, parse_mode=ParseMode.HTML)
        except Exception:
            pass
        return True

    if data.startswith("cfg:welcome:enable_default:"):
        gid = data.split(":")[-1]
        set_inherited_welcome_for_chat(cfg, gid)
        await query.answer("🟢 Boas-vindas ativadas herdando o Padrão Geral!", show_alert=True)
        text, markup = generate_sub_welcome(cfg, gid)
        try:
            await query.edit_message_text(text, reply_markup=markup, parse_mode=ParseMode.HTML)
        except Exception:
            pass
        return True

    if data.startswith("cfg:welcome:test:"):
        gid = data.split(":")[-1]
        try:
            int_gid = int(gid)
        except ValueError:
            await query.answer("ID de grupo inválido para teste.", show_alert=True)
            return True

        await query.answer("🚀 Enviando mensagem de teste no grupo...", show_alert=False)
        success, msg = await test_welcome_message(context.bot, int_gid, user, context)
        await query.answer(f"{'✅' if success else '❌'} {msg}", show_alert=True)
        return True

    if data.startswith("cfg:toggle:welcome:"):
        gid = data.split(":")[-1]
        if gid in ("general", "0", ""):
            cur = cfg.setdefault("welcome", {}).get("enabled", True)
            cfg["welcome"]["enabled"] = not cur
            st = not cur
        else:
            mode = get_welcome_mode_for_chat(cfg, gid)
            if mode == "disabled":
                # Ativa herdando ou com custom
                set_inherited_welcome_for_chat(cfg, gid)
                st = True
            else:
                disable_welcome_for_chat(cfg, gid)
                st = False
        save_config(cfg)
        await query.answer(f"Boas-vindas: {'Ativado' if st else 'Desativado'}", show_alert=True)
        text, markup = generate_sub_welcome(cfg, gid)
        try:
            await query.edit_message_text(text, reply_markup=markup, parse_mode=ParseMode.HTML)
        except Exception:
            pass
        return True

    if data.startswith("cfg:sub:wtime:"):
        gid = data.split(":")[-1]
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
        return True

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
            w_grp = cfg.setdefault("group_welcomes", {}).setdefault(str(gid), dict(get_welcome_for_chat(cfg, gid)))
            w_grp["delete_welcome_after_seconds"] = sec
        save_config(cfg)
        lbl = format_time_label(sec)
        try:
            await query.answer(f"Tempo definido: {lbl}!", show_alert=False)
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
        return True

    if data.startswith("cfg:del:welcome_photo:"):
        gid = data.split(":")[-1]
        if gid in ("general", "0", ""):
            cfg.setdefault("welcome", {})["photo"] = None
        else:
            w_grp = cfg.setdefault("group_welcomes", {}).setdefault(str(gid), dict(get_welcome_for_chat(cfg, gid)))
            w_grp["photo"] = None
        save_config(cfg)
        await query.answer("Foto removida com sucesso!", show_alert=True)
        text, markup = generate_sub_welcome(cfg, gid)
        try:
            await query.edit_message_text(text, reply_markup=markup, parse_mode=ParseMode.HTML)
        except Exception:
            pass
        return True

    if data.startswith("cfg:del:welcome_buttons:"):
        gid = data.split(":")[-1]
        if gid in ("general", "0", ""):
            cfg.setdefault("welcome", {})["buttons"] = []
        else:
            w_grp = cfg.setdefault("group_welcomes", {}).setdefault(str(gid), dict(get_welcome_for_chat(cfg, gid)))
            w_grp["buttons"] = []
        save_config(cfg)
        await query.answer("Botões removidos com sucesso!", show_alert=True)
        text, markup = generate_sub_welcome(cfg, gid)
        try:
            await query.edit_message_text(text, reply_markup=markup, parse_mode=ParseMode.HTML)
        except Exception:
            pass
        return True

    if data.startswith("cfg:del:welcome_article:"):
        gid = data.split(":")[-1]
        if gid in ("general", "0", ""):
            cfg.setdefault("welcome", {})["article_url"] = None
        else:
            w_grp = cfg.setdefault("group_welcomes", {}).setdefault(str(gid), dict(get_welcome_for_chat(cfg, gid)))
            w_grp["article_url"] = None
        save_config(cfg)
        await query.answer("Artigo removido com sucesso!", show_alert=True)
        text, markup = generate_sub_welcome(cfg, gid)
        try:
            await query.edit_message_text(text, reply_markup=markup, parse_mode=ParseMode.HTML)
        except Exception:
            pass
        return True

    if data.startswith("cfg:edit:welcome_text"):
        gid = data.split(":")[-1] if len(data.split(":")) > 3 else "general"
        panel.pending_inputs[user.id] = {"action": "welcome_text", "group_id": gid, "chat_id": chat.id}
        await query.answer()
        g_lbl = f"no grupo {gid}" if gid != "general" else "no Padrão Geral"
        prompt = (
            f"📝 <b>Digite a nova mensagem de boas-vindas ({g_lbl}):</b>\n\n"
            "💡 <b>Variáveis disponíveis:</b>\n"
            "  • <code>{MENTION}</code> ou <code>{mention}</code>: Menção clicável direta para o perfil do membro!\n"
            "  • <code>{name}</code>: Primeiro nome do membro\n"
            "  • <code>{fullname}</code>: Nome completo\n"
            "  • <code>{username}</code>: @username do membro (ou nome se não tiver)\n"
            "  • <code>{group}</code>: Nome do grupo\n"
            "  • <code>{id}</code>: ID numérico do membro\n"
            "  • <code>{date}</code> / <code>{hour}</code>: Data e hora da entrada\n\n"
            "<i>Envie o texto agora (você também pode encaminhar um post pronto com foto e botões) ou digite /cancelar:</i>"
        )
        await chat.send_message(prompt, parse_mode=ParseMode.HTML)
        return True

    if data.startswith("cfg:edit:welcome_photo"):
        gid = data.split(":")[-1] if len(data.split(":")) > 3 else "general"
        panel.pending_inputs[user.id] = {"action": "welcome_photo", "group_id": gid, "chat_id": chat.id}
        await query.answer()
        g_lbl = f"deste grupo ({gid})" if gid != "general" else "do Padrão Geral"
        prompt = f"🖼️ <b>Envie a foto ou imagem de boas-vindas ({g_lbl}) agora (ou envie /cancelar):</b>"
        await chat.send_message(prompt, parse_mode=ParseMode.HTML)
        return True

    if data.startswith("cfg:edit:welcome_buttons"):
        gid = data.split(":")[-1] if len(data.split(":")) > 3 else "general"
        panel.pending_inputs[user.id] = {"action": "welcome_buttons", "group_id": gid, "chat_id": chat.id}
        await query.answer()
        prompt = (
            "🔘 <b>Configure os Botões de Boas-Vindas:</b>\n\n"
            "💡 <b>Exemplos de formatos (Interativos e Links):</b>\n"
            "• <i>Regras do Grupo (Pop-up modal exclusivo na tela):</i>\n"
            "<code>[📜 Regras](regras)</code> ou <code>Regras | regras</code>\n\n"
            "• <i>Tutorial de Busca (@botpartituras_bot):</i>\n"
            "<code>[🎥 Como Pesquisar](tutorial)</code> ou <code>Como Pesquisar | tutorial</code>\n\n"
            "• <i>Alerta Personalizado:</i>\n"
            "<code>[Aviso](buttonalert:Apenas partituras em PDF!)</code>\n\n"
            "• <i>Botões lado a lado (na mesma linha):</i>\n"
            "<code>[📜 Regras](regras) [🎥 Como Pesquisar](tutorial)</code>\n"
            "<code>Regras | regras && Como Pesquisar | tutorial</code>\n\n"
            "• <i>Links de Canais e Redes:</i>\n"
            "<code>Canal Oficial | https://t.me/partiturasecia</code>\n\n"
            "<i>(Envie a lista agora, ou 'remover' para limpar todos, ou /cancelar)</i>"
        )
        await chat.send_message(prompt, parse_mode=ParseMode.HTML)
        return True

    if data.startswith("cfg:edit:welcome_article"):
        gid = data.split(":")[-1] if len(data.split(":")) > 3 else "general"
        panel.pending_inputs[user.id] = {"action": "welcome_article", "group_id": gid, "chat_id": chat.id}
        await query.answer()
        prompt = (
            "📄 <b>Definir Artigo / Instant View para as Boas-Vindas:</b>\n\n"
            "Envie o link do artigo (ex: Telegraph ou página web):\n"
            "<code>https://telegra.ph/Guia-do-Grupo...</code>\n\n"
            "O bot exibirá a prévia do artigo no topo da mensagem de boas-vindas!\n\n"
            "<i>(Envie o link agora, ou 'remover' para limpar, ou /cancelar)</i>"
        )
        await chat.send_message(prompt, parse_mode=ParseMode.HTML)
        return True

    if data.startswith("cfg:preview:welcome"):
        gid = data.split(":")[-1] if len(data.split(":")) > 3 else "general"
        await query.answer("Enviando prévia...")
        await panel.preview_welcome(update, context, gid)
        return True

    return False


async def handle_welcome_input(panel, msg, context: ContextTypes.DEFAULT_TYPE, user, state: dict, action: str) -> bool:
    """Processa entradas de texto, foto, botões e artigo para as boas-vindas."""
    cfg = load_config()

    if action == "welcome_text":
        raw_text, photo_id, extracted_buttons, src_chat_id, src_msg_id, bak_chat_id, bak_msg_id = await panel._extract_message_content(msg, context, user.id)
        target_gid = str(state.get("group_id", "general"))
        if target_gid in ("general", "0", ""):
            w_cfg = cfg.setdefault("welcome", {})
            return_cb = "cfg:welcome:cfg:general"
            prev_cb = "cfg:preview:welcome:general"
        else:
            base = dict(get_welcome_for_chat(cfg, target_gid))
            w_cfg = cfg.setdefault("group_welcomes", {}).setdefault(target_gid, base)
            w_cfg["enabled"] = True
            return_cb = f"cfg:welcome:cfg:{target_gid}"
            prev_cb = f"cfg:preview:welcome:{target_gid}"

        if raw_text:
            w_cfg["message"] = raw_text
        if photo_id:
            w_cfg["photo"] = photo_id
        if extracted_buttons:
            w_cfg["buttons"] = extracted_buttons

        save_config(cfg)
        del panel.pending_inputs[user.id]

        summary_items = ["• <b>Texto:</b> Atualizado com formatação rica"]
        if photo_id:
            summary_items.append("• <b>Foto:</b> Imagem salva com sucesso")
        if extracted_buttons:
            total_btns = sum(len(r) for r in extracted_buttons)
            summary_items.append(f"• <b>Botões:</b> {total_btns} botão(ões) configurados!")

        summary_str = "\n".join(summary_items)
        preview_markup = InlineKeyboardMarkup([
            [InlineKeyboardButton("👀 Ver Prévia", callback_data=prev_cb)],
            [InlineKeyboardButton("⚙️ Voltar às Configurações", callback_data=return_cb)]
        ])
        await msg.reply_text(
            f"✅ <b>Configuração de boas-vindas salva com sucesso!</b>\n\n{summary_str}",
            parse_mode=ParseMode.HTML,
            reply_markup=preview_markup
        )
        return True

    elif action == "welcome_photo":
        if not msg.photo:
            await msg.reply_text("⚠️ Envie uma imagem/foto válida ou digite /cancelar.")
            return True

        target_gid = str(state.get("group_id", "general"))
        if target_gid in ("general", "0", ""):
            w_cfg = cfg.setdefault("welcome", {})
            return_cb = "cfg:welcome:cfg:general"
            prev_cb = "cfg:preview:welcome:general"
        else:
            base = dict(get_welcome_for_chat(cfg, target_gid))
            w_cfg = cfg.setdefault("group_welcomes", {}).setdefault(target_gid, base)
            w_cfg["enabled"] = True
            return_cb = f"cfg:welcome:cfg:{target_gid}"
            prev_cb = f"cfg:preview:welcome:{target_gid}"

        file_id = msg.photo[-1].file_id
        w_cfg["photo"] = file_id
        save_config(cfg)
        del panel.pending_inputs[user.id]

        preview_markup = InlineKeyboardMarkup([
            [InlineKeyboardButton("👀 Ver Prévia", callback_data=prev_cb)],
            [InlineKeyboardButton("⚙️ Voltar às Configurações", callback_data=return_cb)]
        ])
        await msg.reply_text(
            "✅ <b>Imagem de boas-vindas atualizada com sucesso!</b>",
            parse_mode=ParseMode.HTML,
            reply_markup=preview_markup
        )
        return True

    elif action == "welcome_buttons":
        raw_text, photo_id, extracted_buttons, src_chat_id, src_msg_id, bak_chat_id, bak_msg_id = await panel._extract_message_content(msg, context, user.id)
        target_gid = str(state.get("group_id", "general"))
        if target_gid in ("general", "0", ""):
            w_cfg = cfg.setdefault("welcome", {})
            return_cb = "cfg:welcome:cfg:general"
            prev_cb = "cfg:preview:welcome:general"
        else:
            base = dict(get_welcome_for_chat(cfg, target_gid))
            w_cfg = cfg.setdefault("group_welcomes", {}).setdefault(target_gid, base)
            w_cfg["enabled"] = True
            return_cb = f"cfg:welcome:cfg:{target_gid}"
            prev_cb = f"cfg:preview:welcome:{target_gid}"

        if raw_text and raw_text.strip().lower() in ("remover", "apagar", "nenhum"):
            w_cfg["buttons"] = []
            save_config(cfg)
            del panel.pending_inputs[user.id]
            await msg.reply_text("✅ <b>Botões de boas-vindas removidos!</b>", parse_mode=ParseMode.HTML)
            return True

        if not extracted_buttons:
            await msg.reply_text("⚠️ Nenhum botão detectado. Encaminhe uma mensagem com botões ou envie no formato <code>Texto | link</code> (ou /cancelar).", parse_mode=ParseMode.HTML)
            return True

        w_cfg["buttons"] = extracted_buttons
        save_config(cfg)
        del panel.pending_inputs[user.id]

        total_btns = sum(len(r) for r in extracted_buttons)
        preview_markup = InlineKeyboardMarkup([
            [InlineKeyboardButton("👀 Ver Prévia", callback_data=prev_cb)],
            [InlineKeyboardButton("⚙️ Voltar às Configurações", callback_data=return_cb)]
        ])
        await msg.reply_text(
            f"✅ <b>{total_btns} botão(ões) em {len(extracted_buttons)} linha(s) configurados com sucesso!</b>",
            parse_mode=ParseMode.HTML,
            reply_markup=preview_markup
        )
        return True

    elif action == "welcome_article":
        if not msg.text:
            await msg.reply_text("⚠️ Envie um link válido ou digite /cancelar.")
            return True

        target_gid = str(state.get("group_id", "general"))
        if target_gid in ("general", "0", ""):
            w_cfg = cfg.setdefault("welcome", {})
            return_cb = "cfg:welcome:cfg:general"
            prev_cb = "cfg:preview:welcome:general"
        else:
            base = dict(get_welcome_for_chat(cfg, target_gid))
            w_cfg = cfg.setdefault("group_welcomes", {}).setdefault(target_gid, base)
            w_cfg["enabled"] = True
            return_cb = f"cfg:welcome:cfg:{target_gid}"
            prev_cb = f"cfg:preview:welcome:{target_gid}"

        val = msg.text.strip()
        if val.lower() in ("remover", "apagar", "nenhum", "off"):
            w_cfg["article_url"] = None
            save_config(cfg)
            del panel.pending_inputs[user.id]
            await msg.reply_text("✅ <b>Artigo de boas-vindas removido!</b>", parse_mode=ParseMode.HTML)
            return True

        if not (val.startswith("http://") or val.startswith("https://") or val.startswith("t.me/")):
            val = "https://" + val

        w_cfg["article_url"] = val
        save_config(cfg)
        del panel.pending_inputs[user.id]

        preview_markup = InlineKeyboardMarkup([
            [InlineKeyboardButton("👀 Ver Prévia", callback_data=prev_cb)],
            [InlineKeyboardButton("⚙️ Voltar às Configurações", callback_data=return_cb)]
        ])
        await msg.reply_text(
            f"✅ <b>Artigo de boas-vindas definido com sucesso!</b>\nLink: <code>{html.escape(val)}</code>",
            parse_mode=ParseMode.HTML,
            reply_markup=preview_markup
        )
        return True

    return False

