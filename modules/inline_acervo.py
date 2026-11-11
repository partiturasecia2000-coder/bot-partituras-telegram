import os
import re
import html
import json
import time
import sqlite3
import logging
import asyncio
import unicodedata
from pathlib import Path
from datetime import datetime
from telegram import (
    Update,
    InlineQueryResultCachedDocument,
    InlineQueryResultCachedAudio,
    InlineQueryResultArticle,
    InputTextMessageContent,
    InlineKeyboardMarkup,
    InlineKeyboardButton
)
from telegram.constants import ParseMode, ChatMemberStatus
from telegram.ext import ContextTypes
from config import BASE_DIR, load_config, save_config, normalize_chat_id

logger = logging.getLogger("InlineAcervoModule")
DB_PATH = BASE_DIR / "acervo_partituras.db"


from modules.acervo_database import (
    AcervoDatabase,
    CHATTER_PATTERNS,
    CHATTER_RE,
    DB_PATH,
    INSTRUMENT_ALIASES,
    SEARCH_STOPWORDS,
    acervo_db,
    clean_file_title,
    format_bytes,
    generate_search_index_text,
    get_number_variants,
    logger,
    normalize_search_term,
    preprocess_search_query
)

def extract_media_from_message(msg):
    """Extrai informações de mídia de uma mensagem se for documento, áudio ou áudio de voz."""
    if not msg:
        return None

    caption = msg.caption or ""

    if msg.document:
        doc = msg.document
        fn = doc.file_name or "partitura.pdf"
        title = clean_file_title(fn, caption)
        return {
            "file_id": doc.file_id,
            "file_unique_id": getattr(doc, "file_unique_id", ""),
            "file_name": fn,
            "file_type": "document",
            "file_size": doc.file_size or 0,
            "title": title,
            "caption": caption
        }
    elif msg.audio:
        aud = msg.audio
        title = aud.title or aud.file_name or "Playback / Áudio"
        if aud.performer:
            title = f"{aud.performer} - {title}"
        fn = aud.file_name or f"{title}.mp3"
        return {
            "file_id": aud.file_id,
            "file_unique_id": getattr(aud, "file_unique_id", ""),
            "file_name": fn,
            "file_type": "audio",
            "file_size": aud.file_size or 0,
            "title": title,
            "caption": caption
        }
    elif getattr(msg, "voice", None):
        v = msg.voice
        title = clean_file_title("audio_guia.ogg", caption) or "Áudio Guia / Ensaio"
        return {
            "file_id": v.file_id,
            "file_unique_id": getattr(v, "file_unique_id", ""),
            "file_name": f"{title}.ogg",
            "file_type": "audio",
            "file_size": v.file_size or 0,
            "title": title,
            "caption": caption
        }
    return None


def import_universal_json(data, fallback_channel_id: int = None, fallback_title: str = "") -> dict:
    """
    Importa partituras de qualquer JSON:
    1. Formato Telegram Desktop Export (result.json)
    2. Formato de banco legado (banco.json / listas de itens)
    """
    items_to_add = []
    valid_exts = (".pdf", ".sib", ".enc", ".mscz", ".mus", ".xml", ".musicxml", ".zip", ".rar", ".7z", ".mp3", ".wav", ".ogg", ".m4a")

    # Formato 1: Exportação do Telegram Desktop com {"name": "...", "messages": [...]}
    if isinstance(data, dict) and "messages" in data:
        chan_name = data.get("name") or fallback_title or "Canal de Arquivos"
        raw_id = data.get("id")
        channel_id = None
        if raw_id:
            raw_str = str(raw_id)
            channel_id = int(f"-100{raw_str}") if not raw_str.startswith("-100") else int(raw_str)
        elif fallback_channel_id:
            channel_id = normalize_chat_id(fallback_channel_id)
        else:
            channel_id = -1001806380183

        for m in data.get("messages", []):
            if m.get("type") != "message":
                continue
            msg_id = m.get("id")
            if not msg_id:
                continue

            file_raw = m.get("file_name") or m.get("file") or ""
            file_str = str(file_raw).strip() if file_raw else ""

            # Se for texto indicando que o arquivo não foi baixado na exportação ex: "(File not included, size: ...)"
            if file_str.startswith("(") and ")" in file_str:
                clean_name = ""
            elif file_str:
                clean_name = os.path.basename(file_str)
            else:
                clean_name = ""

            mime = (m.get("mime_type") or "").lower()
            media_type = m.get("media_type") or ""

            text_field = m.get("text", "")
            caption = ""
            if isinstance(text_field, str):
                caption = text_field
            elif isinstance(text_field, list):
                caption = "".join(p if isinstance(p, str) else (p.get("text", "") if isinstance(p, dict) else "") for p in text_field)

            lower_fn = clean_name.lower()
            # VERIFICAÇÃO ESTRITA: Mensagem PRECISA conter um arquivo de documento/áudio real
            has_media_file = False
            if clean_name and any(lower_fn.endswith(ext) for ext in valid_exts):
                has_media_file = True
            elif media_type in ("document", "audio_file", "voice_message"):
                has_media_file = True
            elif "pdf" in mime or "audio" in mime:
                has_media_file = True
            elif file_str and not file_str.startswith("("):
                fn_raw = os.path.basename(file_str).lower()
                if any(fn_raw.endswith(ext) for ext in valid_exts):
                    has_media_file = True

            if not has_media_file:
                continue

            file_type = "audio" if (media_type == "audio_file" or any(lower_fn.endswith(a) for a in (".mp3", ".wav", ".ogg", ".m4a"))) else "document"
            file_size = m.get("file_size", 0)
            title = clean_file_title(clean_name, caption)
            if not title or title == "Partitura Musical":
                if caption:
                    title = caption.split("\n")[0][:70]
                elif clean_name:
                    title = clean_name

            # Descarta mensagens cujo título seja pergunta ou bate-papo de grupo (ex: 'alguém tem método?')
            if CHATTER_RE.search(title) or title.endswith("?"):
                continue

            post_url = ""
            cid_str = str(channel_id)
            if cid_str.startswith("-100"):
                post_url = f"https://t.me/c/{cid_str[4:]}/{msg_id}"

            items_to_add.append({
                "channel_id": channel_id,
                "channel_title": chan_name,
                "message_id": msg_id,
                "file_name": clean_name or f"{title}.pdf",
                "title": title,
                "caption": caption,
                "file_type": file_type,
                "file_size": file_size,
                "post_url": post_url
            })

    # Formato 2: Lista de objetos (ex: banco.json legado)
    elif isinstance(data, list):
        for entry in data:
            if not isinstance(entry, dict):
                continue
            raw_title = entry.get("original") or entry.get("texto") or entry.get("title") or entry.get("nome") or ""
            caption = entry.get("legenda") or entry.get("caption") or ""
            channel = entry.get("canal") or entry.get("channel") or fallback_title or "Canal de Arquivos"
            msg_id = entry.get("msg_id") or entry.get("message_id") or entry.get("id")

            if not raw_title or not msg_id:
                continue

            # Limpa quebras de linha e categorias do título se existirem
            first_title_line = raw_title.strip().split("\n")[0].strip()
            title = clean_file_title("", first_title_line or raw_title)

            # Descarta itens que sejam conversas ou pedidos
            if CHATTER_RE.search(title) or title.endswith("?"):
                continue

            file_name = entry.get("file_name") or f"{title}.pdf"

            ch_username = ""
            channel_id = fallback_channel_id or -1001806380183
            post_url = ""

            if str(channel).startswith("@"):
                ch_username = str(channel)
                post_url = f"https://t.me/{ch_username.lstrip('@')}/{msg_id}"
            elif str(channel).replace("-", "").isdigit():
                channel_id = normalize_chat_id(int(channel))
                cid_str = str(channel_id)
                if cid_str.startswith("-100"):
                    post_url = f"https://t.me/c/{cid_str[4:]}/{msg_id}"
            else:
                ch_username = f"@{str(channel).lstrip('@')}"
                post_url = f"https://t.me/{str(channel).lstrip('@')}/{msg_id}"

            file_type = "audio" if any(file_name.lower().endswith(a) for a in (".mp3", ".wav", ".ogg", ".m4a")) else "document"

            items_to_add.append({
                "channel_id": channel_id,
                "channel_title": str(channel).lstrip("@"),
                "channel_username": ch_username,
                "message_id": int(msg_id),
                "file_name": file_name,
                "title": title,
                "caption": caption or raw_title,
                "file_type": file_type,
                "file_size": entry.get("file_size", 0),
                "post_url": post_url
            })

    if not items_to_add:
        return {"success": False, "count": 0, "error": "Nenhum item válido identificado no arquivo JSON."}

    total_added = acervo_db.add_items_batch(items_to_add)
    return {
        "success": True,
        "count": total_added,
        "channel_title": items_to_add[0].get("channel_title", "Canais"),
        "channel_id": items_to_add[0].get("channel_id")
    }


async def handle_private_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Handler prioritário (group=-1) para documentos enviados no privado com o bot.
    Garante que arquivos .json de importação ou arquivos de partituras (.pdf, áudios)
    nunca sejam ignorados ou bloqueados por outros módulos.
    """
    msg = update.effective_message
    if not msg or not msg.document:
        return

    doc = msg.document
    fn = (doc.file_name or "").lower()

    # Caso 1: Arquivo JSON de exportação do acervo (result.json do Telegram Desktop ou banco legado)
    if fn.endswith(".json"):
        cfg = load_config()
        status_msg = await msg.reply_text("📥 <i>Lendo e processando arquivo JSON de partituras...</i>", parse_mode=ParseMode.HTML)
        try:
            doc_file = await context.bot.get_file(doc.file_id)
            file_bytes = await doc_file.download_as_bytearray()
            json_str = file_bytes.decode("utf-8", errors="replace")
            parsed_data = json.loads(json_str)

            import_res = import_universal_json(parsed_data, fallback_channel_id=cfg.get("main_channel_id"))
            if import_res.get("success"):
                count = import_res.get("count", 0)
                chan_title = import_res.get("channel_title", "Canal")
                stats = acervo_db.get_stats()
                total_acervo = stats.get("total_files", 0)
                bot_me = await context.bot.get_me()
                bot_user = bot_me.username or "botpartituras_bot"

                await status_msg.edit_text(
                    f"🎉 <b>IMPORTAÇÃO DO ACERVO CONCLUÍDA COM SUCESSO!</b> 🎼\n\n"
                    f"• <b>Canal de Origem:</b> {html.escape(chan_title)}\n"
                    f"• <b>Partituras Cadastradas:</b> <code>{count}</code>\n"
                    f"• <b>Total Geral no Acervo:</b> <code>{total_acervo}</code>\n\n"
                    f"💡 <b>Teste a busca instantânea agora:</b>\n"
                    f"Em qualquer grupo ou chat, digite:\n"
                    f"<code>@{bot_user} &lt;nome da música&gt;</code>",
                    parse_mode=ParseMode.HTML,
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("🔍 Testar Busca Agora", switch_inline_query_current_chat="")],
                        [InlineKeyboardButton("🎼 Ver Painel do Acervo", callback_data="acervo:menu")]
                    ])
                )
            else:
                err = import_res.get("error", "Nenhuma partitura identificada.")
                await status_msg.edit_text(
                    f"⚠️ <b>Aviso na Importação:</b> {html.escape(err)}\n\n"
                    f"Certifique-se de exportar o canal no Telegram Desktop em formato JSON.",
                    parse_mode=ParseMode.HTML
                )
        except Exception as e_imp:
            logger.error(f"Erro na importação de documento JSON: {e_imp}", exc_info=True)
            await status_msg.edit_text(f"❌ <b>Erro ao processar JSON:</b> <code>{html.escape(str(e_imp))}</code>", parse_mode=ParseMode.HTML)
        return

    # Caso 2: Documento de Partitura (.pdf, .sib, .mus, .mscz, .zip, etc.)
    media_info = extract_media_from_message(msg)
    if media_info:
        cfg = load_config()
        src_channel_id = cfg.get("main_channel_id") or -1001806380183
        src_channel_title = "Acervo Direto"
        orig_msg_id = msg.message_id
        src_username = ""

        # Se foi encaminhado
        fwd_origin = getattr(msg, "forward_origin", None)
        legacy_fwd = getattr(msg, "forward_from_chat", None)

        if fwd_origin and getattr(fwd_origin, "chat", None):
            fc = fwd_origin.chat
            src_channel_id = fc.id
            src_channel_title = getattr(fc, "title", "Canal") or "Canal"
            src_username = getattr(fc, "username", "") or ""
            orig_msg_id = getattr(fwd_origin, "message_id", None) or msg.message_id
        elif legacy_fwd:
            src_channel_id = legacy_fwd.id
            src_channel_title = getattr(legacy_fwd, "title", "Canal") or "Canal"
            src_username = getattr(legacy_fwd, "username", "") or ""
            orig_msg_id = getattr(msg, "forward_from_message_id", None) or msg.message_id

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
            fn_clean = media_info.get("file_name", "partitura")
            await msg.reply_text(
                f"🎼 <b>Partitura Adicionada ao Acervo!</b>\n\n"
                f"• <b>Arquivo:</b> <code>{html.escape(fn_clean)}</code>\n"
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


async def cmd_limpar_acervo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Comando administrativo para zerar o banco do acervo de partituras."""
    msg = update.effective_message
    if not msg:
        return
    deleted = acervo_db.clear_all()
    await msg.reply_text(
        f"🗑️ <b>Acervo de Partituras Limpo com Sucesso!</b>\n\n"
        f"Foram removidos <code>{deleted}</code> registros do banco.\n"
        f"O acervo está 100% zerado e pronto para você enviar o <code>result.json</code>!",
        parse_mode=ParseMode.HTML
    )


async def cmd_limpar_textos(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Comando administrativo para varrer e remover mensagens de bate-papo/perguntas do acervo."""
    msg = update.effective_message
    if not msg:
        return
    status_msg = await msg.reply_text("🧹 <i>Varrendo o banco e removendo mensagens de texto...</i>", parse_mode=ParseMode.HTML)
    deleted = acervo_db.purge_text_chatter()
    stats = acervo_db.get_stats()
    tot = stats.get("total_files", 0)
    await status_msg.edit_text(
        f"🧹 <b>Limpeza de Mensagens Concluída!</b>\n\n"
        f"• <b>Textos removidos:</b> <code>{deleted}</code>\n"
        f"• <b>Partituras reais restantes no acervo:</b> <code>{tot}</code>\n\n"
        f"Todas as suas partituras e áudios legítimos continuam 100% preservados!",
        parse_mode=ParseMode.HTML
    )


# =====================================================================
# AUTO-SUGESTÃO INTELIGENTE DE PARTITURAS NO GRUPO
# =====================================================================

GENERIC_MUSIC_WORDS = {
    "partitura", "partituras", "arranjo", "arranjos", "grade", "grades", "pdf"
}

STOPWORDS = {
    "o", "a", "os", "as", "um", "uma", "uns", "umas",
    "de", "do", "da", "dos", "das", "em", "no", "na",
    "nos", "nas", "para", "pra", "pro", "pras", "pros",
    "com", "por", "pelo", "pela", "pelos", "pelas",
    "que", "se", "ou", "e", "eu", "ele", "ela", "eles", "elas",
    "alguem", "quem", "tem", "teria", "consegue", "passa", "manda",
    "compartilha", "envia", "onde", "acho", "encontro", "consigo",
    "baixo", "como", "preciso", "procuro", "procurando", "favor",
    "pfv", "porfavor", "gentileza", "opa", "ola", "bom", "dia",
    "tarde", "noite", "voce", "voces", "vc", "vcs", "ai"
}

REQUEST_TRIGGERS = [
    r"\b(?:algu[eé]m(?:\s+a[ií])?\s+)?(?:tem|teria|consegue|passa|manda|compartilha|envia)\b",
    r"\bquem\s+(?:tem|teria|pode|consegue|passa|manda|compartilha|envia)\b",
    r"\bonde\s+(?:acho|encontro|tem|consigo|baixo)\b",
    r"\bcomo\s+(?:achar|encontrar|conseguir|baixar)\b",
    r"\bpreciso\s+d?[eoa]?s?\b",
    r"\bprocuro\b",
    r"\bprocurando\b",
    r"\btem\s+(?:a[ií]\s+)?(?:partitura|arranjo|hino|playback|m[eé]todo|grade|cifra)\b",
    r"\bvoc[eê]s?\s+t[eê]m\b",
    r"\bvc[s]?\s+t[eê]m\b",
    r"\bquem\s+tiver\b",
    r"\bse\s+algu[eé]m\s+tiver\b"
]

TRIGGER_RE = re.compile(r"|".join(REQUEST_TRIGGERS), re.IGNORECASE)

MUSIC_INDICATORS = {
    "partitura", "partituras", "arranjo", "arranjos", "hino", "hinos",
    "playback", "playbacks", "metodo", "metodos", "grade", "grades",
    "cifra", "cifras", "musica", "musicas", "louvor", "louvores",
    "sax", "trompete", "violino", "clarinete", "trombone", "flauta",
    "teclado", "piano", "violao", "guitarra", "baixo", "bateria",
    "violoncelo", "cello", "trompa", "tuba", "eufonio", "harpa", "hinario"
}

NON_MUSIC_WORDS = {
    "aula", "reuniao", "tempo", "certeza", "medo", "fome", "sono",
    "dinheiro", "troco", "caneta", "carregador", "chave", "trabalho",
    "carro", "onibus", "moto", "almoco", "jantar", "cafe"
}

# Cooldown de auto-resposta no grupo (em segundos por grupo)
GROUP_ACERVO_COOLDOWN_SECONDS = 25
_group_acervo_cooldown: dict[int, float] = {}


def extract_music_query(text: str, is_private: bool = False) -> str | None:
    """
    Analisa se uma mensagem expressa um pedido ou busca de partitura/música e extrai
    o termo limpo para consulta no banco de dados do acervo.
    Retorna None se a mensagem não for um pedido musical genuíno.
    """
    if not text or len(text.strip()) < 3:
        return None

    # Ignora comandos
    if text.strip().startswith("/"):
        return None

    # No grupo, exige o trigger de pedido ("alguém tem", "quem tem", "preciso", etc.)
    # No privado, se o usuário enviou diretamente o termo/título, permite a busca direta
    if not is_private and not TRIGGER_RE.search(text):
        return None

    pre = preprocess_search_query(text)
    norm = normalize_search_term(pre)
    raw_tokens = norm.split()

    # Se contiver palavras claramente não musicais como "aula", "fome", "dinheiro"
    if any(w in NON_MUSIC_WORDS for w in raw_tokens):
        return None

    has_music_indicator = any(w in MUSIC_INDICATORS for w in raw_tokens)

    # Coleta tokens úteis para o título
    title_tokens = []
    for t in raw_tokens:
        if t in STOPWORDS or t in GENERIC_MUSIC_WORDS:
            continue
        if t.isdigit() or len(t) >= 2:
            title_tokens.append(t)

    if not title_tokens:
        return None

    # Se não tiver indicador explícito e não for privado, precisa de pelo menos 2 palavras
    if not has_music_indicator and len(title_tokens) < 2 and not is_private:
        return None

    return " ".join(title_tokens)


async def check_and_auto_reply_acervo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """
    Verifica se a mensagem no grupo ou no privado é um pedido de partitura.
    Se a funcionalidade estiver ativada, consulta o acervo de 17.151 partituras:
    - Se encontrar partituras correspondentes, envia card elegante com links e botões.
    - Se NÃO encontrar nada correspondente, permanece 100% em silêncio (zero ruído e zero falsos positivos).
    Retorna True se respondeu à mensagem, False caso contrário.
    """
    msg = update.effective_message
    chat = update.effective_chat
    if not msg or not chat:
        return False

    is_group = chat.type in ("group", "supergroup")

    cfg = load_config()
    if not cfg.get("acervo_group_auto_reply", False):
        return False

    if is_group:
        now = time.time()
        last_time = _group_acervo_cooldown.get(chat.id, 0)
        if (now - last_time) < GROUP_ACERVO_COOLDOWN_SECONDS:
            return False

    text = msg.text or msg.caption or ""
    query_term = extract_music_query(text, is_private=(not is_group))
    if not query_term:
        return False

    # Consulta o banco de partituras (17.151 arquivos)
    results = acervo_db.search(query=query_term, limit=3)
    if not results:
        # Silêncio absoluto se não houver partitura correspondente no banco!
        return False

    # Registra o cooldown se for grupo
    if is_group:
        _group_acervo_cooldown[chat.id] = time.time()

    user_name = html.escape(msg.from_user.first_name if msg.from_user else "Membro")
    bot_me = await context.bot.get_me()
    bot_username = bot_me.username or "botpartituras_bot"

    lines = [
        "🎼 <b>Encontrei no Nosso Acervo!</b> 📁\n",
        f"Olá, <b>{user_name}</b>! Encontrei partituras no acervo oficial que combinam com seu pedido:\n"
    ]

    buttons = []
    for idx, item in enumerate(results, start=1):
        t = item.get("title") or item.get("file_name", "Partitura")
        chan = item.get("channel_title") or "Canal Oficial"
        post_url = item.get("post_url", "")
        file_type = item.get("file_type", "document")
        icon = "🎵" if file_type == "audio" else "📄"

        lines.append(f"{idx}️⃣ {icon} <b>{html.escape(t)}</b>\n    📢 <i>{html.escape(chan)}</i>")
        if post_url:
            buttons.append([InlineKeyboardButton(f"📢 Baixar no {chan[:22]}", url=post_url)])

    markup = InlineKeyboardMarkup(buttons)
    try:
        reply_msg = await msg.reply_text(
            "\n".join(lines),
            parse_mode=ParseMode.HTML,
            reply_markup=markup
        )
        logger.info(f"[Acervo Auto-Reply] Sugeridas {len(results)} partituras para '{query_term}' no grupo {chat.title} ({chat.id})")
        if chat and chat.type in ("group", "supergroup"):
            autodel = cfg.get("acervo_auto_delete_seconds", 0)
            if autodel > 0:
                from modules.utils import schedule_message_deletion
                schedule_message_deletion(context, chat.id, reply_msg.message_id, autodel, bot=context.bot)
        return True
    except Exception as e:
        logger.error(f"[Acervo Auto-Reply] Erro ao enviar resposta no grupo: {e}")
        return False


async def handle_inline_acervo_query(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Processa buscas inline digitadas por qualquer usuário no Telegram:
    Exemplo: @MaestroBot Harpa 15
    Suporta paginação contínua (offset) ao rolar para baixo!
    """
    inline_q = update.inline_query
    if not inline_q:
        return

    query_str = inline_q.query.strip()
    offset = int(inline_q.offset) if inline_q.offset and inline_q.offset.isdigit() else 0
    limit = 30

    bot_me = await context.bot.get_me()
    bot_username = bot_me.username or "botpartituras_bot"

    results_data = acervo_db.search(query=query_str, limit=limit, offset=offset)
    inline_results = []

    if not results_data and offset == 0:
        # Se não encontrou nada na primeira página
        if query_str:
            no_res_text = (
                f"🔍 <b>Nenhuma partitura encontrada para:</b> <i>{html.escape(query_str)}</i>\n\n"
                f"💡 <b>Dicas de busca:</b>\n"
                f"• Digite o número do hino (ex: <code>15</code> ou <code>300</code>)\n"
                f"• Digite instrumento (ex: <code>sax</code>, <code>trompete</code>, <code>clarinete</code>)\n"
                f"• Digite trechos do título sem pontuação"
            )
            inline_results.append(
                InlineQueryResultArticle(
                    id="no_results",
                    title="Nenhuma partitura encontrada",
                    description=f"Não encontramos nada para '{query_str[:30]}'. Toque para dicas.",
                    input_message_content=InputTextMessageContent(no_res_text, parse_mode=ParseMode.HTML),
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("🔍 Tentar Outra Busca", switch_inline_query_current_chat="")]
                    ])
                )
            )
        else:
            inline_results.append(
                InlineQueryResultArticle(
                    id="empty_catalog",
                    title="🎼 Acervo Global de Partituras",
                    description="O acervo está sendo sincronizado pelos canais...",
                    input_message_content=InputTextMessageContent(
                        "🎼 <b>Acervo de Partituras em Sincronização!</b>\nUse <code>/acervo</code> no privado para indexar seus canais.",
                        parse_mode=ParseMode.HTML
                    )
                )
            )
    else:
        cfg = load_config()
        chatlist_url = cfg.get("acervo_chatlist_url", "https://t.me/addlist/H5UNPP0h4FI3ZTNh")
        for item in results_data:
            item_id = str(item["id"])
            title = item["title"]
            file_id = item["file_id"]
            file_type = item.get("file_type", "document")
            chan_title = item.get("channel_title") or "Canal de Partituras"
            file_size_str = item.get("file_size_str", "")
            post_url = item.get("post_url", "")
            file_name = item.get("file_name", "partitura.pdf")

            channel_id = item.get("channel_id")
            channel_username = item.get("channel_username", "")
            channel_link = get_channel_invite_link(cfg, channel_id, channel_username)

            badge_short, format_name, format_icon = get_file_format_info(file_name, file_type)

            # Título e descrição refinados na janela suspensa da busca
            dropdown_title = f"{format_icon} {badge_short} {title}"
            desc_parts = []
            if file_size_str:
                desc_parts.append(f"💾 {file_size_str}")
            desc_parts.append(f"📢 {chan_title[:20]}")
            dropdown_desc = " • ".join(desc_parts)

            # Card com visual elegante e divisores
            size_part = f" • 💾 <b>Tamanho:</b> <code>{file_size_str}</code>" if file_size_str else ""
            card_text = (
                f"🎼 <b>{html.escape(title.upper())}</b>\n"
                f"──────────────────────────────\n"
                f"📄 <b>Tipo:</b> {format_name}{size_part}\n"
                f"📢 <b>Canal:</b> {html.escape(chan_title)}\n"
                f"──────────────────────────────\n"
                f"🔒 <b>Acesso ao Canal Privado:</b>\n"
                f"1️⃣ Toque em <b>'1º Entrar no Canal'</b> para se inscrever\n"
                f"2️⃣ Toque em <b>'2º Baixar Partitura'</b> para abrir o arquivo\n\n"
                f"🎵 <i>Enviado via @{bot_username}</i>"
            )

            caption = (
                f"🎼 <b>{html.escape(title.upper())}</b>\n"
                f"──────────────────────────────\n"
                f"📄 <b>Tipo:</b> {format_name}{size_part}\n"
                f"📢 <b>Origem:</b> {html.escape(chan_title)}\n\n"
                f"🎵 <i>Enviado via @{bot_username}</i>"
            )

            buttons = []
            # Linha 1: Botão para ENTRAR no canal específico onde o arquivo está guardado
            if channel_link:
                buttons.append([InlineKeyboardButton(f"📢 1º Entrar no Canal ({chan_title[:16]})", url=channel_link)])

            # Linha 2: Botão para BAIXAR / ABRIR o arquivo naquele canal
            if post_url:
                buttons.append([InlineKeyboardButton("📥 2º Baixar Partitura", url=post_url)])
            elif not channel_link:
                if chatlist_url:
                    buttons.append([InlineKeyboardButton("📁 Nossos Canais", url=chatlist_url)])

            # Linha 3: Botão de atalho para buscar outra partitura imediatamente no grupo
            buttons.append([InlineKeyboardButton("🔍 Buscar Outra Partitura", switch_inline_query_current_chat="")])

            markup = InlineKeyboardMarkup(buttons)

            # Se o item tiver file_id real do Telegram, envia o arquivo instantaneamente
            if file_id and not file_id.startswith("link_"):
                if file_type == "audio":
                    inline_results.append(
                        InlineQueryResultCachedAudio(
                            id=f"aud_{item_id}",
                            audio_file_id=file_id,
                            caption=caption,
                            parse_mode=ParseMode.HTML,
                            reply_markup=markup
                        )
                    )
                else:
                    inline_results.append(
                        InlineQueryResultCachedDocument(
                            id=f"doc_{item_id}",
                            title=dropdown_title,
                            document_file_id=file_id,
                            description=dropdown_desc,
                            caption=caption,
                            parse_mode=ParseMode.HTML,
                            reply_markup=markup
                        )
                    )
            else:
                inline_results.append(
                    InlineQueryResultArticle(
                        id=f"art_{item_id}",
                        title=dropdown_title,
                        description=dropdown_desc,
                        input_message_content=InputTextMessageContent(card_text, parse_mode=ParseMode.HTML),
                        reply_markup=markup
                    )
                )

    # Próxima página contínua para rolagem infinita
    next_offset = str(offset + limit) if len(results_data) == limit else ""

    try:
        await inline_q.answer(
            results=inline_results,
            cache_time=1,
            is_personal=True,
            next_offset=next_offset
        )
    except Exception as e:
        logger.error(f"Erro ao responder inline_query: {e}")


def get_file_format_info(file_name: str, file_type: str = "document") -> tuple[str, str, str]:
    """
    Retorna (badge_curto, nome_formato, emoji_icone) com base na extensão do arquivo.
    Exemplo: ('[PDF]', 'Partitura em PDF', '📕')
    """
    fn = (file_name or "").lower().strip()
    ext = fn.split(".")[-1] if "." in fn else ""

    if ext == "pdf":
        return ("[PDF]", "Partitura em PDF", "📕")
    elif ext in ("sib", "sibelius"):
        return ("[SIB]", "Sibelius (.sib)", "🎼")
    elif ext in ("mus", "musx"):
        return ("[FIN]", "Finale (.musx)", "🎹")
    elif ext in ("enc", "encore"):
        return ("[ENC]", "Encore (.enc)", "🎶")
    elif ext in ("mp3", "m4a", "wav", "ogg", "flac", "aac", "mid", "midi") or file_type == "audio":
        return ("[ÁUDIO]", "Áudio / Playback", "🎧")
    elif ext in ("rar", "zip", "7z", "tar", "gz"):
        return ("[PACOTE]", "Coletânea Compactada", "📦")
    elif ext in ("docx", "doc", "odt", "txt"):
        return ("[TEXTO]", "Texto / Cifra", "📄")
    else:
        return ("[ARQ]", "Arquivo de Partitura", "🎼")


def get_channel_invite_link(cfg: dict, channel_id: int | str, channel_username: str = "") -> str:
    """Retorna o link de convite/entrada específico de um canal do acervo."""
    if not cfg:
        return ""

    cid_str = str(channel_id).replace("-100", "").replace("-", "")

    # 1. Verifica no mapa customizado channel_invite_links
    custom_map = cfg.get("channel_invite_links", {})
    if str(channel_id) in custom_map and custom_map[str(channel_id)]:
        return custom_map[str(channel_id)]
    if cid_str in custom_map and custom_map[cid_str]:
        return custom_map[cid_str]

    # 2. Verifica nos linked_channels do config
    for ch in cfg.get("linked_channels", []):
        ch_id_norm = str(ch.get("id", "")).replace("-100", "").replace("-", "")
        if ch_id_norm == cid_str:
            if ch.get("invite_link"):
                return ch.get("invite_link")
            if ch.get("username"):
                return f"https://t.me/{ch.get('username').lstrip('@')}"

    # 3. Se tiver username público no item do banco
    if channel_username and channel_username.strip():
        u = channel_username.strip().lstrip("@")
        return f"https://t.me/{u}"

    # 4. Fallback: se houver pasta de canais geral configurada
    return cfg.get("acervo_chatlist_url", "")


async def notify_new_acervo_item_in_group(
    bot,
    cfg: dict,
    channel_id: int | str,
    channel_title: str,
    channel_username: str,
    message_id: int,
    file_name: str,
    title: str = "",
    caption: str = "",
    file_type: str = "document",
    file_size: int = 0,
    force_send: bool = False
):
    """
    Publica um aviso com card visual elegante no grupo principal (ex: https://t.me/partiturasecia)
    sempre que uma nova partitura for postada em um canal onde o bot é administrador.
    """
    if not force_send and not cfg.get("acervo_channel_notify_enabled", True):
        return None

    target_chat = cfg.get("acervo_channel_notify_chat", "@partiturasecia")
    if not target_chat:
        target_chat = "@partiturasecia"

    # Trata formato do target_chat (URL, @usuario ou ID numérico)
    if isinstance(target_chat, str):
        target_chat = target_chat.strip()
        if "t.me/" in target_chat:
            target_chat = target_chat.split("t.me/")[-1].strip().strip("/")
            if not target_chat.startswith("@") and not target_chat.startswith("-"):
                target_chat = f"@{target_chat}"
        elif not target_chat.startswith("@") and not target_chat.startswith("-") and not target_chat.isdigit():
            target_chat = f"@{target_chat}"
        elif target_chat.lstrip("-").isdigit():
            target_chat = int(target_chat)

    if not title:
        title = clean_file_title(file_name, caption)
    badge_short, format_name, format_icon = get_file_format_info(file_name, file_type)
    file_size_str = format_bytes(file_size) if file_size else ""

    # Obtém o link do canal específico (tenta detectar/gerar se for admin e não tiver)
    channel_link = get_channel_invite_link(cfg, channel_id, channel_username)
    if not channel_link or channel_link == cfg.get("acervo_chatlist_url", ""):
        try:
            chat = await bot.get_chat(channel_id)
            link = chat.invite_link or (f"https://t.me/{chat.username}" if chat.username else None)
            if not link:
                try:
                    link = await bot.export_chat_invite_link(channel_id)
                except Exception:
                    try:
                        il = await bot.create_chat_invite_link(channel_id, name="Acervo Partituras")
                        link = il.invite_link
                    except Exception:
                        link = None
            if link:
                channel_link = link
                if "channel_invite_links" not in cfg:
                    cfg["channel_invite_links"] = {}
                cfg["channel_invite_links"][str(channel_id)] = link
                save_config(cfg)
        except Exception as e_ch:
            logger.debug(f"Não foi possível obter link direto do canal {channel_id}: {e_ch}")

    if not channel_link:
        channel_link = cfg.get("acervo_chatlist_url", "https://t.me/addlist/H5UNPP0h4FI3ZTNh")

    # Link direto da postagem da partitura no canal
    post_url = ""
    if channel_username:
        u = channel_username.lstrip("@")
        post_url = f"https://t.me/{u}/{message_id}"
    else:
        cid_str = str(channel_id)
        if cid_str.startswith("-100"):
            cid_clean = cid_str[4:]
        elif cid_str.startswith("-"):
            cid_clean = cid_str[1:]
        else:
            cid_clean = cid_str
        post_url = f"https://t.me/c/{cid_clean}/{message_id}"

    # Informações do bot para o rodapé
    try:
        bot_info = await bot.get_me()
        bot_username = bot_info.username or "botpartituras_bot"
    except Exception:
        bot_username = "botpartituras_bot"

    size_part = f" • 💾 <b>Tamanho:</b> <code>{file_size_str}</code>" if file_size_str else ""
    file_display = f"📁 <b>Arquivo:</b> <code>{html.escape(file_name)}</code>\n" if file_name and file_name != title else ""

    card_text = (
        f"🎼 <b>NOVA PARTITURA NO ACERVO!</b>\n"
        f"──────────────────────────────\n"
        f"🎵 <b>Título:</b> <b>{html.escape(title.upper())}</b>\n"
        f"{file_display}"
        f"📄 <b>Tipo:</b> {format_icon} {format_name}{size_part}\n"
        f"📢 <b>Canal:</b> {html.escape(channel_title)}\n"
        f"──────────────────────────────\n"
        f"🔒 <b>Acesso ao Canal Privado:</b>\n"
        f"1️⃣ Toque em <b>'1º Entrar no Canal'</b> para se inscrever\n"
        f"2️⃣ Toque em <b>'2º Baixar Partitura'</b> para abrir o arquivo\n\n"
        f"🎵 <i>Enviado via @{bot_username}</i>"
    )

    buttons = []
    if channel_link:
        buttons.append([InlineKeyboardButton(f"📢 1º Entrar no Canal ({channel_title[:16]})", url=channel_link)])
    if post_url:
        buttons.append([InlineKeyboardButton("📥 2º Baixar Partitura", url=post_url)])
    buttons.append([InlineKeyboardButton("🔍 Pesquisar no Acervo", switch_inline_query_current_chat="")])

    markup = InlineKeyboardMarkup(buttons)

    try:
        sent_msg = await bot.send_message(
            chat_id=target_chat,
            text=card_text,
            parse_mode=ParseMode.HTML,
            reply_markup=markup,
            disable_web_page_preview=True
        )
        logger.info(f"[Acervo Notificação] 📢 Notificado no grupo {target_chat}: '{title}' ({channel_title})")
        return sent_msg
    except Exception as e:
        logger.warning(f"[Acervo Notificação] Não foi possível avisar no grupo {target_chat}: {e}")
        return None


def get_all_acervo_channels(cfg: dict) -> list:
    """Retorna lista unificada de todos os canais do acervo (banco + vinculados)."""
    db_channels = acervo_db.get_channels_summary()
    seen_ids = set()
    result = []

    for ch in db_channels:
        cid = ch["channel_id"]
        seen_ids.add(str(cid))
        seen_ids.add(str(cid).replace("-100", "").replace("-", ""))
        result.append(ch)

    for lch in cfg.get("linked_channels", []):
        cid = lch.get("id")
        norm = str(cid).replace("-100", "").replace("-", "")
        if str(cid) not in seen_ids and norm not in seen_ids:
            seen_ids.add(str(cid))
            result.append({
                "channel_id": cid,
                "channel_title": lch.get("title", f"Canal {cid}"),
                "channel_username": lch.get("username", ""),
                "qtd": 0
            })
    return result


def generate_channel_links_menu_text_and_kb():
    """Gera o menu com a lista de canais e seus links de convite para configuração."""
    cfg = load_config()
    channels = get_all_acervo_channels(cfg)
    fallback_chatlist = cfg.get("acervo_chatlist_url", "https://t.me/addlist/H5UNPP0h4FI3ZTNh")

    lines = [
        "🔗 ════════════════════════ 🔗",
        "   <b>LINKS DE ENTRADA DOS CANAIS</b>",
        "🔗 ════════════════════════ 🔗\n",
        "Configure o link de entrada de cada canal do acervo. Quando alguém buscar uma partitura, "
        "o bot enviará o botão com o link para a pessoa <b>entrar no canal específico daquele arquivo</b>!\n"
    ]

    kb = []
    kb.append([InlineKeyboardButton("🔄 Detectar Links Automaticamente", callback_data="acervo:autodetect_links")])

    if not channels:
        lines.append("⚠️ <i>Nenhum canal indexado no acervo ainda.</i>\n")
    else:
        for ch in channels:
            cid = ch["channel_id"]
            title = ch.get("channel_title") or f"Canal {cid}"
            qtd = ch.get("qtd", 0)

            link = get_channel_invite_link(cfg, cid, ch.get("channel_username", ""))

            if link and link != fallback_chatlist:
                status_icon = "✅"
                link_display = f"<code>{html.escape(link)}</code>"
            else:
                status_icon = "⚠️"
                link_display = "<i>Sem link próprio (usando link geral)</i>"

            lines.append(f"📢 <b>{html.escape(title)}</b> ({qtd} partituras)")
            lines.append(f"   {status_icon} Link: {link_display}\n")

            kb.append([
                InlineKeyboardButton(f"🔗 Configurar: {title[:20]}", callback_data=f"acervo:edit_link:{cid}")
            ])

    lines.append("💡 <i>Toque em um canal para colar o link (t.me/+...), ou use /setlink.</i>")
    kb.append([InlineKeyboardButton("◀ Voltar ao Acervo", callback_data="acervo:menu")])

    return "\n".join(lines), InlineKeyboardMarkup(kb)


def generate_inline_autodel_menu_text_and_kb():
    """Gera o menu interativo para escolher o tempo de auto-exclusão das buscas inline no grupo."""
    cfg = load_config()
    current_sec = cfg.get("inline_auto_delete_seconds", 0)

    if current_sec == 0:
        cur_lbl = "Não apagar (Permanente) 🟢"
    elif current_sec < 60:
        cur_lbl = f"{current_sec} segundos"
    elif current_sec < 3600:
        cur_lbl = f"{current_sec // 60} minutos"
    else:
        hours = current_sec / 3600
        cur_lbl = f"{int(hours) if hours.is_integer() else hours} hora(s)"

    text = (
        "⏱️ ════════════════════════ ⏱️\n"
        "   <b>APAGAR BUSCA INLINE NO GRUPO</b>\n"
        "⏱️ ════════════════════════ ⏱️\n\n"
        "Quando membros pesquisarem com <code>@botpartituras_bot</code> e enviarem a partitura no grupo, "
        "o bot pode apagar essa mensagem automaticamente após o tempo escolhido para manter o grupo limpo e organizado!\n\n"
        f"⚙️ <b>Tempo configurado atualmente:</b> <code>{cur_lbl}</code>\n\n"
        "<i>Toque em uma das opções abaixo para alterar:</i>"
    )

    def mark(val):
        return " ✅" if current_sec == val else ""

    kb = [
        [InlineKeyboardButton(f"❌ Não apagar (Permanente){mark(0)}", callback_data="acervo:set_inline_del:0")],
        [
            InlineKeyboardButton(f"⏱️ 5 min{mark(300)}", callback_data="acervo:set_inline_del:300"),
            InlineKeyboardButton(f"⏱️ 10 min{mark(600)}", callback_data="acervo:set_inline_del:600")
        ],
        [
            InlineKeyboardButton(f"⏱️ 20 min{mark(1200)}", callback_data="acervo:set_inline_del:1200"),
            InlineKeyboardButton(f"⏱️ 30 min{mark(1800)}", callback_data="acervo:set_inline_del:1800")
        ],
        [
            InlineKeyboardButton(f"⏱️ 45 min{mark(2700)}", callback_data="acervo:set_inline_del:2700"),
            InlineKeyboardButton(f"⏱️ 1 hora{mark(3600)}", callback_data="acervo:set_inline_del:3600")
        ],
        [
            InlineKeyboardButton(f"⏱️ 2 horas{mark(7200)}", callback_data="acervo:set_inline_del:7200"),
            InlineKeyboardButton(f"⏱️ 24 horas{mark(86400)}", callback_data="acervo:set_inline_del:86400")
        ],
        [InlineKeyboardButton("◀ Voltar ao Acervo", callback_data="acervo:menu")]
    ]
    return text, InlineKeyboardMarkup(kb)


def generate_acervo_dashboard_text_and_kb():
    """Gera o texto e teclado do painel administrativo do Acervo."""
    stats = acervo_db.get_stats()
    cfg = load_config()
    linked_c = cfg.get("linked_channels", [])

    total_files = stats.get("total_files", 0)
    total_chans = stats.get("total_channels", 0)
    by_type = stats.get("by_type", {})
    top_channels = stats.get("top_channels", [])

    docs_count = by_type.get("document", 0)
    aud_count = by_type.get("audio", 0)

    auto_reply_on = cfg.get("acervo_group_auto_reply", False)
    auto_reply_badge = "ATIVADO 🟢" if auto_reply_on else "DESATIVADO 🔴"

    inline_autodel = cfg.get("inline_auto_delete_seconds", 0)
    if inline_autodel == 0:
        inline_autodel_label = "Não apagar 🟢"
    elif inline_autodel < 60:
        inline_autodel_label = f"{inline_autodel}s ⏳"
    elif inline_autodel < 3600:
        inline_autodel_label = f"{inline_autodel // 60} min ⏳"
    else:
        hours = inline_autodel / 3600
        inline_autodel_label = f"{int(hours) if hours.is_integer() else hours}h ⏳"

    notify_enabled = cfg.get("acervo_channel_notify_enabled", True)
    notify_chat = cfg.get("acervo_channel_notify_chat", "@partiturasecia")
    notify_badge = "🟢 Ativado" if notify_enabled else "🔴 Desativado"

    lines = [
        "🎼 ══════════════════════ 🎼",
        "   <b>ACERVO GLOBAL DE PARTITURAS</b>",
        "🎼 ══════════════════════ 🎼\n",
        f"📊 <b>Total de Partituras Indexadas:</b> <code>{total_files}</code>",
        f"📄 <b>Documentos / PDFs:</b> <code>{docs_count}</code>",
        f"🎵 <b>Áudios / Playbacks:</b> <code>{aud_count}</code>",
        f"📢 <b>Canais no Acervo:</b> <code>{total_chans}</code> (de {len(linked_c)} vinculados)",
        f"📢 <b>Avisar Novas Partituras no Grupo:</b> <code>{notify_badge}</code> (<code>{html.escape(str(notify_chat))}</code>)",
        f"🗑️ <b>Apagar Busca Inline no Grupo:</b> <code>{inline_autodel_label}</code>",
        f"🤖 <b>Auto-Resposta no Grupo:</b> <code>{auto_reply_badge}</code>\n"
    ]

    if top_channels:
        lines.append("🏆 <b>Top Canais no Acervo:</b>")
        for ch in top_channels:
            t = ch.get("channel_title") or f"Canal {ch.get('channel_id')}"
            qtd = ch.get("qtd", 0)
            lines.append(f"  • <b>{html.escape(t[:25])}:</b> <code>{qtd}</code> partituras")
        lines.append("")

    lines.append(
        "💡 <b>Como Usar a Busca Instantânea (@):</b>\n"
        "Em qualquer chat ou grupo, basta digitar:\n"
        "<code>@SeuBot &lt;nome da música ou número&gt;</code>\n"
        "<i>(Ex: @SeuBot Harpa 15 ou @SeuBot Sax)</i>\n\n"
        "🤖 <b>Auto-Resposta Inteligente no Grupo:</b>\n"
        "Quando membros pedem partituras no grupo, o bot consulta o acervo e responde na hora com link e botões!\n"
        "Toque no botão abaixo para ativar ou desativar a qualquer momento.\n\n"
        "📥 <b>Como Adicionar / Sincronizar:</b>\n"
        "1. <b>Automático:</b> Qualquer post novo com PDF nos canais vinculados entra na hora!\n"
        "2. <b>Exportação JSON (Recomendado):</b> Envie o arquivo <code>result.json</code> aqui no chat e o bot indexa 8.000 partituras em 2 segundos!\n"
        "3. <b>Encaminhamento:</b> Encaminhe mensagens dos canais direto aqui no privado!"
    )

    notify_enabled = cfg.get("acervo_channel_notify_enabled", True)
    notify_badge = "🟢 Ativado" if notify_enabled else "🔴 Desativado"

    kb = [
        [InlineKeyboardButton(f"📢 Avisos no Grupo: {notify_badge}", callback_data="acervo:toggle:group_notify")],
        [InlineKeyboardButton(f"🗑️ Apagar Busca Inline: {inline_autodel_label}", callback_data="acervo:inline_autodel_menu")],
        [InlineKeyboardButton("🔗 Links de Entrada dos Canais", callback_data="acervo:channel_links_menu")],
        [InlineKeyboardButton(f"🤖 Auto-Resposta: {auto_reply_badge}", callback_data="acervo:toggle:autoreply")],
        [InlineKeyboardButton("🔍 Testar Busca Agora", switch_inline_query_current_chat="")],
        [InlineKeyboardButton("🧹 Limpar Mensagens de Texto", callback_data="acervo:purge_chatter")],
        [InlineKeyboardButton("🔄 Sincronizar / Varrer Canais", callback_data="acervo:scan:menu")],
        [InlineKeyboardButton("📋 Ver Canais Vinculados", callback_data="cfg:chats:list")],
        [InlineKeyboardButton("◀ Voltar ao Painel", callback_data="cfg:page:1")]
    ]
    return "\n".join(lines), InlineKeyboardMarkup(kb)


async def cmd_acervo_dashboard(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Exibe painel administrativo do Acervo Global de Partituras."""
    msg = update.effective_message
    text, markup = generate_acervo_dashboard_text_and_kb()
    await msg.reply_text(text, parse_mode=ParseMode.HTML, reply_markup=markup)


async def handle_acervo_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Controlador de botões interativos do Acervo."""
    query = update.callback_query
    if not query:
        return

    data = query.data

    if data == "acervo:purge_chatter":
        await query.answer("Varrendo o acervo para remover mensagens de texto...", show_alert=False)
        deleted = acervo_db.purge_text_chatter()
        await query.answer(f"Limpeza concluída! {deleted} mensagens de texto removidas com sucesso.", show_alert=True)
        text, markup = generate_acervo_dashboard_text_and_kb()
        try:
            await query.edit_message_text(text, parse_mode=ParseMode.HTML, reply_markup=markup)
        except Exception:
            pass
        return

    if data == "acervo:toggle:autoreply":
        cfg = load_config()
        new_val = not cfg.get("acervo_group_auto_reply", False)
        cfg["acervo_group_auto_reply"] = new_val
        save_config(cfg)
        status_txt = "ATIVADA 🟢" if new_val else "DESATIVADA 🔴"
        await query.answer(f"Auto-resposta no grupo {status_txt}!", show_alert=True)
        text, markup = generate_acervo_dashboard_text_and_kb()
        try:
            await query.edit_message_text(text, parse_mode=ParseMode.HTML, reply_markup=markup)
        except Exception:
            pass
        return

    if data == "acervo:cycle_autodel":
        try:
            cfg = load_config()
            cycle_options = [0, 60, 120, 300, 600, 30]
            cur = cfg.get("acervo_auto_delete_seconds", 0)
            try:
                idx = cycle_options.index(cur)
                next_val = cycle_options[(idx + 1) % len(cycle_options)]
            except ValueError:
                next_val = 0
            cfg["acervo_auto_delete_seconds"] = next_val
            save_config(cfg)

            lbl = "Desativado (Permanente)" if next_val == 0 else ("30s (Efêmera ⚡)" if next_val == 30 else (f"{next_val // 60} min" if next_val >= 60 else f"{next_val}s"))
            try:
                await query.answer(f"Auto-apagar no grupo: {lbl}!", show_alert=True)
            except Exception:
                pass
            text, markup = generate_acervo_dashboard_text_and_kb()
            try:
                await query.edit_message_text(text, parse_mode=ParseMode.HTML, reply_markup=markup)
            except Exception:
                try:
                    await query.edit_message_text(text, reply_markup=markup)
                except Exception:
                    pass
        except Exception as e:
            logger.error(f"Erro ao ciclar auto-apagar do acervo: {e}", exc_info=True)
            try:
                await query.answer("Erro ao atualizar tempo.", show_alert=True)
            except Exception:
                pass
        return

    if data in ("acervo:menu", "cfg:sub:acervo"):
        await query.answer()
        text, markup = generate_acervo_dashboard_text_and_kb()
        try:
            await query.edit_message_text(text, parse_mode=ParseMode.HTML, reply_markup=markup)
        except Exception:
            await query.message.reply_text(text, parse_mode=ParseMode.HTML, reply_markup=markup)
        return

    if data == "acervo:inline_autodel_menu":
        await query.answer()
        text, markup = generate_inline_autodel_menu_text_and_kb()
        try:
            await query.edit_message_text(text, parse_mode=ParseMode.HTML, reply_markup=markup)
        except Exception:
            pass
        return

    if data.startswith("acervo:set_inline_del:"):
        sec = int(data.split(":")[-1])
        cfg = load_config()
        cfg["inline_auto_delete_seconds"] = sec
        save_config(cfg)

        if sec == 0:
            ans = "Busca inline no grupo: Não apagar (Permanente)!"
        elif sec < 60:
            ans = f"Busca inline será apagada após {sec}s!"
        elif sec < 3600:
            ans = f"Busca inline será apagada após {sec // 60} min!"
        else:
            ans = f"Busca inline será apagada após {sec // 3600}h!"

        try:
            await query.answer(ans, show_alert=True)
        except Exception:
            pass

        text, markup = generate_inline_autodel_menu_text_and_kb()
        try:
            await query.edit_message_text(text, parse_mode=ParseMode.HTML, reply_markup=markup)
        except Exception:
            pass
        return

    if data == "acervo:channel_links_menu":
        await query.answer()
        text, markup = generate_channel_links_menu_text_and_kb()
        try:
            await query.edit_message_text(text, parse_mode=ParseMode.HTML, reply_markup=markup)
        except Exception:
            pass
        return

    if data == "acervo:autodetect_links":
        await query.answer("Varrendo permissões e gerando links dos canais...", show_alert=False)
        cfg = load_config()
        if "channel_invite_links" not in cfg:
            cfg["channel_invite_links"] = {}

        channels = get_all_acervo_channels(cfg)
        detected_count = 0
        failed_channels = []

        for ch in channels:
            cid = ch["channel_id"]
            title = ch.get("channel_title") or f"Canal {cid}"
            try:
                chat = await context.bot.get_chat(cid)
                link = chat.invite_link or (f"https://t.me/{chat.username}" if chat.username else None)
                if not link:
                    link = await context.bot.export_chat_invite_link(cid)
                if link:
                    cfg["channel_invite_links"][str(cid)] = link
                    for lch in cfg.get("linked_channels", []):
                        if str(lch.get("id")) == str(cid):
                            lch["invite_link"] = link
                    detected_count += 1
            except Exception as e:
                failed_channels.append(title)
                logger.debug(f"Não foi possível auto-detectar link de {title}: {e}")

        save_config(cfg)
        msg_result = f"✅ Links detectados para {detected_count} canais!"
        if failed_channels:
            msg_result += f"\n⚠️ {len(failed_channels)} canais precisam de configuração manual."
        await query.answer(msg_result[:200], show_alert=True)
        text, markup = generate_channel_links_menu_text_and_kb()
        try:
            await query.edit_message_text(text, parse_mode=ParseMode.HTML, reply_markup=markup)
        except Exception:
            pass
        return

    if data.startswith("acervo:edit_link:"):
        c_id = data.split(":")[-1]
        from modules.panel import panel_handler
        user = update.effective_user
        cfg = load_config()
        channels = get_all_acervo_channels(cfg)
        chan_title = "Canal"
        for ch in channels:
            if str(ch["channel_id"]) == str(c_id):
                chan_title = ch.get("channel_title", "Canal")
                break

        panel_handler.pending_inputs[user.id] = {
            "action": "acervo:set_channel_link",
            "target_id": c_id,
            "channel_title": chan_title
        }
        await query.answer()
        await query.message.reply_text(
            f"🔗 <b>Definir Link de Entrada do Canal:</b>\n"
            f"📢 <b>{html.escape(chan_title)}</b> (ID: <code>{c_id}</code>)\n\n"
            f"Envie agora o link de convite deste canal (ex: <code>https://t.me/+AbCdEfGh</code> ou <code>@seucanal</code>):\n"
            f"<i>(Ou envie /cancelar para desistir)</i>",
            parse_mode=ParseMode.HTML
        )
        return

    if data == "acervo:scan:menu":
        await query.answer()
        cfg = load_config()
        linked_c = cfg.get("linked_channels", [])

        lines = [
            "🎼 ══════════════════════ 🎼",
            "   <b>SINCRONIZAÇÃO E VARREDURA DO ACERVO</b>",
            "🎼 ══════════════════════ 🎼\n",
            "Escolha a melhor forma de abastecer seu acervo musical:\n",
            "⚡ <b>1. Enviar Arquivo JSON (Super Rápido para 8.000 Partituras):</b>",
            "• No <b>Telegram Desktop</b> no computador, abra o canal do seu acervo.",
            "• Clique nos 3 pontinhos no topo direito ➔ <b>Exportar histórico do canal</b>.",
            "• Desmarque Fotos/Vídeos, marque apenas <b>Arquivos</b> ➔ Formato: <b>JSON</b>.",
            "• Arraste ou envie o arquivo <code>result.json</code> aqui nesta conversa privada!",
            "<i>(O bot indexa até 10.000 partituras em menos de 3 segundos!)</i>\n",
            "📥 <b>2. Encaminhar Mensagens dos Canais:</b>",
            "Selecione postagens com partituras nos seus canais e encaminhe direto para cá!\n",
            "🤖 <b>3. Varrer Canal Vinculado em Segundo Plano:</b>",
            "Selecione um canal vinculado abaixo para o bot verificar os posts:"
        ]

        buttons = []
        if linked_c:
            for ch in linked_c[:6]:
                cid = ch.get("id")
                title = ch.get("title") or f"Canal {cid}"
                buttons.append([InlineKeyboardButton(f"🔄 Varrer: {title[:25]}", callback_data=f"acervo:scan:do:{cid}")])
        else:
            buttons.append([InlineKeyboardButton("➕ Vincular um Canal Agora", callback_data="cfg:sub:link_channel")])

        buttons.append([InlineKeyboardButton("🔍 Testar Busca", switch_inline_query_current_chat="")])
        buttons.append([InlineKeyboardButton("◀ Voltar ao Acervo", callback_data="acervo:menu")])

        await query.edit_message_text("\n".join(lines), parse_mode=ParseMode.HTML, reply_markup=InlineKeyboardMarkup(buttons))
        return

    if data.startswith("acervo:scan:do:"):
        await query.answer("Iniciando varredura em segundo plano...", show_alert=False)
        cid_str = data.split("acervo:scan:do:")[1]
        try:
            channel_id = int(cid_str)
        except ValueError:
            await query.answer("ID de canal inválido.", show_alert=True)
            return

        cfg = load_config()
        ch_info = next((c for c in cfg.get("linked_channels", []) if c.get("id") == channel_id), None)
        ch_title = ch_info.get("title") if ch_info else f"Canal {channel_id}"

        status_msg = await query.message.reply_text(
            f"🔄 <b>Iniciando varredura em segundo plano:</b> <i>{html.escape(ch_title)}</i>\n"
            f"O bot está verificando os arquivos postados. Você receberá uma notificação quando terminar!",
            parse_mode=ParseMode.HTML
        )

        asyncio.create_task(scan_channel_task(
            bot=context.bot,
            channel_id=channel_id,
            admin_chat_id=query.from_user.id,
            status_message_id=status_msg.message_id,
            channel_title=ch_title
        ))
        return


async def scan_channel_task(bot, channel_id: int, admin_chat_id: int, status_message_id: int = None, channel_title: str = ""):
    """
    Varredor resiliente em segundo plano de canais onde o bot é administrador.
    Verifica postagens sequenciais e salva no acervo sem travar o bot.
    """
    logger.info(f"[Varredura] Iniciada para canal {channel_title} ({channel_id})")
    found_count = 0
    checked_count = 0

    try:
        # Tenta descobrir o ID mais recente do canal postando e apagando mensagem de teste, ou escaneando
        # Começa de IDs recentes conhecidos ou faixa configurada
        cfg = load_config()
        ch_info = next((c for c in cfg.get("linked_channels", []) if c.get("id") == channel_id), {})
        ch_user = ch_info.get("username", "")

        # Varre faixas de IDs de mensagens usando cópia temporária para o chat do admin com auto-delete
        # Para respeitar os limites de flood da API do Telegram
        batch_size = 200
        # Se houver progresso anterior, continua de onde parou
        with acervo_db._get_connection() as conn:
            row = conn.execute("SELECT last_scanned_id, total_found FROM varredura_progresso WHERE channel_id = ?;", (channel_id,)).fetchone()
            start_id = (row[0] + 1) if row else 1

        curr_id = start_id
        empty_streak = 0
        max_empty_streak = 150  # Para após 150 IDs consecutivos inexistentes

        while empty_streak < max_empty_streak and checked_count < 1000:
            checked_count += 1
            try:
                # Tenta encaminhar para o admin temporariamente para inspecionar
                fwd = await bot.forward_message(chat_id=admin_chat_id, from_chat_id=channel_id, message_id=curr_id)
                empty_streak = 0
                media = extract_media_from_message(fwd)
                if media:
                    acervo_db.add_item(
                        file_id=media["file_id"],
                        channel_id=channel_id,
                        message_id=curr_id,
                        file_name=media.get("file_name", ""),
                        title=media.get("title", ""),
                        caption=media.get("caption", ""),
                        file_type=media.get("file_type", "document"),
                        file_size=media.get("file_size", 0),
                        file_unique_id=media.get("file_unique_id", ""),
                        channel_title=channel_title,
                        channel_username=ch_user
                    )
                    found_count += 1
                try:
                    await fwd.delete()
                except Exception:
                    pass
            except Exception:
                empty_streak += 1

            curr_id += 1
            if checked_count % 30 == 0:
                await asyncio.sleep(1.0)
            else:
                await asyncio.sleep(0.1)

        acervo_db.update_scan_progress(channel_id, channel_title, curr_id, found_count)

        done_text = (
            f"🎉 <b>Varredura Concluída!</b> 📢\n\n"
            f"• <b>Canal:</b> {html.escape(channel_title)}\n"
            f"• <b>Mensagens verificadas:</b> <code>{checked_count}</code>\n"
            f"• <b>Partituras adicionadas:</b> <code>{found_count}</code>\n\n"
            f"💡 <i>Você já pode buscar essas partituras digitando:</i>\n"
            f"<code>@{bot.username}</code> em qualquer chat!"
        )
        if status_message_id:
            try:
                await bot.edit_message_text(
                    chat_id=admin_chat_id,
                    message_id=status_message_id,
                    text=done_text,
                    parse_mode=ParseMode.HTML,
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("🔍 Testar Busca Agora", switch_inline_query_current_chat="")],
                        [InlineKeyboardButton("🎼 Ver Acervo", callback_data="acervo:menu")]
                    ])
                )
                return
            except Exception:
                pass
        await bot.send_message(chat_id=admin_chat_id, text=done_text, parse_mode=ParseMode.HTML)

    except Exception as e:
        logger.error(f"Erro na varredura do canal {channel_id}: {e}", exc_info=True)
        try:
            await bot.send_message(
                chat_id=admin_chat_id,
                text=f"⚠️ <b>Aviso na Varredura:</b> Não foi possível concluir a varredura completa automática ({e}).\n\n"
                     f"💡 <b>Dica de Ouro:</b> No Telegram Desktop, exporte o histórico do canal em JSON (leva 10s) e envie o arquivo <code>result.json</code> aqui para indexar tudo instantaneamente!",
                parse_mode=ParseMode.HTML
            )
        except Exception:
            pass
