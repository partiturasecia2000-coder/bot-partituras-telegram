import logging
import re
import time
import asyncio
import copy
import math
from datetime import datetime, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode
from telegram.ext import ContextTypes
from config import (
    load_config,
    save_config,
    get_timezone,
    get_timezone_label,
    set_timezone,
    cycle_timezone,
    TIMEZONE_LIST,
    remove_linked_group,
    remove_linked_channel
)
from modules.welcome_ui import (
    generate_welcome_groups_selector,
    generate_sub_welcome,
    generate_sub_welcome_time,
    handle_welcome_callback,
    handle_welcome_input
)
from modules.whitelist import (
    generate_whitelist_hub,
    generate_whitelist_users_page,
    generate_allowed_links_page,
    handle_whitelist_callback,
    handle_whitelist_input
)
from modules.utils import AdminCache, make_disabled_button
from modules.youtube_notifier import (
    add_youtube_channel,
    remove_youtube_channel,
    send_youtube_test_card,
    fetch_youtube_channel_videos
)
from modules.backup_manager import (
    generate_sub_backup,
    send_daily_backup,
    send_weekly_report
)
from modules.recurring import (
    format_interval,
    format_interval_display,
    format_cronograma_display,
    format_weekdays_display,
    format_month_days_display,
    format_autodel_display,
    send_single_recurring_message
)
from modules.auto_responder import validate_regex
from modules.logger_channel import send_mod_log

logger = logging.getLogger("PanelModule")


PUNISHMENT_INFO = {
    "warn": ("⚠️ Só Aviso", "Apaga a mensagem e envia aviso temporário"),
    "warning": ("❗ Só Advertência", "Apaga e conta advertência (1/3, 2/3 -> Ban ao atingir 3)"),
    "ban": ("🔨 Ban Imediato", "Apaga a mensagem e bane o infrator na mesma hora")
}

PUNISHMENT_CYCLE = ["warn", "warning", "ban"]

DELAY_PRESETS = [0, 2, 5, 10, 30]


from modules.panel_views import *
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
        if chat.type == "private":
            return True
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

