from modules.panel_support import *


async def on_cfg_close(self, update, context, cfg, title):
    query = update.callback_query
    chat = update.effective_chat
    user = update.effective_user
    data = query.data
    await query.answer("Painel fechado.")
    try:
        await query.edit_message_text(
            "✓ *Painel fechado*\nUse /painel para abrir novamente.",
            parse_mode=ParseMode.MARKDOWN
        )
    except Exception:
        await query.edit_message_text("Painel fechado. Use /painel para abrir novamente.")
    return


async def on_cfg_sub_acervo(self, update, context, cfg, title):
    query = update.callback_query
    chat = update.effective_chat
    user = update.effective_user
    data = query.data
    await query.answer()
    from modules.inline_acervo import generate_acervo_dashboard_text_and_kb
    text, markup = generate_acervo_dashboard_text_and_kb()
    await query.edit_message_text(text, reply_markup=markup, parse_mode=ParseMode.HTML)
    return


async def on_cfg_sub_timezone(self, update, context, cfg, title):
    query = update.callback_query
    chat = update.effective_chat
    user = update.effective_user
    data = query.data
    await query.answer()
    text, markup = generate_sub_timezone(cfg)
    await query.edit_message_text(text, reply_markup=markup, parse_mode=ParseMode.MARKDOWN)
    return


async def on_cfg_set_tz(self, update, context, cfg, title):
    query = update.callback_query
    chat = update.effective_chat
    user = update.effective_user
    data = query.data
    tz_name = data[len("cfg:set:tz:"):]
    from config import set_timezone, get_timezone_label
    set_timezone(cfg, tz_name)
    await query.answer(f"Fuso alterado para: {get_timezone_label(cfg)}!")
    text, markup = generate_sub_timezone(cfg)
    await query.edit_message_text(text, reply_markup=markup, parse_mode=ParseMode.MARKDOWN)
    return


async def on_cfg_input_tz(self, update, context, cfg, title):
    query = update.callback_query
    chat = update.effective_chat
    user = update.effective_user
    data = query.data
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


async def on_cfg_page_1(self, update, context, cfg, title):
    query = update.callback_query
    chat = update.effective_chat
    user = update.effective_user
    data = query.data
    await query.answer()
    text, markup = generate_page_1(title, cfg)
    await query.edit_message_text(text, reply_markup=markup, parse_mode=ParseMode.MARKDOWN)
    return


async def on_cfg_page_2(self, update, context, cfg, title):
    query = update.callback_query
    chat = update.effective_chat
    user = update.effective_user
    data = query.data
    await query.answer()
    text, markup = generate_hub_system(cfg)
    await query.edit_message_text(text, reply_markup=markup, parse_mode=ParseMode.MARKDOWN)
    return


async def on_cfg_hub_clean(self, update, context, cfg, title):
    query = update.callback_query
    chat = update.effective_chat
    user = update.effective_user
    data = query.data
    await query.answer()
    text, markup = generate_hub_clean(cfg)
    await query.edit_message_text(text, reply_markup=markup, parse_mode=ParseMode.MARKDOWN)
    return


async def on_cfg_hub_security(self, update, context, cfg, title):
    query = update.callback_query
    chat = update.effective_chat
    user = update.effective_user
    data = query.data
    await query.answer()
    text, markup = generate_hub_security(cfg)
    await query.edit_message_text(text, reply_markup=markup, parse_mode=ParseMode.MARKDOWN)
    return


async def on_cfg_hub_welcome(self, update, context, cfg, title):
    query = update.callback_query
    chat = update.effective_chat
    user = update.effective_user
    data = query.data
    await query.answer()
    text, markup = generate_hub_welcome(cfg)
    await query.edit_message_text(text, reply_markup=markup, parse_mode=ParseMode.MARKDOWN)
    return


async def on_cfg_hub_messages(self, update, context, cfg, title):
    query = update.callback_query
    chat = update.effective_chat
    user = update.effective_user
    data = query.data
    await query.answer()
    text, markup = generate_hub_messages(cfg)
    await query.edit_message_text(text, reply_markup=markup, parse_mode=ParseMode.MARKDOWN)
    return


async def on_cfg_hub_system(self, update, context, cfg, title):
    query = update.callback_query
    chat = update.effective_chat
    user = update.effective_user
    data = query.data
    await query.answer()
    text, markup = generate_hub_system(cfg)
    await query.edit_message_text(text, reply_markup=markup, parse_mode=ParseMode.MARKDOWN)
    return


async def on_cfg_sub_clean_help(self, update, context, cfg, title):
    query = update.callback_query
    chat = update.effective_chat
    user = update.effective_user
    data = query.data
    await query.answer()
    text, markup = generate_sub_clean_help()
    await query.edit_message_text(text, reply_markup=markup, parse_mode=ParseMode.MARKDOWN)
    return


async def on_cfg_sub_rules(self, update, context, cfg, title):
    query = update.callback_query
    chat = update.effective_chat
    user = update.effective_user
    data = query.data
    await query.answer()
    text, markup = generate_sub_rules(cfg)
    await query.edit_message_text(text, reply_markup=markup, parse_mode=ParseMode.MARKDOWN)
    return


async def on_cfg_sub_cmd_clean(self, update, context, cfg, title):
    query = update.callback_query
    chat = update.effective_chat
    user = update.effective_user
    data = query.data
    await query.answer()
    text, markup = generate_sub_cmd_clean(cfg)
    await query.edit_message_text(text, reply_markup=markup, parse_mode=ParseMode.MARKDOWN)
    return


async def on_cfg_sub_antispam(self, update, context, cfg, title):
    query = update.callback_query
    chat = update.effective_chat
    user = update.effective_user
    data = query.data
    await query.answer()
    text, markup = generate_sub_antispam(cfg)
    await query.edit_message_text(text, reply_markup=markup, parse_mode=ParseMode.MARKDOWN)
    return


async def on_cfg_sub_antiflood(self, update, context, cfg, title):
    query = update.callback_query
    chat = update.effective_chat
    user = update.effective_user
    data = query.data
    await query.answer()
    text, markup = generate_sub_antiflood(cfg)
    await query.edit_message_text(text, reply_markup=markup, parse_mode=ParseMode.MARKDOWN)
    return


async def on_cfg_sub_banned(self, update, context, cfg, title):
    query = update.callback_query
    chat = update.effective_chat
    user = update.effective_user
    data = query.data
    await query.answer()
    text, markup = generate_sub_banned(cfg)
    await query.edit_message_text(text, reply_markup=markup, parse_mode=ParseMode.MARKDOWN)
    return


async def on_cfg_sub_clean(self, update, context, cfg, title):
    query = update.callback_query
    chat = update.effective_chat
    user = update.effective_user
    data = query.data
    await query.answer()
    text, markup = generate_hub_clean(cfg)
    await query.edit_message_text(text, reply_markup=markup, parse_mode=ParseMode.MARKDOWN)
    return


async def on_cfg_sub_logs(self, update, context, cfg, title):
    query = update.callback_query
    chat = update.effective_chat
    user = update.effective_user
    data = query.data
    await query.answer()
    text, markup = generate_sub_logs(cfg)
    await query.edit_message_text(text, reply_markup=markup, parse_mode=ParseMode.MARKDOWN)
    return


async def on_cfg_sub_nightmode(self, update, context, cfg, title):
    query = update.callback_query
    chat = update.effective_chat
    user = update.effective_user
    data = query.data
    await query.answer()
    text, markup = generate_sub_nightmode(cfg)
    await query.edit_message_text(text, reply_markup=markup, parse_mode=ParseMode.MARKDOWN)
    return


async def on_cfg_sub_docs(self, update, context, cfg, title):
    query = update.callback_query
    chat = update.effective_chat
    user = update.effective_user
    data = query.data
    await query.answer()
    text, markup = generate_sub_docs()
    await query.edit_message_text(text, reply_markup=markup, parse_mode=ParseMode.MARKDOWN)
    return


async def on_cfg_test_nightmode_start(self, update, context, cfg, title):
    query = update.callback_query
    chat = update.effective_chat
    user = update.effective_user
    data = query.data
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


async def on_cfg_logs_set_id(self, update, context, cfg, title):
    query = update.callback_query
    chat = update.effective_chat
    user = update.effective_user
    data = query.data
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


async def on_cfg_logs_test(self, update, context, cfg, title):
    query = update.callback_query
    chat = update.effective_chat
    user = update.effective_user
    data = query.data
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


async def on_cfg_logs_clear(self, update, context, cfg, title):
    query = update.callback_query
    chat = update.effective_chat
    user = update.effective_user
    data = query.data
    cfg["log_channel_id"] = None
    save_config(cfg)
    await query.answer("Canal de logs desativado!")
    text, markup = generate_sub_logs(cfg)
    await query.edit_message_text(text, reply_markup=markup, parse_mode=ParseMode.MARKDOWN)
    return


async def on_cfg_logs_toggle(self, update, context, cfg, title):
    query = update.callback_query
    chat = update.effective_chat
    user = update.effective_user
    data = query.data
    ev_key = data.split(":")[-1]
    events = cfg.setdefault("log_events", {})
    events[ev_key] = not events.get(ev_key, True)
    save_config(cfg)
    status_lbl = "Ativado" if events[ev_key] else "Desativado"
    await query.answer(f"Log de {ev_key}: {status_lbl}")
    text, markup = generate_sub_logs(cfg)
    await query.edit_message_text(text, reply_markup=markup, parse_mode=ParseMode.MARKDOWN)
    return


async def on_cfg_noop(self, update, context, cfg, title):
    query = update.callback_query
    chat = update.effective_chat
    user = update.effective_user
    data = query.data
    await query.answer()
    return
