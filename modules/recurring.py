import time
import asyncio
import logging
import zoneinfo
from datetime import datetime
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, LinkPreviewOptions
from telegram.constants import ParseMode
from config import load_config, save_config
from modules.utils import schedule_message_deletion, build_rich_buttons_markup, smart_send_message, smart_send_photo

logger = logging.getLogger("RecurringMessages")

WEEKDAY_NAMES = ["Seg", "Ter", "Qua", "Qui", "Sex", "Sáb", "Dom"]
INTERVAL_HOURS = [1, 2, 3, 4, 6, 8, 12, 24]
INTERVAL_MINUTES = [1, 2, 3, 5, 10, 15, 20, 30]

# Contador de mensagens por grupo em tempo de execução
GROUP_MESSAGE_COUNTS = {}

def format_interval(minutes: int) -> str:
    """Compatibilidade reversa para formatação de minutos."""
    if minutes < 60:
        return f"{minutes} min"
    hours = minutes // 60
    if hours == 1:
        return "1 hora"
    elif hours == 24:
        return "24 horas (1 dia)"
    return f"{hours} horas"

def format_interval_display(msg_data: dict) -> str:
    """Retorna texto amigável do intervalo (ex: 'A cada 24 horas', 'A cada 50 mensagens')."""
    mode = msg_data.get("repeat_mode", "interval")
    if mode == "messages":
        cnt = msg_data.get("messages_interval", 50)
        return f"A cada {cnt} mensagens"

    itype = msg_data.get("interval_type", "hours")
    ival = msg_data.get("interval_value")
    if ival is None:
        im = msg_data.get("interval_minutes", 1440)
        if im < 60:
            return f"A cada {im} minutos"
        h = im // 60
        return f"A cada {h} hora{'s' if h > 1 else ''}"

    if itype == "hours":
        return f"A cada {ival} hora{'s' if ival > 1 else ''}"
    else:
        return f"A cada {ival} minuto{'s' if ival > 1 else ''}"

def format_cronograma_display(msg_data: dict) -> str:
    """Retorna texto do cronograma (ex: '11:37' ou 'Não definido')."""
    h = msg_data.get("start_hour")
    m = msg_data.get("start_minute")
    if h is not None and m is not None:
        return f"{h:02d}:{m:02d}"
    return "Não definido"

def format_weekdays_display(msg_data: dict) -> str:
    wd = msg_data.get("weekdays")
    if wd is None or len(wd) == 7:
        return "Todos os dias"
    if not wd:
        return "Nenhum dia"
    return ", ".join([WEEKDAY_NAMES[i] for i in sorted(wd) if 0 <= i < 7])

def format_month_days_display(msg_data: dict) -> str:
    md = msg_data.get("month_days")
    if not md or len(md) >= 31:
        return "Todos os dias"
    return ", ".join(map(str, sorted(md)))

def format_autodel_display(seconds: int) -> str:
    if not seconds or seconds <= 0:
        return "❌"
    if seconds < 60:
        return f"{seconds}s"
    if seconds < 3600:
        return f"{seconds // 60} min"
    h = seconds // 3600
    return f"{h} hora{'s' if h > 1 else ''}"

def build_buttons_markup(buttons_data):
    return build_rich_buttons_markup(buttons_data)

async def send_single_recurring_message(bot, msg_data: dict, chat_id: int, job_queue=None) -> int:
    """Envia uma mensagem recorrente com foto, texto e botões, gerenciando deleção anterior e fixação."""
    from telegram import Bot
    if not isinstance(bot, Bot):
        if hasattr(bot, "application") and hasattr(bot.application, "bot"):
            bot = bot.application.bot
        elif hasattr(bot, "bot") and not isinstance(bot, Bot):
            bot = bot.bot
    text = msg_data.get("text", "")
    photo = msg_data.get("photo")
    buttons = msg_data.get("buttons", [])
    markup = build_rich_buttons_markup(buttons)
    pin = msg_data.get("pin_message", False)
    delete_prev = msg_data.get("delete_previous", False)
    last_msg_id = msg_data.get("last_message_id")
    auto_del = msg_data.get("auto_delete_seconds", 0)
    topic_id = msg_data.get("message_thread_id")
    article_url = msg_data.get("article_url")

    extra_kwargs = {}
    if topic_id:
        extra_kwargs["message_thread_id"] = topic_id

    # Suporte a artigo (link preview) no topo
    if not photo:
        if article_url:
            extra_kwargs["link_preview_options"] = LinkPreviewOptions(url=article_url, show_above_text=True, is_disabled=False)
        else:
            extra_kwargs["link_preview_options"] = LinkPreviewOptions(show_above_text=True)

    # 1. Apaga a mensagem anterior se configurado
    if delete_prev and last_msg_id:
        try:
            await bot.delete_message(chat_id=chat_id, message_id=last_msg_id)
        except Exception as e:
            logger.debug(f"Não foi possível apagar mensagem anterior {last_msg_id}: {e}")

    # 2. Envia a nova mensagem (suportando mensagens copiadas idênticas, artigos expansíveis <blockquote expandable>, spoilers e botões em grade)
    sent_msg = None
    source_chat_id = msg_data.get("source_chat_id")
    source_message_id = msg_data.get("source_message_id")
    backup_chat_id = msg_data.get("backup_chat_id")
    backup_message_id = msg_data.get("backup_message_id")

    # Define copy_kwargs SEM link_preview_options (pois copy_message não aceita link_preview_options!)
    copy_kwargs = {}
    if topic_id:
        copy_kwargs["message_thread_id"] = topic_id

    # Se a mensagem foi encaminhada/clonada de outra postagem (mantém layout, artigos expansíveis e botões originais idênticos)
    # Só clona se a fonte for um canal ou supergrupo real (ID negativo), nunca de chat privado de admin
    if source_chat_id and source_message_id and isinstance(source_chat_id, int) and source_chat_id < 0:
        try:
            # 1ª tentativa: cópia 100% nativa (preserva blocos expansíveis e todas as linhas de botões originais do Telegram)
            sent_msg = await bot.copy_message(
                chat_id=chat_id,
                from_chat_id=source_chat_id,
                message_id=source_message_id,
                **copy_kwargs
            )
            logger.info(f"Mensagem clonada com sucesso da fonte #{source_message_id} ({source_chat_id}) para {chat_id}")
        except Exception as e_copy:
            logger.warning(f"Falha ao copiar mensagem fonte #{source_message_id} de {source_chat_id}: {e_copy}. Tentando com markup...")
            if markup:
                try:
                    kwargs_with_markup = dict(copy_kwargs)
                    kwargs_with_markup["reply_markup"] = markup
                    sent_msg = await bot.copy_message(
                        chat_id=chat_id,
                        from_chat_id=source_chat_id,
                        message_id=source_message_id,
                        **kwargs_with_markup
                    )
                except Exception as e_copy2:
                    logger.warning(f"Falha ao copiar com markup da fonte #{source_message_id}: {e_copy2}")

    if not sent_msg and backup_chat_id and backup_message_id and isinstance(backup_chat_id, int) and backup_chat_id < 0:
        bak_kwargs = dict(copy_kwargs)
        if markup:
            bak_kwargs["reply_markup"] = markup
        try:
            sent_msg = await bot.copy_message(
                chat_id=chat_id,
                from_chat_id=backup_chat_id,
                message_id=backup_message_id,
                **bak_kwargs
            )
            logger.info(f"Mensagem clonada com sucesso do backup #{backup_message_id} ({backup_chat_id}) para {chat_id}")
        except Exception as e_bak:
            logger.warning(f"Falha ao copiar mensagem de backup #{backup_message_id}: {e_bak}")

    if not sent_msg:
        if photo:
            sent_msg = await smart_send_photo(
                bot=bot,
                chat_id=chat_id,
                photo=photo,
                caption=text,
                reply_markup=markup,
                message_thread_id=topic_id
            )
        else:
            sent_msg = await smart_send_message(
                bot=bot,
                chat_id=chat_id,
                text=text,
                reply_markup=markup,
                link_preview_options=extra_kwargs.get("link_preview_options"),
                message_thread_id=topic_id
            )

    # 3. Fixa a mensagem se configurado
    if sent_msg and pin:
        try:
            await bot.pin_chat_message(
                chat_id=chat_id,
                message_id=sent_msg.message_id,
                disable_notification=True
            )
            cfg = load_config()
            if cfg.get("delete_pinned_service_messages", True):
                from modules.utils import safe_delete_message
                try:
                    await safe_delete_message(bot, chat_id, sent_msg.message_id + 1)
                except Exception:
                    pass
        except Exception as e:
            logger.warning(f"Não foi possível fixar mensagem {sent_msg.message_id}: {e}")

    # 4. Exclusão Cronometrada (se configurado)
    if sent_msg and auto_del > 0 and job_queue:
        try:
            schedule_message_deletion(job_queue, chat_id, sent_msg.message_id, auto_del)
        except Exception as e_del:
            logger.warning(f"Falha ao agendar auto-exclusão da mensagem {sent_msg.message_id}: {e_del}")

    return sent_msg.message_id if sent_msg else None


async def check_message_count_triggers(bot, chat_id: int, job_queue=None):
    """Incrementa o contador de mensagens do grupo e dispara mensagens repetidas baseadas em quantidade de mensagens."""
    GROUP_MESSAGE_COUNTS[chat_id] = GROUP_MESSAGE_COUNTS.get(chat_id, 0) + 1
    cur_count = GROUP_MESSAGE_COUNTS[chat_id]

    cfg = load_config()
    messages = cfg.get("recurring_messages", [])
    if not messages:
        return

    main_group_id = cfg.get("main_group_id")
    now = time.time()
    updated = False

    try:
        from config import get_timezone
        tz = get_timezone(cfg)
        now_dt = datetime.now(tz)
    except Exception:
        from datetime import timezone, timedelta
        now_dt = datetime.now(timezone(timedelta(hours=-3)))

    for m in messages:
        if not m.get("enabled", True):
            continue
        if m.get("repeat_mode") != "messages":
            continue

        target = m.get("chat_id")
        matches = (target == chat_id) or (target in ("all", "all_groups")) or (not target and chat_id == main_group_id)
        if not matches:
            continue

        # Checa dias da semana
        wd = m.get("weekdays")
        if wd is not None and len(wd) > 0 and now_dt.weekday() not in wd:
            continue

        # Checa dias do mês
        md = m.get("month_days")
        if md is not None and len(md) > 0 and now_dt.day not in md:
            continue

        interval = m.get("messages_interval", 50)
        last_count = m.get("messages_counter_last", 0)

        if (cur_count - last_count) >= interval:
            logger.info(f"Disparando mensagem repetida por contagem #{m.get('id')} no chat {chat_id} (após {cur_count - last_count} msgs)")
            try:
                new_msg_id = await send_single_recurring_message(bot, m, chat_id, job_queue=job_queue)
                if new_msg_id:
                    m["last_message_id"] = new_msg_id
                    m["last_sent_timestamp"] = now
                    m["messages_counter_last"] = cur_count
                    updated = True
            except Exception as e:
                logger.error(f"Erro ao disparar mensagem por contagem #{m.get('id')}: {e}")

    if updated:
        save_config(cfg)


async def process_recurring_messages_job(context_or_bot, job_queue=None):
    """Executado periodicamente a cada 20-30s para disparar mensagens no tempo correto."""
    from telegram import Bot
    if isinstance(context_or_bot, Bot):
        bot = context_or_bot
        jq = job_queue
    elif hasattr(context_or_bot, "application") and hasattr(context_or_bot.application, "bot"):
        bot = context_or_bot.application.bot
        jq = getattr(context_or_bot, "job_queue", job_queue)
    elif hasattr(context_or_bot, "bot") and not isinstance(context_or_bot, Bot):
        bot = context_or_bot.bot
        jq = getattr(context_or_bot, "job_queue", job_queue)
    else:
        bot = context_or_bot
        jq = job_queue

    cfg = load_config()
    messages = cfg.get("recurring_messages", [])
    if not messages:
        return

    main_group_id = cfg.get("main_group_id")
    now = time.time()
    updated = False

    try:
        from config import get_timezone
        tz = get_timezone(cfg)
        now_dt = datetime.now(tz)
    except Exception:
        from datetime import timezone, timedelta
        now_dt = datetime.now(timezone(timedelta(hours=-3)))
    today_str = now_dt.strftime("%Y-%m-%d")

    for m in messages:
        if not m.get("enabled", True):
            continue

        # Se for configurado por contagem de mensagens, é processado em tempo real por check_message_count_triggers
        if m.get("repeat_mode") == "messages":
            continue

        raw_target = m.get("chat_id")
        target_chats = []
        if raw_target == "all":
            for g in cfg.get("linked_groups", []):
                target_chats.append(g["id"])
            for c in cfg.get("linked_channels", []):
                target_chats.append(c["id"])
            if not target_chats and main_group_id:
                target_chats.append(main_group_id)
        elif raw_target == "all_groups":
            for g in cfg.get("linked_groups", []):
                target_chats.append(g["id"])
            if not target_chats and main_group_id:
                target_chats.append(main_group_id)
        elif raw_target == "all_channels":
            for c in cfg.get("linked_channels", []):
                target_chats.append(c["id"])
            if not target_chats and cfg.get("main_channel_id"):
                target_chats.append(cfg["main_channel_id"])
        elif isinstance(raw_target, int) and raw_target < 0:
            target_chats = [raw_target]
        elif isinstance(raw_target, str) and (raw_target.startswith("-") or raw_target.startswith("@")):
            target_chats = [raw_target]
        elif (not raw_target or (isinstance(raw_target, int) and raw_target > 0)) and main_group_id:
            target_chats = [main_group_id]
        elif main_group_id:
            target_chats = [main_group_id]
        elif cfg.get("main_channel_id"):
            target_chats = [cfg["main_channel_id"]]

        if not target_chats:
            continue

        # Checa datas limites (início e final)
        if m.get("start_date") and today_str < m["start_date"]:
            continue
        if m.get("end_date") and today_str > m["end_date"]:
            continue

        # Checa dias da semana
        wd = m.get("weekdays")
        if wd is not None and len(wd) > 0 and now_dt.weekday() not in wd:
            continue

        # Checa dias do mês
        md = m.get("month_days")
        if md is not None and len(md) > 0 and now_dt.day not in md:
            continue

        interval_minutes = m.get("interval_minutes", 1440)
        interval_seconds = interval_minutes * 60
        last_sent = m.get("last_sent_timestamp", 0)

        start_h = m.get("start_hour")
        start_m = m.get("start_minute")

        should_fire = False

        if start_h is not None and start_m is not None:
            # Horário de início fixado (ex: 20:55)
            slot_key = f"{today_str}_{start_h:02d}:{start_m:02d}"
            if interval_minutes >= 1440:
                # Intervalo diário (24h) ou maior: dispara quando bater a hora e minuto exatos!
                if now_dt.hour == start_h and now_dt.minute == start_m:
                    if m.get("last_fired_slot") != slot_key:
                        should_fire = True
            else:
                # Intervalo intra-diário (ex: a cada 2h a partir do horário de início)
                now_mins = now_dt.hour * 60 + now_dt.minute
                start_mins = start_h * 60 + start_m
                diff_mins = now_mins - start_mins
                cur_slot_key = f"{today_str}_{now_dt.hour:02d}:{now_dt.minute:02d}"
                if diff_mins >= 0 and (diff_mins % interval_minutes == 0) and (now_dt.minute == (start_m + (diff_mins % 60)) % 60):
                    if m.get("last_fired_slot") != cur_slot_key:
                        should_fire = True
                elif (now - last_sent) >= interval_seconds:
                    should_fire = True
        else:
            # Sem horário fixado: dispara estritamente por intervalo corrido
            if (now - last_sent) >= interval_seconds:
                should_fire = True

        if should_fire:
            last_id = None
            for dest_id in target_chats:
                logger.info(f"Disparando mensagem recorrente #{m.get('id')} no chat {dest_id}")
                print(f"🚀 [AGENDADOR] Disparando mensagem recorrente #{m.get('id')} para chat {dest_id} (Horário: {now_dt.strftime('%H:%M:%S')})")
                try:
                    new_msg_id = await send_single_recurring_message(bot, m, dest_id, job_queue=jq)
                    if new_msg_id:
                        last_id = new_msg_id
                        print(f"✅ [AGENDADOR] Mensagem #{m.get('id')} enviada com sucesso no chat {dest_id}! ID: {new_msg_id}")
                except Exception as e:
                    err_str = str(e).lower()
                    if "chat not found" in err_str:
                        logger.warning(f"Chat {dest_id} não encontrado para mensagem #{m.get('id')}.")
                        print(f"⚠️ [AGENDADOR] Chat {dest_id} não encontrado! Verifique se o bot ainda está nele.")
                    else:
                        logger.error(f"Erro ao disparar mensagem recorrente #{m.get('id')} no chat {dest_id}: {e}", exc_info=True)
                        print(f"❌ [AGENDADOR] Erro no chat {dest_id}: {e}")

            if last_id:
                m["last_message_id"] = last_id
                m["last_sent_timestamp"] = now
                if start_h is not None and start_m is not None:
                    if interval_minutes >= 1440:
                        m["last_fired_slot"] = f"{today_str}_{start_h:02d}:{start_m:02d}"
                    else:
                        m["last_fired_slot"] = f"{today_str}_{now_dt.hour:02d}:{now_dt.minute:02d}"
                updated = True

    if updated:
        save_config(cfg)


async def process_scheduled_transmissions_job(bot):
    """Verifica e dispara transmissões programadas pelo assistente (/comunicado) que atingiram o horário."""
    cfg = load_config()
    sched_list = cfg.get("scheduled_transmissions", [])
    if not sched_list:
        return

    now_ts = time.time()
    updated = False

    for item in sched_list:
        if item.get("status") != "pending":
            continue

        target_ts = item.get("schedule_timestamp", 0)
        if now_ts >= target_ts:
            item["status"] = "sending"
            updated = True
            asyncio.create_task(_execute_scheduled_transmission(bot, item))

    if updated:
        save_config(cfg)


async def _execute_scheduled_transmission(bot, item: dict):
    """Executa a transmissão agendada com distribuição gradual e suave entre canais/grupos."""
    from config import load_config, save_config
    from modules.panel import get_wizard_targets_list, get_wizard_dest_label
    from modules.utils import build_rich_buttons_markup, smart_send_message, smart_send_photo, smart_send_video
    from modules.logger_channel import send_mod_log
    import telegram.error
    import html

    cfg = load_config()
    target = item.get("target", "main_channel")
    text = item.get("text", "")
    media_type = item.get("media_type")
    media_id = item.get("media_id")
    buttons = item.get("buttons", [])
    pin = item.get("pin", False)
    delay_sec = item.get("delay_seconds", 2)
    creator_id = item.get("creator_id")
    dest_label = get_wizard_dest_label(target, cfg)

    targets = get_wizard_targets_list(target, cfg)
    markup = build_rich_buttons_markup(buttons)

    sent_count = 0
    fail_count = 0
    errors = []

    logger.info(f"Iniciando transmissão agendada #{item.get('id')} para {len(targets)} chat(s) com delay de {delay_sec}s")
    print(f"🚀 [TRANSMISSÃO AGENDADA] Disparando para {len(targets)} chat(s) com distribuição suave de {delay_sec}s/chat...")

    for i, cid in enumerate(targets):
        if i > 0 and delay_sec > 0:
            await asyncio.sleep(delay_sec)

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
                if pin and hasattr(sent_msg, "pin"):
                    try:
                        await sent_msg.pin(disable_notification=False)
                    except Exception as e_pin:
                        logger.debug(f"Não foi possível fixar no chat {cid}: {e_pin}")
        except telegram.error.RetryAfter as e_retry:
            logger.warning(f"FloodWait de {e_retry.retry_after}s recebido no chat {cid}. Aguardando...")
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
                    if pin and hasattr(sent_msg, "pin"):
                        try:
                            await sent_msg.pin(disable_notification=False)
                        except Exception:
                            pass
            except Exception as e_fail:
                fail_count += 1
                errors.append(f"Chat {cid}: {e_fail}")
        except Exception as e_send:
            fail_count += 1
            errors.append(f"Chat {cid}: {e_send}")
            logger.error(f"Erro ao transmitir para chat {cid}: {e_send}")

    # Atualiza registro no config
    cfg = load_config()
    for entry in cfg.get("scheduled_transmissions", []):
        if entry.get("id") == item.get("id"):
            entry["status"] = "completed"
            entry["sent_at"] = time.time()
            entry["sent_count"] = sent_count
            entry["fail_count"] = fail_count
            break
    save_config(cfg)

    # Notifica o criador (Admin)
    media_label = "🎥 Vídeo" if media_type == "video" else ("🖼️ Foto" if media_type == "photo" else "⚪ Texto")
    report = (
        "🎉 *TRANSMISSÃO AGENDADA CONCLUÍDA COM SUCESSO!*\n"
        "🎼 ══════════════════════ 🎼\n\n"
        f"• *Destino:* `{dest_label}`\n"
        f"• *Sucesso:* `{sent_count}` chat(s)\n"
        f"• *Falhas:* `{fail_count}`\n"
        f"• *Distribuição:* `{delay_sec}s entre cada chat (Envio Suave 🌊)`\n"
        f"• *Fixado no Topo:* `{'Sim 📌' if pin else 'Não'}`\n"
        f"• *Mídia:* `{media_label}`\n\n"
        "✅ Todos os envios foram processados e distribuídos com sucesso!"
    )
    if errors:
        report += f"\n\n⚠️ *Falhas registradas:*\n" + "\n".join(errors[:3])

    if creator_id:
        try:
            await bot.send_message(chat_id=creator_id, text=report, parse_mode=ParseMode.MARKDOWN)
        except Exception:
            try:
                await bot.send_message(chat_id=creator_id, text=report)
            except Exception:
                pass

    # Log de Auditoria
    await send_mod_log(
        bot=bot,
        event_type="say",
        title="Transmissão Agendada Concluída",
        user_info=f"Destino: <b>{html.escape(dest_label)}</b> ({sent_count} chats)",
        admin_info=f"Criador ID: <code>{creator_id}</code>",
        details=f"Horário: {item.get('schedule_display', '')} | Delay: {delay_sec}s/chat"
    )

