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


    async def execute_wizard_send(self,update,context,user_id):
        from modules.broadcast_drafts import create_draft,show_preview
        state=self._get_or_create_wizard_state(user_id)
        try:
            item=create_draft(update,state,get_wizard_targets_list(state.get("target","main_channel"),load_config()))
        except (ValueError,OSError):
            await update.effective_message.reply_text("Não foi possível preparar a prévia. Confira texto, mídia e destinos.")
            return
        self.wizard_states.pop(user_id,None)
        self.pending_inputs.pop(user_id,None)
        await show_preview(update,context,item)




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


    async def save_scheduled_transmission(self,update,context,state,user_id,target_dt):
        from modules.broadcast_drafts import create_draft,show_preview
        try:
            item=create_draft(update,state,get_wizard_targets_list(state.get("target","main_channel"),load_config()),
                schedule_timestamp=target_dt.timestamp(),schedule_display=target_dt.strftime("%d/%m/%Y às %H:%M"))
        except (ValueError,OSError):
            await update.effective_message.reply_text("Não foi possível preparar a prévia do agendamento. O rascunho foi mantido.")
            return
        self.wizard_states.pop(user_id,None)
        self.pending_inputs.pop(user_id,None)
        await show_preview(update,context,item)


