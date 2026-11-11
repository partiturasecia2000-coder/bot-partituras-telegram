from modules.panel_support import *

from modules.panel_handlers.state import PersistentPendingInputs
from modules.panel_handlers.broadcast import BroadcastMixin
from modules.panel_handlers.inputs import InputsMixin
from modules.panel_handlers.callbacks import CallbacksMixin

class InteractivePanelHandler(BroadcastMixin, InputsMixin, CallbacksMixin):
    def __init__(self, admin_cache: AdminCache, auto_responder_handler=None):
        self.admin_cache = admin_cache
        self.auto_responder_handler = auto_responder_handler
        self.last_received_private_messages = {}
        self.wizard_states = {}
        cfg = load_config()
        stored = {int(k): v for k, v in cfg.get("_pending_inputs", {}).items() if str(k).lstrip('-').isdigit() or isinstance(k, int)}
        self.pending_inputs = PersistentPendingInputs(self, stored)


    def _save_pending_inputs(self):
        try:
            cfg = load_config()
            cfg["_pending_inputs"] = {str(k): v for k, v in self.pending_inputs.items()}
            save_config(cfg)
        except Exception as e:
            logger.debug(f"Erro ao salvar _pending_inputs: {e}")


    async def _require_admin(self, update: Update) -> bool:
        chat = update.effective_chat
        user = update.effective_user
        if not chat or not user:
            return False
        return await self.admin_cache.is_admin(chat, user.id)


    async def cmd_config(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Envia o menu interativo de configurações."""
        chat = update.effective_chat
        if not await self._require_admin(update):
            await update.effective_message.reply_text("⛔ Este menu é exclusivo para administradores.")
            return

        cfg = load_config()
        title = chat.title or "Chat Privado"
        text, markup = generate_page_1(title, cfg)

        try:
            await update.effective_message.reply_text(
                text=text,
                reply_markup=markup,
                parse_mode=ParseMode.MARKDOWN
            )
        except Exception:
            await update.effective_message.reply_text(text=text, reply_markup=markup)


    async def cmd_cancelar(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Cancela qualquer edição pendente ou assistente de transmissão."""
        user = update.effective_user
        cancelled = False
        if user and user.id in self.wizard_states:
            self.wizard_states.pop(user.id, None)
            cancelled = True
        if user and user.id in self.pending_inputs:
            del self.pending_inputs[user.id]
            self._save_pending_inputs()
            cancelled = True
        if cancelled:
            await update.effective_message.reply_text("❌ Ação cancelada.")
        else:
            await update.effective_message.reply_text("Nenhuma ação pendente para cancelar.")


    async def preview_welcome(self, update: Update, context: ContextTypes.DEFAULT_TYPE, group_id: str = "general"):
        chat = update.effective_chat
        user = update.effective_user
        cfg = load_config()

        from config import get_welcome_for_chat
        target_cid = None if group_id in ("general", "0", "") else group_id
        w = get_welcome_for_chat(cfg, target_cid)

        target_chat = chat
        if target_cid:
            g_item = next((g for g in cfg.get("linked_groups", []) if str(g.get("id")) == str(target_cid)), None)
            if g_item:
                class FakeChat:
                    def __init__(self, cid, title):
                        self.id = cid
                        self.title = title
                        self.type = "supergroup"
                target_chat = FakeChat(int(target_cid) if (target_cid.startswith("-") or target_cid.isdigit()) else chat.id, g_item.get("title", "Grupo"))

        from modules.utils import format_placeholders, build_rich_buttons_markup
        template = w.get("message", "👋 Seja bem-vindo(a), {name} ao grupo *{group}*!")
        formatted_msg = format_placeholders(template, user, target_chat, cfg)

        markup = build_rich_buttons_markup(w.get("buttons", []))
        photo = w.get("photo")
        article_url = w.get("article_url")

        from telegram import LinkPreviewOptions
        lpo = None
        if article_url:
            lpo = LinkPreviewOptions(url=article_url, show_above_text=True, is_disabled=False)
        else:
            lpo = LinkPreviewOptions(show_above_text=True)

        from modules.utils import smart_send_message, smart_send_photo
        if photo:
            await smart_send_photo(bot=context.bot, chat_id=chat.id, photo=photo, caption=formatted_msg, reply_markup=markup)
        else:
            await smart_send_message(bot=context.bot, chat_id=chat.id, text=formatted_msg, reply_markup=markup, link_preview_options=lpo)

