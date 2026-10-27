import os
import re
import json
import logging
from pathlib import Path
BASE_DIR = Path(__file__).resolve().parent
ENV_PATH = BASE_DIR / ".env"
CONFIG_PATH = BASE_DIR / "config.json"

try:
    from dotenv import load_dotenv
    if ENV_PATH.exists():
        load_dotenv(dotenv_path=ENV_PATH)
except ImportError:
    pass

logger = logging.getLogger("BotConfig")

DEFAULT_CONFIG = {
    "telegram_bot_token": "",
    "timezone": "America/Sao_Paulo",
    "welcome": {
        "enabled": True,
        "delete_service_messages": True,
        "delete_welcome_after_seconds": 600,
        "photo": None,
        "article_url": None,
        "buttons": [
            [
                {"text": "📜 Regras do Grupo", "callback_data": "btn:rules"},
                {"text": "🎥 Como Pesquisar", "callback_data": "btn:tutorial"}
            ]
        ],
        "message": "👋 Olá, {name}! Seja bem-vindo(a) ao grupo *{group}*!\n\n📌 Toque nos botões abaixo para consultar as regras do grupo e aprender a pesquisar partituras rapidamente pelo bot!"
    },
    "antispam": {
        "enabled": True,
        "block_links": True,
        "block_telegram_invites": True,
        "block_forwards": True,
        "warn_delete_after_seconds": 8,
        "banned_words_action": "warn",  # "warn" (Só Aviso), "warning" (Advertência c/ contagem), "ban" (Ban Imediato)
        "allowed_domains": ["drive.google.com", "docs.google.com"],
        "banned_words": [
            "ganhe dinheiro",
            "renda extra",
            "investimento garantido",
            "trabalhe em casa ganhando",
            "clique no link",
            "crypto pump",
            "robô do pix",
            "plataforma pagando",
            "t.me/joinchat",
            "cassino online",
            "tigrinho"
        ]
    },
    "antiflood": {
        "enabled": True,
        "max_messages": 5,
        "time_window_seconds": 5,
        "mute_duration_minutes": 5,
        "warn_delete_after_seconds": 8
    },
    "antirepeat": {
        "enabled": True,
        "max_repeated": 2,
        "time_window_hours": 2,
        "time_window_seconds": 7200,
        "warn_delete_after_seconds": 8
    },
    "command_cleanup": {
        "delete_admin_commands": True,
        "delete_non_admin_commands": True,
        "bot_notice_delete_seconds": 10
    },
    "group_welcomes": {},    # Configurações de boas-vindas personalizadas por grupo: {"<chat_id>": {...}}
    "whitelist_users": [],   # Usuários livres/isentos de restrições (links, flood, spam): [{"user_id": int, "name": str, ...}]
    "captcha": {
        "enabled": False,
        "timeout_seconds": 180,
        "kick_on_timeout": True
    },
    "join_requests": {
        "auto_approve": True,
        "send_welcome_dm": True,
        "dm_message": "👋 Olá, {name}!\n\nSua solicitação de entrada no {tipo} *{group}* foi aprovada com sucesso! 🎵\nSeja muito bem-vindo(a) à nossa comunidade musical!"
    },
    "rules": "📜 *Regras do Grupo:*\n\n1. *Respeito acima de tudo*: ofensas ou desrespeito não serão tolerados.\n2. *Sem Spam*: links e divulgações não autorizadas serão apagados.\n3. *Sem Flood*: evite mensagens repetidas ou excessivas.\n\nDúvidas? Chame um administrador!",
    "recurring_messages": [],
    "scheduled_transmissions": [],
    "auto_responses": [
        {
            "id": 1,
            "title": "Chave PIX / Apoio",
            "pattern": r"(?i)\b(qual\s+o?\s*pix|manda\s+o?\s*pix|chave\s+pix|fazer\s+um\s*pix)\b",
            "is_regex": True,
            "text": "💰 *Chave PIX do Grupo:*\n\n`contato@partiturasecia.com.br`\n\nQualquer apoio ajuda a manter nosso acervo e o grupo ativos! Obrigado, {name}! 🎵",
            "photo": None,
            "buttons": [],
            "cooldown_seconds": 30,
            "delay_seconds": 0,
            "reply_to": True,
            "delete_trigger": False,
            "enabled": True
        },
        {
            "id": 2,
            "title": "Acervo de Partituras",
            "pattern": r"(?i)\b(como\s+achar|onde\s+(fica|est[aã]o?)\s+as?\s+partituras?|onde\s+baixo|tem\s+partitura)\b",
            "is_regex": True,
            "text": "🎼 *Acervo de Partituras!*\n\nOlá {name}! Você pode buscar arquivos na lupa do grupo 🔍 ou usar a hashtag #partitura.\n\nFique à vontade para pesquisar ou pedir ajuda aos outros membros!",
            "photo": None,
            "buttons": [],
            "cooldown_seconds": 20,
            "delay_seconds": 0,
            "reply_to": True,
            "delete_trigger": False,
            "enabled": True
        },
        {
            "id": 3,
            "title": "Pedidos de Partituras e Arranjos",
            "pattern": r"(?i)(\b(algu[eé]m\s+(a[ií]\s+)?(tem|teria|consegue|passa|manda|compartilha)|quem\s+(tem|teria|pode)|onde\s+(acho|encontro|tem|consigo|baixo)|como\s+(achar|encontrar|conseguir|baixar)|preciso\s+d?[eoa]?|procuro|procurando)\b.*?\b(partitura|partituras|arranjo|arranjos|m[eé]todo|m[eé]todos|grade|grades|cifra|cifras|playback|pdf|hino|hinos|louvor|louvores|m[uú]sica|m[uú]sicas|sax|trompete|violino|metais|clarinete|trombone|flauta|teclado|bateria|baixo|viol[aã]o|guitarra|violoncelo|cello|trompa|euf[oô]nio|tuba|saxofone|clarone|obo[eé]|fagote|harpa|hin[aá]rio|solo|solos|intro|introdu[cç][aã]o|vers[aã]o|vers[oõ]es|orquestra|banda|coral|coro|quarteto|voz|vozes|soprano|contralto|tenor)\b|\b(partitura|partituras|arranjo|arranjos|m[eé]todo|m[eé]todos|grade|grades|cifra|cifras|playback|pdf|hino|hinos|louvor|louvores|m[uú]sica|m[uú]sicas|sax|trompete|violino|metais|clarinete|trombone|flauta|teclado|bateria|baixo|viol[aã]o|guitarra|violoncelo|cello|trompa|euf[oô]nio|tuba|saxofone|clarone|obo[eé]|fagote|harpa|hin[aá]rio|solo|solos|intro|introdu[cç][aã]o|vers[aã]o|vers[oõ]es|orquestra|banda|coral|coro|quarteto|voz|vozes|soprano|contralto|tenor)\b.*?\b(algu[eé]m\s+(a[ií]\s+)?(tem|teria)|quem\s+tem)\b|\b(algu[eé]m\s+(a[ií]\s+)?(tem|teria)|quem\s+(tem|teria)|onde\s+acho|onde\s+encontro|procuro|procurando)\b.*?[\"\'“][^\"\'”]{2,}[\"\'”]|\b(algu[eé]m\s+(a[ií]\s+)?(tem|teria))\s+(?!not[ií]cias?|d[uú]vidas?|certeza|tempo|medo|fome|troco|dinheiro|caneta|aula|ensaio)\b.*?\b(do|da|de|dos|das)\s+[a-zà-ú]{3,}.*?\?|\b(algu[eé]m\s+(a[ií]\s+)?(tem|teria)|quem\s+(tem|teria))\s*[:\?]?\s*(\n\s*[-*•]|\s*[-*•]|\s*:)|\b(algu[eé]m\s+(a[ií]\s+)?(tem|teria))\s+(ess[ae]s?|dest[ae]s?)\b|\b(algu[eé]m\s+(a[ií]\s+)?(tem|teria))\b.*?\w+\s+[-–—]\s+\w+)",
            "is_regex": True,
            "text": "👋 Olá, {name}!\n\nProcurando por partituras, métodos ou arranjos? Acesse nossos canais oficiais no Telegram ou utilize a busca interna pela lupa 🔍!",
            "photo": None,
            "buttons": [
                [
                    {"text": "📢 Canal de Partituras", "url": "https://t.me/"},
                    {"text": "🎵 Canal de Arranjos", "url": "https://t.me/"}
                ]
            ],
            "cooldown_seconds": 30,
            "delay_seconds": 10,
            "reply_to": True,
            "delete_trigger": False,
            "enabled": True
        }
    ],
    "acervo_group_auto_reply": False,
    "acervo_auto_delete_seconds": 0,  # 0 = Desativado (não apaga respostas de partitura)
    "main_group_id": None,
    "linked_groups": [],     # Lista de grupos vinculados: [{"id": int, "title": str, "type": str, "linked_at": str}]
    "linked_channels": [],   # Lista de canais vinculados: [{"id": int, "title": str, "username": str, "linked_at": str}]
    "main_channel_id": None, # Canal principal para comandos rápidos /canal
    "log_channel_id": None,
    "log_events": {
        "bans": True,
        "mutes": True,
        "warns": True,
        "spam": True,
        "joins": True,
        "leaves": True
    },
    "locks": {
        "sticker": False,
        "gif": False,
        "audio": False,
        "voice": False,
        "video": False,
        "videonote": False,
        "document": False,
        "contact": False,
        "poll": False,
        "forward": False,
        "link": False
    },
    "notes": {},
    "night_mode": {
        "enabled": False,
        "start": "23:00",
        "end": "07:00",
        "warn_delete_after_seconds": 8,
        "announce_start": True,
        "announce_end": True,
        "current_state": None,
        "enabled_chats": []
    }
}

def load_config() -> dict:
    config = dict(DEFAULT_CONFIG)
    bak_path = BASE_DIR / ".config_backup.json"
    if CONFIG_PATH.exists():
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                user_cfg = json.load(f)
                # Mescla configurações preservando campos
                for k, v in user_cfg.items():
                    if isinstance(v, dict) and k in config and isinstance(config[k], dict):
                        config[k].update(v)
                    else:
                        config[k] = v
                # Se o config tiver dados reais salvos, atualiza o backup de segurança
                if user_cfg.get("main_group_id") or user_cfg.get("recurring_messages"):
                    try:
                        with open(bak_path, "w", encoding="utf-8") as fb:
                            json.dump(user_cfg, fb, ensure_ascii=False, indent=2)
                    except Exception:
                        pass
        except Exception as e:
            logger.error(f"Erro ao ler config.json: {e}. Usando configuração padrão.")
    elif bak_path.exists():
        try:
            with open(bak_path, "r", encoding="utf-8") as fb:
                user_cfg = json.load(fb)
                for k, v in user_cfg.items():
                    if isinstance(v, dict) and k in config and isinstance(config[k], dict):
                        config[k].update(v)
                    else:
                        config[k] = v
            save_config(config)
            logger.info("config.json restaurado automaticamente do backup de segurança!")
        except Exception:
            pass

    # Garante migração automática caso main_group_id ou main_channel_id existam
    if config.get("main_group_id"):
        groups = config.setdefault("linked_groups", [])
        if not any(g.get("id") == config["main_group_id"] for g in groups):
            groups.insert(0, {
                "id": config["main_group_id"],
                "title": "Grupo Principal",
                "type": "supergroup",
                "linked_at": ""
            })

    if config.get("main_channel_id"):
        channels = config.setdefault("linked_channels", [])
        if not any(c.get("id") == config["main_channel_id"] for c in channels):
            channels.insert(0, {
                "id": config["main_channel_id"],
                "title": "Canal Principal",
                "username": "",
                "linked_at": ""
            })

    # Garante que a resposta padrão #3 de pedidos de partituras/músicas utilize o regex atualizado
    if "auto_responses" in config and isinstance(config["auto_responses"], list):
        for resp in config["auto_responses"]:
            if resp.get("id") == 3:
                resp["pattern"] = DEFAULT_CONFIG["auto_responses"][2]["pattern"]

    # Garante estrutura padrão de whitelist de usuários e links permitidos
    if "whitelist_users" not in config or not isinstance(config["whitelist_users"], list):
        config["whitelist_users"] = []
        cfg_modified = True

    antispam_cfg = config.setdefault("antispam", {})
    if "allowed_domains" not in antispam_cfg or not isinstance(antispam_cfg["allowed_domains"], list):
        antispam_cfg["allowed_domains"] = ["drive.google.com", "docs.google.com"]
        cfg_modified = True
    elif not antispam_cfg.get("allowed_domains"):
        antispam_cfg["allowed_domains"] = ["drive.google.com", "docs.google.com"]
        cfg_modified = True

    # Normalização automática e desduplicação de IDs de supergrupos/canais salvos no config
    cfg_modified = False

    seen_groups = set()
    deduped_groups = []
    for g in config.get("linked_groups", []):
        old_id = g.get("id")
        norm_id = normalize_chat_id(old_id)
        if norm_id != old_id:
            g["id"] = norm_id
            cfg_modified = True
        if norm_id not in seen_groups:
            seen_groups.add(norm_id)
            deduped_groups.append(g)
        else:
            cfg_modified = True
    config["linked_groups"] = deduped_groups

    seen_channels = set()
    deduped_channels = []
    for c in config.get("linked_channels", []):
        old_id = c.get("id")
        norm_id = normalize_chat_id(old_id)
        if norm_id != old_id:
            c["id"] = norm_id
            cfg_modified = True
        if norm_id not in seen_channels:
            seen_channels.add(norm_id)
            deduped_channels.append(c)
        else:
            cfg_modified = True
    config["linked_channels"] = deduped_channels

    if config.get("main_group_id"):
        norm_id = normalize_chat_id(config["main_group_id"])
        if norm_id != config["main_group_id"]:
            config["main_group_id"] = norm_id
            cfg_modified = True

    if config.get("main_channel_id"):
        norm_id = normalize_chat_id(config["main_channel_id"])
        if norm_id != config["main_channel_id"]:
            config["main_channel_id"] = norm_id
            cfg_modified = True

    if config.get("log_channel_id"):
        norm_id = normalize_chat_id(config["log_channel_id"])
        if norm_id != config["log_channel_id"]:
            config["log_channel_id"] = norm_id
            cfg_modified = True

    nm = config.get("night_mode", {})
    if isinstance(nm, dict) and "enabled_chats" in nm and isinstance(nm["enabled_chats"], list):
        new_chats = []
        for cid in nm["enabled_chats"]:
            nid = normalize_chat_id(cid)
            if nid not in new_chats:
                new_chats.append(nid)
            if nid != cid:
                cfg_modified = True
        if len(new_chats) != len(nm["enabled_chats"]):
            cfg_modified = True
        nm["enabled_chats"] = new_chats

    gw = config.get("group_welcomes", {})
    if isinstance(gw, dict):
        new_gw = {}
        for k, v in gw.items():
            norm_k = str(normalize_chat_id(k))
            new_gw[norm_k] = v
            if norm_k != k:
                cfg_modified = True
        config["group_welcomes"] = new_gw

    # Migração e autocorreção do canal HC Sibelius para o ID real informado (-1001806380183)
    WRONG_HC_IDS = {-1002071806380183, -2071806380183, 2071806380183, 1002071806380183}
    REAL_HC_ID = -1001806380183

    # Se HC Sibelius estava em linked_groups por engano (ele é um canal, não grupo)
    hc_title = "HC Sibelius"
    filtered_groups = []
    found_in_groups = False
    for g in config.get("linked_groups", []):
        if g.get("id") in WRONG_HC_IDS or ("sibelius" in str(g.get("title", "")).lower() and g.get("id") != REAL_HC_ID):
            hc_title = g.get("title") or "HC Sibelius"
            found_in_groups = True
            cfg_modified = True
            continue
        filtered_groups.append(g)
    config["linked_groups"] = filtered_groups

    # Garante em linked_channels com o ID oficial e tipo canal
    channels = config.setdefault("linked_channels", [])
    hc_chan = next((c for c in channels if c.get("id") == REAL_HC_ID), None)
    if not hc_chan:
        for c in channels:
            if c.get("id") in WRONG_HC_IDS or "sibelius" in str(c.get("title", "")).lower():
                c["id"] = REAL_HC_ID
                c["title"] = c.get("title") or hc_title
                hc_chan = c
                cfg_modified = True
                break
        if not hc_chan:
            from datetime import datetime
            channels.insert(0, {
                "id": REAL_HC_ID,
                "title": hc_title,
                "username": "",
                "linked_at": datetime.now().strftime("%d/%m/%Y %H:%M")
            })
            cfg_modified = True
    else:
        if not hc_chan.get("title") or hc_chan.get("title") == f"Canal {REAL_HC_ID}":
            hc_chan["title"] = hc_title
            cfg_modified = True

    if not config.get("main_channel_id") or config.get("main_channel_id") in WRONG_HC_IDS:
        config["main_channel_id"] = REAL_HC_ID
        cfg_modified = True

    if config.get("main_group_id") in WRONG_HC_IDS:
        config["main_group_id"] = config["linked_groups"][0]["id"] if config["linked_groups"] else None
        cfg_modified = True

    if cfg_modified:
        try:
            save_config(config)
            logger.info("Configurações e IDs de canais/grupos sincronizados com sucesso!")
        except Exception:
            pass

    return config

def get_bot_token() -> str:
    # 1. Tenta carregar da variável de ambiente ou do .env
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    if token and token != "SEU_TOKEN_AQUI":
        return token
    
    # 2. Tenta carregar do config.json
    cfg = load_config()
    token_json = cfg.get("telegram_bot_token", "").strip()
    if token_json and token_json != "SEU_TOKEN_AQUI":
        return token_json

    return ""

def save_config(config: dict) -> bool:
    """Salva as configurações alteradas no arquivo config.json e cria cópia de segurança."""
    try:
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(config, f, ensure_ascii=False, indent=2)
        # Salva cópia de segurança oculta
        bak_path = BASE_DIR / ".config_backup.json"
        try:
            with open(bak_path, "w", encoding="utf-8") as fb:
                json.dump(config, fb, ensure_ascii=False, indent=2)
        except Exception:
            pass
        return True
    except Exception as e:
        logger.error(f"Erro ao salvar config.json: {e}")
        return False

# =====================================================================
# AUXILIARES DE FUSO HORÁRIO
# =====================================================================
import zoneinfo
from datetime import datetime

TIMEZONE_LIST = [
    ("America/Sao_Paulo", "🇧🇷 São Paulo / Brasília (UTC-3)"),
    ("America/Manaus", "🇧🇷 Manaus (UTC-4)"),
    ("America/Fortaleza", "🇧🇷 Fortaleza / Nordeste (UTC-3)"),
    ("America/Cuiaba", "🇧🇷 Cuiabá (UTC-4)"),
    ("America/Belem", "🇧🇷 Belém (UTC-3)"),
    ("America/Rio_Branco", "🇧🇷 Acre (UTC-5)"),
    ("America/Noronha", "🇧🇷 Noronha (UTC-2)"),
    ("Europe/Lisbon", "🇵🇹 Lisboa / Portugal (UTC+0/+1)"),
    ("UTC", "🌐 UTC (Universal)")
]

def get_timezone(cfg: dict = None):
    if cfg is None:
        cfg = load_config()
    tz_name = cfg.get("timezone", "America/Sao_Paulo")
    try:
        return zoneinfo.ZoneInfo(tz_name)
    except Exception:
        from datetime import timezone, timedelta
        return timezone(timedelta(hours=-3))

def get_timezone_label(cfg: dict = None) -> str:
    if cfg is None:
        cfg = load_config()
    tz_name = cfg.get("timezone", "America/Sao_Paulo")
    for key, label in TIMEZONE_LIST:
        if key == tz_name:
            return label
    return tz_name

def set_timezone(cfg: dict, tz_name: str) -> bool:
    """Valida e define o fuso horário configurado."""
    try:
        zoneinfo.ZoneInfo(tz_name)
    except Exception:
        return False
    cfg["timezone"] = tz_name
    save_config(cfg)
    return True

def cycle_timezone(cfg: dict) -> str:
    cur = cfg.get("timezone", "America/Sao_Paulo")
    keys = [k for k, _ in TIMEZONE_LIST]
    try:
        idx = keys.index(cur)
        new_tz = keys[(idx + 1) % len(keys)]
    except ValueError:
        new_tz = keys[0]
    cfg["timezone"] = new_tz
    save_config(cfg)
    return new_tz

def normalize_chat_id(val):
    """
    Normaliza IDs de chats do Telegram.
    Garante que qualquer ID numérico de supergrupo ou canal (10 ou mais dígitos)
    tenha o prefixo oficial obrigatório -100 da API do Telegram.
    Exemplo: -2071806380183 -> -1002071806380183
             -1002071806380183 -> -1002071806380183 (mantém sem duplicar)
             -1001001002071806380183 -> -1002071806380183 (limpa corrupções passadas)
             1002071806380183 -> -1002071806380183
             -123456789 -> -123456789 (grupo legado permanece intato)
             123456789 -> 123456789 (chat privado com usuário permanece intato)
    """
    if val is None:
        return val
    try:
        s = str(val).strip()
        if not s:
            return val
        
        # Se for string de username (@canal), mantém como está
        if s.startswith("@"):
            return s
            
        # Verifica se é numérico (com ou sem sinal negativo)
        if not re.match(r"^-?\d+$", s):
            return val
            
        # 1. Se foi corrompido com repetições de 100 (ex: -1001001002071806380183)
        corrupted_match = re.match(r"^-?(?:100)+(\d{9,13})$", s)
        if corrupted_match and (s.count("100") > 1 or len(s) > 17):
            base_digits = corrupted_match.group(1)
            return int(f"-100{base_digits}")
            
        # 2. Se já começa com -100 (formato oficial de canal/supergrupo)
        if s.startswith("-100"):
            return int(s)

        # 3. Se começa com 100 positivo de canal (>= 12 dígitos, ex: 1002071806380183)
        if s.startswith("100") and len(s) >= 12:
            return int(f"-{s}")
            
        # 4. Se começa com - mas não tem 100 e tem 10 ou mais dígitos (ex: -2071806380183)
        digits = s.lstrip("-")
        if s.startswith("-") and len(digits) >= 10:
            return int(f"-100{digits}")
            
        # 5. Números negativos menores (-123456789 = grupo básico legado) ou
        #    Números positivos (123456789 = ID de usuário no privado)
        return int(s)
    except Exception:
        return val

# =====================================================================
# AUXILIARES DE VÍNCULO MULTI-GRUPOS E CANAIS
# =====================================================================

def add_linked_group(cfg: dict, chat_id: int, title: str = "", chat_type: str = "supergroup") -> bool:
    """Adiciona ou atualiza um grupo na lista de grupos vinculados."""
    chat_id = normalize_chat_id(chat_id)
    groups = cfg.setdefault("linked_groups", [])
    found = False
    for g in groups:
        if g.get("id") == chat_id:
            found = True
            if title:
                g["title"] = title
            if chat_type:
                g["type"] = chat_type
            break
    if not found:
        from datetime import datetime
        now_str = datetime.now().strftime("%d/%m/%Y %H:%M")
        groups.append({
            "id": chat_id,
            "title": title or f"Grupo {chat_id}",
            "type": chat_type,
            "linked_at": now_str
        })
    if not cfg.get("main_group_id"):
        cfg["main_group_id"] = chat_id
    nm = cfg.setdefault("night_mode", {})
    c_list = nm.setdefault("enabled_chats", [])
    if chat_id not in c_list:
        c_list.append(chat_id)
    save_config(cfg)
    return True

def remove_linked_group(cfg: dict, chat_id: int) -> bool:
    """Remove um grupo da lista de grupos vinculados."""
    groups = cfg.setdefault("linked_groups", [])
    initial_len = len(groups)
    cfg["linked_groups"] = [g for g in groups if g.get("id") != chat_id]
    if cfg.get("main_group_id") == chat_id:
        cfg["main_group_id"] = cfg["linked_groups"][0]["id"] if cfg["linked_groups"] else None
    save_config(cfg)
    return len(cfg["linked_groups"]) < initial_len

def add_linked_channel(cfg: dict, channel_id: int, title: str = "", username: str = "") -> bool:
    """Adiciona ou atualiza um canal na lista de canais vinculados."""
    channel_id = normalize_chat_id(channel_id)
    channels = cfg.setdefault("linked_channels", [])
    found = False
    for c in channels:
        if c.get("id") == channel_id:
            found = True
            if title:
                c["title"] = title
            if username:
                c["username"] = username
            break
    if not found:
        from datetime import datetime
        now_str = datetime.now().strftime("%d/%m/%Y %H:%M")
        channels.append({
            "id": channel_id,
            "title": title or f"Canal {channel_id}",
            "username": username or "",
            "linked_at": now_str
        })
    if not cfg.get("main_channel_id"):
        cfg["main_channel_id"] = channel_id
    save_config(cfg)
    return True

def remove_linked_channel(cfg: dict, channel_id: int) -> bool:
    """Remove um canal da lista de canais vinculados."""
    channels = cfg.setdefault("linked_channels", [])
    initial_len = len(channels)
    cfg["linked_channels"] = [c for c in channels if c.get("id") != channel_id]
    if cfg.get("main_channel_id") == channel_id:
        cfg["main_channel_id"] = cfg["linked_channels"][0]["id"] if cfg["linked_channels"] else None
    save_config(cfg)
    return len(cfg["linked_channels"]) < initial_len

def get_all_linked_chats(cfg: dict) -> list[dict]:
    """Retorna lista unificada de todos os grupos e canais vinculados."""
    res = []
    for g in cfg.get("linked_groups", []):
        res.append({
            "id": g.get("id"),
            "title": g.get("title", f"Grupo {g.get('id')}"),
            "type": g.get("type", "supergroup"),
            "is_channel": False,
            "username": g.get("username", "")
        })
    for c in cfg.get("linked_channels", []):
        res.append({
            "id": c.get("id"),
            "title": c.get("title", f"Canal {c.get('id')}"),
            "type": "channel",
            "is_channel": True,
            "username": c.get("username", "")
        })
    return res

def get_welcome_for_chat(cfg: dict, chat_id: int | str | None) -> dict:
    """Retorna as configurações de boas-vindas do grupo específico ou o padrão geral."""
    default_w = cfg.get("welcome", {})
    if not chat_id:
        return default_w
    chat_key = str(chat_id)
    gw = cfg.get("group_welcomes", {})
    if chat_key in gw and isinstance(gw[chat_key], dict):
        res = dict(default_w)
        res.update(gw[chat_key])
        return res
    return default_w

def set_welcome_for_chat(cfg: dict, chat_id: int | str, welcome_cfg: dict):
    """Salva configurações de boas-vindas para um grupo específico ou no padrão geral."""
    chat_key = str(chat_id)
    if chat_key in ("general", "0", ""):
        cfg["welcome"] = welcome_cfg
    else:
        gw = cfg.setdefault("group_welcomes", {})
        gw[chat_key] = welcome_cfg
    save_config(cfg)

def remove_custom_welcome(cfg: dict, chat_id: int | str) -> bool:
    """Remove a customização de boas-vindas de um grupo, fazendo-o voltar ao padrão geral."""
    chat_key = str(chat_id)
    gw = cfg.get("group_welcomes", {})
    if chat_key in gw:
        del gw[chat_key]
        save_config(cfg)
        return True
    return False

def get_welcome_mode_for_chat(cfg: dict, chat_id: int | str) -> str:
    """Retorna o modo de boas-vindas do chat: 'inherited', 'custom' ou 'disabled'."""
    chat_key = str(chat_id)
    if chat_key in ("general", "0", ""):
        return "custom" if cfg.get("welcome", {}).get("enabled", True) else "disabled"
    gw = cfg.get("group_welcomes", {})
    if chat_key not in gw or not isinstance(gw[chat_key], dict):
        return "inherited"
    if gw[chat_key].get("enabled") is False:
        return "disabled"
    return "custom"

def disable_welcome_for_chat(cfg: dict, chat_id: int | str):
    """Desativa as boas-vindas especificamente para este grupo."""
    chat_key = str(chat_id)
    if chat_key in ("general", "0", ""):
        cfg.setdefault("welcome", {})["enabled"] = False
    else:
        gw = cfg.setdefault("group_welcomes", {})
        if chat_key not in gw or not isinstance(gw[chat_key], dict):
            gw[chat_key] = {"enabled": False}
        else:
            gw[chat_key]["enabled"] = False
    save_config(cfg)

def set_inherited_welcome_for_chat(cfg: dict, chat_id: int | str):
    """Faz o grupo voltar a herdar 100% o Padrão Geral."""
    chat_key = str(chat_id)
    gw = cfg.get("group_welcomes", {})
    if chat_key in gw:
        del gw[chat_key]
        save_config(cfg)

def set_custom_welcome_for_chat(cfg: dict, chat_id: int | str):
    """Cria uma cópia exclusiva da mensagem atual para edição independente deste grupo."""
    chat_key = str(chat_id)
    if chat_key in ("general", "0", ""):
        return
    gw = cfg.setdefault("group_welcomes", {})
    # Copia a configuração atual ou o padrão geral como base
    current = get_welcome_for_chat(cfg, chat_key)
    custom_copy = dict(current)
    custom_copy["enabled"] = True
    gw[chat_key] = custom_copy
    save_config(cfg)


# ==============================================================================
# Funções de Controle de Usuários Livres (Whitelist de Membros Isentos)
# ==============================================================================

def is_user_whitelisted(cfg: dict, user_id: int | str) -> bool:
    """Verifica se o usuário está na lista branca (isento de restrições de links, flood, spam e repetição)."""
    try:
        uid = int(user_id)
    except (ValueError, TypeError):
        return False

    w_users = cfg.get("whitelist_users", [])
    for u in w_users:
        if isinstance(u, dict) and u.get("user_id") == uid:
            return True
        elif isinstance(u, (int, str)) and str(u) == str(uid):
            return True
    return False

def add_whitelist_user(cfg: dict, user_id: int | str, name: str = "", username: str = "", added_by: str = "") -> bool:
    """Adiciona um usuário à lista branca de membros livres."""
    from datetime import datetime
    try:
        uid = int(user_id)
    except (ValueError, TypeError):
        return False

    cfg.setdefault("whitelist_users", [])
    if is_user_whitelisted(cfg, uid):
        return False

    clean_user = username.lstrip("@") if username else ""
    cfg["whitelist_users"].append({
        "user_id": uid,
        "name": name or f"Usuário {uid}",
        "username": clean_user,
        "added_by": added_by or "Admin",
        "added_at": datetime.now().strftime("%d/%m/%Y %H:%M")
    })
    save_config(cfg)
    return True

def remove_whitelist_user(cfg: dict, user_id: int | str) -> bool:
    """Remove um usuário da lista branca."""
    try:
        uid = int(user_id)
    except (ValueError, TypeError):
        return False

    cfg.setdefault("whitelist_users", [])
    orig_len = len(cfg["whitelist_users"])
    cfg["whitelist_users"] = [
        u for u in cfg["whitelist_users"]
        if not (
            (isinstance(u, dict) and u.get("user_id") == uid) or
            (isinstance(u, (int, str)) and str(u) == str(uid))
        )
    ]
    if len(cfg["whitelist_users"]) != orig_len:
        save_config(cfg)
        return True
    return False

def get_whitelist_users(cfg: dict) -> list:
    """Retorna a lista de usuários livres formatada."""
    return cfg.get("whitelist_users", [])


# ==============================================================================
# Funções de Controle de Links e Domínios Permitidos (Whitelist de Links)
# ==============================================================================

def get_allowed_domains(cfg: dict) -> list:
    """Retorna os domínios/links autorizados na lista branca."""
    return cfg.get("antispam", {}).get("allowed_domains", ["drive.google.com", "docs.google.com"])

def add_allowed_domain(cfg: dict, domain: str) -> bool:
    """Adiciona um link, trecho de link ou domínio à lista branca (ex: drive.google.com ou drive.google.com/drive/folders/...)."""
    dom = domain.strip().lower()
    dom = re.sub(r"^https?://", "", dom)
    dom = re.sub(r"^www\.", "", dom)
    dom = dom.rstrip("/")
    if not dom:
        return False

    domains = cfg.setdefault("antispam", {}).setdefault("allowed_domains", [])
    clean_existing = [d.lower().strip().rstrip("/") for d in domains]
    if dom in clean_existing:
        return False

    domains.append(dom)
    save_config(cfg)
    return True

def remove_allowed_domain(cfg: dict, domain: str) -> bool:
    """Remove um link, trecho de link ou domínio da lista branca."""
    dom = domain.strip().lower()
    dom = re.sub(r"^https?://", "", dom)
    dom = re.sub(r"^www\.", "", dom)
    dom = dom.rstrip("/")

    domains = cfg.setdefault("antispam", {}).setdefault("allowed_domains", [])
    new_domains = [d for d in domains if re.sub(r"^www\.", "", re.sub(r"^https?://", "", d.lower().strip())).rstrip("/") != dom]
    if len(new_domains) != len(domains):
        cfg["antispam"]["allowed_domains"] = new_domains
        save_config(cfg)
        return True
    return False



