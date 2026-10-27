import os
import re
import html
import time
import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, LinkPreviewOptions
from telegram.constants import ParseMode
from telegram.ext import ContextTypes
from config import load_config, get_welcome_for_chat, add_linked_group
from modules.utils import safe_delete_message, schedule_message_deletion, format_placeholders, build_rich_buttons_markup, smart_send_message, smart_send_photo
from modules.logger_channel import send_mod_log

logger = logging.getLogger("WelcomeModule")

# Cache de desduplicação para evitar disparos duplos quando Telegram envia
# ChatMemberUpdated e NEW_CHAT_MEMBERS na mesma entrada de membro
_RECENT_JOINS = {}  # (chat_id, user_id) -> timestamp


async def send_welcome_message(chat, new_member, context: ContextTypes.DEFAULT_TYPE):
    """Envia a mensagem oficial de boas-vindas para um novo membro (personalizada por grupo ou padrão geral)."""
    config = load_config()
    welcome_cfg = get_welcome_for_chat(config, chat.id)

    if not welcome_cfg.get("enabled", True):
        return

    name = new_member.first_name or "Membro"
    username = f"@{new_member.username}" if new_member.username else name
    group_title = chat.title or "Grupo"

    template = welcome_cfg.get("message", "👋 Seja bem-vindo(a), {name} ao grupo *{group}*!")
    formatted_message = format_placeholders(template, new_member, chat, config)

    await send_mod_log(
        bot=context.bot,
        event_type="join",
        title="Novo Membro no Grupo",
        user_info=f"{html.escape(name)} (<code>{new_member.id}</code>) | {html.escape(username)}",
        details=f"Grupo: <b>{html.escape(group_title)}</b>"
    )

    # Prepara botões personalizados (suporta grids multi-colunas)
    buttons_data = welcome_cfg.get("buttons", [])
    markup = build_rich_buttons_markup(buttons_data)

    photo = welcome_cfg.get("photo")
    article_url = welcome_cfg.get("article_url")

    # LinkPreviewOptions para exibir artigo no topo
    lpo = None
    if article_url:
        lpo = LinkPreviewOptions(url=article_url, show_above_text=True, is_disabled=False)
    else:
        lpo = LinkPreviewOptions(show_above_text=True)

    sent_msg = None

    if photo:
        sent_msg = await smart_send_photo(
            bot=context.bot,
            chat_id=chat.id,
            photo=photo,
            caption=formatted_message,
            reply_markup=markup
        )
    else:
        sent_msg = await smart_send_message(
            bot=context.bot,
            chat_id=chat.id,
            text=formatted_message,
            reply_markup=markup,
            link_preview_options=lpo
        )

    if sent_msg:
        delete_seconds = welcome_cfg.get("delete_welcome_after_seconds", 600)
        if delete_seconds > 0:
            schedule_message_deletion(context, chat.id, sent_msg.message_id, delete_seconds, bot=context.bot)
        logger.info(f"Boas-vindas enviada para {name} ({new_member.id}) no chat {chat.id} (auto-delete em {delete_seconds}s)")


async def handle_bot_intro(chat, context: ContextTypes.DEFAULT_TYPE):
    """Envia apresentação do bot quando adicionado a um novo grupo."""
    bot_intro = (
        f"🤖 Olá a todos! Fui adicionado para ajudar a gerenciar o grupo *{chat.title}*!\n\n"
        "🛡️ *Recursos ativos:*\n"
        "• Mensagens de boas-vindas automáticas\n"
        "• Proteção Antispam (links, convites, palavras proibidas)\n"
        "• Bloqueio de mensagens repetidas e flood\n\n"
        "⚠️ *Importante para os administradores:*\n"
        "Por favor, me concedam cargo de *Administrador* com permissão para *Apagar mensagens* "
        "e *Restringir usuários* para que minhas proteções funcionem plenamente!"
    )
    try:
        msg = await chat.send_message(text=bot_intro, parse_mode=ParseMode.MARKDOWN)
        cfg = load_config()
        welcome_cfg = get_welcome_for_chat(cfg, chat.id)
        delete_seconds = welcome_cfg.get("delete_welcome_after_seconds", 600)
        if delete_seconds > 0:
            schedule_message_deletion(context, chat.id, msg.message_id, delete_seconds, bot=context.bot)
    except Exception as e:
        logger.error(f"Erro ao enviar introdução do bot: {e}")


async def handle_member_join(chat, user, context: ContextTypes.DEFAULT_TYPE, captcha_handler=None, service_message_id=None):
    """
    Ponto de entrada unificado e infalível para qualquer entrada de membro no grupo:
    Funciona via link de convite, aprovação de entrada, adição direta ou evento normal.
    """
    if not chat or not user or getattr(user, "is_bot", False):
        return

    now = time.time()
    join_key = (chat.id, user.id)

    # Desduplicação: evita disparos repetidos caso Telegram envie ambos os eventos
    if join_key in _RECENT_JOINS:
        if now - _RECENT_JOINS[join_key] < 60:
            logger.debug(f"[Welcome] Ignorando entrada duplicada para {user.id} no chat {chat.id}")
            return
    _RECENT_JOINS[join_key] = now

    # Limpeza periódica de entradas antigas (> 5 min)
    if len(_RECENT_JOINS) > 100:
        expired = [k for k, t in _RECENT_JOINS.items() if now - t > 300]
        for k in expired:
            _RECENT_JOINS.pop(k, None)

    config = load_config()

    # Sincroniza o grupo automaticamente na lista de grupos vinculados
    if chat.type in ("group", "supergroup"):
        add_linked_group(config, chat.id, chat.title or "Grupo", chat.type)

    welcome_cfg = get_welcome_for_chat(config, chat.id)
    if not welcome_cfg.get("enabled", True):
        logger.info(f"[Welcome] Boas-vindas desativadas para o chat {chat.id} ({chat.title})")
        return

    # Apaga aviso de entrada padrão do Telegram ("Fulano entrou no grupo") se houver
    if service_message_id and welcome_cfg.get("delete_service_messages", True):
        await safe_delete_message(context.bot, chat.id, service_message_id)

    # Verifica se CAPTCHA anti-bot está ativo para este membro
    if captcha_handler and captcha_handler.is_enabled():
        challenged = await captcha_handler.challenge_member(chat, user, context)
        if challenged:
            # O membro foi desafiado e silenciado; as boas-vindas oficiais
            # serão disparadas assim que ele resolver o CAPTCHA!
            return

    # Dispara a mensagem oficial de boas-vindas
    await send_welcome_message(chat, user, context)


async def handle_new_members(update: Update, context: ContextTypes.DEFAULT_TYPE, captcha_handler=None):
    """Manipula a entrada de novos membros recebida via mensagem StatusUpdate.NEW_CHAT_MEMBERS."""
    if not update.message or not update.message.new_chat_members:
        return

    chat = update.effective_chat
    bot_user = await context.bot.get_me()

    for new_member in update.message.new_chat_members:
        if new_member.id == bot_user.id:
            await handle_bot_intro(chat, context)
            continue

        await handle_member_join(
            chat=chat,
            user=new_member,
            context=context,
            captcha_handler=captcha_handler,
            service_message_id=update.message.message_id
        )


async def test_welcome_message(bot, chat_id: int, user, context: ContextTypes.DEFAULT_TYPE) -> tuple[bool, str]:
    """
    Dispara uma mensagem de teste real no grupo especificado para que o administrador
    possa conferir a formatação, foto, botões e auto-exclusão instantaneamente.
    """
    try:
        config = load_config()
        welcome_cfg = get_welcome_for_chat(config, chat_id)
        if not welcome_cfg.get("enabled", True):
            return False, "As boas-vindas deste grupo estão atualmente DESATIVADAS. Ative-as primeiro para testar!"

        class MockChat:
            def __init__(self, cid, title):
                self.id = cid
                self.title = title

        # Descobre o título do chat
        chat_title = "Grupo"
        try:
            real_chat = await bot.get_chat(chat_id)
            chat_title = real_chat.title or "Grupo"
        except Exception:
            for g in config.get("linked_groups", []):
                if str(g.get("id")) == str(chat_id):
                    chat_title = g.get("title", "Grupo")
                    break

        chat_mock = MockChat(chat_id, chat_title)
        template = welcome_cfg.get("message", "👋 Seja bem-vindo(a), {name} ao grupo *{group}*!")
        formatted = format_placeholders(template, user, chat_mock, config)

        test_banner = (
            "🧪 <b>[TESTE DE BOAS-VINDAS]</b>\n"
            "<i>Esta é uma mensagem de demonstração acionada pelo administrador no painel:</i>\n\n"
        )

        final_text = test_banner + formatted

        buttons_data = welcome_cfg.get("buttons", [])
        markup = build_rich_buttons_markup(buttons_data)
        photo = welcome_cfg.get("photo")
        article_url = welcome_cfg.get("article_url")
        lpo = LinkPreviewOptions(url=article_url, show_above_text=True, is_disabled=False) if article_url else LinkPreviewOptions(show_above_text=True)

        if photo:
            sent = await smart_send_photo(
                bot=bot,
                chat_id=chat_id,
                photo=photo,
                caption=final_text,
                reply_markup=markup
            )
        else:
            sent = await smart_send_message(
                bot=bot,
                chat_id=chat_id,
                text=final_text,
                reply_markup=markup,
                link_preview_options=lpo
            )

        if sent:
            del_sec = welcome_cfg.get("delete_welcome_after_seconds", 60)
            # Para o teste, apaga em 60s ou no tempo configurado para não poluir
            test_del = min(del_sec, 60) if del_sec > 0 else 60
            schedule_message_deletion(context, chat_id, sent.message_id, test_del, bot=bot)
            return True, f"Enviado com sucesso no grupo '{chat_title}'! (Auto-exclusão em {test_del}s)"

        return False, "Falha ao enviar mensagem de teste no grupo."
    except Exception as e:
        logger.error(f"Erro no teste de boas-vindas: {e}")
        return False, str(e)


async def handle_rich_button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Manipula cliques nos botões interativos das mensagens de boas-vindas:
    - btn:rules -> Exibe regras em pop-up modal pessoal (show_alert=True) e envia no privado se for longo
    - btn:tutorial -> Exibe pop-up de busca rápida (@botpartituras_bot) e envia tutorial animado no privado
    - btn:alert:<msg> -> Exibe alerta personalizado modal definido pelo administrador
    """
    query = update.callback_query
    if not query:
        return

    data = query.data or ""
    user = query.from_user
    chat = query.message.chat if query.message else None

    logger.info(f"Botão interativo acionado ({data}) pelo usuário {user.id} ({user.first_name})")

    if data == "btn:rules":
        config = load_config()
        raw_rules = config.get("rules", "").strip()
        if not raw_rules:
            raw_rules = "📜 Regras do Grupo:\n1. Respeite todos os membros.\n2. Proibido spam e links não autorizados.\n3. Mantenha o foco em partituras e música."

        # Limpa formatação Markdown para ficar perfeito no pop-up de alerta nativo do Telegram
        clean_rules = re.sub(r"[*_`~]", "", raw_rules)

        if len(clean_rules) <= 195:
            await query.answer(text=clean_rules, show_alert=True)
        else:
            preview = clean_rules[:150] + "...\n(Regras completas enviadas no seu privado!)"
            await query.answer(text=preview, show_alert=True)
            # Tenta enviar as regras completas no privado
            try:
                await context.bot.send_message(
                    chat_id=user.id,
                    text=f"📜 <b>REGRAS DO GRUPO:</b>\n\n{html.escape(raw_rules)}",
                    parse_mode=ParseMode.HTML
                )
            except Exception as e:
                logger.debug(f"Não foi possível enviar regras em DM para {user.id}: {e}")

    elif data == "btn:tutorial":
        tut_alert = (
            "🎥 COMO PESQUISAR PARTITURAS:\n\n"
            "Digite no chat:\n"
            "@botpartituras_bot <nome ou número>\n"
            "Ex: @botpartituras_bot 150\n"
            "Toque no resultado para enviar!"
        )
        await query.answer(text=tut_alert, show_alert=True)

        # Envia tutorial detalhado + GIF animado no chat privado
        try:
            tut_caption = (
                "🎥 <b>COMO PESQUISAR PARTITURAS (MODO INLINE):</b>\n\n"
                "Você pode encontrar qualquer partitura em segundos diretamente no chat do grupo ou privado:\n\n"
                "1️⃣ Digite <code>@botpartituras_bot</code> seguido de um espaço e o nome ou número do hino.\n"
                "2️⃣ Uma janela suspensa se abrirá com os resultados encontrados instantaneamente.\n"
                "3️⃣ Toque ou clique sobre o arquivo desejado para que ele seja enviado na conversa!\n\n"
                "💡 <i>Exemplo: digite <code>@botpartituras_bot 150</code> para ver o Hino 150.</i>"
            )

            # Procura por arquivo de animação tutorial
            base_dir = os.path.dirname(os.path.dirname(__file__))
            candidate_files = [
                os.path.join(base_dir, "assets", "tutorial_busca_partituras.gif"),
                os.path.join(base_dir, "assets", "tutorial_busca_partituras.mp4"),
                r"D:\Movidos\Desktop\tutorial_busca_partituras.gif",
                r"D:\Movidos\Desktop\tutorial_busca_partituras.mp4"
            ]

            media_sent = False
            for c_path in candidate_files:
                if os.path.exists(c_path):
                    with open(c_path, "rb") as f:
                        if c_path.endswith(".gif"):
                            await context.bot.send_animation(
                                chat_id=user.id,
                                animation=f,
                                caption=tut_caption,
                                parse_mode=ParseMode.HTML
                            )
                        else:
                            await context.bot.send_video(
                                chat_id=user.id,
                                video=f,
                                caption=tut_caption,
                                parse_mode=ParseMode.HTML
                            )
                    media_sent = True
                    break

            if not media_sent:
                await context.bot.send_message(
                    chat_id=user.id,
                    text=tut_caption,
                    parse_mode=ParseMode.HTML
                )
        except Exception as e:
            logger.debug(f"Não foi possível enviar tutorial em DM para {user.id}: {e}")

    elif data.startswith("btn:alert:"):
        alert_text = data[10:].strip()
        if not alert_text:
            alert_text = "Aviso do grupo!"
        await query.answer(text=alert_text[:200], show_alert=True)

    else:
        await query.answer()


