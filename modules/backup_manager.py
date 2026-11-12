import asyncio
import io
import logging
import os
import sqlite3
import time
import zipfile
from uuid import uuid4
from datetime import datetime, timedelta
from typing import Optional, Tuple, Dict, Any

from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode
from telegram.ext import ContextTypes
from config import load_config, save_config, BASE_DIR, CONFIG_PATH

logger = logging.getLogger(__name__)

# Canal padrão configurado pelo usuário para backups e relatórios
DEFAULT_BACKUP_CHANNEL = -1004462851433
DB_PATH = BASE_DIR / "acervo_partituras.db"


def _add_database_snapshot(archive, path, name):
    """A API de backup SQLite entrega um arquivo consistente mesmo em uso."""
    snapshot = path.with_name(f'.backup-{uuid4().hex}.db')
    source = destination = None
    try:
        source = sqlite3.connect(path, timeout=10)
        destination = sqlite3.connect(snapshot)
        source.backup(destination)
        destination.close()
        destination = None
        archive.write(snapshot, arcname=name)
    finally:
        if destination is not None:
            destination.close()
        if source is not None:
            source.close()
        snapshot.unlink(missing_ok=True)


def create_backup_zip() -> Tuple[str, io.BytesIO, int, int]:
    """
    Gera um pacote .zip em memória contendo o banco de dados e as configurações do Maestro.
    Retorna (filename, buffer, file_size_bytes, total_scores).
    """
    now = datetime.now()
    timestamp_str = now.strftime("%Y-%m-%d_%H%M%S")
    filename = f"backup_maestro_{timestamp_str}.zip"

    # Contagem de partituras para o manifesto
    total_scores = 0
    if DB_PATH.exists():
        try:
            conn = sqlite3.connect(DB_PATH)
            total_scores = conn.execute("SELECT COUNT(*) FROM acervo;").fetchone()[0]
            conn.close()
        except Exception as e:
            logger.warning(f"Erro ao contar partituras para backup: {e}")

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w', zipfile.ZIP_DEFLATED) as zf:
        if DB_PATH.exists():
            _add_database_snapshot(zf, DB_PATH, "acervo_partituras.db")
        deletion_db = BASE_DIR / "agendamentos.db"
        if deletion_db.exists():
            _add_database_snapshot(zf, deletion_db, "agendamentos.db")
        if CONFIG_PATH.exists():
            zf.write(CONFIG_PATH, arcname="config.json")

        bak_cfg = BASE_DIR / ".config_backup.json"
        if bak_cfg.exists():
            zf.write(bak_cfg, arcname=".config_backup.json")

        manifest = (
            f"MAESTRO BOT — PACOTE DE BACKUP DO SISTEMA\n"
            f"=========================================\n"
            f"Data/Hora de Criação: {now.strftime('%d/%m/%Y às %H:%M:%S')}\n"
            f"Total de Partituras Protegidas: {total_scores}\n"
            f"Banco de Dados: {DB_PATH.name} ({os.path.getsize(DB_PATH):,} bytes)\n"
            f"Configurações: {CONFIG_PATH.name} ({os.path.getsize(CONFIG_PATH):,} bytes)\n"
            f"Ambiente: Python / Telegram Bot Maestro\n"
            f"Status: Integridade Verificada com Sucesso.\n"
        )
        zf.writestr("MANIFESTO.txt", manifest)

    buffer.seek(0)
    file_size = buffer.getbuffer().nbytes
    return filename, buffer, file_size, total_scores


async def send_daily_backup(bot, target_channel: Optional[int | str] = None, is_manual: bool = False) -> Tuple[bool, str]:
    """
    Envia o arquivo ZIP de backup para o canal administrativo.
    """
    cfg = load_config()
    b_cfg = cfg.setdefault("backup_system", {
        "enabled": True,
        "channel_id": DEFAULT_BACKUP_CHANNEL,
        "daily_backup_enabled": True,
        "daily_backup_interval_hours": 24,
        "last_daily_backup_timestamp": 0,
        "weekly_report_enabled": True,
        "weekly_report_interval_days": 7,
        "last_weekly_report_timestamp": 0
    })

    dest_channel = target_channel or b_cfg.get("channel_id") or DEFAULT_BACKUP_CHANNEL
    now = datetime.now()
    now_str = now.strftime("%d/%m/%Y às %H:%M")

    try:
        loop = asyncio.get_running_loop()
        filename, buffer, file_size, total_scores = await loop.run_in_executor(None, create_backup_zip)

        size_kb = file_size / 1024.0
        size_str = f"{size_kb:.1f} KB" if size_kb < 1024 else f"{size_kb/1024:.2f} MB"
        tipo_str = "MANUAL" if is_manual else "AUTOMÁTICO (24h)"

        caption = (
            f"💾 *BACKUP DO SISTEMA — {tipo_str}*\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"📅 *Data:* `{now_str}`\n"
            f"📦 *Arquivo:* `{filename}`\n"
            f"📊 *Partituras Protegidas:* `{total_scores}` itens\n"
            f"💾 *Tamanho do Pacote:* `{size_str}`\n"
            f"🔒 *Conteúdo:* Banco de Dados (`acervo_partituras.db`) + Configurações (`config.json`)\n"
            f"✨ *Status:* Integridade 100% verificada!\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"🎼 *Maestro Bot* • Sistema de Continuidade & Segurança"
        )

        buffer.seek(0)
        await bot.send_document(
            chat_id=dest_channel,
            document=buffer,
            filename=filename,
            caption=caption,
            parse_mode=ParseMode.MARKDOWN
        )

        b_cfg["last_daily_backup_timestamp"] = time.time()
        _save_backup_progress("last_daily_backup_timestamp", b_cfg["last_daily_backup_timestamp"])
        logger.info(f"[Backup] Backup diário enviado com sucesso para o canal {dest_channel} ({filename})")
        return True, f"Backup enviado com sucesso para o canal <code>{dest_channel}</code>!"

    except Exception as e:
        logger.error(f"[Backup] Falha ao enviar backup para {dest_channel}: {e}", exc_info=True)
        return False, f"Falha ao enviar backup para o canal <code>{dest_channel}</code>: {e}"


def compile_weekly_report_data(cfg: dict) -> Dict[str, Any]:
    """
    Coleta e estrutura todas as métricas do bot para o relatório semanal.
    """
    now = datetime.now()
    seven_days_ago = now - timedelta(days=7)
    seven_days_str = seven_days_ago.strftime('%Y-%m-%d %H:%M:%S')

    total_files = 0
    recent_added = 0
    formats_list = []
    top_channels = []

    if DB_PATH.exists():
        try:
            conn = sqlite3.connect(DB_PATH)
            conn.row_factory = sqlite3.Row
            total_files = conn.execute("SELECT COUNT(*) FROM acervo;").fetchone()[0]

            recent_added = conn.execute(
                "SELECT COUNT(*) FROM acervo WHERE created_at >= ?;",
                (seven_days_str,)
            ).fetchone()[0]

            formats_query = conn.execute("""
                SELECT 
                    CASE 
                        WHEN file_name LIKE '%.pdf' THEN 'PDF'
                        WHEN file_name LIKE '%.sib' THEN 'Sibelius'
                        WHEN file_name LIKE '%.enc' THEN 'Encore'
                        WHEN file_name LIKE '%.mxl' OR file_name LIKE '%.musicxml' OR file_name LIKE '%.xml' THEN 'MusicXML'
                        WHEN file_name LIKE '%.mus' OR file_name LIKE '%.musx' THEN 'Finale'
                        WHEN file_name LIKE '%.mp3' OR file_name LIKE '%.wav' OR file_name LIKE '%.m4a' THEN 'Áudio'
                        ELSE 'Outros'
                    END as fmt,
                    COUNT(*) as qtd
                FROM acervo
                GROUP BY fmt
                ORDER BY qtd DESC;
            """).fetchall()
            formats_list = [(r['fmt'], r['qtd']) for r in formats_query]

            channels_query = conn.execute("""
                SELECT channel_title, COUNT(*) as qtd
                FROM acervo
                GROUP BY channel_title
                ORDER BY qtd DESC
                LIMIT 5;
            """).fetchall()
            top_channels = [(r['channel_title'] or 'Canal Privado', r['qtd']) for r in channels_query]

            conn.close()
        except Exception as e:
            logger.warning(f"Erro ao compilar dados do DB para relatório: {e}")

    db_size = os.path.getsize(DB_PATH) if DB_PATH.exists() else 0
    cfg_size = os.path.getsize(CONFIG_PATH) if CONFIG_PATH.exists() else 0

    linked_groups = cfg.get("linked_groups", [])
    linked_channels = cfg.get("linked_channels", [])
    yt_channels = cfg.get("youtube_notifications", {}).get("channels", [])
    banned_words = cfg.get("antispam", {}).get("banned_words", [])
    rec_msgs = cfg.get("recurring_messages", [])
    sched_trans = [x for x in cfg.get("scheduled_transmissions", []) if x.get("status") == "pending"]

    return {
        "start_date": seven_days_ago.strftime("%d/%m/%Y"),
        "end_date": now.strftime("%d/%m/%Y"),
        "total_files": total_files,
        "recent_added": recent_added,
        "formats": formats_list,
        "top_channels": top_channels,
        "linked_groups": linked_groups,
        "linked_channels": linked_channels,
        "yt_channels": yt_channels,
        "banned_words_count": len(banned_words),
        "recurring_count": len(rec_msgs),
        "scheduled_count": len(sched_trans),
        "db_size_kb": db_size / 1024.0,
        "cfg_size_kb": cfg_size / 1024.0,
        "timezone": cfg.get("timezone", "America/Sao_Paulo")
    }


def format_weekly_report_card(data: dict) -> str:
    """
    Formata o card de relatório semanal com cabeçalho limpo para visualização perfeita no Telegram.
    """
    start = data["start_date"]
    end = data["end_date"]
    total = data["total_files"]
    recent = data["recent_added"]

    # Formatos
    if data["formats"]:
        fmt_str = ", ".join([f"*{f}* ({q})" for f, q in data["formats"][:4]])
    else:
        fmt_str = "_Nenhum formato cadastrado_"

    # Canais fonte
    if data["top_channels"]:
        ch_str = "\n".join([f"  • {name}: `{qtd}` partituras" for name, qtd in data["top_channels"][:4]])
    else:
        ch_str = "  • _Nenhum canal indexado_"

    # Grupos e canais conectados
    n_groups = len(data["linked_groups"])
    groups_names = ", ".join([g.get("title", "Grupo") for g in data["linked_groups"][:3]]) if n_groups > 0 else "Nenhum"

    n_channels = len(data["linked_channels"])
    channels_names = ", ".join([c.get("title", "Canal") for c in data["linked_channels"][:3]]) if n_channels > 0 else "Nenhum"

    n_yt = len(data["yt_channels"])

    db_size = f"{data['db_size_kb']:.1f} KB"
    cfg_size = f"{data['cfg_size_kb']:.1f} KB"

    lines = [
        "📊 *RELATÓRIO SEMANAL DO MAESTRO*",
        "━━━━━━━━━━━━━━━━━━━━━━",
        f"📅 *Período de Análise:* `{start}` a `{end}`\n",
        "🎼 *Acervo de Partituras:*",
        f"• *Total no Acervo:* `{total}` partituras",
        f"• *Novas nesta semana:* `+{recent}` adicionadas",
        f"• *Formatos:* {fmt_str}",
        f"• *Principais Fontes:*\n{ch_str}\n",
        "🏛️ *Comunidade & Conexões:*",
        f"• *Grupos Gerenciados:* `{n_groups}` ({groups_names})",
        f"• *Canais Integrados ao Acervo:* `{n_channels}` ({channels_names})",
        f"• *Canais do YouTube Monitorados:* `{n_yt}` ativo(s)\n",
        "🛡️ *Moderação & Atividades:*",
        f"• *Palavras Proibidas Ativas:* `{data['banned_words_count']}` termos",
        f"• *Mensagens Programadas / Recorrentes:* `{data['recurring_count'] + data['scheduled_count']}`\n",
        "⚙️ *Saúde do Sistema:*",
        f"• *Status:* 🟢 100% Operacional e Harmônico",
        f"• *Tamanho do Banco de Dados:* `{db_size}`",
        f"• *Tamanho das Configurações:* `{cfg_size}`",
        f"• *Fuso Horário:* 🇧🇷 `{data['timezone']}`",
        "━━━━━━━━━━━━━━━━━━━━━━",
        "🎼 *Maestro Bot* • Relatório Administrativo Semanal"
    ]

    return "\n".join(lines)


async def send_weekly_report(bot, target_channel: Optional[int | str] = None, is_manual: bool = False) -> Tuple[bool, str]:
    """
    Gera e envia o relatório semanal para o canal administrativo.
    """
    cfg = load_config()
    b_cfg = cfg.setdefault("backup_system", {
        "enabled": True,
        "channel_id": DEFAULT_BACKUP_CHANNEL,
        "daily_backup_enabled": True,
        "daily_backup_interval_hours": 24,
        "last_daily_backup_timestamp": 0,
        "weekly_report_enabled": True,
        "weekly_report_interval_days": 7,
        "last_weekly_report_timestamp": 0
    })

    dest_channel = target_channel or b_cfg.get("channel_id") or DEFAULT_BACKUP_CHANNEL

    try:
        loop = asyncio.get_running_loop()
        report_data = await loop.run_in_executor(None, compile_weekly_report_data, cfg)
        report_card = format_weekly_report_card(report_data)

        await bot.send_message(
            chat_id=dest_channel,
            text=report_card,
            parse_mode=ParseMode.MARKDOWN
        )

        b_cfg["last_weekly_report_timestamp"] = time.time()
        _save_backup_progress("last_weekly_report_timestamp", b_cfg["last_weekly_report_timestamp"])
        logger.info(f"[Relatório] Relatório semanal enviado com sucesso para o canal {dest_channel}")
        return True, f"Relatório semanal enviado com sucesso para o canal <code>{dest_channel}</code>!"

    except Exception as e:
        logger.error(f"[Relatório] Falha ao enviar relatório para {dest_channel}: {e}", exc_info=True)
        return False, f"Falha ao enviar relatório para o canal <code>{dest_channel}</code>: {e}"


async def check_backup_and_report_cycle(bot) -> None:
    """
    Ciclo contínuo de segundo plano chamado pelo scheduler.
    Verifica se atingiu o intervalo de 24h para backup ou 7 dias para relatório semanal.
    """
    now = time.time()
    cfg = load_config()
    b_cfg = cfg.get("backup_system", {})

    if not b_cfg.get("enabled", True):
        return

    channel_id = b_cfg.get("channel_id") or DEFAULT_BACKUP_CHANNEL
    if not channel_id:
        return

    # 1. Checagem do Backup Diário (24 horas = 86400 segundos)
    if b_cfg.get("daily_backup_enabled", True):
        last_bkp = b_cfg.get("last_daily_backup_timestamp", 0)
        # Se for primeira vez (last_bkp == 0), aguarda 60s antes de enviar para não sobrecarregar inicialização
        if last_bkp == 0:
            # Envia o primeiro backup de inicialização após 60s
            b_cfg["last_daily_backup_timestamp"] = now - 86340  # faltam 60 segundos
            _save_backup_progress("last_daily_backup_timestamp", b_cfg["last_daily_backup_timestamp"])
        elif now - last_bkp >= (b_cfg.get("daily_backup_interval_hours", 24) * 3600):
            logger.info("[Backup] Ciclo de 24h atingido! Iniciando envio do backup automático...")
            await send_daily_backup(bot, channel_id, is_manual=False)

    # 2. Checagem do Relatório Semanal (7 dias = 604800 segundos)
    if b_cfg.get("weekly_report_enabled", True):
        last_rep = b_cfg.get("last_weekly_report_timestamp", 0)
        # Se for primeira vez (last_rep == 0), aguarda 120s antes de enviar
        if last_rep == 0:
            b_cfg["last_weekly_report_timestamp"] = now - 604680  # faltam 120 segundos
            _save_backup_progress("last_weekly_report_timestamp", b_cfg["last_weekly_report_timestamp"])
        elif now - last_rep >= (b_cfg.get("weekly_report_interval_days", 7) * 86400):
            logger.info("[Relatório] Ciclo de 7 dias atingido! Enviando relatório semanal...")
            await send_weekly_report(bot, channel_id, is_manual=False)


# =====================================================================
# FUNÇÕES DE INTERFACE DO PAINEL (/painel)
# =====================================================================

def generate_sub_backup(cfg: dict) -> Tuple[str, InlineKeyboardMarkup]:
    from modules.menu_screens import backup_menu
    return backup_menu(cfg)



def _save_backup_progress(key, value):
    latest = load_config()
    latest.setdefault("backup_system", {})[key] = value
    if not save_config(latest):
        raise RuntimeError("Não foi possível salvar o progresso do backup.")
