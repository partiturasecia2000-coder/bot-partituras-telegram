import html
import re
import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton
from telegram.constants import ParseMode
from telegram.ext import ContextTypes
from config import (
    load_config,
    save_config,
    is_user_whitelisted,
    add_whitelist_user,
    remove_whitelist_user,
    get_whitelist_users,
    get_allowed_domains,
    add_allowed_domain,
    remove_allowed_domain
)

logger = logging.getLogger("WhitelistModule")

# Presets populares de domínios com identificador e domínios associados
PRESET_DOMAINS = {
    "gdrive": {
        "label": "Google Drive",
        "domains": ["drive.google.com", "docs.google.com"]
    },
    "youtube": {
        "label": "YouTube",
        "domains": ["youtube.com", "youtu.be"]
    },
    "dropbox": {
        "label": "Dropbox",
        "domains": ["dropbox.com"]
    },
    "onedrive": {
        "label": "OneDrive",
        "domains": ["1drv.ms", "onedrive.live.com"]
    }
}


def get_conversation_reply_keyboard() -> ReplyKeyboardMarkup:
    """
    Retorna o menu em botões na área de conversa (Reply Keyboard persistente).
    Permite acesso rápido às principais funções do bot diretamente no teclado.
    """
    keyboard = [
        [KeyboardButton("🎛️ Painel de Controle"), KeyboardButton("🎼 Acervo de Partituras")],
        [KeyboardButton("📢 Meus Canais"), KeyboardButton("👥 Meus Grupos")],
        [KeyboardButton("🛡️ Whitelist & Links"), KeyboardButton("❓ Ajuda & Comandos")]
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True, is_persistent=True)


def generate_whitelist_hub(cfg: dict):
    """Gera o menu central de Whitelist (Usuários Livres + Links Permitidos)."""
    w_users = get_whitelist_users(cfg)
    a_domains = get_allowed_domains(cfg)

    has_gdrive = any("drive.google.com" in d.lower() for d in a_domains)

    text = (
        "🛡️ <b>CENTRAL DE LISTAS BRANCAS (WHITELIST)</b>\n\n"
        "Aqui você define quem e quais links têm permissão total no grupo, "
        "sem sofrer nenhum bloqueio de antispam, anti-flood ou repetição.\n\n"
        f"👤 <b>Usuários Livres (Isentos):</b> <code>{len(w_users)}</code> cadastrado(s)\n"
        "<i>Membros que podem enviar links, mensagens repetidas e mídias livremente.</i>\n\n"
        f"🌐 <b>Links Permitidos (Domínios):</b> <code>{len(a_domains)}</code> liberado(s)\n"
        f"<i>Status do Google Drive: {'🟢 Liberado' if has_gdrive else '🔴 Bloqueado'}</i>\n\n"
        "Selecione uma área abaixo para gerenciar:"
    )

    kb = [
        [
            InlineKeyboardButton(f"👤 Usuários Livres ({len(w_users)})", callback_data="cfg:sub:whitelist_users"),
            InlineKeyboardButton(f"🌐 Links Permitidos ({len(a_domains)})", callback_data="cfg:sub:allowed_links")
        ],
        [
            InlineKeyboardButton("◀ Voltar ao Painel", callback_data="cfg:page:1")
        ]
    ]
    return text, InlineKeyboardMarkup(kb)


def generate_whitelist_users_page(cfg: dict, page: int = 1):
    """Gera página de gerenciamento de Usuários Livres."""
    users = get_whitelist_users(cfg)
    per_page = 6
    total = len(users)
    total_pages = max(1, (total + per_page - 1) // per_page)
    page = max(1, min(page, total_pages))

    start = (page - 1) * per_page
    end = start + per_page
    current_users = users[start:end]

    lines = [
        "👤 <b>USUÁRIOS LIVRES (LISTA BRANCA)</b>\n",
        "Membros cadastrados nesta lista têm <b>imunidade total</b>:",
        "• Podem enviar links (mesmo com Bloquear Links ativo)",
        "• Podem encaminhar posts de canais",
        "• Não são silenciados por flood ou repetições\n"
    ]

    if not users:
        lines.append("<i>Nenhum usuário livre cadastrado no momento.</i>\n")
    else:
        lines.append(f"📋 <b>Lista de Usuários Livres (Pág. {page}/{total_pages}):</b>")
        for u in current_users:
            uid = u.get("user_id") if isinstance(u, dict) else u
            uname = u.get("name", f"ID {uid}") if isinstance(u, dict) else f"ID {uid}"
            uuser = f" (@{u.get('username')})" if isinstance(u, dict) and u.get("username") else ""
            lines.append(f"• <b>{html.escape(uname)}</b>{html.escape(uuser)} — <code>{uid}</code>")
        lines.append("")

    kb = []
    # Botões de remoção rápida
    for u in current_users:
        uid = u.get("user_id") if isinstance(u, dict) else u
        uname = u.get("name", str(uid)) if isinstance(u, dict) else str(uid)
        short_name = uname[:18]
        kb.append([InlineKeyboardButton(f"❌ Remover: {short_name}", callback_data=f"cfg:del:whitelist_user:{uid}:{page}")])

    # Paginação se necessário
    if total_pages > 1:
        nav = []
        if page > 1:
            nav.append(InlineKeyboardButton("◀ Anterior", callback_data=f"cfg:sub:whitelist_users:{page-1}"))
        if page < total_pages:
            nav.append(InlineKeyboardButton("Próxima ▶", callback_data=f"cfg:sub:whitelist_users:{page+1}"))
        if nav:
            kb.append(nav)

    kb.append([
        InlineKeyboardButton("➕ Adicionar Usuário Livre", callback_data="cfg:add:whitelist_user"),
    ])
    kb.append([
        InlineKeyboardButton("◀ Voltar à Central Whitelist", callback_data="cfg:sub:whitelist_hub")
    ])

    return "\n".join(lines), InlineKeyboardMarkup(kb)


def generate_allowed_links_page(cfg: dict):
    """Gera página de gerenciamento de Links e Domínios Permitidos."""
    domains = get_allowed_domains(cfg)

    lines = [
        "🌐 <b>LINKS E TRECHOS PERMITIDOS NA LISTA BRANCA</b>\n",
        "Quando a proteção de <b>Bloquear Links</b> está ativa no grupo, "
        "apenas links pertencentes a estes domínios ou trechos serão <b>permitidos</b>.",
        "Qualquer outro link será apagado automaticamente.\n",
        "💡 <i>Você pode cadastrar domínios inteiros (ex: <code>drive.google.com</code>), links completos ou partes de links (ex: <code>drive.google.com/drive/folders/...</code>)!</i>\n"
    ]

    if not domains:
        lines.append("<i>⚠️ Nenhum link liberado! Todos os links externos serão bloqueados.</i>\n")
    else:
        lines.append(f"📋 <b>Endereços Atualmente Liberados ({len(domains)}):</b>")
        for d in domains:
            badge = "🟢"
            if "google" in d:
                badge = "📁"
            elif "youtube" in d or "youtu.be" in d:
                badge = "▶️"
            elif "dropbox" in d:
                badge = "📦"
            elif "t.me" in d:
                badge = "📢"
            lines.append(f"  {badge} <code>{html.escape(d)}</code>")
        lines.append("")

    kb = []

    # Linha de Presets 1-clique (Google Drive, YouTube, Dropbox, OneDrive)
    preset_row = []
    for p_key, p_data in PRESET_DOMAINS.items():
        is_active = any(d in domains for d in p_data["domains"])
        icon = "✅" if is_active else "➕"
        preset_row.append(InlineKeyboardButton(f"{icon} {p_data['label']}", callback_data=f"cfg:preset:link:{p_key}"))
        if len(preset_row) == 2:
            kb.append(preset_row)
            preset_row = []
    if preset_row:
        kb.append(preset_row)

    # Botões para remover domínios existentes
    if domains:
        for d in domains[:10]:
            label = d if len(d) <= 24 else f"{d[:11]}...{d[-10:]}"
            kb.append([InlineKeyboardButton(f"🗑️ Remover: {label}", callback_data=f"cfg:del:allowed_link:{d}")])

    kb.append([
        InlineKeyboardButton("➕ Adicionar Link ou Trecho", callback_data="cfg:add:allowed_link")
    ])
    kb.append([
        InlineKeyboardButton("◀ Voltar à Central Whitelist", callback_data="cfg:sub:whitelist_hub")
    ])

    return "\n".join(lines), InlineKeyboardMarkup(kb)


async def handle_whitelist_callback(panel, update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """Controlador de callbacks do módulo de Whitelist."""
    query = update.callback_query
    if not query:
        return False

    data = query.data
    user = update.effective_user
    chat = update.effective_chat
    cfg = load_config()

    if data == "cfg:sub:whitelist_hub":
        await query.answer()
        text, markup = generate_whitelist_hub(cfg)
        try:
            await query.edit_message_text(text, reply_markup=markup, parse_mode=ParseMode.HTML)
        except Exception:
            await query.message.reply_text(text, reply_markup=markup, parse_mode=ParseMode.HTML)
        return True

    if data.startswith("cfg:sub:whitelist_users"):
        parts = data.split(":")
        page = int(parts[-1]) if len(parts) > 3 and parts[-1].isdigit() else 1
        await query.answer()
        text, markup = generate_whitelist_users_page(cfg, page=page)
        try:
            await query.edit_message_text(text, reply_markup=markup, parse_mode=ParseMode.HTML)
        except Exception:
            await query.message.reply_text(text, reply_markup=markup, parse_mode=ParseMode.HTML)
        return True

    if data == "cfg:sub:allowed_links":
        await query.answer()
        text, markup = generate_allowed_links_page(cfg)
        try:
            await query.edit_message_text(text, reply_markup=markup, parse_mode=ParseMode.HTML)
        except Exception:
            await query.message.reply_text(text, reply_markup=markup, parse_mode=ParseMode.HTML)
        return True

    if data == "cfg:add:whitelist_user":
        await query.answer()
        panel.pending_inputs[user.id] = {
            "action": "add_whitelist_user",
            "chat_id": chat.id
        }
        prompt = (
            "👤 <b>ADICIONAR USUÁRIO LIVRE (WHITELIST)</b>\n\n"
            "Envie uma das opções abaixo:\n"
            "• O <b>ID numérico</b> do usuário (Ex: <code>7029735028</code>)\n"
            "• O <b>@username</b> do usuário (Ex: <code>@maestro_admin</code>)\n"
            "• Ou <b>encaminhe</b> qualquer mensagem dele aqui nesta conversa!\n\n"
            "💡 <i>Dica: Você também pode usar o comando <code>/livre</code> respondendo a qualquer mensagem dele no grupo!</i>\n\n"
            "Envie agora ou digite <code>/cancelar</code> para voltar."
        )
        await query.message.reply_text(prompt, parse_mode=ParseMode.HTML)
        return True

    if data.startswith("cfg:del:whitelist_user:"):
        parts = data.split(":")
        target_uid = parts[3]
        page = int(parts[4]) if len(parts) > 4 and parts[4].isdigit() else 1
        removed = remove_whitelist_user(cfg, target_uid)
        lbl = "removido da lista!" if removed else "já não estava na lista."
        await query.answer(f"Usuário {lbl}", show_alert=True)
        text, markup = generate_whitelist_users_page(cfg, page=page)
        try:
            await query.edit_message_text(text, reply_markup=markup, parse_mode=ParseMode.HTML)
        except Exception:
            pass
        return True

    if data == "cfg:add:allowed_link":
        await query.answer()
        panel.pending_inputs[user.id] = {
            "action": "add_allowed_link",
            "chat_id": chat.id
        }
        prompt = (
            "🌐 <b>ADICIONAR LINK, TRECHO OU DOMÍNIO PERMITIDO</b>\n\n"
            "Envie o domínio, link completo ou qualquer parte de link que deseja autorizar nos grupos.\n\n"
            "💡 <b>Exemplos de formatos aceitos:</b>\n"
            "• <b>Domínio inteiro:</b> <code>drive.google.com</code> ou <code>docs.google.com</code>\n"
            "• <b>Pasta / Trecho específico:</b> <code>drive.google.com/drive/folders/1ABC</code>\n"
            "• <b>Link completo:</b> <code>https://drive.google.com/file/d/12345/view</code>\n"
            "• <b>Canal do Telegram:</b> <code>t.me/partiturasecia</code>\n"
            "• <b>Vídeos / Músicas:</b> <code>youtube.com</code> ou <code>youtu.be</code>\n\n"
            "Envie o endereço agora ou envie <code>/cancelar</code> para voltar."
        )
        await query.message.reply_text(prompt, parse_mode=ParseMode.HTML)
        return True

    if data.startswith("cfg:del:allowed_link:"):
        target_domain = data.split("cfg:del:allowed_link:")[1]
        removed = remove_allowed_domain(cfg, target_domain)
        lbl = "removido da lista!" if removed else "já não constava na lista."
        await query.answer(f"Domínio {lbl}", show_alert=True)
        text, markup = generate_allowed_links_page(cfg)
        try:
            await query.edit_message_text(text, reply_markup=markup, parse_mode=ParseMode.HTML)
        except Exception:
            pass
        return True

    if data.startswith("cfg:preset:link:"):
        preset_key = data.split("cfg:preset:link:")[1]
        p_info = PRESET_DOMAINS.get(preset_key)
        if p_info:
            current_domains = get_allowed_domains(cfg)
            # Se já tem algum do preset, remove todos do preset. Se não tem, adiciona todos.
            is_present = any(d in current_domains for d in p_info["domains"])
            if is_present:
                for d in p_info["domains"]:
                    remove_allowed_domain(cfg, d)
                await query.answer(f"🔴 {p_info['label']} removido da lista branca!", show_alert=True)
            else:
                for d in p_info["domains"]:
                    add_allowed_domain(cfg, d)
                await query.answer(f"🟢 {p_info['label']} adicionado à lista branca com sucesso!", show_alert=True)

            text, markup = generate_allowed_links_page(cfg)
            try:
                await query.edit_message_text(text, reply_markup=markup, parse_mode=ParseMode.HTML)
            except Exception:
                pass
        return True

    return False


async def handle_whitelist_input(panel, update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """Processa entradas de texto de administradores relacionadas à Whitelist."""
    user = update.effective_user
    msg = update.effective_message
    if not user or not msg or user.id not in panel.pending_inputs:
        return False

    state = panel.pending_inputs[user.id]
    action = state.get("action")
    if action not in ("add_whitelist_user", "add_allowed_link"):
        return False

    text = (msg.text or "").strip()
    cfg = load_config()

    if action == "add_whitelist_user":
        target_uid = None
        target_name = ""
        target_uname = ""

        # 1. Se encaminhou uma mensagem do usuário
        if msg.forward_from:
            target_uid = msg.forward_from.id
            target_name = msg.forward_from.full_name
            target_uname = msg.forward_from.username or ""
        # 2. Se digitou ID numérico
        elif text.isdigit() or (text.startswith("-") and text[1:].isdigit()):
            target_uid = int(text)
            target_name = f"Usuário {target_uid}"
        # 3. Se digitou @username
        elif text.startswith("@") or len(text) >= 3:
            clean_name = text.lstrip("@")
            # Tenta resolver ID pelo username se conhecido nos chats, ou salva como nome
            target_uid = None
            for g in cfg.get("linked_groups", []):
                try:
                    chat_obj = await context.bot.get_chat(f"@{clean_name}")
                    if chat_obj and chat_obj.id:
                        target_uid = chat_obj.id
                        target_name = chat_obj.full_name or clean_name
                        target_uname = clean_name
                        break
                except Exception:
                    pass

            if not target_uid:
                await msg.reply_text(
                    f"⚠️ Não consegui encontrar o ID numérico para <code>{html.escape(text)}</code>.\n\n"
                    "Por favor, envie o <b>ID numérico</b> do usuário (ex: <code>7029735028</code>) ou "
                    "<b>encaminhe</b> qualquer mensagem dele aqui!",
                    parse_mode=ParseMode.HTML
                )
                return True

        if target_uid:
            del panel.pending_inputs[user.id]
            added = add_whitelist_user(cfg, target_uid, name=target_name, username=target_uname, added_by=user.first_name)
            if added:
                await msg.reply_text(
                    f"✅ <b>Usuário Liberado com Sucesso!</b>\n\n"
                    f"• <b>Nome:</b> {html.escape(target_name)}\n"
                    f"• <b>ID:</b> <code>{target_uid}</code>\n"
                    f"• <b>Status:</b> Isento de restrições de links, flood e spam em todos os grupos!",
                    parse_mode=ParseMode.HTML
                )
            else:
                await msg.reply_text(
                    f"ℹ️ O usuário <code>{target_uid}</code> já estava na lista branca!",
                    parse_mode=ParseMode.HTML
                )
            # Reabre a página de usuários livres
            text_p, markup_p = generate_whitelist_users_page(cfg)
            await msg.reply_text(text_p, reply_markup=markup_p, parse_mode=ParseMode.HTML)
            return True

    if action == "add_allowed_link":
        del panel.pending_inputs[user.id]
        if not text:
            await msg.reply_text("⚠️ Endereço inválido.")
            return True

        added = add_allowed_domain(cfg, text)
        if added:
            await msg.reply_text(
                f"✅ <b>Link / Trecho Autorizado!</b>\n\n"
                f"• <b>Endereço:</b> <code>{html.escape(text)}</code>\n"
                "Membros agora podem enviar links que contenham este endereço sem que o bot apague a mensagem!",
                parse_mode=ParseMode.HTML
            )
        else:
            await msg.reply_text(
                f"ℹ️ O endereço <code>{html.escape(text)}</code> já estava na lista de permissões!",
                parse_mode=ParseMode.HTML
            )
        text_p, markup_p = generate_allowed_links_page(cfg)
        await msg.reply_text(text_p, reply_markup=markup_p, parse_mode=ParseMode.HTML)
        return True

    return False


async def handle_conversation_menu_button(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """
    Trata toques nos botões do Reply Keyboard da área de conversa.
    Retorna True se a mensagem era um dos botões do menu e foi processada.
    """
    msg = update.effective_message
    user = update.effective_user
    chat = update.effective_chat

    if not msg or not msg.text or not chat or chat.type != "private":
        return False

    text = msg.text.strip()
    cfg = load_config()

    if text == "🎛️ Painel de Controle":
        from modules.panel import generate_page_1
        title = chat.title or "Privado"
        t, m = generate_page_1(title, cfg)
        await msg.reply_text(t, reply_markup=m, parse_mode=ParseMode.MARKDOWN)
        return True

    if text == "🎼 Acervo de Partituras":
        from modules.inline_acervo import generate_acervo_dashboard_text_and_kb
        t, m = generate_acervo_dashboard_text_and_kb()
        await msg.reply_text(t, reply_markup=m, parse_mode=ParseMode.HTML)
        return True

    if text == "📢 Meus Canais":
        from modules.panel import generate_chats_list_page
        t, m = generate_chats_list_page(cfg)
        await msg.reply_text(t, reply_markup=m, parse_mode=ParseMode.MARKDOWN)
        return True

    if text == "👥 Meus Grupos":
        from modules.welcome_ui import generate_welcome_groups_selector
        t, m = generate_welcome_groups_selector(cfg)
        await msg.reply_text(t, reply_markup=m, parse_mode=ParseMode.HTML)
        return True

    if text == "🛡️ Whitelist & Links":
        t, m = generate_whitelist_hub(cfg)
        await msg.reply_text(t, reply_markup=m, parse_mode=ParseMode.HTML)
        return True

    if text == "❓ Ajuda & Comandos":
        help_text = (
            "📖 <b>GUIA DE COMANDOS RÁPIDOS</b>\n\n"
            "🎛️ <b>Painel & Navegação:</b>\n"
            "• <code>/painel</code> ou <code>/menu</code> — Abre os menus interativos\n"
            "• <code>/acervo</code> — Painel do Acervo Global (17.000 partituras)\n"
            "• <code>/status</code> — Diagnóstico das proteções do grupo\n\n"
            "🛡️ <b>Usuários Livres & Whitelist:</b>\n"
            "• <code>/livre</code> — Responda a uma mensagem de alguém no grupo para liberá-lo(a)\n"
            "• <code>/livre &lt;ID&gt;</code> — Libera um membro pelo ID ou @username\n"
            "• <code>/removerlivre &lt;ID&gt;</code> — Remove da lista de isenção\n"
            "• <code>/livres</code> — Lista todos os usuários livres\n\n"
            "🌐 <b>Links Permitidos:</b>\n"
            "• <code>/permitirlink drive.google.com</code> — Permite links do Drive\n"
            "• <code>/removerlink &lt;dominio&gt;</code> — Remove domínio da lista branca\n"
            "• <code>/linkspermitidos</code> — Lista domínios autorizados\n\n"
            "📢 <b>Canais e Transmissões:</b>\n"
            "• <code>/canais</code> ou <code>/grupos</code> — Ver chats vinculados\n"
            "• <code>/transmitir &lt;mensagem&gt;</code> — Envia para todos os canais e grupos"
        )
        await msg.reply_text(help_text, parse_mode=ParseMode.HTML)
        return True

    return False
