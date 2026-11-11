from modules.panel_support import *
import html


async def on_youtube_add(self, update, context, cfg, state, action):
    user = update.effective_user
    msg = update.effective_message
    raw_input = msg.text.strip() if msg.text else ""
    if not raw_input:
        await msg.reply_text("❌ Por favor, envie um @handle ou link válido do canal do YouTube, ou digite /cancelar.")
        return True

    del self.pending_inputs[user.id]
    wait_msg = await msg.reply_text("🔍 <i>Consultando dados do canal no YouTube, aguarde...</i>", parse_mode=ParseMode.HTML)

    cfg = load_config()
    success, res_text, ch_data = add_youtube_channel(cfg, raw_input)
    try:
        await wait_msg.delete()
    except Exception:
        pass

    if success:
        kb = [[InlineKeyboardButton("🎬 Voltar ao Notificador", callback_data="cfg:sub:youtube")]]
        await msg.reply_text(
            f"✅ {res_text}\n\n"
            f"📺 Canal: <b>{ch_data.get('name')}</b>\n"
            f"🔗 Link: {ch_data.get('url')}\n"
            f"⏱️ Verificação: A cada 5 minutos\n\n"
            f"<i>O bot anunciará novos vídeos automaticamente no grupo!</i>",
            reply_markup=InlineKeyboardMarkup(kb),
            parse_mode=ParseMode.HTML
        )
    else:
        kb = [[InlineKeyboardButton("➕ Tentar Novamente", callback_data="cfg:youtube:add")]]
        await msg.reply_text(f"⚠️ {res_text}", reply_markup=InlineKeyboardMarkup(kb), parse_mode=ParseMode.HTML)
    return True


async def on_backup_channel(self, update, context, cfg, state, action):
    user = update.effective_user
    msg = update.effective_message
    raw_input = msg.text.strip() if msg.text else ""
    if not raw_input:
        await msg.reply_text("❌ Por favor, envie o ID numérico do canal (ex: -1004462851433), ou digite /cancelar.")
        return True

    try:
        ch_id = int(raw_input)
    except ValueError:
        await msg.reply_text("❌ ID inválido. O ID do canal deve ser numérico (ex: <code>-1004462851433</code>). Tente novamente ou digite /cancelar.", parse_mode=ParseMode.HTML)
        return True

    del self.pending_inputs[user.id]
    cfg = load_config()
    b_cfg = cfg.setdefault("backup_system", {
        "enabled": True, "channel_id": -1004462851433,
        "daily_backup_enabled": True, "daily_backup_interval_hours": 24,
        "last_daily_backup_timestamp": 0, "weekly_report_enabled": True,
        "weekly_report_interval_days": 7, "last_weekly_report_timestamp": 0
    })
    b_cfg["channel_id"] = ch_id
    save_config(cfg)

    kb = [[InlineKeyboardButton("💾 Voltar a Backups", callback_data="cfg:sub:backup")]]
    await msg.reply_text(
        f"✅ Canal de Backup & Relatórios atualizado para: <code>{ch_id}</code>!",
        reply_markup=InlineKeyboardMarkup(kb),
        parse_mode=ParseMode.HTML
    )
    return True


async def on_youtube_target(self, update, context, cfg, state, action):
    user = update.effective_user
    msg = update.effective_message
    raw_input = msg.text.strip() if msg.text else ""
    if not raw_input:
        await msg.reply_text("❌ Por favor, envie o @username ou ID do grupo, ou digite /cancelar.")
        return True

    del self.pending_inputs[user.id]
    cfg = load_config()
    yt_cfg = cfg.setdefault("youtube_notifications", {
        "enabled": True, "target_chat": "@partiturasecia", "check_interval_minutes": 5, "channels": []
    })
    yt_cfg["target_chat"] = raw_input
    save_config(cfg)

    kb = [[InlineKeyboardButton("🎬 Voltar ao Notificador", callback_data="cfg:sub:youtube")]]
    await msg.reply_text(
        f"✅ Grupo destino atualizado com sucesso para: <code>{raw_input}</code>!",
        reply_markup=InlineKeyboardMarkup(kb),
        parse_mode=ParseMode.HTML
    )
    return True


async def on_acervo_set_channel_link(self, update, context, cfg, state, action):
    user = update.effective_user
    msg = update.effective_message
    target_id = state.get("target_id")
    channel_title = state.get("channel_title", "Canal")
    raw_url = msg.text.strip() if msg.text else ""
    if not (raw_url.startswith("http://") or raw_url.startswith("https://") or raw_url.startswith("@")):
        await msg.reply_text("❌ Por favor, envie um link válido (ex: <code>https://t.me/+AbCdEfGh</code> ou <code>@seucanal</code>), ou digite /cancelar.", parse_mode=ParseMode.HTML)
        return True

    cfg = load_config()
    if "channel_invite_links" not in cfg:
        cfg["channel_invite_links"] = {}
    cfg["channel_invite_links"][str(target_id)] = raw_url

    for ch in cfg.get("linked_channels", []):
        if str(ch.get("id")) == str(target_id):
            ch["invite_link"] = raw_url

    save_config(cfg)
    del self.pending_inputs[user.id]

    from modules.inline_acervo import generate_channel_links_menu_text_and_kb
    text, markup = generate_channel_links_menu_text_and_kb()
    await msg.reply_text(
        f"✅ <b>Link de Entrada Salvo com Sucesso!</b>\n\n"
        f"📢 <b>Canal:</b> {html.escape(channel_title)}\n"
        f"🔗 <b>Link:</b> <code>{html.escape(raw_url)}</code>\n\n"
        f"Agora quando alguém buscar uma partitura deste canal, o botão <b>'1º Entrar no Canal'</b> levará para este link!",
        parse_mode=ParseMode.HTML,
        reply_markup=markup
    )
    return True
