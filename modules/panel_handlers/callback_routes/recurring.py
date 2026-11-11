from modules.panel_support import *


async def on_cfg_rec_list(self, update, context, cfg, title):
    query = update.callback_query
    chat = update.effective_chat
    user = update.effective_user
    data = query.data
    parts = data.split(":")
    page = int(parts[-1]) if len(parts) >= 4 and parts[-1].isdigit() else 1
    await query.answer()
    text, markup = generate_recurring_list(title, cfg, page=page)
    try:
        await query.edit_message_text(text, reply_markup=markup, parse_mode=ParseMode.MARKDOWN)
    except Exception:
        await query.edit_message_text(text, reply_markup=markup)
    return


async def on_cfg_rec_add(self, update, context, cfg, title):
    query = update.callback_query
    chat = update.effective_chat
    user = update.effective_user
    data = query.data
    parts = data.split(":")
    page = int(parts[-1]) if len(parts) >= 4 and parts[-1].isdigit() else 1
    rec_list = cfg.setdefault("recurring_messages", [])
    new_id = (max([m.get("id", 0) for m in rec_list] or [0])) + 1
    main_target = chat.id if chat.type in ("group", "supergroup") else cfg.get("main_group_id")
    new_item = {
        "id": new_id,
        "enabled": True,
        "text": "📢 Esta é uma mensagem programada automática! Personalize este texto como desejar.",
        "photo": None,
        "buttons": [],
        "repeat_mode": "interval",
        "interval_type": "hours",
        "interval_value": 24,
        "interval_minutes": 1440,
        "messages_interval": 50,
        "messages_counter_last": 0,
        "start_hour": None,
        "start_minute": None,
        "weekdays": [0, 1, 2, 3, 4, 5, 6],
        "month_days": [],
        "start_date": None,
        "end_date": None,
        "pin_message": False,
        "delete_previous": False,
        "auto_delete_seconds": 0,
        "last_message_id": None,
        "last_sent_timestamp": 0,
        "chat_id": main_target
    }
    rec_list.append(new_item)
    save_config(cfg)
    await query.answer(f"Mensagem #{new_id} criada!")
    text, markup = generate_recurring_detail(cfg, new_id, page=page)
    await query.edit_message_text(text, reply_markup=markup, parse_mode=ParseMode.MARKDOWN)
    return


async def on_cfg_rec_detail(self, update, context, cfg, title):
    query = update.callback_query
    chat = update.effective_chat
    user = update.effective_user
    data = query.data
    parts = data.split(":")
    msg_id = int(parts[3])
    page = int(parts[4]) if len(parts) > 4 and parts[4].isdigit() else 1
    await query.answer()
    text, markup = generate_recurring_detail(cfg, msg_id, page=page)
    await query.edit_message_text(text, reply_markup=markup, parse_mode=ParseMode.MARKDOWN)
    return


async def on_cfg_rec_toggle(self, update, context, cfg, title):
    query = update.callback_query
    chat = update.effective_chat
    user = update.effective_user
    data = query.data
    parts = data.split(":")
    msg_id = int(parts[3])
    page = int(parts[4]) if len(parts) > 4 and parts[4].isdigit() else None
    rec_list = cfg.get("recurring_messages", [])
    for m in rec_list:
        if m.get("id") == msg_id:
            m["enabled"] = not m.get("enabled", True)
            if not m.get("chat_id") or (isinstance(m.get("chat_id"), int) and m.get("chat_id") > 0):
                m["chat_id"] = chat.id if chat.type in ("group", "supergroup") else cfg.get("main_group_id")
            save_config(cfg)
            await query.answer(f"Mensagem #{msg_id}: {'Ativada' if m['enabled'] else 'Desativada'}")
            break
    if page is not None:
        text, markup = generate_recurring_list(title, cfg, page=page)
    else:
        text, markup = generate_recurring_detail(cfg, msg_id, page=1)
    await query.edit_message_text(text, reply_markup=markup, parse_mode=ParseMode.MARKDOWN)
    return


async def on_cfg_rec_del(self, update, context, cfg, title):
    query = update.callback_query
    chat = update.effective_chat
    user = update.effective_user
    data = query.data
    parts = data.split(":")
    msg_id = int(parts[3])
    page = int(parts[4]) if len(parts) > 4 and parts[4].isdigit() else 1
    rec_list = cfg.get("recurring_messages", [])
    cfg["recurring_messages"] = [m for m in rec_list if m.get("id") != msg_id]
    save_config(cfg)
    await query.answer(f"Mensagem #{msg_id} apagada!")
    text, markup = generate_recurring_list(title, cfg, page=page)
    await query.edit_message_text(text, reply_markup=markup, parse_mode=ParseMode.MARKDOWN)
    return


async def on_cfg_rec_clone(self, update, context, cfg, title):
    query = update.callback_query
    chat = update.effective_chat
    user = update.effective_user
    data = query.data
    parts = data.split(":")
    msg_id = int(parts[3])
    page = int(parts[4]) if len(parts) > 4 and parts[4].isdigit() else 1
    rec_list = cfg.setdefault("recurring_messages", [])
    orig_item = next((m for m in rec_list if m.get("id") == msg_id), None)
    if not orig_item:
        await query.answer("Mensagem não encontrada!", show_alert=True)
        return
    new_item = copy.deepcopy(orig_item)
    new_id = (max([m.get("id", 0) for m in rec_list] or [0])) + 1
    new_item["id"] = new_id
    orig_title = get_recurring_title(orig_item)
    new_item["title"] = f"{orig_title} (Cópia)"
    new_item["enabled"] = False  # Começa pausada para o admin escolher canal e horário
    new_item["last_message_id"] = None
    new_item["last_sent_timestamp"] = 0
    new_item["messages_counter_last"] = 0
    rec_list.append(new_item)
    save_config(cfg)
    await query.answer(f"📋 Mensagem duplicada com sucesso como #{new_id}!", show_alert=True)
    text, markup = generate_recurring_detail(cfg, new_id, page=page)
    await query.edit_message_text(text, reply_markup=markup, parse_mode=ParseMode.MARKDOWN)
    return


async def on_cfg_rec_preview(self, update, context, cfg, title):
    query = update.callback_query
    chat = update.effective_chat
    user = update.effective_user
    data = query.data
    msg_id = int(data.split(":")[-1])
    rec_list = cfg.get("recurring_messages", [])
    msg_item = next((m for m in rec_list if m.get("id") == msg_id), None)
    if not msg_item:
        await query.answer("Mensagem não encontrada!", show_alert=True)
        return
    await query.answer("Enviando prévia no chat...")
    await chat.send_message("👁️ *Prévia da Mensagem Programada:*", parse_mode=ParseMode.MARKDOWN)
    try:
        await send_single_recurring_message(context.bot, msg_item, chat.id, job_queue=context.job_queue)
    except Exception as e_prev:
        await chat.send_message(f"❌ Não foi possível exibir a prévia: {e_prev}")
    return


async def on_cfg_rec_title(self, update, context, cfg, title):
    query = update.callback_query
    chat = update.effective_chat
    user = update.effective_user
    data = query.data
    msg_id = int(data.split(":")[-1])
    self.pending_inputs[user.id] = {"action": "rec_title", "msg_id": msg_id, "chat_id": chat.id}
    await query.answer()
    prompt = (
        f"🏷️ *Definir Nome/Identificador para a Mensagem #{msg_id}:*\n\n"
        "Envie agora o nome que deseja dar a esta mensagem para identificá-la facilmente na lista "
        "(ex: `Aviso Canais VIP`, `Lembrete Semanal`, `Promoção Sibelius`):\n\n"
        "_(Ou envie 'limpar' para restaurar o nome padrão, ou /cancelar)_"
    )
    await chat.send_message(prompt, parse_mode=ParseMode.MARKDOWN)
    return


async def on_cfg_rec_pin(self, update, context, cfg, title):
    query = update.callback_query
    chat = update.effective_chat
    user = update.effective_user
    data = query.data
    msg_id = int(data.split(":")[-1])
    rec_list = cfg.get("recurring_messages", [])
    for m in rec_list:
        if m.get("id") == msg_id:
            m["pin_message"] = not m.get("pin_message", False)
            save_config(cfg)
            await query.answer(f"Fixar mensagem: {'Sim' if m['pin_message'] else 'Não'}")
            break
    text, markup = generate_recurring_detail(cfg, msg_id)
    await query.edit_message_text(text, reply_markup=markup, parse_mode=ParseMode.MARKDOWN)
    return


async def on_cfg_rec_delprev(self, update, context, cfg, title):
    query = update.callback_query
    chat = update.effective_chat
    user = update.effective_user
    data = query.data
    msg_id = int(data.split(":")[-1])
    rec_list = cfg.get("recurring_messages", [])
    for m in rec_list:
        if m.get("id") == msg_id:
            m["delete_previous"] = not m.get("delete_previous", False)
            save_config(cfg)
            await query.answer(f"Deletar anterior: {'Sim' if m['delete_previous'] else 'Não'}")
            break
    text, markup = generate_recurring_detail(cfg, msg_id)
    await query.edit_message_text(text, reply_markup=markup, parse_mode=ParseMode.MARKDOWN)
    return


async def on_cfg_rec_hour_menu(self, update, context, cfg, title):
    query = update.callback_query
    chat = update.effective_chat
    user = update.effective_user
    data = query.data
    msg_id = int(data.split(":")[-1])
    await query.answer()
    text, markup = generate_recurring_hour_menu(msg_id)
    await query.edit_message_text(text, reply_markup=markup, parse_mode=ParseMode.MARKDOWN)
    return


async def on_cfg_rec_set_h(self, update, context, cfg, title):
    query = update.callback_query
    chat = update.effective_chat
    user = update.effective_user
    data = query.data
    parts = data.split(":")
    msg_id = int(parts[3])
    hour = int(parts[4])
    await query.answer()
    text, markup = generate_recurring_minute_menu(msg_id, hour)
    await query.edit_message_text(text, reply_markup=markup, parse_mode=ParseMode.MARKDOWN)
    return


async def on_cfg_rec_set_m(self, update, context, cfg, title):
    query = update.callback_query
    chat = update.effective_chat
    user = update.effective_user
    data = query.data
    parts = data.split(":")
    msg_id = int(parts[3])
    hour = int(parts[4])
    minute = int(parts[5])
    rec_list = cfg.get("recurring_messages", [])
    for m in rec_list:
        if m.get("id") == msg_id:
            m["start_hour"] = hour
            m["start_minute"] = minute
            m["last_fired_slot"] = None
            m["last_sent_timestamp"] = 0
            break
    save_config(cfg)
    await query.answer(f"Horário de início definido para {hour:02d}:{minute:02d}!")
    text, markup = generate_recurring_detail(cfg, msg_id)
    await query.edit_message_text(text, reply_markup=markup, parse_mode=ParseMode.MARKDOWN)
    return


async def on_cfg_rec_rep_menu(self, update, context, cfg, title):
    query = update.callback_query
    chat = update.effective_chat
    user = update.effective_user
    data = query.data
    msg_id = int(data.split(":")[-1])
    await query.answer()
    text, markup = generate_recurring_rep_menu(cfg, msg_id)
    await query.edit_message_text(text, reply_markup=markup, parse_mode=ParseMode.MARKDOWN)
    return


async def on_cfg_rec_set_inth(self, update, context, cfg, title):
    query = update.callback_query
    chat = update.effective_chat
    user = update.effective_user
    data = query.data
    parts = data.split(":")
    msg_id = int(parts[3])
    h = int(parts[4])
    rec_list = cfg.get("recurring_messages", [])
    for m in rec_list:
        if m.get("id") == msg_id:
            m["repeat_mode"] = "interval"
            m["interval_type"] = "hours"
            m["interval_value"] = h
            m["interval_minutes"] = h * 60
            break
    save_config(cfg)
    await query.answer(f"Repetição: A cada {h} hora{'s' if h > 1 else ''}!")
    text, markup = generate_recurring_rep_menu(cfg, msg_id)
    await query.edit_message_text(text, reply_markup=markup, parse_mode=ParseMode.MARKDOWN)
    return


async def on_cfg_rec_set_intm(self, update, context, cfg, title):
    query = update.callback_query
    chat = update.effective_chat
    user = update.effective_user
    data = query.data
    parts = data.split(":")
    msg_id = int(parts[3])
    m_val = int(parts[4])
    rec_list = cfg.get("recurring_messages", [])
    for m in rec_list:
        if m.get("id") == msg_id:
            m["repeat_mode"] = "interval"
            m["interval_type"] = "minutes"
            m["interval_value"] = m_val
            m["interval_minutes"] = m_val
            break
    save_config(cfg)
    await query.answer(f"Repetição: A cada {m_val} minuto{'s' if m_val > 1 else ''}!")
    text, markup = generate_recurring_rep_menu(cfg, msg_id)
    await query.edit_message_text(text, reply_markup=markup, parse_mode=ParseMode.MARKDOWN)
    return


async def on_cfg_rec_msg_menu(self, update, context, cfg, title):
    query = update.callback_query
    chat = update.effective_chat
    user = update.effective_user
    data = query.data
    msg_id = int(data.split(":")[-1])
    await query.answer()
    text, markup = generate_recurring_msg_menu(cfg, msg_id)
    await query.edit_message_text(text, reply_markup=markup, parse_mode=ParseMode.MARKDOWN)
    return


async def on_cfg_rec_set_mcnt(self, update, context, cfg, title):
    query = update.callback_query
    chat = update.effective_chat
    user = update.effective_user
    data = query.data
    parts = data.split(":")
    msg_id = int(parts[3])
    cnt = int(parts[4])
    rec_list = cfg.get("recurring_messages", [])
    for m in rec_list:
        if m.get("id") == msg_id:
            m["repeat_mode"] = "messages"
            m["messages_interval"] = cnt
            break
    save_config(cfg)
    await query.answer(f"Repetição: A cada {cnt} mensagens!")
    text, markup = generate_recurring_msg_menu(cfg, msg_id)
    await query.edit_message_text(text, reply_markup=markup, parse_mode=ParseMode.MARKDOWN)
    return


async def on_cfg_rec_in_mcnt(self, update, context, cfg, title):
    query = update.callback_query
    chat = update.effective_chat
    user = update.effective_user
    data = query.data
    msg_id = int(data.split(":")[-1])
    self.pending_inputs[user.id] = {"action": "rec_msg_cnt", "msg_id": msg_id, "chat_id": chat.id}
    await query.answer()
    prompt = (
        f"💬 *Digite a quantidade de mensagens no grupo para acionar a Mensagem #{msg_id}:*\n\n"
        "Exemplo: `50` para postar a cada 50 mensagens enviadas no grupo.\n"
        "_Envie o número agora (ou digite /cancelar para desistir):_"
    )
    await chat.send_message(prompt, parse_mode=ParseMode.MARKDOWN)
    return


async def on_cfg_rec_wday_menu(self, update, context, cfg, title):
    query = update.callback_query
    chat = update.effective_chat
    user = update.effective_user
    data = query.data
    msg_id = int(data.split(":")[-1])
    await query.answer()
    text, markup = generate_recurring_wday_menu(cfg, msg_id)
    await query.edit_message_text(text, reply_markup=markup, parse_mode=ParseMode.MARKDOWN)
    return


async def on_cfg_rec_tog_wday(self, update, context, cfg, title):
    query = update.callback_query
    chat = update.effective_chat
    user = update.effective_user
    data = query.data
    parts = data.split(":")
    msg_id = int(parts[3])
    idx = int(parts[4])
    rec_list = cfg.get("recurring_messages", [])
    for m in rec_list:
        if m.get("id") == msg_id:
            wd = m.setdefault("weekdays", [0, 1, 2, 3, 4, 5, 6])
            if idx in wd:
                wd.remove(idx)
            else:
                wd.append(idx)
            wd.sort()
            break
    save_config(cfg)
    await query.answer()
    text, markup = generate_recurring_wday_menu(cfg, msg_id)
    await query.edit_message_text(text, reply_markup=markup, parse_mode=ParseMode.MARKDOWN)
    return


async def on_cfg_rec_wday_p(self, update, context, cfg, title):
    query = update.callback_query
    chat = update.effective_chat
    user = update.effective_user
    data = query.data
    parts = data.split(":")
    msg_id = int(parts[3])
    preset = parts[4]
    rec_list = cfg.get("recurring_messages", [])
    for m in rec_list:
        if m.get("id") == msg_id:
            if preset == "all":
                m["weekdays"] = [0, 1, 2, 3, 4, 5, 6]
            elif preset == "work":
                m["weekdays"] = [0, 1, 2, 3, 4]
            elif preset == "weekend":
                m["weekdays"] = [5, 6]
            break
    save_config(cfg)
    await query.answer("Dias da semana atualizados!")
    text, markup = generate_recurring_wday_menu(cfg, msg_id)
    await query.edit_message_text(text, reply_markup=markup, parse_mode=ParseMode.MARKDOWN)
    return


async def on_cfg_rec_mday_menu(self, update, context, cfg, title):
    query = update.callback_query
    chat = update.effective_chat
    user = update.effective_user
    data = query.data
    msg_id = int(data.split(":")[-1])
    await query.answer()
    text, markup = generate_recurring_mday_menu(cfg, msg_id)
    await query.edit_message_text(text, reply_markup=markup, parse_mode=ParseMode.MARKDOWN)
    return


async def on_cfg_rec_tog_mday(self, update, context, cfg, title):
    query = update.callback_query
    chat = update.effective_chat
    user = update.effective_user
    data = query.data
    parts = data.split(":")
    msg_id = int(parts[3])
    d = int(parts[4])
    rec_list = cfg.get("recurring_messages", [])
    for m in rec_list:
        if m.get("id") == msg_id:
            md = m.get("month_days")
            if md is None or len(md) >= 31 or not md:
                md = list(range(1, 32))
            if d in md:
                md.remove(d)
            else:
                md.append(d)
            md.sort()
            m["month_days"] = md
            break
    save_config(cfg)
    await query.answer()
    text, markup = generate_recurring_mday_menu(cfg, msg_id)
    await query.edit_message_text(text, reply_markup=markup, parse_mode=ParseMode.MARKDOWN)
    return


async def on_cfg_rec_mday_p(self, update, context, cfg, title):
    query = update.callback_query
    chat = update.effective_chat
    user = update.effective_user
    data = query.data
    parts = data.split(":")
    msg_id = int(parts[3])
    preset = parts[4]
    rec_list = cfg.get("recurring_messages", [])
    for m in rec_list:
        if m.get("id") == msg_id:
            if preset == "all":
                m["month_days"] = []
            elif preset == "1_15":
                m["month_days"] = [1, 15]
            elif preset == "1":
                m["month_days"] = [1]
            break
    save_config(cfg)
    await query.answer("Dias do mês atualizados!")
    text, markup = generate_recurring_mday_menu(cfg, msg_id)
    await query.edit_message_text(text, reply_markup=markup, parse_mode=ParseMode.MARKDOWN)
    return


async def on_cfg_rec_autodel_menu(self, update, context, cfg, title):
    query = update.callback_query
    chat = update.effective_chat
    user = update.effective_user
    data = query.data
    msg_id = int(data.split(":")[-1])
    await query.answer()
    text, markup = generate_recurring_autodel_menu(cfg, msg_id)
    await query.edit_message_text(text, reply_markup=markup, parse_mode=ParseMode.MARKDOWN)
    return


async def on_cfg_rec_set_adel(self, update, context, cfg, title):
    query = update.callback_query
    chat = update.effective_chat
    user = update.effective_user
    data = query.data
    parts = data.split(":")
    msg_id = int(parts[3])
    sec = int(parts[4])
    rec_list = cfg.get("recurring_messages", [])
    for m in rec_list:
        if m.get("id") == msg_id:
            m["auto_delete_seconds"] = sec
            break
    save_config(cfg)
    lbl = format_autodel_display(sec) if sec > 0 else "Desativado"
    await query.answer(f"Exclusão cronometrada: {lbl}")
    text, markup = generate_recurring_autodel_menu(cfg, msg_id)
    await query.edit_message_text(text, reply_markup=markup, parse_mode=ParseMode.MARKDOWN)
    return


async def on_cfg_rec_edit(self, update, context, cfg, title):
    query = update.callback_query
    chat = update.effective_chat
    user = update.effective_user
    data = query.data
    parts = data.split(":")
    msg_id = int(parts[3])
    page = int(parts[4]) if len(parts) > 4 and parts[4].isdigit() else 1
    await query.answer()
    text, markup = generate_recurring_edit_menu(cfg, msg_id, page=page)
    await query.edit_message_text(text, reply_markup=markup, parse_mode=ParseMode.MARKDOWN)
    return


async def on_cfg_rec_dstart(self, update, context, cfg, title):
    query = update.callback_query
    chat = update.effective_chat
    user = update.effective_user
    data = query.data
    msg_id = int(data.split(":")[-1])
    await query.answer()
    text, markup = generate_recurring_date_menu(cfg, msg_id, is_start=True)
    await query.edit_message_text(text, reply_markup=markup, parse_mode=ParseMode.MARKDOWN)
    return


async def on_cfg_rec_dend(self, update, context, cfg, title):
    query = update.callback_query
    chat = update.effective_chat
    user = update.effective_user
    data = query.data
    msg_id = int(data.split(":")[-1])
    await query.answer()
    text, markup = generate_recurring_date_menu(cfg, msg_id, is_start=False)
    await query.edit_message_text(text, reply_markup=markup, parse_mode=ParseMode.MARKDOWN)
    return


async def on_cfg_rec_dstart_today(self, update, context, cfg, title):
    query = update.callback_query
    chat = update.effective_chat
    user = update.effective_user
    data = query.data
    msg_id = int(data.split(":")[-1])
    today_str = datetime.now().strftime("%Y-%m-%d")
    for m in cfg.get("recurring_messages", []):
        if m.get("id") == msg_id:
            m["start_date"] = today_str
            break
    save_config(cfg)
    await query.answer(f"Data de início: {today_str}")
    text, markup = generate_recurring_date_menu(cfg, msg_id, is_start=True)
    await query.edit_message_text(text, reply_markup=markup, parse_mode=ParseMode.MARKDOWN)
    return


async def on_cfg_rec_dend_today(self, update, context, cfg, title):
    query = update.callback_query
    chat = update.effective_chat
    user = update.effective_user
    data = query.data
    msg_id = int(data.split(":")[-1])
    today_str = datetime.now().strftime("%Y-%m-%d")
    for m in cfg.get("recurring_messages", []):
        if m.get("id") == msg_id:
            m["end_date"] = today_str
            break
    save_config(cfg)
    await query.answer(f"Data final: {today_str}")
    text, markup = generate_recurring_date_menu(cfg, msg_id, is_start=False)
    await query.edit_message_text(text, reply_markup=markup, parse_mode=ParseMode.MARKDOWN)
    return


async def on_cfg_rec_dstart_clear(self, update, context, cfg, title):
    query = update.callback_query
    chat = update.effective_chat
    user = update.effective_user
    data = query.data
    msg_id = int(data.split(":")[-1])
    for m in cfg.get("recurring_messages", []):
        if m.get("id") == msg_id:
            m["start_date"] = None
            break
    save_config(cfg)
    await query.answer("Data de início limpa!")
    text, markup = generate_recurring_date_menu(cfg, msg_id, is_start=True)
    await query.edit_message_text(text, reply_markup=markup, parse_mode=ParseMode.MARKDOWN)
    return


async def on_cfg_rec_dend_clear(self, update, context, cfg, title):
    query = update.callback_query
    chat = update.effective_chat
    user = update.effective_user
    data = query.data
    msg_id = int(data.split(":")[-1])
    for m in cfg.get("recurring_messages", []):
        if m.get("id") == msg_id:
            m["end_date"] = None
            break
    save_config(cfg)
    await query.answer("Data final limpa!")
    text, markup = generate_recurring_date_menu(cfg, msg_id, is_start=False)
    await query.edit_message_text(text, reply_markup=markup, parse_mode=ParseMode.MARKDOWN)
    return


async def on_cfg_rec_dstart_input(self, update, context, cfg, title):
    query = update.callback_query
    chat = update.effective_chat
    user = update.effective_user
    data = query.data
    msg_id = int(data.split(":")[-1])
    self.pending_inputs[user.id] = {"action": "rec_dstart", "msg_id": msg_id, "chat_id": chat.id}
    await query.answer()
    prompt = (
        f"📅 *Digite a Data de Início para a Mensagem #{msg_id}:*\n\n"
        "Formato: `DD/MM/AAAA` (Ex: `15/10/2026`)\n"
        "_Envie a data agora (ou digite /cancelar para desistir):_"
    )
    await chat.send_message(prompt, parse_mode=ParseMode.MARKDOWN)
    return


async def on_cfg_rec_dend_input(self, update, context, cfg, title):
    query = update.callback_query
    chat = update.effective_chat
    user = update.effective_user
    data = query.data
    msg_id = int(data.split(":")[-1])
    self.pending_inputs[user.id] = {"action": "rec_dend", "msg_id": msg_id, "chat_id": chat.id}
    await query.answer()
    prompt = (
        f"📅 *Digite a Data Final para a Mensagem #{msg_id}:*\n\n"
        "Formato: `DD/MM/AAAA` (Ex: `31/12/2026`)\n"
        "_Envie a data agora (ou digite /cancelar para desistir):_"
    )
    await chat.send_message(prompt, parse_mode=ParseMode.MARKDOWN)
    return


async def on_cfg_rec_test(self, update, context, cfg, title):
    query = update.callback_query
    chat = update.effective_chat
    user = update.effective_user
    data = query.data
    msg_id = int(data.split(":")[-1])
    rec_list = cfg.get("recurring_messages", [])
    msg_item = next((m for m in rec_list if m.get("id") == msg_id), None)
    if msg_item:
        target_chat_id = msg_item.get("chat_id")
        main_group_id = cfg.get("main_group_id")
        if (not target_chat_id or (isinstance(target_chat_id, int) and target_chat_id > 0)) and main_group_id:
            target_chat_id = main_group_id
        elif not target_chat_id:
            target_chat_id = chat.id

        try:
            await query.answer("Disparando teste...")

            # 1. Envia uma cópia de teste AQUI MESMO no chat privado para o admin ver o resultado!
            await chat.send_message("👁️ *Prévia da Mensagem (Como será exibida):*", parse_mode=ParseMode.MARKDOWN)
            await send_single_recurring_message(context.bot, msg_item, chat.id, job_queue=context.job_queue)

            # 2. Se houver grupo vinculado (diferente do chat privado), envia para o grupo também!
            if target_chat_id and target_chat_id != chat.id:
                await send_single_recurring_message(context.bot, msg_item, target_chat_id, job_queue=context.job_queue)
                await chat.send_message(f"✅ Mensagem de teste #{msg_id} enviada com sucesso para o grupo vinculado!")
            else:
                await chat.send_message(f"✅ Teste concluído com sucesso!")
        except Exception as e:
            await chat.send_message(f"❌ Erro ao enviar mensagem de teste #{msg_id}: {e}")
    return


async def on_cfg_quick_save_rec(self, update, context, cfg, title):
    query = update.callback_query
    chat = update.effective_chat
    user = update.effective_user
    data = query.data
    msg_id = int(data.split(":")[-1])
    captured = self.last_received_private_messages.get(user.id)
    if not captured:
        await query.answer("Nenhuma mensagem recente encontrada.", show_alert=True)
        return

    rec_list = cfg.setdefault("recurring_messages", [])
    target_item = next((m for m in rec_list if m.get("id") == msg_id), None)
    if not target_item:
        target_item = {
            "id": msg_id,
            "enabled": True,
            "text": captured.get("text") or "📢 Postagem Programada",
            "photo": captured.get("photo"),
            "buttons": captured.get("buttons") or [],
            "repeat_mode": "interval",
            "interval_type": "hours",
            "interval_value": 24,
            "interval_minutes": 1440,
            "messages_interval": 50,
            "messages_counter_last": 0,
            "start_hour": None,
            "start_minute": None,
            "weekdays": [0, 1, 2, 3, 4, 5, 6],
            "month_days": [],
            "start_date": None,
            "end_date": None,
            "pin_message": False,
            "delete_previous": False,
            "auto_delete_seconds": 0,
            "last_message_id": None,
            "last_sent_timestamp": 0,
            "chat_id": cfg.get("main_group_id")
        }
        rec_list.append(target_item)
    else:
        if captured.get("text") and captured.get("text") != "📢 Postagem da Comunidade":
            target_item["text"] = captured["text"]
        if captured.get("photo"):
            target_item["photo"] = captured["photo"]
        if captured.get("buttons"):
            target_item["buttons"] = captured["buttons"]
            target_item.pop("source_chat_id", None)
            target_item.pop("source_message_id", None)
            target_item.pop("backup_chat_id", None)
            target_item.pop("backup_message_id", None)
        elif captured.get("source_chat_id") and captured.get("source_message_id") and captured.get("source_chat_id") < 0:
            target_item["source_chat_id"] = captured["source_chat_id"]
            target_item["source_message_id"] = captured["source_message_id"]
            target_item["backup_chat_id"] = captured.get("backup_chat_id")
            target_item["backup_message_id"] = captured.get("backup_message_id")

    save_config(cfg)
    await query.answer(f"Mensagem #{msg_id} salva com sucesso!")
    markup = InlineKeyboardMarkup([
        [InlineKeyboardButton("⚙️ Voltar à Mensagem", callback_data=f"cfg:rec:detail:{msg_id}")],
        [InlineKeyboardButton("🚀 Testar Envio Agora", callback_data=f"cfg:rec:test:{msg_id}")],
        [InlineKeyboardButton("📋 Lista de Mensagens", callback_data="cfg:rec:list")]
    ])
    try:
        await query.edit_message_text(
            f"✅ *Mensagem Programada #{msg_id} configurada e pronta para envio!*\n\n"
            "O texto, artigo expansível, mídias e botões foram vinculados com perfeição.",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=markup
        )
    except Exception:
        await query.edit_message_text(
            f"✅ Mensagem Programada #{msg_id} configurada e pronta para envio!",
            reply_markup=markup
        )
    return


async def on_cfg_rec_target_help(self, update, context, cfg, title):
    query = update.callback_query
    chat = update.effective_chat
    user = update.effective_user
    data = query.data
    msg_id = int(data.split(":")[-1])
    rec_list = cfg.get("recurring_messages", [])
    msg_item = next((m for m in rec_list if m.get("id") == msg_id), None)
    target_chat_id = msg_item.get("chat_id") if msg_item else None
    topic_id = msg_item.get("message_thread_id") if msg_item else None

    groups = cfg.get("linked_groups", [])
    channels = cfg.get("linked_channels", [])

    help_text = (
        f"🎯 *Destino da Mensagem Recorrente #{msg_id}*\n\n"
        f"Selecione abaixo em qual grupo ou canal você deseja que esta postagem programada seja enviada automaticamente:\n\n"
        f"• *Destino atual:* `{target_chat_id or 'Grupo Principal'}`\n"
        f"• *Tópico do fórum:* `{topic_id or 'Geral'}`"
    )

    kb = []
    kb.append([
        InlineKeyboardButton("🌐 Todos (Grupos + Canais)", callback_data=f"cfg:rec:set_target:{msg_id}:all"),
    ])
    if groups and channels:
        kb.append([
            InlineKeyboardButton("👥 Todos os Grupos", callback_data=f"cfg:rec:set_target:{msg_id}:all_groups"),
            InlineKeyboardButton("📢 Todos os Canais", callback_data=f"cfg:rec:set_target:{msg_id}:all_channels")
        ])

    for g in groups:
        gid = g.get("id")
        gtit = g.get("title", f"Grupo {gid}")
        sel = " ✅" if target_chat_id == gid else ""
        kb.append([InlineKeyboardButton(f"👥 {gtit}{sel}", callback_data=f"cfg:rec:set_target:{msg_id}:{gid}")])

    for c in channels:
        cid = c.get("id")
        ctit = c.get("title", f"Canal {cid}")
        sel = " ✅" if target_chat_id == cid else ""
        kb.append([InlineKeyboardButton(f"📢 {ctit}{sel}", callback_data=f"cfg:rec:set_target:{msg_id}:{cid}")])

    kb.append([InlineKeyboardButton("🔙 Voltar", callback_data=f"cfg:rec:detail:{msg_id}")])
    await query.edit_message_text(help_text, reply_markup=InlineKeyboardMarkup(kb), parse_mode=ParseMode.MARKDOWN)
    await query.answer()
    return


async def on_cfg_rec_set_target(self, update, context, cfg, title):
    query = update.callback_query
    chat = update.effective_chat
    user = update.effective_user
    data = query.data
    parts = data.split(":")
    msg_id = int(parts[3])
    target_val = parts[4]
    if target_val.startswith("-") or target_val.isdigit():
        target_val = int(target_val)
    rec_list = cfg.setdefault("recurring_messages", [])
    for m in rec_list:
        if m.get("id") == msg_id:
            m["chat_id"] = target_val
            save_config(cfg)
            break
    await query.answer("🎯 Destino atualizado com sucesso!")
    text, markup = generate_recurring_detail(cfg, msg_id)
    await query.edit_message_text(text, reply_markup=markup, parse_mode=ParseMode.MARKDOWN)
    return


async def on_cfg_rec_text(self, update, context, cfg, title):
    query = update.callback_query
    chat = update.effective_chat
    user = update.effective_user
    data = query.data
    msg_id = int(data.split(":")[-1])
    self.pending_inputs[user.id] = {"action": "rec_text", "msg_id": msg_id, "chat_id": chat.id}
    await query.answer()
    prompt = (
        f"✏️ *Digite o texto da Mensagem Programada #{msg_id}:*\n\n"
        "_Envie sua mensagem agora (ou digite /cancelar para desistir):_"
    )
    await chat.send_message(prompt, parse_mode=ParseMode.MARKDOWN)
    return


async def on_cfg_rec_photo(self, update, context, cfg, title):
    query = update.callback_query
    chat = update.effective_chat
    user = update.effective_user
    data = query.data
    msg_id = int(data.split(":")[-1])
    self.pending_inputs[user.id] = {"action": "rec_photo", "msg_id": msg_id, "chat_id": chat.id}
    await query.answer()
    prompt = (
        f"🖼️ *Envie a foto ou imagem para a Mensagem Programada #{msg_id}:*\n\n"
        "_Envie a foto pelo chat agora (ou digite /cancelar para desistir):_"
    )
    await chat.send_message(prompt, parse_mode=ParseMode.MARKDOWN)
    return


async def on_cfg_rec_delphoto(self, update, context, cfg, title):
    query = update.callback_query
    chat = update.effective_chat
    user = update.effective_user
    data = query.data
    parts = data.split(":")
    msg_id = int(parts[3])
    page = int(parts[4]) if len(parts) > 4 and parts[4].isdigit() else 1
    rec_list = cfg.get("recurring_messages", [])
    for m in rec_list:
        if m.get("id") == msg_id:
            m["photo"] = None
            save_config(cfg)
            await query.answer("Foto removida!")
            break
    text, markup = generate_recurring_edit_menu(cfg, msg_id, page=page)
    await query.edit_message_text(text, reply_markup=markup, parse_mode=ParseMode.MARKDOWN)
    return


async def on_cfg_rec_buttons(self, update, context, cfg, title):
    query = update.callback_query
    chat = update.effective_chat
    user = update.effective_user
    data = query.data
    msg_id = int(data.split(":")[-1])
    self.pending_inputs[user.id] = {"action": "rec_buttons", "msg_id": msg_id, "chat_id": chat.id}
    await query.answer()
    prompt = (
        f"🔘 *Configure os Botões para a Mensagem Programada #{msg_id}:*\n\n"
        "💡 *Suporta Múltiplas Colunas (Lado a Lado):*\n"
        "• *Na mesma linha (Colunas):*\n"
        "`[Botão 1 - https://link1.com] [Botão 2 - https://link2.com]`\n"
        "`[Banda Sinfônica - link] [Bases Cifradas - link] [Big & Band - link]`\n\n"
        "• *Ou com && na mesma linha:*\n"
        "`Botão 1 | link1 && Botão 2 | link2`\n\n"
        "• *Um embaixo do outro:*\n"
        "`Botão 1 | https://link1.com`\n"
        "`Botão 2 | https://link2.com`\n\n"
        "_(Envie a lista agora, ou digite 'remover' para limpar todos, ou /cancelar)_"
    )
    await chat.send_message(prompt, parse_mode=ParseMode.MARKDOWN)
    return


async def on_cfg_rec_article(self, update, context, cfg, title):
    query = update.callback_query
    chat = update.effective_chat
    user = update.effective_user
    data = query.data
    msg_id = int(data.split(":")[-1])
    self.pending_inputs[user.id] = {"action": "rec_article", "msg_id": msg_id, "chat_id": chat.id}
    await query.answer()
    prompt = (
        f"📄 *Definir Artigo / Instant View para a Mensagem #{msg_id}:*\n\n"
        "Envie o link do artigo (ex: Telegraph ou página web):\n"
        "`https://telegra.ph/Principais-Canais-e-Grupos...`\n\n"
        "O bot exibirá a prévia do artigo no topo da mensagem programada!\n\n"
        "_(Envie o link agora, ou 'remover' para limpar, ou /cancelar)_"
    )
    await chat.send_message(prompt, parse_mode=ParseMode.MARKDOWN)
    return


async def on_cfg_rec_delbuttons(self, update, context, cfg, title):
    query = update.callback_query
    chat = update.effective_chat
    user = update.effective_user
    data = query.data
    parts = data.split(":")
    msg_id = int(parts[3])
    page = int(parts[4]) if len(parts) > 4 and parts[4].isdigit() else 1
    rec_list = cfg.get("recurring_messages", [])
    for m in rec_list:
        if m.get("id") == msg_id:
            m["buttons"] = []
            save_config(cfg)
            await query.answer("Botões removidos!")
            break
    text, markup = generate_recurring_edit_menu(cfg, msg_id, page=page)
    await query.edit_message_text(text, reply_markup=markup, parse_mode=ParseMode.MARKDOWN)
    return
