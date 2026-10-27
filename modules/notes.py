import logging
import re
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode
from telegram.ext import ContextTypes
from config import load_config, save_config
from modules.utils import AdminCache, safe_delete_message, schedule_message_deletion, safe_reply, build_rich_buttons_markup, parse_rich_buttons, smart_send_message, smart_send_photo

logger = logging.getLogger("NotesModule")

def parse_note_buttons(text: str) -> tuple[str, list]:
    """Extrai botões inline do texto (suportando colunas e grid)."""
    buttons = parse_rich_buttons(text)
    clean_lines = []
    for line in text.split("\n"):
        # Se for uma linha que só contém botões, remove do texto limpo
        if ("|" in line or "http://" in line or "https://" in line or "t.me/" in line) and ("[" in line or "|" in line or "&&" in line):
            continue
        clean_lines.append(line)
    clean_text = "\n".join(clean_lines).strip()
    return clean_text, buttons

def build_buttons_markup(buttons: list):
    return build_rich_buttons_markup(buttons)


class NotesHandler:
    def __init__(self, admin_cache: AdminCache):
        self.admin_cache = admin_cache

    async def _require_admin(self, update: Update) -> bool:
        chat = update.effective_chat
        user = update.effective_user
        if not chat or not user:
            return False
        if chat.type == "private":
            return True
        return await self.admin_cache.is_admin(chat, user.id)

    async def _clean_trigger(self, update: Update):
        """Apaga a mensagem do comando caso configurado."""
        chat = update.effective_chat
        msg = update.effective_message
        if chat and chat.type != "private" and msg:
            cfg = load_config()
            if cfg.get("command_cleanup", {}).get("delete_admin_commands", True):
                try:
                    await safe_delete_message(update.get_bot(), chat.id, msg.message_id)
                except Exception:
                    pass

    async def cmd_save(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Salva uma nova anotação / nota (estilo Rose Bot).
        Uso:
          /save <nome> <texto>
          Ou em resposta a foto/documento/texto: /save <nome> [legenda opcional]
        """
        msg = update.effective_message
        if not await self._require_admin(update):
            await safe_reply(update, "⛔ Apenas administradores podem salvar notas.")
            return

        await self._clean_trigger(update)

        if not context.args:
            await safe_reply(
                update,
                "📌 *Como salvar uma nota (Estilo Rose Bot):*\n\n"
                "1. `/save <nome> <conteudo>`\n"
                "   _Ex:_ `/save pix Chave PIX: contato@partiturasecia.com.br`\n\n"
                "2. Ou *responda* a uma Foto, Partitura PDF ou Áudio digitando:\n"
                "   `/save <nome> [legenda opcional]`\n\n"
                "👉 *Depois, qualquer um pode chamar a nota digitando `#nome` no grupo!*",
                parse_mode=ParseMode.MARKDOWN
            )
            return

        note_name = context.args[0].lower().lstrip("#")
        reply = msg.reply_to_message

        raw_html = msg.text_html or msg.text or ""
        m_body = re.sub(r"^\/\w+(?:@\w+)?\s+\S+\s*", "", raw_html)
        text_arg = m_body.strip() if m_body != raw_html else ""

        photo_id = None
        doc_id = None
        audio_id = None
        buttons = []

        if reply:
            if reply.photo:
                photo_id = reply.photo[-1].file_id
            elif reply.document:
                doc_id = reply.document.file_id
            elif reply.audio:
                audio_id = reply.audio.file_id

            # Texto base da resposta ou do comando
            caption_or_text = text_arg or reply.caption_html or reply.text_html or reply.caption or reply.text or ""
            clean_text, buttons = parse_note_buttons(caption_or_text)
        else:
            if not text_arg:
                await safe_reply(update, "⚠️ Digite o conteúdo da nota ou responda a uma mensagem/arquivo.")
                return
            clean_text, buttons = parse_note_buttons(text_arg)

        cfg = load_config()
        notes = cfg.setdefault("notes", {})
        notes[note_name] = {
            "text": clean_text,
            "photo": photo_id,
            "document": doc_id,
            "audio": audio_id,
            "buttons": buttons
        }
        save_config(cfg)

        await safe_reply(
            update,
            f"✅ *Nota salva com sucesso!* 📌\n\n"
            f"Nome: `#{note_name}`\n"
            f"Mídia: `{'Foto' if photo_id else 'Documento' if doc_id else 'Áudio' if audio_id else 'Texto'}`\n"
            f"Botões: `{len(buttons)}`\n\n"
            f"💡 *Para chamar:* Envie `#{note_name}` ou `/get {note_name}` no grupo.",
            parse_mode=ParseMode.MARKDOWN
        )

    async def cmd_get(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Busca e envia uma nota pelo nome."""
        await self._clean_trigger(update)
        if not context.args:
            await safe_reply(update, "Uso: `/get <nome_da_nota>` (ex: `/get pix`)", parse_mode=ParseMode.MARKDOWN)
            return

        note_name = context.args[0].lower().lstrip("#")
        await self._send_note(update, note_name)

    async def cmd_notes(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Lista todas as notas salvas no grupo."""
        await self._clean_trigger(update)
        cfg = load_config()
        notes = cfg.get("notes", {})

        if not notes:
            await safe_reply(
                update,
                "📭 *Nenhuma nota salva neste grupo ainda.*\n\n"
                "Para criar uma nota, use:\n"
                "`/save <nome> <conteudo>` ou responda a um arquivo com `/save <nome>`.",
                parse_mode=ParseMode.MARKDOWN
            )
            return

        text = "📑 *Notas e Anotações Salvas no Grupo:*\n\n"
        text += "Para acessar qualquer nota, digite `#nome` no grupo ou use `/get <nome>`:\n\n"

        buttons = []
        row = []
        for name in sorted(notes.keys()):
            text += f"• `#{name}`\n"
            row.append(InlineKeyboardButton(f"#{name}", callback_data=f"note:get:{name}"))
            if len(row) == 2:
                buttons.append(row)
                row = []
        if row:
            buttons.append(row)

        markup = InlineKeyboardMarkup(buttons) if buttons else None
        await safe_reply(update, text, reply_markup=markup, parse_mode=ParseMode.MARKDOWN)

    async def cmd_clear(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Apaga uma nota pelo nome (apenas administradores)."""
        if not await self._require_admin(update):
            await safe_reply(update, "⛔ Apenas administradores podem apagar notas.")
            return

        await self._clean_trigger(update)

        if not context.args:
            await safe_reply(update, "Uso: `/clear <nome_da_nota>` ou `/delnota <nome>`", parse_mode=ParseMode.MARKDOWN)
            return

        note_name = context.args[0].lower().lstrip("#")
        cfg = load_config()
        notes = cfg.get("notes", {})

        if note_name in notes:
            del notes[note_name]
            save_config(cfg)
            await safe_reply(update, f"🗑️ Nota `#{note_name}` apagada com sucesso!", parse_mode=ParseMode.MARKDOWN)
        else:
            await safe_reply(update, f"❌ Nota `#{note_name}` não encontrada.")

    async def _send_note(self, update: Update, note_name: str, reply_to_id: int = None):
        """Envia o conteúdo de uma nota."""
        msg = update.effective_message
        chat = update.effective_chat
        cfg = load_config()
        notes = cfg.get("notes", {})

        note = notes.get(note_name)
        if not note:
            return False

        text = note.get("text", "")
        photo_id = note.get("photo")
        doc_id = note.get("document")
        audio_id = note.get("audio")
        markup = build_buttons_markup(note.get("buttons", []))

        target_reply = reply_to_id or (msg.message_id if msg else None)

        try:
            if photo_id:
                await smart_send_photo(bot=context.bot if context else chat.get_bot(), chat_id=chat.id, photo=photo_id, caption=text, reply_markup=markup)
            elif doc_id:
                try:
                    await chat.send_document(document=doc_id, caption=text, reply_markup=markup, reply_to_message_id=target_reply, parse_mode=ParseMode.MARKDOWN)
                except Exception:
                    await chat.send_document(document=doc_id, caption=text, reply_markup=markup, reply_to_message_id=target_reply)
            elif audio_id:
                try:
                    await chat.send_audio(audio=audio_id, caption=text, reply_markup=markup, reply_to_message_id=target_reply, parse_mode=ParseMode.MARKDOWN)
                except Exception:
                    await chat.send_audio(audio=audio_id, caption=text, reply_markup=markup, reply_to_message_id=target_reply)
            else:
                await smart_send_message(bot=context.bot if context else chat.get_bot(), chat_id=chat.id, text=text, reply_markup=markup)
            return True
        except Exception as e:
            logger.error(f"Erro ao enviar nota {note_name}: {e}")
            return False

    async def check_hashtag_note(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
        """Verifica se a mensagem contém uma hashtag correspondente a uma nota salva (ex: #hinos)."""
        msg = update.effective_message
        if not msg or not msg.text:
            return False

        # Extrai hashtags da mensagem
        text = msg.text.strip()
        words = text.split()
        for w in words:
            if w.startswith("#") and len(w) > 1:
                name = w[1:].lower()
                cfg = load_config()
                if name in cfg.get("notes", {}):
                    reply_id = msg.reply_to_message.message_id if msg.reply_to_message else msg.message_id
                    await self._send_note(update, name, reply_to_id=reply_id)
                    return True
        return False

    async def handle_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Gerencia cliques nos botões de notas da lista."""
        query = update.callback_query
        data = query.data
        if not data.startswith("note:get:"):
            return

        note_name = data.split(":")[-1]
        await query.answer()
        await self._send_note(update, note_name)
