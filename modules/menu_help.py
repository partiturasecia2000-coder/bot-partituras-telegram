"""Apresentação da ajuda; preserva as categorias e os callbacks existentes."""
from telegram import InlineKeyboardButton as Button


def refresh_help(categories):
    categories['main'].update(
        title='<b>❓ AJUDA E COMANDOS</b>',
        text='Escolha um assunto para ver o que você pode fazer.\n\n'
             '<b>Para postar:</b> /comunicado, /falar, /anunciar ou /canal.\n'
             '<b>Para acompanhar:</b> /agendados.\n'
             '<b>Para configurar:</b> /painel.\n\n'
             'As postagens mostram uma prévia antes de pedir sua confirmação.',
        buttons=[
            [Button('🛡 Moderação do grupo',callback_data='help:cat:mod')],
            [Button('✉️ Postagens e envios',callback_data='help:cat:trans')],
            [Button('💬 Respostas automáticas',callback_data='help:cat:auto')],
            [Button('👋 Segurança e entrada',callback_data='help:cat:sec')],
            [Button('📝 Notas e funções do grupo',callback_data='help:cat:rose')],
            [Button('📖 Tutoriais',callback_data='tut:main')],
            [Button('⚙️ Sistema e backups',callback_data='help:cat:sys')],
            [Button('⌨️ Todos os comandos',callback_data='help:cat:all')],
            [Button('ℹ️ Sobre o Maestro',callback_data='help:cat:about')]])
    categories['trans'].update(
        title='<b>✉️ POSTAGENS E ENVIOS</b>',
        text='<b>/comunicado</b> — prepare a postagem passo a passo.\n'
             '<b>/falar texto</b> — escolha onde publicar como o bot.\n'
             '<b>/anunciar texto</b> — prepare um comunicado para fixar.\n'
             '<b>/canal texto</b> — prepare uma postagem no canal vinculado.\n\n'
             'Você pode responder a uma mídia ou usar o comando na legenda. '
             'Confira conteúdo, destinos e horário na prévia; só a confirmação libera o envio.\n\n'
             '<b>/agendados</b> mostra o histórico e os resultados por destino.')
    categories['about'].update(
        title='<b>🎼 MAESTRO · VERSÃO 6</b>',
        text='Painel organizado para grupos, canais e partituras.\n\n'
             '• Botões largos e estados escritos por extenso.\n'
             '• Prévia e confirmação nas postagens.\n'
             '• Histórico de entregas por destino.\n'
             '• Backup e restauração com conferência.\n\n'
             'Abra /painel para configurar ou /menu para ativar os atalhos na conversa.')
    categories['sys'].update(
        title='<b>⚙️ SISTEMA E BACKUPS</b>',
        text='<b>/painel</b> — configurações organizadas por assunto.\n'
             '<b>/menu</b> — atalhos fixos na conversa privada.\n'
             '<b>/tarefas</b> — estado das rotinas automáticas.\n'
             '<b>/backup</b> — baixe um ZIP completo no privado.\n'
             '<b>/restaurar</b> — valide o arquivo e confira a prévia antes de restaurar.\n\n'
             'A restauração mantém uma cópia anterior e exige confirmação. '
             'Programações antigas ficam pausadas para revisão.')
