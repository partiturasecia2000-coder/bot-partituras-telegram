from modules.panel_support import *
from .callback_routes import CALLBACK_ROUTES

class CallbacksMixin:
    async def handle_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Processa os cliques nos botões do painel interativo."""
        query = update.callback_query
        if not query or not query.data:
            return

        chat = update.effective_chat
        user = update.effective_user
        data = query.data

        if not await self._require_admin(update):
            await query.answer("⛔ Apenas administradores podem usar estes botões.", show_alert=True)
            return

        cfg = load_config()
        title = chat.title or "Grupo"

        # Delega callbacks de Boas-Vindas para modules/welcome_ui.py
        if await handle_welcome_callback(self, update, context):
            return

        # Delega callbacks de Whitelist & Links Permitidos para modules/whitelist.py
        if await handle_whitelist_callback(self, update, context):
            return

        for matches, handler in CALLBACK_ROUTES:
            if matches(data):
                await handler(self, update, context, cfg, title)
                return

        await query.answer()
