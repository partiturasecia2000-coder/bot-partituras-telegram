from modules.panel_support import *

class BroadcastMixin:
    async def cmd_comunicado(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Inicia o Guia Interativo de Transmissão / Comunicado."""
        if not await self._require_admin(update):
            await update.effective_message.reply_text("⛔ Este comando é exclusivo para administradores.")
            return
        await self.start_wizard(update, context)


    def _get_or_create_wizard_state(self, user_id: int) -> dict:
        """Obtém o estado do assistente de transmissão de forma unificada e à prova de perda de dados."""
        st = self.wizard_states.get(user_id)
        if not st:
            st = {}
            self.wizard_states[user_id] = st

        # Sincroniza se pending_inputs tiver dados mais recentes ou texto salvo
        if user_id in self.pending_inputs:
            p = self.pending_inputs[user_id]
            if isinstance(p, dict):
                inner = p.get("state")
                if isinstance(inner, dict):
                    for k, v in inner.items():
                        if v is not None and v != "":
                            st[k] = v
                for k in ("text", "media_type", "media_id", "buttons", "pin", "target", "delay_seconds"):
                    if k in p and p[k] is not None and p[k] != "":
                        st[k] = p[k]
        return st


    def _save_wizard_state(self, user_id: int, state: dict, next_action: str = None):
        """Salva o estado do assistente de transmissão em memória e no pending_inputs simultaneamente."""
        self.wizard_states[user_id] = state
        if next_action:
            self.pending_inputs[user_id] = {
                "action": next_action,
                "state": state,
                "target": state.get("target"),
                "text": state.get("text", ""),
                "media_type": state.get("media_type"),
                "media_id": state.get("media_id"),
                "buttons": state.get("buttons", []),
                "pin": state.get("pin", False),
                "delay_seconds": state.get("delay_seconds", 2)
            }
            self._save_pending_inputs()


    async def start_wizard(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Abre o Passo 1 do Guia de Transmissão."""
        cfg = load_config()
        text, markup = generate_wizard_dest_menu(cfg)
        if update.callback_query:
            try:
                await update.callback_query.edit_message_text(text, reply_markup=markup, parse_mode=ParseMode.MARKDOWN)
            except Exception:
                await update.callback_query.edit_message_text(text, reply_markup=markup)
        elif update.effective_message:
            try:
                await update.effective_message.reply_text(text, reply_markup=markup, parse_mode=ParseMode.MARKDOWN)
            except Exception:
                await update.effective_message.reply_text(text, reply_markup=markup)


    async def show_wizard_preview(self, update: Update, context: ContextTypes.DEFAULT_TYPE, state: dict, user_id: int):
        """Envia a prévia idêntica de como a postagem ficará e os controles de envio."""
        cfg = load_config()
        bot = context.bot
        self._save_wizard_state(user_id, state)

        text = state.get("text", "")
        media_type = state.get("media_type")
        media_id = state.get("media_id")
        buttons = state.get("buttons", [])
        pin = state.get("pin", False)
        target = state.get("target", "main_channel")

        from modules.utils import build_rich_buttons_markup, smart_send_message, smart_send_photo, smart_send_video
        markup = build_rich_buttons_markup(buttons)

        # 1. Envia a prévia idêntica ao que será postado
        try:
            if media_type == "video" and media_id:
                await smart_send_video(bot, chat_id=user_id, video=media_id, caption=text, reply_markup=markup)
            elif media_type == "photo" and media_id:
                await smart_send_photo(bot, chat_id=user_id, photo=media_id, caption=text, reply_markup=markup)
            else:
                await smart_send_message(bot, chat_id=user_id, text=text or "📢 Comunicado Oficial", reply_markup=markup)
        except Exception as e_prev:
            logger.error(f"Erro ao gerar prévia da transmissão: {e_prev}")
            try:
                await bot.send_message(chat_id=user_id, text=f"⚠️ Falha ao exibir prévia formatada: {e_prev}")
            except Exception:
                pass

        # 2. Envia os controles de confirmação da transmissão
        dest_label = get_wizard_dest_label(target, cfg)
        media_label = "🎥 Vídeo" if media_type == "video" else ("🖼️ Foto" if media_type == "photo" else "⚪ Nenhuma (Somente Texto)")
        btns_count = sum(len(r) for r in buttons) if (buttons and isinstance(buttons[0], list)) else len(buttons)
        delay_sec = state.get("delay_seconds", 2)

        ctrl_text, ctrl_markup = generate_wizard_preview_controls(dest_label, media_label, btns_count, pin, delay_sec)
        try:
            await bot.send_message(chat_id=user_id, text=ctrl_text, reply_markup=ctrl_markup, parse_mode=ParseMode.MARKDOWN)
        except Exception:
            await bot.send_message(chat_id=user_id, text=ctrl_text, reply_markup=ctrl_markup)


    async def execute_wizard_send(self, update: Update, context: ContextTypes.DEFAULT_TYPE, user_id: int):
        """O envio imediato usa a mesma fila e o mesmo relatório dos agendados."""
        state = self._get_or_create_wizard_state(user_id)
        if not state or (not state.get("text") and not state.get("media_id")):
            await update.effective_message.reply_text("⚠️ Prepare o texto ou a mídia antes de enviar.")
            return
        cfg = load_config()
        if not get_wizard_targets_list(state.get("target", "main_channel"), cfg):
            await update.effective_message.reply_text("⚠️ Nenhum destino encontrado.")
            return
        existing = cfg.setdefault("scheduled_transmissions", [])
        item_id = max(int(time.time()*1000), max((x.get("id", 0) for x in existing), default=0)+1)
        entry = {key: copy.deepcopy(state.get(key)) for key in ("text", "media_type", "media_id", "buttons", "pin", "target", "delay_seconds")}
        entry.update(id=item_id, target=state.get("target", "main_channel"),
                     delay_seconds=state.get("delay_seconds", 2), buttons=state.get("buttons", []),
                     status="pending", schedule_timestamp=time.time(), schedule_display="Envio imediato",
                     creator_id=user_id, created_at=datetime.now().isoformat())
        existing.append(entry)
        if not save_config(cfg):
            await update.effective_message.reply_text("⚠️ Não foi possível salvar; o rascunho foi mantido.")
            return
        self.wizard_states.pop(user_id, None)
        self.pending_inputs.pop(user_id, None)
        if update.callback_query:
            try:
                await update.callback_query.edit_message_reply_markup(reply_markup=None)
            except Exception:
                pass
        from modules.scheduler import start_scheduled_transmission
        start_scheduled_transmission(item_id, force=True)
        await update.effective_message.reply_text(
            "📨 Transmissão registrada. Acompanhe o resultado por destino:",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Ver resultados", callback_data=f"cfg:tx:{item_id}:1")]]))



    async def cmd_agendados(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Exibe o menu de transmissões agendadas pendentes."""
        if not await self._require_admin(update):
            await update.effective_message.reply_text("⛔ Este comando é exclusivo para administradores.")
            return
        cfg = load_config()
        text, markup = generate_scheduled_transmissions_menu(cfg)
        try:
            await update.effective_message.reply_text(text, reply_markup=markup, parse_mode=ParseMode.MARKDOWN)
        except Exception:
            await update.effective_message.reply_text(text, reply_markup=markup)


    async def save_scheduled_transmission(self, update: Update, context: ContextTypes.DEFAULT_TYPE, state: dict, user_id: int, target_dt: datetime):
        """Salva a transmissão agendada no config.json e confirma para o administrador."""
        cfg = load_config()
        bot = context.bot
        target = state.get("target", "main_channel")
        text = state.get("text", "")
        media_type = state.get("media_type")
        media_id = state.get("media_id")
        buttons = state.get("buttons", [])
        pin = state.get("pin", False)
        delay_sec = state.get("delay_seconds", 2)
        dest_label = get_wizard_dest_label(target, cfg)
        targets = get_wizard_targets_list(target, cfg)

        user = update.effective_user
        admin_name = user.full_name if user else "Admin"

        item_id = int(time.time() * 1000)
        target_ts = target_dt.timestamp()
        display_str = target_dt.strftime("%d/%m/%Y às %H:%M")

        entry = {
            "id": item_id,
            "target": target,
            "text": text,
            "media_type": media_type,
            "media_id": media_id,
            "buttons": buttons,
            "pin": pin,
            "delay_seconds": delay_sec,
            "schedule_timestamp": target_ts,
            "schedule_display": display_str,
            "creator_id": user_id,
            "creator_name": admin_name,
            "status": "pending",
            "created_at": datetime.now().isoformat()
        }

        cfg.setdefault("scheduled_transmissions", []).append(entry)
        save_config(cfg)

        self.wizard_states.pop(user_id, None)
        if user_id in self.pending_inputs:
            del self.pending_inputs[user_id]
            self._save_pending_inputs()

        media_label = "🎥 Vídeo" if media_type == "video" else ("🖼️ Foto" if media_type == "photo" else "⚪ Texto")
        btns_count = sum(len(r) for r in buttons) if (buttons and isinstance(buttons[0], list)) else len(buttons)

        confirm_text = (
            "🗓️ *TRANSMISSÃO AGENDADA COM SUCESSO!*\n"
            "🎼 ══════════════════════ 🎼\n\n"
            f"• *Destino:* `{dest_label}` ({len(targets)} chats)\n"
            f"• ⏰ *Horário Programado:* `{display_str}`\n"
            f"• 🌊 *Distribuição:* `{delay_sec}s entre cada chat (Envio Suave)`\n"
            f"• 📌 *Fixar no Topo:* `{'Sim 📌' if pin else 'Não'}`\n"
            f"• 🖼️ *Mídia:* `{media_label}`\n"
            f"• 🔘 *Botões:* `{btns_count} configurado(s)`\n\n"
            "✅ O Maestro Bot efetuará o envio e a distribuição de forma 100% autônoma no horário agendado!\n"
            "Você receberá a confirmação completa aqui no seu privado assim que for disparada."
        )

        confirm_markup = InlineKeyboardMarkup([
            [InlineKeyboardButton("🗓️ Ver Agendadas", callback_data="cfg:sched:list")],
            [InlineKeyboardButton("📢 Nova Transmissão", callback_data="cfg:wiz:start")],
            [InlineKeyboardButton("◀ Voltar ao Painel", callback_data="cfg:page:1")]
        ])

        if update.callback_query:
            try:
                await update.callback_query.edit_message_text(confirm_text, reply_markup=confirm_markup, parse_mode=ParseMode.MARKDOWN)
            except Exception:
                await update.callback_query.edit_message_text(confirm_text, reply_markup=confirm_markup)
        elif update.effective_message:
            try:
                await update.effective_message.reply_text(confirm_text, reply_markup=confirm_markup, parse_mode=ParseMode.MARKDOWN)
            except Exception:
                await update.effective_message.reply_text(confirm_text, reply_markup=confirm_markup)

        # Log de Auditoria
        import html
        await send_mod_log(
            bot=bot,
            event_type="say",
            title="Transmissão Agendada Criada",
            user_info=f"Destino: <b>{html.escape(dest_label)}</b> ({len(targets)} chats)",
            admin_info=f"<b>{html.escape(admin_name)}</b>",
            details=f"Programado para: {display_str} | Delay: {delay_sec}s/chat"
        )

