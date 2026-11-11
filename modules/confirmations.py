"""Confirmações efêmeras, de uso único e vinculadas a usuário/chat/mensagem."""
import hashlib
import html
import json
import secrets
import time

from telegram import InlineKeyboardButton as Button, InlineKeyboardMarkup as Markup
from telegram.constants import ParseMode
from config import load_config, save_config


class ConfirmationRegistry:
    def __init__(self):
        self.pending = {}

    def issue(self, user_id, chat_id, action, payload, now=None):
        now = time.time() if now is None else now
        self.pending = {key: value for key, value in self.pending.items() if value['expires'] > now}
        if len(self.pending) >= 256:
            self.pending.pop(next(iter(self.pending)))
        token = secrets.token_urlsafe(12)
        self.pending[token] = dict(user_id=user_id, chat_id=chat_id, action=action,
                                   payload=payload, expires=now+120, message_id=None)
        return token

    def bind(self, token, message_id):
        self.pending[token]['message_id'] = message_id

    def consume(self, token, user_id, chat_id, message_id, now=None):
        now = time.time() if now is None else now
        item = self.pending.get(token)
        if not item or item['expires'] <= now:
            self.pending.pop(token, None)
            return None
        if (item['user_id'], item['chat_id'], item['message_id']) != (user_id, chat_id, message_id):
            return None
        return self.pending.pop(token)


def registry(context):
    return context.application.bot_data.setdefault('_confirmations', ConfirmationRegistry())


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def action_target(cfg, action, payload):
    if action == 'chat_purge':
        return {key:payload[key] for key in ('chat_id','anchor','count')}
    if action in ('acervo_clear', 'acervo_purge'):
        return action
    if action == 'banned_clear':
        return cfg.get('antispam', {}).get('banned_words', [])
    if action == 'link_delete':
        from config import get_allowed_domains
        return payload['domain'] if payload['domain'] in get_allowed_domains(cfg) else None
    key = {'rec_delete': 'recurring_messages', 'resp_delete': 'auto_responses',
           'unlink_grp': 'linked_groups', 'unlink_chn': 'linked_channels'}.get(action)
    if key:
        return next((x for x in cfg.get(key, []) if x.get('id') == payload['id']), None)
    if action == 'youtube_delete':
        return next((x for x in cfg.get('youtube_notifications', {}).get('channels', [])
                     if (x.get('url') or x.get('input') or x.get('name')) == payload['key']), None)
    raise ValueError('Ação não permitida.')


async def request_confirmation(update, context, action, payload, description, back):
    cfg = load_config()
    target = action_target(cfg, action, payload)
    if target is None:
        if update.callback_query:
            await update.callback_query.answer('Este item mudou ou não existe mais. Atualize a lista.', show_alert=True)
        return
    payload = dict(payload, expected=fingerprint(target), back=back)
    store = registry(context)
    token = store.issue(update.effective_user.id, update.effective_chat.id, action, payload)
    keyboard = Markup([[Button('✅ Confirmar exclusão', callback_data=f'cfg:confirm:{token}')],
                       [Button('Cancelar', callback_data=f'cfg:abort:{token}')]])
    text = f'<b>⚠️ Confirmar ação</b>\n\n{html.escape(description)}\n\nEsta confirmação expira em 2 minutos.'
    query = update.callback_query
    if query:
        await query.answer()
        await query.edit_message_text(text, reply_markup=keyboard, parse_mode=ParseMode.HTML)
        message_id = query.message.message_id
    else:
        message = await update.effective_message.reply_text(text, reply_markup=keyboard, parse_mode=ParseMode.HTML)
        message_id = message.message_id
    store.bind(token, message_id)


async def execute_action(action, payload, panel=None, context=None):
    cfg = load_config()
    target = action_target(cfg, action, payload)
    if target is None or fingerprint(target) != payload['expected']:
        return '⚠️ O item foi alterado. Abra a lista e confirme novamente.'
    if action == 'chat_purge':
        from modules.utils import safe_delete_message
        count=payload['count']
        if not context or not 1<=count<=100:
            return '⚠️ Pedido de limpeza inválido.'
        await safe_delete_message(context.bot,payload['chat_id'],payload['anchor'])
        deleted=0
        for message_id in range(payload['anchor']-1,payload['anchor']-1-count*2,-1):
            if message_id<=0 or deleted>=count:
                break
            if await safe_delete_message(context.bot,payload['chat_id'],message_id):
                deleted+=1
        return f'🧹 {deleted} mensagem(ns) anterior(es) ao comando foram apagadas.'
    if action in ('acervo_clear', 'acervo_purge'):
        from modules.inline_acervo import acervo_db
        deleted = acervo_db.clear_all() if action == 'acervo_clear' else acervo_db.purge_text_chatter()
        return f'✅ Operação concluída: {deleted} registro(s) removido(s).'
    if action == 'banned_clear':
        cfg.setdefault('antispam', {})['banned_words'] = []
    elif action == 'link_delete':
        cfg.setdefault('antispam', {})['allowed_domains'] = [x for x in cfg['antispam'].get('allowed_domains', []) if x != payload['domain']]
    elif action == 'youtube_delete':
        section = cfg.setdefault('youtube_notifications', {})
        section['channels'] = [x for x in section.get('channels', []) if x != target]
    else:
        key = {'rec_delete':'recurring_messages', 'resp_delete':'auto_responses',
               'unlink_grp':'linked_groups', 'unlink_chn':'linked_channels'}[action]
        cfg[key] = [x for x in cfg.get(key, []) if x.get('id') != payload['id']]
        if action.startswith('unlink_'):
            main_key = 'main_group_id' if action == 'unlink_grp' else 'main_channel_id'
            if cfg.get(main_key) == payload['id']:
                cfg[main_key] = cfg[key][0]['id'] if cfg[key] else None
    if not save_config(cfg):
        return '⚠️ Não foi possível salvar a alteração. Nenhuma nova tentativa foi iniciada.'
    if action == 'resp_delete' and panel and panel.auto_responder_handler:
        panel.auto_responder_handler.invalidate_cache(payload['id'])
    return '✅ Alteração salva.'


async def handle_confirmation(update, context, panel=None):
    data = update.callback_query.data
    if not data.startswith(('cfg:confirm:', 'cfg:abort:')):
        return False
    from modules.access import require_management_access
    if not await require_management_access(update):
        return True
    query = update.callback_query
    token = data.split(':')[-1]
    item = registry(context).consume(token, update.effective_user.id, update.effective_chat.id, query.message.message_id)
    if not item:
        await query.answer('Confirmação expirada, já usada ou pertencente a outra mensagem/pessoa.', show_alert=True)
        return True
    await query.answer()
    text = 'Ação cancelada. Nenhum dado foi alterado.' if data.startswith('cfg:abort:') else await execute_action(item['action'], item['payload'], panel, context)
    await query.edit_message_text(text, reply_markup=Markup([[Button('◀ Voltar', callback_data=item['payload']['back'])]]))
    return True


async def confirm_panel_action(panel, update, context):
    from modules.panel_lists import link_key
    data = update.callback_query.data
    if data != 'cfg:banned:clear_all' and not data.startswith(('cfg:rec:del:', 'cfg:resp:del:', 'cfg:chat:unlink:',
            'cfg:youtube:rm:', 'cfg:ytdel:', 'cfg:linkdel:', 'cfg:del:allowed_link:')):
        return False
    parts = data.split(':')
    cfg = load_config()
    pages = context.user_data.get('_list_pages', {})
    if data == 'cfg:banned:clear_all':
        args = ('banned_clear', {}, 'Apagar todas as palavras proibidas? Esta ação não tem desfazer.', 'cfg:sub:banned')
    elif data.startswith('cfg:rec:del:'):
        page = parts[4] if len(parts)>4 and parts[4].isdigit() else '1'
        args = ('rec_delete', {'id':int(parts[3])}, f'Excluir a mensagem recorrente #{parts[3]} e sua programação?', f'cfg:rec:list:{page}')
    elif data.startswith('cfg:resp:del:'):
        args = ('resp_delete', {'id':int(parts[3])}, f'Excluir a resposta automática #{parts[3]}?', f'cfg:list:resp:{pages.get("resp",1)}')
    elif data.startswith('cfg:chat:unlink:'):
        args = ('unlink_'+parts[3], {'id':int(parts[4])}, f'Desvincular o chat {parts[4]}? Ele deixará de integrar as listas de destino.', f'cfg:list:chats:{pages.get("chats",1)}')
    elif data.startswith(('cfg:youtube:rm:', 'cfg:ytdel:')):
        channels = cfg.get('youtube_notifications', {}).get('channels', [])
        if data.startswith('cfg:ytdel:'):
            item = next((x for x in channels if link_key(x.get('url') or x.get('input') or x.get('name','')) == parts[-1]), None)
        else:
            index=int(parts[-1]);item=channels[index] if 0<=index<len(channels) else None
        if not item:
            await update.callback_query.answer('Canal não encontrado. Atualize a lista.', show_alert=True)
            return True
        key=item.get('url') or item.get('input') or item.get('name')
        args=('youtube_delete',{'key':key},f'Remover do monitoramento o canal {item.get("name",key)}?',f'cfg:list:youtube:{pages.get("youtube",1)}')
    elif data.startswith(('cfg:linkdel:', 'cfg:del:allowed_link:')):
        from config import get_allowed_domains
        domain = next((x for x in get_allowed_domains(cfg) if link_key(x)==parts[-1]),None) if data.startswith('cfg:linkdel:') else data.split('cfg:del:allowed_link:',1)[1]
        if domain is None:
            await update.callback_query.answer('Endereço não encontrado.',show_alert=True)
            return True
        args=('link_delete',{'domain':domain},f'Remover este endereço dos links permitidos?\n{domain}',f'cfg:list:links:{pages.get("links",1)}')
    else:
        return False
    await request_confirmation(update,context,*args)
    return True
