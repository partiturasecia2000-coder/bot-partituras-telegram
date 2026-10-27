import logging
import zoneinfo
from datetime import datetime
from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes
from config import load_config, save_config
from modules.utils import AdminCache, safe_delete_message, schedule_message_deletion, safe_reply

logger = logging.getLogger("NightModeModule")

def is_time_between(check_time, start_time, end_time):
    """Verifica se check_time (HH:MM) está entre start_time e end_time, inclusive cruzando a meia-noite."""
    sh, sm = map(int, start_time.split(":"))
    eh, em = map(int, end_time.split(":"))
    ch, cm = check_time.hour, check_time.minute

    start_min = sh * 60 + sm
    end_min = eh * 60 + em
    cur_min = ch * 60 + cm

    if start_min <= end_min:
        return start_min <= cur_min < end_min
    else:
        # Cruza a meia-noite (ex: 23:00 até 07:00)
        return cur_min >= start_min or cur_min < end_min

class NightModeHandler:
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

    async def cmd_nightmode(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Gerencia o Modo Noturno / Silêncio Noturno do grupo (Estilo Rose Bot).
        Uso:
          /noturno on [23:00-07:00]
          /noturno off
          /noturno avisos [on/off]
          /noturno testestart
          /noturno testeend
          /noturno (exibe status)
        """
        msg = update.effective_message
        chat = update.effective_chat
        if not await self._require_admin(update):
            await safe_reply(update, "⛔ Apenas administradores podem configurar o Modo Noturno.")
            return

        await self._clean_trigger(update)

        cfg = load_config()
        nm = cfg.setdefault("night_mode", {
            "enabled": False,
            "start": "23:00",
            "end": "07:00",
            "warn_delete_after_seconds": 8,
            "announce_start": True,
            "announce_end": True,
            "current_state": None,
            "enabled_chats": []
        })

        if not context.args:
            status_text = "🟢 *Ativado*" if nm.get("enabled", False) else "🔴 *Desativado*"
            s = nm.get("start", "23:00")
            e = nm.get("end", "07:00")
            av_start = "🔔 Ativado" if nm.get("announce_start", True) else "🔕 Desativado"
            av_end = "🔔 Ativado" if nm.get("announce_end", True) else "🔕 Desativado"
            cur_st = nm.get("current_state", "day")
            st_icon = "🌙 Noite (Silêncio)" if cur_st == "night" else "☀️ Dia (Liberado)"

            await safe_reply(
                update,
                f"🌙 *Modo Noturno / Silêncio Programado*\n\n"
                f"• Situação: {status_text}\n"
                f"• Horário de Silêncio: das `{s}` às `{e}`\n"
                f"• Estado Atual: {st_icon}\n"
                f"• Aviso de Início no Grupo: {av_start}\n"
                f"• Aviso de Término no Grupo: {av_end}\n\n"
                "💡 *Comandos disponíveis:*\n"
                "• Ativar: `/noturno on` (ou `/noturno on 23:00-07:00`)\n"
                "• Desativar: `/noturno off`\n"
                "• Ligar/Desligar avisos no grupo: `/noturno avisos on` ou `/noturno avisos off`\n"
                "• Testar aviso de início agora: `/noturno testestart`\n"
                "• Testar aviso de fim agora: `/noturno testeend`\n\n"
                "_Durante o silêncio, apenas administradores podem enviar mensagens no grupo._",
                parse_mode=ParseMode.MARKDOWN
            )
            return

        action = context.args[0].lower().strip()

        if action in ("on", "ativar", "ligar"):
            nm["enabled"] = True
            if len(context.args) > 1 and "-" in context.args[1]:
                parts = context.args[1].split("-")
                nm["start"] = parts[0].strip()
                nm["end"] = parts[1].strip()

            # Adiciona chat atual aos grupos monitorados se for grupo
            if chat and chat.type in ("group", "supergroup"):
                c_list = nm.setdefault("enabled_chats", [])
                if chat.id not in c_list:
                    c_list.append(chat.id)
                if not cfg.get("main_group_id"):
                    cfg["main_group_id"] = chat.id
            elif cfg.get("main_group_id"):
                c_list = nm.setdefault("enabled_chats", [])
                if cfg["main_group_id"] not in c_list:
                    c_list.append(cfg["main_group_id"])

            # Sincroniza estado inicial para evitar falso disparo
            try:
                from config import get_timezone
                tz = get_timezone(cfg)
                now_dt = datetime.now(tz)
            except Exception:
                from datetime import timezone, timedelta
                now_dt = datetime.now(timezone(timedelta(hours=-3)))
            nm["current_state"] = "night" if is_time_between(now_dt, nm["start"], nm["end"]) else "day"

            save_config(cfg)

            has_targets = bool(nm.get("enabled_chats") or cfg.get("main_group_id"))
            group_tip = "" if has_targets else "\n\n⚠️ *Aviso:* Nenhum grupo vinculado ainda! Envie `/setgrupo` dentro do grupo para receber os avisos lá."

            await safe_reply(
                update,
                f"🌙 *Modo Noturno Ativado!*\n\n"
                f"• Silêncio diário das *{nm['start']}* às *{nm['end']}*.\n"
                f"• Avisos de início e fim no grupo: *Ativados* 🔔{group_tip}",
                parse_mode=ParseMode.MARKDOWN
            )

        elif action in ("off", "desativar", "desligar"):
            nm["enabled"] = False
            save_config(cfg)
            await safe_reply(update, "☀️ *Modo Noturno Desativado!* O grupo agora aceita mensagens 24 horas por dia.", parse_mode=ParseMode.MARKDOWN)

        elif action in ("avisos", "aviso", "notificacao", "notificar"):
            sub = context.args[1].lower().strip() if len(context.args) > 1 else ""
            if sub in ("off", "desativar", "desligar", "0"):
                nm["announce_start"] = False
                nm["announce_end"] = False
                save_config(cfg)
                await safe_reply(update, "🔕 *Avisos de Início e Término do Modo Noturno Desativados!*", parse_mode=ParseMode.MARKDOWN)
            else:
                nm["announce_start"] = True
                nm["announce_end"] = True
                save_config(cfg)
                await safe_reply(update, "🔔 *Avisos de Início e Término do Modo Noturno Ativados!*", parse_mode=ParseMode.MARKDOWN)

        elif action in ("testestart", "startteste", "teststart"):
            s = nm.get("start", "23:00")
            e = nm.get("end", "07:00")
            txt = (
                "🌙 *Silêncio Noturno Iniciado!*\n\n"
                f"O Modo Noturno acabou de começar (das *{s}* às *{e}*).\n"
                "O envio de mensagens comuns foi temporariamente silenciado para mantermos o descanso e a tranquilidade de todos.\n\n"
                "Tenham uma excelente e abençoada noite! 😴🎹✨"
            )

            # Dispara para os grupos vinculados
            target_chats = set()
            main_id = cfg.get("main_group_id")
            if main_id and isinstance(main_id, int) and main_id < 0:
                target_chats.add(main_id)
            for cid in nm.get("enabled_chats", []):
                if cid and isinstance(cid, int) and cid < 0:
                    target_chats.add(cid)

            sent_cnt = 0
            for cid in target_chats:
                try:
                    await context.bot.send_message(chat_id=cid, text=txt, parse_mode=ParseMode.MARKDOWN)
                    sent_cnt += 1
                except Exception as ex:
                    logger.warning(f"Erro ao enviar testestart para {cid}: {ex}")

            if sent_cnt > 0:
                await msg.reply_text(f"✅ Aviso de início de Modo Noturno enviado com sucesso para {sent_cnt} grupo(s)!")
            else:
                await msg.reply_text(
                    f"📢 *Prévia do Aviso de Início:*\n\n{txt}\n\n"
                    "💡 *Dica:* Nenhum grupo está vinculado ainda. Envie `/setgrupo` dentro do grupo para que o bot envie os avisos lá!",
                    parse_mode=ParseMode.MARKDOWN
                )

        elif action in ("testeend", "endteste", "testend"):
            s = nm.get("start", "23:00")
            e = nm.get("end", "07:00")
            txt = (
                "☀️ *Bom Dia! Silêncio Noturno Encerrado!*\n\n"
                f"O horário de silêncio chegou ao fim (das *{s}* às *{e}*).\n"
                "O chat do grupo está oficialmente aberto para mensagens, novidades e partituras!\n\n"
                "Desejamos a todos um ótimo e produtivo dia! 🎼☕✨"
            )

            # Dispara para os grupos vinculados
            target_chats = set()
            main_id = cfg.get("main_group_id")
            if main_id and isinstance(main_id, int) and main_id < 0:
                target_chats.add(main_id)
            for cid in nm.get("enabled_chats", []):
                if cid and isinstance(cid, int) and cid < 0:
                    target_chats.add(cid)

            sent_cnt = 0
            for cid in target_chats:
                try:
                    await context.bot.send_message(chat_id=cid, text=txt, parse_mode=ParseMode.MARKDOWN)
                    sent_cnt += 1
                except Exception as ex:
                    logger.warning(f"Erro ao enviar testeend para {cid}: {ex}")

            if sent_cnt > 0:
                await msg.reply_text(f"✅ Aviso de término de Modo Noturno enviado com sucesso para {sent_cnt} grupo(s)!")
            else:
                await msg.reply_text(
                    f"📢 *Prévia do Aviso de Término:*\n\n{txt}\n\n"
                    "💡 *Dica:* Nenhum grupo está vinculado ainda. Envie `/setgrupo` dentro do grupo para que o bot envie os avisos lá!",
                    parse_mode=ParseMode.MARKDOWN
                )

        else:
            await msg.reply_text("Uso: `/noturno on`, `/noturno off` ou `/noturno avisos on/off`", parse_mode=ParseMode.MARKDOWN)

    async def check_night_mode(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
        """Verifica se o grupo está atualmente no horário de silêncio noturno e apaga mensagens de não-admins."""
        msg = update.effective_message
        user = update.effective_user
        chat = update.effective_chat

        if not msg or not user or not chat or chat.type == "private":
            return False

        # Admins podem falar a qualquer hora
        if await self.admin_cache.is_admin(chat, user.id):
            return False

        cfg = load_config()
        nm = cfg.get("night_mode", {})
        if not nm.get("enabled", False):
            return False

        try:
            from config import get_timezone
            tz = get_timezone(cfg)
            now_dt = datetime.now(tz)
        except Exception:
            from datetime import timezone, timedelta
            now_dt = datetime.now(timezone(timedelta(hours=-3)))

        start_str = nm.get("start", "23:00")
        end_str = nm.get("end", "07:00")

        if is_time_between(now_dt, start_str, end_str):
            await safe_delete_message(context.bot, chat.id, msg.message_id)
            user_mention = f"@{user.username}" if user.username else user.first_name
            warn_text = (
                f"🌙 Shhh... {user_mention}, o grupo está em *Modo Noturno* (Silêncio das {start_str} às {end_str}).\n"
                f"O chat reabre às *{end_str}* para mantermos o descanso de todos! 🎵"
            )
            try:
                sent = await chat.send_message(warn_text, parse_mode=ParseMode.MARKDOWN)
                schedule_message_deletion(context, chat.id, sent.message_id, 8)
            except Exception:
                pass
            return True

        return False


async def check_night_mode_transitions_job(context_or_bot):
    """
    Job recorrente em segundo plano (roda a cada 20-30 segundos):
    Monitora a virada do relógio e envia aviso no grupo quando o Modo Noturno inicia ou termina!
    """
    from telegram import Bot
    if isinstance(context_or_bot, Bot):
        bot = context_or_bot
    elif hasattr(context_or_bot, "application") and hasattr(context_or_bot.application, "bot"):
        bot = context_or_bot.application.bot
    elif hasattr(context_or_bot, "bot") and not isinstance(context_or_bot, Bot):
        bot = context_or_bot.bot
    else:
        bot = context_or_bot
    try:
        cfg = load_config()
        nm = cfg.get("night_mode", {})
        if not nm.get("enabled", False):
            return

        try:
            from config import get_timezone
            tz = get_timezone(cfg)
            now_dt = datetime.now(tz)
        except Exception:
            from datetime import timezone, timedelta
            now_dt = datetime.now(timezone(timedelta(hours=-3)))
        start_str = nm.get("start", "23:00")
        end_str = nm.get("end", "07:00")
        is_night_now = is_time_between(now_dt, start_str, end_str)

        current_state = nm.get("current_state")

        # Primeira execução após ligar o bot: apenas registra o estado para não disparar falso aviso
        if current_state is None:
            nm["current_state"] = "night" if is_night_now else "day"
            save_config(cfg)
            return

        # Lista de grupos destinatários dos avisos
        target_chats = set()
        main_id = cfg.get("main_group_id")
        if main_id and isinstance(main_id, int) and main_id < 0:
            target_chats.add(main_id)
        for cid in nm.get("enabled_chats", []):
            if cid and isinstance(cid, int) and cid < 0:
                target_chats.add(cid)
        for m in cfg.get("recurring_messages", []):
            c_id = m.get("chat_id")
            if c_id and isinstance(c_id, int) and c_id < 0:
                target_chats.add(c_id)

        # 1. TRANSIÇÃO DIA -> NOITE (Início do Modo Noturno)
        if is_night_now and current_state != "night":
            nm["current_state"] = "night"
            save_config(cfg)

            if nm.get("announce_start", True) and target_chats:
                txt = (
                    "🌙 *Silêncio Noturno Iniciado!*\n\n"
                    f"O Modo Noturno acabou de começar (das *{start_str}* às *{end_str}*).\n"
                    "O envio de mensagens foi temporariamente pausado para mantermos a tranquilidade e o descanso de todos.\n\n"
                    "Tenham uma excelente e abençoada noite! 😴🎹✨"
                )
                for cid in target_chats:
                    try:
                        await bot.send_message(
                            chat_id=cid,
                            text=txt,
                            parse_mode=ParseMode.MARKDOWN
                        )
                        logger.info(f"Aviso de início do Modo Noturno enviado ao chat {cid}")
                    except Exception as e:
                        logger.warning(f"Não foi possível enviar aviso de início do noturno para {cid}: {e}")

        # 2. TRANSIÇÃO NOITE -> DIA (Término do Modo Noturno)
        elif not is_night_now and current_state == "night":
            nm["current_state"] = "day"
            save_config(cfg)

            if nm.get("announce_end", True) and target_chats:
                txt = (
                    "☀️ *Bom Dia! Silêncio Noturno Encerrado!*\n\n"
                    f"O horário de silêncio chegou ao fim (das *{start_str}* às *{end_str}*).\n"
                    "O chat do grupo está oficialmente aberto para mensagens, novidades e partituras!\n\n"
                    "Desejamos a todos um ótimo e produtivo dia! 🎼☕✨"
                )
                for cid in target_chats:
                    try:
                        await bot.send_message(
                            chat_id=cid,
                            text=txt,
                            parse_mode=ParseMode.MARKDOWN
                        )
                        logger.info(f"Aviso de término do Modo Noturno enviado ao chat {cid}")
                    except Exception as e:
                        logger.warning(f"Não foi possível enviar aviso de término do noturno para {cid}: {e}")

    except Exception as ex:
        logger.error(f"Erro no job de transição do Modo Noturno: {ex}")
