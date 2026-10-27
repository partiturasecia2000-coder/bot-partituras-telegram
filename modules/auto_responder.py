import re
import time
import asyncio
import logging
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode
from telegram.ext import ContextTypes
from config import load_config, save_config, get_timezone
from modules.utils import AdminCache, safe_delete_message, safe_reply, format_placeholders, build_rich_buttons_markup, smart_send_message, smart_send_photo

logger = logging.getLogger("AutoResponder")

def validate_regex(pattern: str) -> tuple[bool, str]:
    """Valida se uma string é uma expressão regular válida."""
    if not pattern or not pattern.strip():
        return False, "O padrão não pode ser vazio."
    try:
        re.compile(pattern, re.IGNORECASE)
        return True, ""
    except re.error as e:
        return False, str(e)

def build_buttons_markup(buttons_data: list) -> InlineKeyboardMarkup | None:
    """Gera um InlineKeyboardMarkup a partir de uma lista de botões (suporta multi-colunas)."""
    return build_rich_buttons_markup(buttons_data)

def format_response_text(resp_text: str, user, chat, cfg: dict = None) -> str:
    """Substitui variáveis dinâmicas na mensagem de resposta (suporta variações com '---' e {RANDOM:...})."""
    if not resp_text:
        return ""
    # Divide por '---', '——', '===' ou '%%%' em linhas separadas para variações
    split_pattern = r"(?:^|\n)\s*(?:---|——+|===+|%%%+)\s*(?:\n|$)"
    if re.search(split_pattern, resp_text):
        import random
        variations = [p.strip() for p in re.split(split_pattern, resp_text) if p.strip()]
        if variations:
            resp_text = random.choice(variations)
    elif "---" in resp_text:
        import random
        variations = [p.strip() for p in resp_text.split("---") if p.strip()]
        if variations:
            resp_text = random.choice(variations)
    return format_placeholders(resp_text, user, chat, cfg)


class AutoResponderHandler:
    def __init__(self, admin_cache: AdminCache = None):
        self.admin_cache = admin_cache
        # Cache de regex compilados: { id: re.Pattern }
        self._compiled_cache = {}
        # Histórico de cooldown: { (chat_id, responder_id): last_timestamp }
        self._cooldowns = {}

    def _get_pattern(self, item: dict):
        item_id = item.get("id")
        raw_pattern = item.get("pattern", "")
        is_regex = item.get("is_regex", True)

        if item_id in self._compiled_cache:
            return self._compiled_cache[item_id]

        try:
            if is_regex:
                compiled = re.compile(raw_pattern, re.IGNORECASE)
            else:
                escaped = re.escape(raw_pattern.strip())
                compiled = re.compile(rf"(?i)\b{escaped}\b")
            self._compiled_cache[item_id] = compiled
            return compiled
        except re.error as e:
            logger.error(f"Erro ao compilar regex para resposta #{item_id}: {e}")
            return None

    def invalidate_cache(self, item_id: int = None):
        if item_id:
            self._compiled_cache.pop(item_id, None)
        else:
            self._compiled_cache.clear()

    async def _require_admin(self, update: Update) -> bool:
        if not self.admin_cache:
            return True
        chat = update.effective_chat
        user = update.effective_user
        if not chat or not user:
            return False
        if chat.type == "private":
            return True
        return await self.admin_cache.is_admin(chat, user.id)

    async def handle_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
        """Verifica se a mensagem dispara alguma resposta automática configurada."""
        message = update.effective_message
        chat = update.effective_chat
        user = update.effective_user

        if not message or not chat or not user:
            return False

        # Não ativa em chats privados
        if chat.type == "private":
            return False

        text = message.text or message.caption or ""
        if not text:
            return False

        cfg = load_config()
        responders = cfg.get("auto_responses", [])
        if not responders:
            return False

        now = time.time()

        for item in responders:
            if not item.get("enabled", True):
                continue

            pattern = self._get_pattern(item)
            if not pattern:
                continue

            # Verifica se o texto bate com a regex
            match = pattern.search(text)
            if match:
                item_id = item.get("id")
                cooldown = item.get("cooldown_seconds", 30)
                cd_key = (chat.id, item_id)

                # Verifica cooldown para não poluir o grupo
                last_time = self._cooldowns.get(cd_key, 0)
                if (now - last_time) < cooldown:
                    return False

                self._cooldowns[cd_key] = now

                formatted_text = format_response_text(item.get("text", ""), user, chat, cfg)
                markup = build_buttons_markup(item.get("buttons", []))
                photo = item.get("photo")
                reply_to_id = message.message_id if item.get("reply_to", True) else None

                delay = item.get("delay_seconds", 0)
                if delay > 0:
                    asyncio.create_task(self._send_delayed_response(
                        bot=context.bot,
                        chat_id=chat.id,
                        photo=photo,
                        text=formatted_text,
                        markup=markup,
                        delete_trigger=item.get("delete_trigger", False),
                        trigger_msg_id=message.message_id,
                        reply_to_id=reply_to_id,
                        delay=delay,
                        item_id=item_id,
                        user_id=user.id
                    ))
                    logger.info(f"Resposta automática #{item_id} agendada com delay de {delay}s para {user.id}")
                    return True

                try:
                    if photo:
                        await smart_send_photo(
                            bot=context.bot,
                            chat_id=chat.id,
                            photo=photo,
                            caption=formatted_text,
                            reply_markup=markup,
                            reply_to_message_id=reply_to_id
                        )
                    else:
                        await smart_send_message(
                            bot=context.bot,
                            chat_id=chat.id,
                            text=formatted_text,
                            reply_markup=markup,
                            reply_to_message_id=reply_to_id
                        )

                    logger.info(f"Resposta automática #{item_id} disparada para {user.id} no chat {chat.id}")

                    # Se configurado para apagar a mensagem que acionou o gatilho
                    if item.get("delete_trigger", False):
                        await safe_delete_message(context.bot, chat.id, message.message_id)

                    return True

                except Exception as e:
                    logger.error(f"Erro ao enviar resposta automática #{item_id}: {e}")

        return False

    async def _send_delayed_response(
        self,
        bot,
        chat_id: int,
        photo: str | None,
        text: str,
        markup: InlineKeyboardMarkup | None,
        delete_trigger: bool,
        trigger_msg_id: int,
        reply_to_id: int | None,
        delay: int,
        item_id: int,
        user_id: int
    ):
        """Envia a resposta automática após o delay configurado (em segundo plano sem travar o bot)."""
        try:
            await asyncio.sleep(delay)
            if photo:
                await smart_send_photo(
                    bot=bot,
                    chat_id=chat_id,
                    photo=photo,
                    caption=text,
                    reply_markup=markup,
                    reply_to_message_id=reply_to_id
                )
            else:
                await smart_send_message(
                    bot=bot,
                    chat_id=chat_id,
                    text=text,
                    reply_markup=markup,
                    reply_to_message_id=reply_to_id
                )
            logger.info(f"Resposta automática atrasada #{item_id} ({delay}s) disparada com sucesso para {user_id}")
            if delete_trigger and trigger_msg_id:
                await safe_delete_message(bot, chat_id, trigger_msg_id)
        except Exception as e:
            logger.error(f"Erro ao disparar resposta automática atrasada #{item_id} ({delay}s): {e}")

    async def test_responder(self, update: Update, context: ContextTypes.DEFAULT_TYPE, item_id: int):
        """Envia uma mensagem de teste para verificar como a resposta é exibida."""
        chat = update.effective_chat
        user = update.effective_user
        cfg = load_config()
        responders = cfg.get("auto_responses", [])

        target = next((r for r in responders if r.get("id") == item_id), None)
        if not target:
            return

        formatted_text = format_response_text(target.get("text", ""), user, chat, cfg)
        markup = build_buttons_markup(target.get("buttons", []))
        photo = target.get("photo")

        test_header = "🧪 *[TESTE DE RESPOSTA AUTOMÁTICA]*\n\n"
        final_text = test_header + formatted_text

        try:
            if photo:
                try:
                    await chat.send_photo(
                        photo=photo,
                        caption=final_text,
                        reply_markup=markup,
                        parse_mode=ParseMode.MARKDOWN
                    )
                except Exception:
                    await chat.send_photo(
                        photo=photo,
                        caption=final_text,
                        reply_markup=markup
                    )
            else:
                try:
                    await chat.send_message(
                        text=final_text,
                        reply_markup=markup,
                        parse_mode=ParseMode.MARKDOWN
                    )
                except Exception:
                    await chat.send_message(
                        text=final_text,
                        reply_markup=markup
                    )
        except Exception as e:
            logger.error(f"Erro no teste do auto-responder #{item_id}: {e}")

    # =====================================================================
    # COMANDOS DIRETOS VIA CHAT: /filtros, /filtro, /delfiltro
    # =====================================================================

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

    async def cmd_filtros(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Lista todas as respostas automáticas / filtros configurados."""
        if not await self._require_admin(update):
            await safe_reply(update, "⛔ Este comando é exclusivo para administradores.")
            return

        await self._clean_trigger(update)

        cfg = load_config()
        responders = cfg.get("auto_responses", [])

        if not responders:
            await safe_reply(
                update,
                "📋 *Respostas Automáticas / Filtros:*\n\n"
                "_Nenhum filtro cadastrado no momento._\n"
                "Para criar, use `/config` ou `/filtro <gatilho> <resposta>`.",
                parse_mode=ParseMode.MARKDOWN
            )
            return

        text = "🤖 *Respostas Automáticas & Filtros Regex:*\n\n"
        for item in responders:
            i_id = item.get("id")
            title = item.get("title", f"Filtro #{i_id}")
            pat = item.get("pattern", "")
            mode = "Regex" if item.get("is_regex", True) else "Palavra"
            status = "🟢 Ativo" if item.get("enabled", True) else "🔴 Inativo"
            cd = item.get("cooldown_seconds", 30)

            text += f"• *#{i_id}* - *{title}* ({status})\n"
            text += f"   Gatilho [{mode}]: `{pat}`\n"
            text += f"   Cooldown: `{cd}s`\n\n"

        text += "💡 _Dica: Gerencie visualmente clicando em_ `/config`."
        await safe_reply(update, text, parse_mode=ParseMode.MARKDOWN)

    async def cmd_filtro(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Cria ou edita um filtro rápido no chat."""
        if not await self._require_admin(update):
            await safe_reply(update, "⛔ Este comando é exclusivo para administradores.")
            return

        await self._clean_trigger(update)

        msg = update.effective_message
        args = context.args or []

        if not args:
            help_text = (
                "🎯 *Como usar o comando /filtro:*\n\n"
                "1️⃣ *Criando com texto direto:*\n"
                "`/filtro pix Nossa chave PIX é contato@email.com`\n\n"
                "2️⃣ *Em resposta a uma mensagem com foto ou texto:*\n"
                "Responda à mensagem desejada com:\n"
                "`/filtro <palavra-chave>`\n\n"
                "3️⃣ *Avançado (Regex completo):*\n"
                "Acesse o menu `/config` para criar filtros avançados com Regex e botões!"
            )
            await safe_reply(update, help_text, parse_mode=ParseMode.MARKDOWN)
            return

        trigger = args[0].strip()
        resp_text = " ".join(args[1:]).strip() if len(args) > 1 else ""
        photo = None

        # Se foi enviado em resposta a uma mensagem
        if msg.reply_to_message:
            reply = msg.reply_to_message
            if reply.photo:
                photo = reply.photo[-1].file_id
                if not resp_text and reply.caption:
                    resp_text = reply.caption
            elif not resp_text and reply.text:
                resp_text = reply.text

        if not resp_text and not photo:
            await safe_reply(update, "⚠️ Informe o texto da resposta após o gatilho ou responda a uma mensagem.")
            return

        cfg = load_config()
        responders = cfg.setdefault("auto_responses", [])

        # Verifica se já existe um item com esse gatilho
        existing = next((r for r in responders if r.get("pattern", "").lower() == trigger.lower()), None)

        if existing:
            existing["text"] = resp_text
            if photo:
                existing["photo"] = photo
            existing["enabled"] = True
            save_config(cfg)
            self.invalidate_cache(existing.get("id"))
            await safe_reply(
                update,
                f"✅ *Filtro atualizado com sucesso!*\n\n"
                f"• Gatilho: `{trigger}`\n"
                f"• Resposta: _{resp_text[:100]}..._\n",
                parse_mode=ParseMode.MARKDOWN
            )
        else:
            new_id = (max([r.get("id", 0) for r in responders] or [0])) + 1
            new_item = {
                "id": new_id,
                "title": f"Filtro: {trigger[:20]}",
                "pattern": trigger,
                "is_regex": False,  # Se criado via comando rápido, modo simples por padrão
                "text": resp_text,
                "photo": photo,
                "buttons": [],
                "cooldown_seconds": 15,
                "reply_to": True,
                "delete_trigger": False,
                "enabled": True
            }
            responders.append(new_item)
            save_config(cfg)
            self.invalidate_cache(new_id)

            await safe_reply(
                update,
                f"✅ *Novo filtro #{new_id} criado com sucesso!*\n\n"
                f"• Gatilho: `{trigger}`\n"
                f"• Resposta: _{resp_text[:100]}..._\n\n"
                "💡 Para transformar em Regex ou adicionar botões, acesse `/config`.",
                parse_mode=ParseMode.MARKDOWN
            )

    async def cmd_delfiltro(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Remove um filtro pelo ID ou pelo gatilho."""
        if not await self._require_admin(update):
            await safe_reply(update, "⛔ Este comando é exclusivo para administradores.")
            return

        await self._clean_trigger(update)

        msg = update.effective_message
        args = context.args or []

        if not args:
            await safe_reply(update, "⚠️ Uso: `/delfiltro <id ou palavra-chave>`\nExemplo: `/delfiltro 1` ou `/delfiltro pix`", parse_mode=ParseMode.MARKDOWN)
            return

        target = args[0].strip()
        cfg = load_config()
        responders = cfg.get("auto_responses", [])

        to_remove = None
        if target.isdigit():
            t_id = int(target)
            to_remove = next((r for r in responders if r.get("id") == t_id), None)
        else:
            to_remove = next((r for r in responders if r.get("pattern", "").lower() == target.lower() or r.get("title", "").lower() == target.lower()), None)

        if not to_remove:
            await safe_reply(update, f"❌ Nenhum filtro encontrado com o identificador `{target}`.", parse_mode=ParseMode.MARKDOWN)
            return

        cfg["auto_responses"] = [r for r in responders if r.get("id") != to_remove.get("id")]
        save_config(cfg)
        self.invalidate_cache(to_remove.get("id"))

        await safe_reply(update, f"✅ Filtro #{to_remove.get('id')} (`{to_remove.get('pattern')}`) excluído com sucesso!", parse_mode=ParseMode.MARKDOWN)
