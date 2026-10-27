import sys
import asyncio
from pathlib import Path
import logging

# Garante suporte a caracteres UTF-8 e emojis no terminal Windows
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    # Desativa QuickEdit Mode para evitar que cliques acidentais na janela congelem o bot
    try:
        import ctypes
        kernel32 = ctypes.windll.kernel32
        h_conin = kernel32.CreateFileW("CONIN$", 0xC0000000, 3, None, 3, 0, None)
        if h_conin and h_conin != -1:
            mode = ctypes.c_uint32()
            if kernel32.GetConsoleMode(h_conin, ctypes.byref(mode)):
                new_mode = (mode.value & ~0x0040) | 0x0080
                kernel32.SetConsoleMode(h_conin, new_mode)
    except Exception:
        pass

# Garante que o diretório do projeto esteja no sys.path
BASE_DIR = Path(__file__).resolve().parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from telegram import Update
from telegram.constants import ChatMemberStatus
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ChatJoinRequestHandler,
    ChatMemberHandler,
    InlineQueryHandler,
    filters,
    ContextTypes
)

import html
import json
from config import get_bot_token, load_config, save_config, add_linked_group, add_linked_channel
from modules.utils import AdminCache
from modules.logger_channel import send_mod_log
from modules.welcome import handle_new_members, handle_member_join, handle_rich_button_callback
from modules.antispam import AntispamHandler
from modules.antirepeat import AntirepeatHandler
from modules.admin_commands import AdminCommandHandler
from modules.panel import InteractivePanelHandler
from modules.auto_responder import AutoResponderHandler
from modules.recurring import process_recurring_messages_job, check_message_count_triggers, process_scheduled_transmissions_job
from modules.captcha import CaptchaHandler
from modules.join_requests import handle_chat_join_request
from modules.notes import NotesHandler
from modules.locks import LocksHandler
from modules.nightmode import NightModeHandler, check_night_mode_transitions_job
from modules.tutorial import TutorialHandler
from modules.inline_acervo import (
    acervo_db,
    handle_inline_acervo_query,
    cmd_acervo_dashboard,
    handle_acervo_callback,
    extract_media_from_message,
    import_universal_json,
    handle_private_document,
    cmd_limpar_acervo,
    cmd_limpar_textos,
    check_and_auto_reply_acervo
)

# Configuração de logging
logging.basicConfig(
    format="%(asctime)s - [%(levelname)s] - %(name)s: %(message)s",
    level=logging.INFO
)
# Reduz o ruído de checagens repetitivas das bibliotecas internas (deixa o log limpo e legível)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)
logging.getLogger("apscheduler").setLevel(logging.WARNING)

logger = logging.getLogger("TelegramGroupBot")

import os
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler

class CloudHealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-type", "text/plain; charset=utf-8")
        self.end_headers()
        self.wfile.write(b"Bot Telegram Online 24/7!")

    def log_message(self, format, *args):
        pass

def start_cloud_health_server():
    try:
        # Na Discloud, TYPE=bot não precisa nem deve abrir portas de rede
        if os.getenv("DISCLOUD") or os.getenv("DISCLOUD_APP_ID"):
            return
        port_str = os.getenv("PORT")
        if not port_str or not port_str.isdigit():
            return
        port = int(port_str)
        if port >= 1024:
            server = HTTPServer(("0.0.0.0", port), CloudHealthCheckHandler)
            t = threading.Thread(target=server.serve_forever, daemon=True)
            t.start()
            logger.info(f"Servidor de monitoramento em nuvem ativo na porta {port}")
    except Exception as e:
        logger.warning(f"Health check server ignorado: {e}")

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    """Trata erros inesperados para evitar encerramento do bot."""
    logger.error("Exceção capturada durante a execução:", exc_info=context.error)

def main():
    start_cloud_health_server()
    token = get_bot_token()
    if not token or token == "SEU_TOKEN_AQUI":
        print("\n" + "=" * 60)
        print("❌ ATENÇÃO: TOKEN DO TELEGRAM NÃO CONFIGURADO!")
        print("=" * 60)
        print("Para iniciar o bot, informe o seu Token:")
        print("1. Abra o arquivo 'config.json' e coloque o token no campo 'telegram_bot_token'")
        print("   OU crie um arquivo '.env' com a linha: TELEGRAM_BOT_TOKEN=seu_token_aqui")
        print("\nPara obter o token, converse com o @BotFather no Telegram.")
        print("=" * 60 + "\n")
        sys.exit(1)

    print("\n" + "=" * 60)
    print("🤖 Iniciando Bot de Gerenciamento do Grupo...")
    print("=" * 60)

    # Inicializa serviços compartilhados
    admin_cache = AdminCache(ttl=60)
    antispam_handler = AntispamHandler(admin_cache=admin_cache)
    antirepeat_handler = AntirepeatHandler(admin_cache=admin_cache)
    auto_responder_handler = AutoResponderHandler(admin_cache=admin_cache)
    admin_cmd_handler = AdminCommandHandler(
        admin_cache=admin_cache,
        user_warnings=antispam_handler.user_warnings
    )
    captcha_handler = CaptchaHandler()
    panel_handler = InteractivePanelHandler(
        admin_cache=admin_cache,
        auto_responder_handler=auto_responder_handler
    )
    notes_handler = NotesHandler(admin_cache=admin_cache)
    locks_handler = LocksHandler(admin_cache=admin_cache)
    nightmode_handler = NightModeHandler(admin_cache=admin_cache)
    tutorial_handler = TutorialHandler()

    async def on_new_members(update: Update, context: ContextTypes.DEFAULT_TYPE):
        await handle_new_members(update, context, captcha_handler=captcha_handler)

    async def on_my_chat_member(update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Detecta automaticamente quando o bot é adicionado como administrador em grupos ou canais."""
        if not update.my_chat_member:
            return
        chat = update.my_chat_member.chat
        new_status = update.my_chat_member.new_chat_member.status
        cfg = load_config()

        if new_status in (ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.MEMBER):
            if chat.type in ("group", "supergroup"):
                add_linked_group(cfg, chat.id, chat.title or "Grupo", chat.type)
                logger.info(f"Bot registrado/atualizado no grupo {chat.title} ({chat.id})")
            elif chat.type == "channel":
                ch_user = f"@{chat.username}" if chat.username else ""
                add_linked_channel(cfg, chat.id, chat.title or f"Canal {chat.id}", ch_user)
                logger.info(f"Bot registrado/atualizado como admin no canal {chat.title} ({chat.id})")

    async def on_chat_member_updated(update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Monitora e registra em tempo real quando pessoas entram ou saem de canais e grupos vinculados."""
        if not update.chat_member:
            return

        chat = update.chat_member.chat
        old_m = update.chat_member.old_chat_member
        new_m = update.chat_member.new_chat_member

        user = new_m.user if new_m else (old_m.user if old_m else None)
        if not user or user.is_bot:
            return

        old_status = old_m.status if old_m else None
        new_status = new_m.status if new_m else None

        is_channel = chat.type == "channel"
        chat_type_label = "Canal" if is_channel else "Grupo"
        chat_name = f"{chat.title} (@{chat.username})" if chat.username else (chat.title or str(chat.id))

        user_info = f"<b>{html.escape(user.full_name)}</b>"
        if user.username:
            user_info += f" (@{user.username})"
        user_info += f" [ID: <code>{user.id}</code>]"

        # 1. Alguém se inscreveu no canal ou entrou no grupo
        if old_status in (ChatMemberStatus.LEFT, ChatMemberStatus.BANNED, None) and new_status in (ChatMemberStatus.MEMBER, ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.RESTRICTED):
            action_title = f"Nova Inscrição no {chat_type_label}" if is_channel else "Novo Membro no Grupo"
            await send_mod_log(
                bot=context.bot,
                event_type="join",
                title=action_title,
                user_info=user_info,
                details=f"📍 <b>Local:</b> {html.escape(chat_name)}"
            )
            logger.info(f"[{chat_type_label}] {user.full_name} ({user.id}) se inscreveu/entrou em {chat_name}")

            # Se for entrada em GRUPO ou SUPERGRUPO, dispara as boas-vindas oficiais com desduplicação!
            if chat.type in ("group", "supergroup") and new_status != ChatMemberStatus.ADMINISTRATOR:
                try:
                    await handle_member_join(chat, user, context, captcha_handler=captcha_handler)
                except Exception as e_w:
                    logger.error(f"Erro ao disparar boas-vindas via on_chat_member_updated no grupo {chat.id}: {e_w}")

        # 2. Alguém cancelou a inscrição / saiu
        elif old_status in (ChatMemberStatus.MEMBER, ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.RESTRICTED) and new_status == ChatMemberStatus.LEFT:
            action_title = f"Inscrição Cancelada no {chat_type_label}" if is_channel else "Membro Saiu do Grupo"
            await send_mod_log(
                bot=context.bot,
                event_type="leave",
                title=action_title,
                user_info=user_info,
                details=f"📍 <b>Local:</b> {html.escape(chat_name)}"
            )
            logger.info(f"[{chat_type_label}] {user.full_name} ({user.id}) cancelou inscrição/saiu de {chat_name}")

    async def on_channel_post(update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Auto-vincula o canal e auto-indexa partituras/áudios no acervo global instantaneamente."""
        msg = update.channel_post or update.edited_channel_post
        if not msg or not msg.chat or msg.chat.type != "channel":
            return
        chat = msg.chat
        cfg = load_config()
        ch_user = f"@{chat.username}" if chat.username else ""
        title = chat.title or f"Canal {chat.id}"
        add_linked_channel(cfg, chat.id, title, ch_user)
        logger.info(f"Canal auto-vinculado via postagem no canal: {title} ({chat.id})")

        # Auto-indexação no Acervo Global de Partituras
        media_info = extract_media_from_message(msg)
        if media_info:
            added = acervo_db.add_item(
                file_id=media_info["file_id"],
                channel_id=chat.id,
                message_id=msg.message_id,
                file_name=media_info.get("file_name", ""),
                title=media_info.get("title", ""),
                caption=media_info.get("caption", ""),
                file_type=media_info.get("file_type", "document"),
                file_size=media_info.get("file_size", 0),
                file_unique_id=media_info.get("file_unique_id", ""),
                channel_title=title,
                channel_username=ch_user
            )
            if added:
                logger.info(f"[Acervo] ⚡ Auto-indexada partitura do canal '{title}': {media_info.get('file_name')} (ID: {msg.message_id})")
                if cfg.get("log_channel_id"):
                    try:
                        stats = acervo_db.get_stats()
                        tot = stats.get("total_files", 0)
                        fn = media_info.get("file_name", "partitura")
                        t = media_info.get("title", fn)
                        await send_mod_log(
                            bot=context.bot,
                            event_type="acervo",
                            title="⚡ Nova Partitura Auto-Indexada",
                            user_info=f"📢 Canal <b>{html.escape(title)}</b>",
                            details=(
                                f"🎼 <b>Título:</b> {html.escape(t)}\n"
                                f"📁 <b>Arquivo:</b> <code>{html.escape(fn)}</code>\n"
                                f"📊 <b>Total no Acervo:</b> <code>{tot}</code> partituras"
                            )
                        )
                    except Exception as e_log:
                        logger.debug(f"Erro ao enviar log de acervo: {e_log}")

    async def on_group_migration(update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Atualiza automaticamente o ID de chats que migraram para supergrupo."""
        msg = update.effective_message
        if not msg:
            return
        old_id = msg.chat.id
        new_id = getattr(msg, "migrate_to_chat_id", None)
        if new_id:
            cfg = load_config()
            logger.info(f"Chat migrou de {old_id} para o supergrupo oficial {new_id}!")
            for g in cfg.get("linked_groups", []):
                if g.get("id") == old_id:
                    g["id"] = new_id
                    g["type"] = "supergroup"
            for c in cfg.get("linked_channels", []):
                if c.get("id") == old_id:
                    c["id"] = new_id
            if cfg.get("main_group_id") == old_id:
                cfg["main_group_id"] = new_id
            save_config(cfg)

    async def on_pinned_service_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Apaga automaticamente a notificação de serviço que o Telegram gera quando uma mensagem é fixada."""
        msg = update.effective_message
        chat = update.effective_chat
        if not msg or not chat:
            return
        cfg = load_config()
        if cfg.get("delete_pinned_service_messages", True):
            from modules.utils import safe_delete_message
            await safe_delete_message(context.bot, chat.id, msg.message_id)
            logger.info(f"[Pin Cleanup] Notificação de fixação {msg.message_id} apagada no chat {chat.id}")

    async def filter_message_pipeline(update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Pipeline que processa as mensagens de texto e mídia para antispam, anti-repetição, locks, modo noturno e auto-respostas."""
        if not update.effective_message:
            return

        chat = update.effective_chat
        user = update.effective_user

        # Memoriza e sincroniza automaticamente o ID dos grupos vinculados
        if chat and chat.type in ("group", "supergroup"):
            cfg = load_config()
            add_linked_group(cfg, chat.id, chat.title or "Grupo", chat.type)

        # 0. Intercepta entradas de administradores configurando texto, foto ou botões no painel
        if await panel_handler.handle_pending_input(update, context):
            return

        # Se for mensagem no chat privado com o bot e não for comando:
        if chat and chat.type == "private":
            msg = update.effective_message
            fwd_chat = None
            if msg:
                fwd_orig = getattr(msg, "forward_origin", None)
                if fwd_orig and getattr(fwd_orig, "chat", None):
                    if fwd_orig.chat.type in ("channel", "supergroup", "group"):
                        fwd_chat = fwd_orig.chat
                elif getattr(msg, "forward_from_chat", None):
                    legacy_fwd = getattr(msg, "forward_from_chat", None)
                    if legacy_fwd and getattr(legacy_fwd, "type", "") in ("channel", "supergroup", "group"):
                        fwd_chat = legacy_fwd

            # Auto-vínculo inteligente se encaminhou mensagem de um canal/supergrupo no privado
            if fwd_chat:
                cfg = load_config()
                try:
                    bot_me = await context.bot.get_me()
                    bot_member = await fwd_chat.get_member(bot_me.id)
                    if bot_member.status in ("administrator", "creator"):
                        ch_user = f"@{fwd_chat.username}" if fwd_chat.username else ""
                        title = fwd_chat.title or f"Chat {fwd_chat.id}"
                        add_linked_channel(cfg, fwd_chat.id, title, ch_user)
                        total_c = len(cfg.get("linked_channels", []))
                        chat_type_lbl = "Canal" if fwd_chat.type == "channel" else "Supergrupo"
                        from telegram import InlineKeyboardMarkup, InlineKeyboardButton
                        kb = InlineKeyboardMarkup([
                            [InlineKeyboardButton("📢 Fazer um Comunicado Agora", callback_data="cfg:wiz:start")],
                            [InlineKeyboardButton(f"📋 Ver Destinos Vinculados ({total_c})", callback_data="cfg:chats:list")]
                        ])
                        await msg.reply_text(
                            f"🎉 <b>{chat_type_lbl} Vinculado Automaticamente!</b> 📢\n\n"
                            f"• <b>Nome:</b> {html.escape(title)}\n"
                            f"• <b>ID:</b> <code>{fwd_chat.id}</code>\n"
                            f"• <b>Tipo:</b> <code>{fwd_chat.type}</code>\n"
                            f"• <b>Link:</b> {html.escape(ch_user or 'Privado')}\n\n"
                            f"O bot detectou a mensagem encaminhada, conferiu que é Administrador e salvou como destino de transmissão!\n"
                            f"Total de canais/destinos vinculados agora: <b>{total_c}</b>.",
                            parse_mode=ParseMode.HTML,
                            reply_markup=kb
                        )
                        return
                    else:
                        chat_type_lbl = "Canal" if fwd_chat.type == "channel" else "Grupo"
                        await msg.reply_text(
                            f"⚠️ <b>{chat_type_lbl} Detectado:</b> {html.escape(fwd_chat.title or '')}\n\n"
                            f"Porém este bot ainda não é <b>Administrador</b> com permissão de postar mensagens.\n"
                            f"Adicione o bot como Administrador no {chat_type_lbl.lower()} e encaminhe a mensagem novamente!",
                            parse_mode=ParseMode.HTML
                        )
                        return
                except Exception as e:
                    logger.warning(f"Erro ao verificar chat encaminhado: {e}")

            # 1. Detecção automática de arquivo JSON de partituras (Telegram Desktop result.json ou banco legado)
            if msg and msg.document and msg.document.file_name and msg.document.file_name.lower().endswith(".json"):
                cfg = load_config()
                try:
                    status_pending = await msg.reply_text("📥 <i>Processando arquivo de partituras JSON...</i>", parse_mode=ParseMode.HTML)
                    doc_file = await context.bot.get_file(msg.document.file_id)
                    file_bytes = await doc_file.download_as_bytearray()
                    json_str = file_bytes.decode("utf-8", errors="replace")
                    parsed_data = json.loads(json_str)

                    import_res = import_universal_json(parsed_data, fallback_channel_id=cfg.get("main_channel_id"))
                    if import_res.get("success"):
                        count = import_res.get("count", 0)
                        chan_title = import_res.get("channel_title", "Canais")
                        stats = acervo_db.get_stats()
                        total_acervo = stats.get("total_files", 0)
                        bot_me = await context.bot.get_me()
                        bot_user = bot_me.username or "botpartituras_bot"

                        from telegram import InlineKeyboardMarkup, InlineKeyboardButton
                        await status_pending.edit_text(
                            f"🎉 <b>IMPORTAÇÃO DO ACERVO CONCLUÍDA!</b> 🎼\n\n"
                            f"• <b>Origem:</b> {html.escape(chan_title)}\n"
                            f"• <b>Partituras Processadas:</b> <code>{count}</code>\n"
                            f"• <b>Total Geral no Acervo:</b> <code>{total_acervo}</code>\n\n"
                            f"💡 <b>Teste a busca instantânea agora mesmo:</b>\n"
                            f"Digite em qualquer chat: <code>@{bot_user} Harpa 15</code>",
                            parse_mode=ParseMode.HTML,
                            reply_markup=InlineKeyboardMarkup([
                                [InlineKeyboardButton("🔍 Testar Busca Agora", switch_inline_query_current_chat="")],
                                [InlineKeyboardButton("🎼 Ver Acervo", callback_data="acervo:menu")]
                            ])
                        )
                        return
                    else:
                        await status_pending.edit_text(
                            f"⚠️ <b>Não foi possível importar:</b> {html.escape(import_res.get('error', 'Formato desconhecido'))}\n\n"
                            f"Certifique-se de exportar o canal no Telegram Desktop em formato JSON (result.json).",
                            parse_mode=ParseMode.HTML
                        )
                        return
                except Exception as e_json:
                    logger.error(f"Erro ao processar JSON no privado: {e_json}", exc_info=True)
                    await msg.reply_text(f"❌ <b>Erro ao ler arquivo JSON:</b> <code>{html.escape(str(e_json))}</code>", parse_mode=ParseMode.HTML)
                    return

            # 2. Detecção automática de partituras/áudios enviados ou encaminhados no privado
            media_info = extract_media_from_message(msg)
            if media_info:
                src_channel_id = None
                src_channel_title = "Acervo Direto"
                src_username = ""
                orig_msg_id = msg.message_id

                fwd_origin = getattr(msg, "forward_origin", None)
                legacy_fwd = getattr(msg, "forward_from_chat", None)

                if fwd_chat:
                    src_channel_id = fwd_chat.id
                    src_channel_title = fwd_chat.title or "Canal"
                    src_username = fwd_chat.username or ""
                    orig_msg_id = getattr(msg, "forward_from_message_id", None) or getattr(fwd_origin, "message_id", None) or msg.message_id
                elif fwd_origin and getattr(fwd_origin, "chat", None):
                    f_c = fwd_origin.chat
                    src_channel_id = f_c.id
                    src_channel_title = getattr(f_c, "title", "Canal") or "Canal"
                    src_username = getattr(f_c, "username", "") or ""
                    orig_msg_id = getattr(fwd_origin, "message_id", None) or msg.message_id
                elif legacy_fwd:
                    src_channel_id = legacy_fwd.id
                    src_channel_title = getattr(legacy_fwd, "title", "Canal") or "Canal"
                    src_username = getattr(legacy_fwd, "username", "") or ""
                    orig_msg_id = getattr(msg, "forward_from_message_id", None) or msg.message_id
                else:
                    cfg = load_config()
                    src_channel_id = cfg.get("main_channel_id") or -1001806380183

                added = acervo_db.add_item(
                    file_id=media_info["file_id"],
                    channel_id=src_channel_id,
                    message_id=orig_msg_id,
                    file_name=media_info.get("file_name", ""),
                    title=media_info.get("title", ""),
                    caption=media_info.get("caption", ""),
                    file_type=media_info.get("file_type", "document"),
                    file_size=media_info.get("file_size", 0),
                    file_unique_id=media_info.get("file_unique_id", ""),
                    channel_title=src_channel_title,
                    channel_username=src_username
                )
                if added:
                    stats = acervo_db.get_stats()
                    tot = stats.get("total_files", 0)
                    fn = media_info.get("file_name", "partitura")
                    from telegram import InlineKeyboardMarkup, InlineKeyboardButton
                    await msg.reply_text(
                        f"🎼 <b>Partitura Adicionada ao Acervo!</b>\n\n"
                        f"• <b>Arquivo:</b> <code>{html.escape(fn)}</code>\n"
                        f"• <b>Origem:</b> {html.escape(src_channel_title)}\n"
                        f"• <b>Total no Acervo:</b> <code>{tot}</code> itens\n\n"
                        f"<i>Disponível imediatamente na busca inline (@)!</i>",
                        parse_mode=ParseMode.HTML,
                        reply_markup=InlineKeyboardMarkup([
                            [InlineKeyboardButton("🔍 Testar Busca", switch_inline_query_current_chat="")],
                            [InlineKeyboardButton("🎼 Ver Acervo", callback_data="acervo:menu")]
                        ])
                    )
                    return

            # 2.5 Checa se o usuário tocou em um dos botões do menu na área de conversa (Reply Keyboard)
            from modules.whitelist import handle_conversation_menu_button
            if await handle_conversation_menu_button(update, context):
                return

            # 3. Se for pedido ou busca de partitura no privado, responde direto com o acervo!
            if await check_and_auto_reply_acervo(update, context):
                return

            # Oferece ações interativas imediatas (NUNCA fica no vácuo ou mudo)
            await panel_handler.handle_unsolicited_private_message(update, context)
            return

        # Limpeza defensiva: se algum membro enviar texto de botão de menu no grupo, apaga e remove o teclado
        MENU_BUTTON_TEXTS = {
            "🎛️ Painel de Controle", "🎼 Acervo de Partituras",
            "📢 Meus Canais", "👥 Meus Grupos",
            "🛡️ Whitelist & Links", "❓ Ajuda & Comandos"
        }
        msg = update.effective_message
        if msg and msg.text in MENU_BUTTON_TEXTS:
            from telegram import ReplyKeyboardRemove
            try:
                await msg.delete()
                # Força o Telegram do usuário a esconder o teclado do grupo
                cl = await chat.send_message("🧹", reply_markup=ReplyKeyboardRemove())
                await cl.delete()
            except Exception:
                pass
            return

        # 1. Checa Silêncio Noturno (Modo Noturno estilo Rose Bot)
        if await nightmode_handler.check_night_mode(update, context):
            return

        # 2. Checa Bloqueios de Mídia (/lock estilo Rose Bot)
        if await locks_handler.check_locks(update, context):
            return

        # 3. Checa Antispam / Flood / Palavras Proibidas / Links
        handled = await antispam_handler.handle_message(update, context)
        if handled:
            return

        # 4. Checa Mensagens Repetidas (Anti-Repeat)
        if await antirepeat_handler.handle_message(update, context):
            return

        # 5. Checa Hashtags de Notas salvas (#nota estilo Rose Bot)
        if await notes_handler.check_hashtag_note(update, context):
            return

        # 5.5 Auto-Sugestão Inteligente de Partituras no Grupo (Acervo Global com 17.151 partituras)
        if await check_and_auto_reply_acervo(update, context):
            return

        # 6. Respostas Automáticas Personalizadas com Regex & Palavras-Chave
        await auto_responder_handler.handle_message(update, context)

        # 7. Checa Mensagens Repetidas por Contagem no Grupo (ex: a cada 50 mensagens)
        if chat and chat.type in ("group", "supergroup"):
            await check_message_count_triggers(context.bot, chat.id, job_queue=context.job_queue)

    BACKGROUND_TASKS = set()

    async def background_scheduler(application):
        """Loop autônomo e resiliente de segundo plano (independente de JobQueue/APScheduler)."""
        logger.info("Agendador autônomo de segundo plano (Loop Contínuo) iniciado!")
        print("🚀 [SISTEMA] Agendador autônomo de segundo plano (Loop Contínuo) iniciado!")
        await asyncio.sleep(3)
        while True:
            try:
                await process_recurring_messages_job(application.bot, job_queue=application.job_queue)
            except Exception as e_rec:
                logger.error(f"Erro no ciclo de mensagens recorrentes: {e_rec}", exc_info=True)

            try:
                await process_scheduled_transmissions_job(application.bot)
            except Exception as e_sched:
                logger.error(f"Erro no ciclo de transmissões agendadas: {e_sched}", exc_info=True)

            try:
                await check_night_mode_transitions_job(application.bot)
            except Exception as e_nm:
                logger.error(f"Erro no ciclo de modo noturno: {e_nm}", exc_info=True)

            await asyncio.sleep(10)

    async def post_init(application):
        task = asyncio.create_task(background_scheduler(application))
        BACKGROUND_TASKS.add(task)
        application.bot_data["_bg_scheduler_task"] = task

        # Auto-limpeza silenciosa de mensagens de texto espúrias do acervo na inicialização
        async def run_startup_purge():
            try:
                purged = acervo_db.purge_text_chatter()
                if purged > 0:
                    logger.info(f"[Acervo] 🧹 Auto-limpeza inicial removeu {purged} mensagens de texto do acervo.")
            except Exception as e_p:
                logger.debug(f"[Acervo] Erro na auto-limpeza inicial: {e_p}")

        asyncio.create_task(run_startup_purge())

        # Configura lista de comandos visíveis no botão Menu EXCLUSIVAMENTE NO PRIVADO (Zero no grupo)
        try:
            from telegram import BotCommand, BotCommandScopeAllPrivateChats, BotCommandScopeAllGroupChats, BotCommandScopeDefault
            private_commands = [
                BotCommand("painel", "Abrir Painel de Controle Principal"),
                BotCommand("menu", "Menu de Botões na Área de Conversa"),
                BotCommand("acervo", "Acervo Global de Partituras"),
                BotCommand("whitelist", "Usuários Livres e Links Permitidos"),
                BotCommand("canais", "Ver Canais Vinculados"),
                BotCommand("grupos", "Ver Grupos Vinculados"),
                BotCommand("status", "Status e Proteções do Grupo"),
                BotCommand("ajuda", "Guia Completo de Comandos")
            ]
            # Exclusivo no chat privado!
            await application.bot.set_my_commands(private_commands, scope=BotCommandScopeAllPrivateChats())
            # Deleta comandos nos grupos para NENHUM membro ver nem ativar nada no grupo!
            await application.bot.delete_my_commands(scope=BotCommandScopeAllGroupChats())
            await application.bot.delete_my_commands(scope=BotCommandScopeDefault())
            logger.info("Comandos do menu configurados: 100% no privado, 0 nos grupos!")
        except Exception as e_cmd:
            logger.debug(f"Não foi possível configurar bot commands: {e_cmd}")

    # Constrói o Application do python-telegram-bot
    app = ApplicationBuilder().token(token).post_init(post_init).build()

    # Registra erro
    app.add_error_handler(error_handler)

    # 1. Evento de Boas-Vindas e Verificação Anti-Bot (CAPTCHA)
    app.add_handler(
        MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS, on_new_members)
    )

    # Solicitações de entrada no grupo (Join Requests)
    app.add_handler(ChatJoinRequestHandler(handle_chat_join_request))

    # Auto-detecção e vínculo automático ao ser adicionado como administrador em grupos ou canais
    app.add_handler(ChatMemberHandler(on_my_chat_member, ChatMemberHandler.MY_CHAT_MEMBER))

    # Auto-detecção e vínculo automático quando qualquer postagem for feita no canal (novas ou editadas)
    app.add_handler(MessageHandler(filters.ChatType.CHANNEL | filters.UpdateType.EDITED_CHANNEL_POST, on_channel_post))

    # Auto-migração e sincronização de ID quando grupos viram supergrupos no Telegram
    app.add_handler(MessageHandler(filters.StatusUpdate.MIGRATE, on_group_migration))

    # Auto-exclusão de avisos de serviço de mensagens fixadas no grupo ou canal
    app.add_handler(MessageHandler(filters.StatusUpdate.PINNED_MESSAGE, on_pinned_service_message), group=-2)

    # Monitora entradas e saídas de membros em canais e grupos em tempo real
    app.add_handler(ChatMemberHandler(on_chat_member_updated, ChatMemberHandler.CHAT_MEMBER))

    # Callbacks de CAPTCHA
    app.add_handler(CallbackQueryHandler(captcha_handler.handle_callback, pattern=r"^captcha:"))

    # Callbacks da Central de Ajuda
    app.add_handler(CallbackQueryHandler(admin_cmd_handler.handle_help_callback, pattern=r"^help:"))

    # Callbacks de Notas
    app.add_handler(CallbackQueryHandler(notes_handler.handle_callback, pattern=r"^note:"))

    # Callbacks da Central de Tutoriais
    app.add_handler(CallbackQueryHandler(tutorial_handler.handle_callback, pattern=r"^tut:"))

    # Callbacks de Transmissão (/falar)
    app.add_handler(CallbackQueryHandler(admin_cmd_handler.handle_falar_callback, pattern=r"^falar:"))

    # Callbacks de Destino do /anunciar
    app.add_handler(CallbackQueryHandler(admin_cmd_handler.handle_anunciar_callback, pattern=r"^cfg:anunciar:"))

    # Callbacks de Botões Interativos de Boas-Vindas (Regras, Tutorial, Avisos em modal na tela)
    app.add_handler(CallbackQueryHandler(handle_rich_button_callback, pattern=r"^btn:"))

    # Handler prioritário para documentos enviados no privado (JSON do Acervo / Partituras)
    app.add_handler(
        MessageHandler(filters.ChatType.PRIVATE & filters.Document.ALL, handle_private_document),
        group=-1
    )

    # 0. Busca Instantânea no Acervo Global de Partituras (Inline Mode: @Bot Harpa 15)
    app.add_handler(InlineQueryHandler(handle_inline_acervo_query))

    # Callbacks do Acervo de Partituras
    app.add_handler(CallbackQueryHandler(handle_acervo_callback, pattern=r"^acervo:"))

    # 2. Comandos Administrativos e Utilitários
    app.add_handler(CommandHandler(["acervo", "partituras", "partitura", "buscarpartitura"], cmd_acervo_dashboard))
    app.add_handler(CommandHandler(["limpar_acervo", "limparacervo", "resetacervo"], cmd_limpar_acervo))
    app.add_handler(CommandHandler(["limpar_textos", "limpartextos", "purgartextos"], cmd_limpar_textos))
    app.add_handler(CommandHandler(["config", "painel", "settings", "status"], panel_handler.cmd_config))
    app.add_handler(CommandHandler(["comunicado", "transmissao", "wizard"], panel_handler.cmd_comunicado))
    app.add_handler(CommandHandler(["agendados", "transmissoes", "agenda"], panel_handler.cmd_agendados))
    app.add_handler(CommandHandler(["cancelar", "cancel"], panel_handler.cmd_cancelar))
    app.add_handler(CallbackQueryHandler(panel_handler.handle_callback, pattern=r"^cfg:"))
    app.add_handler(CommandHandler(["regras", "rules"], admin_cmd_handler.cmd_regras))
    app.add_handler(CommandHandler(["setregras", "setrules", "definirregras"], admin_cmd_handler.cmd_setregras))
    app.add_handler(CommandHandler(["ban", "banir"], admin_cmd_handler.cmd_ban))
    app.add_handler(CommandHandler(["kick", "expulsar"], admin_cmd_handler.cmd_kick))
    app.add_handler(CommandHandler(["mute", "silenciar"], admin_cmd_handler.cmd_mute))
    app.add_handler(CommandHandler(["unmute", "desmutar"], admin_cmd_handler.cmd_unmute))
    app.add_handler(CommandHandler(["warn", "advertir"], admin_cmd_handler.cmd_warn))
    app.add_handler(CommandHandler(["unwarn", "desadvertir"], admin_cmd_handler.cmd_unwarn))
    app.add_handler(CommandHandler(["warns", "advertencias"], admin_cmd_handler.cmd_warns))
    app.add_handler(CommandHandler(["pin", "fixar"], admin_cmd_handler.cmd_pin))
    app.add_handler(CommandHandler(["unpin", "desfixar"], admin_cmd_handler.cmd_unpin))
    app.add_handler(CommandHandler(["limpar", "clean"], admin_cmd_handler.cmd_limpar))
    app.add_handler(CommandHandler(["falar", "say", "dizer"], admin_cmd_handler.cmd_say))
    app.add_handler(CommandHandler(["anunciar", "anuncio"], admin_cmd_handler.cmd_anunciar))
    app.add_handler(CommandHandler(["info", "user", "perfil"], admin_cmd_handler.cmd_info))
    app.add_handler(CommandHandler(["chatinfo", "groupinfo", "id"], admin_cmd_handler.cmd_chatinfo))
    app.add_handler(CommandHandler(["setgrupo", "vinculargrupo", "addgrupo"], admin_cmd_handler.cmd_setgrupo))
    app.add_handler(CommandHandler(["desvincular", "removergrupo", "delgrupo"], admin_cmd_handler.cmd_desvincular))
    app.add_handler(CommandHandler(["setcanal", "setcanais", "vincularcanal", "vincularcanais", "addcanal"], admin_cmd_handler.cmd_setcanal))
    app.add_handler(CommandHandler(["desvincularcanal", "removercanal", "delcanal"], admin_cmd_handler.cmd_desvincularcanal))
    app.add_handler(CommandHandler(["grupos", "canais", "groups", "chats"], admin_cmd_handler.cmd_chats))
    app.add_handler(CommandHandler(["canal", "postar", "post"], admin_cmd_handler.cmd_canal))
    app.add_handler(CommandHandler(["testecanal", "diagcanal", "statuscanal"], admin_cmd_handler.cmd_testecanal))
    app.add_handler(CommandHandler(["transmitir", "broadcast"], admin_cmd_handler.cmd_transmitir))
    app.add_handler(CommandHandler(["vincularmsg", "setdestino"], admin_cmd_handler.cmd_vincularmsg))
    app.add_handler(CommandHandler(["relogio", "horario", "hora", "diag"], admin_cmd_handler.cmd_relogio))
    app.add_handler(CommandHandler(["setlog", "log"], admin_cmd_handler.cmd_setlog))
    app.add_handler(CommandHandler(["backup", "exportar"], admin_cmd_handler.cmd_backup))
    app.add_handler(CommandHandler(["restaurar", "restore", "importar"], admin_cmd_handler.cmd_restaurar))
    app.add_handler(CommandHandler(["filtro", "filter"], auto_responder_handler.cmd_filtro))
    app.add_handler(CommandHandler(["filtros", "filters"], auto_responder_handler.cmd_filtros))
    app.add_handler(CommandHandler(["delfiltro", "delfilter"], auto_responder_handler.cmd_delfiltro))
    app.add_handler(CommandHandler(["save", "salvar"], notes_handler.cmd_save))
    app.add_handler(CommandHandler(["get", "nota"], notes_handler.cmd_get))
    app.add_handler(CommandHandler(["notes", "notas"], notes_handler.cmd_notes))
    app.add_handler(CommandHandler(["clear", "delnota", "removenota"], notes_handler.cmd_clear))
    app.add_handler(CommandHandler(["lock", "bloquear", "travar"], locks_handler.cmd_lock))
    app.add_handler(CommandHandler(["unlock", "desbloquear", "destravar"], locks_handler.cmd_unlock))
    app.add_handler(CommandHandler(["locks", "bloqueios"], locks_handler.cmd_locks))
    app.add_handler(CommandHandler(["noturno", "nightmode", "silencio"], nightmode_handler.cmd_nightmode))
    app.add_handler(CommandHandler(["report", "denunciar"], admin_cmd_handler.cmd_report))
    app.add_handler(CommandHandler(["tutorial", "tutoriais", "guia"], tutorial_handler.cmd_tutorial))
    app.add_handler(CommandHandler("start", admin_cmd_handler.cmd_start))
    app.add_handler(CommandHandler(["ajuda", "help"], admin_cmd_handler.cmd_ajuda))
    app.add_handler(CommandHandler(["sobre", "doc", "versao", "documentacao", "manual", "version"], admin_cmd_handler.cmd_sobre))
    app.add_handler(CommandHandler(["menu", "teclado"], admin_cmd_handler.cmd_menu))
    app.add_handler(CommandHandler(["fecharmenu", "limparmenu", "semmenu", "semteclado"], admin_cmd_handler.cmd_fecharmenu))
    app.add_handler(CommandHandler(["livre", "liberar", "whitelistuser"], admin_cmd_handler.cmd_livre))
    app.add_handler(CommandHandler(["removerlivre", "dellivre", "unwhitelistuser"], admin_cmd_handler.cmd_removerlivre))
    app.add_handler(CommandHandler(["livres", "whitelistusers"], admin_cmd_handler.cmd_livres))
    app.add_handler(CommandHandler(["permitirlink", "liberarlink", "whitelistlink"], admin_cmd_handler.cmd_permitirlink))
    app.add_handler(CommandHandler(["removerlink", "dellink"], admin_cmd_handler.cmd_removerlink))
    app.add_handler(CommandHandler(["linkspermitidos", "dominiospermitidos", "allowedlinks"], admin_cmd_handler.cmd_linkspermitidos))

    async def cmd_whitelist_hub(update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not await admin_cache.is_admin(update.effective_chat, update.effective_user.id):
            await update.effective_message.reply_text("⛔ Apenas administradores podem acessar a Whitelist.")
            return
        from modules.whitelist import generate_whitelist_hub
        cfg = load_config()
        t, m = generate_whitelist_hub(cfg)
        await update.effective_message.reply_text(t, reply_markup=m, parse_mode=ParseMode.HTML)

    app.add_handler(CommandHandler(["whitelist", "listabranca"], cmd_whitelist_hub))

    # 3. Monitoramento de Mensagens Normais (Antispam, Anti-Repetição, Locks, Modo Noturno e Auto-Respostas)
    # Exclui comandos (/comando) e atualizações de status do pipeline de mensagens comuns
    message_filter = (
        filters.ALL
        & (~filters.COMMAND)
        & (~filters.StatusUpdate.ALL)
    )
    app.add_handler(MessageHandler(message_filter, filter_message_pipeline))

    # 4. Agendamento em segundo plano de Mensagens Programadas e Modo Noturno
    if app.job_queue:
        app.job_queue.run_repeating(
            process_recurring_messages_job,
            interval=30,
            first=10,
            name="recurring_messages_checker"
        )
        app.job_queue.run_repeating(
            check_night_mode_transitions_job,
            interval=30,
            first=5,
            name="night_mode_transitions_checker"
        )

    print("✅ Bot configurado com sucesso! Conectando aos servidores do Telegram...")
    print("Pressione Ctrl + C no terminal para parar o bot quando desejar.")
    print("=" * 60 + "\n")

    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
