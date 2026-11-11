from modules.panel_support import *


async def on_welcome(self, update, context, cfg, state, action):
    user = update.effective_user
    msg = update.effective_message
    return await handle_welcome_input(self, msg, context, user, state, action)


async def on_banned_add(self, update, context, cfg, state, action):
    user = update.effective_user
    msg = update.effective_message
    if not msg.text:
        await msg.reply_text("⚠️ Envie as palavras separadas por vírgula ou /cancelar.")
        return True

    raw = msg.text.replace("\n", ",")
    new_items = [w.strip().lower() for w in raw.split(",") if w.strip()]
    if not new_items:
        await msg.reply_text("⚠️ Nenhuma palavra válida detectada. Digite /cancelar para desistir.")
        return True

    current = cfg.setdefault("antispam", {}).setdefault("banned_words", [])
    added_count = 0
    for w in new_items:
        if w not in current:
            current.append(w)
            added_count += 1

    save_config(cfg)
    del self.pending_inputs[user.id]

    markup = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔤 Voltar a Palavras Proibidas", callback_data="cfg:sub:banned")]
    ])
    await msg.reply_text(
        f"✅ *{added_count} nova(s) palavra(s) adicionada(s) à lista negra com sucesso!*",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=markup
    )
    return True


async def on_banned_remove(self, update, context, cfg, state, action):
    user = update.effective_user
    msg = update.effective_message
    if not msg.text:
        await msg.reply_text("⚠️ Envie as palavras a remover ou /cancelar.")
        return True

    raw = msg.text.replace("\n", ",")
    to_remove = [w.strip().lower() for w in raw.split(",") if w.strip()]
    current = cfg.setdefault("antispam", {}).setdefault("banned_words", [])

    removed_count = 0
    for w in to_remove:
        if w in current:
            current.remove(w)
            removed_count += 1

    save_config(cfg)
    del self.pending_inputs[user.id]

    markup = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔤 Voltar a Palavras Proibidas", callback_data="cfg:sub:banned")]
    ])
    await msg.reply_text(
        f"✅ *{removed_count} palavra(s) removida(s) da lista negra!*",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=markup
    )
    return True


async def on_logs_set_id(self, update, context, cfg, state, action):
    user = update.effective_user
    msg = update.effective_message
    if not msg.text:
        await msg.reply_text("⚠️ Envie o ID do canal ou /cancelar.")
        return True

    val = msg.text.strip()
    if val.lower() in ("desativar", "off", "remover"):
        cfg["log_channel_id"] = None
        save_config(cfg)
        del self.pending_inputs[user.id]
        markup = InlineKeyboardMarkup([[InlineKeyboardButton("📡 Voltar ao Menu de Logs", callback_data="cfg:sub:logs")]])
        await msg.reply_text("✅ *Canal de logs desativado!*", parse_mode=ParseMode.MARKDOWN, reply_markup=markup)
        return True

    try:
        channel_id = int(val)
        await context.bot.send_message(
            chat_id=channel_id,
            text="📡 *Canal de Logs Conectado via Painel!*\nRegistro de auditoria ativado com sucesso.",
            parse_mode=ParseMode.MARKDOWN
        )
        cfg["log_channel_id"] = channel_id
        save_config(cfg)
        del self.pending_inputs[user.id]
        markup = InlineKeyboardMarkup([[InlineKeyboardButton("📡 Voltar ao Menu de Logs", callback_data="cfg:sub:logs")]])
        await msg.reply_text(f"✅ *Canal de logs conectado com sucesso!* (ID: `{channel_id}`)\nMensagem de teste enviada.", parse_mode=ParseMode.MARKDOWN, reply_markup=markup)
        return True
    except Exception as e:
        await msg.reply_text(
            f"❌ *Erro ao conectar ao canal:* `{e}`\n\n"
            "Certifique-se de que o bot foi adicionado como **Administrador** no canal e reenvie o ID ou digite /cancelar:",
            parse_mode=ParseMode.MARKDOWN
        )
        return True
    return False


async def on_welcome_autodel_time(self, update, context, cfg, state, action):
    user = update.effective_user
    msg = update.effective_message
    target_gid = str(state.get("group_id", "general"))
    val_text = (msg.text or "").strip()
    sec = parse_time_string_to_seconds(val_text)

    if sec is None:
        await msg.reply_text(
            "⚠️ *Tempo inválido!*\n\n"
            "Envie um tempo entre *1 minuto (60s)* e *24 horas (86400s)*, ou `nunca` para desativar.\n\n"
            "💡 *Exemplos válidos:*\n"
            "• `5m` ou `5 min` ou `5` (5 minutos)\n"
            "• `10m` ou `15m` ou `30m`\n"
            "• `1h` ou `2h` ou `24h`\n"
            "• `nunca` ou `0` (não apagar)\n\n"
            "Tente novamente ou envie /cancelar:",
            parse_mode=ParseMode.MARKDOWN
        )
        return True

    if target_gid in ("general", "0", ""):
        cfg.setdefault("welcome", {})["delete_welcome_after_seconds"] = sec
        ret_cb = "cfg:sub:wtime:general"
    else:
        from config import get_welcome_for_chat
        w_grp = cfg.setdefault("group_welcomes", {}).setdefault(target_gid, dict(get_welcome_for_chat(cfg, target_gid)))
        w_grp["delete_welcome_after_seconds"] = sec
        ret_cb = f"cfg:sub:wtime:{target_gid}"

    save_config(cfg)
    del self.pending_inputs[user.id]

    lbl = format_time_label(sec)
    desc = "nunca apagar (fica visível para sempre)" if sec == 0 else f"apagar após {lbl} ({sec}s)"
    markup = InlineKeyboardMarkup([
        [InlineKeyboardButton("⏱️ Voltar ao Menu de Tempo", callback_data=ret_cb)],
        [InlineKeyboardButton("💬 Voltar às Boas-Vindas", callback_data=f"cfg:welcome:cfg:{target_gid}")]
    ])
    await msg.reply_text(
        f"✅ *Tempo de auto-apagar atualizado com sucesso!*\nNovo tempo: *{desc}*.",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=markup
    )
    return True


async def on_custom_timezone(self, update, context, cfg, state, action):
    user = update.effective_user
    msg = update.effective_message
    val_text = (msg.text or "").strip()
    from config import set_timezone
    success = set_timezone(cfg, val_text)
    if not success:
        await msg.reply_text(
            "❌ *Fuso horário inválido!*\n\n"
            "O fuso deve seguir o padrão IANA oficial (ex: `America/Sao_Paulo`, `America/Manaus`, `America/Fortaleza`, `America/Cuiaba`, `Europe/Lisbon`, `UTC`).\n\n"
            "Por favor, verifique o nome e tente novamente ou envie /cancelar:",
            parse_mode=ParseMode.MARKDOWN
        )
        return True

    del self.pending_inputs[user.id]
    from config import get_timezone_label
    markup = InlineKeyboardMarkup([
        [InlineKeyboardButton("🕒 Voltar ao Menu de Fuso", callback_data="cfg:sub:timezone")],
        [InlineKeyboardButton("◀ Voltar ao Painel Avançado", callback_data="cfg:page:2")]
    ])
    await msg.reply_text(
        f"✅ *Fuso horário alterado com sucesso para:* `{get_timezone_label(cfg)}`!",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=markup
    )
    return True
