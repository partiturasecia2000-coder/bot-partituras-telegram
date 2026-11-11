from modules.panel_support import *


async def on_cfg_sub_youtube(self, update, context, cfg, title):
    query = update.callback_query
    chat = update.effective_chat
    user = update.effective_user
    data = query.data
    await query.answer()
    text, markup = generate_sub_youtube(cfg)
    await query.edit_message_text(text, reply_markup=markup, parse_mode=ParseMode.MARKDOWN)
    return


async def on_cfg_toggle_youtube(self, update, context, cfg, title):
    query = update.callback_query
    chat = update.effective_chat
    user = update.effective_user
    data = query.data
    yt_cfg = cfg.setdefault("youtube_notifications", {
        "enabled": True, "target_chat": "@partiturasecia", "check_interval_minutes": 5, "channels": []
    })
    yt_cfg["enabled"] = not yt_cfg.get("enabled", True)
    save_config(cfg)
    await query.answer("Status do Notificador do YouTube alterado!")
    text, markup = generate_sub_youtube(cfg)
    await query.edit_message_text(text, reply_markup=markup, parse_mode=ParseMode.MARKDOWN)
    return


async def on_cfg_youtube_add(self, update, context, cfg, title):
    query = update.callback_query
    chat = update.effective_chat
    user = update.effective_user
    data = query.data
    await query.answer()
    self.pending_inputs[user.id] = {"action": "youtube_add"}
    prompt = (
        "🎬 <b>Adicionar Canal do YouTube</b>\n\n"
        "Envie o <b>@handle</b> ou o <b>link do canal</b> que você deseja monitorar.\n\n"
        "<i>Exemplos aceitos:</i>\n"
        "• <code>@NomeDoCanal</code>\n"
        "• <code>https://www.youtube.com/@NomeDoCanal</code>\n"
        "• <code>https://www.youtube.com/channel/UC...</code>\n\n"
        "Envie agora ou digite /cancelar:"
    )
    await query.message.reply_text(prompt, parse_mode=ParseMode.HTML)
    return


async def on_cfg_youtube_del(self, update, context, cfg, title):
    query = update.callback_query
    chat = update.effective_chat
    user = update.effective_user
    data = query.data
    await query.answer()
    text, markup = generate_sub_youtube_delete(cfg)
    await query.edit_message_text(text, reply_markup=markup, parse_mode=ParseMode.MARKDOWN)
    return


async def on_cfg_youtube_rm(self, update, context, cfg, title):
    query = update.callback_query
    chat = update.effective_chat
    user = update.effective_user
    data = query.data
    await query.answer()
    idx_str = data.split(":")[-1]
    success, msg = remove_youtube_channel(cfg, idx_str)
    cfg = load_config()
    text, markup = generate_sub_youtube_delete(cfg)
    try:
        await query.edit_message_text(text, reply_markup=markup, parse_mode=ParseMode.MARKDOWN)
    except Exception:
        pass
    return


async def on_cfg_youtube_target(self, update, context, cfg, title):
    query = update.callback_query
    chat = update.effective_chat
    user = update.effective_user
    data = query.data
    await query.answer()
    self.pending_inputs[user.id] = {"action": "youtube_target"}
    cur_target = cfg.get("youtube_notifications", {}).get("target_chat", "@partiturasecia")
    prompt = (
        "🎯 <b>Definir Grupo Destino do YouTube</b>\n\n"
        f"Destino atual configurado: <code>{cur_target}</code>\n\n"
        "Envie o @username do grupo (ex: <code>@partiturasecia</code>) ou o ID numérico do chat (ex: <code>-100...</code>).\n\n"
        "Envie agora ou digite /cancelar:"
    )
    await query.message.reply_text(prompt, parse_mode=ParseMode.HTML)
    return


async def on_cfg_youtube_test(self, update, context, cfg, title):
    query = update.callback_query
    chat = update.effective_chat
    user = update.effective_user
    data = query.data
    await query.answer("Enviando card de teste...")
    target = cfg.get("youtube_notifications", {}).get("target_chat") or cfg.get("main_group_id") or "@partiturasecia"
    ok, res_msg = await send_youtube_test_card(context.bot, target, cfg)
    if ok:
        await query.message.reply_text(f"🚀 {res_msg}", parse_mode=ParseMode.HTML)
    else:
        await query.message.reply_text(f"⚠️ {res_msg}", parse_mode=ParseMode.HTML)
    return
