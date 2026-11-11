from modules.panel_support import *


async def on_wiz_text(self, update, context, cfg, state, action):
    user = update.effective_user
    msg = update.effective_message
    wiz_state = self._get_or_create_wizard_state(user.id)
    raw_text, photo_id, extracted_buttons, src_chat_id, src_msg_id, bak_chat_id, bak_msg_id = await self._extract_message_content(msg, context, user.id)
    video_id = msg.video.file_id if msg.video else None

    if not raw_text and not photo_id and not video_id:
        await msg.reply_text("⚠️ Por favor envie o texto do seu comunicado (ou uma foto/vídeo com legenda).")
        return True

    wiz_state["text"] = raw_text or ""
    if photo_id:
        wiz_state["media_type"] = "photo"
        wiz_state["media_id"] = photo_id
    elif video_id:
        wiz_state["media_type"] = "video"
        wiz_state["media_id"] = video_id

    if extracted_buttons:
        wiz_state["buttons"] = extracted_buttons

    dest_label = get_wizard_dest_label(wiz_state.get("target", "main_channel"), cfg)

    # Se já forneceu mídia e botões juntos na mensagem:
    if wiz_state.get("media_type") and wiz_state.get("buttons"):
        del self.pending_inputs[user.id]
        self._save_wizard_state(user.id, wiz_state)
        await self.show_wizard_preview(update, context, wiz_state, user.id)
        return True
    # Se forneceu mídia mas não botões:
    elif wiz_state.get("media_type"):
        wiz_state["step"] = "buttons"
        self._save_wizard_state(user.id, wiz_state, next_action="wiz_buttons")
        media_label = "🖼️ Foto" if wiz_state["media_type"] == "photo" else "🎥 Vídeo"
        p_text, p_markup = generate_wizard_buttons_prompt(dest_label, media_label)
        await msg.reply_text(p_text, reply_markup=p_markup, parse_mode=ParseMode.MARKDOWN)
        return True
    # Se não forneceu mídia: avança para o Passo 3 (Mídia)
    else:
        wiz_state["step"] = "media"
        self._save_wizard_state(user.id, wiz_state, next_action="wiz_media")
        p_text, p_markup = generate_wizard_media_prompt(dest_label, wiz_state["text"])
        await msg.reply_text(p_text, reply_markup=p_markup, parse_mode=ParseMode.MARKDOWN)
        return True
    return False


async def on_wiz_media(self, update, context, cfg, state, action):
    user = update.effective_user
    msg = update.effective_message
    wiz_state = self._get_or_create_wizard_state(user.id)
    dest_label = get_wizard_dest_label(wiz_state.get("target", "main_channel"), cfg)

    if msg.photo:
        wiz_state["media_type"] = "photo"
        wiz_state["media_id"] = msg.photo[-1].file_id
    elif msg.video:
        wiz_state["media_type"] = "video"
        wiz_state["media_id"] = msg.video.file_id
    else:
        p_text, p_markup = generate_wizard_media_prompt(dest_label, wiz_state.get("text", ""))
        await msg.reply_text("⚠️ Envie uma **Foto** ou **Vídeo**, ou clique em **Pular Mídia** no botão abaixo:", reply_markup=p_markup, parse_mode=ParseMode.MARKDOWN)
        return True

    if wiz_state.get("buttons"):
        del self.pending_inputs[user.id]
        self._save_wizard_state(user.id, wiz_state)
        await self.show_wizard_preview(update, context, wiz_state, user.id)
    else:
        wiz_state["step"] = "buttons"
        self._save_wizard_state(user.id, wiz_state, next_action="wiz_buttons")
        media_label = "🖼️ Foto" if wiz_state.get("media_type") == "photo" else "🎥 Vídeo"
        p_text, p_markup = generate_wizard_buttons_prompt(dest_label, media_label)
        await msg.reply_text(p_text, reply_markup=p_markup, parse_mode=ParseMode.MARKDOWN)
    return True


async def on_wiz_buttons(self, update, context, cfg, state, action):
    user = update.effective_user
    msg = update.effective_message
    wiz_state = self._get_or_create_wizard_state(user.id)
    raw_text = (msg.text or "").strip()
    if raw_text.lower() in ("pular", "nenhum", "remover", "off"):
        wiz_state["buttons"] = []
    else:
        extracted = self._parse_buttons(raw_text)
        if not extracted:
            await msg.reply_text(
                "⚠️ Não encontrei botões no formato correto.\n\n"
                "Envie no modelo: `[Nome do Botão | https://link.com]`\n"
                "Ou clique em **Pular Botões** abaixo:",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⏭️ Pular Botões", callback_data="cfg:wiz:skip_buttons")]])
            )
            return True
        wiz_state["buttons"] = extracted

    del self.pending_inputs[user.id]
    self._save_wizard_state(user.id, wiz_state)
    await self.show_wizard_preview(update, context, wiz_state, user.id)
    return True


async def on_wiz_sched_custom(self, update, context, cfg, state, action):
    user = update.effective_user
    msg = update.effective_message
    val_text = (msg.text or "").strip()
    state = state or self.wizard_states.get(user.id, {})

    from config import get_timezone
    tz = get_timezone(cfg)
    now_dt = datetime.now(tz)

    target_dt = None

    # 1. Relativo: 10m, 45m, 2h, etc.
    m_rel = re.match(r'^(\d+)\s*(m|min|mins|minuto|minutos|h|hr|hrs|hora|horas)$', val_text, re.I)
    if m_rel:
        num = int(m_rel.group(1))
        unit = m_rel.group(2).lower()
        target_dt = now_dt + (timedelta(minutes=num) if unit.startswith('m') else timedelta(hours=num))

    # 2. Hora simples: 18:30 ou 18h30
    if not target_dt:
        val_clean = val_text.replace('h', ':').replace('H', ':')
        m_time = re.match(r'^(\d{1,2}):(\d{2})(?::(\d{2}))?$', val_clean)
        if m_time:
            h = int(m_time.group(1))
            m = int(m_time.group(2))
            if 0 <= h <= 23 and 0 <= m <= 59:
                cand = now_dt.replace(hour=h, minute=m, second=0, microsecond=0)
                if cand <= now_dt:
                    cand += timedelta(days=1)
                target_dt = cand

    # 3. Data e hora completas
    if not target_dt:
        for fmt in ('%d/%m/%Y %H:%M', '%d/%m %H:%M %Y', '%Y-%m-%d %H:%M'):
            try:
                to_parse = val_text if fmt != '%d/%m %H:%M %Y' else f"{val_text} {now_dt.year}"
                dt = datetime.strptime(to_parse, fmt)
                dt = dt.replace(tzinfo=tz)
                if dt < now_dt and fmt == '%d/%m %H:%M %Y':
                    dt = dt.replace(year=now_dt.year + 1)
                target_dt = dt
                break
            except ValueError:
                pass

    if not target_dt or target_dt <= now_dt:
        await msg.reply_text(
            "⚠️ *Não entendi o horário ou a data informada já passou.*\n\n"
            "💡 *Exemplos válidos:*\n"
            "• `18:30` ou `20:00` (hoje ou amanhã)\n"
            "• `18/10 14:00` (dia/mês hora:minuto)\n"
            "• `30m` ou `2h` (daqui a 30 minutos ou 2 horas)\n\n"
            "Por favor envie novamente (ou digite /cancelar):",
            parse_mode=ParseMode.MARKDOWN
        )
        return True

    del self.pending_inputs[user.id]
    await self.save_scheduled_transmission(update, context, state, user.id, target_dt)
    return True


async def on_wiz_link_channel(self, update, context, cfg, state, action):
    user = update.effective_user
    msg = update.effective_message
    val_text = (msg.text or "").strip()
    from config import add_linked_channel
    tokens = [t.strip(",; \n\r") for t in val_text.split() if t.strip(",; \n\r")]
    if not tokens:
        await msg.reply_text("⚠️ Envie o `@username` ou ID do canal (ex: `@meucanal` ou múltiplos `@c1 @c2`), ou digite /cancelar.", parse_mode=ParseMode.MARKDOWN)
        return True

    success_channels = []
    errors = []
    for t in tokens:
        try:
            target_chat = await context.bot.get_chat(t)
            if target_chat.type not in ("channel", "supergroup", "group"):
                errors.append(f"• `{t}`: chat inválido ({target_chat.type})")
                continue

            title = target_chat.title or f"Chat {target_chat.id}"
            username = f"@{target_chat.username}" if target_chat.username else ""
            add_linked_channel(cfg, target_chat.id, title, username)
            success_channels.append((target_chat.id, title, username))
        except Exception as e:
            errors.append(f"• `{t}`: {e}")

    if success_channels:
        del self.pending_inputs[user.id]
        self._save_pending_inputs()

        next_markup = InlineKeyboardMarkup([
            [InlineKeyboardButton("📢 Continuar e Escolher Destino", callback_data="cfg:wiz:start")],
            [InlineKeyboardButton("◀ Voltar ao Painel", callback_data="cfg:page:1")]
        ])

        if len(success_channels) == 1 and not errors:
            cid, title, username = success_channels[0]
            await msg.reply_text(
                f"✅ *Canal '{title}' vinculado com sucesso!* 📢\n\n"
                f"• ID: `{cid}`\n"
                f"• Link: `{username or 'Privado'}`\n\n"
                "O canal foi salvo nas configurações permanentes do bot.\n"
                "Deseja iniciar sua transmissão para ele agora?",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("📢 Transmitir para Este Canal", callback_data=f"cfg:wiz:dest:chn:{cid}")],
                    [InlineKeyboardButton("◀ Voltar à Seleção de Destinos", callback_data="cfg:wiz:start")]
                ])
            )
        else:
            lines = [f"✅ *{len(success_channels)} canal(is) vinculado(s) com sucesso!* 📢\n"]
            for cid, title, username in success_channels:
                u_str = f" ({username})" if username else ""
                lines.append(f"• *{title}* (`{cid}`){u_str}")
            if errors:
                lines.append("\n⚠️ *Falhas encontradas:*")
                lines.extend(errors)
            lines.append("\nOs canais foram salvos permanentemente no bot.")
            await msg.reply_text("\n".join(lines), parse_mode=ParseMode.MARKDOWN, reply_markup=next_markup)
        return True
    else:
        err_msg = "\n".join(errors) if errors else "Não foi possível conectar."
        await msg.reply_text(
            f"❌ *Não foi possível conectar ao(s) canal(is):*\n{err_msg}\n\n"
            "Certifique-se de que adicionou o bot como Administrador no canal com permissão de *Postar Mensagens* e tente novamente (ou digite /cancelar):",
            parse_mode=ParseMode.MARKDOWN
        )
        return True
    return False
