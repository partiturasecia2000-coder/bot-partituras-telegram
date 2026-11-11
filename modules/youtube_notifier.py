import asyncio
import logging
import re
import json
import time
import urllib.request
from typing import Optional, Tuple, List, Dict, Any
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes
from telegram.constants import ParseMode
from config import load_config, save_config

logger = logging.getLogger(__name__)

# Cache de controle de última checagem para evitar requisições em excesso
_LAST_CHECK_TIMESTAMP = 0


def fetch_youtube_channel_videos(channel_url_or_handle: str) -> Dict[str, Any]:
    """
    Busca os vídeos mais recentes de um canal do YouTube diretamente da página pública.
    Suporta @handle, URL completa ou ID de canal, sem necessidade de chaves de API.
    """
    clean = channel_url_or_handle.strip()
    if not clean.startswith("http"):
        if not clean.startswith("@"):
            clean = f"@{clean}"
        url = f"https://www.youtube.com/{clean}/videos"
    else:
        base = clean.rstrip('/')
        if not base.endswith('/videos'):
            url = f"{base}/videos"
        else:
            url = base

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
        "Accept-Language": "pt-BR,pt;q=0.9,en-US;q=0.8,en;q=0.7",
    }

    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=12) as response:
            html = response.read().decode('utf-8', errors='ignore')
    except Exception as e:
        logger.warning(f"Erro ao acessar canal do YouTube ({url}): {e}")
        return {"channel_name": channel_url_or_handle, "channel_id": None, "url": url, "videos": []}

    # Extrai título do canal
    title_match = re.search(r'<meta\s+property="og:title"\s+content="([^"]+)"', html)
    if not title_match:
        title_match = re.search(r'<title>([^<]+)</title>', html)
    channel_name = title_match.group(1).replace(" - YouTube", "").strip() if title_match else channel_url_or_handle

    # Procura canonical url ou channelId
    cid_match = re.search(r'itemprop="identifier"\s+content="(UC[\w-]{22})"', html)
    if not cid_match:
        cid_match = re.search(r'"channelId":"(UC[\w-]{22})"', html)
    channel_id = cid_match.group(1) if cid_match else None

    # Tenta extrair ytInitialData
    videos = []
    match = re.search(r'var ytInitialData\s*=\s*({.+?});</script>', html)
    if not match:
        match = re.search(r'window\["ytInitialData"\]\s*=\s*({.+?});</script>', html)

    if match:
        try:
            data = json.loads(match.group(1))

            def parse_recursive(obj):
                if isinstance(obj, dict):
                    # Formato 1: lockupViewModel (YouTube 2024+)
                    if "lockupViewModel" in obj:
                        lvm = obj["lockupViewModel"]
                        vid = lvm.get("contentId")
                        if not vid:
                            cmd_ctx = lvm.get("rendererContext", {}).get("commandContext", {})
                            we = cmd_ctx.get("onTap", {}).get("innertubeCommand", {}).get("watchEndpoint", {})
                            vid = we.get("videoId")

                        title = ""
                        meta_vm = lvm.get("metadata", {}).get("lockupMetadataViewModel", {})
                        if "title" in meta_vm and "content" in meta_vm["title"]:
                            title = meta_vm["title"]["content"]

                        time_text = ""
                        rows = meta_vm.get("metadata", {}).get("contentMetadataViewModel", {}).get("metadataRows", [])
                        for row in rows:
                            for part in row.get("metadataParts", []):
                                t = part.get("text", {}).get("content", "")
                                if "há " in t.lower() or "ago" in t.lower() or "dia" in t.lower() or "hora" in t.lower():
                                    time_text = t

                        if vid and title:
                            videos.append({
                                "video_id": vid,
                                "title": title,
                                "url": f"https://www.youtube.com/watch?v={vid}",
                                "published": time_text,
                                "thumbnail": f"https://i.ytimg.com/vi/{vid}/hqdefault.jpg"
                            })

                    # Formato 2: videoRenderer (YouTube legado)
                    elif "videoRenderer" in obj:
                        vr = obj["videoRenderer"]
                        vid = vr.get("videoId")
                        title = ""
                        if "title" in vr and "runs" in vr["title"]:
                            title = "".join(r.get("text", "") for r in vr["title"]["runs"])
                        elif "title" in vr and "simpleText" in vr["title"]:
                            title = vr["title"]["simpleText"]

                        time_text = vr.get("publishedTimeText", {}).get("simpleText", "")
                        if vid and title:
                            videos.append({
                                "video_id": vid,
                                "title": title,
                                "url": f"https://www.youtube.com/watch?v={vid}",
                                "published": time_text,
                                "thumbnail": f"https://i.ytimg.com/vi/{vid}/hqdefault.jpg"
                            })

                    for v in obj.values():
                        parse_recursive(v)
                elif isinstance(obj, list):
                    for item in obj:
                        parse_recursive(item)

            parse_recursive(data)
        except Exception as e:
            logger.warning(f"Erro ao parsear ytInitialData: {e}")

    # Remove duplicados preservando ordem cronológica
    seen = set()
    deduped = []
    for v in videos:
        if v["video_id"] not in seen:
            seen.add(v["video_id"])
            deduped.append(v)

    return {
        "channel_name": channel_name,
        "channel_id": channel_id,
        "url": url,
        "videos": deduped
    }


def format_youtube_card(video: dict, channel_name: str, channel_url: str) -> Tuple[str, InlineKeyboardMarkup]:
    """Formata o card visual de notificação de novo vídeo do YouTube para envio no grupo."""
    video_title = video.get("title", "Novo Vídeo")
    video_url = video.get("url", "")
    published = video.get("published", "")

    # Limpeza de caracteres conflitantes de markdown
    clean_title = video_title.replace("*", "").replace("_", "").replace("`", "")
    clean_channel = channel_name.replace("*", "").replace("_", "").replace("`", "")

    lines = [
        "🎬 *NOVO VÍDEO NO YOUTUBE!*",
        f"📺 *Canal:* {clean_channel}",
        f"🎥 *Título:* *{clean_title}*"
    ]
    if published:
        lines.append(f"⏰ *Publicação:* `{published}`")

    lines.extend([
        "",
        f"🔗 *Assista agora:* {video_url}",
        "",
        "🎼 *Partituras & Cia* • Compartilhando boa música com você!"
    ])

    text = "\n".join(lines)

    kb = [
        [
            InlineKeyboardButton("▶️ Assistir no YouTube", url=video_url),
            InlineKeyboardButton("📺 Visitar Canal", url=channel_url)
        ]
    ]
    return text, InlineKeyboardMarkup(kb)


def add_youtube_channel(cfg: dict, channel_input: str) -> Tuple[bool, str, Optional[dict]]:
    """Adiciona um canal à lista de monitoramento do YouTube."""
    clean_input = channel_input.strip()
    if not clean_input:
        return False, "Informe o @handle ou URL do canal.", None

    yt_cfg = cfg.setdefault("youtube_notifications", {
        "enabled": True,
        "target_chat": "@partiturasecia",
        "check_interval_minutes": 5,
        "channels": []
    })
    channels = yt_cfg.setdefault("channels", [])

    # Busca informações do canal
    info = fetch_youtube_channel_videos(clean_input)
    channel_name = info.get("channel_name") or clean_input
    channel_id = info.get("channel_id")
    channel_url = info.get("url") or clean_input
    videos = info.get("videos", [])

    # Verifica se já está cadastrado
    for ch in channels:
        if (channel_id and ch.get("channel_id") == channel_id) or ch.get("url") == channel_url:
            return False, f"O canal <b>{channel_name}</b> já está cadastrado na lista!", None

    last_vid = videos[0]["video_id"] if videos else ""

    new_channel = {
        "channel_id": channel_id,
        "name": channel_name,
        "url": channel_url,
        "input": clean_input,
        "last_video_id": last_vid
    }
    channels.append(new_channel)
    save_config(cfg)

    msg = f"Canal <b>{channel_name}</b> cadastrado com sucesso!"
    if videos:
        msg += f"\nÚltimo vídeo registrado: <i>{videos[0]['title']}</i>"
    return True, msg, new_channel


def remove_youtube_channel(cfg: dict, identifier: str) -> Tuple[bool, str]:
    """Remove um canal cadastrado por índice, ID ou URL."""
    yt_cfg = cfg.get("youtube_notifications", {})
    channels = yt_cfg.get("channels", [])
    if not channels:
        return False, "Nenhum canal cadastrado no momento."

    # Se for índice numérico
    if identifier.isdigit():
        idx = int(identifier)
        if 0 <= idx < len(channels):
            removed = channels.pop(idx)
            save_config(cfg)
            return True, f"Canal <b>{removed.get('name', 'Canal')}</b> removido com sucesso!"

    # Busca por ID ou URL ou nome
    for i, ch in enumerate(channels):
        if (ch.get("channel_id") == identifier or 
            ch.get("url") == identifier or 
            ch.get("name", "").lower() == identifier.lower() or 
            ch.get("input", "").lower() == identifier.lower()):
            removed = channels.pop(i)
            save_config(cfg)
            return True, f"Canal <b>{removed.get('name', 'Canal')}</b> removido com sucesso!"

    return False, f"Canal com identificador '{identifier}' não foi encontrado."


async def check_youtube_channels_cycle(bot) -> None:
    """Ciclo autônomo periódico para verificar canais e enviar cards de novos vídeos."""
    global _LAST_CHECK_TIMESTAMP
    now = time.time()

    cfg = load_config()
    yt_cfg = cfg.get("youtube_notifications", {})
    if not yt_cfg.get("enabled", True):
        return

    channels = yt_cfg.get("channels", [])
    if not channels:
        return

    interval_sec = yt_cfg.get("check_interval_minutes", 5) * 60
    if now - _LAST_CHECK_TIMESTAMP < interval_sec:
        return

    _LAST_CHECK_TIMESTAMP = now

    target_chat = yt_cfg.get("target_chat") or cfg.get("main_group_id") or "@partiturasecia"
    logger.info(f"[YouTube Notifier] Verificando {len(channels)} canais para envio em {target_chat}...")

    # Executa busca em thread separada para não bloquear o event loop
    loop = asyncio.get_running_loop()
    config_modified = False

    for ch in channels:
        try:
            ch_url = ch.get("url") or ch.get("input")
            if not ch_url:
                continue

            info = await loop.run_in_executor(None, fetch_youtube_channel_videos, ch_url)
            vids = info.get("videos", [])
            if not vids:
                continue

            latest_vid = vids[0]
            last_recorded_id = ch.get("last_video_id")

            # Se for a primeira vez que monitora este canal, apenas memoriza o último vídeo
            if not last_recorded_id:
                ch["last_video_id"] = latest_vid["video_id"]
                config_modified = True
                continue

            # Se houve publicação de novo vídeo!
            if latest_vid["video_id"] != last_recorded_id:
                logger.info(f"[YouTube Notifier] NOVO VÍDEO DETECTADO: {latest_vid['title']} ({latest_vid['video_id']})")
                channel_name = ch.get("name") or info.get("channel_name", "Canal do YouTube")
                card_text, markup = format_youtube_card(latest_vid, channel_name, ch_url)

                try:
                    await bot.send_message(
                        chat_id=target_chat,
                        text=card_text,
                        reply_markup=markup,
                        parse_mode=ParseMode.MARKDOWN,
                        disable_web_page_preview=False
                    )
                    logger.info(f"[YouTube Notifier] Notificação enviada para {target_chat} com sucesso!")
                except Exception as e_send:
                    logger.error(f"[YouTube Notifier] Falha ao enviar notificação para {target_chat}: {e_send}")

                ch["last_video_id"] = latest_vid["video_id"]
                config_modified = True

        except Exception as e_ch:
            logger.error(f"[YouTube Notifier] Erro ao checar canal {ch.get('name')}: {e_ch}")

    if config_modified:
        latest = load_config()
        progress = {(ch.get("url") or ch.get("input")): ch.get("last_video_id") for ch in channels}
        for ch in latest.get("youtube_notifications", {}).get("channels", []):
            key = ch.get("url") or ch.get("input")
            if key in progress and progress[key]:
                ch["last_video_id"] = progress[key]
        if not save_config(latest):
            raise RuntimeError("Não foi possível salvar o progresso do YouTube.")


async def check_youtube_channels_job(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handler para execução via JobQueue."""
    await check_youtube_channels_cycle(context.bot)


async def send_youtube_test_card(bot, target_chat: Any, cfg: dict) -> Tuple[bool, str]:
    """Envia um card de teste com o último vídeo de um dos canais cadastrados."""
    yt_cfg = cfg.get("youtube_notifications", {})
    channels = yt_cfg.get("channels", [])

    loop = asyncio.get_running_loop()

    if channels:
        ch = channels[0]
        ch_url = ch.get("url") or ch.get("input")
        info = await loop.run_in_executor(None, fetch_youtube_channel_videos, ch_url)
        vids = info.get("videos", [])
        if vids:
            vid = vids[0]
            name = ch.get("name") or info.get("channel_name", "YouTube")
        else:
            vid = {
                "video_id": "P7GTfHdl5E8",
                "title": "Vídeo Demonstrativo do Canal - Partituras & Cia",
                "url": "https://www.youtube.com/watch?v=P7GTfHdl5E8",
                "published": "há poucos instantes"
            }
            name = ch.get("name", "Canal de Teste")
    else:
        vid = {
            "video_id": "VC4g2l47rzc",
            "title": "Demonstração de Notificação do Canal - Partituras & Cia",
            "url": "https://www.youtube.com/watch?v=VC4g2l47rzc",
            "published": "agora"
        }
        name = "Canal Oficial de Demonstração"
        ch_url = "https://www.youtube.com/@partiturasecia"

    card_text, markup = format_youtube_card(vid, name, ch_url)
    try:
        await bot.send_message(
            chat_id=target_chat,
            text=card_text,
            reply_markup=markup,
            parse_mode=ParseMode.MARKDOWN,
            disable_web_page_preview=False
        )
        return True, f"Card de teste enviado com sucesso para <b>{target_chat}</b>!"
    except Exception as e:
        return False, f"Falha ao enviar card para <b>{target_chat}</b>: {e}"
