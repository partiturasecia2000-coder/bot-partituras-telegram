import re
import time
import logging
from datetime import datetime
from telegram import Update, ChatMember, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ChatMemberStatus, ParseMode
from telegram.ext import ContextTypes

logger = logging.getLogger("BotUtils")

def format_placeholders(text: str, user=None, chat=None, cfg: dict = None) -> str:
    """Substitui variáveis dinâmicas na mensagem de forma segura e flexível (ex: {name}, {MENTION}, {group})."""
    if not text:
        return ""

    name = "Membro"
    last_name = ""
    username = "Membro"
    user_id = "0"
    if user:
        name = user.first_name or "Membro"
        last_name = user.last_name or ""
        username = f"@{user.username}" if user.username else name
        user_id = str(user.id)

    full_name = f"{name} {last_name}".strip()
    group_title = (chat.title or "Grupo") if chat else "Grupo"

    # Se o texto já usa HTML, gera o mention em HTML, caso contrário em Markdown
    is_html = "<" in text and ">" in text
    if is_html:
        import html as html_lib
        safe_name = html_lib.escape(name)
        safe_fullname = html_lib.escape(full_name)
        safe_username = html_lib.escape(username)
        safe_group = html_lib.escape(group_title)
        mention_tag = f'<a href="tg://user?id={user_id}">{safe_name}</a>'
    else:
        safe_name = name
        safe_fullname = full_name
        safe_username = username
        safe_group = group_title
        mention_tag = f"[{name}](tg://user?id={user_id})"

    from config import get_timezone
    try:
        now_tz = datetime.now(get_timezone(cfg))
    except Exception:
        now_tz = datetime.now()
    date_str = now_tz.strftime("%d/%m/%Y")
    hour_str = now_tz.strftime("%H:%M")

    replacements = {
        "{name}": safe_name,
        "{NAME}": safe_name,
        "{fullname}": safe_fullname,
        "{FULLNAME}": safe_fullname,
        "{username}": safe_username,
        "{USERNAME}": safe_username,
        "{mention}": mention_tag,
        "{MENTION}": mention_tag,
        "{id}": user_id,
        "{ID}": user_id,
        "{group}": safe_group,
        "{GROUP}": safe_group,
        "{date}": date_str,
        "{DATE}": date_str,
        "{hour}": hour_str,
        "{HOUR}": hour_str,
        "{rules}": (cfg.get("rules", "") if cfg else "") or "Respeite todos os membros e evite spam.",
        "{regras}": (cfg.get("rules", "") if cfg else "") or "Respeite todos os membros e evite spam.",
    }

    result = text
    for k, v in replacements.items():
        result = result.replace(k, v)

    # Suporte a Spintax / Variações randômicas: {RANDOM:Olá|Oi|Opa} ou {VAR:op1|op2}
    import random
    def _pick_random(match):
        choices = [c.strip() for c in match.group(1).split("|") if c.strip()]
        return random.choice(choices) if choices else ""
    result = re.sub(r"\{(?:RANDOM|VAR|ALEATORIO):([^}]+)\}", _pick_random, result, flags=re.IGNORECASE)

    return result

def convert_rich_text(text: str) -> str:
    """
    Converte marcações intuitivas de mensagens enriquecidas, markdown e artigos para HTML nativo do Telegram:
    - Negrito: *texto* ou **texto** ou <b>texto</b>
    - Itálico: _texto_ ou <i>texto</i>
    - Sublinhado: __texto__ ou <u>texto</u>
    - Tachado / Riscado: ~texto~ ou ~~texto~~ ou <s>texto</s>
    - Spoiler: ||texto|| ou <tg-spoiler>texto</tg-spoiler>
    - Código inline: `código` ou <code>código</code>
    - Bloco de código: ```bloco``` ou <pre>bloco</pre>
    - Links: [texto](url) ou <a href="url">texto</a>
    - Citação Simples: > citação ou <blockquote>texto</blockquote>
    - Citação Expansível / Artigo: >> citação ou [artigo]texto[/artigo] ou <blockquote expandable>texto</blockquote>
    """
    if not text:
        return ""

    # 1. Escapa ampersands soltos para evitar que quebrem o parser HTML
    text = re.sub(r"&(?!amp;|lt;|gt;|quot;)", "&amp;", text)

    # 2. Converte tags amigáveis de artigo expansível [artigo]...[/artigo]
    text = re.sub(
        r"\[(?:artigo|article|expandir|expandable)\]([\s\S]*?)\[\/(?:artigo|article|expandir|expandable)\]",
        r"<blockquote expandable>\1</blockquote>",
        text,
        flags=re.IGNORECASE
    )

    # 3. Converte linhas começando com >> (expansível) ou > (simples)
    lines = text.split("\n")
    new_lines = []
    in_exp = False
    in_quote = False
    buf = []

    for line in lines:
        if line.startswith(">> ") or line.startswith("&gt;&gt; "):
            if in_quote:
                joined = " ".join(buf)
                new_lines.append(f"<blockquote>{joined}</blockquote>")
                buf = []
                in_quote = False
            c = line[3:] if line.startswith(">> ") else line[9:]
            buf.append(c)
            in_exp = True
        elif line.startswith("> ") or line.startswith("&gt; "):
            if in_exp:
                joined = " ".join(buf)
                new_lines.append(f"<blockquote expandable>{joined}</blockquote>")
                buf = []
                in_exp = False
            c = line[2:] if line.startswith("> ") else line[5:]
            buf.append(c)
            in_quote = True
        else:
            if in_exp:
                joined = " ".join(buf)
                new_lines.append(f"<blockquote expandable>{joined}</blockquote>")
                buf = []
                in_exp = False
            if in_quote:
                joined = " ".join(buf)
                new_lines.append(f"<blockquote>{joined}</blockquote>")
                buf = []
                in_quote = False
            new_lines.append(line)

    if in_exp:
        joined = " ".join(buf)
        new_lines.append(f"<blockquote expandable>{joined}</blockquote>")
    if in_quote:
        joined = " ".join(buf)
        new_lines.append(f"<blockquote>{joined}</blockquote>")

    text = "\n".join(new_lines)

    # 4. Spoilers ||texto||
    text = re.sub(r"\|\|(.*?)\|\|", r"<tg-spoiler>\1</tg-spoiler>", text)

    # 5. Blocos de código ```codigo```
    text = re.sub(r"```([\s\S]*?)```", r"<pre>\1</pre>", text)

    # 6. Código inline `codigo`
    text = re.sub(r"`([^`\n]+)`", r"<code>\1</code>", text)

    # 7. Links [texto](url) - preserva botões que usam buttonurl:
    text = re.sub(r"\[([^\]]+)\]\((?!(?:buttonurl:))((?:https?://|t\.me/)[^\s)]+)\)", r'<a href="\2">\1</a>', text)

    # 8. Negrito **texto** e *texto*
    text = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", text)
    text = re.sub(r"(?<![\w\*])\*(?!\*)(.+?)(?<!\*)\*(?![\w\*])", r"<b>\1</b>", text)

    # 9. Sublinhado __texto__ e Itálico _texto_
    text = re.sub(r"(?<!\w)__(.+?)__(?!\w)", r"<u>\1</u>", text)
    text = re.sub(r"(?<!\w)_(.+?)_(?!\w)", r"<i>\1</i>", text)

    # 10. Tachado / Riscado ~~texto~~ e ~texto~
    text = re.sub(r"~~(.+?)~~", r"<s>\1</s>", text)
    text = re.sub(r"(?<!\w)~([^~\n]+)~(?![\w~])", r"<s>\1</s>", text)

    return text

def _build_button_dict(label: str, target: str) -> dict | None:
    """Cria um dicionário padronizado de botão (suportando regras, tutoriais, alertas e URLs)."""
    label = label.strip()
    target = target.strip().strip("()")
    if not label or not target:
        return None

    target_lower = target.lower()

    # 1. Regras do Grupo (modal interativo show_alert na tela do usuário)
    if target_lower in ("regras", "rules", "btn:rules", "#regras", "#rules"):
        return {"text": label, "callback_data": "btn:rules"}

    # 2. Tutorial de busca rápida de partituras (@botpartituras_bot)
    elif target_lower in ("tutorial", "comopesquisar", "como_pesquisar", "busca", "pesquisar", "btn:tutorial", "#tutorial"):
        return {"text": label, "callback_data": "btn:tutorial"}

    # 3. Alertas personalizados via modal show_alert: buttonalert:Texto ou alert:Texto
    elif target_lower.startswith("buttonalert:") or target_lower.startswith("alert:"):
        sep = ":" if ":" in target else " "
        alert_content = target.split(sep, 1)[1].strip()
        return {"text": label, "callback_data": f"btn:alert:{alert_content[:60]}"}

    # 4. Outros callbacks diretos btn:...
    elif target_lower.startswith("btn:"):
        return {"text": label, "callback_data": target}

    # 5. URLs convencionais (Web links, canais, grupos)
    else:
        url = target
        if not (url.startswith("http://") or url.startswith("https://") or url.startswith("t.me/")):
            url = "https://" + url
        return {"text": label, "url": url}

def parse_rich_buttons(text: str) -> list[list[dict]]:
    """
    Analisa texto com botões e retorna lista de linhas (permitindo múltiplos botões por linha).
    Formatos aceitos:
      1. Colchetes com links, regras ou tutoriais:
         [📜 Regras](regras) [🎥 Como Pesquisar](tutorial)
         [Canal Oficial](https://t.me/partiturasecia)
         [Aviso](buttonalert:Apenas partituras em PDF!)
      2. Colchetes com separador:
         [Texto 1 - https://link1.com] [Texto 2 - https://link2.com]
         [📜 Regras | regras] [🎥 Como Pesquisar | tutorial]
      3. Separadores na mesma linha: '&&' ou ':same':
         Regras | regras && Como Pesquisar | tutorial
      4. Linha simples:
         Regras | regras
         Canal | https://t.me/partiturasecia
    """
    rows = []
    lines = text.strip().split("\n")
    for line in lines:
        line = line.strip()
        if not line:
            continue

        row_buttons = []

        # 1. Padrões com colchetes: [Texto](destino) ou [Texto - destino] ou [Texto | destino]
        bracket_pattern = r"\[(.*?)\]\((?:buttonurl:)?(.*?)\)|\[(.*?)\s*(?:\||-|–)\s*(.*?)\]"
        matches = re.findall(bracket_pattern, line)
        if matches:
            for m in matches:
                b_text = (m[0] or m[2]).strip()
                b_target = (m[1] or m[3]).strip()
                b_dict = _build_button_dict(b_text, b_target)
                if b_dict:
                    row_buttons.append(b_dict)
            if row_buttons:
                rows.append(row_buttons)
                continue

        # 2. Separadores na mesma linha: '&&' ou ':same'
        if "&&" in line or " :same " in line:
            parts = re.split(r"\s*(?:&&|:same)\s*", line)
            for part in parts:
                sep = "|" if "|" in part else (" - " if " - " in part else None)
                if sep:
                    p_text, p_target = part.split(sep, 1)
                    b_dict = _build_button_dict(p_text.strip().strip("[]"), p_target.strip().strip("()"))
                    if b_dict:
                        row_buttons.append(b_dict)
            if row_buttons:
                rows.append(row_buttons)
                continue

        # 3. Linha simples: Texto | destino ou Texto - destino
        sep = "|" if "|" in line else (" - " if " - " in line else None)
        if sep:
            p_text, p_target = line.split(sep, 1)
            b_dict = _build_button_dict(p_text.strip().strip("[]"), p_target.strip().strip("()"))
            if b_dict:
                rows.append([b_dict])

    return rows

def build_rich_buttons_markup(buttons_data) -> InlineKeyboardMarkup | None:
    """Constrói um InlineKeyboardMarkup suportando grids multi-colunas ou listas flat (URLs e Callbacks)."""
    if not buttons_data:
        return None

    kb = []
    # Se já for uma lista de listas (linhas de botões)
    if isinstance(buttons_data, list) and buttons_data and isinstance(buttons_data[0], list):
        for row in buttons_data:
            kb_row = []
            for b in row:
                if isinstance(b, dict) and "text" in b:
                    if "callback_data" in b:
                        kb_row.append(InlineKeyboardButton(text=b["text"], callback_data=b["callback_data"]))
                    elif "url" in b:
                        kb_row.append(InlineKeyboardButton(text=b["text"], url=b["url"]))
            if kb_row:
                kb.append(kb_row)
    else:
        # Formato flat legado
        for item in buttons_data:
            if isinstance(item, dict) and "text" in item:
                if "callback_data" in item:
                    kb.append([InlineKeyboardButton(text=item["text"], callback_data=item["callback_data"])])
                elif "url" in item:
                    kb.append([InlineKeyboardButton(text=item["text"], url=item["url"])])

    return InlineKeyboardMarkup(kb) if kb else None

class AdminCache:
    """Cache em memória para administradores do grupo, evitando limites da API do Telegram."""
    def __init__(self, ttl: int = 60):
        self.ttl = ttl
        self._cache = {}  # (chat_id, user_id): (is_admin, expiry_time)

    async def is_admin(self, chat, user_id: int) -> bool:
        if not chat or not user_id:
            return False

        # Mensagens privadas sempre tratadas como livres de restrições de grupo
        if chat.type == "private":
            return True

        now = time.time()
        key = (chat.id, user_id)
        if key in self._cache:
            is_adm, expiry = self._cache[key]
            if now < expiry:
                return is_adm

        try:
            member = await chat.get_member(user_id)
            is_adm = member.status in (ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.OWNER)
            self._cache[key] = (is_adm, now + self.ttl)
            return is_adm
        except Exception as e:
            logger.debug(f"Não foi possível verificar status de admin para {user_id}: {e}")
            return False

    def invalidate(self, chat_id: int, user_id: int):
        self._cache.pop((chat_id, user_id), None)


async def safe_delete_message(bot, chat_id: int, message_id: int) -> bool:
    """Tenta apagar uma mensagem sem lançar exceções não tratadas."""
    try:
        await bot.delete_message(chat_id=chat_id, message_id=message_id)
        return True
    except Exception as e:
        logger.debug(f"Falha ao apagar mensagem {message_id} no chat {chat_id}: {e}")
        return False


async def _delete_job_callback(context: ContextTypes.DEFAULT_TYPE):
    """Callback do job_queue para apagar mensagem agendada."""
    data = context.job.data
    chat_id = data.get("chat_id")
    message_id = data.get("message_id")
    if chat_id and message_id:
        await safe_delete_message(context.bot, chat_id, message_id)


def schedule_message_deletion(context_or_jq, chat_id: int, message_id: int, delay_seconds: int, bot=None):
    """Agenda a exclusão de uma mensagem após X segundos usando o JobQueue ou fallback com asyncio."""
    if delay_seconds <= 0 or not context_or_jq:
        return

    jq = getattr(context_or_jq, "job_queue", context_or_jq)
    if jq and hasattr(jq, "run_once"):
        try:
            jq.run_once(
                _delete_job_callback,
                when=delay_seconds,
                data={"chat_id": chat_id, "message_id": message_id},
                name=f"del_{chat_id}_{message_id}"
            )
            return
        except Exception as e_jq:
            logger.debug(f"Falha ao agendar no JobQueue: {e_jq}")

    # Fallback com asyncio task caso JobQueue não esteja disponível
    bot_obj = bot or getattr(context_or_jq, "bot", None)
    if bot_obj:
        import asyncio
        async def _async_delete_task():
            try:
                await asyncio.sleep(delay_seconds)
                await safe_delete_message(bot_obj, chat_id, message_id)
            except Exception:
                pass
        try:
            asyncio.create_task(_async_delete_task())
        except Exception:
            pass
    else:
        logger.warning("JobQueue e bot não estão disponíveis para agendar exclusão de mensagem.")


async def safe_reply(update: Update, text: str, **kwargs):
    """Responde ao update com fallback para chat.send_message caso o comando original tenha sido apagado."""
    chat = getattr(update, "effective_chat", None)
    msg = getattr(update, "effective_message", None)
    if msg:
        try:
            return await msg.reply_text(text, **kwargs)
        except Exception:
            pass
    if chat:
        return await chat.send_message(text, **kwargs)
    return None


def split_long_text(text: str, max_length: int = 3900) -> list[str]:
    """Divide um texto longo em partes menores respeitando parágrafos e quebras de linha."""
    if not text or len(text) <= max_length:
        return [text] if text else []

    chunks = []
    current_chunk = []
    current_len = 0

    paragraphs = text.split("\n")
    for p in paragraphs:
        p_len = len(p) + 1
        if p_len > max_length:
            words = p.split(" ")
            sub_chunk = []
            sub_len = 0
            for w in words:
                w_len = len(w) + 1
                if sub_len + w_len > max_length:
                    if sub_chunk:
                        if current_chunk:
                            chunks.append("\n".join(current_chunk) + "\n" + " ".join(sub_chunk))
                            current_chunk = []
                            current_len = 0
                        else:
                            chunks.append(" ".join(sub_chunk))
                    sub_chunk = [w]
                    sub_len = w_len
                else:
                    sub_chunk.append(w)
                    sub_len += w_len
            if sub_chunk:
                current_chunk.append(" ".join(sub_chunk))
                current_len += len(" ".join(sub_chunk)) + 1
        elif current_len + p_len > max_length:
            chunks.append("\n".join(current_chunk))
            current_chunk = [p]
            current_len = p_len
        else:
            current_chunk.append(p)
            current_len += p_len

    if current_chunk:
        chunks.append("\n".join(current_chunk))

    return chunks


async def _send_single_smart_message(
    bot,
    chat_id: int | str,
    text: str,
    reply_markup=None,
    link_preview_options=None,
    message_thread_id=None,
    reply_to_message_id=None
):
    """Envia um fragmento de mensagem com suporte a HTML rico, Markdown e fallback limpo."""
    rich_html = convert_rich_text(text)
    extra_kwargs = {}
    if message_thread_id:
        extra_kwargs["message_thread_id"] = message_thread_id
    if link_preview_options:
        extra_kwargs["link_preview_options"] = link_preview_options
    if reply_to_message_id:
        extra_kwargs["reply_to_message_id"] = reply_to_message_id

    has_html_tags = bool(re.search(r"<\/?(blockquote|tg-spoiler|tg-emoji|span|b|strong|i|em|u|ins|s|strike|del|code|pre|a)[\s>]", rich_html, re.IGNORECASE))

    if has_html_tags:
        try:
            return await bot.send_message(
                chat_id=chat_id,
                text=rich_html,
                reply_markup=reply_markup,
                parse_mode=ParseMode.HTML,
                **extra_kwargs
            )
        except Exception as e_html:
            if "replied" in str(e_html).lower() or "reply" in str(e_html).lower():
                extra_kwargs.pop("reply_to_message_id", None)
            if "too long" in str(e_html).lower():
                raise e_html

    try:
        return await bot.send_message(
            chat_id=chat_id,
            text=text,
            reply_markup=reply_markup,
            parse_mode=ParseMode.MARKDOWN,
            **extra_kwargs
        )
    except Exception as e_md:
        if "replied" in str(e_md).lower() or "reply" in str(e_md).lower():
            extra_kwargs.pop("reply_to_message_id", None)
        if "too long" in str(e_md).lower():
            raise e_md

    clean_text = re.sub(r"<[^>]+>", "", rich_html)
    try:
        return await bot.send_message(
            chat_id=chat_id,
            text=clean_text,
            reply_markup=reply_markup,
            **extra_kwargs
        )
    except Exception as e_clean:
        if "reply_to_message_id" in extra_kwargs:
            extra_kwargs.pop("reply_to_message_id", None)
            return await bot.send_message(
                chat_id=chat_id,
                text=clean_text,
                reply_markup=reply_markup,
                **extra_kwargs
            )
        raise e_clean


async def smart_send_message(
    bot,
    chat_id: int | str,
    text: str,
    reply_markup=None,
    link_preview_options=None,
    message_thread_id=None,
    reply_to_message_id=None
):
    """
    Envia mensagens suportando formatações avançadas (HTML rico, Artigos expansíveis <blockquote expandable>, Spoilers, Markdown e botões em grade).
    Se o texto ultrapassar o limite do Telegram (4096 caracteres), divide automaticamente em partes seguras e entrega todas!
    """
    if not text:
        return None

    from config import normalize_chat_id
    chat_id = normalize_chat_id(chat_id)

    if len(text) > 3900:
        parts = split_long_text(text, max_length=3900)
        last_msg = None
        for i, part in enumerate(parts):
            is_last = (i == len(parts) - 1)
            cur_markup = reply_markup if is_last else None
            cur_reply_to = reply_to_message_id if i == 0 else None
            last_msg = await _send_single_smart_message(
                bot=bot,
                chat_id=chat_id,
                text=part,
                reply_markup=cur_markup,
                link_preview_options=link_preview_options,
                message_thread_id=message_thread_id,
                reply_to_message_id=cur_reply_to
            )
        return last_msg

    try:
        return await _send_single_smart_message(
            bot=bot,
            chat_id=chat_id,
            text=text,
            reply_markup=reply_markup,
            link_preview_options=link_preview_options,
            message_thread_id=message_thread_id,
            reply_to_message_id=reply_to_message_id
        )
    except Exception as e:
        if "too long" in str(e).lower():
            parts = split_long_text(text, max_length=3500)
            last_msg = None
            for i, part in enumerate(parts):
                is_last = (i == len(parts) - 1)
                cur_markup = reply_markup if is_last else None
                cur_reply_to = reply_to_message_id if i == 0 else None
                last_msg = await _send_single_smart_message(
                    bot=bot,
                    chat_id=chat_id,
                    text=part,
                    reply_markup=cur_markup,
                    link_preview_options=link_preview_options,
                    message_thread_id=message_thread_id,
                    reply_to_message_id=cur_reply_to
                )
            return last_msg
        if "supergroup" in str(e).lower() or "not a member" in str(e).lower():
            if str(chat_id).startswith("-") and not str(chat_id).startswith("-100"):
                alt_id = int(f"-100{abs(int(chat_id))}")
                logger.info(f"Auto-corrigindo envio de mensagem do chat {chat_id} para supergrupo {alt_id}...")
                return await _send_single_smart_message(
                    bot=bot,
                    chat_id=alt_id,
                    text=text,
                    reply_markup=reply_markup,
                    link_preview_options=link_preview_options,
                    message_thread_id=message_thread_id,
                    reply_to_message_id=reply_to_message_id
                )
        raise e


async def smart_send_photo(
    bot,
    chat_id: int | str,
    photo,
    caption: str = "",
    reply_markup=None,
    message_thread_id=None,
    reply_to_message_id=None
):
    """
    Envia fotos com suporte a legendas ricas. Se a legenda exceder o limite de 1024 caracteres do Telegram,
    envia a foto e publica o texto completo logo abaixo para não perder conteúdo nem dar erro de limite.
    """
    from config import normalize_chat_id
    chat_id = normalize_chat_id(chat_id)

    # Se a legenda for maior que 1000 caracteres, envia a foto e o texto detalhado em seguida
    if caption and len(caption) > 1000:
        extra = {}
        if message_thread_id:
            extra["message_thread_id"] = message_thread_id
        if reply_to_message_id:
            extra["reply_to_message_id"] = reply_to_message_id
        sent_photo = await bot.send_photo(chat_id=chat_id, photo=photo, **extra)
        sent_text = await smart_send_message(
            bot=bot,
            chat_id=chat_id,
            text=caption,
            reply_markup=reply_markup,
            message_thread_id=message_thread_id,
            reply_to_message_id=sent_photo.message_id
        )
        return sent_text or sent_photo

    extra_kwargs = {}
    if message_thread_id:
        extra_kwargs["message_thread_id"] = message_thread_id
    if reply_to_message_id:
        extra_kwargs["reply_to_message_id"] = reply_to_message_id

    rich_html = convert_rich_text(caption) if caption else ""
    has_html_tags = bool(re.search(r"<\/?(blockquote|tg-spoiler|tg-emoji|span|b|strong|i|em|u|ins|s|strike|del|code|pre|a)[\s>]", rich_html, re.IGNORECASE))

    if has_html_tags:
        try:
            return await bot.send_photo(
                chat_id=chat_id,
                photo=photo,
                caption=rich_html,
                reply_markup=reply_markup,
                parse_mode=ParseMode.HTML,
                **extra_kwargs
            )
        except Exception as e_html:
            if "replied" in str(e_html).lower() or "reply" in str(e_html).lower():
                extra_kwargs.pop("reply_to_message_id", None)
            if "too long" in str(e_html).lower():
                sent_photo = await bot.send_photo(chat_id=chat_id, photo=photo, **extra_kwargs)
                return await smart_send_message(bot=bot, chat_id=chat_id, text=caption, reply_markup=reply_markup, reply_to_message_id=sent_photo.message_id)

    try:
        return await bot.send_photo(
            chat_id=chat_id,
            photo=photo,
            caption=caption,
            reply_markup=reply_markup,
            parse_mode=ParseMode.MARKDOWN,
            **extra_kwargs
        )
    except Exception as e_md:
        if "replied" in str(e_md).lower() or "reply" in str(e_md).lower():
            extra_kwargs.pop("reply_to_message_id", None)
        if "too long" in str(e_md).lower():
            sent_photo = await bot.send_photo(chat_id=chat_id, photo=photo, **extra_kwargs)
            return await smart_send_message(bot=bot, chat_id=chat_id, text=caption, reply_markup=reply_markup, reply_to_message_id=sent_photo.message_id)

    clean_caption = re.sub(r"<[^>]+>", "", rich_html) if rich_html else caption
    try:
        return await bot.send_photo(
            chat_id=chat_id,
            photo=photo,
            caption=clean_caption,
            reply_markup=reply_markup,
            **extra_kwargs
        )
    except Exception as e_clean:
        if "too long" in str(e_clean).lower():
            sent_photo = await bot.send_photo(chat_id=chat_id, photo=photo, **extra_kwargs)
            return await smart_send_message(bot=bot, chat_id=chat_id, text=caption, reply_markup=reply_markup, reply_to_message_id=sent_photo.message_id)
        if "reply_to_message_id" in extra_kwargs:
            extra_kwargs.pop("reply_to_message_id", None)
            return await bot.send_photo(
                chat_id=chat_id,
                photo=photo,
                caption=clean_caption,
                reply_markup=reply_markup,
                **extra_kwargs
            )
        raise e_clean


async def smart_send_video(
    bot,
    chat_id: int | str,
    video,
    caption: str = "",
    reply_markup=None,
    message_thread_id=None,
    reply_to_message_id=None
):
    """
    Envia vídeos com suporte a legendas ricas. Se a legenda exceder 1024 caracteres,
    envia o vídeo e publica o texto completo logo abaixo com botões.
    """
    from config import normalize_chat_id
    chat_id = normalize_chat_id(chat_id)

    if caption and len(caption) > 1000:
        extra = {}
        if message_thread_id:
            extra["message_thread_id"] = message_thread_id
        if reply_to_message_id:
            extra["reply_to_message_id"] = reply_to_message_id
        sent_video = await bot.send_video(chat_id=chat_id, video=video, **extra)
        sent_text = await smart_send_message(
            bot=bot,
            chat_id=chat_id,
            text=caption,
            reply_markup=reply_markup,
            message_thread_id=message_thread_id,
            reply_to_message_id=sent_video.message_id
        )
        return sent_text or sent_video

    extra_kwargs = {}
    if message_thread_id:
        extra_kwargs["message_thread_id"] = message_thread_id
    if reply_to_message_id:
        extra_kwargs["reply_to_message_id"] = reply_to_message_id

    rich_html = convert_rich_text(caption) if caption else ""
    has_html_tags = bool(re.search(r"<\/?(blockquote|tg-spoiler|tg-emoji|span|b|strong|i|em|u|ins|s|strike|del|code|pre|a)[\s>]", rich_html, re.IGNORECASE))

    if has_html_tags:
        try:
            return await bot.send_video(
                chat_id=chat_id,
                video=video,
                caption=rich_html,
                reply_markup=reply_markup,
                parse_mode=ParseMode.HTML,
                **extra_kwargs
            )
        except Exception as e_html:
            if "replied" in str(e_html).lower() or "reply" in str(e_html).lower():
                extra_kwargs.pop("reply_to_message_id", None)
            if "too long" in str(e_html).lower():
                sent_video = await bot.send_video(chat_id=chat_id, video=video, **extra_kwargs)
                return await smart_send_message(bot=bot, chat_id=chat_id, text=caption, reply_markup=reply_markup, reply_to_message_id=sent_video.message_id)

    try:
        return await bot.send_video(
            chat_id=chat_id,
            video=video,
            caption=caption,
            reply_markup=reply_markup,
            parse_mode=ParseMode.MARKDOWN,
            **extra_kwargs
        )
    except Exception as e_md:
        if "replied" in str(e_md).lower() or "reply" in str(e_md).lower():
            extra_kwargs.pop("reply_to_message_id", None)
        if "too long" in str(e_md).lower():
            sent_video = await bot.send_video(chat_id=chat_id, video=video, **extra_kwargs)
            return await smart_send_message(bot=bot, chat_id=chat_id, text=caption, reply_markup=reply_markup, reply_to_message_id=sent_video.message_id)

    clean_caption = re.sub(r"<[^>]+>", "", rich_html) if rich_html else caption
    try:
        return await bot.send_video(
            chat_id=chat_id,
            video=video,
            caption=clean_caption,
            reply_markup=reply_markup,
            **extra_kwargs
        )
    except Exception as e_clean:
        if "too long" in str(e_clean).lower():
            sent_video = await bot.send_video(chat_id=chat_id, video=video, **extra_kwargs)
            return await smart_send_message(bot=bot, chat_id=chat_id, text=caption, reply_markup=reply_markup, reply_to_message_id=sent_video.message_id)
        if "reply_to_message_id" in extra_kwargs:
            extra_kwargs.pop("reply_to_message_id", None)
            return await bot.send_video(
                chat_id=chat_id,
                video=video,
                caption=clean_caption,
                reply_markup=reply_markup,
                **extra_kwargs
            )
        raise e_clean


def make_disabled_button(text: str, callback_data: str = "cfg:noop") -> InlineKeyboardButton:
    """
    Cria um botão desabilitado nativo no teclado inline (Telegram Bot API 10.3).
    O botão aparece com estilo desativado/cinza nativo e não dispara requisição.
    Possui fallback seguro para clientes anteriores.
    """
    try:
        return InlineKeyboardButton(text=text, callback_data=callback_data, api_kwargs={"disabled": True})
    except Exception:
        return InlineKeyboardButton(text=text, callback_data=callback_data)


async def send_ephemeral_or_temporary_warning(
    bot,
    chat_id: int | str,
    user_id: int,
    text: str,
    context: ContextTypes.DEFAULT_TYPE = None,
    delete_after_seconds: int = 8,
    parse_mode = None,
    reply_to_message_id = None
):
    """
    Envia aviso de moderação de forma EFÊMERA (Telegram Bot API 10.2 / 10.3),
    visível APENAS para o infrator no grupo, sem poluir a visão dos outros membros.
    Se o chat/cliente não suportar efêmeras, envia com auto-deleção padrão agendada.
    """
    from config import normalize_chat_id
    norm_chat_id = normalize_chat_id(chat_id)

    # 1. Tenta envio efêmero oficial da Bot API 10.2+ / 10.3
    try:
        eph_kwargs = {
            "chat_id": norm_chat_id,
            "text": text,
            "api_kwargs": {
                "ephemeral_message_parameters": {
                    "receiver_user_id": int(user_id)
                }
            }
        }
        if parse_mode:
            eph_kwargs["parse_mode"] = parse_mode
        if reply_to_message_id:
            eph_kwargs["reply_to_message_id"] = reply_to_message_id

        sent = await bot.send_message(**eph_kwargs)
        if sent:
            logger.info(f"Aviso efêmero (invisível para os outros) entregue para usuário {user_id} no chat {norm_chat_id}")
            return sent
    except Exception as e_eph:
        logger.debug(f"Envio efêmero não suportado no chat {norm_chat_id} ({e_eph}). Usando fallback padrão.")

    # 2. Fallback padrão: envia normal e agenda auto-deleção
    try:
        fallback_kwargs = {
            "chat_id": norm_chat_id,
            "text": text
        }
        if parse_mode:
            fallback_kwargs["parse_mode"] = parse_mode
        if reply_to_message_id:
            fallback_kwargs["reply_to_message_id"] = reply_to_message_id

        sent = await bot.send_message(**fallback_kwargs)
        if sent and context and delete_after_seconds > 0:
            schedule_message_deletion(context, norm_chat_id, sent.message_id, delete_after_seconds)
        return sent
    except Exception as e_fall:
        logger.error(f"Erro no fallback de envio de aviso temporário no chat {norm_chat_id}: {e_fall}")
        return None



