from modules.panel_support import *


async def on_cfg_wiz_start(self, update, context, cfg, title):
    query = update.callback_query
    chat = update.effective_chat
    user = update.effective_user
    data = query.data
    await query.answer()
    text, markup = generate_wizard_dest_menu(cfg)
    try:
        await query.edit_message_text(text, reply_markup=markup, parse_mode=ParseMode.MARKDOWN)
    except Exception:
        await query.edit_message_text(text, reply_markup=markup)
    return


async def on_cfg_wiz_add_channel(self, update, context, cfg, title):
    query = update.callback_query
    chat = update.effective_chat
    user = update.effective_user
    data = query.data
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


async def on_cfg_wiz_dest(self, update, context, cfg, title):
    query = update.callback_query
    chat = update.effective_chat
    user = update.effective_user
    data = query.data
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


async def on_cfg_wiz_edit_text(self, update, context, cfg, title):
    query = update.callback_query
    chat = update.effective_chat
    user = update.effective_user
    data = query.data
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


async def on_cfg_wiz_skip_media(self, update, context, cfg, title):
    query = update.callback_query
    chat = update.effective_chat
    user = update.effective_user
    data = query.data
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


async def on_cfg_wiz_edit_media(self, update, context, cfg, title):
    query = update.callback_query
    chat = update.effective_chat
    user = update.effective_user
    data = query.data
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


async def on_cfg_wiz_skip_buttons(self, update, context, cfg, title):
    query = update.callback_query
    chat = update.effective_chat
    user = update.effective_user
    data = query.data
    state = self._get_or_create_wizard_state(user.id)
    state["buttons"] = []
    if user.id in self.pending_inputs:
        del self.pending_inputs[user.id]
        self._save_pending_inputs()
    self._save_wizard_state(user.id, state)
    await query.answer()
    await self.show_wizard_preview(update, context, state, user.id)
    return


async def on_cfg_wiz_edit_buttons(self, update, context, cfg, title):
    query = update.callback_query
    chat = update.effective_chat
    user = update.effective_user
    data = query.data
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


async def on_cfg_wiz_toggle_pin(self, update, context, cfg, title):
    query = update.callback_query
    chat = update.effective_chat
    user = update.effective_user
    data = query.data
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


async def on_cfg_wiz_toggle_delay(self, update, context, cfg, title):
    query = update.callback_query
    chat = update.effective_chat
    user = update.effective_user
    data = query.data
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


async def on_cfg_wiz_sched_menu(self, update, context, cfg, title):
    query = update.callback_query
    chat = update.effective_chat
    user = update.effective_user
    data = query.data
    state = self.wizard_states.get(user.id, {})
    text, markup = generate_wizard_schedule_menu(cfg, state)
    await query.answer()
    try:
        await query.edit_message_text(text, reply_markup=markup, parse_mode=ParseMode.MARKDOWN)
    except Exception:
        await query.edit_message_text(text, reply_markup=markup)
    return


async def on_cfg_wiz_back_preview(self, update, context, cfg, title):
    query = update.callback_query
    chat = update.effective_chat
    user = update.effective_user
    data = query.data
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


async def on_cfg_wiz_set_rel(self, update, context, cfg, title):
    query = update.callback_query
    chat = update.effective_chat
    user = update.effective_user
    data = query.data
    mins = int(data.split(":")[-1])
    state = self.wizard_states.get(user.id, {})
    from config import get_timezone
    tz = get_timezone(cfg)
    target_dt = datetime.now(tz) + timedelta(minutes=mins)
    await query.answer("⏰ Agendando...")
    await self.save_scheduled_transmission(update, context, state, user.id, target_dt)
    return


async def on_cfg_wiz_set_time(self, update, context, cfg, title):
    query = update.callback_query
    chat = update.effective_chat
    user = update.effective_user
    data = query.data
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


async def on_cfg_wiz_set_custom(self, update, context, cfg, title):
    query = update.callback_query
    chat = update.effective_chat
    user = update.effective_user
    data = query.data
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


async def on_cfg_sched_list(self, update, context, cfg, title):
    query = update.callback_query
    chat = update.effective_chat
    user = update.effective_user
    data = query.data
    await query.answer()
    text, markup = generate_scheduled_transmissions_menu(cfg)
    try:
        await query.edit_message_text(text, reply_markup=markup, parse_mode=ParseMode.MARKDOWN)
    except Exception:
        await query.edit_message_text(text, reply_markup=markup)
    return


async def on_cfg_sched_cancel(self, update, context, cfg, title):
    query = update.callback_query
    chat = update.effective_chat
    user = update.effective_user
    data = query.data
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


async def on_cfg_sched_fire(self, update, context, cfg, title):
    query = update.callback_query
    chat = update.effective_chat
    user = update.effective_user
    data = query.data
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


async def on_cfg_wiz_send(self, update, context, cfg, title):
    query = update.callback_query
    chat = update.effective_chat
    user = update.effective_user
    data = query.data
    await query.answer("🚀 Enviando transmissão...")
    await self.execute_wizard_send(update, context, user.id)
    return


async def on_cfg_wiz_cancel(self, update, context, cfg, title):
    query = update.callback_query
    chat = update.effective_chat
    user = update.effective_user
    data = query.data
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
