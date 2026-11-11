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

        # Fechar painel
        if data == "cfg:close":
            await query.answer("Configurações salvas!")
            try:
                await query.edit_message_text(
                    "✅ *Painel de Configurações Concluído!*\nTodas as alterações estão salvas e ativas.",
                    parse_mode=ParseMode.MARKDOWN
                )
            except Exception:
                await query.edit_message_text("✅ Painel concluído! Alterações salvas.")
            return

        # Acervo Musical (Inline)
        if data == "cfg:sub:acervo":
            await query.answer()
            from modules.inline_acervo import generate_acervo_dashboard_text_and_kb
            text, markup = generate_acervo_dashboard_text_and_kb()
            await query.edit_message_text(text, reply_markup=markup, parse_mode=ParseMode.HTML)
            return

        # Fuso Horário - Submenu & Ações
        if data == "cfg:sub:timezone":
            await query.answer()
            text, markup = generate_sub_timezone(cfg)
            await query.edit_message_text(text, reply_markup=markup, parse_mode=ParseMode.MARKDOWN)
            return

        if data.startswith("cfg:set:tz:"):
            tz_name = data[len("cfg:set:tz:"):]
            from config import set_timezone, get_timezone_label
            set_timezone(cfg, tz_name)
            await query.answer(f"Fuso alterado para: {get_timezone_label(cfg)}!")
            text, markup = generate_sub_timezone(cfg)
            await query.edit_message_text(text, reply_markup=markup, parse_mode=ParseMode.MARKDOWN)
            return

        if data == "cfg:input:tz":
            self.pending_inputs[user.id] = {"action": "custom_timezone", "chat_id": chat.id}
            await query.answer()
            prompt = (
                "🕒 *Digite o Nome do Fuso Horário (Formato IANA):*\n\n"
                "Exemplos:\n"
                "• `America/Sao_Paulo`\n"
                "• `America/Manaus`\n"
                "• `America/Fortaleza`\n"
                "• `America/Belem`\n"
                "• `America/Cuiaba`\n"
                "• `America/Rio_Branco`\n"
                "• `Europe/Lisbon`\n"
                "• `UTC`\n\n"
                "_Envie o nome agora (ou digite /cancelar):_"
            )
            await chat.send_message(prompt, parse_mode=ParseMode.MARKDOWN)
            return

        if data == "cfg:cycle:timezone":
            new_tz = cycle_timezone(cfg)
            tz_lbl = get_timezone_label(cfg)
            await query.answer(f"Fuso horário alterado para: {tz_lbl}")
            # Atualiza a página onde o usuário estava
            text, markup = generate_page_2(title, cfg)
            await query.edit_message_text(text, reply_markup=markup, parse_mode=ParseMode.MARKDOWN)
            return

        # Auto-Apagar Boas-Vindas - Submenu & Ações
        if data.startswith("cfg:sub:wtime:"):
            gid = data.split(":")[-1] if len(data.split(":")) > 3 else "general"
            try:
                await query.answer()
            except Exception:
                pass
            text, markup = generate_sub_welcome_time(cfg, gid)
            try:
                await query.edit_message_text(text, reply_markup=markup, parse_mode=ParseMode.HTML)
            except Exception:
                try:
                    await query.edit_message_text(text, reply_markup=markup)
                except Exception:
                    pass
            return

        if data.startswith("cfg:set:wtime:"):
            parts = data.split(":")
            val1 = parts[3] if len(parts) > 3 else "general"
            val2 = parts[4] if len(parts) > 4 else "60"

            if val1 == "general":
                gid = "general"
                try:
                    sec = int(val2)
                except Exception:
                    sec = 60
            elif val2 == "general":
                gid = "general"
                try:
                    sec = int(val1)
                except Exception:
                    sec = 60
            else:
                try:
                    n1 = int(val1)
                    n2 = int(val2)
                    if n1 < 0:
                        gid = str(n1)
                        sec = n2
                    elif n2 < 0:
                        gid = str(n2)
                        sec = n1
                    elif n1 in (0, 30, 60, 120, 300, 600, 900, 1800, 3600) or (n1 <= 86400 < n2):
                        sec = n1
                        gid = str(n2)
                    else:
                        gid = str(n1)
                        sec = n2
                except Exception:
                    gid = val1
                    try:
                        sec = int(val2)
                    except Exception:
                        sec = 60

            if gid in ("general", "0", ""):
                cfg.setdefault("welcome", {})["delete_welcome_after_seconds"] = sec
            else:
                from config import get_welcome_for_chat
                w_grp = cfg.setdefault("group_welcomes", {}).setdefault(str(gid), dict(get_welcome_for_chat(cfg, gid)))
                w_grp["delete_welcome_after_seconds"] = sec
            save_config(cfg)
            lbl = format_time_label(sec)
            desc = "nunca apagar" if sec == 0 else f"apagar após {lbl}"
            try:
                await query.answer(f"Tempo definido: {desc}!", show_alert=False)
            except Exception:
                pass
            text, markup = generate_sub_welcome_time(cfg, gid)
            try:
                await query.edit_message_text(text, reply_markup=markup, parse_mode=ParseMode.HTML)
            except Exception:
                try:
                    await query.edit_message_text(text, reply_markup=markup)
                except Exception:
                    pass
            return

        if data.startswith("cfg:input:wtime:"):
            gid = data.split(":")[-1] if len(data.split(":")) > 3 else "general"
            self.pending_inputs[user.id] = {"action": "welcome_autodel_time", "group_id": gid, "chat_id": chat.id}
            await query.answer()
            prompt = (
                "⏱️ *Digite o Tempo para Auto-Apagar as Boas-Vindas:*\n\n"
                "Você pode digitar de *1 minuto a 24 horas* (ou `nunca`).\n\n"
                "💡 *Exemplos:*\n"
                "• `10m` ou `10 min` ou `10` (10 minutos)\n"
                "• `30m` (30 minutos)\n"
                "• `1h` (1 hora)\n"
                "• `2h` ou `2 horas`\n"
                "• `12h` ou `24h`\n"
                "• `nunca` ou `0` (não apagar)\n\n"
                "_Envie o tempo desejado agora (ou digite /cancelar):_"
            )
            await chat.send_message(prompt, parse_mode=ParseMode.MARKDOWN)
            return

        # =============================================================
        # ASSISTENTE DE TRANSMISSÃO GUIADA (WIZARD)
        # =============================================================
        if data == "cfg:wiz:start":
            await query.answer()
            text, markup = generate_wizard_dest_menu(cfg)
            try:
                await query.edit_message_text(text, reply_markup=markup, parse_mode=ParseMode.MARKDOWN)
            except Exception:
                await query.edit_message_text(text, reply_markup=markup)
            return

        if data == "cfg:wiz:add_channel":
            self.pending_inputs[user.id] = {"action": "wiz_link_channel"}
            self._save_pending_inputs()
            await query.answer()
            prompt = (
                "📢 *Vincular Canal ao Bot:*\n\n"
                "1. Adicione o bot como *Administrador* no seu Canal com permissão de *Postar Mensagens*.\n"
                "2. Digite aqui no privado o `@username` do canal (ex: `@meucanal`) ou o ID numérico (ex: `-1001234567890`).\n\n"
                "_Envie o canal agora (ou digite /cancelar):_"
            )
            await chat.send_message(prompt, parse_mode=ParseMode.MARKDOWN)
            return

        if data.startswith("cfg:wiz:dest:"):
            target = data.replace("cfg:wiz:dest:", "")
            linked_c = cfg.get("linked_channels", [])
            if target in ("main_channel", "all_channels") and not linked_c:
                self.pending_inputs[user.id] = {"action": "wiz_link_channel"}
                self._save_pending_inputs()
                await query.answer("⚠️ Nenhum canal vinculado ao bot ainda!", show_alert=True)
                prompt = (
                    "📢 *Nenhum Canal Vinculado Ainda!*\n\n"
                    "Para o bot poder postar no seu canal:\n"
                    "1. Adicione o bot como *Administrador* no Canal com permissão de *Postar Mensagens*.\n"
                    "2. Envie aqui no privado o `@username` do canal (ex: `@meucanal`) ou o ID numérico (ex: `-1001234567890`).\n\n"
                    "_Envie o canal agora (ou digite /cancelar):_"
                )
                await chat.send_message(prompt, parse_mode=ParseMode.MARKDOWN)
                return

            state = self._get_or_create_wizard_state(user.id)
            state.update({
                "step": "text",
                "target": target,
                "text": "",
                "media_type": None,
                "media_id": None,
                "buttons": [],
                "pin": False,
                "delay_seconds": 2
            })
            self._save_wizard_state(user.id, state, next_action="wiz_text")
            dest_label = get_wizard_dest_label(target, cfg)
            text, markup = generate_wizard_text_prompt(dest_label)
            await query.answer()
            try:
                await query.edit_message_text(text, reply_markup=markup, parse_mode=ParseMode.MARKDOWN)
            except Exception:
                await query.edit_message_text(text, reply_markup=markup)
            return

        if data == "cfg:wiz:edit_text":
            state = self._get_or_create_wizard_state(user.id)
            state["step"] = "text"
            self._save_wizard_state(user.id, state, next_action="wiz_text")
            dest_label = get_wizard_dest_label(state.get("target", "main_channel"), cfg)
            text, markup = generate_wizard_text_prompt(dest_label)
            await query.answer()
            try:
                await query.edit_message_text(text, reply_markup=markup, parse_mode=ParseMode.MARKDOWN)
            except Exception:
                await query.edit_message_text(text, reply_markup=markup)
            return

        if data == "cfg:wiz:skip_media":
            state = self._get_or_create_wizard_state(user.id)
            state["media_type"] = None
            state["media_id"] = None
            state["step"] = "buttons"
            self._save_wizard_state(user.id, state, next_action="wiz_buttons")
            dest_label = get_wizard_dest_label(state.get("target", "main_channel"), cfg)
            text, markup = generate_wizard_buttons_prompt(dest_label, "⚪ Nenhuma (Somente Texto)")
            await query.answer()
            try:
                await query.edit_message_text(text, reply_markup=markup, parse_mode=ParseMode.MARKDOWN)
            except Exception:
                await query.edit_message_text(text, reply_markup=markup)
            return

        if data == "cfg:wiz:edit_media":
            state = self._get_or_create_wizard_state(user.id)
            state["step"] = "media"
            self._save_wizard_state(user.id, state, next_action="wiz_media")
            dest_label = get_wizard_dest_label(state.get("target", "main_channel"), cfg)
            text, markup = generate_wizard_media_prompt(dest_label, state.get("text", ""))
            await query.answer()
            try:
                await query.edit_message_text(text, reply_markup=markup, parse_mode=ParseMode.MARKDOWN)
            except Exception:
                await query.edit_message_text(text, reply_markup=markup)
            return

        if data == "cfg:wiz:skip_buttons":
            state = self._get_or_create_wizard_state(user.id)
            state["buttons"] = []
            if user.id in self.pending_inputs:
                del self.pending_inputs[user.id]
                self._save_pending_inputs()
            self._save_wizard_state(user.id, state)
            await query.answer()
            await self.show_wizard_preview(update, context, state, user.id)
            return

        if data == "cfg:wiz:edit_buttons":
            state = self._get_or_create_wizard_state(user.id)
            state["step"] = "buttons"
            self._save_wizard_state(user.id, state, next_action="wiz_buttons")
            dest_label = get_wizard_dest_label(state.get("target", "main_channel"), cfg)
            media_label = "🎥 Vídeo" if state.get("media_type") == "video" else ("🖼️ Foto" if state.get("media_type") == "photo" else "⚪ Nenhuma")
            text, markup = generate_wizard_buttons_prompt(dest_label, media_label)
            await query.answer()
            try:
                await query.edit_message_text(text, reply_markup=markup, parse_mode=ParseMode.MARKDOWN)
            except Exception:
                await query.edit_message_text(text, reply_markup=markup)
            return

        if data == "cfg:wiz:toggle_pin":
            state = self._get_or_create_wizard_state(user.id)
            state["pin"] = not state.get("pin", False)
            self._save_wizard_state(user.id, state)
            dest_label = get_wizard_dest_label(state.get("target", "main_channel"), cfg)
            media_label = "🎥 Vídeo" if state.get("media_type") == "video" else ("🖼️ Foto" if state.get("media_type") == "photo" else "⚪ Nenhuma")
            btns = state.get("buttons", [])
            btns_count = sum(len(r) for r in btns) if (btns and isinstance(btns[0], list)) else len(btns)
            delay_sec = state.get("delay_seconds", 2)
            ctrl_text, ctrl_markup = generate_wizard_preview_controls(dest_label, media_label, btns_count, state["pin"], delay_sec)
            await query.answer(f"Fixar no topo: {'Ativado 📌' if state['pin'] else 'Desativado'}")
            try:
                await query.edit_message_text(ctrl_text, reply_markup=ctrl_markup, parse_mode=ParseMode.MARKDOWN)
            except Exception:
                await query.edit_message_text(ctrl_text, reply_markup=ctrl_markup)
            return

        if data == "cfg:wiz:toggle_delay":
            state = self._get_or_create_wizard_state(user.id)
            cur_delay = state.get("delay_seconds", 2)
            presets = [0, 2, 5, 10, 30]
            idx = presets.index(cur_delay) if cur_delay in presets else 0
            new_delay = presets[(idx + 1) % len(presets)]
            state["delay_seconds"] = new_delay
            self._save_wizard_state(user.id, state)
            dest_label = get_wizard_dest_label(state.get("target", "main_channel"), cfg)
            media_label = "🎥 Vídeo" if state.get("media_type") == "video" else ("🖼️ Foto" if state.get("media_type") == "photo" else "⚪ Nenhuma")
            btns = state.get("buttons", [])
            btns_count = sum(len(r) for r in btns) if (btns and isinstance(btns[0], list)) else len(btns)
            ctrl_text, ctrl_markup = generate_wizard_preview_controls(dest_label, media_label, btns_count, state.get("pin", False), new_delay)
            await query.answer(f"Distribuição: {get_delay_label(new_delay)}")
            try:
                await query.edit_message_text(ctrl_text, reply_markup=ctrl_markup, parse_mode=ParseMode.MARKDOWN)
            except Exception:
                await query.edit_message_text(ctrl_text, reply_markup=ctrl_markup)
            return

        if data == "cfg:wiz:sched_menu":
            state = self.wizard_states.get(user.id, {})
            text, markup = generate_wizard_schedule_menu(cfg, state)
            await query.answer()
            try:
                await query.edit_message_text(text, reply_markup=markup, parse_mode=ParseMode.MARKDOWN)
            except Exception:
                await query.edit_message_text(text, reply_markup=markup)
            return

        if data == "cfg:wiz:back_preview":
            state = self.wizard_states.get(user.id, {})
            dest_label = get_wizard_dest_label(state.get("target", "main_channel"), cfg)
            media_label = "🎥 Vídeo" if state.get("media_type") == "video" else ("🖼️ Foto" if state.get("media_type") == "photo" else "⚪ Nenhuma")
            btns = state.get("buttons", [])
            btns_count = sum(len(r) for r in btns) if (btns and isinstance(btns[0], list)) else len(btns)
            delay_sec = state.get("delay_seconds", 2)
            ctrl_text, ctrl_markup = generate_wizard_preview_controls(dest_label, media_label, btns_count, state.get("pin", False), delay_sec)
            await query.answer()
            try:
                await query.edit_message_text(ctrl_text, reply_markup=ctrl_markup, parse_mode=ParseMode.MARKDOWN)
            except Exception:
                await query.edit_message_text(ctrl_text, reply_markup=ctrl_markup)
            return

        if data.startswith("cfg:wiz:set_rel:"):
            mins = int(data.split(":")[-1])
            state = self.wizard_states.get(user.id, {})
            from config import get_timezone
            tz = get_timezone(cfg)
            target_dt = datetime.now(tz) + timedelta(minutes=mins)
            await query.answer("⏰ Agendando...")
            await self.save_scheduled_transmission(update, context, state, user.id, target_dt)
            return

        if data.startswith("cfg:wiz:set_time:"):
            tspec = data.replace("cfg:wiz:set_time:", "")
            state = self.wizard_states.get(user.id, {})
            from config import get_timezone
            tz = get_timezone(cfg)
            now_dt = datetime.now(tz)
            if tspec == "tomorrow_09:00":
                target_dt = (now_dt + timedelta(days=1)).replace(hour=9, minute=0, second=0, microsecond=0)
            else:
                h, m = map(int, tspec.split(":"))
                cand = now_dt.replace(hour=h, minute=m, second=0, microsecond=0)
                if cand <= now_dt:
                    cand += timedelta(days=1)
                target_dt = cand
            await query.answer("⏰ Agendando...")
            await self.save_scheduled_transmission(update, context, state, user.id, target_dt)
            return

        if data == "cfg:wiz:set_custom":
            state = self.wizard_states.get(user.id, {})
            self.pending_inputs[user.id] = {"action": "wiz_sched_custom", "state": state}
            await query.answer()
            prompt = (
                "🕒 *Digite a Data e Hora para o Agendamento:*\n\n"
                "💡 *Exemplos válidos:*\n"
                "• `18:30` ou `20:00` (hoje ou amanhã se já tiver passado)\n"
                "• `18/10 14:00` (dia/mês hora:minuto)\n"
                "• `30m` ou `2h` (daqui a 30 minutos ou 2 horas)\n\n"
                "_Envie a data/hora agora (ou digite /cancelar):_"
            )
            await chat.send_message(prompt, parse_mode=ParseMode.MARKDOWN)
            return

        # Gerenciamento de Transmissões Agendadas
        if data == "cfg:sched:list":
            await query.answer()
            text, markup = generate_scheduled_transmissions_menu(cfg)
            try:
                await query.edit_message_text(text, reply_markup=markup, parse_mode=ParseMode.MARKDOWN)
            except Exception:
                await query.edit_message_text(text, reply_markup=markup)
            return

        if data.startswith("cfg:sched:cancel:"):
            item_id = int(data.split(":")[-1])
            sched_list = cfg.get("scheduled_transmissions", [])
            item = next((x for x in sched_list if x.get("id") == item_id), None)
            if item:
                item["status"] = "cancelled"
                save_config(cfg)
                await query.answer("🗑️ Agendamento cancelado!", show_alert=True)
            else:
                await query.answer("⚠️ Agendamento não encontrado.", show_alert=True)
            text, markup = generate_scheduled_transmissions_menu(cfg)
            try:
                await query.edit_message_text(text, reply_markup=markup, parse_mode=ParseMode.MARKDOWN)
            except Exception:
                await query.edit_message_text(text, reply_markup=markup)
            return

        if data.startswith("cfg:sched:fire:"):
            item_id = int(data.split(":")[-1])
            sched_list = cfg.get("scheduled_transmissions", [])
            item = next((x for x in sched_list if x.get("id") == item_id), None)
            if item and item.get("status") == "pending":
                item["status"] = "sending"
                save_config(cfg)
                from modules.recurring import _execute_scheduled_transmission
                asyncio.create_task(_execute_scheduled_transmission(context.bot, item))
                await query.answer("🚀 Transmissão disparada imediatamente!", show_alert=True)
            else:
                await query.answer("⚠️ Transmissão já executada ou cancelada.", show_alert=True)
            text, markup = generate_scheduled_transmissions_menu(cfg)
            try:
                await query.edit_message_text(text, reply_markup=markup, parse_mode=ParseMode.MARKDOWN)
            except Exception:
                await query.edit_message_text(text, reply_markup=markup)
            return

        if data == "cfg:wiz:send":
            await query.answer("🚀 Enviando transmissão...")
            await self.execute_wizard_send(update, context, user.id)
            return

        if data == "cfg:wiz:cancel":
            self.wizard_states.pop(user.id, None)
            if user.id in self.pending_inputs:
                del self.pending_inputs[user.id]
                self._save_pending_inputs()
            await query.answer("Transmissão cancelada.")
            text, markup = generate_page_1(title, cfg)
            try:
                await query.edit_message_text(text, reply_markup=markup, parse_mode=ParseMode.MARKDOWN)
            except Exception:
                await query.edit_message_text(text, reply_markup=markup)
            return

        # Navegação de Centrais Temáticas (Hubs) e Painel Principal
        if data == "cfg:page:1":
            await query.answer()
            text, markup = generate_page_1(title, cfg)
            await query.edit_message_text(text, reply_markup=markup, parse_mode=ParseMode.MARKDOWN)
            return

        if data == "cfg:page:2":
            await query.answer()
            text, markup = generate_hub_system(cfg)
            await query.edit_message_text(text, reply_markup=markup, parse_mode=ParseMode.MARKDOWN)
            return

        if data == "cfg:hub:clean":
            await query.answer()
            text, markup = generate_hub_clean(cfg)
            await query.edit_message_text(text, reply_markup=markup, parse_mode=ParseMode.MARKDOWN)
            return

        if data == "cfg:hub:security":
            await query.answer()
            text, markup = generate_hub_security(cfg)
            await query.edit_message_text(text, reply_markup=markup, parse_mode=ParseMode.MARKDOWN)
            return

        if data == "cfg:hub:welcome":
            await query.answer()
            text, markup = generate_hub_welcome(cfg)
            await query.edit_message_text(text, reply_markup=markup, parse_mode=ParseMode.MARKDOWN)
            return

        if data == "cfg:hub:messages":
            await query.answer()
            text, markup = generate_hub_messages(cfg)
            await query.edit_message_text(text, reply_markup=markup, parse_mode=ParseMode.MARKDOWN)
            return

        if data == "cfg:hub:system":
            await query.answer()
            text, markup = generate_hub_system(cfg)
            await query.edit_message_text(text, reply_markup=markup, parse_mode=ParseMode.MARKDOWN)
            return

        if data == "cfg:sub:clean_help":
            await query.answer()
            text, markup = generate_sub_clean_help()
            await query.edit_message_text(text, reply_markup=markup, parse_mode=ParseMode.MARKDOWN)
            return

        # Sub-menus padrões
        if data == "cfg:sub:rules":
            await query.answer()
            text, markup = generate_sub_rules(cfg)
            await query.edit_message_text(text, reply_markup=markup, parse_mode=ParseMode.MARKDOWN)
            return

        # Submenu YouTube Notifier
        if data == "cfg:sub:youtube":
            await query.answer()
            text, markup = generate_sub_youtube(cfg)
            await query.edit_message_text(text, reply_markup=markup, parse_mode=ParseMode.MARKDOWN)
            return

        if data == "cfg:toggle:youtube":
            yt_cfg = cfg.setdefault("youtube_notifications", {
                "enabled": True, "target_chat": "@partiturasecia", "check_interval_minutes": 5, "channels": []
            })
            yt_cfg["enabled"] = not yt_cfg.get("enabled", True)
            save_config(cfg)
            await query.answer("Status do Notificador do YouTube alterado!")
            text, markup = generate_sub_youtube(cfg)
            await query.edit_message_text(text, reply_markup=markup, parse_mode=ParseMode.MARKDOWN)
            return

        if data == "cfg:youtube:add":
            await query.answer()
            self.pending_inputs[user.id] = {"action": "youtube_add"}
            prompt = (
                "🎬 <b>Adicionar Canal do YouTube</b>\n\n"
                "Envie o <b>@handle</b> ou o <b>link do canal</b> que você deseja monitorar.\n\n"
                "<i>Exemplos aceitos:</i>\n"
                "• <code>@NomeDoCanal</code>\n"
                "• <code>https://www.youtube.com/@NomeDoCanal</code>\n"
                "• <code>https://www.youtube.com/channel/UC...</code>\n\n"
                "Envie agora ou digite /cancelar:"
            )
            await query.message.reply_text(prompt, parse_mode=ParseMode.HTML)
            return

        if data == "cfg:youtube:del":
            await query.answer()
            text, markup = generate_sub_youtube_delete(cfg)
            await query.edit_message_text(text, reply_markup=markup, parse_mode=ParseMode.MARKDOWN)
            return

        if data.startswith("cfg:youtube:rm:"):
            await query.answer()
            idx_str = data.split(":")[-1]
            success, msg = remove_youtube_channel(cfg, idx_str)
            cfg = load_config()
            text, markup = generate_sub_youtube_delete(cfg)
            try:
                await query.edit_message_text(text, reply_markup=markup, parse_mode=ParseMode.MARKDOWN)
            except Exception:
                pass
            return

        if data == "cfg:youtube:target":
            await query.answer()
            self.pending_inputs[user.id] = {"action": "youtube_target"}
            cur_target = cfg.get("youtube_notifications", {}).get("target_chat", "@partiturasecia")
            prompt = (
                "🎯 <b>Definir Grupo Destino do YouTube</b>\n\n"
                f"Destino atual configurado: <code>{cur_target}</code>\n\n"
                "Envie o @username do grupo (ex: <code>@partiturasecia</code>) ou o ID numérico do chat (ex: <code>-100...</code>).\n\n"
                "Envie agora ou digite /cancelar:"
            )
            await query.message.reply_text(prompt, parse_mode=ParseMode.HTML)
            return

        if data == "cfg:youtube:test":
            await query.answer("Enviando card de teste...")
            target = cfg.get("youtube_notifications", {}).get("target_chat") or cfg.get("main_group_id") or "@partiturasecia"
            ok, res_msg = await send_youtube_test_card(context.bot, target, cfg)
            if ok:
                await query.message.reply_text(f"🚀 {res_msg}", parse_mode=ParseMode.HTML)
            else:
                await query.message.reply_text(f"⚠️ {res_msg}", parse_mode=ParseMode.HTML)
            return

        # Submenu Backups & Relatórios
        if data == "cfg:sub:backup":
            await query.answer()
            text, markup = generate_sub_backup(cfg)
            await query.edit_message_text(text, reply_markup=markup, parse_mode=ParseMode.MARKDOWN)
            return

        if data == "cfg:toggle:daily_bkp":
            b_cfg = cfg.setdefault("backup_system", {
                "enabled": True, "channel_id": -1004462851433,
                "daily_backup_enabled": True, "daily_backup_interval_hours": 24,
                "last_daily_backup_timestamp": 0, "weekly_report_enabled": True,
                "weekly_report_interval_days": 7, "last_weekly_report_timestamp": 0
            })
            b_cfg["daily_backup_enabled"] = not b_cfg.get("daily_backup_enabled", True)
            save_config(cfg)
            await query.answer("Status do Backup Diário alterado!")
            text, markup = generate_sub_backup(cfg)
            await query.edit_message_text(text, reply_markup=markup, parse_mode=ParseMode.MARKDOWN)
            return

        if data == "cfg:toggle:weekly_rep":
            b_cfg = cfg.setdefault("backup_system", {
                "enabled": True, "channel_id": -1004462851433,
                "daily_backup_enabled": True, "daily_backup_interval_hours": 24,
                "last_daily_backup_timestamp": 0, "weekly_report_enabled": True,
                "weekly_report_interval_days": 7, "last_weekly_report_timestamp": 0
            })
            b_cfg["weekly_report_enabled"] = not b_cfg.get("weekly_report_enabled", True)
            save_config(cfg)
            await query.answer("Status do Relatório Semanal alterado!")
            text, markup = generate_sub_backup(cfg)
            await query.edit_message_text(text, reply_markup=markup, parse_mode=ParseMode.MARKDOWN)
            return

        if data == "cfg:bkp:now":
            await query.answer("Gerando e enviando arquivo ZIP de backup...")
            b_channel = cfg.get("backup_system", {}).get("channel_id", -1004462851433)
            ok, res_msg = await send_daily_backup(context.bot, b_channel, is_manual=True)
            if ok:
                await query.message.reply_text(f"💾 {res_msg}", parse_mode=ParseMode.HTML)
            else:
                await query.message.reply_text(f"⚠️ {res_msg}", parse_mode=ParseMode.HTML)
            cfg = load_config()
            text, markup = generate_sub_backup(cfg)
            try:
                await query.edit_message_text(text, reply_markup=markup, parse_mode=ParseMode.MARKDOWN)
            except Exception:
                pass
            return

        if data == "cfg:rep:now":
            await query.answer("Gerando e enviando relatório semanal...")
            b_channel = cfg.get("backup_system", {}).get("channel_id", -1004462851433)
            ok, res_msg = await send_weekly_report(context.bot, b_channel, is_manual=True)
            if ok:
                await query.message.reply_text(f"📊 {res_msg}", parse_mode=ParseMode.HTML)
            else:
                await query.message.reply_text(f"⚠️ {res_msg}", parse_mode=ParseMode.HTML)
            cfg = load_config()
            text, markup = generate_sub_backup(cfg)
            try:
                await query.edit_message_text(text, reply_markup=markup, parse_mode=ParseMode.MARKDOWN)
            except Exception:
                pass
            return

        if data == "cfg:bkp:channel":
            await query.answer()
            self.pending_inputs[user.id] = {"action": "backup_channel"}
            cur_ch = cfg.get("backup_system", {}).get("channel_id", -1004462851433)
            prompt = (
                "🎯 <b>Definir Canal de Backup & Relatórios</b>\n\n"
                f"Canal atual configurado: <code>{cur_ch}</code>\n\n"
                "Envie o ID numérico do canal (ex: <code>-1004462851433</code>) ou encaminhe uma mensagem dele.\n\n"
                "Envie agora ou digite /cancelar:"
            )
            await query.message.reply_text(prompt, parse_mode=ParseMode.HTML)
            return

        if data == "cfg:sub:cmd_clean":
            await query.answer()
            text, markup = generate_sub_cmd_clean(cfg)
            await query.edit_message_text(text, reply_markup=markup, parse_mode=ParseMode.MARKDOWN)
            return

        if data == "cfg:sub:antispam":
            await query.answer()
            text, markup = generate_sub_antispam(cfg)
            await query.edit_message_text(text, reply_markup=markup, parse_mode=ParseMode.MARKDOWN)
            return

        if data == "cfg:sub:antiflood":
            await query.answer()
            text, markup = generate_sub_antiflood(cfg)
            await query.edit_message_text(text, reply_markup=markup, parse_mode=ParseMode.MARKDOWN)
            return

        if data == "cfg:sub:banned":
            await query.answer()
            text, markup = generate_sub_banned(cfg)
            await query.edit_message_text(text, reply_markup=markup, parse_mode=ParseMode.MARKDOWN)
            return

        if data == "cfg:sub:clean":
            await query.answer()
            text, markup = generate_hub_clean(cfg)
            await query.edit_message_text(text, reply_markup=markup, parse_mode=ParseMode.MARKDOWN)
            return

        if data == "cfg:sub:logs":
            await query.answer()
            text, markup = generate_sub_logs(cfg)
            await query.edit_message_text(text, reply_markup=markup, parse_mode=ParseMode.MARKDOWN)
            return

        if data == "cfg:sub:nightmode":
            await query.answer()
            text, markup = generate_sub_nightmode(cfg)
            await query.edit_message_text(text, reply_markup=markup, parse_mode=ParseMode.MARKDOWN)
            return

        if data == "cfg:sub:docs":
            await query.answer()
            text, markup = generate_sub_docs()
            await query.edit_message_text(text, reply_markup=markup, parse_mode=ParseMode.MARKDOWN)
            return

        if data == "cfg:toggle:nightmode":
            nm = cfg.setdefault("night_mode", {})
            nm["enabled"] = not nm.get("enabled", False)
            if nm["enabled"]:
                if chat.type in ("group", "supergroup"):
                    c_list = nm.setdefault("enabled_chats", [])
                    if chat.id not in c_list:
                        c_list.append(chat.id)
                elif cfg.get("main_group_id"):
                    c_list = nm.setdefault("enabled_chats", [])
                    if cfg["main_group_id"] not in c_list:
                        c_list.append(cfg["main_group_id"])
            save_config(cfg)
            st = "Ativado" if nm["enabled"] else "Desativado"
            await query.answer(f"Modo Noturno: {st}")
            text, markup = generate_sub_nightmode(cfg)
            await query.edit_message_text(text, reply_markup=markup, parse_mode=ParseMode.MARKDOWN)
            return

        if data == "cfg:toggle:nightmode_ann":
            nm = cfg.setdefault("night_mode", {})
            cur = nm.get("announce_start", True) and nm.get("announce_end", True)
            nm["announce_start"] = not cur
            nm["announce_end"] = not cur
            save_config(cfg)
            st = "Ativados" if not cur else "Desativados"
            await query.answer(f"Avisos: {st}")
            text, markup = generate_sub_nightmode(cfg)
            await query.edit_message_text(text, reply_markup=markup, parse_mode=ParseMode.MARKDOWN)
            return

        if data in ("cfg:test:nightmode_start", "cfg:test:nightmode_end"):
            is_start = data == "cfg:test:nightmode_start"
            nm = cfg.get("night_mode", {})
            s = nm.get("start", "23:00")
            e = nm.get("end", "07:00")
            if is_start:
                txt = (
                    "🌙 *Silêncio Noturno Iniciado!*\n\n"
                    f"O Modo Noturno acabou de começar (das *{s}* às *{e}*).\n"
                    "O envio de mensagens comuns foi temporariamente pausado para mantermos o descanso e a tranquilidade de todos.\n\n"
                    "Tenham uma excelente e abençoada noite! 😴🎹✨"
                )
            else:
                txt = (
                    "☀️ *Bom Dia! Silêncio Noturno Encerrado!*\n\n"
                    f"O horário de silêncio chegou ao fim (das *{s}* às *{e}*).\n"
                    "O chat do grupo está oficialmente aberto para mensagens, novidades e partituras!\n\n"
                    "Desejamos a todos um ótimo e produtivo dia! 🎼☕✨"
                )

            # Envia para os grupos monitorados se existirem
            target_chats = set()
            main_id = cfg.get("main_group_id")
            if main_id and isinstance(main_id, int) and main_id < 0:
                target_chats.add(main_id)
            for cid in nm.get("enabled_chats", []):
                if cid and isinstance(cid, int) and cid < 0:
                    target_chats.add(cid)

            sent_count = 0
            for cid in target_chats:
                try:
                    await context.bot.send_message(chat_id=cid, text=txt, parse_mode=ParseMode.MARKDOWN)
                    sent_count += 1
                except Exception:
                    pass

            await query.answer(f"Aviso de teste disparado ({sent_count} grupo(s))!")
            if sent_count > 0:
                await chat.send_message(f"✅ Aviso de {'início' if is_start else 'término'} enviado para o(s) grupo(s)!")
            else:
                await chat.send_message(f"📢 *Prévia do aviso de {'início' if is_start else 'término'}:*\n\n{txt}\n\n💡 *Dica:* Para enviar direto ao grupo, vincule-o usando /setgrupo no grupo!", parse_mode=ParseMode.MARKDOWN)
            return

        if data == "cfg:logs:set_id":
            self.pending_inputs[user.id] = {"action": "logs_set_id", "chat_id": chat.id}
            await query.answer()
            prompt = (
                "📡 *Configurar Canal de Logs & Auditoria:*\n\n"
                "1. Crie um canal ou grupo privado no Telegram.\n"
                "2. Adicione este bot como **Administrador** lá.\n"
                "3. Envie o **ID do Canal** aqui (ex: `-1001234567890`).\n"
                "_(Para descobrir o ID, use o comando /chatinfo dentro do canal/grupo)_\n\n"
                "_Envie o ID agora ou digite /cancelar:_"
            )
            await chat.send_message(prompt, parse_mode=ParseMode.MARKDOWN)
            return

        if data == "cfg:logs:test":
            channel_id = cfg.get("log_channel_id")
            if not channel_id:
                await query.answer("Nenhum canal configurado ainda. Defina o ID primeiro!", show_alert=True)
                return
            success = await send_mod_log(
                bot=context.bot,
                event_type="config",
                title="Teste de Conexão com Canal de Logs",
                user_info=f"{user.first_name} (<code>{user.id}</code>)",
                details="O canal de logs está funcionando perfeitamente! 🚀"
            )
            if success:
                await query.answer("Log de teste enviado com sucesso!", show_alert=True)
            else:
                await query.answer("Erro ao enviar. Verifique se o bot é Admin no canal!", show_alert=True)
            return

        if data == "cfg:logs:clear":
            cfg["log_channel_id"] = None
            save_config(cfg)
            await query.answer("Canal de logs desativado!")
            text, markup = generate_sub_logs(cfg)
            await query.edit_message_text(text, reply_markup=markup, parse_mode=ParseMode.MARKDOWN)
            return

        if data.startswith("cfg:logs:toggle:"):
            ev_key = data.split(":")[-1]
            events = cfg.setdefault("log_events", {})
            events[ev_key] = not events.get(ev_key, True)
            save_config(cfg)
            status_lbl = "Ativado" if events[ev_key] else "Desativado"
            await query.answer(f"Log de {ev_key}: {status_lbl}")
            text, markup = generate_sub_logs(cfg)
            await query.edit_message_text(text, reply_markup=markup, parse_mode=ParseMode.MARKDOWN)
            return

        # -------------------------------------------------------------
        # SEÇÃO: PALAVRAS PROIBIDAS (AÇÕES INTERATIVAS)
        # -------------------------------------------------------------
        if data == "cfg:banned:cycle_action":
            cur_action = cfg.setdefault("antispam", {}).get("banned_words_action", "warn")
            idx = PUNISHMENT_CYCLE.index(cur_action) if cur_action in PUNISHMENT_CYCLE else 0
            new_action = PUNISHMENT_CYCLE[(idx + 1) % len(PUNISHMENT_CYCLE)]
            cfg["antispam"]["banned_words_action"] = new_action
            save_config(cfg)
            new_title = PUNISHMENT_INFO[new_action][0]
            await query.answer(f"Punição alterada para: {new_title}")
            text, markup = generate_sub_banned(cfg)
            await query.edit_message_text(text, reply_markup=markup, parse_mode=ParseMode.MARKDOWN)
            return

        if data == "cfg:banned:add":
            self.pending_inputs[user.id] = {"action": "banned_add", "chat_id": chat.id}
            await query.answer()
            prompt = (
                "✏️ *Adicionar Palavras Proibidas:*\n\n"
                "Envie os termos que deseja bloquear (separados por vírgula ou um por linha).\n\n"
                "Exemplo:\n"
                "`golpe, robô do pix, pirataria, hack`\n\n"
                "_Envie sua lista agora ou digite /cancelar:_"
            )
            await chat.send_message(prompt, parse_mode=ParseMode.MARKDOWN)
            return

        if data == "cfg:banned:remove":
            self.pending_inputs[user.id] = {"action": "banned_remove", "chat_id": chat.id}
            await query.answer()
            prompt = (
                "🗑️ *Remover Palavras Proibidas:*\n\n"
                "Envie os termos que deseja retirar da lista negra (separados por vírgula ou um por linha).\n\n"
                "_Envie agora ou digite /cancelar:_"
            )
            await chat.send_message(prompt, parse_mode=ParseMode.MARKDOWN)
            return

        if data == "cfg:banned:view_all":
            banned_list = cfg.get("antispam", {}).get("banned_words", [])
            await query.answer()
            if not banned_list:
                msg_text = "🔤 *Lista de Palavras Proibidas:*\n_Nenhum termo cadastrado no momento._"
            else:
                formatted = "\n".join(f"• `{w}`" for w in banned_list)
                msg_text = f"🔤 *Lista Completa de Palavras Proibidas ({len(banned_list)}):*\n\n{formatted}"

            markup = InlineKeyboardMarkup([[InlineKeyboardButton("◀ Voltar", callback_data="cfg:sub:banned")]])
            await query.edit_message_text(msg_text, reply_markup=markup, parse_mode=ParseMode.MARKDOWN)
            return

        if data == "cfg:banned:clear_all":
            cfg.setdefault("antispam", {})["banned_words"] = []
            save_config(cfg)
            await query.answer("Todas as palavras proibidas foram apagadas!")
            text, markup = generate_sub_banned(cfg)
            await query.edit_message_text(text, reply_markup=markup, parse_mode=ParseMode.MARKDOWN)
            return

        # -------------------------------------------------------------
        # SEÇÃO: MENSAGENS REPETIDAS / PROGRAMADAS (CRONOGRAMA)
        # -------------------------------------------------------------
        if data == "cfg:rec:list" or data.startswith("cfg:rec:list:"):
            parts = data.split(":")
            page = int(parts[-1]) if len(parts) >= 4 and parts[-1].isdigit() else 1
            await query.answer()
            text, markup = generate_recurring_list(title, cfg, page=page)
            try:
                await query.edit_message_text(text, reply_markup=markup, parse_mode=ParseMode.MARKDOWN)
            except Exception:
                await query.edit_message_text(text, reply_markup=markup)
            return

        if data == "cfg:noop":
            await query.answer()
            return

        if data == "cfg:rec:add" or data.startswith("cfg:rec:add:"):
            parts = data.split(":")
            page = int(parts[-1]) if len(parts) >= 4 and parts[-1].isdigit() else 1
            rec_list = cfg.setdefault("recurring_messages", [])
            new_id = (max([m.get("id", 0) for m in rec_list] or [0])) + 1
            main_target = chat.id if chat.type in ("group", "supergroup") else cfg.get("main_group_id")
            new_item = {
                "id": new_id,
                "enabled": True,
                "text": "📢 Esta é uma mensagem programada automática! Personalize este texto como desejar.",
                "photo": None,
                "buttons": [],
                "repeat_mode": "interval",
                "interval_type": "hours",
                "interval_value": 24,
                "interval_minutes": 1440,
                "messages_interval": 50,
                "messages_counter_last": 0,
                "start_hour": None,
                "start_minute": None,
                "weekdays": [0, 1, 2, 3, 4, 5, 6],
                "month_days": [],
                "start_date": None,
                "end_date": None,
                "pin_message": False,
                "delete_previous": False,
                "auto_delete_seconds": 0,
                "last_message_id": None,
                "last_sent_timestamp": 0,
                "chat_id": main_target
            }
            rec_list.append(new_item)
            save_config(cfg)
            await query.answer(f"Mensagem #{new_id} criada!")
            text, markup = generate_recurring_detail(cfg, new_id, page=page)
            await query.edit_message_text(text, reply_markup=markup, parse_mode=ParseMode.MARKDOWN)
            return

        if data.startswith("cfg:rec:detail:"):
            parts = data.split(":")
            msg_id = int(parts[3])
            page = int(parts[4]) if len(parts) > 4 and parts[4].isdigit() else 1
            await query.answer()
            text, markup = generate_recurring_detail(cfg, msg_id, page=page)
            await query.edit_message_text(text, reply_markup=markup, parse_mode=ParseMode.MARKDOWN)
            return

        if data.startswith("cfg:rec:toggle:"):
            parts = data.split(":")
            msg_id = int(parts[3])
            page = int(parts[4]) if len(parts) > 4 and parts[4].isdigit() else None
            rec_list = cfg.get("recurring_messages", [])
            for m in rec_list:
                if m.get("id") == msg_id:
                    m["enabled"] = not m.get("enabled", True)
                    if not m.get("chat_id") or (isinstance(m.get("chat_id"), int) and m.get("chat_id") > 0):
                        m["chat_id"] = chat.id if chat.type in ("group", "supergroup") else cfg.get("main_group_id")
                    save_config(cfg)
                    await query.answer(f"Mensagem #{msg_id}: {'Ativada' if m['enabled'] else 'Desativada'}")
                    break
            if page is not None:
                text, markup = generate_recurring_list(title, cfg, page=page)
            else:
                text, markup = generate_recurring_detail(cfg, msg_id, page=1)
            await query.edit_message_text(text, reply_markup=markup, parse_mode=ParseMode.MARKDOWN)
            return

        if data.startswith("cfg:rec:del:"):
            parts = data.split(":")
            msg_id = int(parts[3])
            page = int(parts[4]) if len(parts) > 4 and parts[4].isdigit() else 1
            rec_list = cfg.get("recurring_messages", [])
            cfg["recurring_messages"] = [m for m in rec_list if m.get("id") != msg_id]
            save_config(cfg)
            await query.answer(f"Mensagem #{msg_id} apagada!")
            text, markup = generate_recurring_list(title, cfg, page=page)
            await query.edit_message_text(text, reply_markup=markup, parse_mode=ParseMode.MARKDOWN)
            return

        if data.startswith("cfg:rec:clone:"):
            parts = data.split(":")
            msg_id = int(parts[3])
            page = int(parts[4]) if len(parts) > 4 and parts[4].isdigit() else 1
            rec_list = cfg.setdefault("recurring_messages", [])
            orig_item = next((m for m in rec_list if m.get("id") == msg_id), None)
            if not orig_item:
                await query.answer("Mensagem não encontrada!", show_alert=True)
                return
            new_item = copy.deepcopy(orig_item)
            new_id = (max([m.get("id", 0) for m in rec_list] or [0])) + 1
            new_item["id"] = new_id
            orig_title = get_recurring_title(orig_item)
            new_item["title"] = f"{orig_title} (Cópia)"
            new_item["enabled"] = False  # Começa pausada para o admin escolher canal e horário
            new_item["last_message_id"] = None
            new_item["last_sent_timestamp"] = 0
            new_item["messages_counter_last"] = 0
            rec_list.append(new_item)
            save_config(cfg)
            await query.answer(f"📋 Mensagem duplicada com sucesso como #{new_id}!", show_alert=True)
            text, markup = generate_recurring_detail(cfg, new_id, page=page)
            await query.edit_message_text(text, reply_markup=markup, parse_mode=ParseMode.MARKDOWN)
            return

        if data.startswith("cfg:rec:preview:"):
            msg_id = int(data.split(":")[-1])
            rec_list = cfg.get("recurring_messages", [])
            msg_item = next((m for m in rec_list if m.get("id") == msg_id), None)
            if not msg_item:
                await query.answer("Mensagem não encontrada!", show_alert=True)
                return
            await query.answer("Enviando prévia no chat...")
            await chat.send_message("👁️ *Prévia da Mensagem Programada:*", parse_mode=ParseMode.MARKDOWN)
            try:
                await send_single_recurring_message(context.bot, msg_item, chat.id, job_queue=context.job_queue)
            except Exception as e_prev:
                await chat.send_message(f"❌ Não foi possível exibir a prévia: {e_prev}")
            return

        if data.startswith("cfg:rec:title:"):
            msg_id = int(data.split(":")[-1])
            self.pending_inputs[user.id] = {"action": "rec_title", "msg_id": msg_id, "chat_id": chat.id}
            await query.answer()
            prompt = (
                f"🏷️ *Definir Nome/Identificador para a Mensagem #{msg_id}:*\n\n"
                "Envie agora o nome que deseja dar a esta mensagem para identificá-la facilmente na lista "
                "(ex: `Aviso Canais VIP`, `Lembrete Semanal`, `Promoção Sibelius`):\n\n"
                "_(Ou envie 'limpar' para restaurar o nome padrão, ou /cancelar)_"
            )
            await chat.send_message(prompt, parse_mode=ParseMode.MARKDOWN)
            return

        if data.startswith("cfg:rec:pin:"):
            msg_id = int(data.split(":")[-1])
            rec_list = cfg.get("recurring_messages", [])
            for m in rec_list:
                if m.get("id") == msg_id:
                    m["pin_message"] = not m.get("pin_message", False)
                    save_config(cfg)
                    await query.answer(f"Fixar mensagem: {'Sim' if m['pin_message'] else 'Não'}")
                    break
            text, markup = generate_recurring_detail(cfg, msg_id)
            await query.edit_message_text(text, reply_markup=markup, parse_mode=ParseMode.MARKDOWN)
            return

        if data.startswith("cfg:rec:delprev:"):
            msg_id = int(data.split(":")[-1])
            rec_list = cfg.get("recurring_messages", [])
            for m in rec_list:
                if m.get("id") == msg_id:
                    m["delete_previous"] = not m.get("delete_previous", False)
                    save_config(cfg)
                    await query.answer(f"Deletar anterior: {'Sim' if m['delete_previous'] else 'Não'}")
                    break
            text, markup = generate_recurring_detail(cfg, msg_id)
            await query.edit_message_text(text, reply_markup=markup, parse_mode=ParseMode.MARKDOWN)
            return

        if data.startswith("cfg:rec:hour_menu:"):
            msg_id = int(data.split(":")[-1])
            await query.answer()
            text, markup = generate_recurring_hour_menu(msg_id)
            await query.edit_message_text(text, reply_markup=markup, parse_mode=ParseMode.MARKDOWN)
            return

        if data.startswith("cfg:rec:set_h:"):
            parts = data.split(":")
            msg_id = int(parts[3])
            hour = int(parts[4])
            await query.answer()
            text, markup = generate_recurring_minute_menu(msg_id, hour)
            await query.edit_message_text(text, reply_markup=markup, parse_mode=ParseMode.MARKDOWN)
            return

        if data.startswith("cfg:rec:set_m:"):
            parts = data.split(":")
            msg_id = int(parts[3])
            hour = int(parts[4])
            minute = int(parts[5])
            rec_list = cfg.get("recurring_messages", [])
            for m in rec_list:
                if m.get("id") == msg_id:
                    m["start_hour"] = hour
                    m["start_minute"] = minute
                    m["last_fired_slot"] = None
                    m["last_sent_timestamp"] = 0
                    break
            save_config(cfg)
            await query.answer(f"Horário de início definido para {hour:02d}:{minute:02d}!")
            text, markup = generate_recurring_detail(cfg, msg_id)
            await query.edit_message_text(text, reply_markup=markup, parse_mode=ParseMode.MARKDOWN)
            return

        if data.startswith("cfg:rec:rep_menu:"):
            msg_id = int(data.split(":")[-1])
            await query.answer()
            text, markup = generate_recurring_rep_menu(cfg, msg_id)
            await query.edit_message_text(text, reply_markup=markup, parse_mode=ParseMode.MARKDOWN)
            return

        if data.startswith("cfg:rec:set_inth:"):
            parts = data.split(":")
            msg_id = int(parts[3])
            h = int(parts[4])
            rec_list = cfg.get("recurring_messages", [])
            for m in rec_list:
                if m.get("id") == msg_id:
                    m["repeat_mode"] = "interval"
                    m["interval_type"] = "hours"
                    m["interval_value"] = h
                    m["interval_minutes"] = h * 60
                    break
            save_config(cfg)
            await query.answer(f"Repetição: A cada {h} hora{'s' if h > 1 else ''}!")
            text, markup = generate_recurring_rep_menu(cfg, msg_id)
            await query.edit_message_text(text, reply_markup=markup, parse_mode=ParseMode.MARKDOWN)
            return

        if data.startswith("cfg:rec:set_intm:"):
            parts = data.split(":")
            msg_id = int(parts[3])
            m_val = int(parts[4])
            rec_list = cfg.get("recurring_messages", [])
            for m in rec_list:
                if m.get("id") == msg_id:
                    m["repeat_mode"] = "interval"
                    m["interval_type"] = "minutes"
                    m["interval_value"] = m_val
                    m["interval_minutes"] = m_val
                    break
            save_config(cfg)
            await query.answer(f"Repetição: A cada {m_val} minuto{'s' if m_val > 1 else ''}!")
            text, markup = generate_recurring_rep_menu(cfg, msg_id)
            await query.edit_message_text(text, reply_markup=markup, parse_mode=ParseMode.MARKDOWN)
            return

        if data.startswith("cfg:rec:msg_menu:"):
            msg_id = int(data.split(":")[-1])
            await query.answer()
            text, markup = generate_recurring_msg_menu(cfg, msg_id)
            await query.edit_message_text(text, reply_markup=markup, parse_mode=ParseMode.MARKDOWN)
            return

        if data.startswith("cfg:rec:set_mcnt:"):
            parts = data.split(":")
            msg_id = int(parts[3])
            cnt = int(parts[4])
            rec_list = cfg.get("recurring_messages", [])
            for m in rec_list:
                if m.get("id") == msg_id:
                    m["repeat_mode"] = "messages"
                    m["messages_interval"] = cnt
                    break
            save_config(cfg)
            await query.answer(f"Repetição: A cada {cnt} mensagens!")
            text, markup = generate_recurring_msg_menu(cfg, msg_id)
            await query.edit_message_text(text, reply_markup=markup, parse_mode=ParseMode.MARKDOWN)
            return

        if data.startswith("cfg:rec:in_mcnt:"):
            msg_id = int(data.split(":")[-1])
            self.pending_inputs[user.id] = {"action": "rec_msg_cnt", "msg_id": msg_id, "chat_id": chat.id}
            await query.answer()
            prompt = (
                f"💬 *Digite a quantidade de mensagens no grupo para acionar a Mensagem #{msg_id}:*\n\n"
                "Exemplo: `50` para postar a cada 50 mensagens enviadas no grupo.\n"
                "_Envie o número agora (ou digite /cancelar para desistir):_"
            )
            await chat.send_message(prompt, parse_mode=ParseMode.MARKDOWN)
            return

        if data.startswith("cfg:rec:wday_menu:"):
            msg_id = int(data.split(":")[-1])
            await query.answer()
            text, markup = generate_recurring_wday_menu(cfg, msg_id)
            await query.edit_message_text(text, reply_markup=markup, parse_mode=ParseMode.MARKDOWN)
            return

        if data.startswith("cfg:rec:tog_wday:"):
            parts = data.split(":")
            msg_id = int(parts[3])
            idx = int(parts[4])
            rec_list = cfg.get("recurring_messages", [])
            for m in rec_list:
                if m.get("id") == msg_id:
                    wd = m.setdefault("weekdays", [0, 1, 2, 3, 4, 5, 6])
                    if idx in wd:
                        wd.remove(idx)
                    else:
                        wd.append(idx)
                    wd.sort()
                    break
            save_config(cfg)
            await query.answer()
            text, markup = generate_recurring_wday_menu(cfg, msg_id)
            await query.edit_message_text(text, reply_markup=markup, parse_mode=ParseMode.MARKDOWN)
            return

        if data.startswith("cfg:rec:wday_p:"):
            parts = data.split(":")
            msg_id = int(parts[3])
            preset = parts[4]
            rec_list = cfg.get("recurring_messages", [])
            for m in rec_list:
                if m.get("id") == msg_id:
                    if preset == "all":
                        m["weekdays"] = [0, 1, 2, 3, 4, 5, 6]
                    elif preset == "work":
                        m["weekdays"] = [0, 1, 2, 3, 4]
                    elif preset == "weekend":
                        m["weekdays"] = [5, 6]
                    break
            save_config(cfg)
            await query.answer("Dias da semana atualizados!")
            text, markup = generate_recurring_wday_menu(cfg, msg_id)
            await query.edit_message_text(text, reply_markup=markup, parse_mode=ParseMode.MARKDOWN)
            return

        if data.startswith("cfg:rec:mday_menu:"):
            msg_id = int(data.split(":")[-1])
            await query.answer()
            text, markup = generate_recurring_mday_menu(cfg, msg_id)
            await query.edit_message_text(text, reply_markup=markup, parse_mode=ParseMode.MARKDOWN)
            return

        if data.startswith("cfg:rec:tog_mday:"):
            parts = data.split(":")
            msg_id = int(parts[3])
            d = int(parts[4])
            rec_list = cfg.get("recurring_messages", [])
            for m in rec_list:
                if m.get("id") == msg_id:
                    md = m.get("month_days")
                    if md is None or len(md) >= 31 or not md:
                        md = list(range(1, 32))
                    if d in md:
                        md.remove(d)
                    else:
                        md.append(d)
                    md.sort()
                    m["month_days"] = md
                    break
            save_config(cfg)
            await query.answer()
            text, markup = generate_recurring_mday_menu(cfg, msg_id)
            await query.edit_message_text(text, reply_markup=markup, parse_mode=ParseMode.MARKDOWN)
            return

        if data.startswith("cfg:rec:mday_p:"):
            parts = data.split(":")
            msg_id = int(parts[3])
            preset = parts[4]
            rec_list = cfg.get("recurring_messages", [])
            for m in rec_list:
                if m.get("id") == msg_id:
                    if preset == "all":
                        m["month_days"] = []
                    elif preset == "1_15":
                        m["month_days"] = [1, 15]
                    elif preset == "1":
                        m["month_days"] = [1]
                    break
            save_config(cfg)
            await query.answer("Dias do mês atualizados!")
            text, markup = generate_recurring_mday_menu(cfg, msg_id)
            await query.edit_message_text(text, reply_markup=markup, parse_mode=ParseMode.MARKDOWN)
            return

        if data.startswith("cfg:rec:autodel_menu:"):
            msg_id = int(data.split(":")[-1])
            await query.answer()
            text, markup = generate_recurring_autodel_menu(cfg, msg_id)
            await query.edit_message_text(text, reply_markup=markup, parse_mode=ParseMode.MARKDOWN)
            return

        if data.startswith("cfg:rec:set_adel:"):
            parts = data.split(":")
            msg_id = int(parts[3])
            sec = int(parts[4])
            rec_list = cfg.get("recurring_messages", [])
            for m in rec_list:
                if m.get("id") == msg_id:
                    m["auto_delete_seconds"] = sec
                    break
            save_config(cfg)
            lbl = format_autodel_display(sec) if sec > 0 else "Desativado"
            await query.answer(f"Exclusão cronometrada: {lbl}")
            text, markup = generate_recurring_autodel_menu(cfg, msg_id)
            await query.edit_message_text(text, reply_markup=markup, parse_mode=ParseMode.MARKDOWN)
            return

        if data.startswith("cfg:rec:edit:"):
            parts = data.split(":")
            msg_id = int(parts[3])
            page = int(parts[4]) if len(parts) > 4 and parts[4].isdigit() else 1
            await query.answer()
            text, markup = generate_recurring_edit_menu(cfg, msg_id, page=page)
            await query.edit_message_text(text, reply_markup=markup, parse_mode=ParseMode.MARKDOWN)
            return

        if data.startswith("cfg:rec:dstart:"):
            msg_id = int(data.split(":")[-1])
            await query.answer()
            text, markup = generate_recurring_date_menu(cfg, msg_id, is_start=True)
            await query.edit_message_text(text, reply_markup=markup, parse_mode=ParseMode.MARKDOWN)
            return

        if data.startswith("cfg:rec:dend:"):
            msg_id = int(data.split(":")[-1])
            await query.answer()
            text, markup = generate_recurring_date_menu(cfg, msg_id, is_start=False)
            await query.edit_message_text(text, reply_markup=markup, parse_mode=ParseMode.MARKDOWN)
            return

        if data.startswith("cfg:rec:dstart_today:"):
            msg_id = int(data.split(":")[-1])
            today_str = datetime.now().strftime("%Y-%m-%d")
            for m in cfg.get("recurring_messages", []):
                if m.get("id") == msg_id:
                    m["start_date"] = today_str
                    break
            save_config(cfg)
            await query.answer(f"Data de início: {today_str}")
            text, markup = generate_recurring_date_menu(cfg, msg_id, is_start=True)
            await query.edit_message_text(text, reply_markup=markup, parse_mode=ParseMode.MARKDOWN)
            return

        if data.startswith("cfg:rec:dend_today:"):
            msg_id = int(data.split(":")[-1])
            today_str = datetime.now().strftime("%Y-%m-%d")
            for m in cfg.get("recurring_messages", []):
                if m.get("id") == msg_id:
                    m["end_date"] = today_str
                    break
            save_config(cfg)
            await query.answer(f"Data final: {today_str}")
            text, markup = generate_recurring_date_menu(cfg, msg_id, is_start=False)
            await query.edit_message_text(text, reply_markup=markup, parse_mode=ParseMode.MARKDOWN)
            return

        if data.startswith("cfg:rec:dstart_clear:"):
            msg_id = int(data.split(":")[-1])
            for m in cfg.get("recurring_messages", []):
                if m.get("id") == msg_id:
                    m["start_date"] = None
                    break
            save_config(cfg)
            await query.answer("Data de início limpa!")
            text, markup = generate_recurring_date_menu(cfg, msg_id, is_start=True)
            await query.edit_message_text(text, reply_markup=markup, parse_mode=ParseMode.MARKDOWN)
            return

        if data.startswith("cfg:rec:dend_clear:"):
            msg_id = int(data.split(":")[-1])
            for m in cfg.get("recurring_messages", []):
                if m.get("id") == msg_id:
                    m["end_date"] = None
                    break
            save_config(cfg)
            await query.answer("Data final limpa!")
            text, markup = generate_recurring_date_menu(cfg, msg_id, is_start=False)
            await query.edit_message_text(text, reply_markup=markup, parse_mode=ParseMode.MARKDOWN)
            return

        if data.startswith("cfg:rec:dstart_input:"):
            msg_id = int(data.split(":")[-1])
            self.pending_inputs[user.id] = {"action": "rec_dstart", "msg_id": msg_id, "chat_id": chat.id}
            await query.answer()
            prompt = (
                f"📅 *Digite a Data de Início para a Mensagem #{msg_id}:*\n\n"
                "Formato: `DD/MM/AAAA` (Ex: `15/10/2026`)\n"
                "_Envie a data agora (ou digite /cancelar para desistir):_"
            )
            await chat.send_message(prompt, parse_mode=ParseMode.MARKDOWN)
            return

        if data.startswith("cfg:rec:dend_input:"):
            msg_id = int(data.split(":")[-1])
            self.pending_inputs[user.id] = {"action": "rec_dend", "msg_id": msg_id, "chat_id": chat.id}
            await query.answer()
            prompt = (
                f"📅 *Digite a Data Final para a Mensagem #{msg_id}:*\n\n"
                "Formato: `DD/MM/AAAA` (Ex: `31/12/2026`)\n"
                "_Envie a data agora (ou digite /cancelar para desistir):_"
            )
            await chat.send_message(prompt, parse_mode=ParseMode.MARKDOWN)
            return

        if data.startswith("cfg:rec:test:"):
            msg_id = int(data.split(":")[-1])
            rec_list = cfg.get("recurring_messages", [])
            msg_item = next((m for m in rec_list if m.get("id") == msg_id), None)
            if msg_item:
                target_chat_id = msg_item.get("chat_id")
                main_group_id = cfg.get("main_group_id")
                if (not target_chat_id or (isinstance(target_chat_id, int) and target_chat_id > 0)) and main_group_id:
                    target_chat_id = main_group_id
                elif not target_chat_id:
                    target_chat_id = chat.id

                try:
                    await query.answer("Disparando teste...")

                    # 1. Envia uma cópia de teste AQUI MESMO no chat privado para o admin ver o resultado!
                    await chat.send_message("👁️ *Prévia da Mensagem (Como será exibida):*", parse_mode=ParseMode.MARKDOWN)
                    await send_single_recurring_message(context.bot, msg_item, chat.id, job_queue=context.job_queue)

                    # 2. Se houver grupo vinculado (diferente do chat privado), envia para o grupo também!
                    if target_chat_id and target_chat_id != chat.id:
                        await send_single_recurring_message(context.bot, msg_item, target_chat_id, job_queue=context.job_queue)
                        await chat.send_message(f"✅ Mensagem de teste #{msg_id} enviada com sucesso para o grupo vinculado!")
                    else:
                        await chat.send_message(f"✅ Teste concluído com sucesso!")
                except Exception as e:
                    await chat.send_message(f"❌ Erro ao enviar mensagem de teste #{msg_id}: {e}")
            return

        if data.startswith("cfg:quick_save_rec:"):
            msg_id = int(data.split(":")[-1])
            captured = self.last_received_private_messages.get(user.id)
            if not captured:
                await query.answer("Nenhuma mensagem recente encontrada.", show_alert=True)
                return

            rec_list = cfg.setdefault("recurring_messages", [])
            target_item = next((m for m in rec_list if m.get("id") == msg_id), None)
            if not target_item:
                target_item = {
                    "id": msg_id,
                    "enabled": True,
                    "text": captured.get("text") or "📢 Postagem Programada",
                    "photo": captured.get("photo"),
                    "buttons": captured.get("buttons") or [],
                    "repeat_mode": "interval",
                    "interval_type": "hours",
                    "interval_value": 24,
                    "interval_minutes": 1440,
                    "messages_interval": 50,
                    "messages_counter_last": 0,
                    "start_hour": None,
                    "start_minute": None,
                    "weekdays": [0, 1, 2, 3, 4, 5, 6],
                    "month_days": [],
                    "start_date": None,
                    "end_date": None,
                    "pin_message": False,
                    "delete_previous": False,
                    "auto_delete_seconds": 0,
                    "last_message_id": None,
                    "last_sent_timestamp": 0,
                    "chat_id": cfg.get("main_group_id")
                }
                rec_list.append(target_item)
            else:
                if captured.get("text") and captured.get("text") != "📢 Postagem da Comunidade":
                    target_item["text"] = captured["text"]
                if captured.get("photo"):
                    target_item["photo"] = captured["photo"]
                if captured.get("buttons"):
                    target_item["buttons"] = captured["buttons"]
                    target_item.pop("source_chat_id", None)
                    target_item.pop("source_message_id", None)
                    target_item.pop("backup_chat_id", None)
                    target_item.pop("backup_message_id", None)
                elif captured.get("source_chat_id") and captured.get("source_message_id") and captured.get("source_chat_id") < 0:
                    target_item["source_chat_id"] = captured["source_chat_id"]
                    target_item["source_message_id"] = captured["source_message_id"]
                    target_item["backup_chat_id"] = captured.get("backup_chat_id")
                    target_item["backup_message_id"] = captured.get("backup_message_id")

            save_config(cfg)
            await query.answer(f"Mensagem #{msg_id} salva com sucesso!")
            markup = InlineKeyboardMarkup([
                [InlineKeyboardButton("⚙️ Voltar à Mensagem", callback_data=f"cfg:rec:detail:{msg_id}")],
                [InlineKeyboardButton("🚀 Testar Envio Agora", callback_data=f"cfg:rec:test:{msg_id}")],
                [InlineKeyboardButton("📋 Lista de Mensagens", callback_data="cfg:rec:list")]
            ])
            try:
                await query.edit_message_text(
                    f"✅ *Mensagem Programada #{msg_id} configurada e pronta para envio!*\n\n"
                    "O texto, artigo expansível, mídias e botões foram vinculados com perfeição.",
                    parse_mode=ParseMode.MARKDOWN,
                    reply_markup=markup
                )
            except Exception:
                await query.edit_message_text(
                    f"✅ Mensagem Programada #{msg_id} configurada e pronta para envio!",
                    reply_markup=markup
                )
            return

        if data == "cfg:quick_save_welcome":
            captured = self.last_received_private_messages.get(user.id)
            if not captured:
                await query.answer("Nenhuma mensagem recente encontrada.", show_alert=True)
                return

            w_cfg = cfg.setdefault("welcome", {})
            if captured.get("text"):
                w_cfg["message"] = captured["text"]
            if captured.get("photo"):
                w_cfg["photo"] = captured["photo"]
            if captured.get("buttons"):
                w_cfg["buttons"] = captured["buttons"]

            save_config(cfg)
            await query.answer("Boas-vindas atualizadas com sucesso!")
            markup = InlineKeyboardMarkup([
                [InlineKeyboardButton("👁️ Visualizar Boas-Vindas", callback_data="cfg:preview:welcome")],
                [InlineKeyboardButton("🔙 Menu Boas-Vindas", callback_data="cfg:sub:welcome")]
            ])
            try:
                await query.edit_message_text(
                    "✅ *Boas-Vindas atualizadas com sucesso!*\n\nA nova postagem rica foi definida.",
                    parse_mode=ParseMode.MARKDOWN,
                    reply_markup=markup
                )
            except Exception:
                await query.edit_message_text(
                    "✅ Boas-Vindas atualizadas com sucesso!",
                    reply_markup=markup
                )
            return

        if data == "cfg:chats:list":
            text, markup = generate_chats_list_page(cfg)
            await query.edit_message_text(text, reply_markup=markup, parse_mode=ParseMode.MARKDOWN)
            return

        if data == "cfg:chats:how_to":
            await query.answer()
            help_text = (
                "🌐 ═══════════════════ 🌐\n"
                "   *COMO VINCULAR GRUPOS E CANAIS*\n"
                "🌐 ═══════════════════ 🌐\n\n"
                "👥 *Para Vincular um Grupo:*\n"
                "1. Adicione o Maestro Bot no grupo.\n"
                "2. Promova o bot a *Administrador* com permissões padrão.\n"
                "3. Envie o comando `/setgrupo` dentro do grupo.\n"
                "4. Pronto! O grupo estará registrado na orquestração.\n\n"
                "📢 *Para Vincular um Canal:*\n"
                "1. Adicione o Maestro Bot no seu canal como *Administrador*.\n"
                "2. No privado do bot, envie:\n"
                "   `/setcanal @seucanal`\n"
                "   ou pelo ID: `/setcanal -1001234567890`\n"
                "3. Pronto! O canal estará pronto para transmissões.\n\n"
                "💡 *Dica:* Você pode vincular quantos grupos e canais desejar!"
            )
            markup = InlineKeyboardMarkup([
                [InlineKeyboardButton("◀ Voltar à Lista de Chats", callback_data="cfg:chats:list")]
            ])
            await query.edit_message_text(help_text, reply_markup=markup, parse_mode=ParseMode.MARKDOWN)
            return

        if data.startswith("cfg:chat:info:") or data.startswith("cfg:chats:info:"):
            parts = data.split(":")
            chat_type = parts[3]
            target_id = parts[4]
            await query.answer()
            text, markup = generate_sub_chat_info(cfg, chat_type, target_id)
            await query.edit_message_text(text, reply_markup=markup, parse_mode=ParseMode.MARKDOWN)
            return

        if data.startswith("cfg:chat:set_main:"):
            parts = data.split(":")
            chat_type = parts[3]
            target_id = int(parts[4])
            if chat_type == "grp":
                cfg["main_group_id"] = target_id
                save_config(cfg)
                await query.answer("⭐️ Grupo definido como Principal!", show_alert=True)
            else:
                cfg["main_channel_id"] = target_id
                save_config(cfg)
                await query.answer("⭐️ Canal definido como Principal!", show_alert=True)
            text, markup = generate_sub_chat_info(cfg, chat_type, target_id)
            await query.edit_message_text(text, reply_markup=markup, parse_mode=ParseMode.MARKDOWN)
            return

        if data.startswith("cfg:chat:unlink:"):
            parts = data.split(":")
            chat_type = parts[3]
            target_id = int(parts[4])
            if chat_type == "grp":
                from config import remove_linked_group
                remove_linked_group(cfg, target_id)
                await query.answer("Grupo desvinculado com sucesso!", show_alert=True)
            else:
                from config import remove_linked_channel
                remove_linked_channel(cfg, target_id)
                await query.answer("Canal desvinculado com sucesso!", show_alert=True)
            text, markup = generate_chats_list_page(cfg)
            await query.edit_message_text(text, reply_markup=markup, parse_mode=ParseMode.MARKDOWN)
            return

        if data.startswith("cfg:chat:post_prompt:"):
            cid = data.split(":")[-1]
            await query.answer()
            prompt = (
                f"📢 *Como Enviar Mensagem para o Canal (`{cid}`):*\n\n"
                "Envie o comando no chat privado:\n"
                "`/canal [Sua mensagem aqui]`\n\n"
                "✨ *Suporta Formatação Total:*\n"
                "• **Negrito**, *itálico*, `código`, ||spoiler||\n"
                "• Citações expansíveis com `>>`\n"
                "• Botões com links em colunas: `[Site - https://...] [Canal - https://...]`\n"
                "• Fotos com legenda formatada!"
            )
            markup = InlineKeyboardMarkup([
                [InlineKeyboardButton("◀ Voltar ao Canal", callback_data=f"cfg:chat:info:chn:{cid}")]
            ])
            await chat.send_message(prompt, parse_mode=ParseMode.MARKDOWN, reply_markup=markup)
            return

        if data.startswith("cfg:rec:target_help:"):
            msg_id = int(data.split(":")[-1])
            rec_list = cfg.get("recurring_messages", [])
            msg_item = next((m for m in rec_list if m.get("id") == msg_id), None)
            target_chat_id = msg_item.get("chat_id") if msg_item else None
            topic_id = msg_item.get("message_thread_id") if msg_item else None

            groups = cfg.get("linked_groups", [])
            channels = cfg.get("linked_channels", [])

            help_text = (
                f"🎯 *Destino da Mensagem Recorrente #{msg_id}*\n\n"
                f"Selecione abaixo em qual grupo ou canal você deseja que esta postagem programada seja enviada automaticamente:\n\n"
                f"• *Destino atual:* `{target_chat_id or 'Grupo Principal'}`\n"
                f"• *Tópico do fórum:* `{topic_id or 'Geral'}`"
            )

            kb = []
            kb.append([
                InlineKeyboardButton("🌐 Todos (Grupos + Canais)", callback_data=f"cfg:rec:set_target:{msg_id}:all"),
            ])
            if groups and channels:
                kb.append([
                    InlineKeyboardButton("👥 Todos os Grupos", callback_data=f"cfg:rec:set_target:{msg_id}:all_groups"),
                    InlineKeyboardButton("📢 Todos os Canais", callback_data=f"cfg:rec:set_target:{msg_id}:all_channels")
                ])

            for g in groups:
                gid = g.get("id")
                gtit = g.get("title", f"Grupo {gid}")
                sel = " ✅" if target_chat_id == gid else ""
                kb.append([InlineKeyboardButton(f"👥 {gtit}{sel}", callback_data=f"cfg:rec:set_target:{msg_id}:{gid}")])

            for c in channels:
                cid = c.get("id")
                ctit = c.get("title", f"Canal {cid}")
                sel = " ✅" if target_chat_id == cid else ""
                kb.append([InlineKeyboardButton(f"📢 {ctit}{sel}", callback_data=f"cfg:rec:set_target:{msg_id}:{cid}")])

            kb.append([InlineKeyboardButton("🔙 Voltar", callback_data=f"cfg:rec:detail:{msg_id}")])
            await query.edit_message_text(help_text, reply_markup=InlineKeyboardMarkup(kb), parse_mode=ParseMode.MARKDOWN)
            await query.answer()
            return

        if data.startswith("cfg:rec:set_target:"):
            parts = data.split(":")
            msg_id = int(parts[3])
            target_val = parts[4]
            if target_val.startswith("-") or target_val.isdigit():
                target_val = int(target_val)
            rec_list = cfg.setdefault("recurring_messages", [])
            for m in rec_list:
                if m.get("id") == msg_id:
                    m["chat_id"] = target_val
                    save_config(cfg)
                    break
            await query.answer("🎯 Destino atualizado com sucesso!")
            text, markup = generate_recurring_detail(cfg, msg_id)
            await query.edit_message_text(text, reply_markup=markup, parse_mode=ParseMode.MARKDOWN)
            return

        if data.startswith("cfg:rec:text:"):
            msg_id = int(data.split(":")[-1])
            self.pending_inputs[user.id] = {"action": "rec_text", "msg_id": msg_id, "chat_id": chat.id}
            await query.answer()
            prompt = (
                f"✏️ *Digite o texto da Mensagem Programada #{msg_id}:*\n\n"
                "_Envie sua mensagem agora (ou digite /cancelar para desistir):_"
            )
            await chat.send_message(prompt, parse_mode=ParseMode.MARKDOWN)
            return

        if data.startswith("cfg:rec:photo:"):
            msg_id = int(data.split(":")[-1])
            self.pending_inputs[user.id] = {"action": "rec_photo", "msg_id": msg_id, "chat_id": chat.id}
            await query.answer()
            prompt = (
                f"🖼️ *Envie a foto ou imagem para a Mensagem Programada #{msg_id}:*\n\n"
                "_Envie a foto pelo chat agora (ou digite /cancelar para desistir):_"
            )
            await chat.send_message(prompt, parse_mode=ParseMode.MARKDOWN)
            return

        if data.startswith("cfg:rec:delphoto:"):
            parts = data.split(":")
            msg_id = int(parts[3])
            page = int(parts[4]) if len(parts) > 4 and parts[4].isdigit() else 1
            rec_list = cfg.get("recurring_messages", [])
            for m in rec_list:
                if m.get("id") == msg_id:
                    m["photo"] = None
                    save_config(cfg)
                    await query.answer("Foto removida!")
                    break
            text, markup = generate_recurring_edit_menu(cfg, msg_id, page=page)
            await query.edit_message_text(text, reply_markup=markup, parse_mode=ParseMode.MARKDOWN)
            return

        if data.startswith("cfg:rec:buttons:"):
            msg_id = int(data.split(":")[-1])
            self.pending_inputs[user.id] = {"action": "rec_buttons", "msg_id": msg_id, "chat_id": chat.id}
            await query.answer()
            prompt = (
                f"🔘 *Configure os Botões para a Mensagem Programada #{msg_id}:*\n\n"
                "💡 *Suporta Múltiplas Colunas (Lado a Lado):*\n"
                "• *Na mesma linha (Colunas):*\n"
                "`[Botão 1 - https://link1.com] [Botão 2 - https://link2.com]`\n"
                "`[Banda Sinfônica - link] [Bases Cifradas - link] [Big & Band - link]`\n\n"
                "• *Ou com && na mesma linha:*\n"
                "`Botão 1 | link1 && Botão 2 | link2`\n\n"
                "• *Um embaixo do outro:*\n"
                "`Botão 1 | https://link1.com`\n"
                "`Botão 2 | https://link2.com`\n\n"
                "_(Envie a lista agora, ou digite 'remover' para limpar todos, ou /cancelar)_"
            )
            await chat.send_message(prompt, parse_mode=ParseMode.MARKDOWN)
            return

        if data.startswith("cfg:rec:article:"):
            msg_id = int(data.split(":")[-1])
            self.pending_inputs[user.id] = {"action": "rec_article", "msg_id": msg_id, "chat_id": chat.id}
            await query.answer()
            prompt = (
                f"📄 *Definir Artigo / Instant View para a Mensagem #{msg_id}:*\n\n"
                "Envie o link do artigo (ex: Telegraph ou página web):\n"
                "`https://telegra.ph/Principais-Canais-e-Grupos...`\n\n"
                "O bot exibirá a prévia do artigo no topo da mensagem programada!\n\n"
                "_(Envie o link agora, ou 'remover' para limpar, ou /cancelar)_"
            )
            await chat.send_message(prompt, parse_mode=ParseMode.MARKDOWN)
            return

        if data.startswith("cfg:rec:delbuttons:"):
            parts = data.split(":")
            msg_id = int(parts[3])
            page = int(parts[4]) if len(parts) > 4 and parts[4].isdigit() else 1
            rec_list = cfg.get("recurring_messages", [])
            for m in rec_list:
                if m.get("id") == msg_id:
                    m["buttons"] = []
                    save_config(cfg)
                    await query.answer("Botões removidos!")
                    break
            text, markup = generate_recurring_edit_menu(cfg, msg_id, page=page)
            await query.edit_message_text(text, reply_markup=markup, parse_mode=ParseMode.MARKDOWN)
            return

        # -------------------------------------------------------------
        # SEÇÃO: RESPOSTAS AUTOMÁTICAS (REGEX & PALAVRAS)
        # -------------------------------------------------------------
        if data == "cfg:resp:list":
            await query.answer()
            text, markup = generate_auto_responder_list(title, cfg)
            await query.edit_message_text(text, reply_markup=markup, parse_mode=ParseMode.MARKDOWN)
            return

        if data == "cfg:resp:add":
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

        if data.startswith("cfg:resp:detail:"):
            resp_id = int(data.split(":")[-1])
            await query.answer()
            text, markup = generate_auto_responder_detail(cfg, resp_id)
            await query.edit_message_text(text, reply_markup=markup, parse_mode=ParseMode.MARKDOWN)
            return

        if data.startswith("cfg:resp:toggle:"):
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

        if data.startswith("cfg:resp:del:"):
            resp_id = int(data.split(":")[-1])
            responders = cfg.get("auto_responses", [])
            cfg["auto_responses"] = [r for r in responders if r.get("id") != resp_id]
            save_config(cfg)
            if self.auto_responder_handler:
                self.auto_responder_handler.invalidate_cache(resp_id)
            await query.answer(f"Resposta #{resp_id} excluída!")
            text, markup = generate_auto_responder_list(title, cfg)
            await query.edit_message_text(text, reply_markup=markup, parse_mode=ParseMode.MARKDOWN)
            return

        if data.startswith("cfg:resp:cycle_cd:"):
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

        if data.startswith("cfg:resp:cycle_delay:"):
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

        if data.startswith("cfg:resp:toggle_regex:"):
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

        if data.startswith("cfg:resp:toggle_reply:"):
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

        if data.startswith("cfg:resp:toggle_del_trig:"):
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

        if data.startswith("cfg:resp:test:"):
            resp_id = int(data.split(":")[-1])
            if self.auto_responder_handler:
                await query.answer("Enviando teste de resposta...")
                await self.auto_responder_handler.test_responder(update, context, resp_id)
            else:
                await query.answer("Handler de teste não configurado.", show_alert=True)
            return

        if data.startswith("cfg:resp:edit_text:"):
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

        if data.startswith("cfg:resp:edit_pattern:"):
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

        if data.startswith("cfg:resp:edit_title:"):
            resp_id = int(data.split(":")[-1])
            self.pending_inputs[user.id] = {"action": "resp_edit_title", "item_id": resp_id, "chat_id": chat.id}
            await query.answer()
            prompt = f"🏷️ *Digite o novo Título da Resposta #{resp_id} (ou /cancelar):*"
            await chat.send_message(prompt, parse_mode=ParseMode.MARKDOWN)
            return

        if data.startswith("cfg:resp:edit_photo:"):
            resp_id = int(data.split(":")[-1])
            self.pending_inputs[user.id] = {"action": "resp_edit_photo", "item_id": resp_id, "chat_id": chat.id}
            await query.answer()
            prompt = f"🖼️ *Envie a foto ou imagem para a Resposta #{resp_id} (ou /cancelar):*"
            await chat.send_message(prompt, parse_mode=ParseMode.MARKDOWN)
            return

        if data.startswith("cfg:resp:del_photo:"):
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

        if data.startswith("cfg:resp:edit_buttons:"):
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

        if data.startswith("cfg:resp:del_buttons:"):
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

        # -------------------------------------------------------------
        # TOGGLES GERAIS
        # -------------------------------------------------------------
        if data == "cfg:toggle:antispam":
            cur = cfg.setdefault("antispam", {}).get("enabled", True)
            cfg["antispam"]["enabled"] = not cur
            save_config(cfg)
            await query.answer(f"Anti-spam: {'Ativado' if not cur else 'Desativado'}")
            text, markup = generate_sub_antispam(cfg)
            await query.edit_message_text(text, reply_markup=markup, parse_mode=ParseMode.MARKDOWN)
            return

        if data == "cfg:toggle:links":
            cur = cfg.setdefault("antispam", {}).get("block_links", True)
            cfg["antispam"]["block_links"] = not cur
            save_config(cfg)
            await query.answer(f"Bloqueio de links: {'Ativado' if not cur else 'Desativado'}")
            text, markup = generate_hub_security(cfg)
            await query.edit_message_text(text, reply_markup=markup, parse_mode=ParseMode.MARKDOWN)
            return

        if data == "cfg:toggle:invites":
            cur = cfg.setdefault("antispam", {}).get("block_telegram_invites", True)
            cfg["antispam"]["block_telegram_invites"] = not cur
            save_config(cfg)
            await query.answer(f"Bloqueio de convites: {'Ativado' if not cur else 'Desativado'}")
            text, markup = generate_hub_security(cfg)
            await query.edit_message_text(text, reply_markup=markup, parse_mode=ParseMode.MARKDOWN)
            return

        if data == "cfg:toggle:forwards":
            cur = cfg.setdefault("antispam", {}).get("block_forwards", True)
            cfg["antispam"]["block_forwards"] = not cur
            save_config(cfg)
            await query.answer(f"Bloqueio de encaminhamentos: {'Ativado' if not cur else 'Desativado'}")
            text, markup = generate_hub_security(cfg)
            await query.edit_message_text(text, reply_markup=markup, parse_mode=ParseMode.MARKDOWN)
            return

        if data == "cfg:toggle:user_repeat":
            cur = cfg.setdefault("antirepeat", {}).get("enabled", True)
            cfg["antirepeat"]["enabled"] = not cur
            save_config(cfg)
            await query.answer(f"Filtro anti-repetição de membros: {'Ativado' if not cur else 'Desativado'}")
            text, markup = generate_hub_security(cfg)
            await query.edit_message_text(text, reply_markup=markup, parse_mode=ParseMode.MARKDOWN)
            return

        if data == "cfg:toggle:flood":
            cur = cfg.setdefault("antiflood", {}).get("enabled", True)
            cfg["antiflood"]["enabled"] = not cur
            save_config(cfg)
            await query.answer(f"Anti-flood: {'Ativado' if not cur else 'Desativado'}")
            text, markup = generate_sub_antiflood(cfg)
            await query.edit_message_text(text, reply_markup=markup, parse_mode=ParseMode.MARKDOWN)
            return

        if data == "cfg:toggle:service_msg":
            cur = cfg.setdefault("welcome", {}).get("delete_service_messages", True)
            cfg["welcome"]["delete_service_messages"] = not cur
            save_config(cfg)
            await query.answer(f"Limpar msg de entrada: {'Ativado' if not cur else 'Desativado'}")
            text, markup = generate_hub_clean(cfg)
            await query.edit_message_text(text, reply_markup=markup, parse_mode=ParseMode.MARKDOWN)
            return

        if data == "cfg:toggle:pin_service_msg":
            cur = cfg.get("delete_pinned_service_messages", True)
            cfg["delete_pinned_service_messages"] = not cur
            save_config(cfg)
            await query.answer(f"Limpar avisos de fixado: {'Ativado' if not cur else 'Desativado'}")
            text, markup = generate_hub_clean(cfg)
            await query.edit_message_text(text, reply_markup=markup, parse_mode=ParseMode.MARKDOWN)
            return

        if data == "cfg:toggle:welcome":
            cur = cfg.setdefault("welcome", {}).get("enabled", True)
            cfg["welcome"]["enabled"] = not cur
            save_config(cfg)
            await query.answer(f"Boas-vindas: {'Ativadas' if not cur else 'Desativadas'}")
            text, markup = generate_hub_welcome(cfg)
            await query.edit_message_text(text, reply_markup=markup, parse_mode=ParseMode.MARKDOWN)
            return

        if data == "cfg:toggle:captcha":
            cur = cfg.setdefault("captcha", {}).get("enabled", False)
            cfg["captcha"]["enabled"] = not cur
            save_config(cfg)
            await query.answer(f"Anti-Bot CAPTCHA: {'Ativado' if not cur else 'Desativado'}")
            text, markup = generate_hub_security(cfg)
            await query.edit_message_text(text, reply_markup=markup, parse_mode=ParseMode.MARKDOWN)
            return

        if data == "cfg:toggle:join_req":
            cur = cfg.setdefault("join_requests", {}).get("auto_approve", False)
            cfg["join_requests"]["auto_approve"] = not cur
            save_config(cfg)
            await query.answer(f"Auto-aprovação de entrada: {'Ativada' if not cur else 'Desativada'}")
            text, markup = generate_hub_welcome(cfg)
            await query.edit_message_text(text, reply_markup=markup, parse_mode=ParseMode.MARKDOWN)
            return

        if data == "cfg:toggle:cmd_clean":
            cur = cfg.setdefault("command_cleanup", {}).get("delete_admin_commands", True)
            cfg["command_cleanup"]["delete_admin_commands"] = not cur
            cfg["command_cleanup"]["delete_non_admin_commands"] = not cur
            save_config(cfg)
            await query.answer(f"Limpeza de comandos: {'Ativada' if not cur else 'Desativada'}")
            text, markup = generate_sub_cmd_clean(cfg)
            await query.edit_message_text(text, reply_markup=markup, parse_mode=ParseMode.MARKDOWN)
            return

        if data == "cfg:toggle:clean_admin":
            cc = cfg.setdefault("command_cleanup", {})
            cur = cc.get("delete_admin_commands", True)
            cc["delete_admin_commands"] = not cur
            save_config(cfg)
            await query.answer(f"Comandos de Admin: {'Ativado' if not cur else 'Desativado'}")
            text, markup = generate_sub_cmd_clean(cfg)
            await query.edit_message_text(text, reply_markup=markup, parse_mode=ParseMode.MARKDOWN)
            return

        if data == "cfg:toggle:clean_user":
            cc = cfg.setdefault("command_cleanup", {})
            cur = cc.get("delete_non_admin_commands", True)
            cc["delete_non_admin_commands"] = not cur
            save_config(cfg)
            await query.answer(f"Comandos de Membros: {'Ativado' if not cur else 'Desativado'}")
            text, markup = generate_sub_cmd_clean(cfg)
            await query.edit_message_text(text, reply_markup=markup, parse_mode=ParseMode.MARKDOWN)
            return

        if data == "cfg:cycle:clean_notice":
            cc = cfg.setdefault("command_cleanup", {})
            cur = cc.get("bot_notice_delete_seconds", 10)
            seq = [0, 5, 10, 15, 30]
            idx = seq.index(cur) if cur in seq else 0
            new_val = seq[(idx + 1) % len(seq)]
            cc["bot_notice_delete_seconds"] = new_val
            save_config(cfg)
            lbl = f"{new_val}s" if new_val > 0 else "Nunca apagar"
            await query.answer(f"Tempo do aviso do bot: {lbl}")
            text, markup = generate_sub_cmd_clean(cfg)
            await query.edit_message_text(text, reply_markup=markup, parse_mode=ParseMode.MARKDOWN)
            return

        if data == "cfg:cycle:repeat_window":
            cur = cfg.setdefault("antirepeat", {}).get("time_window_hours", 2)
            next_hours = {1: 2, 2: 4, 4: 6, 6: 12, 12: 24, 24: 1}
            new_h = next_hours.get(cur, 2)
            cfg["antirepeat"]["time_window_hours"] = new_h
            cfg["antirepeat"]["time_window_seconds"] = int(new_h * 3600)
            save_config(cfg)
            await query.answer(f"Janela de repetição: {new_h} hora(s)")
            text, markup = generate_page_2(title, cfg)
            await query.edit_message_text(text, reply_markup=markup, parse_mode=ParseMode.MARKDOWN)
            return

        # Ciclos de valores numéricos
        if data.startswith("cfg:cycle:welcome_time"):
            gid = data.split(":")[-1] if len(data.split(":")) > 3 else "general"
            if gid in ("general", "0", ""):
                cur = cfg.setdefault("welcome", {}).get("delete_welcome_after_seconds", 60)
            else:
                from config import get_welcome_for_chat
                w_grp = cfg.setdefault("group_welcomes", {}).setdefault(str(gid), dict(get_welcome_for_chat(cfg, gid)))
                cur = w_grp.get("delete_welcome_after_seconds", 60)

            next_vals = {0: 30, 30: 60, 60: 120, 120: 300, 300: 600, 600: 1800, 1800: 0}
            new_val = next_vals.get(cur, 60)

            if gid in ("general", "0", ""):
                cfg["welcome"]["delete_welcome_after_seconds"] = new_val
            else:
                w_grp["delete_welcome_after_seconds"] = new_val

            save_config(cfg)
            label = format_time_label(new_val)
            try:
                await query.answer(f"Tempo de boas-vindas: {label}")
            except Exception:
                pass
            if query.message and query.message.text and "Página 2" in query.message.text:
                text, markup = generate_page_2(title, cfg)
                pm = ParseMode.MARKDOWN
            else:
                text, markup = generate_sub_welcome(cfg, gid)
                pm = ParseMode.HTML
            try:
                await query.edit_message_text(text, reply_markup=markup, parse_mode=pm)
            except Exception:
                try:
                    await query.edit_message_text(text, reply_markup=markup)
                except Exception:
                    pass
            return

        if data == "cfg:cycle:flood_mute":
            cur = cfg.setdefault("antiflood", {}).get("mute_duration_minutes", 5)
            next_vals = {5: 15, 15: 30, 30: 60, 60: 5}
            new_val = next_vals.get(cur, 5)
            cfg["antiflood"]["mute_duration_minutes"] = new_val
            save_config(cfg)
            await query.answer(f"Punição: silenciar por {new_val} min")
            text, markup = generate_sub_antiflood(cfg)
            await query.edit_message_text(text, reply_markup=markup, parse_mode=ParseMode.MARKDOWN)
            return

        await query.answer()

