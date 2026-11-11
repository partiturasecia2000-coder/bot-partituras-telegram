from modules.panel_support import *


async def on_rec_text(self, update, context, cfg, state, action):
    user = update.effective_user
    msg = update.effective_message
    msg_id = state.get("msg_id", 1)
    raw_text, photo_id, extracted_buttons, src_chat_id, src_msg_id, bak_chat_id, bak_msg_id = await self._extract_message_content(msg, context, user.id)

    rec_list = cfg.setdefault("recurring_messages", [])
    target_item = next((m for m in rec_list if m.get("id") == msg_id), None)
    if not target_item:
        target_item = {
            "id": msg_id,
            "enabled": True,
            "text": "📢 Postagem Programada",
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
            "chat_id": cfg.get("main_group_id")
        }
        rec_list.append(target_item)

    if raw_text:
        target_item["text"] = raw_text
    if photo_id:
        target_item["photo"] = photo_id
    if extracted_buttons:
        target_item["buttons"] = extracted_buttons
    if src_chat_id and src_msg_id and src_chat_id < 0:
        target_item["source_chat_id"] = src_chat_id
        target_item["source_message_id"] = src_msg_id
        target_item["backup_chat_id"] = bak_chat_id
        target_item["backup_message_id"] = bak_msg_id
    else:
        target_item.pop("source_chat_id", None)
        target_item.pop("source_message_id", None)
        target_item.pop("backup_chat_id", None)
        target_item.pop("backup_message_id", None)

    save_config(cfg)
    del self.pending_inputs[user.id]

    # Envia prévia visual da mensagem no chat privado
    try:
        await msg.reply_text("👁️ *Veja abaixo a prévia de como sua mensagem ficou:*", parse_mode=ParseMode.MARKDOWN)
        await send_single_recurring_message(context.bot, target_item, msg.chat.id, job_queue=context.job_queue)
    except Exception as e_pv:
        logger.warning(f"Erro ao exibir prévia no rec_text: {e_pv}")

    summary_items = ["• *Texto:* Salvo com sucesso"]
    if photo_id:
        summary_items.append("• *Foto:* Imagem salva")
    if extracted_buttons:
        total_btns = sum(len(r) for r in extracted_buttons)
        summary_items.append(f"• *Botões:* {total_btns} botão(ões) capturados")

    summary_str = "\n".join(summary_items)

    btns_exist = bool(target_item.get("buttons"))
    btn_action_label = "🔘 Alterar Botões com Links" if btns_exist else "🔘 Adicionar Botões com Links"
    photo_exist = bool(target_item.get("photo"))
    photo_action_label = "🖼️ Alterar Foto" if photo_exist else "🖼️ Adicionar Foto / Banner"

    markup = InlineKeyboardMarkup([
        [InlineKeyboardButton(btn_action_label, callback_data=f"cfg:rec:buttons:{msg_id}")],
        [
            InlineKeyboardButton(photo_action_label, callback_data=f"cfg:rec:photo:{msg_id}"),
            InlineKeyboardButton("🎯 Canal de Destino", callback_data=f"cfg:rec:target_help:{msg_id}")
        ],
        [
            InlineKeyboardButton("⏰ Horário de Envio", callback_data=f"cfg:rec:hour_menu:{msg_id}"),
            InlineKeyboardButton("👀 Ver Prévia", callback_data=f"cfg:rec:preview:{msg_id}")
        ],
        [
            InlineKeyboardButton("⚙️ Menu Completo", callback_data=f"cfg:rec:detail:{msg_id}"),
            InlineKeyboardButton("📋 Lista de Mensagens", callback_data="cfg:rec:list")
        ]
    ])
    confirm_msg = (
        f"✅ *Texto da Mensagem #{msg_id} salvo com sucesso!*\n\n{summary_str}\n\n"
        "👉 *Próximo passo:* Para adicionar botões com links (ex: canais/grupos), clique no botão abaixo:"
    )
    try:
        await msg.reply_text(
            confirm_msg,
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=markup
        )
    except Exception:
        await msg.reply_text(
            confirm_msg.replace("*", "").replace("•", "-"),
            reply_markup=markup
        )
    return True


async def on_rec_photo(self, update, context, cfg, state, action):
    user = update.effective_user
    msg = update.effective_message
    msg_id = state.get("msg_id", 1)
    if not msg.photo:
        await msg.reply_text("⚠️ Envie uma imagem válida ou digite /cancelar.")
        return True

    file_id = msg.photo[-1].file_id
    rec_list = cfg.setdefault("recurring_messages", [])
    target_item = next((m for m in rec_list if m.get("id") == msg_id), None)
    if not target_item:
        target_item = {
            "id": msg_id,
            "enabled": True,
            "text": "📢 Postagem Programada",
            "photo": file_id,
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
            "chat_id": cfg.get("main_group_id")
        }
        rec_list.append(target_item)
    else:
        target_item["photo"] = file_id

    target_item.pop("source_chat_id", None)
    target_item.pop("source_message_id", None)
    target_item.pop("backup_chat_id", None)
    target_item.pop("backup_message_id", None)

    save_config(cfg)
    del self.pending_inputs[user.id]

    try:
        await msg.reply_text("👁️ *Veja abaixo a prévia com a nova foto:*", parse_mode=ParseMode.MARKDOWN)
        await send_single_recurring_message(context.bot, target_item, msg.chat.id, job_queue=context.job_queue)
    except Exception as e_pv:
        logger.warning(f"Erro ao exibir prévia no rec_photo: {e_pv}")

    btns_exist = bool(target_item.get("buttons"))
    btn_action_label = "🔘 Alterar Botões" if btns_exist else "🔘 Adicionar Botões com Links"

    markup = InlineKeyboardMarkup([
        [InlineKeyboardButton(btn_action_label, callback_data=f"cfg:rec:buttons:{msg_id}")],
        [
            InlineKeyboardButton("🎯 Canal de Destino", callback_data=f"cfg:rec:target_help:{msg_id}"),
            InlineKeyboardButton("⏰ Horário de Envio", callback_data=f"cfg:rec:hour_menu:{msg_id}")
        ],
        [
            InlineKeyboardButton("✏️ Editar Texto", callback_data=f"cfg:rec:text:{msg_id}"),
            InlineKeyboardButton("👀 Ver Prévia", callback_data=f"cfg:rec:preview:{msg_id}")
        ],
        [
            InlineKeyboardButton("⚙️ Menu Completo", callback_data=f"cfg:rec:detail:{msg_id}"),
            InlineKeyboardButton("📋 Lista de Mensagens", callback_data="cfg:rec:list")
        ]
    ])
    try:
        await msg.reply_text(f"✅ *Foto da mensagem #{msg_id} atualizada com sucesso!*\n\n👉 Escolha o próximo passo abaixo:", parse_mode=ParseMode.MARKDOWN, reply_markup=markup)
    except Exception:
        await msg.reply_text(f"✅ Foto da mensagem #{msg_id} atualizada com sucesso!", reply_markup=markup)
    return True


async def on_rec_buttons(self, update, context, cfg, state, action):
    user = update.effective_user
    msg = update.effective_message
    msg_id = state.get("msg_id", 1)
    raw_text, photo_id, extracted_buttons, src_chat_id, src_msg_id, bak_chat_id, bak_msg_id = await self._extract_message_content(msg, context, user.id)

    rec_list = cfg.setdefault("recurring_messages", [])
    target_item = next((m for m in rec_list if m.get("id") == msg_id), None)
    if not target_item:
        target_item = {
            "id": msg_id,
            "enabled": True,
            "text": "📢 Postagem Programada",
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
            "chat_id": cfg.get("main_group_id")
        }
        rec_list.append(target_item)

    if raw_text and raw_text.strip().lower() in ("remover", "apagar", "nenhum"):
        target_item["buttons"] = []
        target_item.pop("source_chat_id", None)
        target_item.pop("source_message_id", None)
        target_item.pop("backup_chat_id", None)
        target_item.pop("backup_message_id", None)
        save_config(cfg)
        del self.pending_inputs[user.id]
        markup = InlineKeyboardMarkup([
            [InlineKeyboardButton("⚙️ Voltar à Mensagem", callback_data=f"cfg:rec:detail:{msg_id}")],
            [InlineKeyboardButton("📋 Lista de Mensagens", callback_data="cfg:rec:list")]
        ])
        await msg.reply_text(f"✅ *Botões da mensagem #{msg_id} removidos!*", parse_mode=ParseMode.MARKDOWN, reply_markup=markup)
        return True

    if extracted_buttons:
        target_item["buttons"] = extracted_buttons
        target_item.pop("source_chat_id", None)
        target_item.pop("source_message_id", None)
        target_item.pop("backup_chat_id", None)
        target_item.pop("backup_message_id", None)
    elif src_chat_id and src_msg_id and src_chat_id < 0:
        target_item["source_chat_id"] = src_chat_id
        target_item["source_message_id"] = src_msg_id
        target_item["backup_chat_id"] = bak_chat_id
        target_item["backup_message_id"] = bak_msg_id
    else:
        await msg.reply_text("⚠️ Nenhum botão detectado. Envie os botões no formato:\n`Texto do Botão | https://link.com`\n\nOu digite /cancelar.")
        return True

    save_config(cfg)
    del self.pending_inputs[user.id]

    # Envia prévia visual da mensagem no chat privado
    try:
        await msg.reply_text("👁️ *Veja abaixo como sua mensagem ficou com os botões:*", parse_mode=ParseMode.MARKDOWN)
        await send_single_recurring_message(context.bot, target_item, msg.chat.id, job_queue=context.job_queue)
    except Exception as e_pv:
        logger.warning(f"Erro ao exibir prévia no rec_buttons: {e_pv}")

    total_btns = sum(len(r) for r in extracted_buttons) if extracted_buttons else 0
    photo_exist = bool(target_item.get("photo"))
    photo_action_label = "🖼️ Alterar Foto" if photo_exist else "🖼️ Adicionar Foto / Banner"

    markup = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🎯 Canal de Destino", callback_data=f"cfg:rec:target_help:{msg_id}"),
            InlineKeyboardButton("⏰ Horário de Envio", callback_data=f"cfg:rec:hour_menu:{msg_id}")
        ],
        [
            InlineKeyboardButton(photo_action_label, callback_data=f"cfg:rec:photo:{msg_id}"),
            InlineKeyboardButton("✏️ Editar Texto", callback_data=f"cfg:rec:text:{msg_id}")
        ],
        [
            InlineKeyboardButton("📋 Duplicar para outro canal", callback_data=f"cfg:rec:clone:{msg_id}"),
            InlineKeyboardButton("👀 Ver Prévia", callback_data=f"cfg:rec:preview:{msg_id}")
        ],
        [
            InlineKeyboardButton("⚙️ Menu Completo", callback_data=f"cfg:rec:detail:{msg_id}"),
            InlineKeyboardButton("📋 Lista de Mensagens", callback_data="cfg:rec:list")
        ]
    ])
    reply_txt = f"✅ *{total_btns} botão(ões) em {len(extracted_buttons)} linha(s) configurados com sucesso na mensagem #{msg_id}!*"
    try:
        await msg.reply_text(reply_txt, parse_mode=ParseMode.MARKDOWN, reply_markup=markup)
    except Exception:
        await msg.reply_text(reply_txt.replace("*", ""), reply_markup=markup)
    return True


async def on_rec_title(self, update, context, cfg, state, action):
    user = update.effective_user
    msg = update.effective_message
    msg_id = state.get("msg_id", 1)
    val = (msg.text or "").strip()
    if not val:
        await msg.reply_text("⚠️ Envie um texto válido para o nome ou /cancelar.")
        return True
    rec_list = cfg.setdefault("recurring_messages", [])
    target_item = next((m for m in rec_list if m.get("id") == msg_id), None)
    if target_item:
        if val.lower() in ("limpar", "padrao", "padrão", "remover"):
            target_item.pop("title", None)
        else:
            target_item["title"] = val
        save_config(cfg)
    del self.pending_inputs[user.id]

    new_title = get_recurring_title(target_item) if target_item else val
    markup = InlineKeyboardMarkup([
        [InlineKeyboardButton("⚙️ Voltar à Mensagem", callback_data=f"cfg:rec:detail:{msg_id}")],
        [InlineKeyboardButton("📋 Lista de Mensagens", callback_data="cfg:rec:list")]
    ])
    await msg.reply_text(
        f"✅ *Nome da Mensagem #{msg_id} atualizado para:* `{new_title}`",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=markup
    )
    return True


async def on_rec_article(self, update, context, cfg, state, action):
    user = update.effective_user
    msg = update.effective_message
    msg_id = state.get("msg_id")
    if not msg.text:
        await msg.reply_text("⚠️ Envie um link válido ou digite /cancelar.")
        return True

    val = msg.text.strip()
    rec_list = cfg.get("recurring_messages", [])
    for item in rec_list:
        if item.get("id") == msg_id:
            if val.lower() in ("remover", "apagar", "nenhum", "off"):
                item["article_url"] = None
            else:
                if not (val.startswith("http://") or val.startswith("https://") or val.startswith("t.me/")):
                    val = "https://" + val
                item["article_url"] = val
            break
    save_config(cfg)
    del self.pending_inputs[user.id]

    markup = InlineKeyboardMarkup([
        [InlineKeyboardButton("⚙️ Voltar à Mensagem", callback_data=f"cfg:rec:detail:{msg_id}")],
        [InlineKeyboardButton("📋 Lista de Mensagens", callback_data="cfg:rec:list")]
    ])
    msg_txt = "✅ *Artigo removido com sucesso!*" if val.lower() in ("remover", "apagar", "nenhum", "off") else f"✅ *Artigo da Mensagem #{msg_id} salvo com sucesso!*\nLink: `{val}`\n\nA prévia do artigo será exibida no topo do envio!"
    await msg.reply_text(msg_txt, parse_mode=ParseMode.MARKDOWN, reply_markup=markup)
    return True


async def on_rec_msg_cnt(self, update, context, cfg, state, action):
    user = update.effective_user
    msg = update.effective_message
    msg_id = state.get("msg_id")
    if not msg.text or not msg.text.strip().isdigit():
        await msg.reply_text("⚠️ Por favor, digite um número inteiro de mensagens (ex: 50) ou /cancelar.")
        return True
    cnt = int(msg.text.strip())
    if cnt <= 0:
        await msg.reply_text("⚠️ O número de mensagens deve ser maior que 0.")
        return True
    rec_list = cfg.get("recurring_messages", [])
    for item in rec_list:
        if item.get("id") == msg_id:
            item["repeat_mode"] = "messages"
            item["messages_interval"] = cnt
            break
    save_config(cfg)
    del self.pending_inputs[user.id]
    text, markup = generate_recurring_msg_menu(cfg, msg_id)
    await msg.reply_text(f"✅ Repetição definida para a cada *{cnt} mensagens*!", parse_mode=ParseMode.MARKDOWN, reply_markup=markup)
    return True


async def on_rec_dstart(self, update, context, cfg, state, action):
    user = update.effective_user
    msg = update.effective_message
    msg_id = state.get("msg_id")
    field = "start_date" if action == "rec_dstart" else "end_date"
    raw = msg.text.strip()
    date_val = None
    try:
        if "/" in raw:
            parts = raw.split("/")
            if len(parts) == 3:
                d, m, y = int(parts[0]), int(parts[1]), int(parts[2])
                date_val = f"{y:04d}-{m:02d}-{d:02d}"
        elif "-" in raw:
            parts = raw.split("-")
            if len(parts) == 3:
                y, m, d = int(parts[0]), int(parts[1]), int(parts[2])
                date_val = f"{y:04d}-{m:02d}-{d:02d}"
    except Exception:
        pass

    if not date_val:
        await msg.reply_text("⚠️ Formato de data inválido. Use DD/MM/AAAA (ex: 25/12/2026) ou digite /cancelar.")
        return True

    rec_list = cfg.get("recurring_messages", [])
    for item in rec_list:
        if item.get("id") == msg_id:
            item[field] = date_val
            break
    save_config(cfg)
    del self.pending_inputs[user.id]
    title = "Data de Início" if field == "start_date" else "Data Final"
    text, markup = generate_recurring_detail(cfg, msg_id)
    await msg.reply_text(f"✅ *{title}* definida para `{date_val}`!", parse_mode=ParseMode.MARKDOWN, reply_markup=markup)
    return True
