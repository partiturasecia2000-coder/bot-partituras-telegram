from modules.panel_support import *


async def on_cfg_sub_backup(self, update, context, cfg, title):
    query = update.callback_query
    chat = update.effective_chat
    user = update.effective_user
    data = query.data
    await query.answer()
    text, markup = generate_sub_backup(cfg)
    await query.edit_message_text(text, reply_markup=markup, parse_mode=ParseMode.MARKDOWN)
    return


async def on_cfg_toggle_daily_bkp(self, update, context, cfg, title):
    query = update.callback_query
    chat = update.effective_chat
    user = update.effective_user
    data = query.data
    b_cfg = cfg.setdefault("backup_system", {
        "enabled": True, "channel_id": -1004462851433,
        "daily_backup_enabled": True, "daily_backup_interval_hours": 24,
        "last_daily_backup_timestamp": 0, "weekly_report_enabled": True,
        "weekly_report_interval_days": 7, "last_weekly_report_timestamp": 0
    })
    b_cfg["daily_backup_enabled"] = not b_cfg.get("daily_backup_enabled", True)
    save_config(cfg)
    await query.answer("Status do Backup Diário alterado!")
    text, markup = generate_sub_backup(cfg)
    await query.edit_message_text(text, reply_markup=markup, parse_mode=ParseMode.MARKDOWN)
    return


async def on_cfg_toggle_weekly_rep(self, update, context, cfg, title):
    query = update.callback_query
    chat = update.effective_chat
    user = update.effective_user
    data = query.data
    b_cfg = cfg.setdefault("backup_system", {
        "enabled": True, "channel_id": -1004462851433,
        "daily_backup_enabled": True, "daily_backup_interval_hours": 24,
        "last_daily_backup_timestamp": 0, "weekly_report_enabled": True,
        "weekly_report_interval_days": 7, "last_weekly_report_timestamp": 0
    })
    b_cfg["weekly_report_enabled"] = not b_cfg.get("weekly_report_enabled", True)
    save_config(cfg)
    await query.answer("Status do Relatório Semanal alterado!")
    text, markup = generate_sub_backup(cfg)
    await query.edit_message_text(text, reply_markup=markup, parse_mode=ParseMode.MARKDOWN)
    return


async def on_cfg_bkp_now(self, update, context, cfg, title):
    query = update.callback_query
    chat = update.effective_chat
    user = update.effective_user
    data = query.data
    await query.answer("Gerando e enviando arquivo ZIP de backup...")
    b_channel = cfg.get("backup_system", {}).get("channel_id", -1004462851433)
    ok, res_msg = await send_daily_backup(context.bot, b_channel, is_manual=True)
    if ok:
        await query.message.reply_text(f"💾 {res_msg}", parse_mode=ParseMode.HTML)
    else:
        await query.message.reply_text(f"⚠️ {res_msg}", parse_mode=ParseMode.HTML)
    cfg = load_config()
    text, markup = generate_sub_backup(cfg)
    try:
        await query.edit_message_text(text, reply_markup=markup, parse_mode=ParseMode.MARKDOWN)
    except Exception:
        pass
    return


async def on_cfg_rep_now(self, update, context, cfg, title):
    query = update.callback_query
    chat = update.effective_chat
    user = update.effective_user
    data = query.data
    await query.answer("Gerando e enviando relatório semanal...")
    b_channel = cfg.get("backup_system", {}).get("channel_id", -1004462851433)
    ok, res_msg = await send_weekly_report(context.bot, b_channel, is_manual=True)
    if ok:
        await query.message.reply_text(f"📊 {res_msg}", parse_mode=ParseMode.HTML)
    else:
        await query.message.reply_text(f"⚠️ {res_msg}", parse_mode=ParseMode.HTML)
    cfg = load_config()
    text, markup = generate_sub_backup(cfg)
    try:
        await query.edit_message_text(text, reply_markup=markup, parse_mode=ParseMode.MARKDOWN)
    except Exception:
        pass
    return


async def on_cfg_bkp_channel(self, update, context, cfg, title):
    query = update.callback_query
    chat = update.effective_chat
    user = update.effective_user
    data = query.data
    await query.answer()
    self.pending_inputs[user.id] = {"action": "backup_channel"}
    cur_ch = cfg.get("backup_system", {}).get("channel_id", -1004462851433)
    prompt = (
        "🎯 <b>Definir Canal de Backup & Relatórios</b>\n\n"
        f"Canal atual configurado: <code>{cur_ch}</code>\n\n"
        "Envie o ID numérico do canal (ex: <code>-1004462851433</code>) ou encaminhe uma mensagem dele.\n\n"
        "Envie agora ou digite /cancelar:"
    )
    await query.message.reply_text(prompt, parse_mode=ParseMode.HTML)
    return
