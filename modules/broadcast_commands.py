"""Comandos de postagem com seleção de destino, prévia e histórico comuns."""
import copy
import re
import time

from telegram import InlineKeyboardButton as Button, InlineKeyboardMarkup as Markup
from telegram.constants import ParseMode,ChatMemberStatus

from config import load_config,get_all_linked_chats,normalize_chat_id
from modules.access import require_management_access
from modules.broadcast_drafts import create_draft,show_preview
from modules.panel_lists import page_slice,navigation


def extract_payload(message):
    raw=getattr(message,'text_html',None) or getattr(message,'caption_html',None) or getattr(message,'text',None) or getattr(message,'caption',None) or ''
    text=re.sub(r'^/\w+(?:@\w+)?\s*','',raw).strip()
    reply=getattr(message,'reply_to_message',None)
    source=reply or message
    media_type=None;media_id=None
    photos=getattr(source,'photo',None)
    if photos:
        media_type='photo';media_id=photos[-1].file_id
    else:
        for kind in ('document','video','audio','voice'):
            media=getattr(source,kind,None)
            if media:
                media_type=kind;media_id=media.file_id;break
    if reply and not text:
        text=getattr(reply,'caption_html',None) or getattr(reply,'caption',None) or getattr(reply,'text_html',None) or getattr(reply,'text',None) or ''
    return dict(text=text,media_type=media_type,media_id=media_id,buttons=[],pin=False,
                delay_seconds=2,message_thread_id=getattr(message,'message_thread_id',None))


def prepare_buttons(payload):
    from modules.utils import parse_rich_buttons
    text=payload.get('text') or ''
    buttons=parse_rich_buttons(text)
    if buttons:
        payload['buttons']=buttons
        payload['text']='\n'.join(line for line in text.split('\n') if not parse_rich_buttons(line)).strip()
    return payload


def set_copy_source(payload,message,had_override):
    reply=getattr(message,'reply_to_message',None)
    if reply and not had_override and not payload.get('buttons'):
        payload['copy_source']=dict(chat_id=reply.chat.id,message_id=reply.message_id)


def fill_reply_text(payload,message):
    reply=getattr(message,'reply_to_message',None)
    if reply and not payload.get('text'):
        payload['text']=getattr(reply,'caption_html',None) or getattr(reply,'caption',None) or getattr(reply,'text_html',None) or getattr(reply,'text',None) or ''


def resolve_targets(choice,cfg):
    if choice in ('all','all_groups','all_channels','main_channel'):
        from modules.panel_views.broadcast import get_wizard_targets_list
        return get_wizard_targets_list(choice,cfg)
    if choice=='main_group':
        groups=cfg.get('linked_groups',[])
        value=cfg.get('main_group_id') or (groups[0]['id'] if groups else None)
        return [value] if value else []
    return [normalize_chat_id(choice)]


async def preview_post(update,context,payload,targets,source):
    try:
        item=create_draft(update,prepare_buttons(copy.deepcopy(payload)),targets,source)
        await show_preview(update,context,item)
        return item
    except (ValueError,OSError):
        await update.effective_message.reply_text('Não foi possível preparar a prévia. Confira conteúdo e destinos; nenhum envio foi iniciado.')
        return None


async def show_selector(update,context,stage,page=1,edit=False):
    cfg=load_config();items=get_all_linked_chats(cfg)
    shown,page,pages,_=page_slice(items,page,6)
    buttons=[]
    for item in shown:
        kind='chn' if item.get('is_channel') else 'grp'
        buttons.append([Button(str(item.get('title',item['id']))[:35],callback_data=f'falar:send:{kind}:{item["id"]}')])
    buttons += [[Button('Grupos',callback_data='falar:send:all_groups'),Button('Canais',callback_data='falar:send:all_channels')],
                [Button('Todos',callback_data='falar:send:all')]]
    buttons += navigation('falar:page',page,pages)
    buttons += [[Button('Cancelar',callback_data='falar:cancel')]]
    text='🎯 Escolha os destinos. Depois você verá a prévia completa antes de confirmar o envio.'
    if edit:
        await update.callback_query.edit_message_text(text,reply_markup=Markup(buttons))
    else:
        message=await update.effective_message.reply_text(text,reply_markup=Markup(buttons))
        stage['message_id']=message.message_id


class TrackedBroadcastCommands:
    async def cmd_say(self,update,context):
        if not await require_management_access(update):return
        payload=extract_payload(update.effective_message)
        if not payload['text'] and not payload['media_id']:
            await update.effective_message.reply_text('Use /falar <texto>, responda a uma mídia com /falar ou use /falar <ID ou número do chat> <texto>. O envio sempre terá prévia.');return
        cfg=load_config();linked=get_all_linked_chats(cfg)
        private=update.effective_chat.type=='private'
        target=None;raw=payload['text']
        if private:
            match=re.match(r'^(-\d+|@\w+)(?::(\d+))?\s*([\s\S]*)',raw)
            ordinal=re.match(r'^(\d+)(?::(\d+))?\s+([\s\S]*)',raw) if not match else None
            if match:
                target=normalize_chat_id(match.group(1));payload['text']=match.group(3).strip()
                if match.group(2):payload['message_thread_id']=int(match.group(2))
            elif ordinal and 1<=int(ordinal.group(1))<=len(linked):
                target=linked[int(ordinal.group(1))-1]['id'];payload['text']=ordinal.group(3).strip()
                if ordinal.group(2):payload['message_thread_id']=int(ordinal.group(2))
        else:
            target=update.effective_chat.id
        # O destino explícito fora dos vínculos exige administração real nesse chat.
        if target is not None and private and str(target) not in {str(row['id']) for row in linked}:
            try:
                chat=await context.bot.get_chat(target)
                member=await chat.get_member(update.effective_user.id)
                if member.status not in (ChatMemberStatus.ADMINISTRATOR,ChatMemberStatus.OWNER):
                    raise PermissionError()
            except Exception:
                await update.effective_message.reply_text('Não foi possível confirmar sua administração no destino indicado.');return
        fill_reply_text(payload,update.effective_message)
        prepare_buttons(payload)
        original=(getattr(update.effective_message,'text_html',None) or getattr(update.effective_message,'caption_html',None) or getattr(update.effective_message,'text',None) or getattr(update.effective_message,'caption',None) or '')
        had_override=bool(re.sub(r'^/\w+(?:@\w+)?\s*','',original).strip())
        set_copy_source(payload,update.effective_message,had_override)
        if target is None:
            if len(linked)==1:target=linked[0]['id']
            elif linked:
                stage=dict(payload=payload,source='falar',chat_id=update.effective_chat.id,expires=time.time()+600)
                context.user_data['_post_selection']=stage
                await show_selector(update,context,stage);return
        await preview_post(update,context,payload,[target] if target is not None else [],'falar')

    async def handle_falar_callback(self,update,context):
        if not await require_management_access(update):return
        query=update.callback_query;data=query.data
        stage=context.user_data.get('_post_selection')
        if not stage or stage['chat_id']!=update.effective_chat.id or stage.get('message_id')!=query.message.message_id or time.time()>stage['expires']:
            await query.answer('Seleção expirada ou de outra conversa. Prepare o comando novamente.',show_alert=True);return
        if data=='falar:cancel':
            context.user_data.pop('_post_selection',None)
            await query.answer();await query.edit_message_text('Envio cancelado.');return
        if data.startswith('falar:page:'):
            page=int(data.split(':')[-1]) if data.split(':')[-1].isdigit() else 1
            await query.answer();await show_selector(update,context,stage,page,edit=True);return
        if not data.startswith('falar:send:'):
            await query.answer();return
        choice=data.split('falar:send:',1)[1]
        if choice.startswith(('grp:','chn:')):choice=choice.split(':',1)[1]
        cfg=load_config()
        if choice not in ('all','all_groups','all_channels') and str(choice) not in {str(row['id']) for row in get_all_linked_chats(cfg)}:
            await query.answer('Este destino não está mais vinculado.',show_alert=True);return
        targets=resolve_targets(choice,cfg)
        context.user_data.pop('_post_selection',None)
        await query.answer()
        await preview_post(update,context,stage['payload'],targets,stage['source'])

    async def cmd_anunciar(self,update,context):
        if not await require_management_access(update):return
        payload=extract_payload(update.effective_message);payload['pin']=True
        raw=payload['text'];choice=None
        for prefix,value in [('canal ','main_channel'),('grupo ','main_group'),('todos ','all'),('all ','all')]:
            if raw.lower().startswith(prefix):
                choice=value;payload['text']=raw[len(prefix):].strip();break
        if not payload['text'] and not payload['media_id']:
            await update.effective_message.reply_text('Use /anunciar <texto> ou /anunciar canal|grupo|todos <texto>. Você poderá conferir a postagem antes de confirmar.');return
        if payload['text']:payload['text']='📢 <b>[COMUNICADO OFICIAL]</b>\n\n'+payload['text']
        cfg=load_config()
        if choice is None:
            if update.effective_chat.type!='private':choice=update.effective_chat.id
            elif cfg.get('linked_channels') and cfg.get('linked_groups'):
                stage=dict(payload=payload,source='anunciar',chat_id=update.effective_chat.id,expires=time.time()+600)
                context.user_data['_post_selection']=stage;await show_selector(update,context,stage);return
            else:choice='main_channel' if cfg.get('linked_channels') else 'main_group'
        await preview_post(update,context,payload,resolve_targets(choice,cfg),'anunciar')

    async def handle_anunciar_callback(self,update,context):
        if not await require_management_access(update):return
        await update.callback_query.answer('Este botão é de uma versão anterior. Prepare /anunciar novamente para ver a prévia.',show_alert=True)

    async def cmd_canal(self,update,context):
        if not await require_management_access(update):return
        cfg=load_config();channels=cfg.get('linked_channels',[])
        if not channels:
            await update.effective_message.reply_text('Vincule um canal com /setcanal antes de postar.');return
        payload=extract_payload(update.effective_message);body=payload['text']
        target=cfg.get('main_channel_id') or channels[0]['id']
        match=re.match(r'^(-\d+|@\w+)\s*([\s\S]*)',body)
        if match:
            found=next((row for row in channels if str(row['id'])==match.group(1) or str(row.get('username','')).lstrip('@').lower()==match.group(1).lstrip('@').lower()),None)
            if not found:
                await update.effective_message.reply_text('O canal indicado não está vinculado. Nenhum envio foi preparado.');return
            target=found['id'];payload['text']=match.group(2).strip()
        if payload['text'].lower()=='pin' or payload['text'].lower().startswith('pin '):
            payload['pin']=True;payload['text']=payload['text'][3:].strip()
        fill_reply_text(payload,update.effective_message)
        prepare_buttons(payload)
        raw=getattr(update.effective_message,'text_html',None) or getattr(update.effective_message,'caption_html',None) or getattr(update.effective_message,'text',None) or getattr(update.effective_message,'caption',None) or ''
        override=re.sub(r'^/\w+(?:@\w+)?\s*','',raw).strip()
        override=re.sub(r'^(-\d+|@\w+)\s*','',override).strip()
        override=re.sub(r'^pin(?:\s+|$)','',override,flags=re.IGNORECASE).strip()
        set_copy_source(payload,update.effective_message,bool(override))
        payload['message_thread_id']=None
        await preview_post(update,context,payload,[target],'canal')
