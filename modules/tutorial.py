import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

logger = logging.getLogger("TutorialModule")

TUTORIAL_PAGES = {
    "main": {
        "title": "🎓 <b>CENTRAL DE TUTORIAIS & GUIAS DO BOT</b>",
        "text": (
            "Seja bem-vindo ao manual interativo do seu bot de gerenciamento!\n\n"
            "Aqui você encontra tutoriais passo a passo explicando como configurar e usar cada uma das principais ferramentas inspiradas nos melhores bots do Telegram (Group Help & Miss Rose):\n\n"
            "👉 <b>Escolha um dos tópicos abaixo para ver o tutorial completo:</b>"
        ),
        "buttons": [
            [
                InlineKeyboardButton("📌 1. Anotações & Hashtags", callback_data="tut:notes"),
                InlineKeyboardButton("🔒 2. Bloqueios de Mídia (/locks)", callback_data="tut:locks")
            ],
            [
                InlineKeyboardButton("⏱️ 3. Mensagens Programadas", callback_data="tut:recurring"),
                InlineKeyboardButton("📢 4. Transmissões (/falar)", callback_data="tut:falar")
            ],
            [
                InlineKeyboardButton("🛡️ 5. Moderação & Punições", callback_data="tut:mod"),
                InlineKeyboardButton("🌙 6. Silêncio Noturno", callback_data="tut:night")
            ],
            [
                InlineKeyboardButton("🤖 7. Auto-Respostas (Regex)", callback_data="tut:auto"),
                InlineKeyboardButton("💾 8. Backup & Restauração", callback_data="tut:backup")
            ],
            [
                InlineKeyboardButton("🧩 9. CAPTCHA Anti-Bot", callback_data="tut:captcha"),
                InlineKeyboardButton("📰 10. Artigos & Botões Ricos", callback_data="tut:rich")
            ],
            [
                InlineKeyboardButton("📢 11. Canais & Multi-Grupos 🆕", callback_data="tut:channels"),
                InlineKeyboardButton("📋 Menu de Comandos", callback_data="help:cat:all")
            ]
        ]
    },
    "notes": {
        "title": "📌 <b>TUTORIAL: ANOTAÇÕES & HASHTAGS (#NOTAS)</b>",
        "text": (
            "O sistema de Notas permite salvar textos, fotos de partituras, PDFs e botões para que qualquer membro ou admin acerte rapidamente respostas usando uma hashtag!\n\n"
            "<b>1. Como salvar uma nota simples:</b>\n"
            "• Digite no chat: <code>/save pix Chave PIX: contato@partiturasecia.com.br</code>\n"
            "• O bot salvará a nota com o nome <code>#pix</code>!\n\n"
            "<b>2. Como salvar com Foto, PDF de Partitura ou Áudio:</b>\n"
            "• Envie a foto ou o arquivo no grupo.\n"
            "• <b>Responda ao arquivo</b> digitando: <code>/save hinario Confira nosso hinário completo!</code>\n"
            "• O bot salvará aquele arquivo vinculado à nota <code>#hinario</code>!\n\n"
            "<b>3. Como colocar botões com links na nota:</b>\n"
            "• Basta incluir no texto o formato: <code>[Nosso Site](buttonurl:https://seusite.com)</code>\n"
            "• Ou em uma linha separada: <code>Canal Oficial | https://t.me/seucanal</code>\n\n"
            "<b>4. Como acessar as notas no dia a dia:</b>\n"
            "• Qualquer membro pode digitar <code>#pix</code> ou <code>#hinario</code> no grupo.\n"
            "• Ou usar <code>/get pix</code>.\n"
            "• Para ver todas as notas existentes: <code>/notas</code> ou <code>/notes</code>.\n"
            "• Para apagar: <code>/clear nome</code>."
        ),
        "buttons": [
            [InlineKeyboardButton("◀ Voltar aos Tutoriais", callback_data="tut:main")]
        ]
    },
    "locks": {
        "title": "🔒 <b>TUTORIAL: BLOQUEIOS DE MÍDIA (/LOCKS)</b>",
        "text": (
            "O módulo de Locks permite travar o envio de tipos específicos de mensagens no grupo para membros comuns, evitando poluição e mantendo o chat limpo:\n\n"
            "<b>1. Como bloquear um tipo de mídia:</b>\n"
            "• <code>/lock sticker</code> - Bloqueia figurinhas\n"
            "• <code>/lock audio</code> - Bloqueia músicas e arquivos de áudio\n"
            "• <code>/lock voice</code> - Bloqueia áudios de voz do microfone\n"
            "• <code>/lock video</code> - Bloqueia vídeos\n"
            "• <code>/lock videonote</code> - Bloqueia vídeos redondos\n"
            "• <code>/lock gif</code> - Bloqueia GIFs e animações\n"
            "• <code>/lock document</code> - Bloqueia arquivos e PDFs\n"
            "• <code>/lock forward</code> - Bloqueia mensagens encaminhadas de outros canais\n"
            "• <code>/lock contact</code> - Bloqueia cartões de contato\n"
            "• <code>/lock poll</code> - Bloqueia criação de enquetes\n\n"
            "<b>2. Como liberar novamente:</b>\n"
            "• Basta usar <code>/unlock sticker</code>, <code>/unlock audio</code>, etc.\n\n"
            "<b>3. Como consultar todos os bloqueios ativos:</b>\n"
            "• Digite <code>/locks</code> para ver a tabela visual completa com 🔒 Bloqueado e 🔓 Liberado!"
        ),
        "buttons": [
            [InlineKeyboardButton("◀ Voltar aos Tutoriais", callback_data="tut:main")]
        ]
    },
    "recurring": {
        "title": "⏱️ <b>TUTORIAL: MENSAGENS REPETIDAS & CRONOGRAMA</b>",
        "text": (
            "O motor de mensagens repetidas do Maestro possui a interface idêntica ao Group Help com seletores visuais completos!\n\n"
            "<b>1. Acessando o painel:</b>\n"
            "• Envie <code>/config</code> no privado do bot.\n"
            "• Clique em <b>⏱️ Msg Repetidas</b> e depois em <b>➕ Adicionar mensagem</b>.\n\n"
            "<b>2. Configurando o Horário de Início:</b>\n"
            "• Clique em <b>🔘 Definir horário</b> (ou ⏰ Cronograma).\n"
            "• Selecione a hora na grade (0 a 23) e depois o minuto (0 a 59).\n"
            "• <i>Exemplo:</i> Definir 11:37 fará o bot disparar a mensagem exatamente nesse horário!\n\n"
            "<b>3. Configurando a Frequência:</b>\n"
            "• Clique em <b>🔄 Repetição</b> para escolher a cada 1h, 2h, 4h, 12h ou 24h.\n"
            "• Ou clique em <b>💬 Repetir a cada poucas mensagens</b> para disparar por volume de chat (ex: a cada 50 mensagens enviadas no grupo)!\n\n"
            "<b>4. Dias da Semana e Exclusão:</b>\n"
            "• Use <b>🗓️ Dias da semana</b> para selecionar em quais dias enviar.\n"
            "• Use <b>⏳ Exclusão Cronometrada</b> se desejar que a mensagem se auto-apague após 30 min, 1 hora, etc."
        ),
        "buttons": [
            [InlineKeyboardButton("◀ Voltar aos Tutoriais", callback_data="tut:main")]
        ]
    },
    "falar": {
        "title": "📢 <b>TUTORIAL: TRANSMISSÕES PELO PRIVADO (/FALAR)</b>",
        "text": (
            "Com este recurso, você pode postar mensagens oficiais, partituras ou avisos no grupo diretamente do privado do bot, aparecendo com o nome e avatar do bot!\n\n"
            "<b>1. Primeiro Passo: Vincular o Grupo</b>\n"
            "• No seu grupo (<i>Partituras & Cia</i>), envie o comando <code>/setgrupo</code>.\n"
            "• O bot confirmará que aquele grupo é o Grupo Principal.\n\n"
            "<b>2. Como enviar texto simples pelo privado:</b>\n"
            "• Vá no chat privado com o bot e envie:\n"
            "  <code>/falar Olá a todos! Novas partituras foram adicionadas hoje.</code>\n"
            "• A mensagem será postada no grupo na hora!\n\n"
            "<b>3. Como enviar Fotos, Partituras em PDF ou Áudios:</b>\n"
            "• No privado do bot, selecione o arquivo PDF, foto ou música.\n"
            "• Na legenda do arquivo, digite: <code>/falar Partitura disponível para estudo!</code>\n"
            "• O bot transmitirá o documento com a legenda diretamente para o grupo!\n\n"
            "<b>4. Fixar no topo automaticamente:</b>\n"
            "• Use <code>/anunciar &lt;texto&gt;</code> para enviar e fixar no topo do grupo."
        ),
        "buttons": [
            [InlineKeyboardButton("◀ Voltar aos Tutoriais", callback_data="tut:main")]
        ]
    },
    "mod": {
        "title": "🛡️ <b>TUTORIAL: MODERAÇÃO & PUNIÇÕES FLEXÍVEIS</b>",
        "text": (
            "Ferramentas completas para manter a ordem do grupo com tempos dinâmicos:\n\n"
            "<b>1. Silenciar (Mute temporário flexível):</b>\n"
            "• Responda à mensagem do infrator com:\n"
            "  <code>/mute 15m Flood</code>\n"
            "  <code>/mute 2h Desrespeito</code>\n"
            "  <code>/mute 1d</code>\n"
            "• Para desmutar antes do prazo: <code>/unmute</code> (em resposta).\n\n"
            "<b>2. Banir (Ban com tempo flexível ou permanente):</b>\n"
            "• <code>/ban 1d Spam</code> - Bane por 1 dia\n"
            "• <code>/ban 7d</code> - Bane por 1 semana\n"
            "• <code>/ban</code> - Banimento definitivo do grupo.\n\n"
            "<b>3. Advertências (Sistema de 3 Warns):</b>\n"
            "• <code>/warn &lt;motivo&gt;</code> (em resposta) aplica 1 advertência.\n"
            "• Ao atingir 3 advertências, o membro é banido automaticamente!\n"
            "• <code>/unwarn</code> remove uma advertência.\n\n"
            "<b>4. Limpeza em lote:</b>\n"
            "• <code>/limpar 20</code> - Apaga as últimas 20 mensagens do chat rapidamente."
        ),
        "buttons": [
            [InlineKeyboardButton("◀ Voltar aos Tutoriais", callback_data="tut:main")]
        ]
    },
    "night": {
        "title": "🌙 <b>TUTORIAL: MODO NOTURNO (SILÊNCIO PROGRAMADO)</b>",
        "text": (
            "Permite definir um horário de descanso noturno em que membros comuns não podem enviar mensagens no grupo, garantindo paz para a comunidade:\n\n"
            "<b>1. Como ativar o silêncio noturno:</b>\n"
            "• <code>/noturno on</code> (usa o horário padrão: 23:00 às 07:00)\n"
            "• Ou com horário personalizado:\n"
            "  <code>/noturno on 22:30-06:30</code>\n\n"
            "<b>2. Avisos Automáticos no Grupo (Início & Término) 🔔:</b>\n"
            "• <b>Ao Iniciar (23:00):</b> O bot avisa no grupo que o Modo Noturno começou, silenciando mensagens e desejando uma boa noite!\n"
            "• <b>Ao Terminar (07:00):</b> O bot dá Bom Dia e anuncia que o grupo foi reaberto para mensagens e partituras!\n"
            "• Para ligar/desligar esses avisos: <code>/noturno avisos on</code> ou <code>/noturno avisos off</code>.\n"
            "• Para testar os avisos agora mesmo: <code>/noturno testestart</code> e <code>/noturno testeend</code>.\n\n"
            "<b>3. Como funciona durante a noite:</b>\n"
            "• Se um membro comum enviar mensagem, o bot apaga na hora e avisa que o chat reabre pela manhã.\n"
            "• Administradores continuam podendo postar normalmente a qualquer hora.\n\n"
            "<b>4. Como desativar o modo noturno:</b>\n"
            "• <code>/noturno off</code> (retorna ao chat livre 24 horas)."
        ),
        "buttons": [
            [InlineKeyboardButton("◀ Voltar aos Tutoriais", callback_data="tut:main")]
        ]
    },
    "auto": {
        "title": "🤖 <b>TUTORIAL: AUTO-RESPOSTAS & REGEX INTELIGENTE</b>",
        "text": (
            "Crie respostas automáticas que respondem a dúvidas frequentes, PIX, regras ou pedidos de partituras sem precisar de um admin online:\n\n"
            "<b>1. Criar resposta rápida por comando:</b>\n"
            "• <code>/filtro pix Chave PIX: contato@partiturasecia.com.br</code>\n"
            "• Toda vez que alguém falar 'pix' no grupo, o bot responde!\n\n"
            "<b>2. Criar resposta com Foto ou Partitura:</b>\n"
            "• Responda a uma imagem/PDF com <code>/filtro partituras</code>.\n"
            "• O bot salvará a mídia como resposta oficial!\n\n"
            "<b>3. Respostas Avançadas com Regex:</b>\n"
            "• No menu <code>/config</code> -> <b>🤖 Auto-Respostas</b>, você pode criar padrões como:\n"
            "  <code>(?i)\\b(onde\\s+estao|como\\s+achar)\\s+as?\\s+partituras?\\b</code>\n"
            "• O bot entenderá variações de frases naturais e responderá na hora!"
        ),
        "buttons": [
            [InlineKeyboardButton("◀ Voltar aos Tutoriais", callback_data="tut:main")]
        ]
    },
    "backup": {
        "title": "💾 <b>TUTORIAL: BACKUP & RESTAURAÇÃO DAS CONFIGURAÇÕES</b>",
        "text": (
            "Como o bot roda em servidores na nuvem (Discloud), este recurso permite proteger 100% dos seus dados contra qualquer reinício ou atualização:\n\n"
            "<b>1. Como fazer backup dos seus dados:</b>\n"
            "• No privado do bot, envie o comando <code>/backup</code>.\n"
            "• O bot enviará o arquivo <code>config.json</code> atualizado para você.\n"
            "• Guarde esse arquivo nas suas Mensagens Salvas do Telegram ou no computador!\n\n"
            "<b>2. Como restaurar após uma atualização:</b>\n"
            "• Se você atualizar o bot na Discloud e quiser restaurar todas as suas mensagens repetidas e regras:\n"
            "• Envie o arquivo <code>config.json</code> no privado do bot com a legenda <code>/restaurar</code>.\n"
            "• Ou responda ao arquivo digitando <code>/restaurar</code>.\n"
            "• Em 1 segundo, todas as suas mensagens, intervalos e configurações voltam exatamente como estavam!"
        ),
        "buttons": [
            [InlineKeyboardButton("◀ Voltar aos Tutoriais", callback_data="tut:main")]
        ]
    },
    "captcha": {
        "title": "🧩 <b>TUTORIAL: CAPTCHA MUSICAL ANTI-BOT</b>",
        "text": (
            "Protege o grupo contra invasões em massa de robôs de spam e contas falsas:\n\n"
            "<b>1. Como ativar o CAPTCHA:</b>\n"
            "• Envie <code>/config</code> -> Página 2 -> <b>🧩 CAPTCHA: Ativado</b>.\n\n"
            "<b>2. Como funciona na entrada:</b>\n"
            "• Assim que um novo membro entra no grupo, ele é silenciado automaticamente.\n"
            "• O bot envia um desafio com o botão <code>[ 🎵 Sou Humano ]</code>.\n"
            "• O membro tem 3 minutos para clicar no botão.\n"
            "• Ao clicar, ele é desmutado imediatamente e recebe as boas-vindas!\n"
            "• Se não confirmar no tempo limite, é expulso automaticamente do grupo."
        ),
        "buttons": [
            [InlineKeyboardButton("◀ Voltar aos Tutoriais", callback_data="tut:main")]
        ]
    },
    "rich": {
        "title": "📰 <b>TUTORIAL: ARTIGOS EXPANSÍVEIS & MENSAGENS ENRIQUECIDAS</b>",
        "text": (
            "O Maestro suporta a nova tecnologia de <b>Mensagens Enriquecidas Nativas do Telegram</b> para criar comunicados longos, tutoriais e artigos que não poluem o chat e contam com botões interativos:\n\n"
            "<b>1. Artigos Expansíveis/Recolhíveis (Collapsible Quotes):</b>\n"
            "• Para colocar um artigo longo com botão 'Expandir' direto dentro do Telegram, use:\n"
            "  <code>&lt;blockquote expandable&gt;Seu texto longo ou artigo aqui...&lt;/blockquote&gt;</code>\n"
            "• Ou use a forma simplificada:\n"
            "  <code>[artigo]Seu texto longo ou artigo aqui...[/artigo]</code>\n"
            "• O texto ficará elegante e compacto, revelando o artigo completo ao toque!\n\n"
            "<b>2. Formatações Visuais Nativas:</b>\n"
            "• <b>Negrito:</b> <code>&lt;b&gt;Título&lt;/b&gt;</code> ou <code>*Título*</code>\n"
            "• <i>Itálico:</i> <code>&lt;i&gt;Texto&lt;/i&gt;</code> ou <code>_Texto_</code>\n"
            "• <u>Sublinhado:</u> <code>&lt;u&gt;Texto&lt;/u&gt;</code>\n"
            "• <s>Tachado:</s> <code>&lt;s&gt;Texto&lt;/s&gt;</code>\n"
            "• Spoilers: <code>||segredo||</code> ou <code>&lt;tg-spoiler&gt;segredo&lt;/tg-spoiler&gt;</code>\n\n"
            "<b>3. Botões Interativos em Grade (Multi-Colunas):</b>\n"
            "• Coloque múltiplos botões na mesma linha usando colchetes:\n"
            "  <code>[🎹 Partituras - https://t.me/canal] [🎼 Hinários - https://t.me/canal]</code>\n"
            "• Ou usando <code>&&</code>:\n"
            "  <code>Site | https://seusite.com && Canal | https://t.me/canal</code>\n\n"
            "<b>4. Marcadores Dinâmicos:</b>\n"
            "• <code>{MENTION}</code>: Menciona o membro clicável\n"
            "• <code>{name}</code>: Primeiro nome\n"
            "• <code>{group}</code>: Nome do grupo\n"
            "• <code>{hour}</code> e <code>{date}</code>: Hora e data atuais."
        ),
        "buttons": [
            [InlineKeyboardButton("◀ Voltar aos Tutoriais", callback_data="tut:main")]
        ]
    },
    "channels": {
        "title": "📢 <b>TUTORIAL: CANAIS & MÚLTIPLOS GRUPOS</b>",
        "text": (
            "O Maestro permite conectar e gerenciar múltiplos grupos e canais simultaneamente com total facilidade!\n\n"
            "<b>1. Como vincular múltiplos grupos:</b>\n"
            "• Adicione o bot como Administrador no grupo.\n"
            "• Envie o comando <code>/setgrupo</code> diretamente dentro do grupo.\n"
            "• Você pode repetir isso em quantos grupos desejar!\n"
            "• Para desvincular um grupo: envie <code>/desvincular</code> nele.\n\n"
            "<b>2. Como vincular um Canal ao bot:</b>\n"
            "• Adicione o bot como <b>Administrador</b> no canal com a permissão <b>Postar mensagens</b>.\n"
            "• No privado do bot, envie: <code>/setcanal @nomedoseucanal</code> (ou use o ID numérico <code>-100...</code>).\n"
            "• O bot confirmará o vínculo e liberará o envio imediato!\n\n"
            "<b>3. Como mandar mensagens no canal:</b>\n"
            "• Envie no privado: <code>/canal &lt;sua mensagem&gt;</code> ou <code>/postar &lt;sua mensagem&gt;</code>.\n"
            "• <i>Com mídias:</i> Responda a uma Foto, PDF de Partitura ou Áudio com <code>/canal</code> para postar com todas as formatações!\n"
            "• <i>Para fixar no topo:</i> Use <code>/canal pin &lt;texto&gt;</code>.\n\n"
            "<b>4. Transmissão Global para Todos:</b>\n"
            "• Envie <code>/transmitir &lt;mensagem&gt;</code> no privado para disparar um comunicado para <b>TODOS os grupos e canais vinculados</b> de uma vez só!\n\n"
            "<b>5. Consultar todos os chats conectados:</b>\n"
            "• Envie <code>/grupos</code> ou <code>/canais</code> para ver a lista com nomes, links e IDs."
        ),
        "buttons": [
            [InlineKeyboardButton("◀ Voltar aos Tutoriais", callback_data="tut:main")]
        ]
    }
}

class TutorialHandler:
    async def cmd_tutorial(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Exibe a central de tutoriais interativa."""
        msg = update.effective_message
        tut = TUTORIAL_PAGES["main"]
        header = f"{tut['title']}\n\n{tut['text']}"
        markup = InlineKeyboardMarkup(tut["buttons"])

        try:
            await msg.reply_text(header, reply_markup=markup, parse_mode=ParseMode.HTML)
        except Exception:
            await msg.reply_text(header, reply_markup=markup)

    async def handle_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Gerencia a navegação entre as páginas do tutorial."""
        query = update.callback_query
        data = query.data
        if not data.startswith("tut:"):
            return

        page_key = data.split(":")[-1]
        tut = TUTORIAL_PAGES.get(page_key, TUTORIAL_PAGES["main"])
        header = f"{tut['title']}\n\n{tut['text']}"
        markup = InlineKeyboardMarkup(tut["buttons"])

        try:
            await query.edit_message_text(header, reply_markup=markup, parse_mode=ParseMode.HTML)
        except Exception as e:
            logger.debug(f"Falha ao editar página do tutorial: {e}")

        await query.answer()
