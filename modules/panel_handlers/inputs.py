from modules.panel_support import *
from .input_routes import INPUT_ROUTES

class InputsMixin:
    async def _extract_message_content(self, msg, context: ContextTypes.DEFAULT_TYPE = None, user_id: int = None) -> tuple[str, str | None, list, int | None, int | None, int | None, int | None]:
        """
        Extrai o conteúdo de qualquer mensagem enviada ou encaminhada de forma 100% segura e instantânea:
        - raw_text: HTML formatado (msg.text_html, msg.caption_html, msg.text, msg.caption ou rich_message blocks)
        - photo_id: ID do arquivo de imagem se presente
        - extracted_buttons: Lista de linhas de botões (Inline Keyboard)
        - source_chat_id: ID do chat de onde a mensagem foi originada (canal ou chat privado)
        - source_message_id: ID da mensagem original
        - backup_chat_id: ID do chat privado como backup para copy_message
        - backup_message_id: ID da mensagem no chat privado como backup
        """
        raw_text = ""
        try:
            raw_text = msg.text_html or ""
        except Exception:
            pass
        if not raw_text:
            try:
                raw_text = msg.text or ""
            except Exception:
                pass
        if not raw_text:
            try:
                raw_text = msg.caption_html or ""
            except Exception:
                pass
        if not raw_text:
            try:
                raw_text = msg.caption or ""
            except Exception:
                pass

        photo_id = None
        try:
            if msg.photo:
                photo_id = msg.photo[-1].file_id
        except Exception:
            pass

        backup_chat_id = msg.chat.id if msg.chat else None
        backup_message_id = msg.message_id

        # 1. Detecta origem encaminhada (seja via novo forward_origin do Bot API 7.0+ ou forward_from_chat antigo)
        fwd_origin = getattr(msg, "forward_origin", None)
        fwd_chat_id = None
        fwd_msg_id = None
        try:
            if fwd_origin:
                c = getattr(fwd_origin, "chat", None)
                if c:
                    fwd_chat_id = c.id
                    fwd_msg_id = getattr(fwd_origin, "message_id", None)
            else:
                legacy_fwd = getattr(msg, "forward_from_chat", None)
                if legacy_fwd:
                    fwd_chat_id = getattr(legacy_fwd, "id", None)
                    fwd_msg_id = getattr(msg, "forward_from_message_id", None)
        except Exception:
            pass

        is_forwarded = bool(fwd_chat_id and fwd_msg_id and isinstance(fwd_chat_id, int) and fwd_chat_id < 0)
        source_chat_id = fwd_chat_id if is_forwarded else None
        source_message_id = fwd_msg_id if is_forwarded else None
        backup_chat_id = (msg.chat.id if msg.chat else None) if is_forwarded else None
        backup_message_id = msg.message_id if is_forwarded else None

        # 2. Se raw_text estiver vazio, tenta link_preview_options
        if not raw_text:
            try:
                lpo = getattr(msg, "link_preview_options", None)
                if lpo and getattr(lpo, "url", None):
                    raw_text = lpo.url
            except Exception:
                pass

        # 3. Se ainda assim estiver vazio, tenta extrair de blocos internos
        if not raw_text:
            try:
                d = msg.to_dict() if hasattr(msg, "to_dict") else {}
                rich = d.get("rich_message") or getattr(msg, "api_kwargs", {}).get("rich_message") or {}
                blocks = rich.get("blocks", [])
                texts = []
                for b in blocks:
                    if isinstance(b, dict):
                        if "text" in b:
                            texts.append(b["text"])
                        elif "caption" in b:
                            texts.append(b["caption"])
                if texts:
                    raw_text = "\n\n".join(texts)
            except Exception:
                pass

        # 4. Garante que raw_text nunca fique vazio
        if not raw_text:
            raw_text = "📢 Postagem da Comunidade"

        extracted_buttons = []

        # 5. Tenta obter botões diretamente do reply_markup da mensagem (se presente)
        try:
            if msg.reply_markup and getattr(msg.reply_markup, "inline_keyboard", None):
                for row in msg.reply_markup.inline_keyboard:
                    row_btns = []
                    for btn in row:
                        cb = getattr(btn, "callback_data", None)
                        if cb:
                            row_btns.append({"text": btn.text, "callback_data": cb})
                            continue
                        url = getattr(btn, "url", None)
                        if not url and getattr(btn, "web_app", None):
                            url = getattr(btn.web_app, "url", None)
                        if not url and getattr(btn, "login_url", None):
                            url = getattr(btn.login_url, "url", None)
                        if url:
                            row_btns.append({"text": btn.text, "url": url})
                    if row_btns:
                        extracted_buttons.append(row_btns)
        except Exception:
            pass

        # 6. Tenta extrair botões da sintaxe textual ([Texto - Link] ou [Texto](buttonurl:Link) ou Texto | Link)
        if not extracted_buttons and raw_text:
            try:
                parsed = self._parse_buttons(raw_text)
                if parsed:
                    extracted_buttons = parsed
                    lines = raw_text.split("\n")
                    clean_lines = [l for l in lines if not self._parse_buttons(l)]
                    raw_text = "\n".join(clean_lines).strip()
            except Exception:
                pass

        return raw_text, photo_id, extracted_buttons, source_chat_id, source_message_id, backup_chat_id, backup_message_id


    async def handle_pending_input(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
        """Intercepta entradas de administradores de forma resiliente, garantindo que o bot nunca fique mudo."""
        try:
            return await self._handle_pending_input_internal(update, context)
        except Exception as e:
            logger.error(f"Erro em handle_pending_input: {e}", exc_info=True)
            msg = update.effective_message
            if msg:
                try:
                    await msg.reply_text(
                        f"⚠️ Ocorreu um erro ao processar sua entrada: {e}\nPor favor envie novamente ou digite /cancelar."
                    )
                except Exception:
                    pass
            return True


    async def handle_unsolicited_private_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Oferece menu interativo quando o usuário envia mensagem no privado sem ação prévia."""
        msg = update.effective_message
        user = update.effective_user
        if not msg or not user:
            return
        if not await self._require_admin(update):
            return

        try:
            raw_text, photo_id, extracted_buttons, src_chat_id, src_msg_id, bak_chat_id, bak_msg_id = await self._extract_message_content(msg, context, user.id)

            self.last_received_private_messages[user.id] = {
                "text": raw_text,
                "photo": photo_id,
                "buttons": extracted_buttons,
                "source_chat_id": src_chat_id,
                "source_message_id": src_msg_id,
                "backup_chat_id": bak_chat_id,
                "backup_message_id": bak_msg_id
            }

            kb = [
                [InlineKeyboardButton("⏱️ Salvar como Mensagem Programada #1", callback_data="cfg:quick_save_rec:1")],
                [InlineKeyboardButton("👋 Salvar como Boas-Vindas", callback_data="cfg:quick_save_welcome")],
                [InlineKeyboardButton("⚙️ Abrir Painel de Configurações", callback_data="cfg:page:1")]
            ]
            prompt = (
                "📥 *Postagem Recebida no Chat Privado!*\n\n"
                "Identifiquei o envio da sua mensagem com formato enriquecido / botões.\n"
                "👉 *Escolha abaixo o que deseja fazer com ela:*"
            )
            try:
                await msg.reply_text(prompt, reply_markup=InlineKeyboardMarkup(kb), parse_mode=ParseMode.MARKDOWN)
            except Exception:
                await msg.reply_text("📥 Postagem recebida! Escolha o que deseja fazer com ela:", reply_markup=InlineKeyboardMarkup(kb))
        except Exception as e_unsol:
            logger.error(f"Erro ao tratar mensagem privada não solicitada: {e_unsol}")


    async def _handle_pending_input_internal(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
        """Processamento interno das entradas pendentes."""
        user = update.effective_user
        msg = update.effective_message
        if not user or not msg or user.id not in self.pending_inputs:
            return False

        state = self.pending_inputs[user.id]
        action = state.get("action")
        cfg = load_config()

        # Cancelamento
        if msg.text and msg.text.strip().lower() in ("/cancelar", "cancelar"):
            del self.pending_inputs[user.id]
            await msg.reply_text("❌ Alteração cancelada.")
            return True

        if not await self._require_admin(update):
            await msg.reply_text("⛔ Apenas administradores podem alterar configurações.")
            return True

        # Whitelist & Links Permitidos (modules/whitelist.py)
        if await handle_whitelist_input(self, update, context):
            return True

        for matches, handler in INPUT_ROUTES:
            if matches(action):
                return await handler(self, update, context, cfg, state, action)
        return False


    def _parse_buttons(self, text: str) -> list:
        from modules.utils import parse_rich_buttons
        return parse_rich_buttons(text)

