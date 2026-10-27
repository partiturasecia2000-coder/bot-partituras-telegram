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
        self._init_db()

    def _get_connection(self):
        conn = sqlite3.connect(str(self.db_path), timeout=30.0)
        conn.row_factory = sqlite3.Row
        # Habilita WAL mode para alta performance e concorrência sem bloqueio
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA synchronous=NORMAL;")
        return conn

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
            logger.error(f"Erro ao purgar textos espúrios do acervo: {e}")
            return 0


# Instância global do banco de dados do acervo
acervo_db = AcervoDatabase()


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
        for item in results_data:
            item_id = str(item["id"])
            title = item["title"]
            file_id = item["file_id"]
            file_type = item.get("file_type", "document")
            chan_title = item.get("channel_title") or "Canal de Partituras"
            file_size_str = item.get("file_size_str", "")
            post_url = item.get("post_url", "")
            file_name = item.get("file_name", "partitura.pdf")

            desc_parts = [f"📢 {chan_title[:24]}"]
            if file_size_str:
                desc_parts.append(file_size_str)
            description = " • ".join(desc_parts)

            caption = (
                f"🎼 <b>{html.escape(title)}</b>\n"
                f"📁 <b>Arquivo:</b> <code>{html.escape(file_name)}</code>\n"
                f"📢 <b>Origem:</b> {html.escape(chan_title)}\n\n"
                f"🎵 <i>Enviado via @{bot_username}</i>"
            )

            buttons = []
            if post_url:
                buttons.append([InlineKeyboardButton(f"📢 Abrir no {chan_title[:20]}", url=post_url)])
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
                            title=title,
                            document_file_id=file_id,
                            description=description,
                            caption=caption,
                            parse_mode=ParseMode.HTML,
                            reply_markup=markup
                        )
                    )
            else:
                # Item indexado por link/histórico: envia card elegante com link direto ao post
                card_text = (
                    f"🎼 <b>{html.escape(title)}</b>\n"
                    f"📁 <b>Arquivo:</b> <code>{html.escape(file_name)}</code>\n"
                    f"📢 <b>Canal:</b> {html.escape(chan_title)}\n\n"
                    f"<i>Toque no botão abaixo para baixar ou visualizar no canal:</i>"
                )
                inline_results.append(
                    InlineQueryResultArticle(
                        id=f"art_{item_id}",
                        title=title,
                        description=f"📢 {chan_title} • Toque para abrir no canal",
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

    autodel = cfg.get("acervo_auto_delete_seconds", 0)
    if autodel == 0:
        autodel_label = "Desativado (Permanente) 🟢"
    elif autodel == 30:
        autodel_label = "30s (Efêmera ⚡)"
    elif autodel == 60:
        autodel_label = "1 min ⏳"
    elif autodel == 120:
        autodel_label = "2 min ⏳"
    elif autodel == 300:
        autodel_label = "5 min ⏳"
    elif autodel == 600:
        autodel_label = "10 min ⏳"
    else:
        autodel_label = f"{autodel}s ⏳"

    lines = [
        "🎼 ══════════════════════ 🎼",
        "   <b>ACERVO GLOBAL DE PARTITURAS</b>",
        "🎼 ══════════════════════ 🎼\n",
        f"📊 <b>Total de Partituras Indexadas:</b> <code>{total_files}</code>",
        f"📄 <b>Documentos / PDFs:</b> <code>{docs_count}</code>",
        f"🎵 <b>Áudios / Playbacks:</b> <code>{aud_count}</code>",
        f"📢 <b>Canais no Acervo:</b> <code>{total_chans}</code> (de {len(linked_c)} vinculados)",
        f"🤖 <b>Auto-Resposta no Grupo:</b> <code>{auto_reply_badge}</code>",
        f"⏳ <b>Auto-Apagar / Efêmera no Grupo:</b> <code>{autodel_label}</code>\n"
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

    kb = [
        [InlineKeyboardButton(f"🤖 Auto-Resposta: {auto_reply_badge}", callback_data="acervo:toggle:autoreply")],
        [InlineKeyboardButton(f"⏳ Auto-Apagar no Grupo: {autodel_label}", callback_data="acervo:cycle_autodel")],
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
