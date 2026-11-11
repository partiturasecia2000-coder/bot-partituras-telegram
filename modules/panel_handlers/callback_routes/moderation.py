from modules.panel_support import *


async def on_cfg_cycle_timezone(self, update, context, cfg, title):
    query = update.callback_query
    chat = update.effective_chat
    user = update.effective_user
    data = query.data
    new_tz = cycle_timezone(cfg)
    tz_lbl = get_timezone_label(cfg)
    await query.answer(f"Fuso horário alterado para: {tz_lbl}")
    # Atualiza a página onde o usuário estava
    text, markup = generate_page_2(title, cfg)
    await query.edit_message_text(text, reply_markup=markup, parse_mode=ParseMode.MARKDOWN)
    return


async def on_cfg_toggle_nightmode(self, update, context, cfg, title):
    query = update.callback_query
    chat = update.effective_chat
    user = update.effective_user
    data = query.data
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


async def on_cfg_toggle_nightmode_ann(self, update, context, cfg, title):
    query = update.callback_query
    chat = update.effective_chat
    user = update.effective_user
    data = query.data
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


async def on_cfg_banned_cycle_action(self, update, context, cfg, title):
    query = update.callback_query
    chat = update.effective_chat
    user = update.effective_user
    data = query.data
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


async def on_cfg_banned_add(self, update, context, cfg, title):
    query = update.callback_query
    chat = update.effective_chat
    user = update.effective_user
    data = query.data
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


async def on_cfg_banned_remove(self, update, context, cfg, title):
    query = update.callback_query
    chat = update.effective_chat
    user = update.effective_user
    data = query.data
    self.pending_inputs[user.id] = {"action": "banned_remove", "chat_id": chat.id}
    await query.answer()
    prompt = (
        "🗑️ *Remover Palavras Proibidas:*\n\n"
        "Envie os termos que deseja retirar da lista negra (separados por vírgula ou um por linha).\n\n"
        "_Envie agora ou digite /cancelar:_"
    )
    await chat.send_message(prompt, parse_mode=ParseMode.MARKDOWN)
    return


async def on_cfg_banned_view_all(self, update, context, cfg, title):
    query = update.callback_query
    chat = update.effective_chat
    user = update.effective_user
    data = query.data
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


async def on_cfg_banned_clear_all(self, update, context, cfg, title):
    query = update.callback_query
    chat = update.effective_chat
    user = update.effective_user
    data = query.data
    cfg.setdefault("antispam", {})["banned_words"] = []
    save_config(cfg)
    await query.answer("Todas as palavras proibidas foram apagadas!")
    text, markup = generate_sub_banned(cfg)
    await query.edit_message_text(text, reply_markup=markup, parse_mode=ParseMode.MARKDOWN)
    return


async def on_cfg_toggle_antispam(self, update, context, cfg, title):
    query = update.callback_query
    chat = update.effective_chat
    user = update.effective_user
    data = query.data
    cur = cfg.setdefault("antispam", {}).get("enabled", True)
    cfg["antispam"]["enabled"] = not cur
    save_config(cfg)
    await query.answer(f"Anti-spam: {'Ativado' if not cur else 'Desativado'}")
    text, markup = generate_sub_antispam(cfg)
    await query.edit_message_text(text, reply_markup=markup, parse_mode=ParseMode.MARKDOWN)
    return


async def on_cfg_toggle_links(self, update, context, cfg, title):
    query = update.callback_query
    chat = update.effective_chat
    user = update.effective_user
    data = query.data
    cur = cfg.setdefault("antispam", {}).get("block_links", True)
    cfg["antispam"]["block_links"] = not cur
    save_config(cfg)
    await query.answer(f"Bloqueio de links: {'Ativado' if not cur else 'Desativado'}")
    text, markup = generate_hub_security(cfg)
    await query.edit_message_text(text, reply_markup=markup, parse_mode=ParseMode.MARKDOWN)
    return


async def on_cfg_toggle_invites(self, update, context, cfg, title):
    query = update.callback_query
    chat = update.effective_chat
    user = update.effective_user
    data = query.data
    cur = cfg.setdefault("antispam", {}).get("block_telegram_invites", True)
    cfg["antispam"]["block_telegram_invites"] = not cur
    save_config(cfg)
    await query.answer(f"Bloqueio de convites: {'Ativado' if not cur else 'Desativado'}")
    text, markup = generate_hub_security(cfg)
    await query.edit_message_text(text, reply_markup=markup, parse_mode=ParseMode.MARKDOWN)
    return


async def on_cfg_toggle_forwards(self, update, context, cfg, title):
    query = update.callback_query
    chat = update.effective_chat
    user = update.effective_user
    data = query.data
    cur = cfg.setdefault("antispam", {}).get("block_forwards", True)
    cfg["antispam"]["block_forwards"] = not cur
    save_config(cfg)
    await query.answer(f"Bloqueio de encaminhamentos: {'Ativado' if not cur else 'Desativado'}")
    text, markup = generate_hub_security(cfg)
    await query.edit_message_text(text, reply_markup=markup, parse_mode=ParseMode.MARKDOWN)
    return


async def on_cfg_toggle_user_repeat(self, update, context, cfg, title):
    query = update.callback_query
    chat = update.effective_chat
    user = update.effective_user
    data = query.data
    cur = cfg.setdefault("antirepeat", {}).get("enabled", True)
    cfg["antirepeat"]["enabled"] = not cur
    save_config(cfg)
    await query.answer(f"Filtro anti-repetição de membros: {'Ativado' if not cur else 'Desativado'}")
    text, markup = generate_hub_security(cfg)
    await query.edit_message_text(text, reply_markup=markup, parse_mode=ParseMode.MARKDOWN)
    return


async def on_cfg_toggle_flood(self, update, context, cfg, title):
    query = update.callback_query
    chat = update.effective_chat
    user = update.effective_user
    data = query.data
    cur = cfg.setdefault("antiflood", {}).get("enabled", True)
    cfg["antiflood"]["enabled"] = not cur
    save_config(cfg)
    await query.answer(f"Anti-flood: {'Ativado' if not cur else 'Desativado'}")
    text, markup = generate_sub_antiflood(cfg)
    await query.edit_message_text(text, reply_markup=markup, parse_mode=ParseMode.MARKDOWN)
    return


async def on_cfg_toggle_service_msg(self, update, context, cfg, title):
    query = update.callback_query
    chat = update.effective_chat
    user = update.effective_user
    data = query.data
    cur = cfg.setdefault("welcome", {}).get("delete_service_messages", True)
    cfg["welcome"]["delete_service_messages"] = not cur
    save_config(cfg)
    await query.answer(f"Limpar msg de entrada: {'Ativado' if not cur else 'Desativado'}")
    text, markup = generate_hub_clean(cfg)
    await query.edit_message_text(text, reply_markup=markup, parse_mode=ParseMode.MARKDOWN)
    return


async def on_cfg_toggle_pin_service_msg(self, update, context, cfg, title):
    query = update.callback_query
    chat = update.effective_chat
    user = update.effective_user
    data = query.data
    cur = cfg.get("delete_pinned_service_messages", True)
    cfg["delete_pinned_service_messages"] = not cur
    save_config(cfg)
    await query.answer(f"Limpar avisos de fixado: {'Ativado' if not cur else 'Desativado'}")
    text, markup = generate_hub_clean(cfg)
    await query.edit_message_text(text, reply_markup=markup, parse_mode=ParseMode.MARKDOWN)
    return


async def on_cfg_toggle_welcome(self, update, context, cfg, title):
    query = update.callback_query
    chat = update.effective_chat
    user = update.effective_user
    data = query.data
    cur = cfg.setdefault("welcome", {}).get("enabled", True)
    cfg["welcome"]["enabled"] = not cur
    save_config(cfg)
    await query.answer(f"Boas-vindas: {'Ativadas' if not cur else 'Desativadas'}")
    text, markup = generate_hub_welcome(cfg)
    await query.edit_message_text(text, reply_markup=markup, parse_mode=ParseMode.MARKDOWN)
    return


async def on_cfg_toggle_captcha(self, update, context, cfg, title):
    query = update.callback_query
    chat = update.effective_chat
    user = update.effective_user
    data = query.data
    cur = cfg.setdefault("captcha", {}).get("enabled", False)
    cfg["captcha"]["enabled"] = not cur
    save_config(cfg)
    await query.answer(f"Anti-Bot CAPTCHA: {'Ativado' if not cur else 'Desativado'}")
    text, markup = generate_hub_security(cfg)
    await query.edit_message_text(text, reply_markup=markup, parse_mode=ParseMode.MARKDOWN)
    return


async def on_cfg_toggle_join_req(self, update, context, cfg, title):
    query = update.callback_query
    chat = update.effective_chat
    user = update.effective_user
    data = query.data
    cur = cfg.setdefault("join_requests", {}).get("auto_approve", False)
    cfg["join_requests"]["auto_approve"] = not cur
    save_config(cfg)
    await query.answer(f"Auto-aprovação de entrada: {'Ativada' if not cur else 'Desativada'}")
    text, markup = generate_hub_welcome(cfg)
    await query.edit_message_text(text, reply_markup=markup, parse_mode=ParseMode.MARKDOWN)
    return


async def on_cfg_toggle_cmd_clean(self, update, context, cfg, title):
    query = update.callback_query
    chat = update.effective_chat
    user = update.effective_user
    data = query.data
    cur = cfg.setdefault("command_cleanup", {}).get("delete_admin_commands", True)
    cfg["command_cleanup"]["delete_admin_commands"] = not cur
    cfg["command_cleanup"]["delete_non_admin_commands"] = not cur
    save_config(cfg)
    await query.answer(f"Limpeza de comandos: {'Ativada' if not cur else 'Desativada'}")
    text, markup = generate_sub_cmd_clean(cfg)
    await query.edit_message_text(text, reply_markup=markup, parse_mode=ParseMode.MARKDOWN)
    return


async def on_cfg_toggle_clean_admin(self, update, context, cfg, title):
    query = update.callback_query
    chat = update.effective_chat
    user = update.effective_user
    data = query.data
    cc = cfg.setdefault("command_cleanup", {})
    cur = cc.get("delete_admin_commands", True)
    cc["delete_admin_commands"] = not cur
    save_config(cfg)
    await query.answer(f"Comandos de Admin: {'Ativado' if not cur else 'Desativado'}")
    text, markup = generate_sub_cmd_clean(cfg)
    await query.edit_message_text(text, reply_markup=markup, parse_mode=ParseMode.MARKDOWN)
    return


async def on_cfg_toggle_clean_user(self, update, context, cfg, title):
    query = update.callback_query
    chat = update.effective_chat
    user = update.effective_user
    data = query.data
    cc = cfg.setdefault("command_cleanup", {})
    cur = cc.get("delete_non_admin_commands", True)
    cc["delete_non_admin_commands"] = not cur
    save_config(cfg)
    await query.answer(f"Comandos de Membros: {'Ativado' if not cur else 'Desativado'}")
    text, markup = generate_sub_cmd_clean(cfg)
    await query.edit_message_text(text, reply_markup=markup, parse_mode=ParseMode.MARKDOWN)
    return


async def on_cfg_cycle_clean_notice(self, update, context, cfg, title):
    query = update.callback_query
    chat = update.effective_chat
    user = update.effective_user
    data = query.data
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


async def on_cfg_cycle_repeat_window(self, update, context, cfg, title):
    query = update.callback_query
    chat = update.effective_chat
    user = update.effective_user
    data = query.data
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


async def on_cfg_cycle_welcome_time(self, update, context, cfg, title):
    query = update.callback_query
    chat = update.effective_chat
    user = update.effective_user
    data = query.data
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


async def on_cfg_cycle_flood_mute(self, update, context, cfg, title):
    query = update.callback_query
    chat = update.effective_chat
    user = update.effective_user
    data = query.data
    cur = cfg.setdefault("antiflood", {}).get("mute_duration_minutes", 5)
    next_vals = {5: 15, 15: 30, 30: 60, 60: 5}
    new_val = next_vals.get(cur, 5)
    cfg["antiflood"]["mute_duration_minutes"] = new_val
    save_config(cfg)
    await query.answer(f"Punição: silenciar por {new_val} min")
    text, markup = generate_sub_antiflood(cfg)
    await query.edit_message_text(text, reply_markup=markup, parse_mode=ParseMode.MARKDOWN)
    return
