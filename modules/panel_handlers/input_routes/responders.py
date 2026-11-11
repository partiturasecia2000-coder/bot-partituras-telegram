from modules.panel_support import *


async def on_resp_edit_text(self, update, context, cfg, state, action):
    user = update.effective_user
    msg = update.effective_message
    item_id = state.get("item_id")
    raw_text, photo_id, extracted_buttons, src_chat_id, src_msg_id, bak_chat_id, bak_msg_id = await self._extract_message_content(msg, context, user.id)

    responders = cfg.setdefault("auto_responses", [])
    for item in responders:
        if item.get("id") == item_id:
            if raw_text:
                item["text"] = raw_text
            if photo_id:
                item["photo"] = photo_id
            if extracted_buttons:
                item["buttons"] = extracted_buttons
            break
    save_config(cfg)
    if self.auto_responder_handler:
        self.auto_responder_handler.invalidate_cache(item_id)
    del self.pending_inputs[user.id]

    summary_items = ["• *Texto:* Atualizado com formatação rica"]
    if photo_id:
        summary_items.append("• *Foto:* Imagem salva com sucesso")
    if extracted_buttons:
        total_btns = sum(len(r) for r in extracted_buttons)
        summary_items.append(f"• *Botões:* {total_btns} botão(ões) capturados!")

    summary_str = "\n".join(summary_items)
    markup = InlineKeyboardMarkup([
        [InlineKeyboardButton("⚙️ Voltar à Resposta", callback_data=f"cfg:resp:detail:{item_id}")],
        [InlineKeyboardButton("📋 Lista de Respostas", callback_data="cfg:resp:list")]
    ])
    await msg.reply_text(f"✅ *Resposta #{item_id} atualizada com sucesso!*\n\n{summary_str}", parse_mode=ParseMode.MARKDOWN, reply_markup=markup)
    return True


async def on_resp_edit_pattern(self, update, context, cfg, state, action):
    user = update.effective_user
    msg = update.effective_message
    item_id = state.get("item_id")
    if not msg.text:
        await msg.reply_text("⚠️ Envie o gatilho/expressão ou /cancelar.")
        return True

    new_pat = msg.text.strip()
    responders = cfg.setdefault("auto_responses", [])
    target = next((r for r in responders if r.get("id") == item_id), None)
    if target and target.get("is_regex", True):
        valid, err = validate_regex(new_pat)
        if not valid:
            await msg.reply_text(
                f"❌ *Expressão Regular (Regex) Inválida!*\n\nErro: `{err}`\n\n"
                "💡 *Dicas de sintaxe:*\n"
                "• Para palavras exatas: `(?i)\\b(pix|chave)\\b`\n"
                "• Para alternativas: `(?i)ajuda|suporte|duvida`\n\n"
                "Envie a regex corrigida ou digite /cancelar:",
                parse_mode=ParseMode.MARKDOWN
            )
            return True

    if target:
        target["pattern"] = new_pat
    save_config(cfg)
    if self.auto_responder_handler:
        self.auto_responder_handler.invalidate_cache(item_id)
    del self.pending_inputs[user.id]

    markup = InlineKeyboardMarkup([
        [InlineKeyboardButton("⚙️ Voltar à Resposta", callback_data=f"cfg:resp:detail:{item_id}")],
        [InlineKeyboardButton("📋 Lista de Respostas", callback_data="cfg:resp:list")]
    ])
    await msg.reply_text(f"✅ *Gatilho da resposta #{item_id} atualizado para:* `{new_pat}`", parse_mode=ParseMode.MARKDOWN, reply_markup=markup)
    return True


async def on_resp_edit_title(self, update, context, cfg, state, action):
    user = update.effective_user
    msg = update.effective_message
    item_id = state.get("item_id")
    if not msg.text:
        await msg.reply_text("⚠️ Envie um título ou /cancelar.")
        return True

    new_title = msg.text.strip()
    responders = cfg.setdefault("auto_responses", [])
    for item in responders:
        if item.get("id") == item_id:
            item["title"] = new_title
            break
    save_config(cfg)
    del self.pending_inputs[user.id]

    markup = InlineKeyboardMarkup([
        [InlineKeyboardButton("⚙️ Voltar à Resposta", callback_data=f"cfg:resp:detail:{item_id}")],
        [InlineKeyboardButton("📋 Lista de Respostas", callback_data="cfg:resp:list")]
    ])
    await msg.reply_text(f"✅ *Título alterado para:* `{new_title}`", parse_mode=ParseMode.MARKDOWN, reply_markup=markup)
    return True


async def on_resp_edit_photo(self, update, context, cfg, state, action):
    user = update.effective_user
    msg = update.effective_message
    item_id = state.get("item_id")
    if not msg.photo:
        await msg.reply_text("⚠️ Por favor envie uma FOTO/IMAGEM ou digite /cancelar.")
        return True

    file_id = msg.photo[-1].file_id
    responders = cfg.setdefault("auto_responses", [])
    for item in responders:
        if item.get("id") == item_id:
            item["photo"] = file_id
            break
    save_config(cfg)
    del self.pending_inputs[user.id]

    markup = InlineKeyboardMarkup([
        [InlineKeyboardButton("⚙️ Voltar à Resposta", callback_data=f"cfg:resp:detail:{item_id}")],
        [InlineKeyboardButton("📋 Lista de Respostas", callback_data="cfg:resp:list")]
    ])
    await msg.reply_text(f"✅ *Foto da resposta #{item_id} configurada com sucesso!*", parse_mode=ParseMode.MARKDOWN, reply_markup=markup)
    return True


async def on_resp_edit_buttons(self, update, context, cfg, state, action):
    user = update.effective_user
    msg = update.effective_message
    item_id = state.get("item_id")
    if not msg.text:
        await msg.reply_text("⚠️ Envie os botões ou /cancelar.")
        return True

    if msg.text.strip().lower() in ("remover", "limpar", "nenhum"):
        responders = cfg.setdefault("auto_responses", [])
        for item in responders:
            if item.get("id") == item_id:
                item["buttons"] = []
                break
        save_config(cfg)
        del self.pending_inputs[user.id]
        markup = InlineKeyboardMarkup([[InlineKeyboardButton("⚙️ Voltar", callback_data=f"cfg:resp:detail:{item_id}")]])
        await msg.reply_text(f"✅ *Botões removidos da resposta #{item_id}!*", parse_mode=ParseMode.MARKDOWN, reply_markup=markup)
        return True

    new_buttons = self._parse_buttons(msg.text)
    if not new_buttons:
        await msg.reply_text("⚠️ Nenhum botão válido detectado.\nEnvie no formato: `Texto | https://link.com` ou /cancelar.", parse_mode=ParseMode.MARKDOWN)
        return True

    responders = cfg.setdefault("auto_responses", [])
    for item in responders:
        if item.get("id") == item_id:
            item["buttons"] = new_buttons
            break
    save_config(cfg)
    del self.pending_inputs[user.id]

    markup = InlineKeyboardMarkup([
        [InlineKeyboardButton("⚙️ Voltar à Resposta", callback_data=f"cfg:resp:detail:{item_id}")],
        [InlineKeyboardButton("📋 Lista de Respostas", callback_data="cfg:resp:list")]
    ])
    await msg.reply_text(f"✅ *{len(new_buttons)} botão(ões) configurado(s) na resposta #{item_id}!*", parse_mode=ParseMode.MARKDOWN, reply_markup=markup)
    return True
