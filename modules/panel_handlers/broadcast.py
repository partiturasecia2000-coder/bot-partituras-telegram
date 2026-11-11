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
        """Dispara a transmissão para os chats selecionados com distribuição gradual e gera relatório detalhado."""
        state = self._get_or_create_wizard_state(user_id)
        if not state or (not state.get("text") and not state.get("media_id")):
            p = self.pending_inputs.get(user_id, {})
            if isinstance(p, dict):
                inner = p.get("state")
                if isinstance(inner, dict):
                    state.update(inner)
                for k in ("text", "media_type", "media_id", "buttons", "pin", "target", "delay_seconds"):
                    if k in p and p[k]:
                        state[k] = p[k]

        if not state:
            if update.callback_query:
                await update.callback_query.answer("⚠️ Nenhuma transmissão pendente encontrada.", show_alert=True)
            return

        cfg = load_config()
        bot = context.bot
        target = state.get("target", "main_channel")
        text = state.get("text", "")
        media_type = state.get("media_type")
        media_id = state.get("media_id")
        buttons = state.get("buttons", [])
        pin = state.get("pin", False)
        delay_sec = state.get("delay_seconds", 2)

        # Se texto estiver vazio mas não tem mídia, fallback para texto padrão
        if not text and not media_id:
            text = "📢 Comunicado Oficial"
            state["text"] = text

        targets = get_wizard_targets_list(target, cfg)
        if not targets:
            msg = update.effective_message
            if msg:
                await msg.reply_text("⚠️ Nenhum chat de destino encontrado para esse envio.")
            return

        if update.callback_query:
            try:
                await update.callback_query.edit_message_reply_markup(reply_markup=None)
            except Exception:
                pass

        from modules.utils import build_rich_buttons_markup, smart_send_message, smart_send_photo, smart_send_video
        import telegram.error
        markup = build_rich_buttons_markup(buttons)

        sent_count = 0
        fail_count = 0
        errors = []

        from config import normalize_chat_id
        all_chats_map = {}
        for x in cfg.get("linked_groups", []) + cfg.get("linked_channels", []):
            raw_id = x.get("id")
            norm_id = normalize_chat_id(raw_id)
            title = x.get("title") or f"Chat {norm_id}"
            all_chats_map[raw_id] = title
            all_chats_map[norm_id] = title
        all_chats_map[-1001806380183] = "HC Sibelius"
        delivered_names = []

        for i, raw_cid in enumerate(targets):
            if i > 0 and delay_sec > 0:
                await asyncio.sleep(delay_sec)

            cid = normalize_chat_id(raw_cid)
            if cid in (-1002071806380183, -2071806380183, 2071806380183):
                cid = -1001806380183
            c_title = all_chats_map.get(cid) or all_chats_map.get(raw_cid, str(cid))
            if "sibelius" in c_title.lower() or cid == -1001806380183:
                c_title = "HC Sibelius"
            logger.info(f"Transmitindo mensagem wizard para chat {cid} ({c_title})...")
            try:
                sent_msg = None
                if media_type == "video" and media_id:
                    sent_msg = await smart_send_video(bot, chat_id=cid, video=media_id, caption=text, reply_markup=markup)
                elif media_type == "photo" and media_id:
                    sent_msg = await smart_send_photo(bot, chat_id=cid, photo=media_id, caption=text, reply_markup=markup)
                else:
                    sent_msg = await smart_send_message(bot, chat_id=cid, text=text, reply_markup=markup)

                if sent_msg:
                    sent_count += 1
                    delivered_names.append(c_title)
                    logger.info(f"Sucesso ao entregar mensagem no chat {cid} ({c_title})")
                    if pin and hasattr(sent_msg, "pin"):
                        try:
                            await sent_msg.pin(disable_notification=False)
                        except Exception as e_pin:
                            logger.debug(f"Não foi possível fixar mensagem no chat {cid}: {e_pin}")
                    
                    real_id = getattr(getattr(sent_msg, "chat", None), "id", cid)
                    if real_id != raw_cid:
                        logger.info(f"Auto-corrigindo chat '{c_title}' de {raw_cid} para {real_id} no config!")
                        for g in cfg.get("linked_groups", []):
                            if g.get("id") == raw_cid:
                                g["id"] = real_id
                        for c in cfg.get("linked_channels", []):
                            if c.get("id") == raw_cid:
                                c["id"] = real_id
                        save_config(cfg)
                else:
                    fail_count += 1
                    errors.append(f"Chat {c_title} ({cid}): Falha no envio (sem confirmação do Telegram)")
                    logger.error(f"Falha ao enviar mensagem no chat {cid} ({c_title}): smart_send retornou None")
            except telegram.error.RetryAfter as e_retry:
                logger.warning(f"FloodWait de {e_retry.retry_after}s recebido no chat {cid} ({c_title}). Aguardando...")
                await asyncio.sleep(e_retry.retry_after + 1)
                try:
                    if media_type == "video" and media_id:
                        sent_msg = await smart_send_video(bot, chat_id=cid, video=media_id, caption=text, reply_markup=markup)
                    elif media_type == "photo" and media_id:
                        sent_msg = await smart_send_photo(bot, chat_id=cid, photo=media_id, caption=text, reply_markup=markup)
                    else:
                        sent_msg = await smart_send_message(bot, chat_id=cid, text=text, reply_markup=markup)
                    if sent_msg:
                        sent_count += 1
                        delivered_names.append(c_title)
                        logger.info(f"Sucesso ao entregar mensagem após retry no chat {cid} ({c_title})")
                        if pin and hasattr(sent_msg, "pin"):
                            try:
                                await sent_msg.pin(disable_notification=False)
                            except Exception:
                                pass
                except Exception as e_fail:
                    fail_count += 1
                    errors.append(f"Chat {c_title} ({cid}): {e_fail}")
                    logger.error(f"Erro ao entregar no chat {cid} ({c_title}) após retry: {e_fail}")
            except Exception as e_send:
                fail_count += 1
                errors.append(f"Chat {c_title} ({cid}): {e_send}")
                logger.error(f"Erro ao transmitir para chat {cid} ({c_title}): {e_send}")

        # Limpa o estado
        self.wizard_states.pop(user_id, None)
        if user_id in self.pending_inputs:
            del self.pending_inputs[user_id]
            self._save_pending_inputs()

        dest_label = get_wizard_dest_label(target, cfg)
        media_label = "🎥 Vídeo" if media_type == "video" else ("🖼️ Foto" if media_type == "photo" else "⚪ Texto")

        report = (
            "🎉 *TRANSMISSÃO CONCLUÍDA!*\n"
            "🎼 ══════════════════════ 🎼\n\n"
            f"• *Destino Escolhido:* `{dest_label}`\n"
            f"• *Sucesso:* `{sent_count}` chat(s)\n"
            f"• *Falhas:* `{fail_count}`\n"
            f"• *Distribuição:* `{delay_sec}s entre cada chat (Envio Suave 🌊)`\n"
            f"• *Fixado no Topo:* `{'Sim 📌' if pin else 'Não'}`\n"
            f"• *Mídia:* `{media_label}`\n\n"
        )
        if delivered_names:
            report += "📋 *Entregue com sucesso em:*\n" + "\n".join([f"  ✅ `{name}`" for name in delivered_names]) + "\n\n"

        if target in ("all", "all_channels", "main_channel") and not cfg.get("linked_channels"):
            report += "⚠️ *Aviso Importante:* O bot não possui canais vinculados no momento (`/canais`). Para conectar seu canal, use `/setcanal @seucanal`.\n\n"

        if errors:
            report += f"⚠️ *Detalhes das falhas:*\n" + "\n".join(errors[:3])

        final_markup = InlineKeyboardMarkup([
            [InlineKeyboardButton("📢 Nova Transmissão", callback_data="cfg:wiz:start")],
            [InlineKeyboardButton("🗓️ Ver Agendadas", callback_data="cfg:sched:list")],
            [InlineKeyboardButton("◀ Voltar ao Painel", callback_data="cfg:page:1")]
        ])

        try:
            await update.effective_message.reply_text(report, reply_markup=final_markup, parse_mode=ParseMode.MARKDOWN)
        except Exception:
            await update.effective_message.reply_text(report, reply_markup=final_markup)

        # Envia Log de Auditoria
        admin_user = update.effective_user
        if admin_user:
            adm_info = f"{admin_user.full_name} (@{admin_user.username})" if admin_user.username else admin_user.full_name
            import html
            await send_mod_log(
                bot=bot,
                event_type="say",
                title="Transmissão Guiada Realizada",
                user_info=f"Destino: <b>{html.escape(dest_label)}</b> ({sent_count} chats)",
                admin_info=f"<b>{html.escape(adm_info)}</b>",
                details=f"Fixado: {'Sim' if pin else 'Não'} | Mídia: {media_label} | Delay: {delay_sec}s"
            )


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

