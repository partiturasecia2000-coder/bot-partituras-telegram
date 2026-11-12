"""Rótulos do teclado e aliases de versões anteriores."""
from telegram import KeyboardButton,ReplyKeyboardMarkup

KEYBOARD_ROWS=(
    ('⚙️ Painel','🎼 Partituras'),
    ('✉️ Nova postagem','🗓 Histórico'),
    ('📢 Canais','👥 Grupos'),
    ('✅ Pessoas e links','❓ Ajuda'),
)

SHORTCUTS={
    '⚙️ Painel':'panel','🎼 Partituras':'acervo','✉️ Nova postagem':'compose','🗓 Histórico':'history',
    '📢 Canais':'channels','👥 Grupos':'groups','✅ Pessoas e links':'allowed','❓ Ajuda':'help',
    '🎛️ Painel de Controle':'panel','🎼 Acervo de Partituras':'acervo',
    '📢 Meus Canais':'channels','👥 Meus Grupos':'groups',
    '🛡️ Whitelist & Links':'allowed','❓ Ajuda & Comandos':'help',
}


def conversation_keyboard():
    return ReplyKeyboardMarkup([[KeyboardButton(label) for label in row] for row in KEYBOARD_ROWS],
        resize_keyboard=True,is_persistent=True,input_field_placeholder='Escolha um atalho ou escreva um comando')
