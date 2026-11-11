from modules.panel_support import *


async def on_cfg_resp_list(self, update, context, cfg, title):
    query = update.callback_query
    chat = update.effective_chat
    user = update.effective_user
    data = query.data
    await query.answer()
    text, markup = generate_auto_responder_list(title, cfg)
    await query.edit_message_text(text, reply_markup=markup, parse_mode=ParseMode.MARKDOWN)
    return


async def on_cfg_resp_add(self, update, context, cfg, title):
    query = update.callback_query
    chat = update.effective_chat
    user = update.effective_user
    data = query.data
    responders = cfg.setdefault("auto_responses", [])
    new_id = (max([r.get("id", 0) for r in responders] or [0])) + 1
    new_item = {
        "id": new_id,
        "title": f"Resposta #{new_id}",
        "pattern": "(?i)ajuda|duvida",
        "is_regex": True,
        "text": "👋 Olá, {name}! Como posso te ajudar hoje no grupo {group}?",
        "photo": None,
        "buttons": [],
        "cooldown_seconds": 30,
        "reply_to": True,
        "delete_trigger": False,
        "enabled": True
    }
    responders.append(new_item)
    save_config(cfg)
    if self.auto_responder_handler:
        self.auto_responder_handler.invalidate_cache(new_id)
    await query.answer(f"Resposta #{new_id} criada!")
    text, markup = generate_auto_responder_detail(cfg, new_id)
    await query.edit_message_text(text, reply_markup=markup, parse_mode=ParseMode.MARKDOWN)
    return


async def on_cfg_resp_detail(self, update, context, cfg, title):
    query = update.callback_query
    chat = update.effective_chat
    user = update.effective_user
    data = query.data
    resp_id = int(data.split(":")[-1])
    await query.answer()
    text, markup = generate_auto_responder_detail(cfg, resp_id)
    await query.edit_message_text(text, reply_markup=markup, parse_mode=ParseMode.MARKDOWN)
    return


async def on_cfg_resp_toggle(self, update, context, cfg, title):
    query = update.callback_query
    chat = update.effective_chat
    user = update.effective_user
    data = query.data
    resp_id = int(data.split(":")[-1])
    responders = cfg.get("auto_responses", [])
    for r in responders:
        if r.get("id") == resp_id:
            r["enabled"] = not r.get("enabled", True)
            save_config(cfg)
            await query.answer(f"Resposta #{resp_id}: {'Ativada' if r['enabled'] else 'Desativada'}")
            break
    text, markup = generate_auto_responder_detail(cfg, resp_id)
    await query.edit_message_text(text, reply_markup=markup, parse_mode=ParseMode.MARKDOWN)
    return


async def on_cfg_resp_del(self, update, context, cfg, title):
    from modules.confirmations import confirm_panel_action
    await confirm_panel_action(self, update, context)


async def on_cfg_resp_cycle_cd(self, update, context, cfg, title):
    query = update.callback_query
    chat = update.effective_chat
    user = update.effective_user
    data = query.data
    resp_id = int(data.split(":")[-1])
    responders = cfg.get("auto_responses", [])
    for r in responders:
        if r.get("id") == resp_id:
            cur_cd = r.get("cooldown_seconds", 30)
            cycle = [5, 10, 15, 30, 60, 120]
            next_cd = cycle[(cycle.index(cur_cd) + 1) % len(cycle)] if cur_cd in cycle else 30
            r["cooldown_seconds"] = next_cd
            save_config(cfg)
            await query.answer(f"Cooldown: {next_cd}s")
            break
    text, markup = generate_auto_responder_detail(cfg, resp_id)
    await query.edit_message_text(text, reply_markup=markup, parse_mode=ParseMode.MARKDOWN)
    return


async def on_cfg_resp_cycle_delay(self, update, context, cfg, title):
    query = update.callback_query
    chat = update.effective_chat
    user = update.effective_user
    data = query.data
    resp_id = int(data.split(":")[-1])
    responders = cfg.get("auto_responses", [])
    for r in responders:
        if r.get("id") == resp_id:
            cur_delay = r.get("delay_seconds", 0)
            cycle = [0, 5, 10, 15, 20, 30]
            next_delay = cycle[(cycle.index(cur_delay) + 1) % len(cycle)] if cur_delay in cycle else 0
            r["delay_seconds"] = next_delay
            save_config(cfg)
            delay_msg = f"{next_delay}s" if next_delay > 0 else "Imediato (0s)"
            await query.answer(f"Espera / Delay: {delay_msg}")
            break
    text, markup = generate_auto_responder_detail(cfg, resp_id)
    await query.edit_message_text(text, reply_markup=markup, parse_mode=ParseMode.MARKDOWN)
    return


async def on_cfg_resp_toggle_regex(self, update, context, cfg, title):
    query = update.callback_query
    chat = update.effective_chat
    user = update.effective_user
    data = query.data
    resp_id = int(data.split(":")[-1])
    responders = cfg.get("auto_responses", [])
    for r in responders:
        if r.get("id") == resp_id:
            r["is_regex"] = not r.get("is_regex", True)
            save_config(cfg)
            if self.auto_responder_handler:
                self.auto_responder_handler.invalidate_cache(resp_id)
            mode_label = "Regex" if r["is_regex"] else "Palavra Simples"
            await query.answer(f"Modo: {mode_label}")
            break
    text, markup = generate_auto_responder_detail(cfg, resp_id)
    await query.edit_message_text(text, reply_markup=markup, parse_mode=ParseMode.MARKDOWN)
    return


async def on_cfg_resp_toggle_reply(self, update, context, cfg, title):
    query = update.callback_query
    chat = update.effective_chat
    user = update.effective_user
    data = query.data
    resp_id = int(data.split(":")[-1])
    responders = cfg.get("auto_responses", [])
    for r in responders:
        if r.get("id") == resp_id:
            r["reply_to"] = not r.get("reply_to", True)
            save_config(cfg)
            await query.answer(f"Responder citando: {'Sim' if r['reply_to'] else 'Não'}")
            break
    text, markup = generate_auto_responder_detail(cfg, resp_id)
    await query.edit_message_text(text, reply_markup=markup, parse_mode=ParseMode.MARKDOWN)
    return


async def on_cfg_resp_toggle_del_trig(self, update, context, cfg, title):
    query = update.callback_query
    chat = update.effective_chat
    user = update.effective_user
    data = query.data
    resp_id = int(data.split(":")[-1])
    responders = cfg.get("auto_responses", [])
    for r in responders:
        if r.get("id") == resp_id:
            r["delete_trigger"] = not r.get("delete_trigger", False)
            save_config(cfg)
            await query.answer(f"Apagar gatilho do usuário: {'Sim' if r['delete_trigger'] else 'Não'}")
            break
    text, markup = generate_auto_responder_detail(cfg, resp_id)
    await query.edit_message_text(text, reply_markup=markup, parse_mode=ParseMode.MARKDOWN)
    return


async def on_cfg_resp_test(self, update, context, cfg, title):
    query = update.callback_query
    chat = update.effective_chat
    user = update.effective_user
    data = query.data
    resp_id = int(data.split(":")[-1])
    if self.auto_responder_handler:
        await query.answer("Enviando teste de resposta...")
        await self.auto_responder_handler.test_responder(update, context, resp_id)
    else:
        await query.answer("Handler de teste não configurado.", show_alert=True)
    return


async def on_cfg_resp_edit_text(self, update, context, cfg, title):
    query = update.callback_query
    chat = update.effective_chat
    user = update.effective_user
    data = query.data
    resp_id = int(data.split(":")[-1])
    self.pending_inputs[user.id] = {"action": "resp_edit_text", "item_id": resp_id, "chat_id": chat.id}
    await query.answer()
    prompt = (
        f"✏️ *Digite a mensagem da Resposta Automática #{resp_id}:*\n\n"
        "Variáveis disponíveis:\n"
        "• `{name}` - Nome do usuário\n"
        "• `{username}` - @username\n"
        "• `{group}` - Nome do grupo\n"
        "• `{id}` - ID do usuário\n"
        "• `{date}` - Data atual\n"
        "• `{hora}` - Hora atual\n\n"
        "_Envie o texto agora ou digite /cancelar:_"
    )
    await chat.send_message(prompt, parse_mode=ParseMode.MARKDOWN)
    return


async def on_cfg_resp_edit_pattern(self, update, context, cfg, title):
    query = update.callback_query
    chat = update.effective_chat
    user = update.effective_user
    data = query.data
    resp_id = int(data.split(":")[-1])
    self.pending_inputs[user.id] = {"action": "resp_edit_pattern", "item_id": resp_id, "chat_id": chat.id}
    await query.answer()
    prompt = (
        f"🎯 *Digite o Gatilho / Expressão da Resposta #{resp_id}:*\n\n"
        "💡 *Exemplos:*\n"
        "• Palavra simples: `pix` ou `partituras`\n"
        "• Regex flexível: `(?i)\\b(pix|chave\\s*pix|manda\\s*pix)\\b`\n\n"
        "_Envie o novo gatilho agora ou digite /cancelar:_"
    )
    await chat.send_message(prompt, parse_mode=ParseMode.MARKDOWN)
    return


async def on_cfg_resp_edit_title(self, update, context, cfg, title):
    query = update.callback_query
    chat = update.effective_chat
    user = update.effective_user
    data = query.data
    resp_id = int(data.split(":")[-1])
    self.pending_inputs[user.id] = {"action": "resp_edit_title", "item_id": resp_id, "chat_id": chat.id}
    await query.answer()
    prompt = f"🏷️ *Digite o novo Título da Resposta #{resp_id} (ou /cancelar):*"
    await chat.send_message(prompt, parse_mode=ParseMode.MARKDOWN)
    return


async def on_cfg_resp_edit_photo(self, update, context, cfg, title):
    query = update.callback_query
    chat = update.effective_chat
    user = update.effective_user
    data = query.data
    resp_id = int(data.split(":")[-1])
    self.pending_inputs[user.id] = {"action": "resp_edit_photo", "item_id": resp_id, "chat_id": chat.id}
    await query.answer()
    prompt = f"🖼️ *Envie a foto ou imagem para a Resposta #{resp_id} (ou /cancelar):*"
    await chat.send_message(prompt, parse_mode=ParseMode.MARKDOWN)
    return


async def on_cfg_resp_del_photo(self, update, context, cfg, title):
    query = update.callback_query
    chat = update.effective_chat
    user = update.effective_user
    data = query.data
    resp_id = int(data.split(":")[-1])
    responders = cfg.get("auto_responses", [])
    for r in responders:
        if r.get("id") == resp_id:
            r["photo"] = None
            save_config(cfg)
            await query.answer("Foto removida!")
            break
    text, markup = generate_auto_responder_detail(cfg, resp_id)
    await query.edit_message_text(text, reply_markup=markup, parse_mode=ParseMode.MARKDOWN)
    return


async def on_cfg_resp_edit_buttons(self, update, context, cfg, title):
    query = update.callback_query
    chat = update.effective_chat
    user = update.effective_user
    data = query.data
    resp_id = int(data.split(":")[-1])
    self.pending_inputs[user.id] = {"action": "resp_edit_buttons", "item_id": resp_id, "chat_id": chat.id}
    await query.answer()
    prompt = (
        f"🔘 *Configure os Botões para a Resposta #{resp_id}:*\n\n"
        "Envie no formato: `Texto | https://link.com`\n"
        "Exemplo:\n"
        "`Chave PIX Copia e Cola | https://partituras.com/pix`\n\n"
        "_(Envie agora, ou 'remover' para limpar todos, ou /cancelar)_"
    )
    await chat.send_message(prompt, parse_mode=ParseMode.MARKDOWN)
    return


async def on_cfg_resp_del_buttons(self, update, context, cfg, title):
    query = update.callback_query
    chat = update.effective_chat
    user = update.effective_user
    data = query.data
    resp_id = int(data.split(":")[-1])
    responders = cfg.get("auto_responses", [])
    for r in responders:
        if r.get("id") == resp_id:
            r["buttons"] = []
            save_config(cfg)
            await query.answer("Botões removidos!")
            break
    text, markup = generate_auto_responder_detail(cfg, resp_id)
    await query.edit_message_text(text, reply_markup=markup, parse_mode=ParseMode.MARKDOWN)
    return
