"""Conteúdo compartilhado por prévia e entrega, incluindo documentos e tópicos."""
from telegram.constants import ParseMode
from telegram.error import BadRequest, Forbidden


async def send_content(bot, chat_id, item, *, preview=False):
    from modules.utils import (build_rich_buttons_markup, convert_rich_text,
                               smart_send_message, smart_send_photo, smart_send_video)
    text=item.get('text') or ''
    markup=build_rich_buttons_markup(item.get('buttons') or [])
    extra={}
    if item.get('message_thread_id') and not preview:
        extra['message_thread_id']=item['message_thread_id']
    source=item.get('copy_source')
    if source:
        try:
            return await bot.copy_message(chat_id=chat_id,from_chat_id=source['chat_id'],message_id=source['message_id'],**extra)
        except (BadRequest,Forbidden):
            pass  # Pedido recusado: usar a mídia/texto extraído não repete uma entrega.
    media_id=item.get('media_id')
    kind=item.get('media_type')
    if kind=='photo' and media_id:
        return await smart_send_photo(bot,chat_id=chat_id,photo=media_id,caption=text,reply_markup=markup,**extra)
    if kind=='video' and media_id:
        return await smart_send_video(bot,chat_id=chat_id,video=media_id,caption=text,reply_markup=markup,**extra)
    if kind in ('document','audio','voice') and media_id:
        sender=getattr(bot,'send_'+kind)
        kwargs=dict(chat_id=chat_id,**{kind:media_id},**extra)
        if len(text)>1000:
            sent=await sender(**kwargs)
            return await smart_send_message(bot,chat_id=chat_id,text=text,reply_markup=markup,
                                            reply_to_message_id=sent.message_id,**extra) or sent
        kwargs.update(caption=convert_rich_text(text),reply_markup=markup)
        try:
            return await sender(**kwargs,parse_mode=ParseMode.HTML)
        except BadRequest:
            return await sender(**dict(kwargs,caption=text))
    return await smart_send_message(bot,chat_id=chat_id,text=text,reply_markup=markup,**extra)
