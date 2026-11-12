"""Prévia vinculada ao autor, conteúdo integral e confirmação antes de enfileirar."""
import copy
import hashlib
import html
import json
import re
import time

from telegram import InlineKeyboardButton as Button, InlineKeyboardMarkup as Markup
from telegram.constants import ParseMode
from telegram.error import BadRequest
from config import load_config,save_config,normalize_chat_id
from modules.panel_lists import page_slice,navigation
from modules.transmission_delivery import find_entry


def digest(item):
    keys=('text','media_type','media_id','copy_source','buttons','pin','delay_seconds',
          'schedule_timestamp','destination_snapshot','message_thread_id','creator_id','origin_chat_id')
    value={key:item.get(key) for key in keys}
    return hashlib.sha256(json.dumps(value,sort_keys=True,ensure_ascii=False).encode()).hexdigest()


def make_snapshot(targets,cfg):
    titles={str(normalize_chat_id(row['id'])):row.get('title') or str(row['id'])
            for row in cfg.get('linked_groups',[])+cfg.get('linked_channels',[])}
    result=[];seen=set()
    for target in targets:
        cid=normalize_chat_id(target)
        if cid is None or str(cid) in seen:
            continue
        seen.add(str(cid))
        result.append(dict(chat_id=cid,title=titles.get(str(cid),str(cid))))
    return result


def create_draft(update,payload,targets,source='comunicado',schedule_timestamp=None,schedule_display=None):
    if not payload.get('text') and not payload.get('media_id') and not payload.get('copy_source'):
        raise ValueError('Prepare texto ou mídia antes de continuar.')
    cfg=load_config();entries=cfg.setdefault('scheduled_transmissions',[])
    snapshot=make_snapshot(targets,cfg)
    if not snapshot:
        raise ValueError('Nenhum destino encontrado.')
    item=copy.deepcopy(payload)
    item.update(id=max(int(time.time()*1000),max((x.get('id',0) for x in entries),default=0)+1),
        source=source,status='draft',creator_id=update.effective_user.id,origin_chat_id=update.effective_chat.id,
        schedule_timestamp=schedule_timestamp if schedule_timestamp is not None else 0,
        schedule_display=schedule_display or 'Após confirmar',destination_snapshot=snapshot,
        created_at=time.time(),draft_expires_at=time.time()+1800,buttons=payload.get('buttons') or [],
        delay_seconds=payload.get('delay_seconds') or 0)
    item['preview_digest']=digest(item)
    entries.append(item)
    if not save_config(cfg):
        raise OSError('Não foi possível salvar a prévia; nenhum envio foi iniciado.')
    return item


def render_preview(item,section='text',page=1):
    labels={'photo':'Foto','video':'Vídeo','document':'Documento/PDF','audio':'Áudio','voice':'Voz'}
    media=labels.get(item.get('media_type'),'Somente texto')
    targets=item.get('destination_snapshot',[])
    lines=[f'<b>🔎 PRÉVIA COMPLETA #{item["id"]}</b>',
        f'Conteúdo: {media} | Fixar: {"Sim" if item.get("pin") else "Não"}',
        'Horário: '+html.escape(item.get('schedule_display','Após confirmar')),
        f'Distribuição: {item.get("delay_seconds",0)}s entre destinos',
        f'Destinos: {len(targets)} | Botões: {sum(len(x) if isinstance(x,list) else 1 for x in item.get("buttons",[]))}']
    if item.get('message_thread_id'):
        lines.append(f'Tópico: {item["message_thread_id"]}')
    if section=='targets':
        shown,page,pages,_=page_slice(targets,page,8)
        lines.append('\n<b>Destinos exatos desta prévia:</b>')
        lines += [html.escape(str(x['title'])[:100])+f' (<code>{html.escape(str(x["chat_id"]))}</code>)' for x in shown]
    else:
        from modules.utils import convert_rich_text
        raw=item.get('text') or '(Sem texto; confira o anexo em Ver conteúdo real.)'
        rich=convert_rich_text(raw)
        rich=re.sub(r'<br\s*/?>|</(?:p|div|blockquote)>','\n',rich,flags=re.IGNORECASE)
        raw=html.unescape(re.sub(r'<[^>]+>','',rich))
        chunks=[raw[i:i+1800] for i in range(0,len(raw),1800)]
        shown,page,pages,_=page_slice(chunks,page,1)
        lines.append(f'\n<b>Texto completo — parte {page}/{pages}:</b>')
        lines.append(html.escape(shown[0]))
        if len(targets)<=5:
            lines.append('\n<b>Destinos:</b> '+', '.join(html.escape(str(x['title'])[:60]) for x in targets))
    keyboard=navigation(f'cfg:draft:{item["id"]}:{section}',page,pages)
    keyboard += [[Button('Texto completo',callback_data=f'cfg:draft:{item["id"]}:text:1'),
                  Button('Todos os destinos',callback_data=f'cfg:draft:{item["id"]}:targets:1')],
                 [Button('👁 Ver conteúdo no privado',callback_data=f'cfg:draft:{item["id"]}:sample:1')]]
    if item.get('status')=='draft':
        label='✅ Confirmar agendamento' if item.get('schedule_timestamp') else '✅ Confirmar envio'
        keyboard += [[Button(label,callback_data=f'cfg:draft:{item["id"]}:confirm:1')],
                     [Button('Cancelar',callback_data=f'cfg:draft:{item["id"]}:cancel:1')]]
    else:
        lines.append('\nEsta prévia já foi confirmada, cancelada ou expirou.')
        keyboard += [[Button('Ver resultados',callback_data=f'cfg:tx:{item["id"]}:1')]]
    return '\n'.join(lines),Markup(keyboard)


async def show_preview(update,context,item):
    text,keyboard=render_preview(item)
    message=await update.effective_message.reply_text(text,reply_markup=keyboard,parse_mode=ParseMode.HTML)
    cfg=load_config();stored=find_entry(cfg,item['id'])
    if stored and stored.get('status')=='draft':
        stored['preview_message_id']=message.message_id
        if not save_config(cfg):
            await message.edit_text('Não foi possível registrar a confirmação. Abra uma nova prévia.')


async def submission_authorized(update,context,item):
    from config import get_all_linked_chats
    from telegram.constants import ChatMemberStatus
    cfg=load_config()
    linked={str(normalize_chat_id(row['id'])) for row in get_all_linked_chats(cfg)}
    if update.effective_chat.type!='private':linked.add(str(update.effective_chat.id))
    for destination in item.get('destination_snapshot',[]):
        if str(destination['chat_id']) in linked:continue
        try:
            chat=await context.bot.get_chat(destination['chat_id'])
            member=await chat.get_member(update.effective_user.id)
            if member.status not in (ChatMemberStatus.ADMINISTRATOR,ChatMemberStatus.OWNER):return False
        except Exception:return False
    return True


async def handle_draft_callback(update,context):
    query=update.callback_query
    if not query.data.startswith('cfg:draft:'):
        return False
    from modules.access import require_management_access
    if not await require_management_access(update):
        return True
    try:
        _,_,raw_id,section,raw_page=query.data.split(':');item_id=int(raw_id);page=int(raw_page)
    except ValueError:
        await query.answer('Prévia inválida.',show_alert=True);return True
    cfg=load_config();item=find_entry(cfg,item_id)
    if not item or item.get('creator_id')!=update.effective_user.id or item.get('origin_chat_id')!=update.effective_chat.id or item.get('preview_message_id')!=query.message.message_id:
        await query.answer('Esta prévia pertence a outra pessoa ou mensagem.',show_alert=True);return True
    if item.get('status')!='draft':
        await query.answer('Esta prévia já foi usada. Consulte o histórico.',show_alert=True);return True
    if time.time()>item.get('draft_expires_at',0):
        item['status']='expired';save_config(cfg)
        await query.answer('Prévia expirada. Prepare o envio novamente.',show_alert=True);return True
    if digest(item)!=item.get('preview_digest'):
        await query.answer('O conteúdo mudou. Prepare uma nova prévia.',show_alert=True);return True
    if section in ('confirm','cancel'):
        if section=='confirm':
            from modules.backup_restore import restore_blocks_writes
            if restore_blocks_writes(context.application):
                await query.answer('Aguarde a restauração terminar.',show_alert=True);return True
            if item.get('schedule_timestamp') and item['schedule_timestamp']<=time.time():
                await query.answer('O horário escolhido já passou. Prepare um novo agendamento.',show_alert=True);return True
            if not await submission_authorized(update,context,item):
                await query.answer('Um destino não está mais vinculado ou sua administração não pôde ser confirmada. Prepare nova prévia.',show_alert=True);return True
            cfg=load_config();item=find_entry(cfg,item_id)
            if not item or item.get('status')!='draft' or digest(item)!=item.get('preview_digest'):
                await query.answer('A prévia mudou ou já foi usada.',show_alert=True);return True
        item['status']='pending' if section=='confirm' else 'cancelled'
        item['confirmed_at']=time.time()
        if not save_config(cfg):
            await query.answer('Não foi possível salvar; nenhum envio começou.',show_alert=True);return True
        if section=='confirm':
            from modules.scheduler import start_scheduled_transmission
            start_scheduled_transmission(item_id)
        await query.answer()
        text='📨 Confirmado. Acompanhe os resultados no histórico.' if section=='confirm' else 'Envio cancelado. Nenhum destino recebeu a postagem.'
        await query.edit_message_text(text,reply_markup=Markup([[Button('Ver histórico',callback_data=f'cfg:tx:{item_id}:1')]]))
        return True
    if section=='sample':
        from modules.broadcast_content import send_content
        await query.answer('Mostrando no seu privado, sem enviar aos destinos.')
        try:
            await send_content(context.bot,update.effective_user.id,item,preview=True)
        except Exception:
            await query.message.reply_text('Abra a conversa privada com o bot para ver a mídia formatada. Os destinos não receberam nenhum envio.')
        return True
    if section not in ('text','targets'):
        await query.answer('Página inválida.',show_alert=True);return True
    text,keyboard=render_preview(item,section,page)
    await query.answer()
    try:
        await query.edit_message_text(text,reply_markup=keyboard,parse_mode=ParseMode.HTML)
    except BadRequest as exc:
        if 'not modified' not in str(exc).lower():raise
    return True
