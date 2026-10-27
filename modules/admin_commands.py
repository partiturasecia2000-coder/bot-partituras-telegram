import re
import html
import io
import json
import logging
from datetime import datetime, timedelta, timezone
from telegram import Update, ChatPermissions, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode, ChatMemberStatus
from telegram.ext import ContextTypes
from config import (
    load_config,
    save_config,
    add_linked_group,
    remove_linked_group,
    add_linked_channel,
    remove_linked_channel,
    get_all_linked_chats
)
from modules.utils import (
    AdminCache,
    safe_delete_message,
    schedule_message_deletion,
    safe_reply,
    smart_send_message,
    smart_send_photo,
    parse_rich_buttons,
    build_rich_buttons_markup,
    convert_rich_text
)
from modules.logger_channel import send_mod_log

logger = logging.getLogger("AdminCommands")

def parse_flexible_time(args: list[str]) -> tuple[timedelta | None, str, str]:
    """
    Analisa argumentos para extrair tempo flexível (ex: 10m, 30m, 2h, 1d, 7d, ou número solto) e motivo.
    Formatos aceitos:
      - '10m', '15m', '30m' -> Minutos
      - '1h', '2h', '12h' -> Horas
      - '1d', '3d', '7d', '30d' -> Dias
      - '1w' -> Semanas
      - '30' (só número) -> Minutos
    Retorna: (timedelta ou None, texto_amigavel, motivo)
    """
    if not args:
        return None, "", ""

    first = args[0].strip().lower()
    match = re.match(r"^(\d+)([mhdsw]?)$", first)
    if not match:
        return None, "", " ".join(args)

    val = int(match.group(1))
    unit = match.group(2) or "m"

    reason = " ".join(args[1:]).strip() if len(args) > 1 else ""

    if unit == "m":
        return timedelta(minutes=val), f"{val} minuto(s)", reason
    elif unit == "h":
        return timedelta(hours=val), f"{val} hora(s)", reason
    elif unit == "d":
        return timedelta(days=val), f"{val} dia(s)", reason
    elif unit == "w":
        return timedelta(weeks=val), f"{val} semana(s)", reason
    elif unit == "s":
        return timedelta(seconds=val), f"{val} segundo(s)", reason

    return None, "", " ".join(args)

HELP_CATEGORIES = {
    "main": {
        "title": "📚 <b>CENTRAL DE AJUDA & GUIA DE COMANDOS</b>",
        "text": (
            "Olá! Escolha uma das categorias abaixo para ver os detalhes, sintaxe e exemplos de cada recurso do bot:\n\n"
            "🛡️ <b>Moderação:</b> Bans, Mutes, Kicks, Warns e Limpeza\n"
            "📢 <b>Transmissões:</b> Envio pelo privado (/falar), anúncios e pins\n"
            "🤖 <b>Auto-Respostas:</b> Filtros automáticos, palavras-chave e Regex\n"
            "🧩 <b>Segurança & Captcha:</b> Verificação anti-bot, proteção de links e flood\n"
            "⚙️ <b>Gestão & Sistema:</b> Painel /config, logs, vincular grupo e equipe\n\n"
            "<i>💡 Clique nos botões abaixo para navegar:</i>"
        ),
        "buttons": [
            [InlineKeyboardButton("🛡️ Moderação & Punições", callback_data="help:cat:mod"),
             InlineKeyboardButton("📢 Transmissões (/falar)", callback_data="help:cat:trans")],
            [InlineKeyboardButton("🤖 Auto-Respostas & Regex", callback_data="help:cat:auto"),
             InlineKeyboardButton("🧩 Segurança & Captcha", callback_data="help:cat:sec")],
            [InlineKeyboardButton("🌹 Recursos Estilo Rose", callback_data="help:cat:rose"),
             InlineKeyboardButton("🎓 Central de Tutoriais", callback_data="tut:main")],
            [InlineKeyboardButton("⚙️ Gestão & Sistema", callback_data="help:cat:sys"),
             InlineKeyboardButton("📋 Todos os Comandos", callback_data="help:cat:all")],
            [InlineKeyboardButton("ℹ️ Versão & Sobre o Bot", callback_data="help:cat:about")]
        ]
    },
    "mod": {
        "title": "🛡️ <b>MODERAÇÃO & PUNIÇÕES</b>",
        "text": (
            "Comandos para manter a ordem e aplicar regras:\n\n"
            "• <code>/ban [tempo] [motivo]</code> (em resposta)\n"
            "  Bane o membro. O tempo é flexível:\n"
            "  <i>Exemplos:</i> <code>/ban 1d Spam</code> | <code>/ban 2h</code> | <code>/ban</code> (permanente)\n\n"
            "• <code>/kick [motivo]</code> (em resposta)\n"
            "  Remove o membro do grupo sem bloqueio definitivo.\n\n"
            "• <code>/mute [tempo] [motivo]</code> (em resposta)\n"
            "  Silencia o membro por tempo flexível (padrão: 15 min).\n"
            "  <i>Exemplos:</i> <code>/mute 30m Flood</code> | <code>/mute 2h</code> | <code>/mute 1d</code>\n\n"
            "• <code>/unmute</code> (em resposta)\n"
            "  Devolve permissão de fala ao membro silenciado imediatamente.\n\n"
            "• <code>/warn [motivo]</code> (em resposta)\n"
            "  Aplica advertência (3 advertências = banimento automático).\n\n"
            "• <code>/unwarn</code> (em resposta)\n"
            "  Remove 1 advertência do membro respondido.\n\n"
            "• <code>/warns</code>\n"
            "  Exibe a contagem de advertências ativas do usuário.\n\n"
            "• <code>/limpar [quantidade]</code>\n"
            "  Apaga as últimas mensagens do chat em lote (Ex: <code>/limpar 20</code>)."
        ),
        "buttons": [
            [InlineKeyboardButton("◀ Voltar ao Menu de Ajuda", callback_data="help:cat:main")]
        ]
    },
    "trans": {
        "title": "📢 <b>TRANSMISSÕES, CANAIS & MENSAGENS</b>",
        "text": (
            "• <code>/comunicado</code> ou <code>/transmissao</code>\n"
            "  <b>Guia Visual Passo a Passo:</b> Seleciona destinos, formata texto, anexa Foto ou Vídeo, adiciona botões, define agendamento futuro e distribuição suave (delay anti-flood) com prévia em tempo real!\n\n"
            "• <code>/agendados</code> ou <code>/transmissoes</code>\n"
            "  Consulta e gerencia a fila de transmissões agendadas pendentes.\n\n"
            "• <code>/canal &lt;texto&gt;</code> ou <code>/postar &lt;texto&gt;</code>\n"
            "  Posta diretamente no seu <b>Canal vinculado</b> com TODAS as formatações (negrito Ctrl+B, artigos expansíveis &gt;&gt;, botões em grade e mídias)!\n\n"
            "• <code>/canal pin &lt;texto&gt;</code>\n"
            "  Posta no canal e <b>fixa no topo automaticamente</b>.\n\n"
            "• <code>/falar &lt;texto&gt;</code> ou <code>/say &lt;texto&gt;</code>\n"
            "  <b>No privado:</b> Transmite o texto diretamente para o grupo principal ou específico (<code>/falar &lt;id&gt; &lt;texto&gt;</code>).\n"
            "  <i>Com Mídias:</i> Responda a Foto, PDF ou Áudio no privado com <code>/falar</code> para enviar ao grupo!\n\n"
            "• <code>/transmitir &lt;texto&gt;</code> ou <code>/broadcast</code>\n"
            "  Transmite a postagem para <b>TODOS os grupos e canais vinculados</b> de uma vez só!\n\n"
            "• <code>/grupos</code> ou <code>/canais</code>\n"
            "  Lista todos os grupos e canais vinculados com IDs e status.\n\n"
            "• <code>/setcanal @seucanal</code>\n"
            "  Vincula um canal para postagens automáticas e manuais.\n\n"
            "• <code>/anunciar &lt;texto&gt;</code>\n"
            "  Envia um comunicado oficial e <b>fixa automaticamente no topo do grupo</b>!\n\n"
            "• <code>/pin</code> / <code>/unpin</code> (em resposta)\n"
            "  Fixa ou desfixa a mensagem respondida no topo."
        ),
        "buttons": [
            [InlineKeyboardButton("◀ Voltar ao Menu de Ajuda", callback_data="help:cat:main")]
        ]
    },
    "auto": {
        "title": "🤖 <b>AUTO-RESPOSTAS & REGEX</b>",
        "text": (
            "Respostas automáticas inteligentes por palavras-chave e expressões regulares:\n\n"
            "• <code>/filtros</code>\n"
            "  Lista todas as respostas cadastradas com seus IDs, gatilhos e status.\n\n"
            "• <code>/filtro &lt;gatilho&gt; &lt;resposta&gt;</code>\n"
            "  Cria uma resposta automática rápida no grupo.\n"
            "  <i>Dica:</i> Você pode responder a uma partitura, foto ou texto com <code>/filtro &lt;gatilho&gt;</code> para salvar aquela mídia como resposta!\n\n"
            "• <code>/delfiltro &lt;id ou gatilho&gt;</code>\n"
            "  Remove um filtro automático existente.\n\n"
            "<i>💡 Para editar respostas avançadas com botões e Regex, use o painel /config.</i>"
        ),
        "buttons": [
            [InlineKeyboardButton("◀ Voltar ao Menu de Ajuda", callback_data="help:cat:main")]
        ]
    },
    "sec": {
        "title": "🧩 <b>SEGURANÇA, CAPTCHA & ENTRADA</b>",
        "text": (
            "Sistemas de proteção ativa para blindar o grupo:\n\n"
            "• <b>Anti-Bot / CAPTCHA Musical:</b>\n"
            "  Novos membros são silenciados até apertar <code>[ 🎵 Sou Humano ]</code>. Se não confirmarem no tempo limite, são expulsos automaticamente.\n\n"
            "• <b>Filtro Anti-Repetição em Horas:</b>\n"
            "  Detecta mensagens ou mídias idênticas enviadas em um intervalo configurável (ex: 2h, 6h, 24h) e apaga automaticamente.\n\n"
            "• <b>Auto-Aprovação de Entrada (Join Requests):</b>\n"
            "  Aprova solicitações de entrada automaticamente e pode enviar uma mensagem acolhedora no privado do novo membro.\n\n"
            "• <b>Anti-Spam & Anti-Flood:</b>\n"
            "  Bloqueia links externos, convites de outros canais do Telegram, encaminhamentos e excesso de mensagens por segundo."
        ),
        "buttons": [
            [InlineKeyboardButton("◀ Voltar ao Menu de Ajuda", callback_data="help:cat:main")]
        ]
    },
    "sys": {
        "title": "⚙️ <b>GESTÃO, AUDITORIA & SISTEMA</b>",
        "text": (
            "Comandos de administração e informações:\n\n"
            "• <code>/config</code>\n"
            "  Painel Visual Interativo com botões para ativar/desativar qualquer módulo em tempo real.\n\n"
            "• <code>/status</code>\n"
            "  Resumo visual de todas as proteções ativas no grupo.\n\n"
            "• <code>/chatinfo</code>\n"
            "  Exibe dados do chat, número de membros e o <b>Chat ID</b>.\n\n"
            "• <code>/setgrupo</code>\n"
            "  Vincula o grupo atual como principal para o <code>/falar</code>.\n\n"
            "• <code>/setlog &lt;id_do_canal&gt;</code>\n"
            "  Define o canal privado onde todas as punições e ações serão registradas.\n\n"
            "• <code>/staff</code>\n"
            "  Lista os administradores e criador do grupo.\n\n"
            "• <code>/info</code> (ou em resposta)\n"
            "  Ficha completa do usuário (ID, @username, advertências, cargo).\n\n"
            "• <code>/regras</code>\n"
            "  Exibe as normas oficiais do grupo.\n\n"
            "• <code>/setregras</code>\n"
            "  Define ou edita as regras oficiais do grupo (ou responda a uma mensagem).\n\n"
            "• <code>/backup</code>\n"
            "  Envia o arquivo <code>config.json</code> para você salvar todas as suas configurações.\n\n"
            "• <code>/restaurar</code>\n"
            "  Restaura todas as configurações enviando o arquivo <code>config.json</code> de backup."
        ),
        "buttons": [
            [InlineKeyboardButton("◀ Voltar ao Menu de Ajuda", callback_data="help:cat:main")]
        ]
    },
    "all": {
        "title": "📋 <b>LISTA GERAL DE COMANDOS</b>",
        "text": (
            "<b>Comandos Gerais:</b>\n"
            "• <code>/regras</code> - Exibe as regras do grupo\n"
            "• <code>/info</code> - Consulta ficha do usuário\n"
            "• <code>/warns</code> - Consulta advertências\n"
            "• <code>/staff</code> - Lista equipe de moderação\n"
            "• <code>/ajuda</code> - Abre esta central de ajuda\n\n"
            "<b>Comandos de Administrador:</b>\n"
            "• <code>/config</code> - Painel Interativo\n"
            "• <code>/status</code> - Resumo de proteções\n"
            "• <code>/chatinfo</code> - Exibe ID e dados do chat\n"
            "• <code>/setgrupo</code> - Vincula grupo principal\n"
            "• <code>/falar &lt;texto&gt;</code> - Transmite no grupo como bot\n"
            "• <code>/anunciar &lt;texto&gt;</code> - Transmite e fixa no topo\n"
            "• <code>/backup</code> - Baixa backup de dados e configurações\n"
            "• <code>/restaurar</code> - Restaura configurações via arquivo .json\n"
            "• <code>/setlog &lt;id&gt;</code> - Conecta canal de logs\n"
            "• <code>/filtros</code> - Lista respostas automáticas\n"
            "• <code>/filtro &lt;g&gt; &lt;r&gt;</code> - Cria resposta rápida\n"
            "• <code>/delfiltro &lt;id&gt;</code> - Remove filtro\n"
            "• <code>/save &lt;nome&gt; &lt;txt&gt;</code> - Salva nota (#hashtag)\n"
            "• <code>/notas</code> - Lista todas as notas salvas\n"
            "• <code>/get &lt;nome&gt;</code> - Envia a nota salva\n"
            "• <code>/clear &lt;nome&gt;</code> - Apaga uma nota\n"
            "• <code>/lock &lt;tipo&gt;</code> - Bloqueia mídia específica\n"
            "• <code>/unlock &lt;tipo&gt;</code> - Libera mídia\n"
            "• <code>/locks</code> - Tabela de bloqueios de mídia\n"
            "• <code>/noturno on/off</code> - Silêncio programado noturno\n"
            "• <code>/report</code> - Denuncia mensagem à moderação\n"
            "• <code>/tutorial</code> - Central de tutoriais passo a passo\n"
            "• <code>/ban [tempo] [motivo]</code> - Bane usuário\n"
            "• <code>/kick [motivo]</code> - Remove usuário\n"
            "• <code>/mute [tempo] [motivo]</code> - Silencia temporariamente\n"
            "• <code>/unmute</code> - Desmuta usuário\n"
            "• <code>/warn [motivo]</code> - Aplica advertência\n"
            "• <code>/unwarn</code> - Remove advertência\n"
            "• <code>/pin</code> - Fixa mensagem\n"
            "• <code>/unpin</code> - Desfixa mensagem\n"
            "• <code>/limpar [qtd]</code> - Limpa mensagens em lote"
        ),
        "buttons": [
            [InlineKeyboardButton("◀ Voltar ao Menu de Ajuda", callback_data="help:cat:main")]
        ]
    },
    "rose": {
        "title": "🌹 <b>RECURSOS INSPIRADOS NO MISS ROSE BOT</b>",
        "text": (
            "Ferramentas consagradas para gerenciamento ágil do grupo:\n\n"
            "📌 <b>Sistema de Notas & Hashtags:</b>\n"
            "• <code>/save &lt;nome&gt; &lt;conteúdo&gt;</code>\n"
            "  Salva uma nota com texto ou botões.\n"
            "  <i>Dica com Mídia:</i> Responda a uma foto, PDF de partitura ou áudio com <code>/save &lt;nome&gt;</code> para salvar aquele arquivo!\n"
            "• <code>#nome</code> ou <code>/get &lt;nome&gt;</code>\n"
            "  Envia a nota salva na hora.\n"
            "• <code>/notas</code> ou <code>/notes</code>\n"
            "  Exibe a lista de todas as notas salvas.\n"
            "• <code>/clear &lt;nome&gt;</code>\n"
            "  Apaga a nota selecionada.\n\n"
            "🔒 <b>Bloqueios Específicos (/locks):</b>\n"
            "• <code>/lock &lt;tipo&gt;</code> - Bloqueia mídia para membros comuns\n"
            "  <i>Tipos:</i> <code>sticker</code>, <code>audio</code>, <code>voice</code>, <code>video</code>, <code>gif</code>, <code>doc</code>, <code>forward</code>, <code>contact</code>, <code>poll</code>\n"
            "• <code>/unlock &lt;tipo&gt;</code> - Libera a mídia bloqueada\n"
            "• <code>/locks</code> - Exibe tabela com tudo o que está 🔒 Bloqueado ou 🔓 Liberado\n\n"
            "🌙 <b>Silêncio Noturno Programado:</b>\n"
            "• <code>/noturno on</code> (ou <code>/noturno on 23:00-07:00</code>)\n"
            "• <code>/noturno off</code>\n"
            "• <code>/noturno avisos [on/off]</code> - Avisos automáticos de início e fim no grupo\n"
            "• <code>/noturno testestart</code> e <code>testeend</code> - Testa os avisos na hora\n\n"
            "🚨 <b>Denúncia de Membros:</b>\n"
            "• <code>/report [motivo]</code> (em resposta à mensagem)\n"
            "  Alerta imediatamente a equipe e o canal Log Maestro!"
        ),
        "buttons": [
            [InlineKeyboardButton("🎓 Ver Tutorial do Rose", callback_data="tut:notes"),
             InlineKeyboardButton("◀ Voltar", callback_data="help:cat:main")]
        ]
    },
    "about": {
        "title": "ℹ️ <b>MAESTRO BOT ENTERPRISE — v2.5.0</b>",
        "text": (
            "🤖 <b>Sistema Autônomo e Inteligente de Gestão para Telegram</b>\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "<b>Versão do Sistema:</b> <code>v2.5.0 Enterprise Release</code>\n"
            "<b>Ambiente:</b> Python 3.14 + PTB 22.8 + APScheduler\n"
            "<b>Hospedagem:</b> 100% Compatível com Discloud & VPS Linux/Windows\n\n"
            "🚀 <b>Visão Geral dos Recursos:</b>\n\n"
            "📢 <b>Multi-Grupos & Canais:</b>\n"
            "• Vincule infinitos grupos e canais simultaneamente.\n"
            "• Comandos <code>/falar</code>, <code>/canal</code> (ou <code>/postar</code>) e <code>/transmitir</code> com formatação total do Telegram.\n"
            "• Auto-registro silencioso ao ser promovido a admin em qualquer chat.\n\n"
            "⏱️ <b>Mensagens Recorrentes & Loop Contínuo:</b>\n"
            "• Disparos por intervalo de minutos, por horário fixo ou por contagem de mensagens de membros.\n"
            "• Seletor interativo de destino (Todos, Apenas Grupos, Apenas Canais ou Chat Específico).\n"
            "• Agendador autônomo com monitoramento de relógio a cada 10s.\n\n"
            "🎨 <b>Formatação Nativa RICA:</b>\n"
            "• Negrito, Itálico, Spoiler, Código e Artigos Expansíveis (<code>&gt;&gt;</code>).\n"
            "• Botões interativos em grade lado a lado (<code>[Texto | url] [Texto2 | url2]</code>).\n\n"
            "🛡️ <b>Segurança e Blindagem Completa:</b>\n"
            "• CAPTCHA Anti-Bot interativo com expulsão automática.\n"
            "• Anti-Spam (links externos e convites do Telegram) e Anti-Flood com bloqueio dinâmico.\n"
            "• Anti-Repetição inteligente com hash de mídia e texto por janela de horas.\n"
            "• Bloqueios cirúrgicos de mídia (<code>/lock</code>) e Modo Noturno programado.\n\n"
            "💾 <b>Backup & Auditoria:</b>\n"
            "• Exportação (<code>/backup</code>) e restauração (<code>/restaurar</code>) instantânea das configurações.\n"
            "• Canal de logs dedicado para registro de todas as ações de moderação.\n\n"
            "📖 <i>Para o manual técnico completo, consulte o arquivo <b>DOCUMENTACAO.md</b> no diretório raiz do bot.</i>"
        ),
        "buttons": [
            [InlineKeyboardButton("🎓 Central de Tutoriais", callback_data="tut:main"),
             InlineKeyboardButton("📋 Lista de Comandos", callback_data="help:cat:all")],
            [InlineKeyboardButton("⚙️ Abrir Painel /config", callback_data="cfg:page:1"),
             InlineKeyboardButton("◀ Voltar ao Menu", callback_data="help:cat:main")]
        ]
    }
}

class AdminCommandHandler:
    def __init__(self, admin_cache: AdminCache, user_warnings: dict = None):
        self.admin_cache = admin_cache
        self.user_warnings = user_warnings if user_warnings is not None else {}
        self.pending_broadcasts = {}

    async def _require_admin(self, update: Update, auto_clean: bool = True) -> bool:
        """Verifica se quem executou o comando é administrador. Apaga comando de não-admins se ativado."""
        chat = update.effective_chat
        user = update.effective_user
        msg = update.effective_message
        if not chat or not user:
            return False
        if chat.type == "private":
            return True
        is_adm = await self.admin_cache.is_admin(chat, user.id)
        if not is_adm and auto_clean and msg:
            cfg = load_config()
            if cfg.get("command_cleanup", {}).get("delete_non_admin_commands", True):
                try:
                    await safe_delete_message(update.get_bot(), chat.id, msg.message_id)
                except Exception:
                    pass
        return is_adm

    def _get_notice_delay(self, default_val: int = 10) -> int:
        cfg = load_config()
        return cfg.get("command_cleanup", {}).get("bot_notice_delete_seconds", default_val)

    async def _clean_admin_trigger(self, update: Update):
        """Apaga a mensagem de comando do administrador no grupo para manter o chat limpo."""
        chat = update.effective_chat
        msg = update.effective_message
        if chat and chat.type != "private" and msg:
            cfg = load_config()
            if cfg.get("command_cleanup", {}).get("delete_admin_commands", True):
                try:
                    await safe_delete_message(update.get_bot(), chat.id, msg.message_id)
                except Exception:
                    pass

    async def cmd_start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Responde ao comando /start com mensagem de boas-vindas e instruções."""
        chat = update.effective_chat
        user = update.effective_user
        if not chat or not user:
            return

        logger.info(f"Comando /start recebido de {user.id} ({user.first_name}) no chat {chat.id}")

        if chat.type == "private":
            from modules.whitelist import get_conversation_reply_keyboard
            reply_kb = get_conversation_reply_keyboard()

            # Suporte a deep-linking: /start regras ou /start tutorial
            if context.args:
                arg = context.args[0].lower()
                if arg in ("regras", "rules"):
                    cfg = load_config()
                    r_text = cfg.get("rules", "Não há regras definidas.")
                    try:
                        await update.effective_message.reply_text(
                            f"📜 <b>REGRAS DO GRUPO:</b>\n\n{html.escape(r_text)}",
                            parse_mode=ParseMode.HTML,
                            reply_markup=reply_kb
                        )
                    except Exception:
                        await update.effective_message.reply_text(f"📜 REGRAS DO GRUPO:\n\n{r_text}", reply_markup=reply_kb)
                    return

                elif arg in ("tutorial", "busca", "pesquisar", "comopesquisar"):
                    tut_caption = (
                        "🎥 <b>COMO PESQUISAR PARTITURAS (MODO INLINE):</b>\n\n"
                        "Você pode encontrar qualquer partitura em segundos diretamente no chat do grupo ou privado:\n\n"
                        "1️⃣ Digite <code>@botpartituras_bot</code> seguido de um espaço e o nome ou número do hino.\n"
                        "2️⃣ Uma janela suspensa se abrirá com os resultados encontrados instantaneamente.\n"
                        "3️⃣ Toque ou clique sobre o arquivo desejado para que ele seja enviado na conversa!\n\n"
                        "💡 <i>Exemplo: digite <code>@botpartituras_bot 150</code> para ver o Hino 150.</i>"
                    )
                    import os
                    base_dir = os.path.dirname(os.path.dirname(__file__))
                    candidate_files = [
                        os.path.join(base_dir, "assets", "tutorial_busca_partituras.gif"),
                        os.path.join(base_dir, "assets", "tutorial_busca_partituras.mp4"),
                        r"D:\Movidos\Desktop\tutorial_busca_partituras.gif",
                        r"D:\Movidos\Desktop\tutorial_busca_partituras.mp4"
                    ]
                    media_sent = False
                    for c_path in candidate_files:
                        if os.path.exists(c_path):
                            with open(c_path, "rb") as f:
                                if c_path.endswith(".gif"):
                                    await update.effective_message.reply_animation(
                                        animation=f,
                                        caption=tut_caption,
                                        parse_mode=ParseMode.HTML,
                                        reply_markup=reply_kb
                                    )
                                else:
                                    await update.effective_message.reply_video(
                                        video=f,
                                        caption=tut_caption,
                                        parse_mode=ParseMode.HTML,
                                        reply_markup=reply_kb
                                    )
                            media_sent = True
                            break
                    if not media_sent:
                        await update.effective_message.reply_text(tut_caption, parse_mode=ParseMode.HTML, reply_markup=reply_kb)
                    return

            welcome_text = (
                f"👋 Olá, <b>{html.escape(user.first_name)}</b>!\n\n"
                "Eu sou o <b>Maestro Bot</b>, orquestrador e moderador dos seus grupos e canais musicais!\n\n"
                "🎹 <b>Menu em Botões na Área de Conversa Ativado:</b>\n"
                "Toque nos botões fixos abaixo para acessar o painel, acervo, canais e listas brancas a qualquer momento.\n\n"
                "🛡️ <b>Principais Funções:</b>\n"
                "• 🎼 Acervo Global com mais de 17.000 partituras\n"
                "• 👋 Boas-vindas personalizadas por grupo\n"
                "• 🛡️ Whitelist de Usuários Livres e Links Permitidos (Google Drive)\n"
                "• 🚫 Proteção Antispam, Anti-Flood e Anti-Repetição\n"
                "• 📢 Transmissões e mensagens programadas"
            )
            try:
                await update.effective_message.reply_text(welcome_text, parse_mode=ParseMode.HTML, reply_markup=reply_kb)
            except Exception:
                await update.effective_message.reply_text(welcome_text, reply_markup=reply_kb)
        else:
            cfg = load_config()
            if cfg.get("main_group_id") != chat.id:
                cfg["main_group_id"] = chat.id
            from telegram import ReplyKeyboardRemove
            try:
                cl = await update.effective_message.reply_text("👋", reply_markup=ReplyKeyboardRemove())
                await cl.delete()
            except Exception:
                pass
            await self.cmd_ajuda(update, context)

    async def cmd_regras(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Exibe as regras do grupo."""
        config = load_config()
        rules_text = config.get("rules", "Não há regras definidas.")
        await self._clean_admin_trigger(update)
        try:
            await safe_reply(update, rules_text, parse_mode=ParseMode.MARKDOWN)
        except Exception:
            await safe_reply(update, rules_text)

    async def cmd_setregras(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Define ou atualiza as regras do grupo (apenas administradores)."""
        if not await self._require_admin(update):
            await safe_reply(update, "⛔ Este comando é exclusivo para administradores do grupo.")
            return

        message = update.effective_message
        new_rules = ""

        # 1. Se respondeu a uma mensagem com o comando
        if message and message.reply_to_message:
            rep = message.reply_to_message
            new_rules = rep.text or rep.caption or ""

        # 2. Se enviou o texto logo após o comando
        if not new_rules and context.args:
            parts = message.text.split(None, 1)
            if len(parts) > 1:
                new_rules = parts[1].strip()

        config = load_config()

        # 3. Se nenhum texto foi fornecido, mostra instrução e as regras atuais
        if not new_rules:
            curr_rules = config.get("rules", "<i>Nenhuma regra configurada.</i>")
            help_text = (
                "📜 <b>Gerenciamento de Regras do Grupo:</b>\n\n"
                "Para definir ou alterar as regras, use:\n"
                "• <code>/setregras [texto das regras]</code>\n"
                "• Ou responda a qualquer mensagem com <code>/setregras</code>\n\n"
                "🔘 <b>Como exibir as regras aos membros:</b>\n"
                "• <b>No botão de boas-vindas:</b> <code>[📜 Regras](regras)</code> ou <code>Regras | regras</code>\n"
                "• <b>Na mensagem de boas-vindas:</b> use a tag <code>{rules}</code>\n"
                "• <b>Por comando:</b> qualquer membro pode enviar <code>/regras</code>\n\n"
                f"📋 <b>Regras Atuais:</b>\n<blockquote>{html.escape(curr_rules)}</blockquote>"
            )
            await safe_reply(update, help_text, parse_mode=ParseMode.HTML)
            return

        # Salva as novas regras
        config["rules"] = new_rules
        save_config(config)

        await self._clean_admin_trigger(update)

        confirm_text = (
            "✅ <b>Regras do grupo atualizadas com sucesso!</b>\n\n"
            "• As novas regras já estão ativas para novos membros nos botões <code>[📜 Regras](regras)</code> e no comando <code>/regras</code>.\n\n"
            f"📋 <b>Prévia salva:</b>\n<blockquote>{html.escape(new_rules)}</blockquote>"
        )
        await safe_reply(update, confirm_text, parse_mode=ParseMode.HTML)

    async def cmd_status(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Exibe o painel de status das proteções ativas (apenas admins)."""
        if not await self._require_admin(update):
            await safe_reply(update, "⛔ Este comando é exclusivo para administradores do grupo.")
            return

        chat = update.effective_chat
        if chat and chat.type in ("group", "supergroup"):
            cfg_save = load_config()
            if cfg_save.get("main_group_id") != chat.id:
                cfg_save["main_group_id"] = chat.id
                save_config(cfg_save)

        await self._clean_admin_trigger(update)

        config = load_config()
        w = config.get("welcome", {})
        s = config.get("antispam", {})
        f = config.get("antiflood", {})
        r = config.get("antirepeat", {})

        def icon(b): return "✅ Ativado" if b else "❌ Desativado"

        text = (
            "⚙️ *Painel de Moderação do Grupo*\n\n"
            f"👋 *Boas-Vindas:* {icon(w.get('enabled', True))}\n"
            f"   • Auto-apagar: {w.get('delete_welcome_after_seconds', 0)}s\n"
            f"   • Limpar msg de entrada: {icon(w.get('delete_service_messages', True))}\n\n"
            f"🛡️ *Antispam:* {icon(s.get('enabled', True))}\n"
            f"   • Bloquear Links: {icon(s.get('block_links', True))}\n"
            f"   • Bloquear Convites Telegram: {icon(s.get('block_telegram_invites', True))}\n"
            f"   • Bloquear Encaminhamentos: {icon(s.get('block_forwards', True))}\n"
            f"   • Palavras proibidas: {len(s.get('banned_words', []))} cadastradas\n\n"
            f"🌊 *Anti-Flood:* {icon(f.get('enabled', True))}\n"
            f"   • Limite: {f.get('max_messages', 5)} msgs em {f.get('time_window_seconds', 5)}s\n"
            f"   • Punição: Silêncio de {f.get('mute_duration_minutes', 5)} min\n\n"
            f"🔁 *Anti-Repetição:* {icon(r.get('enabled', True))}\n"
            f"   • Limite: {r.get('max_repeated', 2)} repetições em {r.get('time_window_seconds', 60)}s\n\n"
            "_Para alterar essas opções, edite o arquivo config.json na pasta do bot._"
        )
        await safe_reply(update, text, parse_mode=ParseMode.MARKDOWN)

    async def cmd_ban(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Bane o usuário respondido (permanente ou temporário: /ban 1d, /ban 2h)."""
        if not await self._require_admin(update):
            return

        msg = update.effective_message
        chat = update.effective_chat
        del_sec = self._get_notice_delay(15)

        if not msg.reply_to_message or not msg.reply_to_message.from_user:
            await self._clean_admin_trigger(update)
            notice = await chat.send_message("⚠️ Responda à mensagem do usuário com `/ban [tempo] [motivo]` (Ex: `/ban 1d Spam` ou `/ban 2h`).", parse_mode=ParseMode.MARKDOWN)
            if del_sec > 0:
                schedule_message_deletion(context, chat.id, notice.message_id, 8)
            return

        target_user = msg.reply_to_message.from_user
        delta, time_label, reason = parse_flexible_time(context.args or [])
        if not reason:
            reason = "Comando /ban administrativo"

        until_date = None
        if delta:
            until_date = datetime.now(timezone.utc) + delta

        await self._clean_admin_trigger(update)

        try:
            if until_date:
                await chat.ban_member(user_id=target_user.id, until_date=until_date)
                resp_text = f"🔨 Usuário <b>{html.escape(target_user.first_name)}</b> foi banido temporariamente por <b>{time_label}</b>."
                if reason and reason != "Comando /ban administrativo":
                    resp_text += f"\nMotivo: <i>{html.escape(reason)}</i>"
            else:
                await chat.ban_member(user_id=target_user.id)
                resp_text = f"🔨 Usuário <b>{html.escape(target_user.first_name)}</b> foi banido permanentemente."
                if reason and reason != "Comando /ban administrativo":
                    resp_text += f"\nMotivo: <i>{html.escape(reason)}</i>"

            notice = await chat.send_message(resp_text, parse_mode=ParseMode.HTML)
            if del_sec > 0:
                schedule_message_deletion(context, chat.id, notice.message_id, del_sec)

            logger.info(f"Usuário {target_user.id} banido por {update.effective_user.id} ({time_label or 'permanente'})")
            await send_mod_log(
                bot=context.bot,
                event_type="ban",
                title=f"Membro Banido ({time_label or 'Permanente'})",
                user_info=f"{html.escape(target_user.first_name)} (<code>{target_user.id}</code>)",
                admin_info=f"{html.escape(update.effective_user.first_name)} (<code>{update.effective_user.id}</code>)",
                reason=reason
            )
        except Exception as e:
            await msg.reply_text(f"❌ Não foi possível banir o usuário: {e}")

    async def cmd_kick(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Remove o usuário do grupo sem bloqueio definitivo (apenas admins)."""
        if not await self._require_admin(update):
            return

        msg = update.effective_message
        chat = update.effective_chat
        del_sec = self._get_notice_delay(15)

        if not msg.reply_to_message or not msg.reply_to_message.from_user:
            await self._clean_admin_trigger(update)
            notice = await chat.send_message("⚠️ Responda à mensagem do usuário que deseja remover com `/kick`.")
            if del_sec > 0:
                schedule_message_deletion(context, chat.id, notice.message_id, 8)
            return

        target_user = msg.reply_to_message.from_user
        reason = " ".join(context.args) if context.args else "Comando /kick administrativo"

        await self._clean_admin_trigger(update)

        try:
            await chat.unban_member(user_id=target_user.id)
            resp_text = f"👢 Usuário <b>{html.escape(target_user.first_name)}</b> foi removido do grupo."
            if reason and reason != "Comando /kick administrativo":
                resp_text += f"\nMotivo: <i>{html.escape(reason)}</i>"

            notice = await chat.send_message(resp_text, parse_mode=ParseMode.HTML)
            if del_sec > 0:
                schedule_message_deletion(context, chat.id, notice.message_id, del_sec)

            logger.info(f"Usuário {target_user.id} removido por {update.effective_user.id}")
            await send_mod_log(
                bot=context.bot,
                event_type="kick",
                title="Membro Removido (Kick)",
                user_info=f"{html.escape(target_user.first_name)} (<code>{target_user.id}</code>)",
                admin_info=f"{html.escape(update.effective_user.first_name)} (<code>{update.effective_user.id}</code>)",
                reason=reason
            )
        except Exception as e:
            await msg.reply_text(f"❌ Não foi possível remover o usuário: {e}")

    async def cmd_mute(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Silencia o usuário respondido (tempo flexível: /mute 30m, /mute 2h, /mute 1d)."""
        if not await self._require_admin(update):
            return

        msg = update.effective_message
        chat = update.effective_chat
        del_sec = self._get_notice_delay(15)

        if not msg.reply_to_message or not msg.reply_to_message.from_user:
            await self._clean_admin_trigger(update)
            notice = await chat.send_message("⚠️ Responda à mensagem do usuário com `/mute [tempo] [motivo]` (Ex: `/mute 30m Flood` ou `/mute 2h`).", parse_mode=ParseMode.MARKDOWN)
            if del_sec > 0:
                schedule_message_deletion(context, chat.id, notice.message_id, 8)
            return

        target_user = msg.reply_to_message.from_user
        delta, time_label, reason = parse_flexible_time(context.args or [])
        if not delta:
            delta = timedelta(minutes=15)
            time_label = "15 minuto(s)"

        if not reason:
            reason = f"Silenciado por {time_label}"

        until_date = datetime.now(timezone.utc) + delta

        await self._clean_admin_trigger(update)

        try:
            await chat.restrict_member(
                user_id=target_user.id,
                permissions=ChatPermissions(can_send_messages=False),
                until_date=until_date
            )
            resp_text = f"🔇 Usuário <b>{html.escape(target_user.first_name)}</b> foi silenciado por <b>{time_label}</b>."
            if reason and reason != f"Silenciado por {time_label}":
                resp_text += f"\nMotivo: <i>{html.escape(reason)}</i>"

            notice = await chat.send_message(resp_text, parse_mode=ParseMode.HTML)
            if del_sec > 0:
                schedule_message_deletion(context, chat.id, notice.message_id, del_sec)

            logger.info(f"Usuário {target_user.id} silenciado por {time_label}")
            await send_mod_log(
                bot=context.bot,
                event_type="mute",
                title=f"Membro Silenciado ({time_label})",
                user_info=f"{html.escape(target_user.first_name)} (<code>{target_user.id}</code>)",
                admin_info=f"{html.escape(update.effective_user.first_name)} (<code>{update.effective_user.id}</code>)",
                reason=reason
            )
        except Exception as e:
            await msg.reply_text(f"❌ Erro ao silenciar usuário: {e}")

    async def cmd_unmute(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Remove o silêncio de um usuário (apenas admins)."""
        if not await self._require_admin(update):
            return

        msg = update.effective_message
        chat = update.effective_chat
        del_sec = self._get_notice_delay(10)

        if not msg.reply_to_message or not msg.reply_to_message.from_user:
            await self._clean_admin_trigger(update)
            notice = await chat.send_message("⚠️ Responda à mensagem do usuário que deseja desmutar com `/unmute`.")
            if del_sec > 0:
                schedule_message_deletion(context, chat.id, notice.message_id, 8)
            return

        target_user = msg.reply_to_message.from_user

        await self._clean_admin_trigger(update)

        try:
            await chat.restrict_member(
                user_id=target_user.id,
                permissions=ChatPermissions(
                    can_send_messages=True,
                    can_send_other_messages=True,
                    can_add_web_page_previews=True
                )
            )
            notice = await chat.send_message(f"🔊 Permissões de envio restabelecidas para <b>{html.escape(target_user.first_name)}</b>.", parse_mode=ParseMode.HTML)
            if del_sec > 0:
                schedule_message_deletion(context, chat.id, notice.message_id, del_sec)

            await send_mod_log(
                bot=context.bot,
                event_type="unmute",
                title="Membro Desmutado",
                user_info=f"{html.escape(target_user.first_name)} (<code>{target_user.id}</code>)",
                admin_info=f"{html.escape(update.effective_user.first_name)} (<code>{update.effective_user.id}</code>)"
            )
        except Exception as e:
            await msg.reply_text(f"❌ Erro ao desmutar usuário: {e}")

    async def cmd_limpar(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Apaga as últimas N mensagens enviadas no grupo (ex: /limpar 10)."""
        if not await self._require_admin(update):
            return

        msg = update.effective_message
        chat = update.effective_chat

        count = 5
        if context.args and context.args[0].isdigit():
            count = min(int(context.args[0]), 100)

        await safe_delete_message(context.bot, chat.id, msg.message_id)

        deleted = 0
        for msg_id in range(msg.message_id - 1, msg.message_id - 1 - (count * 2), -1):
            if deleted >= count:
                break
            if await safe_delete_message(context.bot, chat.id, msg_id):
                deleted += 1

        confirm_msg = await chat.send_message(f"🧹 {deleted} mensagem(ns) foram apagadas.")
        schedule_message_deletion(context, chat.id, confirm_msg.message_id, 5)

    async def cmd_warn(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Aplica uma advertência manual a um usuário (3 advertências = ban)."""
        if not await self._require_admin(update):
            return

        msg = update.effective_message
        chat = update.effective_chat
        del_sec = self._get_notice_delay(15)

        if not msg.reply_to_message or not msg.reply_to_message.from_user:
            await self._clean_admin_trigger(update)
            notice = await chat.send_message("⚠️ Responda à mensagem do usuário que deseja advertir com `/warn [motivo]`.", parse_mode=ParseMode.MARKDOWN)
            if del_sec > 0:
                schedule_message_deletion(context, chat.id, notice.message_id, 8)
            return

        target_user = msg.reply_to_message.from_user
        if target_user.is_bot:
            await self._clean_admin_trigger(update)
            notice = await chat.send_message("⚠️ Não é possível advertir bots.")
            if del_sec > 0:
                schedule_message_deletion(context, chat.id, notice.message_id, 8)
            return

        w_key = (chat.id, target_user.id)
        reason = " ".join(context.args) if context.args else "Violação das regras do grupo"
        curr_warns = self.user_warnings.get(w_key, 0) + 1
        self.user_warnings[w_key] = curr_warns

        await self._clean_admin_trigger(update)

        safe_name = target_user.first_name
        if curr_warns >= 3:
            try:
                await chat.ban_member(user_id=target_user.id)
                self.user_warnings.pop(w_key, None)
                notice = await chat.send_message(
                    f"🔨 *{safe_name} atingiu 3/3 advertências e foi BANIDO(A) do grupo!*\n"
                    f"📌 Motivo: _{reason}_",
                    parse_mode=ParseMode.MARKDOWN
                )
                if del_sec > 0:
                    schedule_message_deletion(context, chat.id, notice.message_id, del_sec)

                await send_mod_log(
                    bot=context.bot,
                    event_type="ban",
                    title="Membro Banido por 3 Advertências",
                    user_info=f"{html.escape(safe_name)} (<code>{target_user.id}</code>)",
                    admin_info=f"{html.escape(update.effective_user.first_name)} (<code>{update.effective_user.id}</code>)",
                    reason=reason
                )
            except Exception as e:
                await chat.send_message(f"⚠️ {safe_name} atingiu 3 advertências, mas ocorreu um erro ao banir: {e}")
        else:
            notice = await chat.send_message(
                f"❗ *Advertência ({curr_warns}/3)* aplicada a *{safe_name}*!\n"
                f"📌 Motivo: _{reason}_\n"
                f"⚠️ Ao atingir 3 advertências, o usuário será banido automaticamente.",
                parse_mode=ParseMode.MARKDOWN
            )
            if del_sec > 0:
                schedule_message_deletion(context, chat.id, notice.message_id, del_sec)

            await send_mod_log(
                bot=context.bot,
                event_type="warn",
                title=f"Advertência Aplicada ({curr_warns}/3)",
                user_info=f"{html.escape(safe_name)} (<code>{target_user.id}</code>)",
                admin_info=f"{html.escape(update.effective_user.first_name)} (<code>{update.effective_user.id}</code>)",
                reason=reason
            )

    async def cmd_unwarn(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Remove uma advertência de um usuário."""
        if not await self._require_admin(update):
            return

        msg = update.effective_message
        chat = update.effective_chat
        del_sec = self._get_notice_delay(10)

        if not msg.reply_to_message or not msg.reply_to_message.from_user:
            await self._clean_admin_trigger(update)
            notice = await chat.send_message("⚠️ Responda à mensagem do usuário com `/unwarn` para retirar uma advertência.")
            if del_sec > 0:
                schedule_message_deletion(context, chat.id, notice.message_id, 8)
            return

        target_user = msg.reply_to_message.from_user
        w_key = (chat.id, target_user.id)
        curr_warns = self.user_warnings.get(w_key, 0)

        await self._clean_admin_trigger(update)

        if curr_warns <= 0:
            notice = await chat.send_message(f"ℹ️ {target_user.first_name} não possui nenhuma advertência ativa.")
            if del_sec > 0:
                schedule_message_deletion(context, chat.id, notice.message_id, del_sec)
            return

        new_val = curr_warns - 1
        if new_val == 0:
            self.user_warnings.pop(w_key, None)
        else:
            self.user_warnings[w_key] = new_val

        notice = await chat.send_message(
            f"✅ Uma advertência foi removida de *{target_user.first_name}*!\n"
            f"Total atual: *{new_val}/3* advertências.",
            parse_mode=ParseMode.MARKDOWN
        )
        if del_sec > 0:
            schedule_message_deletion(context, chat.id, notice.message_id, del_sec)

        await send_mod_log(
            bot=context.bot,
            event_type="unwarn",
            title=f"Advertência Removida (Atual: {new_val}/3)",
            user_info=f"{html.escape(target_user.first_name)} (<code>{target_user.id}</code>)",
            admin_info=f"{html.escape(update.effective_user.first_name)} (<code>{update.effective_user.id}</code>)"
        )

    async def cmd_warns(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Consulta as advertências de um usuário."""
        msg = update.effective_message
        chat = update.effective_chat
        del_sec = self._get_notice_delay(12)

        target_user = msg.from_user
        if msg.reply_to_message and msg.reply_to_message.from_user:
            target_user = msg.reply_to_message.from_user

        w_key = (chat.id, target_user.id)
        curr_warns = self.user_warnings.get(w_key, 0)

        await self._clean_admin_trigger(update)

        notice = await chat.send_message(
            f"📋 *Status de Advertências:* {target_user.first_name}\n"
            f"Advertências ativas: *{curr_warns}/3*",
            parse_mode=ParseMode.MARKDOWN
        )
        if del_sec > 0:
            schedule_message_deletion(context, chat.id, notice.message_id, del_sec)

    async def cmd_pin(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Fixa a mensagem respondida no topo do grupo."""
        if not await self._require_admin(update):
            return

        msg = update.effective_message
        chat = update.effective_chat
        del_sec = self._get_notice_delay(5)

        if not msg.reply_to_message:
            await self._clean_admin_trigger(update)
            notice = await chat.send_message("⚠️ Responda à mensagem que deseja fixar com `/pin`.")
            if del_sec > 0:
                schedule_message_deletion(context, chat.id, notice.message_id, 8)
            return

        notify = False
        if context.args and context.args[0].lower() in ("notificar", "alerta", "loud", "notify"):
            notify = True

        try:
            await chat.pin_chat_message(
                message_id=msg.reply_to_message.message_id,
                disable_notification=not notify
            )
            cfg = self.config or load_config()
            if cfg.get("delete_pinned_service_messages", True):
                from modules.utils import safe_delete_message
                try:
                    await safe_delete_message(context.bot, chat.id, msg.message_id + 1)
                except Exception:
                    pass
            await self._clean_admin_trigger(update)
            notice = await chat.send_message("📌 Mensagem fixada com sucesso!")
            if del_sec > 0:
                schedule_message_deletion(context, chat.id, notice.message_id, del_sec)
        except Exception as e:
            await msg.reply_text(f"❌ Erro ao fixar mensagem: {e}")

    async def cmd_unpin(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Desfixa mensagens fixadas."""
        if not await self._require_admin(update):
            return

        msg = update.effective_message
        chat = update.effective_chat
        del_sec = self._get_notice_delay(5)

        try:
            if msg.reply_to_message:
                await chat.unpin_chat_message(message_id=msg.reply_to_message.message_id)
            else:
                await chat.unpin_chat_message()
            await self._clean_admin_trigger(update)
            notice = await chat.send_message("📌 Mensagem desfixada com sucesso!")
            if del_sec > 0:
                schedule_message_deletion(context, chat.id, notice.message_id, del_sec)
        except Exception as e:
            await msg.reply_text(f"❌ Erro ao desfixar mensagem: {e}")

    async def cmd_say(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Envia mensagem no grupo como sendo o bot (funciona no privado e no grupo)."""
        chat = update.effective_chat
        user = update.effective_user
        msg = update.effective_message
        cfg = load_config()

        is_private = (chat.type == "private")

        if is_private:
            all_linked = get_all_linked_chats(cfg)
            main_grp = cfg.get("main_group_id")
            main_chn = cfg.get("main_channel_id")

            if not all_linked and not main_grp and not main_chn:
                await msg.reply_text(
                    "⚠️ <b>Nenhum grupo ou canal vinculado!</b>\n\n"
                    "Para vincular:\n"
                    "• No grupo: Envie <code>/setgrupo</code>\n"
                    "• No canal: Envie <code>/setcanal @seucanal</code> aqui no privado",
                    parse_mode=ParseMode.HTML
                )
                return

            target_thread_id = None
            raw_html = msg.text_html or msg.text or ""
            body_html = re.sub(r"^\/\w+(?:@\w+)?\s*", "", raw_html)

            reply = msg.reply_to_message
            photo = None
            document = None
            audio = None
            voice = None
            video = None
            text_to_send = body_html.strip()

            if reply:
                if reply.photo:
                    photo = reply.photo[-1].file_id
                    if not text_to_send:
                        text_to_send = reply.caption_html or reply.caption or ""
                elif reply.document:
                    document = reply.document.file_id
                    if not text_to_send:
                        text_to_send = reply.caption_html or reply.caption or ""
                elif reply.video:
                    video = reply.video.file_id
                    if not text_to_send:
                        text_to_send = reply.caption_html or reply.caption or ""
                elif reply.audio:
                    audio = reply.audio.file_id
                    if not text_to_send:
                        text_to_send = reply.caption_html or reply.caption or ""
                elif reply.voice:
                    voice = reply.voice.file_id
                elif not text_to_send:
                    text_to_send = reply.text_html or reply.text or ""
            elif msg.photo:
                photo = msg.photo[-1].file_id
                if not text_to_send:
                    caption_html = msg.caption_html or msg.caption or ""
                    text_to_send = re.sub(r"^/\w+(?:@\w+)?\s*", "", caption_html).strip()
            elif msg.document:
                document = msg.document.file_id
                if not text_to_send:
                    caption_html = msg.caption_html or msg.caption or ""
                    text_to_send = re.sub(r"^/\w+(?:@\w+)?\s*", "", caption_html).strip()
            elif msg.video:
                video = msg.video.file_id
                if not text_to_send:
                    caption_html = msg.caption_html or msg.caption or ""
                    text_to_send = re.sub(r"^/\w+(?:@\w+)?\s*", "", caption_html).strip()
            elif msg.audio:
                audio = msg.audio.file_id
                if not text_to_send:
                    caption_html = msg.caption_html or msg.caption or ""
                    text_to_send = re.sub(r"^/\w+(?:@\w+)?\s*", "", caption_html).strip()

            # Caso o usuário envie apenas /falar sem nada: exibe o Guia Maestro com lista de grupos
            if not text_to_send and not photo and not document and not audio and not voice and not video:
                chat_lines = []
                for i, c in enumerate(all_linked, 1):
                    is_m = " ⭐️ [Principal]" if (c["id"] == main_grp or c["id"] == main_chn) else ""
                    icon = "📢" if c.get("is_channel") else "👥"
                    chat_lines.append(f"• <b>{i}. {icon} {html.escape(c.get('title', 'Chat'))}{is_m}</b> (<code>{c['id']}</code>)")

                chats_str = "\n".join(chat_lines) if chat_lines else "<i>Nenhum chat registrado ainda.</i>"

                guide = (
                    "🎼 <b>MAESTRO BOT — TRANSMISSÕES PELO PRIVADO</b>\n"
                    "━━━━━━━━━━━━━━━━━━━━\n"
                    "Pelo privado você pode enviar comunicados, partituras (PDF), fotos ou áudios como o bot para <b>qualquer grupo ou canal vinculado</b>!\n\n"
                    "💡 <b>Como utilizar:</b>\n"
                    "1️⃣ <b>Com Seletor Interativo:</b>\n"
                    "Envie: <code>/falar Olá a todos!</code>\n"
                    "<i>(O Maestro abrirá botões na hora para você escolher o grupo!)</i>\n\n"
                    "2️⃣ <b>Com Fotos, Partituras e Áudios:</b>\n"
                    "Envie foto, áudio ou PDF com legenda <code>/falar</code> (ou responda a uma mensagem com <code>/falar</code>).\n\n"
                    "3️⃣ <b>Direto pelo Número ou ID:</b>\n"
                    "<code>/falar 1 Sua mensagem aqui</code> (envia direto no chat #1)\n"
                    "<code>/falar 2 Sua mensagem aqui</code> (envia direto no chat #2)\n\n"
                    f"📋 <b>Chats Vinculados Disponíveis:</b>\n{chats_str}"
                )
                await msg.reply_text(guide, parse_mode=ParseMode.HTML)
                return

            target_group_id = None
            explicit_target = False

            # Checa se o início do texto é um ID de grupo/canal ou username (ex: -100..., -... ou @canal)
            m_target = re.match(r"^(-100\d+|-\d+|@\w+)(?::(\d+))?\s*([\s\S]*)", text_to_send)
            if m_target:
                raw_target = m_target.group(1)
                try:
                    target_group_id = int(raw_target) if (raw_target.startswith("-") or raw_target.isdigit()) else raw_target
                    if m_target.group(2):
                        target_thread_id = int(m_target.group(2))
                    text_to_send = m_target.group(3).strip()
                    explicit_target = True
                except Exception:
                    pass

            # Checa se o início do texto é o número do chat na lista (ex: /falar 1 Mensagem, /falar 2 Mensagem)
            if not explicit_target:
                m_num = re.match(r"^(\d{1,2})(?::(\d+))?\s+([\s\S]*)", text_to_send)
                if m_num and all_linked:
                    idx = int(m_num.group(1))
                    if 1 <= idx <= len(all_linked):
                        target_group_id = all_linked[idx - 1]["id"]
                        if m_num.group(2):
                            target_thread_id = int(m_num.group(2))
                        text_to_send = m_num.group(3).strip()
                        explicit_target = True

            # Se não especificou destino explicitamente:
            if not explicit_target:
                if len(all_linked) > 1:
                    # Abre seletor interativo com botões
                    self.pending_broadcasts[user.id] = {
                        "text": text_to_send,
                        "photo": photo,
                        "document": document,
                        "audio": audio,
                        "voice": voice,
                        "video": video,
                        "target_thread_id": target_thread_id
                    }

                    media_tags = []
                    if photo: media_tags.append("🖼️ Foto")
                    if document: media_tags.append("📄 Documento/PDF")
                    if audio: media_tags.append("🎵 Áudio")
                    if video: media_tags.append("🎬 Vídeo")
                    if voice: media_tags.append("🎙️ Mensagem de Voz")

                    media_str = f"• <b>Anexo:</b> {', '.join(media_tags)}\n" if media_tags else ""
                    preview_t = text_to_send if len(text_to_send) <= 150 else text_to_send[:147] + "..."
                    text_str = f"• <b>Texto:</b> <i>{html.escape(preview_t)}</i>\n" if preview_t else ""

                    selector_text = (
                        "🎼 <b>MAESTRO — TRANSMISSÃO PELO PRIVADO</b>\n"
                        "━━━━━━━━━━━━━━━━━━━━\n\n"
                        "📝 <b>Conteúdo pronto para envio:</b>\n"
                        f"{media_str}{text_str}\n"
                        "🎯 <b>Toque abaixo no grupo ou canal onde deseja transmitir:</b>"
                    )
                    markup = self._build_falar_target_keyboard(cfg)
                    await msg.reply_text(selector_text, reply_markup=markup, parse_mode=ParseMode.HTML)
                    return
                elif len(all_linked) == 1:
                    target_group_id = all_linked[0]["id"]
                else:
                    target_group_id = main_grp or main_chn

            # Envio direto (quando explicitamente indicado ou quando há apenas 1 chat vinculado)
            payload = {
                "text": text_to_send,
                "photo": photo,
                "document": document,
                "audio": audio,
                "voice": voice,
                "video": video,
                "target_thread_id": target_thread_id
            }
            ok, res = await self._execute_broadcast(context, user, target_group_id, payload, target_thread_id)
            if ok:
                await msg.reply_text(f"✅ <b>Mensagem enviada com sucesso no chat {html.escape(res)}!</b>", parse_mode=ParseMode.HTML)
                logger.info(f"Admin {user.id} enviou mensagem pelo privado para {target_group_id}")
            else:
                await msg.reply_text(f"❌ Erro ao enviar mensagem: {res}")

        else:
            if not await self._require_admin(update):
                return

            raw_html = msg.caption_html or msg.text_html or msg.caption or msg.text or ""
            text_to_send = re.sub(r"^/\w+(?:@\w+)?\s*", "", raw_html).strip()
            photo = None
            document = None
            audio = None
            voice = None

            if msg.reply_to_message:
                reply = msg.reply_to_message
                if reply.photo:
                    photo = reply.photo[-1].file_id
                    if not text_to_send:
                        text_to_send = reply.caption_html or reply.caption or ""
                elif reply.document:
                    document = reply.document.file_id
                    if not text_to_send:
                        text_to_send = reply.caption_html or reply.caption or ""
                elif reply.audio:
                    audio = reply.audio.file_id
                    if not text_to_send:
                        text_to_send = reply.caption_html or reply.caption or ""
                elif reply.voice:
                    voice = reply.voice.file_id
                elif not text_to_send:
                    text_to_send = reply.text_html or reply.text or ""
            elif msg.photo:
                photo = msg.photo[-1].file_id
                if not text_to_send:
                    caption_html = msg.caption_html or msg.caption or ""
                    text_to_send = re.sub(r"^/\w+(?:@\w+)?\s*", "", caption_html).strip()

            await safe_delete_message(context.bot, chat.id, msg.message_id)

            if not text_to_send and not photo and not document and not audio and not voice:
                notice = await chat.send_message("⚠️ Uso: `/say <texto>` ou `/falar <texto>` (ou responda a foto/áudio/PDF)", parse_mode=ParseMode.MARKDOWN)
                del_sec = self._get_notice_delay(8)
                if del_sec > 0:
                    schedule_message_deletion(context, chat.id, notice.message_id, del_sec)
                return

            extracted_btns = parse_rich_buttons(text_to_send) if text_to_send else []
            markup = build_rich_buttons_markup(extracted_btns) if extracted_btns else None
            if extracted_btns:
                lines = text_to_send.split("\n")
                clean_lines = [l for l in lines if not parse_rich_buttons(l)]
                text_to_send = "\n".join(clean_lines).strip()

            thread_id = getattr(msg, "message_thread_id", None)
            send_kwargs = {}
            if thread_id:
                send_kwargs["message_thread_id"] = thread_id

            if photo:
                await smart_send_photo(bot=context.bot, chat_id=chat.id, photo=photo, caption=text_to_send, reply_markup=markup, **send_kwargs)
            elif document:
                rich_caption = convert_rich_text(text_to_send)
                try:
                    await context.bot.send_document(chat_id=chat.id, document=document, caption=rich_caption, parse_mode=ParseMode.HTML, reply_markup=markup, **send_kwargs)
                except Exception:
                    await context.bot.send_document(chat_id=chat.id, document=document, caption=text_to_send, reply_markup=markup, **send_kwargs)
            elif audio:
                await context.bot.send_audio(chat_id=chat.id, audio=audio, caption=text_to_send, reply_markup=markup, **send_kwargs)
            elif voice:
                await context.bot.send_voice(chat_id=chat.id, voice=voice, **send_kwargs)
            else:
                await smart_send_message(bot=context.bot, chat_id=chat.id, text=text_to_send, reply_markup=markup, **send_kwargs)

    def _build_falar_target_keyboard(self, cfg: dict) -> InlineKeyboardMarkup:
        """Cria teclado inline com todos os grupos e canais vinculados para seleção de destino."""
        all_linked = get_all_linked_chats(cfg)
        main_grp = cfg.get("main_group_id")
        main_chn = cfg.get("main_channel_id")

        kb = []
        groups = [c for c in all_linked if not c.get("is_channel")]
        channels = [c for c in all_linked if c.get("is_channel")]

        if groups:
            for g in groups:
                gid = g["id"]
                gtit = g.get("title", f"Grupo {gid}")
                if len(gtit) > 22:
                    gtit = gtit[:20] + "…"
                is_m = " ⭐️" if gid == main_grp else ""
                kb.append([InlineKeyboardButton(f"👥 {gtit}{is_m}", callback_data=f"falar:send:grp:{gid}")])

        if channels:
            for c in channels:
                cid = c["id"]
                ctit = c.get("title", f"Canal {cid}")
                if len(ctit) > 22:
                    ctit = ctit[:20] + "…"
                is_m = " ⭐️" if cid == main_chn else ""
                kb.append([InlineKeyboardButton(f"📢 {ctit}{is_m}", callback_data=f"falar:send:chn:{cid}")])

        special_row = []
        if len(groups) > 1:
            special_row.append(InlineKeyboardButton("👥 Todos Grupos", callback_data="falar:send:all_groups"))
        if len(channels) > 1:
            special_row.append(InlineKeyboardButton("📢 Todos Canais", callback_data="falar:send:all_channels"))
        if special_row:
            kb.append(special_row)

        if len(all_linked) > 1:
            kb.append([InlineKeyboardButton("🌐 Transmitir em TODOS", callback_data="falar:send:all")])

        kb.append([InlineKeyboardButton("❌ Cancelar Envio", callback_data="falar:cancel")])
        return InlineKeyboardMarkup(kb)

    async def _execute_broadcast(self, context: ContextTypes.DEFAULT_TYPE, user, target_id: int | str, payload: dict, thread_id: int | None = None) -> tuple[bool, str]:
        """Envia mensagem ou mídia para o chat especificado com suporte completo a formatações e botões."""
        try:
            target_chat = await context.bot.get_chat(target_id)
        except Exception as e:
            return False, f"Chat não encontrado ({e})"

        cfg = load_config()
        # Validação de Administrador
        is_adm = False
        try:
            if target_chat.type == "channel":
                try:
                    m_mem = await target_chat.get_member(user.id)
                    is_adm = m_mem.status in (ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.OWNER)
                except Exception:
                    pass
                if not is_adm:
                    for g in cfg.get("linked_groups", []):
                        try:
                            gc = await context.bot.get_chat(g["id"])
                            if await self.admin_cache.is_admin(gc, user.id):
                                is_adm = True
                                break
                        except Exception:
                            pass
                if not is_adm and cfg.get("main_group_id"):
                    try:
                        gc = await context.bot.get_chat(cfg["main_group_id"])
                        if await self.admin_cache.is_admin(gc, user.id):
                            is_adm = True
                    except Exception:
                        pass
            else:
                is_adm = await self.admin_cache.is_admin(target_chat, user.id)
        except Exception:
            is_adm = True

        if not is_adm:
            return False, "Você não tem permissão de administrador neste chat."

        text_to_send = payload.get("text") or ""
        photo = payload.get("photo")
        document = payload.get("document")
        audio = payload.get("audio")
        voice = payload.get("voice")
        video = payload.get("video")

        target_thread_id = thread_id or payload.get("target_thread_id")
        send_kwargs = {}
        if target_thread_id:
            send_kwargs["message_thread_id"] = target_thread_id

        extracted_btns = parse_rich_buttons(text_to_send) if text_to_send else []
        markup = build_rich_buttons_markup(extracted_btns) if extracted_btns else None
        if extracted_btns:
            lines = text_to_send.split("\n")
            clean_lines = [l for l in lines if not parse_rich_buttons(l)]
            text_to_send = "\n".join(clean_lines).strip()

        try:
            if photo:
                await smart_send_photo(bot=context.bot, chat_id=target_id, photo=photo, caption=text_to_send, reply_markup=markup, **send_kwargs)
            elif document:
                rich_caption = convert_rich_text(text_to_send)
                try:
                    await context.bot.send_document(chat_id=target_id, document=document, caption=rich_caption, parse_mode=ParseMode.HTML, reply_markup=markup, **send_kwargs)
                except Exception:
                    await context.bot.send_document(chat_id=target_id, document=document, caption=text_to_send, reply_markup=markup, **send_kwargs)
            elif video:
                rich_caption = convert_rich_text(text_to_send)
                try:
                    await context.bot.send_video(chat_id=target_id, video=video, caption=rich_caption, parse_mode=ParseMode.HTML, reply_markup=markup, **send_kwargs)
                except Exception:
                    await context.bot.send_video(chat_id=target_id, video=video, caption=text_to_send, reply_markup=markup, **send_kwargs)
            elif audio:
                await context.bot.send_audio(chat_id=target_id, audio=audio, caption=text_to_send, reply_markup=markup, **send_kwargs)
            elif voice:
                await context.bot.send_voice(chat_id=target_id, voice=voice, **send_kwargs)
            else:
                await smart_send_message(bot=context.bot, chat_id=target_id, text=text_to_send, reply_markup=markup, **send_kwargs)

            chat_title = target_chat.title or str(target_id)
            return True, chat_title
        except Exception as e:
            logger.error(f"Erro ao transmitir para {target_id}: {e}")
            return False, str(e)

    async def handle_falar_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Gerencia os cliques nos botões de escolha de destino para o comando /falar."""
        query = update.callback_query
        if not query or not query.data:
            return

        user = update.effective_user
        data = query.data

        if data == "falar:cancel":
            self.pending_broadcasts.pop(user.id, None)
            await query.answer("Transmissão cancelada.")
            try:
                await query.edit_message_text("❌ <b>Transmissão cancelada.</b>", parse_mode=ParseMode.HTML)
            except Exception:
                pass
            return

        payload = self.pending_broadcasts.get(user.id)
        if not payload:
            await query.answer("⚠️ Nenhuma mensagem pendente ou o envio expirou. Envie /falar novamente.", show_alert=True)
            return

        cfg = load_config()

        if data.startswith("falar:send:grp:") or data.startswith("falar:send:chn:"):
            target_id = data.split(":")[-1]
            if target_id.startswith("-") or target_id.isdigit():
                target_id = int(target_id)

            await query.answer("Transmitindo mensagem...")
            ok, res = await self._execute_broadcast(context, user, target_id, payload)
            if ok:
                self.pending_broadcasts.pop(user.id, None)
                await query.edit_message_text(f"✅ <b>Mensagem transmitida com sucesso para {html.escape(res)}!</b>", parse_mode=ParseMode.HTML)
            else:
                await query.answer(f"Erro: {res}", show_alert=True)
            return

        if data == "falar:send:all_groups":
            groups = cfg.get("linked_groups", [])
            if not groups and cfg.get("main_group_id"):
                groups = [{"id": cfg["main_group_id"], "title": "Grupo Principal"}]

            await query.answer(f"Transmitindo para {len(groups)} grupo(s)...")
            success_count = 0
            for g in groups:
                ok, _ = await self._execute_broadcast(context, user, g["id"], payload)
                if ok:
                    success_count += 1

            self.pending_broadcasts.pop(user.id, None)
            await query.edit_message_text(f"✅ <b>Mensagem transmitida com sucesso para {success_count} grupo(s)!</b>", parse_mode=ParseMode.HTML)
            return

        if data == "falar:send:all_channels":
            channels = cfg.get("linked_channels", [])
            if not channels and cfg.get("main_channel_id"):
                channels = [{"id": cfg["main_channel_id"], "title": "Canal Principal"}]

            await query.answer(f"Transmitindo para {len(channels)} canal(is)...")
            success_count = 0
            for c in channels:
                ok, _ = await self._execute_broadcast(context, user, c["id"], payload)
                if ok:
                    success_count += 1

            self.pending_broadcasts.pop(user.id, None)
            await query.edit_message_text(f"✅ <b>Mensagem transmitida com sucesso para {success_count} canal(is)!</b>", parse_mode=ParseMode.HTML)
            return

        if data == "falar:send:all":
            all_chats = get_all_linked_chats(cfg)
            await query.answer(f"Transmitindo para {len(all_chats)} chat(s)...")
            success_count = 0
            for c in all_chats:
                ok, _ = await self._execute_broadcast(context, user, c["id"], payload)
                if ok:
                    success_count += 1

            self.pending_broadcasts.pop(user.id, None)
            await query.edit_message_text(f"✅ <b>Mensagem transmitida com sucesso para {success_count} grupo(s) e canal(is)!</b>", parse_mode=ParseMode.HTML)
            return

    async def cmd_anunciar(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Envia mensagem como bot e FIXA no topo automaticamente (suporta canal, grupo ou ambos)."""
        chat = update.effective_chat
        user = update.effective_user
        msg = update.effective_message
        cfg = load_config()

        is_private = (chat.type == "private")
        if not is_private and not await self._require_admin(update):
            return

        if not is_private and msg:
            await safe_delete_message(context.bot, chat.id, msg.message_id)

        raw_html = msg.text_html or msg.text or ""
        text_to_send = re.sub(r"^\/\w+(?:@\w+)?\s*", "", raw_html).strip()
        if not text_to_send and msg.reply_to_message:
            reply = msg.reply_to_message
            text_to_send = reply.text_html or reply.caption_html or reply.text or reply.caption or ""

        if not text_to_send:
            channels = cfg.get("linked_channels", [])
            groups = cfg.get("linked_groups", [])
            await safe_reply(
                update,
                "📢 <b>Como usar o /anunciar (Fixar no Topo):</b>\n\n"
                "• <code>/anunciar canal &lt;texto&gt;</code> — Fixa anúncio no <b>Canal Principal</b>\n"
                "• <code>/anunciar grupo &lt;texto&gt;</code> — Fixa anúncio no <b>Grupo Principal</b>\n"
                "• <code>/anunciar todos &lt;texto&gt;</code> — Fixa anúncio em <b>Todos os Canais e Grupos</b>\n"
                "• <code>/anunciar &lt;texto&gt;</code> — Envia anúncio com menu de escolha de destino\n\n"
                f"<i>Status: {len(groups)} grupos e {len(channels)} canais vinculados.</i>",
                parse_mode=ParseMode.HTML
            )
            return

        # Verifica se o primeiro argumento indica o destino
        dest_mode = "auto"
        if text_to_send.lower().startswith("canal "):
            dest_mode = "channel"
            text_to_send = text_to_send[6:].strip()
        elif text_to_send.lower().startswith("grupo "):
            dest_mode = "group"
            text_to_send = text_to_send[6:].strip()
        elif text_to_send.lower().startswith("todos ") or text_to_send.lower().startswith("all "):
            dest_mode = "all"
            text_to_send = text_to_send[6:].strip()

        channels = cfg.get("linked_channels", [])
        groups = cfg.get("linked_groups", [])

        # Se for no privado e modo "auto" e temos canais e grupos, oferece os botões rápidos
        if is_private and dest_mode == "auto":
            if channels and groups:
                if not hasattr(self, "pending_anuncios"):
                    self.pending_anuncios = {}
                self.pending_anuncios[user.id] = text_to_send
                kb = InlineKeyboardMarkup([
                    [InlineKeyboardButton("📢 Fixar no Canal Principal", callback_data="cfg:anunciar:dest:channel")],
                    [InlineKeyboardButton("👥 Fixar no Grupo Principal", callback_data="cfg:anunciar:dest:group")],
                    [InlineKeyboardButton(f"🌐 Fixar em TODOS ({len(groups)}G + {len(channels)}C)", callback_data="cfg:anunciar:dest:all")],
                    [InlineKeyboardButton("❌ Cancelar", callback_data="cfg:anunciar:dest:cancel")]
                ])
                await msg.reply_text(
                    f"📢 <b>Onde você deseja publicar e fixar este comunicado?</b>\n\n"
                    f"<i>Prévia:</i>\n{html.escape(text_to_send[:250])}...",
                    reply_markup=kb,
                    parse_mode=ParseMode.HTML
                )
                return
            elif channels and not groups:
                dest_mode = "channel"
            else:
                dest_mode = "group"

        target_ids = []
        if dest_mode == "channel":
            cid = cfg.get("main_channel_id") or (channels[0]["id"] if channels else None)
            if cid:
                target_ids.append(cid)
            else:
                await msg.reply_text("⚠️ Nenhum canal vinculado. Use <code>/setcanal @seucanal</code> primeiro.", parse_mode=ParseMode.HTML)
                return
        elif dest_mode == "group":
            gid = cfg.get("main_group_id") or (groups[0]["id"] if groups else (chat.id if not is_private else None))
            if gid:
                target_ids.append(gid)
            else:
                await msg.reply_text("⚠️ Nenhum grupo principal configurado.", parse_mode=ParseMode.HTML)
                return
        elif dest_mode == "all":
            for g in groups:
                if g.get("id") and g["id"] not in target_ids:
                    target_ids.append(g["id"])
            if cfg.get("main_group_id") and cfg["main_group_id"] not in target_ids:
                target_ids.append(cfg["main_group_id"])
            for c in channels:
                if c.get("id") and c["id"] not in target_ids:
                    target_ids.append(c["id"])

        if not target_ids:
            target_ids = [chat.id]

        formatted = f"📢 <b>[COMUNICADO OFICIAL]</b>\n\n{text_to_send}"
        all_chats_map = {x["id"]: x.get("title", f"Chat {x['id']}") for x in groups + channels}

        success_chats = []
        fail_chats = []

        for tid in target_ids:
            try:
                sent_msg = await smart_send_message(
                    bot=context.bot,
                    chat_id=tid,
                    text=formatted
                )
                if sent_msg:
                    try:
                        await context.bot.pin_chat_message(
                            chat_id=tid,
                            message_id=sent_msg.message_id,
                            disable_notification=False
                        )
                    except Exception as e_pin:
                        logger.warning(f"Erro ao fixar no chat {tid}: {e_pin}")
                    c_title = all_chats_map.get(tid, str(tid))
                    success_chats.append(c_title)
            except Exception as e:
                logger.error(f"Erro ao enviar anúncio para {tid}: {e}")
                c_title = all_chats_map.get(tid, str(tid))
                fail_chats.append((c_title, str(e)))

        if is_private:
            report_lines = []
            if success_chats:
                report_lines.append(f"✅ <b>Anúncio enviado e fixado no topo com sucesso em ({len(success_chats)} chat(s)):</b>")
                for sc in success_chats:
                    report_lines.append(f"• <b>{html.escape(sc)}</b>")
            if fail_chats:
                report_lines.append("\n❌ <b>Falhas ao enviar:</b>")
                for fc, err in fail_chats:
                    report_lines.append(f"• <b>{html.escape(fc)}</b>: {html.escape(err)}")
            await msg.reply_text("\n".join(report_lines), parse_mode=ParseMode.HTML)

    async def handle_anunciar_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Gerencia os botões de seleção de destino do /anunciar."""
        query = update.callback_query
        user = update.effective_user
        data = query.data
        if not data.startswith("cfg:anunciar:dest:"):
            return

        choice = data.replace("cfg:anunciar:dest:", "")
        text_to_send = getattr(self, "pending_anuncios", {}).pop(user.id, None)

        if choice == "cancel" or not text_to_send:
            await query.answer("Anúncio cancelado.")
            try:
                await query.edit_message_text("❌ Anúncio cancelado.")
            except Exception:
                pass
            return

        await query.answer("Publicando comunicado...")
        cfg = load_config()
        channels = cfg.get("linked_channels", [])
        groups = cfg.get("linked_groups", [])

        target_ids = []
        if choice == "channel":
            cid = cfg.get("main_channel_id") or (channels[0]["id"] if channels else None)
            if cid:
                target_ids.append(cid)
        elif choice == "group":
            gid = cfg.get("main_group_id") or (groups[0]["id"] if groups else None)
            if gid:
                target_ids.append(gid)
        elif choice == "all":
            for g in groups:
                if g.get("id") and g["id"] not in target_ids:
                    target_ids.append(g["id"])
            if cfg.get("main_group_id") and cfg["main_group_id"] not in target_ids:
                target_ids.append(cfg["main_group_id"])
            for c in channels:
                if c.get("id") and c["id"] not in target_ids:
                    target_ids.append(c["id"])

        formatted = f"📢 <b>[COMUNICADO OFICIAL]</b>\n\n{text_to_send}"
        all_chats_map = {x["id"]: x.get("title", f"Chat {x['id']}") for x in groups + channels}

        success_chats = []
        fail_chats = []

        for tid in target_ids:
            try:
                sent_msg = await smart_send_message(
                    bot=context.bot,
                    chat_id=tid,
                    text=formatted
                )
                if sent_msg:
                    try:
                        await context.bot.pin_chat_message(
                            chat_id=tid,
                            message_id=sent_msg.message_id,
                            disable_notification=False
                        )
                    except Exception as e_pin:
                        logger.warning(f"Erro ao fixar no chat {tid}: {e_pin}")
                    c_title = all_chats_map.get(tid, str(tid))
                    success_chats.append(c_title)
            except Exception as e:
                logger.error(f"Erro ao enviar anúncio para {tid}: {e}")
                c_title = all_chats_map.get(tid, str(tid))
                fail_chats.append((c_title, str(e)))

        report_lines = []
        if success_chats:
            report_lines.append(f"✅ <b>Anúncio enviado e fixado no topo com sucesso em ({len(success_chats)} chat(s)):</b>")
            for sc in success_chats:
                report_lines.append(f"• <b>{html.escape(sc)}</b>")
        if fail_chats:
            report_lines.append("\n❌ <b>Falhas ao enviar:</b>")
            for fc, err in fail_chats:
                report_lines.append(f"• <b>{html.escape(fc)}</b>: {html.escape(err)}")

        try:
            await query.edit_message_text("\n".join(report_lines), parse_mode=ParseMode.HTML)
        except Exception:
            await query.message.reply_text("\n".join(report_lines), parse_mode=ParseMode.HTML)

    async def _auto_delete_test_msg(self, bot, chat_id, msg_id, delay):
        await asyncio.sleep(delay)
        try:
            await bot.delete_message(chat_id=chat_id, message_id=msg_id)
        except Exception:
            pass

    async def cmd_testecanal(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Diagnóstico em tempo real dos canais vinculados ao bot."""
        msg = update.effective_message
        if not await self._require_admin(update):
            await msg.reply_text("⛔ Apenas administradores podem testar canais.")
            return

        cfg = load_config()
        channels = cfg.get("linked_channels", [])
        if not channels:
            await msg.reply_text(
                "⚠️ <b>Nenhum canal vinculado ao bot!</b>\n\n"
                "Para vincular:\n"
                "1. Adicione o bot como Administrador no canal com permissão de <b>Postar mensagens</b>.\n"
                "2. No privado do bot, use <code>/setcanal @nomedoseucanal</code> (ou simplesmente encaminhe um post do canal para cá)!",
                parse_mode=ParseMode.HTML
            )
            return

        status_msg = await msg.reply_text("🔍 <b>Testando conexão e permissões nos canais...</b>", parse_mode=ParseMode.HTML)
        bot_me = await context.bot.get_me()
        lines = ["📢 <b>DIAGNÓSTICO DOS CANAIS VINCULADOS:</b>\n"]

        for idx, c in enumerate(channels, 1):
            cid = c.get("id")
            title = c.get("title", f"Canal {cid}")
            username = c.get("username", "")

            try:
                target_chat = await context.bot.get_chat(cid)
                member = await target_chat.get_member(bot_me.id)
                status = getattr(member, "status", "unknown")

                if status in ("administrator", "creator"):
                    can_post = getattr(member, "can_post_messages", None)
                    can_edit = getattr(member, "can_edit_messages", None)
                    can_pin = getattr(member, "can_pin_messages", None)

                    perm_status = []
                    if can_post is False:
                        perm_status.append("❌ <b>Postar: DESATIVADO</b> (Ative nas permissões do admin no Telegram!)")
                    else:
                        perm_status.append("✅ Postar: Liberado")

                    if can_pin is False:
                        perm_status.append("⚠️ Fixar: Desativado")
                    else:
                        perm_status.append("✅ Fixar: Liberado")

                    test_success = False
                    test_error = ""
                    try:
                        sent = await context.bot.send_message(
                            chat_id=cid,
                            text="🔔 <i>Teste de diagnóstico do Maestro Bot — Conexão OK!</i>",
                            parse_mode=ParseMode.HTML
                        )
                        test_success = True
                        asyncio.create_task(self._auto_delete_test_msg(context.bot, cid, sent.message_id, 5))
                    except Exception as e_send:
                        test_error = str(e_send)

                    if test_success:
                        lines.append(
                            f"{idx}. 📢 <b>{html.escape(title)}</b> {username}\n"
                            f"   • ID: <code>{cid}</code>\n"
                            f"   • Cargo: <b>{status.upper()}</b>\n"
                            f"   • Permissões: {', '.join(perm_status)}\n"
                            f"   • Teste de Disparo: <b>✅ SUCESSO! O canal recebeu o teste perfeitamente!</b>\n"
                        )
                    else:
                        lines.append(
                            f"{idx}. 📢 <b>{html.escape(title)}</b> {username}\n"
                            f"   • ID: <code>{cid}</code>\n"
                            f"   • Cargo: <b>{status.upper()}</b>\n"
                            f"   • Permissões: {', '.join(perm_status)}\n"
                            f"   • Teste de Disparo: <b>❌ FALHOU:</b> <code>{html.escape(test_error)}</code>\n"
                            f"   💡 <i>Ação: Abra o canal no Telegram ➔ Administradores ➔ toque no bot e ATIVE a permissão 'Postar Mensagens'.</i>\n"
                        )
                else:
                    lines.append(
                        f"{idx}. 📢 <b>{html.escape(title)}</b> {username}\n"
                        f"   • ID: <code>{cid}</code>\n"
                        f"   • Cargo: ⚠️ <b>{status.upper()}</b> (Não é Administrador!)\n"
                        f"   💡 <i>Ação: Promova o bot a Administrador do canal com permissão de postar mensagens.</i>\n"
                    )
            except Exception as e:
                lines.append(
                    f"{idx}. 📢 <b>{html.escape(title)}</b>\n"
                    f"   • ID: <code>{cid}</code>\n"
                    f"   • Conexão: ❌ <b>Erro ao acessar canal:</b> {html.escape(str(e))}\n"
                    f"   💡 <i>Ação: Verifique se o bot ainda está no canal ou se o canal foi excluído/alterado.</i>\n"
                )

        lines.append("━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
        lines.append("💡 <i>Para postar no canal: use <code>/canal &lt;texto&gt;</code>, <code>/anunciar canal &lt;texto&gt;</code> ou <code>/comunicado</code>!</i>")

        try:
            await status_msg.edit_text("\n".join(lines), parse_mode=ParseMode.HTML)
        except Exception:
            await msg.reply_text("\n".join(lines), parse_mode=ParseMode.HTML)

    async def cmd_info(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Exibe a ficha/perfil detalhado de um usuário."""
        chat = update.effective_chat
        msg = update.effective_message

        target_user = None
        if msg.reply_to_message and msg.reply_to_message.from_user:
            target_user = msg.reply_to_message.from_user
        elif context.args:
            arg = context.args[0]
            if arg.isdigit():
                try:
                    chat_member = await chat.get_member(user_id=int(arg))
                    target_user = chat_member.user
                except Exception:
                    pass
        else:
            target_user = msg.from_user

        await self._clean_admin_trigger(update)

        if not target_user:
            await safe_reply(update, "⚠️ Responda à mensagem de alguém com `/info` ou envie `/info [id]`.")
            return

        role = "Membro"
        if chat.type != "private":
            try:
                member = await chat.get_member(target_user.id)
                if member.status == "creator":
                    role = "👑 Dono / Criador"
                elif member.status == "administrator":
                    role = "⭐ Administrador"
                elif member.status == "restricted":
                    role = "🔇 Silenciado / Restrito"
                elif member.status in ("left", "kicked"):
                    role = "❌ Não pertence ao grupo"
            except Exception:
                pass

        w_key = (chat.id, target_user.id)
        warns = self.user_warnings.get(w_key, 0)
        user_name = target_user.first_name + (f" {target_user.last_name}" if target_user.last_name else "")
        username = f"@{target_user.username}" if target_user.username else "Sem @"

        info_text = (
            "👤 *INFORMAÇÕES DO USUÁRIO*\n\n"
            f"• *Nome:* `{user_name}`\n"
            f"• *ID:* `{target_user.id}`\n"
            f"• *Username:* {username}\n"
            f"• *Cargo no Grupo:* `{role}`\n"
            f"• *Advertências:* `{warns}/3`\n"
            f"• *Bot:* {'Sim 🤖' if target_user.is_bot else 'Não 👤'}\n"
            f"• *Link direto:* [Abrir Perfil](tg://user?id={target_user.id})"
        )
        await safe_reply(update, info_text, parse_mode=ParseMode.MARKDOWN)

    async def cmd_chatinfo(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Exibe informações sobre o chat atual (incluindo Chat ID)."""
        chat = update.effective_chat
        cfg = load_config()

        if chat and chat.type in ("group", "supergroup"):
            if cfg.get("main_group_id") != chat.id:
                cfg["main_group_id"] = chat.id
                save_config(cfg)

        await self._clean_admin_trigger(update)

        member_count = "N/D"
        try:
            member_count = await chat.get_member_count()
        except Exception:
            pass

        log_id = cfg.get("log_channel_id", "Não configurado")

        text = (
            "🏷️ *INFORMAÇÕES DO GRUPO*\n\n"
            f"• *Título:* `{chat.title or 'Privado'}`\n"
            f"• *Chat ID:* `{chat.id}`\n"
            f"• *Tipo:* `{chat.type}`\n"
            f"• *Total de Membros:* `{member_count}`\n"
            f"• *Canal de Log:* `{log_id}`\n"
            f"• *Fuso Horário:* `{cfg.get('timezone', 'America/Sao_Paulo')}`\n\n"
            "💡 _Use o Chat ID para configurar canais de logs e transmissões._"
        )
        await safe_reply(update, text, parse_mode=ParseMode.MARKDOWN)

    async def cmd_staff(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Lista os administradores e criador do grupo."""
        chat = update.effective_chat
        if chat.type == "private":
            await safe_reply(update, "⚠️ Use este comando dentro de um grupo.")
            return

        await self._clean_admin_trigger(update)

        try:
            admins = await chat.get_administrators()
            text = f"🛡️ *EQUIPE DE ADMINISTRAÇÃO - {chat.title}*\n\n"
            for a in admins:
                u = a.user
                name = u.first_name or "Admin"
                if a.status == "creator":
                    text += f"👑 *Criador:* {name} (`{u.id}`)\n"
                elif not u.is_bot:
                    text += f"⭐ *Admin:* {name} (`{u.id}`)\n"
            await safe_reply(update, text, parse_mode=ParseMode.MARKDOWN)
        except Exception as e:
            await safe_reply(update, f"❌ Não foi possível listar os administradores: {e}")

    async def cmd_setlog(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Define o ID do canal onde os registros de moderação serão enviados."""
        if not await self._require_admin(update):
            return

        msg = update.effective_message
        args = context.args or []
        await self._clean_admin_trigger(update)

        if not args:
            await safe_reply(
                update,
                "📡 *Configurar Canal de Logs:*\n\n"
                "Para ativar o canal de auditoria, adicione este bot como **Administrador** no canal/grupo de logs e envie:\n"
                "`/setlog <id_do_canal>`\n\n"
                "Exemplo: `/setlog -1001234567890`\n"
                "Para desativar: `/setlog desativar`",
                parse_mode=ParseMode.MARKDOWN
            )
            return

        target = args[0].strip()
        cfg = load_config()

        if target.lower() in ("desativar", "off", "remover", "none"):
            cfg["log_channel_id"] = None
            save_config(cfg)
            await msg.reply_text("✅ Canal de logs desativado com sucesso!")
            return

        try:
            channel_id = int(target)
            await context.bot.send_message(
                chat_id=channel_id,
                text="📡 *Canal de Logs Conectado com Sucesso!*\nTodas as ações de moderação e auditoria do grupo serão registradas aqui.",
                parse_mode=ParseMode.MARKDOWN
            )
            cfg["log_channel_id"] = channel_id
            save_config(cfg)
            await msg.reply_text(f"✅ *Canal de logs configurado com sucesso!* (ID: `{channel_id}`)\nMensagem de teste enviada ao canal.", parse_mode=ParseMode.MARKDOWN)
        except Exception as e:
            await msg.reply_text(
                f"❌ *Erro ao conectar ao canal:* `{e}`\n\n"
                "⚠️ Certifique-se de que o bot foi adicionado como **Administrador** no canal!",
                parse_mode=ParseMode.MARKDOWN
            )

    async def cmd_setgrupo(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Vincula um grupo à lista de grupos do bot (permite múltiplos grupos)."""
        chat = update.effective_chat
        msg = update.effective_message
        user = update.effective_user

        if not await self._require_admin(update):
            await safe_reply(update, "⛔ Apenas administradores podem vincular grupos.")
            return

        await self._clean_admin_trigger(update)

        cfg = load_config()

        try:
            target_id = None
            target_title = None
            target_type = "supergroup"

            if chat.type in ("group", "supergroup"):
                target_id = chat.id
                target_title = chat.title or "Grupo"
                target_type = chat.type
            elif context.args and (context.args[0].startswith("-") or context.args[0].isdigit()):
                try:
                    from config import normalize_chat_id
                    raw_id = context.args[0].strip()
                    if raw_id.lstrip("-").isdigit() and len(raw_id.lstrip("-")) >= 10:
                        target_id = normalize_chat_id(f"-100{raw_id.lstrip('-')}")
                    else:
                        target_id = normalize_chat_id(int(raw_id))
                    t_chat = await context.bot.get_chat(target_id)
                    target_title = t_chat.title or f"Grupo {target_id}"
                    target_type = t_chat.type
                except Exception:
                    target_title = f"Grupo {target_id}"

            if target_id:
                add_linked_group(cfg, target_id, target_title, target_type)
                groups = cfg.get("linked_groups", [])
                text = (
                    f"✅ <b>Grupo Vinculado com Sucesso!</b>\n\n"
                    f"• <b>Nome:</b> {html.escape(target_title)}\n"
                    f"• <b>ID:</b> <code>{target_id}</code>\n"
                    f"• <b>Total de Grupos Vinculados:</b> <b>{len(groups)}</b>\n\n"
                    f"👉 <b>Comandos úteis:</b>\n"
                    f"• <code>/grupos</code> — Lista todos os grupos e canais vinculados\n"
                    f"• <code>/falar {target_id} &lt;mensagem&gt;</code> — Envia mensagem específica para este grupo\n"
                    f"• <code>/transmitir &lt;mensagem&gt;</code> — Transmite para TODOS os grupos e canais vinculados!\n"
                    f"• <code>/desvincular {target_id}</code> — Desvincula este grupo\n\n"
                    f"💡 <i>Você pode vincular quantos grupos quiser!</i>"
                )
                await safe_reply(update, text, parse_mode=ParseMode.HTML)
            else:
                await safe_reply(
                    update,
                    "⚠️ <b>Como vincular grupos:</b>\n\n"
                    "1. Envie <code>/setgrupo</code> diretamente dentro de qualquer grupo onde o bot é administrador.\n"
                    "2. Ou envie <code>/setgrupo &lt;id_do_grupo&gt;</code> aqui no privado (ex: <code>/setgrupo -1001234567890</code>).\n\n"
                    "💡 <i>Você pode vincular quantos grupos desejar! O bot gerencia todos eles simultaneamente.</i>",
                    parse_mode=ParseMode.HTML
                )
        except Exception as e:
            logger.error(f"Erro no cmd_setgrupo: {e}")
            await safe_reply(update, f"❌ Erro ao vincular grupo: {e}")

    async def cmd_desvincular(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Desvincula um grupo da lista de grupos vinculados."""
        chat = update.effective_chat
        msg = update.effective_message

        if not await self._require_admin(update):
            await safe_reply(update, "⛔ Apenas administradores podem desvincular grupos.")
            return

        await self._clean_admin_trigger(update)

        cfg = load_config()
        target_id = None

        if chat.type in ("group", "supergroup"):
            target_id = chat.id
        elif context.args and (context.args[0].startswith("-") or context.args[0].isdigit()):
            target_id = int(context.args[0])

        if not target_id:
            await safe_reply(
                update,
                "⚠️ Uso: Envie <code>/desvincular</code> dentro do grupo ou <code>/desvincular &lt;id_do_grupo&gt;</code>.",
                parse_mode=ParseMode.HTML
            )
            return

        removed = remove_linked_group(cfg, target_id)
        if removed:
            await safe_reply(
                update,
                f"🗑️ <b>Grupo desvinculado com sucesso!</b> (ID: <code>{target_id}</code>)\n"
                f"Grupos restantes: <b>{len(cfg.get('linked_groups', []))}</b>",
                parse_mode=ParseMode.HTML
            )
        else:
            await safe_reply(update, f"⚠️ Grupo com ID <code>{target_id}</code> não estava na lista de vinculados.", parse_mode=ParseMode.HTML)

    async def cmd_setcanal(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Vincula um ou múltiplos canais Telegram para postagens automáticas e manuais."""
        msg = update.effective_message

        if not await self._require_admin(update):
            await msg.reply_text("⛔ Apenas administradores podem vincular canais.")
            return

        if not context.args:
            await msg.reply_text(
                "📢 <b>Como vincular Canais ao Bot:</b>\n\n"
                "1. Adicione este bot como <b>Administrador</b> no seu Canal com permissão para <b>Postar mensagens</b>.\n"
                "2. Envie aqui no privado:\n"
                "   <code>/setcanal @nomedoseucanal</code>\n"
                "   ou para múltiplos canais de uma vez só:\n"
                "   <code>/setcanal @canal1 @canal2 @canal3</code>\n"
                "   ou pelo ID numérico:\n"
                "   <code>/setcanal -1001234567890</code>\n\n"
                "⚡ <b>Método Mais Rápido (Auto-Vínculo Instantâneo):</b>\n"
                "Você pode simplesmente <b>encaminhar qualquer postagem do seu canal</b> aqui para o privado do bot! Ele detecta o canal, confere se é admin e vincula na mesma hora!",
                parse_mode=ParseMode.HTML
            )
            return

        cfg = load_config()
        success_list = []
        error_list = []

        for raw_arg in context.args:
            arg = raw_arg.strip(",; \n\r")
            if not arg:
                continue
            from config import normalize_chat_id
            if arg.lstrip("-").isdigit() and len(arg.lstrip("-")) >= 10:
                norm_arg = str(normalize_chat_id(f"-100{arg.lstrip('-')}"))
            else:
                norm_arg = str(normalize_chat_id(arg))
            try:
                try:
                    target_chat = await context.bot.get_chat(norm_arg)
                except Exception:
                    target_chat = await context.bot.get_chat(arg)
                if target_chat.type not in ("channel", "supergroup", "group"):
                    error_list.append(f"• <code>{arg}</code>: Chat inválido ({target_chat.type}).")
                    continue

                bot_me = await context.bot.get_me()
                try:
                    bot_member = await target_chat.get_member(bot_me.id)
                    if bot_member.status not in ("administrator", "creator"):
                        error_list.append(f"• <code>{arg}</code>: O bot precisa ser <b>Administrador</b> no canal ou grupo!")
                        continue
                except Exception:
                    pass

                title = target_chat.title or f"Chat {target_chat.id}"
                username = f"@{target_chat.username}" if target_chat.username else ""

                add_linked_channel(cfg, target_chat.id, title, username)
                success_list.append((target_chat.id, title, username, target_chat.type))
            except Exception as e:
                logger.error(f"Erro ao vincular canal {arg}: {e}")
                error_list.append(f"• <code>{arg}</code>: {e}")

        channels = cfg.get("linked_channels", [])
        if success_list:
            if len(success_list) == 1 and not error_list:
                cid, title, username, c_type = success_list[0]
                type_lbl = "Canal" if c_type == "channel" else "Supergrupo"
                text = (
                    f"✅ <b>{type_lbl} Vinculado com Sucesso!</b> 📢\n\n"
                    f"• <b>Nome:</b> {html.escape(title)}\n"
                    f"• <b>ID:</b> <code>{cid}</code>\n"
                    f"• <b>Tipo:</b> <code>{c_type}</code>\n"
                    f"• <b>Link/User:</b> {html.escape(username or 'Privado')}\n"
                    f"• <b>Total de Destinos Vinculados:</b> <b>{len(channels)}</b>\n\n"
                    f"👉 <b>Como postar:</b>\n"
                    f"Envie aqui no privado:\n"
                    f"<code>/canal Sua mensagem com negrito, itálico, spoilers ou botões</code>\n"
                    f"ou use <code>/comunicado</code> para abrir o Assistente de Transmissão!"
                )
                await msg.reply_text(text, parse_mode=ParseMode.HTML)
            else:
                lines = [f"✅ <b>{len(success_list)} Canal(is) Vinculado(s) com Sucesso!</b> 📢\n"]
                for item in success_list:
                    cid, title, username = item[0], item[1], item[2]
                    u_str = f" ({username})" if username else ""
                    lines.append(f"• <b>{html.escape(title)}</b>{u_str} — <code>{cid}</code>")
                lines.append(f"\n📊 <b>Total de canais vinculados agora:</b> <b>{len(channels)}</b>")
                if error_list:
                    lines.append("\n⚠️ <b>Avisos / Não foi possível conectar em:</b>")
                    lines.extend(error_list)
                    lines.append("\n<i>Verifique se o bot foi adicionado como Administrador com permissão de postar.</i>")
                await msg.reply_text("\n".join(lines), parse_mode=ParseMode.HTML)
        else:
            err_text = "\n".join(error_list) if error_list else "Nenhum canal válido informado."
            await msg.reply_text(
                f"❌ <b>Não foi possível vincular os canais:</b>\n{err_text}\n\n"
                "Verifique se o bot foi adicionado como Administrador no canal antes de vincular!",
                parse_mode=ParseMode.HTML
            )

    async def cmd_desvincularcanal(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Desvincula um canal da lista de canais vinculados."""
        msg = update.effective_message
        if not await self._require_admin(update):
            await msg.reply_text("⛔ Apenas administradores podem desvincular canais.")
            return

        if not context.args:
            await msg.reply_text("⚠️ Uso: <code>/desvincularcanal &lt;id_ou_@username&gt;</code>", parse_mode=ParseMode.HTML)
            return

        arg = context.args[0].strip()
        cfg = load_config()
        target_id = None
        if arg.startswith("-") or arg.isdigit():
            target_id = int(arg)
        else:
            clean_user = arg.lower().lstrip("@")
            for c in cfg.get("linked_channels", []):
                if c.get("username", "").lower().lstrip("@") == clean_user:
                    target_id = c.get("id")
                    break

        if not target_id:
            try:
                c_chat = await context.bot.get_chat(arg)
                target_id = c_chat.id
            except Exception:
                pass

        if not target_id:
            await msg.reply_text("❌ Canal não encontrado na lista de vinculados.", parse_mode=ParseMode.HTML)
            return

        removed = remove_linked_channel(cfg, target_id)
        if removed:
            await msg.reply_text(
                f"🗑️ <b>Canal desvinculado com sucesso!</b> (ID: <code>{target_id}</code>)\n"
                f"Canais restantes: <b>{len(cfg.get('linked_channels', []))}</b>",
                parse_mode=ParseMode.HTML
            )
        else:
            await msg.reply_text(f"⚠️ Canal com ID <code>{target_id}</code> não estava vinculado.", parse_mode=ParseMode.HTML)

    async def cmd_chats(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Lista todos os grupos e canais vinculados ao bot."""
        if not await self._require_admin(update):
            await safe_reply(update, "⛔ Apenas administradores podem listar chats vinculados.")
            return

        await self._clean_admin_trigger(update)

        cfg = load_config()
        groups = cfg.get("linked_groups", [])
        channels = cfg.get("linked_channels", [])
        main_grp = cfg.get("main_group_id")
        main_ch = cfg.get("main_channel_id")

        lines = ["🌐 <b>CHATS VINCULADOS AO BOT</b>\n"]

        lines.append(f"👥 <b>Grupos Vinculados ({len(groups)}):</b>")
        if not groups:
            lines.append("<i>Nenhum grupo vinculado ainda. Envie /setgrupo dentro de um grupo!</i>")
        else:
            for idx, g in enumerate(groups, 1):
                gid = g.get("id")
                gtitle = html.escape(g.get("title", f"Grupo {gid}"))
                is_m = " ⭐️ [Principal]" if gid == main_grp else ""
                lines.append(f"  {idx}. <b>{gtitle}</b>{is_m}\n     ID: <code>{gid}</code>")

        lines.append("")
        lines.append(f"📢 <b>Canais Vinculados ({len(channels)}):</b>")
        if not channels:
            lines.append("<i>Nenhum canal vinculado ainda. Envie /setcanal @seucanal!</i>")
        else:
            for idx, c in enumerate(channels, 1):
                cid = c.get("id")
                ctitle = html.escape(c.get("title", f"Canal {cid}"))
                cuser = f" ({c.get('username')})" if c.get("username") else ""
                is_m = " ⭐️ [Principal]" if cid == main_ch else ""
                lines.append(f"  {idx}. <b>{ctitle}</b>{cuser}{is_m}\n     ID: <code>{cid}</code>")

        lines.append("\n👉 <b>Ações Rápidas:</b>")
        lines.append("• <code>/falar &lt;texto&gt;</code> — Envia para o grupo principal")
        lines.append("• <code>/falar &lt;id_do_grupo&gt; &lt;texto&gt;</code> — Envia para um grupo específico")
        lines.append("• <code>/canal &lt;texto&gt;</code> — Envia para o canal com formatação rica")
        lines.append("• <code>/transmitir &lt;texto&gt;</code> — Envia para TODOS os grupos e canais ao mesmo tempo")

        await safe_reply(update, "\n".join(lines), parse_mode=ParseMode.HTML)

    async def cmd_canal(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Envia uma postagem rica diretamente para o canal vinculado com todas as formatações das mensagens repetidas."""
        msg = update.effective_message
        user = update.effective_user
        cfg = load_config()

        channels = cfg.get("linked_channels", [])
        if not channels:
            await msg.reply_text(
                "⚠️ <b>Nenhum canal vinculado ainda!</b>\n\n"
                "Para vincular um canal:\n"
                "1. Adicione o bot como administrador no seu canal com permissão de postar.\n"
                "2. Envie aqui: <code>/setcanal @nomedoseucanal</code> ou <code>/setcanal -100...</code>",
                parse_mode=ParseMode.HTML
            )
            return

        if not await self._require_admin(update):
            await msg.reply_text("⛔ Apenas administradores podem postar no canal.")
            return

        raw_html = msg.text_html or msg.text or ""
        body_html = re.sub(r"^\/\w+(?:@\w+)?\s*", "", raw_html).strip()

        target_channel_id = cfg.get("main_channel_id") or channels[0]["id"]
        pin_post = False

        # Verifica se o primeiro argumento é o ID ou username de outro canal vinculado
        m_target = re.match(r"^(-100\d+|-\d+|@\w+)\s*([\s\S]*)", body_html)
        if m_target:
            cand = m_target.group(1)
            for c in channels:
                if str(c.get("id")) == cand or (c.get("username") and c.get("username").lower() == cand.lower()):
                    target_channel_id = c.get("id")
                    body_html = m_target.group(2).strip()
                    break

        if body_html.lower().startswith("pin "):
            pin_post = True
            body_html = body_html[4:].strip()

        text_to_send = body_html
        reply = msg.reply_to_message

        photo = None
        document = None
        audio = None
        voice = None
        video = None

        if reply:
            if reply.photo:
                photo = reply.photo[-1].file_id
                if not text_to_send:
                    text_to_send = reply.caption_html or reply.caption or ""
            elif reply.document:
                document = reply.document.file_id
                if not text_to_send:
                    text_to_send = reply.caption_html or reply.caption or ""
            elif reply.audio:
                audio = reply.audio.file_id
                if not text_to_send:
                    text_to_send = reply.caption_html or reply.caption or ""
            elif reply.video:
                video = reply.video.file_id
                if not text_to_send:
                    text_to_send = reply.caption_html or reply.caption or ""
            elif reply.voice:
                voice = reply.voice.file_id
            elif not text_to_send:
                text_to_send = reply.text_html or reply.text or ""
        elif msg.photo:
            photo = msg.photo[-1].file_id
            if not text_to_send:
                cap_html = msg.caption_html or msg.caption or ""
                text_to_send = re.sub(r"^/\w+(?:@\w+)?\s*", "", cap_html).strip()

        if not text_to_send and not photo and not document and not audio and not voice and not video:
            await msg.reply_text(
                "⚠️ <b>Como postar no canal:</b>\n\n"
                "• <code>/canal &lt;sua postagem&gt;</code>\n"
                "• <code>/canal pin &lt;postagem para fixar no topo&gt;</code>\n"
                "• Ou <b>responda</b> a uma foto, partitura em PDF, áudio ou post com <code>/canal</code> para publicar diretamente no canal com todos os botões e formatações!\n\n"
                "💡 <i>Suporta negrito (Ctrl+B), itálico, spoilers, artigos expansíveis (&gt;&gt;) e botões em grade: [Texto - Link]</i>",
                parse_mode=ParseMode.HTML
            )
            return

        extracted_btns = parse_rich_buttons(text_to_send)
        markup = build_rich_buttons_markup(extracted_btns) if extracted_btns else None
        if extracted_btns:
            lines = text_to_send.split("\n")
            clean_lines = [l for l in lines if not parse_rich_buttons(l)]
            text_to_send = "\n".join(clean_lines).strip()

        sent_msg = None
        try:
            if reply and not body_html and not extracted_btns:
                try:
                    sent_msg = await context.bot.copy_message(
                        chat_id=target_channel_id,
                        from_chat_id=reply.chat.id,
                        message_id=reply.message_id
                    )
                except Exception as e_copy:
                    logger.debug(f"copy_message para canal falhou ({e_copy}), enviando normal...")

            if not sent_msg:
                if photo:
                    sent_msg = await smart_send_photo(
                        bot=context.bot,
                        chat_id=target_channel_id,
                        photo=photo,
                        caption=text_to_send,
                        reply_markup=markup
                    )
                elif document:
                    try:
                        sent_msg = await context.bot.send_document(
                            chat_id=target_channel_id,
                            document=document,
                            caption=convert_rich_text(text_to_send),
                            parse_mode=ParseMode.HTML,
                            reply_markup=markup
                        )
                    except Exception:
                        sent_msg = await context.bot.send_document(
                            chat_id=target_channel_id,
                            document=document,
                            caption=text_to_send,
                            reply_markup=markup
                        )
                elif audio:
                    sent_msg = await context.bot.send_audio(
                        chat_id=target_channel_id,
                        audio=audio,
                        caption=convert_rich_text(text_to_send),
                        parse_mode=ParseMode.HTML,
                        reply_markup=markup
                    )
                elif video:
                    sent_msg = await context.bot.send_video(
                        chat_id=target_channel_id,
                        video=video,
                        caption=convert_rich_text(text_to_send),
                        parse_mode=ParseMode.HTML,
                        reply_markup=markup
                    )
                elif voice:
                    sent_msg = await context.bot.send_voice(
                        chat_id=target_channel_id,
                        voice=voice
                    )
                else:
                    sent_msg = await smart_send_message(
                        bot=context.bot,
                        chat_id=target_channel_id,
                        text=text_to_send,
                        reply_markup=markup
                    )

            if pin_post and sent_msg:
                try:
                    await context.bot.pin_chat_message(
                        chat_id=target_channel_id,
                        message_id=sent_msg.message_id
                    )
                except Exception as e_pin:
                    logger.warning(f"Erro ao fixar no canal: {e_pin}")

            c_info = next((c for c in channels if c.get("id") == target_channel_id), {})
            c_name = c_info.get("title", f"Canal {target_channel_id}")
            pin_note = " e fixada no topo" if pin_post else ""
            await msg.reply_text(f"✅ <b>Mensagem publicada{pin_note} com sucesso no canal {html.escape(c_name)}!</b>", parse_mode=ParseMode.HTML)
            logger.info(f"Admin {user.id} postou mensagem no canal {target_channel_id}")

        except Exception as e:
            logger.error(f"Erro ao postar no canal {target_channel_id}: {e}")
            await msg.reply_text(f"❌ <b>Erro ao postar no canal:</b> {e}", parse_mode=ParseMode.HTML)

    async def cmd_transmitir(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Transmite uma mensagem para TODOS os grupos e canais vinculados simultaneamente."""
        msg = update.effective_message
        user = update.effective_user
        cfg = load_config()

        if not await self._require_admin(update):
            await msg.reply_text("⛔ Apenas administradores podem fazer transmissões globais.")
            return

        all_chats = get_all_linked_chats(cfg)
        if not all_chats:
            await msg.reply_text(
                "⚠️ <b>Nenhum grupo ou canal vinculado!</b>\nUse <code>/setgrupo</code> nos grupos e <code>/setcanal</code> no canal primeiro.",
                parse_mode=ParseMode.HTML
            )
            return

        raw_html = msg.text_html or msg.text or ""
        body_html = re.sub(r"^\/\w+(?:@\w+)?\s*", "", raw_html).strip()

        text_to_send = body_html
        reply = msg.reply_to_message

        photo = None
        document = None
        if reply:
            if reply.photo:
                photo = reply.photo[-1].file_id
                if not text_to_send:
                    text_to_send = reply.caption_html or reply.caption or ""
            elif reply.document:
                document = reply.document.file_id
                if not text_to_send:
                    text_to_send = reply.caption_html or reply.caption or ""
            elif not text_to_send:
                text_to_send = reply.text_html or reply.text or ""
        elif msg.photo:
            photo = msg.photo[-1].file_id
            if not text_to_send:
                cap_html = msg.caption_html or msg.caption or ""
                text_to_send = re.sub(r"^/\w+(?:@\w+)?\s*", "", cap_html).strip()

        if not text_to_send and not photo and not document:
            await msg.reply_text(
                "📢 <b>Transmissão Geral (/transmitir):</b>\n\n"
                "Uso: <code>/transmitir &lt;mensagem&gt;</code>\n"
                "Ou responda a uma foto/documento/texto com <code>/transmitir</code>.\n\n"
                f"Esta mensagem será enviada com todas as formatações para <b>{len(all_chats)} chats</b> ({len(cfg.get('linked_groups', []))} grupos e {len(cfg.get('linked_channels', []))} canais)!",
                parse_mode=ParseMode.HTML
            )
            return

        extracted_btns = parse_rich_buttons(text_to_send)
        markup = build_rich_buttons_markup(extracted_btns) if extracted_btns else None
        if extracted_btns:
            lines = text_to_send.split("\n")
            clean_lines = [l for l in lines if not parse_rich_buttons(l)]
            text_to_send = "\n".join(clean_lines).strip()

        status_msg = await msg.reply_text(f"⏳ Transmitindo para {len(all_chats)} chats vinculados...")

        success_count = 0
        error_count = 0

        for chat_item in all_chats:
            cid = chat_item["id"]
            try:
                if photo:
                    await smart_send_photo(bot=context.bot, chat_id=cid, photo=photo, caption=text_to_send, reply_markup=markup)
                elif document:
                    try:
                        await context.bot.send_document(chat_id=cid, document=document, caption=convert_rich_text(text_to_send), parse_mode=ParseMode.HTML, reply_markup=markup)
                    except Exception:
                        await context.bot.send_document(chat_id=cid, document=document, caption=text_to_send, reply_markup=markup)
                else:
                    await smart_send_message(bot=context.bot, chat_id=cid, text=text_to_send, reply_markup=markup)
                success_count += 1
            except Exception as e:
                logger.error(f"Erro ao transmitir para chat {cid}: {e}")
                error_count += 1

        await status_msg.edit_text(
            f"📢 <b>Transmissão Concluída!</b>\n\n"
            f"✅ Enviado com sucesso para: <b>{success_count}</b> chat(s)\n"
            f"{f'❌ Falhas: <b>{error_count}</b>' if error_count > 0 else ''}",
            parse_mode=ParseMode.HTML
        )

    async def cmd_ajuda(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Exibe a central de ajuda interativa com categorias e explicações detalhadas."""
        msg = update.effective_message

        is_adm = await self._require_admin(update, auto_clean=False)

        cat_data = HELP_CATEGORIES["main"]
        header = f"{cat_data['title']}\n\n{cat_data['text']}"

        if not is_adm:
            # Não-admin vê apenas a lista de comandos gerais
            user_text = (
                "🤖 <b>Comandos Disponíveis:</b>\n\n"
                "• <code>/regras</code> - Exibe as regras oficiais do grupo\n"
                "• <code>/info</code> (ou em resposta) - Exibe ficha do usuário\n"
                "• <code>/warns</code> - Consulta suas advertências ativas\n"
                "• <code>/staff</code> - Lista os administradores do grupo\n"
                "• <code>/ajuda</code> - Mostra esta mensagem\n\n"
                "<i>Dúvidas ou suporte? Fale com a equipe de administração!</i>"
            )
            await msg.reply_text(user_text, parse_mode=ParseMode.HTML)
            return

        reply_markup = InlineKeyboardMarkup(cat_data["buttons"])
        try:
            await msg.reply_text(header, reply_markup=reply_markup, parse_mode=ParseMode.HTML)
        except Exception:
            await msg.reply_text(header, reply_markup=reply_markup)

    async def handle_help_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Gerencia os cliques nos botões da central de ajuda."""
        query = update.callback_query
        data = query.data

        if not data.startswith("help:cat:"):
            return

        cat_key = data.split(":")[-1]
        cat_data = HELP_CATEGORIES.get(cat_key, HELP_CATEGORIES["main"])

        header = f"{cat_data['title']}\n\n{cat_data['text']}"
        reply_markup = InlineKeyboardMarkup(cat_data["buttons"])

        try:
            await query.edit_message_text(header, reply_markup=reply_markup, parse_mode=ParseMode.HTML)
        except Exception as e:
            logger.debug(f"Falha ao editar menu de ajuda: {e}")

        await query.answer()

    async def cmd_backup(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Envia o arquivo config.json atual para o administrador fazer download."""
        msg = update.effective_message
        if not await self._require_admin(update):
            await msg.reply_text("⛔ Apenas administradores podem fazer backup das configurações.")
            return

        await self._clean_admin_trigger(update)

        try:
            cfg = load_config()
            cfg_bytes = json.dumps(cfg, indent=2, ensure_ascii=False).encode("utf-8")

            rec_cnt = len(cfg.get("recurring_messages", []))
            res_cnt = len(cfg.get("auto_responses", []))
            main_grp = cfg.get("main_group_id")

            caption = (
                "📦 *Backup do Sistema do Bot*\n\n"
                f"• *Mensagens Programadas:* `{rec_cnt}`\n"
                f"• *Respostas Automáticas:* `{res_cnt}`\n"
                f"• *Grupo Principal:* `{main_grp or 'Não vinculado'}`\n\n"
                "💡 *Como usar este backup:*\n"
                "1. Guarde este arquivo em um local seguro ou no Telegram.\n"
                "2. Se você atualizar o bot na nuvem (Discloud) ou quiser restaurar tudo, "
                "basta enviar este arquivo no privado do bot com a legenda `/restaurar` (ou responder a ele com `/restaurar`)."
            )

            await update.effective_chat.send_document(
                document=io.BytesIO(cfg_bytes),
                filename="config.json",
                caption=caption,
                parse_mode=ParseMode.MARKDOWN
            )
        except Exception as e:
            logger.error(f"Erro ao gerar backup: {e}")
            await msg.reply_text(f"❌ Erro ao gerar backup: {e}")

    async def cmd_restaurar(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Restaura o arquivo config.json a partir de um documento enviado pelo admin."""
        msg = update.effective_message
        if not await self._require_admin(update):
            await msg.reply_text("⛔ Apenas administradores podem restaurar configurações.")
            return

        await self._clean_admin_trigger(update)

        doc = msg.document
        if not doc and msg.reply_to_message and msg.reply_to_message.document:
            doc = msg.reply_to_message.document

        if not doc:
            await msg.reply_text(
                "⚠️ *Como restaurar o backup:*\n\n"
                "1. Envie o arquivo `config.json` no privado do bot com a legenda `/restaurar`.\n"
                "2. Ou responda a um arquivo `config.json` enviado anteriormente digitando `/restaurar`.",
                parse_mode=ParseMode.MARKDOWN
            )
            return

        if not (doc.file_name and doc.file_name.endswith(".json")):
            await msg.reply_text("❌ Por favor, envie um arquivo `.json` válido (ex: `config.json`).")
            return

        try:
            telegram_file = await doc.get_file()
            file_bytes = await telegram_file.download_as_bytearray()
            raw_text = file_bytes.decode("utf-8")
            new_cfg = json.loads(raw_text)

            if not isinstance(new_cfg, dict):
                await msg.reply_text("❌ Formato inválido. O arquivo deve conter um objeto JSON válido.")
                return

            current_cfg = load_config()
            # Preserva o bot token atual se o enviado não tiver
            if not new_cfg.get("telegram_bot_token") and current_cfg.get("telegram_bot_token"):
                new_cfg["telegram_bot_token"] = current_cfg["telegram_bot_token"]

            save_config(new_cfg)

            rec_cnt = len(new_cfg.get("recurring_messages", []))
            res_cnt = len(new_cfg.get("auto_responses", []))
            main_grp = new_cfg.get("main_group_id")

            text = (
                "✅ *Configurações Restauradas com Sucesso!*\n\n"
                f"• *Mensagens Programadas restauradas:* `{rec_cnt}`\n"
                f"• *Respostas Automáticas restauradas:* `{res_cnt}`\n"
                f"• *Grupo Principal:* `{main_grp or 'Não vinculado'}`\n\n"
                "🎉 O bot carregou tudo com sucesso e está operando normalmente com seus dados!"
            )
            await msg.reply_text(text, parse_mode=ParseMode.MARKDOWN)
        except Exception as e:
            logger.error(f"Erro ao restaurar backup: {e}")
            await msg.reply_text(f"❌ Erro ao restaurar configurações: {e}")

    async def cmd_report(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Permite que membros reportem mensagens ofensivas ou spam para a moderação (Estilo Rose Bot)."""
        msg = update.effective_message
        chat = update.effective_chat
        user = update.effective_user

        if not chat or chat.type == "private":
            await msg.reply_text("Este comando só funciona em grupos.")
            return

        reply = msg.reply_to_message
        if not reply:
            await msg.reply_text("⚠️ Responda à mensagem que deseja denunciar usando `/report [motivo]`.", parse_mode=ParseMode.MARKDOWN)
            return

        reason = " ".join(context.args).strip() if context.args else "Possível violação de regras"
        reported_user = reply.from_user

        confirm_text = f"🚨 *Denúncia enviada aos administradores!* Obrigado por ajudar a manter o grupo seguro."
        sent = await msg.reply_text(confirm_text, parse_mode=ParseMode.MARKDOWN)
        schedule_message_deletion(context, chat.id, sent.message_id, 8)
        await self._clean_admin_trigger(update)

        reported_info = f"{html.escape(reported_user.first_name)} (<code>{reported_user.id}</code>)" if reported_user else "Desconhecido"
        reporter_info = f"{html.escape(user.first_name)} (<code>{user.id}</code>)"
        msg_link = f"https://t.me/c/{str(chat.id).replace('-100', '')}/{reply.message_id}" if str(chat.id).startswith("-100") else ""

        await send_mod_log(
            bot=context.bot,
            event_type="warn",
            title="🚨 Denúncia de Membro (/report)",
            user_info=reported_info,
            reason=reason,
            details=f"<b>Denunciado por:</b> {reporter_info}\n<b>Link da Mensagem:</b> {msg_link or 'N/A'}"
        )

    async def cmd_vincularmsg(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Vincula uma mensagem recorrente ao grupo atual e opcionalmente ao tópico atual, clonando a mensagem se for resposta."""
        msg = update.effective_message
        chat = update.effective_chat
        user = update.effective_user

        if not chat or chat.type == "private":
            await safe_reply(update, "⚠️ Este comando deve ser executado dentro do grupo (ou do tópico) onde você deseja que a mensagem repetida seja enviada.")
            return

        if not await self._require_admin(update):
            await safe_reply(update, "⛔ Apenas administradores podem vincular mensagens programadas.")
            return

        await self._clean_admin_trigger(update)

        if not context.args or not context.args[0].isdigit():
            await safe_reply(
                update,
                "🎯 *Como vincular mensagem repetida a este grupo/tópico:*\n\n"
                "Uso: `/vincularmsg <ID_DA_MENSAGEM>`\n"
                "_Exemplo:_ `/vincularmsg 1` ou `/vincularmsg 2`\n\n"
                "💡 *Super Dica:* Se você responder a uma postagem do grupo (com artigos, botões e formatação rica) com `/vincularmsg 1`, "
                "o bot irá clonar a postagem inteira com 100% de fidelidade para os envios programados!\n\n"
                "👉 Para gerenciar suas mensagens, use `/config` no privado do bot -> **⏱️ Msg Repetidas**.",
                parse_mode=ParseMode.MARKDOWN
            )
            return

        msg_id = int(context.args[0])
        cfg = load_config()

        # Garante que o grupo atual esteja registrado nas configurações gerais e no modo noturno
        if not cfg.get("main_group_id"):
            cfg["main_group_id"] = chat.id
        nm = cfg.setdefault("night_mode", {})
        c_list = nm.setdefault("enabled_chats", [])
        if chat.id not in c_list:
            c_list.append(chat.id)

        rec_list = cfg.setdefault("recurring_messages", [])

        target_item = None
        for item in rec_list:
            if item.get("id") == msg_id:
                target_item = item
                break

        if not target_item:
            target_item = {
                "id": msg_id,
                "enabled": True,
                "text": "📢 Postagem Programada",
                "photo": None,
                "buttons": [],
                "repeat_mode": "interval",
                "interval_type": "hours",
                "interval_value": 24,
                "interval_minutes": 1440,
                "messages_interval": 50,
                "messages_counter_last": 0,
                "start_hour": None,
                "start_minute": None,
                "weekdays": [0, 1, 2, 3, 4, 5, 6],
                "month_days": [],
                "start_date": None,
                "end_date": None,
                "pin_message": False,
                "delete_previous": False,
                "auto_delete_seconds": 0,
                "last_message_id": None,
                "last_sent_timestamp": 0,
                "chat_id": chat.id,
                "message_thread_id": None
            }
            rec_list.append(target_item)

        # Atualiza chat_id e message_thread_id
        target_item["chat_id"] = chat.id
        thread_id = getattr(msg, "message_thread_id", None)
        target_item["message_thread_id"] = thread_id

        # Se o comando foi executado respondendo a uma mensagem existente, CLONA A MENSAGEM NATIVAMENTE!
        replied = msg.reply_to_message
        clone_info = ""
        if replied:
            target_item["source_chat_id"] = chat.id
            target_item["source_message_id"] = replied.message_id
            target_item["backup_chat_id"] = chat.id
            target_item["backup_message_id"] = replied.message_id

            # Fallbacks textuais e de mídia
            raw_text = None
            try:
                raw_text = replied.text_html or replied.caption_html or replied.text or replied.caption
            except Exception:
                pass
            if raw_text:
                target_item["text"] = raw_text

            try:
                if replied.photo:
                    target_item["photo"] = replied.photo[-1].file_id
            except Exception:
                pass

            # Extração dos botões para backup
            extracted_btns = []
            try:
                if replied.reply_markup and getattr(replied.reply_markup, "inline_keyboard", None):
                    for row in replied.reply_markup.inline_keyboard:
                        row_btns = []
                        for btn in row:
                            url = getattr(btn, "url", None)
                            if not url and getattr(btn, "web_app", None):
                                url = getattr(btn.web_app, "url", None)
                            if not url and getattr(btn, "login_url", None):
                                url = getattr(btn.login_url, "url", None)
                            if url:
                                row_btns.append({"text": btn.text, "url": url})
                        if row_btns:
                            extracted_btns.append(row_btns)
                    if extracted_btns:
                        target_item["buttons"] = extracted_btns
            except Exception:
                pass

            total_btns = sum(len(r) for r in extracted_btns)
            btn_txt = f"{total_btns} botões em {len(extracted_btns)} linhas" if total_btns else "Layout original preservado"
            clone_info = (
                f"\n• *Postagem Clonada:* Mensagem #{replied.message_id}\n"
                f"• *Conteúdo e Botões:* {btn_txt}\n"
                f"• *Modo:* Clonagem Nativa 100% idêntica (artigos expansíveis, spoilers e botões preservados) 🚀\n"
            )

        target_item["last_fired_slot"] = None
        target_item["last_sent_timestamp"] = 0
        save_config(cfg)

        topic_label = f"Tópico ID: `{thread_id}`" if thread_id else "Geral (Sem tópico específico)"
        test_markup = InlineKeyboardMarkup([
            [InlineKeyboardButton("🚀 Testar Disparo Agora", callback_data=f"cfg:rec:test:{msg_id}")]
        ])

        await safe_reply(
            update,
            f"🎯 *Mensagem Programada #{msg_id} Vinculada com Sucesso!*\n\n"
            f"• *Grupo:* {chat.title} (`{chat.id}`)\n"
            f"• *Destino:* {topic_label}"
            f"{clone_info}\n"
            f"A partir de agora, os disparos automáticos desta mensagem serão postados diretamente aqui! 🎵",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=test_markup
        )

    async def cmd_relogio(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Diagnóstico rápido em tempo real do relógio e status do bot."""
        await self._clean_admin_trigger(update)
        cfg = load_config()
        try:
            from config import get_timezone
            tz = get_timezone(cfg)
            now_dt = datetime.now(tz)
        except Exception:
            from datetime import timezone, timedelta
            now_dt = datetime.now(timezone(timedelta(hours=-3)))

        rec_list = cfg.get("recurring_messages", [])
        m1 = next((m for m in rec_list if m.get("id") == 1), None)

        m1_info = "Não configurada"
        if m1:
            h = m1.get("start_hour")
            m_val = m1.get("start_minute")
            h_str = f"{h:02d}:{m_val:02d}" if h is not None and m_val is not None else "Intervalo corrido"
            dest = m1.get("chat_id")
            m1_info = (
                f"• Situação: {'🟢 Ativa' if m1.get('enabled') else '🔴 Desativada'}\n"
                f"• Horário Agendado: `{h_str}`\n"
                f"• Destino: `{dest}`\n"
                f"• Último Slot Disparado: `{m1.get('last_fired_slot') or 'Nenhum'}`"
            )

        resp = (
            "🕒 *Diagnóstico do Relógio do Bot:*\n\n"
            f"• *Hora Atual do Bot:* `{now_dt.strftime('%H:%M:%S')}`\n"
            f"• *Data:* `{now_dt.strftime('%d/%m/%Y')}`\n"
            f"• *Fuso:* `{cfg.get('timezone', 'America/Sao_Paulo')}`\n\n"
            f"⏱️ *Mensagem Programada #1:*\n"
            f"{m1_info}\n\n"
            "_O agendador contínuo verifica o relógio a cada 10 segundos._"
        )
        await safe_reply(update, resp, parse_mode=ParseMode.MARKDOWN)

    async def cmd_sobre(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Exibe a versão do bot, arquitetura e documentação completa interativa."""
        msg = update.effective_message
        if not msg:
            return

        await self._clean_admin_trigger(update)

        cat_data = HELP_CATEGORIES.get("about", HELP_CATEGORIES["main"])
        header = f"{cat_data['title']}\n\n{cat_data['text']}"
        reply_markup = InlineKeyboardMarkup(cat_data["buttons"])

        try:
            await safe_reply(update, header, reply_markup=reply_markup, parse_mode=ParseMode.HTML)
        except Exception:
            await safe_reply(update, header, reply_markup=reply_markup)

    async def cmd_menu(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Ativa o menu em botões na área de conversa (Reply Keyboard) exclusivamente no chat privado."""
        msg = update.effective_message
        chat = update.effective_chat
        if not msg or not chat:
            return
        await self._clean_admin_trigger(update)

        # Se for acionado dentro de um grupo, REMOVE imediatamente o teclado do grupo!
        if chat.type in ("group", "supergroup"):
            from telegram import ReplyKeyboardRemove
            from modules.utils import schedule_message_deletion
            bot_me = await context.bot.get_me()
            sent = await msg.reply_text(
                f"🧹 Teclado removido do grupo! O menu de botões é exclusivo para o chat privado do bot: @{bot_me.username}",
                reply_markup=ReplyKeyboardRemove()
            )
            schedule_message_deletion(context, chat.id, sent.message_id, 8, bot=context.bot)
            return

        from modules.whitelist import get_conversation_reply_keyboard
        reply_kb = get_conversation_reply_keyboard()
        await safe_reply(
            update,
            "🎹 <b>Menu em Botões no Teclado Ativado (Exclusivo Privado)!</b>\n\n"
            "Os botões fixos agora estão disponíveis no seu teclado no privado para acesso rápido.",
            reply_markup=reply_kb,
            parse_mode=ParseMode.HTML
        )

    async def cmd_fecharmenu(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Remove o menu de botões do teclado em qualquer chat ou grupo."""
        msg = update.effective_message
        chat = update.effective_chat
        if not msg or not chat:
            return
        await self._clean_admin_trigger(update)
        from telegram import ReplyKeyboardRemove
        from modules.utils import schedule_message_deletion
        sent = await msg.reply_text(
            "🧹 Menu em botões do teclado desativado e removido com sucesso!",
            reply_markup=ReplyKeyboardRemove()
        )
        if chat.type in ("group", "supergroup"):
            schedule_message_deletion(context, chat.id, sent.message_id, 6, bot=context.bot)

    async def cmd_livre(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Adiciona um usuário à lista branca de membros livres (/livre [id | @username] ou respondendo a uma mensagem)."""
        if not await self._require_admin(update):
            await safe_reply(update, "⛔ Apenas administradores podem gerenciar a lista branca.")
            return
        await self._clean_admin_trigger(update)
        msg = update.effective_message
        cfg = load_config()
        from config import add_whitelist_user

        target_user = None
        uname = ""
        uuser = ""
        uid = None

        if msg.reply_to_message and msg.reply_to_message.from_user:
            target_user = msg.reply_to_message.from_user
            uid = target_user.id
            uname = target_user.full_name
            uuser = target_user.username or ""
        elif context.args:
            arg = context.args[0].strip()
            if arg.isdigit() or (arg.startswith("-") and arg[1:].isdigit()):
                uid = int(arg)
                uname = f"Usuário {uid}"
                uuser = ""
            else:
                uuser = arg.lstrip("@")
                try:
                    chat_obj = await context.bot.get_chat(f"@{uuser}")
                    if chat_obj and chat_obj.id:
                        uid = chat_obj.id
                        uname = chat_obj.full_name or uuser
                except Exception:
                    pass
                if not uid:
                    await safe_reply(
                        update,
                        f"⚠️ Não foi possível encontrar o ID para <code>@{uuser}</code>.\n"
                        "Forneça o ID numérico ou responda à mensagem do usuário com <code>/livre</code>.",
                        parse_mode=ParseMode.HTML
                    )
                    return
        else:
            await safe_reply(
                update,
                "💡 <b>Como Usar:</b>\n"
                "• Responda à mensagem de alguém no grupo com <code>/livre</code>\n"
                "• Ou digite <code>/livre &lt;ID ou @username&gt;</code> para torná-lo livre de restrições.",
                parse_mode=ParseMode.HTML
            )
            return

        added = add_whitelist_user(cfg, uid, name=uname, username=uuser, added_by=update.effective_user.first_name)
        if added:
            await safe_reply(
                update,
                f"✅ <b>Usuário Liberado com Sucesso!</b>\n\n"
                f"• <b>Nome:</b> {html.escape(uname)}\n"
                f"• <b>ID:</b> <code>{uid}</code>\n"
                f"Agora este membro pode enviar links (inclusive Google Drive), mensagens repetidas e mídias sem bloqueio!",
                parse_mode=ParseMode.HTML
            )
        else:
            await safe_reply(
                update,
                f"ℹ️ O usuário <code>{uid}</code> já está na lista branca!",
                parse_mode=ParseMode.HTML
            )

    async def cmd_removerlivre(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Remove um usuário da lista branca (/removerlivre [id | @username] ou respondendo a uma mensagem)."""
        if not await self._require_admin(update):
            await safe_reply(update, "⛔ Apenas administradores podem gerenciar a lista branca.")
            return
        await self._clean_admin_trigger(update)
        msg = update.effective_message
        cfg = load_config()
        from config import remove_whitelist_user

        uid = None
        if msg.reply_to_message and msg.reply_to_message.from_user:
            uid = msg.reply_to_message.from_user.id
        elif context.args:
            arg = context.args[0].strip()
            if arg.isdigit() or (arg.startswith("-") and arg[1:].isdigit()):
                uid = int(arg)
            else:
                w_users = cfg.get("whitelist_users", [])
                target = next((u for u in w_users if isinstance(u, dict) and u.get("username", "").lower() == arg.lstrip("@").lower()), None)
                if target:
                    uid = target.get("user_id")

        if not uid:
            await safe_reply(
                update,
                "💡 <b>Uso:</b> Responda à mensagem de alguém com <code>/removerlivre</code> ou envie <code>/removerlivre &lt;ID&gt;</code>.",
                parse_mode=ParseMode.HTML
            )
            return

        removed = remove_whitelist_user(cfg, uid)
        if removed:
            await safe_reply(
                update,
                f"🗑️ Usuário <code>{uid}</code> removido da lista branca! As restrições de moderação voltam a ser aplicadas normalmente.",
                parse_mode=ParseMode.HTML
            )
        else:
            await safe_reply(
                update,
                f"ℹ️ O usuário <code>{uid}</code> não foi encontrado na lista branca.",
                parse_mode=ParseMode.HTML
            )

    async def cmd_livres(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Lista todos os usuários livres / isentos de restrições."""
        if not await self._require_admin(update):
            await safe_reply(update, "⛔ Apenas administradores podem ver a lista branca.")
            return
        await self._clean_admin_trigger(update)
        cfg = load_config()
        from modules.whitelist import generate_whitelist_users_page
        text, markup = generate_whitelist_users_page(cfg, page=1)
        await safe_reply(update, text, reply_markup=markup, parse_mode=ParseMode.HTML)

    async def cmd_permitirlink(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Adiciona um link, trecho ou domínio à lista branca (/permitirlink <link_ou_dominio>)."""
        if not await self._require_admin(update):
            await safe_reply(update, "⛔ Apenas administradores podem liberar links.")
            return
        await self._clean_admin_trigger(update)
        if not context.args:
            await safe_reply(
                update,
                "💡 <b>Como Usar:</b>\n"
                "• Liberar domínio: <code>/permitirlink drive.google.com</code>\n"
                "• Liberar pasta/link: <code>/permitirlink drive.google.com/drive/folders/1ABC</code>\n"
                "• Liberar canal: <code>/permitirlink t.me/partiturasecia</code>",
                parse_mode=ParseMode.HTML
            )
            return
        link_entry = " ".join(context.args).strip()
        cfg = load_config()
        from config import add_allowed_domain
        added = add_allowed_domain(cfg, link_entry)
        if added:
            await safe_reply(
                update,
                f"✅ <b>Link / Trecho Liberado!</b>\nO endereço <code>{html.escape(link_entry)}</code> foi adicionado à lista branca e não será mais bloqueado nos grupos.",
                parse_mode=ParseMode.HTML
            )
        else:
            await safe_reply(
                update,
                f"ℹ️ O endereço <code>{html.escape(link_entry)}</code> já estava liberado na lista branca.",
                parse_mode=ParseMode.HTML
            )

    async def cmd_removerlink(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Remove um link ou domínio da lista branca (/removerlink <link_ou_dominio>)."""
        if not await self._require_admin(update):
            await safe_reply(update, "⛔ Apenas administradores podem gerenciar links.")
            return
        await self._clean_admin_trigger(update)
        if not context.args:
            await safe_reply(
                update,
                "💡 <b>Como Usar:</b>\n<code>/removerlink drive.google.com</code> ou <code>/removerlink t.me/partiturasecia</code>",
                parse_mode=ParseMode.HTML
            )
            return
        link_entry = " ".join(context.args).strip()
        cfg = load_config()
        from config import remove_allowed_domain
        removed = remove_allowed_domain(cfg, link_entry)
        if removed:
            await safe_reply(
                update,
                f"🗑️ Endereço <code>{html.escape(link_entry)}</code> removido da lista branca! Links deste endereço voltarão a ser bloqueados.",
                parse_mode=ParseMode.HTML
            )
        else:
            await safe_reply(
                update,
                f"ℹ️ O endereço <code>{html.escape(link_entry)}</code> não constava na lista branca.",
                parse_mode=ParseMode.HTML
            )

    async def cmd_linkspermitidos(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Lista todos os domínios liberados."""
        if not await self._require_admin(update):
            await safe_reply(update, "⛔ Apenas administradores podem ver links permitidos.")
            return
        await self._clean_admin_trigger(update)
        cfg = load_config()
        from modules.whitelist import generate_allowed_links_page
        text, markup = generate_allowed_links_page(cfg)
        await safe_reply(update, text, reply_markup=markup, parse_mode=ParseMode.HTML)




