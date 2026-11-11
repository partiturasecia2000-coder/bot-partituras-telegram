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


def normalize_search_term(text: str) -> str:
    """Normaliza texto removendo acentos, pontuação e convertendo para minúsculas."""
    if not text:
        return ""
    n = unicodedata.normalize("NFKD", str(text))
    clean = "".join(c for c in n if not unicodedata.combining(c)).lower()
    clean = re.sub(r"[^\w\s]", " ", clean)
    return " ".join(clean.split())


# Dicionário abrangente de sinônimos e abreviações musicais/instrumentos
INSTRUMENT_ALIASES = {
    "sax": ["sax", "saxofone", "saxophone", "saxo"],
    "saxofone": ["saxofone", "saxophone", "sax"],
    "saxophone": ["saxophone", "saxofone", "sax"],
    "tpt": ["tpt", "trompete", "trumpet", "tromp"],
    "trompete": ["trompete", "tpt", "trumpet", "tromp"],
    "trumpet": ["trumpet", "trompete", "tpt"],
    "tromp": ["trompete", "trumpet", "tpt"],
    "tbn": ["tbn", "trombone"],
    "trombone": ["trombone", "tbn"],
    "clari": ["clari", "clarinete", "clarineta", "clarinet"],
    "clarinete": ["clarinete", "clarineta", "clarinet", "clari"],
    "clarineta": ["clarineta", "clarinete", "clarinet"],
    "clarinet": ["clarinet", "clarinete", "clarineta"],
    "flauta": ["flauta", "flute", "flt", "flautim"],
    "flute": ["flute", "flauta", "flt"],
    "flt": ["flt", "flauta", "flute"],
    "violino": ["violino", "violin", "vln"],
    "violin": ["violin", "violino", "vln"],
    "vln": ["vln", "violino", "violin"],
    "violoncelo": ["violoncelo", "cello", "vlc"],
    "cello": ["cello", "violoncelo", "vlc"],
    "vlc": ["vlc", "violoncelo", "cello"],
    "teclado": ["teclado", "piano", "keyboard", "orgao"],
    "piano": ["piano", "teclado"],
    "orgao": ["orgao", "organ"],
    "violao": ["violao", "guitarra", "acustico"],
    "guitarra": ["guitarra", "guitar", "violao"],
    "baixo": ["baixo", "bass", "contrabaixo"],
    "contrabaixo": ["contrabaixo", "baixo", "bass"],
    "bateria": ["bateria", "drums"],
    "tuba": ["tuba", "sousafone"],
    "trompa": ["trompa", "horn"],
    "eufonio": ["eufonio", "euphonium", "bombardino"],
    "bombardino": ["bombardino", "eufonio", "euphonium"],
    "oboe": ["oboe", "oboe"],
    "fagote": ["fagote", "bassoon"],
    "orquestra": ["orquestra", "orquestral", "orchestra", "grade"],
    "grade": ["grade", "score", "orquestra", "full score"],
    "harpa": ["harpa", "harpa crista", "hc"],
    "ccb": ["ccb"],
}

# Stopwords que costumam ser digitadas em pedidos informais ou buscas genéricas
SEARCH_STOPWORDS = {
    "o", "a", "os", "as", "um", "uma", "uns", "umas",
    "de", "do", "da", "dos", "das", "em", "no", "na",
    "nos", "nas", "para", "pra", "pro", "pras", "pros",
    "com", "por", "pelo", "pela", "pelos", "pelas",
    "que", "se", "ou", "e", "eu", "ele", "ela",
    "partitura", "partituras", "score", "pdf",
    "alguem", "quem", "tem", "teria", "consegue", "passa", "manda",
    "compartilha", "envia", "onde", "acho", "encontro", "consigo",
    "baixo", "como", "preciso", "procuro", "procurando", "favor",
    "pfv", "porfavor", "gentileza", "opa", "ola", "bom", "dia",
    "tarde", "noite", "voce", "voces", "vc", "vcs", "ai"
}


def get_number_variants(num_str: str) -> list[str]:
    """Retorna variações com e sem zeros à esquerda para números de hinos/partituras."""
    try:
        n = int(num_str)
        variants = {str(n), f"{n:02d}", f"{n:03d}", f"{n:04d}"}
        return list(variants)
    except ValueError:
        return [num_str]


def preprocess_search_query(text: str) -> str:
    """Desgruda números colados em letras (ex: harpa15 -> harpa 15, hino015 -> hino 015) e expande siglas."""
    if not text:
        return ""
    # Separa letras grudadas em números (ex: hino15 -> hino 15, ccb5 -> ccb 5)
    t = re.sub(r'([a-zA-ZÀ-ÿ]+)(\d+)', r'\1 \2', text)
    t = re.sub(r'(\d+)([a-zA-ZÀ-ÿ]+)', r'\1 \2', t)
    # Expande siglas comuns de hinários
    tokens = t.split()
    expanded = []
    for tok in tokens:
        tl = tok.lower()
        if tl == "hc":
            expanded.extend(["harpa", "crista"])
        elif tl == "h":
            expanded.append("hino")
        else:
            expanded.append(tok)
    return " ".join(expanded)


def generate_search_index_text(title: str, file_name: str, caption: str, channel_title: str) -> str:
    """Gera texto normalizado com índice enriquecido com variantes numéricas."""
    base = f"{title} {file_name} {caption} {channel_title}"
    norm = normalize_search_term(base)
    numbers = set(re.findall(r'\b\d+\b', norm))
    extra = []
    for num in numbers:
        extra.extend(get_number_variants(num))
    if extra:
        norm = f"{norm} {' '.join(set(extra))}"
    return norm


# Padrões de mensagens de bate-papo/perguntas para filtrar importação espúria de grupos de discussão
CHATTER_PATTERNS = [
    r"^(?:algu[eé]m(?:\s+a[ií])?\s+)?(?:tem|teria|consegue|passa|manda|compartilha|envia)\b",
    r"^quem\s+(?:tem|teria|pode|consegue|passa|manda|compartilha|envia|sabe)\b",
    r"\b(?:algu[eé]m|quem)\s+(?:tem|teria|consegue|sabe|manda|passa|compartilha|envia)\b",
    r"^onde\s+(?:acho|encontro|tem|consigo|baixo)\b",
    r"^como\s+(?:achar|encontrar|conseguir|baixar|fazer)\b",
    r"^preciso\s+d?[eoa]?s?\b",
    r"^procuro\b",
    r"^procurando\b",
    r"^por\s+favor\b",
    r"^pfv\b",
    r"^bom\s+dia\b",
    r"^boa\s+tarde\b",
    r"^boa\s+noite\b",
    r"^ol[aá]\b",
    r"^opa\b",
    r"^pessoal\b",
    r"^irm[aã]os?\b",
    r"^galera\b",
    r"^amigos?\b",
    r"^algu[eé]m\b",
    r"^vc\s+tem",
    r"^voc[eê]\s+tem",
    r"\?$",  # Termina com ponto de interrogação (pergunta de chat)
]
CHATTER_RE = re.compile(r"|".join(CHATTER_PATTERNS), re.IGNORECASE)


def clean_file_title(file_name: str, caption: str = "") -> str:
    """Gera um título legível e limpo para a partitura a partir do nome do arquivo ou legenda."""
    # Se houver legenda curta e clara, usa a primeira linha
    if caption:
        first_line = caption.strip().split("\n")[0].strip()
        first_line = re.sub(r"^[#🎼🎵📄📌\s*-]+", "", first_line).strip()
        if 4 <= len(first_line) <= 80:
            return first_line

    if not file_name:
        return "Partitura Musical"

    # Remove extensões conhecidas de música e documentos
    name = re.sub(r"\.(pdf|sib|enc|mscz|mus|xml|musicxml|zip|rar|7z|mp3|wav|ogg|m4a)$", "", file_name, flags=re.IGNORECASE)
    # Substitui underscores, hifens colados e pontos por espaços
    name = re.sub(r"[_+]+", " ", name)
    name = re.sub(r"\s*-\s*", " - ", name)
    name = re.sub(r"\s+", " ", name).strip()
    return name or file_name


def format_bytes(size: int) -> str:
    """Formata bytes em KB ou MB."""
    if not size or size <= 0:
        return ""
    if size < 1024:
        return f"{size} B"
    elif size < 1024 * 1024:
        return f"{size / 1024:.1f} KB"
    else:
        return f"{size / (1024 * 1024):.1f} MB"


class AcervoDatabase:
    """Gerenciador de Banco de Dados SQLite do Acervo Global de Partituras."""

    def __init__(self, db_path: Path = DB_PATH):
        self.db_path = db_path
        self._check_integrity()
        self._init_db()

    def _heal_db(self):
        """Auto-recupera e recria o banco limpo caso o arquivo SQLite esteja corrompido ou malformado."""
        logger.warning("[AcervoDatabase] Banco corrompido/malformado detectado! Limpando arquivos residuais para auto-recuperação...")
        for ext in ["", "-wal", "-shm", "-journal"]:
            p = Path(str(self.db_path) + ext)
            if p.exists():
                try:
                    p.unlink()
                except Exception as e_un:
                    logger.warning(f"Não foi possível remover {p}: {e_un}")

    def _check_integrity(self):
        """Checa se o arquivo existente está íntegro na inicialização."""
        if not self.db_path.exists():
            return
        is_corrupt = False
        try:
            conn = sqlite3.connect(str(self.db_path), timeout=5.0)
            cur = conn.cursor()
            cur.execute("PRAGMA integrity_check;")
            res = cur.fetchone()
            conn.close()
            if not res or res[0] != "ok":
                is_corrupt = True
        except Exception as e:
            logger.warning(f"[AcervoDatabase] Integrity check falhou ({e}). Auto-recuperando...")
            is_corrupt = True

        if is_corrupt:
            self._heal_db()

    def _get_connection(self):
        try:
            conn = sqlite3.connect(str(self.db_path), timeout=30.0)
            conn.row_factory = sqlite3.Row
            # Em containers/Discloud, DELETE mode é imune a descompassos com -wal e -shm
            conn.execute("PRAGMA journal_mode=DELETE;")
            conn.execute("PRAGMA synchronous=NORMAL;")
            return conn
        except sqlite3.DatabaseError as e:
            if "malformed" in str(e).lower() or "corrupt" in str(e).lower():
                logger.error(f"[AcervoDatabase] Conexão falhou por banco malformado ({e}). Executando auto-recuperação...")
                self._heal_db()
                self._init_db()
                conn = sqlite3.connect(str(self.db_path), timeout=30.0)
                conn.row_factory = sqlite3.Row
                conn.execute("PRAGMA journal_mode=DELETE;")
                conn.execute("PRAGMA synchronous=NORMAL;")
                return conn
            raise

    def _init_db(self):
        with self._get_connection() as conn:
            conn.execute("""
            CREATE TABLE IF NOT EXISTS acervo (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                file_id TEXT NOT NULL,
                file_unique_id TEXT,
                file_name TEXT,
                title TEXT NOT NULL,
                clean_title TEXT NOT NULL,
                file_type TEXT DEFAULT 'document',
                file_size INTEGER DEFAULT 0,
                file_size_str TEXT DEFAULT '',
                channel_id INTEGER NOT NULL,
                channel_title TEXT DEFAULT '',
                channel_username TEXT DEFAULT '',
                message_id INTEGER NOT NULL,
                post_url TEXT DEFAULT '',
                caption TEXT DEFAULT '',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(channel_id, message_id)
            );
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_acervo_clean_title ON acervo(clean_title);")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_acervo_channel ON acervo(channel_id);")

            # Tabela de progresso de varredura
            conn.execute("""
            CREATE TABLE IF NOT EXISTS varredura_progresso (
                channel_id INTEGER PRIMARY KEY,
                channel_title TEXT,
                last_scanned_id INTEGER DEFAULT 0,
                total_found INTEGER DEFAULT 0,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            """)
            conn.commit()

    def add_item(
        self,
        file_id: str,
        channel_id: int,
        message_id: int,
        file_name: str = "",
        title: str = "",
        caption: str = "",
        file_type: str = "document",
        file_size: int = 0,
        file_unique_id: str = "",
        channel_title: str = "",
        channel_username: str = "",
        post_url: str = ""
    ) -> bool:
        """Adiciona ou atualiza um item individual no acervo."""
        channel_id = normalize_chat_id(channel_id)
        if not title:
            title = clean_file_title(file_name, caption)

        size_str = format_bytes(file_size)
        clean_tit = generate_search_index_text(title, file_name, caption, channel_title)

        if not post_url:
            if channel_username:
                u = channel_username.lstrip("@")
                post_url = f"https://t.me/{u}/{message_id}"
            else:
                cid_str = str(channel_id)
                if cid_str.startswith("-100"):
                    num = cid_str[4:]
                    post_url = f"https://t.me/c/{num}/{message_id}"

        try:
            with self._get_connection() as conn:
                conn.execute("""
                INSERT INTO acervo (
                    file_id, file_unique_id, file_name, title, clean_title,
                    file_type, file_size, file_size_str, channel_id,
                    channel_title, channel_username, message_id, post_url, caption
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(channel_id, message_id) DO UPDATE SET
                    file_id=CASE WHEN excluded.file_id NOT LIKE 'link_%' THEN excluded.file_id ELSE acervo.file_id END,
                    file_name=excluded.file_name,
                    title=excluded.title,
                    clean_title=excluded.clean_title,
                    file_size=excluded.file_size,
                    file_size_str=excluded.file_size_str,
                    channel_title=excluded.channel_title,
                    post_url=excluded.post_url,
                    caption=excluded.caption;
                """, (
                    file_id, file_unique_id, file_name, title, clean_tit,
                    file_type, file_size, size_str, channel_id,
                    channel_title, channel_username, message_id, post_url, caption
                ))
                conn.commit()
            return True
        except Exception as e:
            logger.error(f"Erro ao salvar item no acervo: {e}")
            return False

    def add_items_batch(self, items: list[dict]) -> int:
        """Adiciona múltiplos itens ao acervo em uma única transação rápida."""
        if not items:
            return 0
        inserted_or_updated = 0
        try:
            with self._get_connection() as conn:
                for item in items:
                    channel_id = normalize_chat_id(item.get("channel_id", 0))
                    file_name = item.get("file_name", "")
                    caption = item.get("caption", "")
                    title = item.get("title") or clean_file_title(file_name, caption)
                    file_size = item.get("file_size", 0)
                    size_str = format_bytes(file_size)
                    channel_title = item.get("channel_title", "")
                    channel_username = item.get("channel_username", "")
                    message_id = item.get("message_id", 0)
                    file_id = item.get("file_id") or f"link_{channel_id}_{message_id}"
                    file_type = item.get("file_type", "document")
                    file_unique_id = item.get("file_unique_id", "")
                    post_url = item.get("post_url", "")

                    if not post_url:
                        if channel_username:
                            u = channel_username.lstrip("@")
                            post_url = f"https://t.me/{u}/{message_id}"
                        else:
                            cid_str = str(channel_id)
                            if cid_str.startswith("-100"):
                                num = cid_str[4:]
                                post_url = f"https://t.me/c/{num}/{message_id}"

                    clean_tit = generate_search_index_text(title, file_name, caption, channel_title)

                    conn.execute("""
                    INSERT INTO acervo (
                        file_id, file_unique_id, file_name, title, clean_title,
                        file_type, file_size, file_size_str, channel_id,
                        channel_title, channel_username, message_id, post_url, caption
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(channel_id, message_id) DO UPDATE SET
                        file_id=CASE WHEN excluded.file_id NOT LIKE 'link_%' THEN excluded.file_id ELSE acervo.file_id END,
                        file_name=excluded.file_name,
                        title=excluded.title,
                        clean_title=excluded.clean_title,
                        file_size=excluded.file_size,
                        file_size_str=excluded.file_size_str,
                        channel_title=excluded.channel_title,
                        post_url=excluded.post_url,
                        caption=excluded.caption;
                    """, (
                        file_id, file_unique_id, file_name, title, clean_tit,
                        file_type, file_size, size_str, channel_id,
                        channel_title, channel_username, message_id, post_url, caption
                    ))
                    inserted_or_updated += 1
                conn.commit()
            return inserted_or_updated
        except Exception as e:
            if "malformed" in str(e).lower() or "corrupt" in str(e).lower():
                logger.error(f"[AcervoDatabase] Erro malformed durante inserção de lote: {e}. Auto-recriando banco...")
                self._heal_db()
                self._init_db()
                try:
                    with self._get_connection() as conn:
                        retry_count = 0
                        for item in items:
                            channel_id = normalize_chat_id(item.get("channel_id", 0))
                            file_name = item.get("file_name", "")
                            caption = item.get("caption", "")
                            title = item.get("title") or clean_file_title(file_name, caption)
                            file_size = item.get("file_size", 0)
                            size_str = format_bytes(file_size)
                            channel_title = item.get("channel_title", "")
                            channel_username = item.get("channel_username", "")
                            message_id = item.get("message_id", 0)
                            file_id = item.get("file_id") or f"link_{channel_id}_{message_id}"
                            file_type = item.get("file_type", "document")
                            file_unique_id = item.get("file_unique_id", "")
                            post_url = item.get("post_url", "")

                            if not post_url:
                                if channel_username:
                                    u = channel_username.lstrip("@")
                                    post_url = f"https://t.me/{u}/{message_id}"
                                else:
                                    cid_str = str(channel_id)
                                    if cid_str.startswith("-100"):
                                        num = cid_str[4:]
                                        post_url = f"https://t.me/c/{num}/{message_id}"

                            clean_tit = generate_search_index_text(title, file_name, caption, channel_title)

                            conn.execute("""
                            INSERT INTO acervo (
                                file_id, file_unique_id, file_name, title, clean_title,
                                file_type, file_size, file_size_str, channel_id,
                                channel_title, channel_username, message_id, post_url, caption
                            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                            ON CONFLICT(channel_id, message_id) DO UPDATE SET
                                file_id=CASE WHEN excluded.file_id NOT LIKE 'link_%' THEN excluded.file_id ELSE acervo.file_id END,
                                file_name=excluded.file_name,
                                title=excluded.title,
                                clean_title=excluded.clean_title,
                                file_size=excluded.file_size,
                                file_size_str=excluded.file_size_str,
                                channel_title=excluded.channel_title,
                                post_url=excluded.post_url,
                                caption=excluded.caption;
                            """, (
                                file_id, file_unique_id, file_name, title, clean_tit,
                                file_type, file_size, size_str, channel_id,
                                channel_title, channel_username, message_id, post_url, caption
                            ))
                            retry_count += 1
                        conn.commit()
                    return retry_count
                except Exception as e_retry:
                    logger.error(f"[AcervoDatabase] Erro no retry do lote: {e_retry}")
            logger.error(f"Erro no lote de itens do acervo: {e}")
            return inserted_or_updated

    def search(self, query: str = "", limit: int = 30, offset: int = 0) -> list[dict]:
        """Busca itens no acervo usando casamento inteligente de termos com paginação rápida e ranqueamento por relevância."""
        preprocessed = preprocess_search_query(query)
        q_clean = normalize_search_term(preprocessed)
        raw_tokens = [t for t in q_clean.split() if len(t) >= 1]

        try:
            with self._get_connection() as conn:
                if not raw_tokens:
                    cursor = conn.execute("""
                    SELECT id, file_id, file_name, title, file_type, file_size_str,
                           channel_id, channel_title, channel_username, message_id, post_url, caption
                    FROM acervo
                    ORDER BY id DESC
                    LIMIT ? OFFSET ?
                    """, (limit, offset))
                    return [dict(r) for r in cursor.fetchall()]

                # Filtra stopwords para encontrar os termos essenciais
                filtered_tokens = [t for t in raw_tokens if t not in SEARCH_STOPWORDS]
                if not filtered_tokens:
                    filtered_tokens = raw_tokens

                # Constrói grupos de tokens (números com variantes 015/15 e sinônimos de instrumentos)
                token_groups = []
                for t in filtered_tokens:
                    if t.isdigit():
                        token_groups.append(get_number_variants(t))
                    elif t in INSTRUMENT_ALIASES:
                        token_groups.append(INSTRUMENT_ALIASES[t])
                    else:
                        token_groups.append([t])

                # Monta cláusula WHERE para os grupos
                where_clauses = []
                params = []
                for group in token_groups:
                    sub_clauses = []
                    for term in group:
                        sub_clauses.append("(clean_title LIKE ? OR lower(title) LIKE ? OR lower(file_name) LIKE ?)")
                        p = f"%{term}%"
                        params.extend([p, p, p])
                    where_clauses.append(f"({' OR '.join(sub_clauses)})")

                # Tier 1 & 2: AND entre todos os grupos de termos
                fetch_limit = max(100, (offset + limit) * 2)
                sql_and = f"""
                SELECT id, file_id, file_name, title, clean_title, file_type, file_size_str,
                       channel_id, channel_title, channel_username, message_id, post_url, caption
                FROM acervo
                WHERE {' AND '.join(where_clauses)}
                ORDER BY id DESC
                LIMIT ?
                """
                cursor = conn.execute(sql_and, params + [fetch_limit])
                and_results = [dict(r) for r in cursor.fetchall()]

                # Tier 3: Se houver menos que fetch_limit resultados e houver mais de 1 grupo, busca complementar por OR
                collected_ids = {r["id"] for r in and_results}
                or_results = []
                if len(and_results) < (offset + limit) and len(token_groups) > 1:
                    where_or = " OR ".join(where_clauses)
                    sql_or = f"""
                    SELECT id, file_id, file_name, title, clean_title, file_type, file_size_str,
                           channel_id, channel_title, channel_username, message_id, post_url, caption
                    FROM acervo
                    WHERE {where_or}
                    ORDER BY id DESC
                    LIMIT ?
                    """
                    cursor = conn.execute(sql_or, params + [fetch_limit])
                    for r in cursor.fetchall():
                        rd = dict(r)
                        if rd["id"] not in collected_ids:
                            or_results.append(rd)
                            collected_ids.add(rd["id"])

                all_candidates = and_results + or_results

                # Ranqueamento inteligente por relevância
                def calculate_score(item: dict) -> float:
                    score = 0.0
                    c_title = item.get("clean_title") or ""
                    tit_lower = (item.get("title") or "").lower()
                    words_set = set(c_title.split())
                    target_numbers = set(re.findall(r'\b\d+\b', c_title))

                    # 1. Correspondência exata da frase completa (com limite de palavra para evitar falso positivo de número)
                    if q_clean and re.search(rf'\b{re.escape(q_clean)}\b', c_title):
                        score += 200.0
                    elif q_clean and q_clean in c_title:
                        score += 80.0
                    if q_clean and c_title.startswith(q_clean):
                        score += 60.0

                    # 2. Avaliação de correspondência por grupo de termos
                    for group in token_groups:
                        is_num_group = any(t.isdigit() for t in group)
                        if is_num_group:
                            # Grande pontuação quando o número de hino bate exatamente (ex: 15 ou 015)
                            if any(num in target_numbers for num in group):
                                score += 150.0
                            elif any(num in c_title for num in group):
                                score += 10.0
                        else:
                            matched_in_group = False
                            for term in group:
                                if term in words_set:
                                    score += 50.0
                                    matched_in_group = True
                                    break
                                elif term in tit_lower:
                                    score += 40.0
                                    matched_in_group = True
                                    break
                                elif term in c_title:
                                    score += 20.0
                                    matched_in_group = True
                                    break

                    # 3. Preferência por documentos (PDF, Sibelius, etc) sobre áudios
                    if item.get("file_type") == "document":
                        score += 15.0

                    return score

                all_candidates.sort(key=lambda x: (calculate_score(x), x["id"]), reverse=True)

                final_results = []
                for item in all_candidates[offset:offset + limit]:
                    final_results.append({k: v for k, v in item.items() if k != "clean_title"})
                return final_results
        except Exception as e:
            logger.error(f"Erro na busca do acervo: {e}")
            return []

    def get_item(self, item_id: int) -> dict:
        """Obtém os detalhes de um item específico do acervo pelo ID."""
        try:
            with self._get_connection() as conn:
                conn.row_factory = sqlite3.Row
                row = conn.execute("""
                    SELECT id, channel_id, channel_title, message_id, file_id, file_unique_id, 
                           file_name, file_size_str, file_type, mime_type, title, post_url 
                    FROM acervo WHERE id = ?;
                """, (item_id,)).fetchone()
                if row:
                    return dict(row)
                return None
        except Exception as e:
            logger.error(f"Erro ao obter item {item_id} do acervo: {e}")
            return None

    def get_channels_summary(self) -> list:
        """Retorna resumo de todos os canais que possuem partituras no acervo."""
        try:
            with self._get_connection() as conn:
                conn.row_factory = sqlite3.Row
                rows = conn.execute("""
                    SELECT channel_id, channel_title, channel_username, COUNT(*) as qtd
                    FROM acervo
                    WHERE channel_id IS NOT NULL AND channel_id != 0
                    GROUP BY channel_id
                    ORDER BY qtd DESC;
                """).fetchall()
                return [dict(r) for r in rows]
        except Exception as e:
            logger.error(f"Erro ao obter canais do acervo: {e}")
            return []

    def get_stats(self) -> dict:
        """Retorna estatísticas gerais do acervo global."""
        try:
            with self._get_connection() as conn:
                total_files = conn.execute("SELECT COUNT(*) FROM acervo;").fetchone()[0]
                total_channels = conn.execute("SELECT COUNT(DISTINCT channel_id) FROM acervo;").fetchone()[0]
                by_type = conn.execute("SELECT file_type, COUNT(*) FROM acervo GROUP BY file_type;").fetchall()
                top_channels = conn.execute("""
                SELECT channel_title, channel_id, COUNT(*) as qtd
                FROM acervo
                GROUP BY channel_id
                ORDER BY qtd DESC
                LIMIT 8;
                """).fetchall()

                return {
                    "total_files": total_files,
                    "total_channels": total_channels,
                    "by_type": {r[0]: r[1] for r in by_type},
                    "top_channels": [dict(r) for r in top_channels]
                }
        except Exception as e:
            if "malformed" in str(e).lower() or "corrupt" in str(e).lower():
                self._heal_db()
                self._init_db()
            logger.error(f"Erro ao obter estatísticas do acervo: {e}")
            return {"total_files": 0, "total_channels": 0, "by_type": {}, "top_channels": []}

    def update_scan_progress(self, channel_id: int, channel_title: str, last_scanned_id: int, total_found: int):
        try:
            with self._get_connection() as conn:
                conn.execute("""
                INSERT INTO varredura_progresso (channel_id, channel_title, last_scanned_id, total_found, updated_at)
                VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(channel_id) DO UPDATE SET
                    last_scanned_id=excluded.last_scanned_id,
                    total_found=excluded.total_found,
                    updated_at=CURRENT_TIMESTAMP;
                """, (channel_id, channel_title, last_scanned_id, total_found))
                conn.commit()
        except Exception as e:
            logger.error(f"Erro ao salvar progresso de varredura: {e}")

    def clear_channel(self, channel_id: int) -> int:
        """Remove todos os itens de um canal específico."""
        try:
            cid = normalize_chat_id(channel_id)
            with self._get_connection() as conn:
                res = conn.execute("DELETE FROM acervo WHERE channel_id = ?;", (cid,))
                conn.commit()
                return res.rowcount
        except Exception as e:
            logger.error(f"Erro ao limpar canal {channel_id}: {e}")
            return 0

    def clear_all(self) -> int:
        """Remove todos os itens do acervo de forma limpa."""
        try:
            with self._get_connection() as conn:
                res = conn.execute("DELETE FROM acervo;")
                conn.execute("DELETE FROM varredura_progresso;")
                conn.commit()
                return res.rowcount
        except Exception as e:
            logger.error(f"Erro ao limpar todo o acervo: {e}")
            return 0

    def purge_text_chatter(self) -> int:
        """
        Varre o acervo e remove mensagens espúrias de bate-papo de grupos
        (ex: 'alguém tem método de trombone?', 'quem tem o hino 15?', etc.)
        que foram indexadas erroneamente como partituras.
        Mantém todas as partituras e áudios legítimos 100% intactos.
        """
        deleted_count = 0
        try:
            with self._get_connection() as conn:
                # Mensagens de texto erroneamente importadas possuem file_id iniciado por 'link_' e tamanho 0
                cursor = conn.execute("""
                    SELECT id, title, file_name, caption
                    FROM acervo
                    WHERE file_id LIKE 'link_%' AND (file_size = 0 OR file_size IS NULL);
                """)
                rows = cursor.fetchall()
                to_delete = []
                for row in rows:
                    item_id = row[0]
                    t = (row[1] or "").strip()
                    cap = (row[3] or "").strip()
                    if CHATTER_RE.search(t) or t.endswith("?") or (cap and CHATTER_RE.search(cap)):
                        to_delete.append(item_id)

                if to_delete:
                    for i in range(0, len(to_delete), 500):
                        batch = to_delete[i:i+500]
                        placeholders = ",".join("?" for _ in batch)
                        conn.execute(f"DELETE FROM acervo WHERE id IN ({placeholders});", batch)
                    conn.commit()
                    deleted_count = len(to_delete)
                    logger.info(f"[Acervo] Limpeza concluída: {deleted_count} mensagens de texto removidas do acervo.")
            return deleted_count
        except Exception as e:
            if "malformed" in str(e).lower() or "corrupt" in str(e).lower():
                self._heal_db()
                self._init_db()
            logger.error(f"Erro ao purgar textos espúrios do acervo: {e}")
            return 0


# Instância global do banco de dados do acervo
acervo_db = AcervoDatabase()

