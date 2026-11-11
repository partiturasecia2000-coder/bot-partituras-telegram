from modules.panel_support import *


async def on_cfg_sub_wtime(self, update, context, cfg, title):
    query = update.callback_query
    chat = update.effective_chat
    user = update.effective_user
    data = query.data
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


async def on_cfg_set_wtime(self, update, context, cfg, title):
    query = update.callback_query
    chat = update.effective_chat
    user = update.effective_user
    data = query.data
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


async def on_cfg_input_wtime(self, update, context, cfg, title):
    query = update.callback_query
    chat = update.effective_chat
    user = update.effective_user
    data = query.data
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


async def on_cfg_quick_save_welcome(self, update, context, cfg, title):
    query = update.callback_query
    chat = update.effective_chat
    user = update.effective_user
    data = query.data
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


async def on_cfg_chats_list(self, update, context, cfg, title):
    query = update.callback_query
    chat = update.effective_chat
    user = update.effective_user
    data = query.data
    text, markup = generate_chats_list_page(cfg)
    await query.edit_message_text(text, reply_markup=markup, parse_mode=ParseMode.MARKDOWN)
    return


async def on_cfg_chats_how_to(self, update, context, cfg, title):
    query = update.callback_query
    chat = update.effective_chat
    user = update.effective_user
    data = query.data
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


async def on_cfg_chat_info(self, update, context, cfg, title):
    query = update.callback_query
    chat = update.effective_chat
    user = update.effective_user
    data = query.data
    parts = data.split(":")
    chat_type = parts[3]
    target_id = parts[4]
    await query.answer()
    text, markup = generate_sub_chat_info(cfg, chat_type, target_id)
    await query.edit_message_text(text, reply_markup=markup, parse_mode=ParseMode.MARKDOWN)
    return


async def on_cfg_chat_set_main(self, update, context, cfg, title):
    query = update.callback_query
    chat = update.effective_chat
    user = update.effective_user
    data = query.data
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


async def on_cfg_chat_unlink(self, update, context, cfg, title):
    query = update.callback_query
    chat = update.effective_chat
    user = update.effective_user
    data = query.data
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


async def on_cfg_chat_post_prompt(self, update, context, cfg, title):
    query = update.callback_query
    chat = update.effective_chat
    user = update.effective_user
    data = query.data
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
