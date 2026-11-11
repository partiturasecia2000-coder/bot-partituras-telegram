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

        # Whitelist & Links Permitidos (modules/whitelist.py)
        if await handle_whitelist_input(self, update, context):
            return True

        if action == "youtube_add":
            raw_input = msg.text.strip() if msg.text else ""
            if not raw_input:
                await msg.reply_text("❌ Por favor, envie um @handle ou link válido do canal do YouTube, ou digite /cancelar.")
                return True

            del self.pending_inputs[user.id]
            wait_msg = await msg.reply_text("🔍 <i>Consultando dados do canal no YouTube, aguarde...</i>", parse_mode=ParseMode.HTML)

            cfg = load_config()
            success, res_text, ch_data = add_youtube_channel(cfg, raw_input)
            try:
                await wait_msg.delete()
            except Exception:
                pass

            if success:
                kb = [[InlineKeyboardButton("🎬 Voltar ao Notificador", callback_data="cfg:sub:youtube")]]
                await msg.reply_text(
                    f"✅ {res_text}\n\n"
                    f"📺 Canal: <b>{ch_data.get('name')}</b>\n"
                    f"🔗 Link: {ch_data.get('url')}\n"
                    f"⏱️ Verificação: A cada 5 minutos\n\n"
                    f"<i>O bot anunciará novos vídeos automaticamente no grupo!</i>",
                    reply_markup=InlineKeyboardMarkup(kb),
                    parse_mode=ParseMode.HTML
                )
            else:
                kb = [[InlineKeyboardButton("➕ Tentar Novamente", callback_data="cfg:youtube:add")]]
                await msg.reply_text(f"⚠️ {res_text}", reply_markup=InlineKeyboardMarkup(kb), parse_mode=ParseMode.HTML)
            return True

        if action == "backup_channel":
            raw_input = msg.text.strip() if msg.text else ""
            if not raw_input:
                await msg.reply_text("❌ Por favor, envie o ID numérico do canal (ex: -1004462851433), ou digite /cancelar.")
                return True

            try:
                ch_id = int(raw_input)
            except ValueError:
                await msg.reply_text("❌ ID inválido. O ID do canal deve ser numérico (ex: <code>-1004462851433</code>). Tente novamente ou digite /cancelar.", parse_mode=ParseMode.HTML)
                return True

            del self.pending_inputs[user.id]
            cfg = load_config()
            b_cfg = cfg.setdefault("backup_system", {
                "enabled": True, "channel_id": -1004462851433,
                "daily_backup_enabled": True, "daily_backup_interval_hours": 24,
                "last_daily_backup_timestamp": 0, "weekly_report_enabled": True,
                "weekly_report_interval_days": 7, "last_weekly_report_timestamp": 0
            })
            b_cfg["channel_id"] = ch_id
            save_config(cfg)

            kb = [[InlineKeyboardButton("💾 Voltar a Backups", callback_data="cfg:sub:backup")]]
            await msg.reply_text(
                f"✅ Canal de Backup & Relatórios atualizado para: <code>{ch_id}</code>!",
                reply_markup=InlineKeyboardMarkup(kb),
                parse_mode=ParseMode.HTML
            )
            return True

        if action == "youtube_target":
            raw_input = msg.text.strip() if msg.text else ""
            if not raw_input:
                await msg.reply_text("❌ Por favor, envie o @username ou ID do grupo, ou digite /cancelar.")
                return True

            del self.pending_inputs[user.id]
            cfg = load_config()
            yt_cfg = cfg.setdefault("youtube_notifications", {
                "enabled": True, "target_chat": "@partiturasecia", "check_interval_minutes": 5, "channels": []
            })
            yt_cfg["target_chat"] = raw_input
            save_config(cfg)

            kb = [[InlineKeyboardButton("🎬 Voltar ao Notificador", callback_data="cfg:sub:youtube")]]
            await msg.reply_text(
                f"✅ Grupo destino atualizado com sucesso para: <code>{raw_input}</code>!",
                reply_markup=InlineKeyboardMarkup(kb),
                parse_mode=ParseMode.HTML
            )
            return True

        if action == "acervo:set_channel_link":
            target_id = state.get("target_id")
            channel_title = state.get("channel_title", "Canal")
            raw_url = msg.text.strip() if msg.text else ""
            if not (raw_url.startswith("http://") or raw_url.startswith("https://") or raw_url.startswith("@")):
                await msg.reply_text("❌ Por favor, envie um link válido (ex: <code>https://t.me/+AbCdEfGh</code> ou <code>@seucanal</code>), ou digite /cancelar.", parse_mode=ParseMode.HTML)
                return True

            cfg = load_config()
            if "channel_invite_links" not in cfg:
                cfg["channel_invite_links"] = {}
            cfg["channel_invite_links"][str(target_id)] = raw_url

            for ch in cfg.get("linked_channels", []):
                if str(ch.get("id")) == str(target_id):
                    ch["invite_link"] = raw_url

            save_config(cfg)
            del self.pending_inputs[user.id]

            from modules.inline_acervo import generate_channel_links_menu_text_and_kb
            text, markup = generate_channel_links_menu_text_and_kb()
            await msg.reply_text(
                f"✅ <b>Link de Entrada Salvo com Sucesso!</b>\n\n"
                f"📢 <b>Canal:</b> {html.escape(channel_title)}\n"
                f"🔗 <b>Link:</b> <code>{html.escape(raw_url)}</code>\n\n"
                f"Agora quando alguém buscar uma partitura deste canal, o botão <b>'1º Entrar no Canal'</b> levará para este link!",
                parse_mode=ParseMode.HTML,
                reply_markup=markup
            )
            return True

        # -------------------------------------------------------------
        # 1. TEXTO / FOTO / BOTÕES DE BOAS-VINDAS (modules/welcome_ui.py)
        # -------------------------------------------------------------
        if action.startswith("welcome_"):
            return await handle_welcome_input(self, msg, context, user, state, action)

        # -------------------------------------------------------------
        # 2. TEXTO / FOTO / BOTÕES DE MENSAGEM REPETIDA (CRONOGRAMA)
        # -------------------------------------------------------------
        elif action == "rec_text":
            msg_id = state.get("msg_id", 1)
            raw_text, photo_id, extracted_buttons, src_chat_id, src_msg_id, bak_chat_id, bak_msg_id = await self._extract_message_content(msg, context, user.id)

            rec_list = cfg.setdefault("recurring_messages", [])
            target_item = next((m for m in rec_list if m.get("id") == msg_id), None)
            if not target_item:
                target_item = {
                    "id": msg_id,
                    "enabled": True,
                    "text": "📢 Postagem Programada",
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
                    "chat_id": cfg.get("main_group_id")
                }
                rec_list.append(target_item)

            if raw_text:
                target_item["text"] = raw_text
            if photo_id:
                target_item["photo"] = photo_id
            if extracted_buttons:
                target_item["buttons"] = extracted_buttons
            if src_chat_id and src_msg_id and src_chat_id < 0:
                target_item["source_chat_id"] = src_chat_id
                target_item["source_message_id"] = src_msg_id
                target_item["backup_chat_id"] = bak_chat_id
                target_item["backup_message_id"] = bak_msg_id
            else:
                target_item.pop("source_chat_id", None)
                target_item.pop("source_message_id", None)
                target_item.pop("backup_chat_id", None)
                target_item.pop("backup_message_id", None)

            save_config(cfg)
            del self.pending_inputs[user.id]

            # Envia prévia visual da mensagem no chat privado
            try:
                await msg.reply_text("👁️ *Veja abaixo a prévia de como sua mensagem ficou:*", parse_mode=ParseMode.MARKDOWN)
                await send_single_recurring_message(context.bot, target_item, msg.chat.id, job_queue=context.job_queue)
            except Exception as e_pv:
                logger.warning(f"Erro ao exibir prévia no rec_text: {e_pv}")

            summary_items = ["• *Texto:* Salvo com sucesso"]
            if photo_id:
                summary_items.append("• *Foto:* Imagem salva")
            if extracted_buttons:
                total_btns = sum(len(r) for r in extracted_buttons)
                summary_items.append(f"• *Botões:* {total_btns} botão(ões) capturados")

            summary_str = "\n".join(summary_items)

            btns_exist = bool(target_item.get("buttons"))
            btn_action_label = "🔘 Alterar Botões com Links" if btns_exist else "🔘 Adicionar Botões com Links"
            photo_exist = bool(target_item.get("photo"))
            photo_action_label = "🖼️ Alterar Foto" if photo_exist else "🖼️ Adicionar Foto / Banner"

            markup = InlineKeyboardMarkup([
                [InlineKeyboardButton(btn_action_label, callback_data=f"cfg:rec:buttons:{msg_id}")],
                [
                    InlineKeyboardButton(photo_action_label, callback_data=f"cfg:rec:photo:{msg_id}"),
                    InlineKeyboardButton("🎯 Canal de Destino", callback_data=f"cfg:rec:target_help:{msg_id}")
                ],
                [
                    InlineKeyboardButton("⏰ Horário de Envio", callback_data=f"cfg:rec:hour_menu:{msg_id}"),
                    InlineKeyboardButton("👀 Ver Prévia", callback_data=f"cfg:rec:preview:{msg_id}")
                ],
                [
                    InlineKeyboardButton("⚙️ Menu Completo", callback_data=f"cfg:rec:detail:{msg_id}"),
                    InlineKeyboardButton("📋 Lista de Mensagens", callback_data="cfg:rec:list")
                ]
            ])
            confirm_msg = (
                f"✅ *Texto da Mensagem #{msg_id} salvo com sucesso!*\n\n{summary_str}\n\n"
                "👉 *Próximo passo:* Para adicionar botões com links (ex: canais/grupos), clique no botão abaixo:"
            )
            try:
                await msg.reply_text(
                    confirm_msg,
                    parse_mode=ParseMode.MARKDOWN,
                    reply_markup=markup
                )
            except Exception:
                await msg.reply_text(
                    confirm_msg.replace("*", "").replace("•", "-"),
                    reply_markup=markup
                )
            return True

        elif action == "rec_photo":
            msg_id = state.get("msg_id", 1)
            if not msg.photo:
                await msg.reply_text("⚠️ Envie uma imagem válida ou digite /cancelar.")
                return True

            file_id = msg.photo[-1].file_id
            rec_list = cfg.setdefault("recurring_messages", [])
            target_item = next((m for m in rec_list if m.get("id") == msg_id), None)
            if not target_item:
                target_item = {
                    "id": msg_id,
                    "enabled": True,
                    "text": "📢 Postagem Programada",
                    "photo": file_id,
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
                    "chat_id": cfg.get("main_group_id")
                }
                rec_list.append(target_item)
            else:
                target_item["photo"] = file_id

            target_item.pop("source_chat_id", None)
            target_item.pop("source_message_id", None)
            target_item.pop("backup_chat_id", None)
            target_item.pop("backup_message_id", None)

            save_config(cfg)
            del self.pending_inputs[user.id]

            try:
                await msg.reply_text("👁️ *Veja abaixo a prévia com a nova foto:*", parse_mode=ParseMode.MARKDOWN)
                await send_single_recurring_message(context.bot, target_item, msg.chat.id, job_queue=context.job_queue)
            except Exception as e_pv:
                logger.warning(f"Erro ao exibir prévia no rec_photo: {e_pv}")

            btns_exist = bool(target_item.get("buttons"))
            btn_action_label = "🔘 Alterar Botões" if btns_exist else "🔘 Adicionar Botões com Links"

            markup = InlineKeyboardMarkup([
                [InlineKeyboardButton(btn_action_label, callback_data=f"cfg:rec:buttons:{msg_id}")],
                [
                    InlineKeyboardButton("🎯 Canal de Destino", callback_data=f"cfg:rec:target_help:{msg_id}"),
                    InlineKeyboardButton("⏰ Horário de Envio", callback_data=f"cfg:rec:hour_menu:{msg_id}")
                ],
                [
                    InlineKeyboardButton("✏️ Editar Texto", callback_data=f"cfg:rec:text:{msg_id}"),
                    InlineKeyboardButton("👀 Ver Prévia", callback_data=f"cfg:rec:preview:{msg_id}")
                ],
                [
                    InlineKeyboardButton("⚙️ Menu Completo", callback_data=f"cfg:rec:detail:{msg_id}"),
                    InlineKeyboardButton("📋 Lista de Mensagens", callback_data="cfg:rec:list")
                ]
            ])
            try:
                await msg.reply_text(f"✅ *Foto da mensagem #{msg_id} atualizada com sucesso!*\n\n👉 Escolha o próximo passo abaixo:", parse_mode=ParseMode.MARKDOWN, reply_markup=markup)
            except Exception:
                await msg.reply_text(f"✅ Foto da mensagem #{msg_id} atualizada com sucesso!", reply_markup=markup)
            return True

        elif action == "rec_buttons":
            msg_id = state.get("msg_id", 1)
            raw_text, photo_id, extracted_buttons, src_chat_id, src_msg_id, bak_chat_id, bak_msg_id = await self._extract_message_content(msg, context, user.id)

            rec_list = cfg.setdefault("recurring_messages", [])
            target_item = next((m for m in rec_list if m.get("id") == msg_id), None)
            if not target_item:
                target_item = {
                    "id": msg_id,
                    "enabled": True,
                    "text": "📢 Postagem Programada",
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
                    "chat_id": cfg.get("main_group_id")
                }
                rec_list.append(target_item)

            if raw_text and raw_text.strip().lower() in ("remover", "apagar", "nenhum"):
                target_item["buttons"] = []
                target_item.pop("source_chat_id", None)
                target_item.pop("source_message_id", None)
                target_item.pop("backup_chat_id", None)
                target_item.pop("backup_message_id", None)
                save_config(cfg)
                del self.pending_inputs[user.id]
                markup = InlineKeyboardMarkup([
                    [InlineKeyboardButton("⚙️ Voltar à Mensagem", callback_data=f"cfg:rec:detail:{msg_id}")],
                    [InlineKeyboardButton("📋 Lista de Mensagens", callback_data="cfg:rec:list")]
                ])
                await msg.reply_text(f"✅ *Botões da mensagem #{msg_id} removidos!*", parse_mode=ParseMode.MARKDOWN, reply_markup=markup)
                return True

            if extracted_buttons:
                target_item["buttons"] = extracted_buttons
                target_item.pop("source_chat_id", None)
                target_item.pop("source_message_id", None)
                target_item.pop("backup_chat_id", None)
                target_item.pop("backup_message_id", None)
            elif src_chat_id and src_msg_id and src_chat_id < 0:
                target_item["source_chat_id"] = src_chat_id
                target_item["source_message_id"] = src_msg_id
                target_item["backup_chat_id"] = bak_chat_id
                target_item["backup_message_id"] = bak_msg_id
            else:
                await msg.reply_text("⚠️ Nenhum botão detectado. Envie os botões no formato:\n`Texto do Botão | https://link.com`\n\nOu digite /cancelar.")
                return True

            save_config(cfg)
            del self.pending_inputs[user.id]

            # Envia prévia visual da mensagem no chat privado
            try:
                await msg.reply_text("👁️ *Veja abaixo como sua mensagem ficou com os botões:*", parse_mode=ParseMode.MARKDOWN)
                await send_single_recurring_message(context.bot, target_item, msg.chat.id, job_queue=context.job_queue)
            except Exception as e_pv:
                logger.warning(f"Erro ao exibir prévia no rec_buttons: {e_pv}")

            total_btns = sum(len(r) for r in extracted_buttons) if extracted_buttons else 0
            photo_exist = bool(target_item.get("photo"))
            photo_action_label = "🖼️ Alterar Foto" if photo_exist else "🖼️ Adicionar Foto / Banner"

            markup = InlineKeyboardMarkup([
                [
                    InlineKeyboardButton("🎯 Canal de Destino", callback_data=f"cfg:rec:target_help:{msg_id}"),
                    InlineKeyboardButton("⏰ Horário de Envio", callback_data=f"cfg:rec:hour_menu:{msg_id}")
                ],
                [
                    InlineKeyboardButton(photo_action_label, callback_data=f"cfg:rec:photo:{msg_id}"),
                    InlineKeyboardButton("✏️ Editar Texto", callback_data=f"cfg:rec:text:{msg_id}")
                ],
                [
                    InlineKeyboardButton("📋 Duplicar para outro canal", callback_data=f"cfg:rec:clone:{msg_id}"),
                    InlineKeyboardButton("👀 Ver Prévia", callback_data=f"cfg:rec:preview:{msg_id}")
                ],
                [
                    InlineKeyboardButton("⚙️ Menu Completo", callback_data=f"cfg:rec:detail:{msg_id}"),
                    InlineKeyboardButton("📋 Lista de Mensagens", callback_data="cfg:rec:list")
                ]
            ])
            reply_txt = f"✅ *{total_btns} botão(ões) em {len(extracted_buttons)} linha(s) configurados com sucesso na mensagem #{msg_id}!*"
            try:
                await msg.reply_text(reply_txt, parse_mode=ParseMode.MARKDOWN, reply_markup=markup)
            except Exception:
                await msg.reply_text(reply_txt.replace("*", ""), reply_markup=markup)
            return True

        elif action == "rec_title":
            msg_id = state.get("msg_id", 1)
            val = (msg.text or "").strip()
            if not val:
                await msg.reply_text("⚠️ Envie um texto válido para o nome ou /cancelar.")
                return True
            rec_list = cfg.setdefault("recurring_messages", [])
            target_item = next((m for m in rec_list if m.get("id") == msg_id), None)
            if target_item:
                if val.lower() in ("limpar", "padrao", "padrão", "remover"):
                    target_item.pop("title", None)
                else:
                    target_item["title"] = val
                save_config(cfg)
            del self.pending_inputs[user.id]

            new_title = get_recurring_title(target_item) if target_item else val
            markup = InlineKeyboardMarkup([
                [InlineKeyboardButton("⚙️ Voltar à Mensagem", callback_data=f"cfg:rec:detail:{msg_id}")],
                [InlineKeyboardButton("📋 Lista de Mensagens", callback_data="cfg:rec:list")]
            ])
            await msg.reply_text(
                f"✅ *Nome da Mensagem #{msg_id} atualizado para:* `{new_title}`",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=markup
            )
            return True

        elif action == "rec_article":
            msg_id = state.get("msg_id")
            if not msg.text:
                await msg.reply_text("⚠️ Envie um link válido ou digite /cancelar.")
                return True

            val = msg.text.strip()
            rec_list = cfg.get("recurring_messages", [])
            for item in rec_list:
                if item.get("id") == msg_id:
                    if val.lower() in ("remover", "apagar", "nenhum", "off"):
                        item["article_url"] = None
                    else:
                        if not (val.startswith("http://") or val.startswith("https://") or val.startswith("t.me/")):
                            val = "https://" + val
                        item["article_url"] = val
                    break
            save_config(cfg)
            del self.pending_inputs[user.id]

            markup = InlineKeyboardMarkup([
                [InlineKeyboardButton("⚙️ Voltar à Mensagem", callback_data=f"cfg:rec:detail:{msg_id}")],
                [InlineKeyboardButton("📋 Lista de Mensagens", callback_data="cfg:rec:list")]
            ])
            msg_txt = "✅ *Artigo removido com sucesso!*" if val.lower() in ("remover", "apagar", "nenhum", "off") else f"✅ *Artigo da Mensagem #{msg_id} salvo com sucesso!*\nLink: `{val}`\n\nA prévia do artigo será exibida no topo do envio!"
            await msg.reply_text(msg_txt, parse_mode=ParseMode.MARKDOWN, reply_markup=markup)
            return True

        elif action == "rec_msg_cnt":
            msg_id = state.get("msg_id")
            if not msg.text or not msg.text.strip().isdigit():
                await msg.reply_text("⚠️ Por favor, digite um número inteiro de mensagens (ex: 50) ou /cancelar.")
                return True
            cnt = int(msg.text.strip())
            if cnt <= 0:
                await msg.reply_text("⚠️ O número de mensagens deve ser maior que 0.")
                return True
            rec_list = cfg.get("recurring_messages", [])
            for item in rec_list:
                if item.get("id") == msg_id:
                    item["repeat_mode"] = "messages"
                    item["messages_interval"] = cnt
                    break
            save_config(cfg)
            del self.pending_inputs[user.id]
            text, markup = generate_recurring_msg_menu(cfg, msg_id)
            await msg.reply_text(f"✅ Repetição definida para a cada *{cnt} mensagens*!", parse_mode=ParseMode.MARKDOWN, reply_markup=markup)
            return True

        elif action in ("rec_dstart", "rec_dend"):
            msg_id = state.get("msg_id")
            field = "start_date" if action == "rec_dstart" else "end_date"
            raw = msg.text.strip()
            date_val = None
            try:
                if "/" in raw:
                    parts = raw.split("/")
                    if len(parts) == 3:
                        d, m, y = int(parts[0]), int(parts[1]), int(parts[2])
                        date_val = f"{y:04d}-{m:02d}-{d:02d}"
                elif "-" in raw:
                    parts = raw.split("-")
                    if len(parts) == 3:
                        y, m, d = int(parts[0]), int(parts[1]), int(parts[2])
                        date_val = f"{y:04d}-{m:02d}-{d:02d}"
            except Exception:
                pass

            if not date_val:
                await msg.reply_text("⚠️ Formato de data inválido. Use DD/MM/AAAA (ex: 25/12/2026) ou digite /cancelar.")
                return True

            rec_list = cfg.get("recurring_messages", [])
            for item in rec_list:
                if item.get("id") == msg_id:
                    item[field] = date_val
                    break
            save_config(cfg)
            del self.pending_inputs[user.id]
            title = "Data de Início" if field == "start_date" else "Data Final"
            text, markup = generate_recurring_detail(cfg, msg_id)
            await msg.reply_text(f"✅ *{title}* definida para `{date_val}`!", parse_mode=ParseMode.MARKDOWN, reply_markup=markup)
            return True

        # -------------------------------------------------------------
        # 3. ADICIONAR / REMOVER PALAVRAS PROIBIDAS
        # -------------------------------------------------------------
        elif action == "banned_add":
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

        elif action == "banned_remove":
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

        # -------------------------------------------------------------
        # 4. CONFIGURAÇÃO DE RESPOSTAS AUTOMÁTICAS (REGEX & PALAVRAS)
        # -------------------------------------------------------------
        elif action == "resp_edit_text":
            item_id = state.get("item_id")
            raw_text, photo_id, extracted_buttons, src_chat_id, src_msg_id, bak_chat_id, bak_msg_id = await self._extract_message_content(msg, context, user.id)

            responders = cfg.setdefault("auto_responses", [])
            for item in responders:
                if item.get("id") == item_id:
                    if raw_text:
                        item["text"] = raw_text
                    if photo_id:
                        item["photo"] = photo_id
                    if extracted_buttons:
                        item["buttons"] = extracted_buttons
                    break
            save_config(cfg)
            if self.auto_responder_handler:
                self.auto_responder_handler.invalidate_cache(item_id)
            del self.pending_inputs[user.id]

            summary_items = ["• *Texto:* Atualizado com formatação rica"]
            if photo_id:
                summary_items.append("• *Foto:* Imagem salva com sucesso")
            if extracted_buttons:
                total_btns = sum(len(r) for r in extracted_buttons)
                summary_items.append(f"• *Botões:* {total_btns} botão(ões) capturados!")

            summary_str = "\n".join(summary_items)
            markup = InlineKeyboardMarkup([
                [InlineKeyboardButton("⚙️ Voltar à Resposta", callback_data=f"cfg:resp:detail:{item_id}")],
                [InlineKeyboardButton("📋 Lista de Respostas", callback_data="cfg:resp:list")]
            ])
            await msg.reply_text(f"✅ *Resposta #{item_id} atualizada com sucesso!*\n\n{summary_str}", parse_mode=ParseMode.MARKDOWN, reply_markup=markup)
            return True

        elif action == "resp_edit_pattern":
            item_id = state.get("item_id")
            if not msg.text:
                await msg.reply_text("⚠️ Envie o gatilho/expressão ou /cancelar.")
                return True

            new_pat = msg.text.strip()
            responders = cfg.setdefault("auto_responses", [])
            target = next((r for r in responders if r.get("id") == item_id), None)
            if target and target.get("is_regex", True):
                valid, err = validate_regex(new_pat)
                if not valid:
                    await msg.reply_text(
                        f"❌ *Expressão Regular (Regex) Inválida!*\n\nErro: `{err}`\n\n"
                        "💡 *Dicas de sintaxe:*\n"
                        "• Para palavras exatas: `(?i)\\b(pix|chave)\\b`\n"
                        "• Para alternativas: `(?i)ajuda|suporte|duvida`\n\n"
                        "Envie a regex corrigida ou digite /cancelar:",
                        parse_mode=ParseMode.MARKDOWN
                    )
                    return True

            if target:
                target["pattern"] = new_pat
            save_config(cfg)
            if self.auto_responder_handler:
                self.auto_responder_handler.invalidate_cache(item_id)
            del self.pending_inputs[user.id]

            markup = InlineKeyboardMarkup([
                [InlineKeyboardButton("⚙️ Voltar à Resposta", callback_data=f"cfg:resp:detail:{item_id}")],
                [InlineKeyboardButton("📋 Lista de Respostas", callback_data="cfg:resp:list")]
            ])
            await msg.reply_text(f"✅ *Gatilho da resposta #{item_id} atualizado para:* `{new_pat}`", parse_mode=ParseMode.MARKDOWN, reply_markup=markup)
            return True

        elif action == "resp_edit_title":
            item_id = state.get("item_id")
            if not msg.text:
                await msg.reply_text("⚠️ Envie um título ou /cancelar.")
                return True

            new_title = msg.text.strip()
            responders = cfg.setdefault("auto_responses", [])
            for item in responders:
                if item.get("id") == item_id:
                    item["title"] = new_title
                    break
            save_config(cfg)
            del self.pending_inputs[user.id]

            markup = InlineKeyboardMarkup([
                [InlineKeyboardButton("⚙️ Voltar à Resposta", callback_data=f"cfg:resp:detail:{item_id}")],
                [InlineKeyboardButton("📋 Lista de Respostas", callback_data="cfg:resp:list")]
            ])
            await msg.reply_text(f"✅ *Título alterado para:* `{new_title}`", parse_mode=ParseMode.MARKDOWN, reply_markup=markup)
            return True

        elif action == "resp_edit_photo":
            item_id = state.get("item_id")
            if not msg.photo:
                await msg.reply_text("⚠️ Por favor envie uma FOTO/IMAGEM ou digite /cancelar.")
                return True

            file_id = msg.photo[-1].file_id
            responders = cfg.setdefault("auto_responses", [])
            for item in responders:
                if item.get("id") == item_id:
                    item["photo"] = file_id
                    break
            save_config(cfg)
            del self.pending_inputs[user.id]

            markup = InlineKeyboardMarkup([
                [InlineKeyboardButton("⚙️ Voltar à Resposta", callback_data=f"cfg:resp:detail:{item_id}")],
                [InlineKeyboardButton("📋 Lista de Respostas", callback_data="cfg:resp:list")]
            ])
            await msg.reply_text(f"✅ *Foto da resposta #{item_id} configurada com sucesso!*", parse_mode=ParseMode.MARKDOWN, reply_markup=markup)
            return True

        elif action == "resp_edit_buttons":
            item_id = state.get("item_id")
            if not msg.text:
                await msg.reply_text("⚠️ Envie os botões ou /cancelar.")
                return True

            if msg.text.strip().lower() in ("remover", "limpar", "nenhum"):
                responders = cfg.setdefault("auto_responses", [])
                for item in responders:
                    if item.get("id") == item_id:
                        item["buttons"] = []
                        break
                save_config(cfg)
                del self.pending_inputs[user.id]
                markup = InlineKeyboardMarkup([[InlineKeyboardButton("⚙️ Voltar", callback_data=f"cfg:resp:detail:{item_id}")]])
                await msg.reply_text(f"✅ *Botões removidos da resposta #{item_id}!*", parse_mode=ParseMode.MARKDOWN, reply_markup=markup)
                return True

            new_buttons = self._parse_buttons(msg.text)
            if not new_buttons:
                await msg.reply_text("⚠️ Nenhum botão válido detectado.\nEnvie no formato: `Texto | https://link.com` ou /cancelar.", parse_mode=ParseMode.MARKDOWN)
                return True

            responders = cfg.setdefault("auto_responses", [])
            for item in responders:
                if item.get("id") == item_id:
                    item["buttons"] = new_buttons
                    break
            save_config(cfg)
            del self.pending_inputs[user.id]

            markup = InlineKeyboardMarkup([
                [InlineKeyboardButton("⚙️ Voltar à Resposta", callback_data=f"cfg:resp:detail:{item_id}")],
                [InlineKeyboardButton("📋 Lista de Respostas", callback_data="cfg:resp:list")]
            ])
            await msg.reply_text(f"✅ *{len(new_buttons)} botão(ões) configurado(s) na resposta #{item_id}!*", parse_mode=ParseMode.MARKDOWN, reply_markup=markup)
            return True

        # -------------------------------------------------------------
        # 5. CONFIGURAÇÃO DE CANAL DE LOGS
        # -------------------------------------------------------------
        elif action == "logs_set_id":
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

        # -------------------------------------------------------------
        # 6. CONFIGURAÇÃO DE TEMPO DE AUTO-APAGAR BOAS-VINDAS
        # -------------------------------------------------------------
        elif action == "welcome_autodel_time":
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

        # -------------------------------------------------------------
        # 7. CONFIGURAÇÃO DE FUSO HORÁRIO PERSONALIZADO
        # -------------------------------------------------------------
        elif action == "custom_timezone":
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

        # -------------------------------------------------------------
        # 7. ASSISTENTE DE TRANSMISSÃO GUIADA (WIZARD)
        # -------------------------------------------------------------
        elif action == "wiz_text":
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

        elif action == "wiz_media":
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

        elif action == "wiz_buttons":
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

        elif action == "wiz_sched_custom":
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

        elif action == "wiz_link_channel":
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


    def _parse_buttons(self, text: str) -> list:
        from modules.utils import parse_rich_buttons
        return parse_rich_buttons(text)

