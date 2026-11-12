"""Navegação adicional do painel, antes das rotas legadas."""
from telegram.constants import ParseMode
from telegram.error import BadRequest
from config import load_config
from modules import panel_lists as lists


async def handle_navigation(panel, update, context):
    query = update.callback_query
    data = query.data
    aliases = {'cfg:sched:list':'tx', 'cfg:chats:list':'chats', 'cfg:resp:list':'resp',
               'cfg:sub:allowed_links':'links', 'cfg:youtube:del':'youtube','cfg:banned:view_all':'banned'}
    if data not in aliases and not data.startswith(('cfg:list:', 'cfg:tx:', 'cfg:txretry:', 'cfg:txresume:')):
        return False
    pages = context.user_data.setdefault('_list_pages', {})
    cfg = load_config()
    parse_mode = ParseMode.MARKDOWN
    try:
        if data.startswith(('cfg:txretry:', 'cfg:txresume:')):
            from modules.scheduler import start_scheduled_transmission
            item_id = int(data.split(':')[-1])
            mode = 'failed' if data.startswith('cfg:txretry:') else 'pending'
            started = start_scheduled_transmission(item_id, force=True, mode=mode)
            await query.answer('Nova tentativa iniciada apenas nos destinos elegíveis.' if started else 'Nenhum destino elegível ou envio já em andamento.', show_alert=True)
            text, markup = lists.transmission_detail(load_config(),item_id,back_page=pages.get('tx',1))
            parse_mode = ParseMode.HTML
        elif data.startswith('cfg:tx:'):
            _,_,item_id,page = data.split(':')
            text,markup=lists.transmission_detail(cfg,int(item_id),int(page),pages.get('tx',1))
            parse_mode=ParseMode.HTML
            await query.answer()
        else:
            if data in aliases:
                kind=aliases[data];page=pages.get(kind,1)
            else:
                _,_,kind,page=data.split(':')
                page=int(page)
            functions={'tx':lists.transmissions_page,'chats':lists.chats_page,'dest':lists.wizard_destinations,
                       'links':lists.allowed_links,'youtube':lists.youtube_channels,'banned':lists.banned_words}
            functions['channels']=lambda cfg,page:lists.chats_page(cfg,page,kind='channels')
            functions['groups']=lambda cfg,page:lists.chats_page(cfg,page,kind='groups')
            if kind=='resp':
                text,markup=lists.responders_page(update.effective_chat.title or 'Chat',cfg,page)
            elif kind in functions:
                text,markup=functions[kind](cfg,page)
            else:
                raise ValueError('Lista inválida')
            pages[kind]=max(1,page)
            if kind=='links':
                parse_mode=ParseMode.HTML
            await query.answer()
    except (ValueError,IndexError):
        await query.answer('Navegação inválida. Abra o painel novamente.',show_alert=True)
        return True
    try:
        await query.edit_message_text(text,reply_markup=markup,parse_mode=parse_mode)
    except BadRequest as exc:
        if 'not modified' not in str(exc).lower():
            raise
    return True
