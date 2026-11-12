"""Resultados persistentes por destino para transmissões imediatas e agendadas."""
import asyncio
import time

from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.error import BadRequest, Forbidden, RetryAfter

from config import load_config, save_config, normalize_chat_id


def find_entry(cfg, item_id):
    return next((x for x in cfg.get('scheduled_transmissions', []) if x.get('id') == item_id), None)


def persist(cfg):
    if not save_config(cfg):
        raise RuntimeError('Não foi possível registrar o resultado da transmissão.')


def frozen_targets(item, cfg):
    from modules.panel_views.broadcast import get_wizard_targets_list
    titles = {str(normalize_chat_id(x.get('id'))): x.get('title', '')
              for x in cfg.get('linked_groups', []) + cfg.get('linked_channels', [])}
    results = []
    seen = set()
    targets=[row['chat_id'] for row in item['destination_snapshot']] if 'destination_snapshot' in item else get_wizard_targets_list(item.get('target', 'main_channel'), cfg)
    for raw in targets:
        cid = normalize_chat_id(raw)
        if cid in (-1002071806380183, -2071806380183, 2071806380183):
            cid = -1001806380183
        if str(cid) in seen:
            continue
        seen.add(str(cid))
        results.append(dict(chat_id=cid, title=titles.get(str(cid)) or str(cid),
                            status='pending', attempts=0, message_ids=[]))
    return results


def prepare_attempt(item, cfg, mode):
    if mode == 'initial':
        if item.get('status') != 'pending' or item.get('delivery_results'):
            return False
        item['delivery_results'] = frozen_targets(item, cfg)
        selected = item['delivery_results']
    elif mode in ('failed', 'pending'):
        if item.get('status') in ('sending', 'cancelled', 'pending'):
            return False
        selected = [x for x in item.get('delivery_results', []) if x.get('status') == mode]
    else:
        return False
    if not selected:
        return False
    for row in selected:
        row['status'] = 'queued'
    item['active_destination_ids'] = [str(row['chat_id']) for row in selected]
    return True


def update_destination(item_id, chat_id, **fields):
    cfg = load_config()
    item = find_entry(cfg, item_id)
    if not item:
        raise RuntimeError('Transmissão não encontrada.')
    row = next(x for x in item['delivery_results'] if str(x['chat_id']) == str(chat_id))
    row.update(fields, updated_at=time.time())
    persist(cfg)
    return row


def recover_results(item):
    for row in item.get('delivery_results', []):
        if row.get('status') == 'sending':
            row.update(status='unknown', reason='Envio interrompido; confira no destino antes de repetir.')
        elif row.get('status') == 'queued':
            row['status'] = 'pending'


def repair_linked_chat(old_id, new_id):
    """Preserva a autocorreção dos IDs confirmados pelo Telegram no envio guiado."""
    if str(old_id) == str(new_id):
        return
    cfg=load_config()
    changed=False
    for key in ('linked_groups','linked_channels'):
        for chat in cfg.get(key,[]):
            if str(chat.get('id'))==str(old_id):
                chat['id']=new_id
                changed=True
    for key in ('main_group_id','main_channel_id'):
        if str(cfg.get(key))==str(old_id):
            cfg[key]=new_id
            changed=True
    if changed:
        persist(cfg)


class RecordingBot:
    """Registra cada parte confirmada, inclusive textos divididos e legendas longas."""
    def __init__(self, bot, item_id, row):
        self.bot, self.item_id, self.row = bot, item_id, row
        self.ids = []

    def __getattr__(self, name):
        original = getattr(self.bot, name)
        if name not in ('send_message','send_photo','send_video','send_document','send_audio','send_voice','copy_message'):
            return original
        async def send(*args, **kwargs):
            message = await original(*args, **kwargs)
            message_id = getattr(message, 'message_id', None)
            if message_id is not None:
                self.ids.append(message_id)
                actual_id=getattr(getattr(message,'chat',None),'id',None)
                fields={'message_ids':list(self.ids)}
                if actual_id is not None:
                    fields['actual_chat_id']=actual_id
                update_destination(self.item_id, self.row['chat_id'], **fields)
                if actual_id is not None:
                    repair_linked_chat(self.row['chat_id'],actual_id)
            return message
        return send


def failure_details(exc, has_parts):
    if has_parts:
        return 'unknown', 'Envio parcial confirmado; confira as partes no destino.'
    if isinstance(exc, Forbidden):
        return 'failed', 'O bot não tem permissão ou foi bloqueado no destino.'
    if isinstance(exc, BadRequest):
        message = str(exc).lower()
        if 'chat not found' in message:
            return 'failed', 'Destino não encontrado. Confira o ID e se o bot ainda participa do chat.'
        if 'not enough rights' in message or 'not a member' in message:
            return 'failed', 'O bot não tem acesso ou permissão de postagem no destino.'
        if any(value in message for value in ('file_id', 'file identifier', 'wrong remote file')):
            return 'failed', 'Mídia indisponível ou identificador inválido. Prepare a mídia novamente.'
        if 'empty transmission' in message:
            return 'failed', 'O comunicado não possui texto ou mídia para enviar.'
        if 'too long' in message:
            return 'failed', 'O Telegram recusou o tamanho do texto ou da legenda.'
        return 'failed', 'O Telegram rejeitou o pedido. Confira o destino, a mídia e o conteúdo.'
    if isinstance(exc, RetryAfter):
        return 'failed', 'O Telegram limitou o envio. Aguarde antes de tentar novamente.'
    return 'unknown', 'Não foi possível confirmar a entrega; confira no destino.'


async def execute_transmission(bot, original_item):
    from modules.utils import build_rich_buttons_markup, smart_send_message, smart_send_photo, smart_send_video
    item_id = original_item['id']
    current = find_entry(load_config(), item_id)
    if not current:
        return
    item = dict(current)
    selected = set(item.get('active_destination_ids', []))
    rows = [dict(row) for row in item.get('delivery_results', []) if str(row['chat_id']) in selected]
    markup = build_rich_buttons_markup(item.get('buttons', []))
    for index, row in enumerate(rows):
        if index and item.get('delay_seconds', 2) > 0:
            await asyncio.sleep(item.get('delay_seconds', 2))
        update_destination(item_id, row['chat_id'], status='sending', attempts=row.get('attempts', 0)+1,
                           message_ids=[], reason='', pin_warning='')
        proxy = RecordingBot(bot, item_id, row)
        try:
            from modules.broadcast_content import send_content
            message=await send_content(proxy,row['chat_id'],item)
            if not message:
                raise BadRequest('Empty transmission')
        except asyncio.CancelledError:
            # O supervisor converte sending em unknown e queued em pending.
            raise
        except Exception as exc:
            status, reason = failure_details(exc, bool(proxy.ids))
            update_destination(item_id, row['chat_id'], status=status, reason=reason,
                               error_code=type(exc).__name__, message_ids=list(proxy.ids))
            continue
        # Confirma a entrega antes de tentar fixar; falha ao fixar não pede reenvio.
        update_destination(item_id, row['chat_id'], status='sent', message_ids=list(proxy.ids))
        if item.get('pin'):
            try:
                if hasattr(message,'pin'):
                    await message.pin(disable_notification=False)
                else:
                    await bot.pin_chat_message(chat_id=row['chat_id'],message_id=message.message_id,disable_notification=False)
            except Exception:
                update_destination(item_id, row['chat_id'], pin_warning='Entregue, mas não foi possível fixar.')

    cfg = load_config()
    item = find_entry(cfg, item_id)
    if not item:
        return
    results = item.get('delivery_results', [])
    sent = sum(row['status'] == 'sent' for row in results)
    failed = sum(row['status'] == 'failed' for row in results)
    unknown = sum(row['status'] == 'unknown' for row in results)
    item.update(status='completed' if results and sent == len(results) else 'partial',
                sent_at=time.time(), sent_count=sent, fail_count=failed, unknown_count=unknown)
    persist(cfg)
    creator = item.get('creator_id')
    if creator:
        text = (f'📋 Transmissão #{item_id}\n'
                f'Entregues: {sent}\nFalhas confirmadas: {failed}\nSem confirmação: {unknown}\n'
                'Veja os resultados por destino antes de tentar novamente.')
        keyboard = InlineKeyboardMarkup([[InlineKeyboardButton('Ver resultados', callback_data=f'cfg:tx:{item_id}:1')]])
        try:
            await bot.send_message(chat_id=creator, text=text, reply_markup=keyboard)
        except Exception:
            pass  # Falha no relatório não altera a entrega aos destinos.
    from modules.logger_channel import send_mod_log
    try:
        await send_mod_log(bot=bot,event_type='say',title='Transmissão processada',
                           user_info=f'Transmissão <code>{item_id}</code>',
                           admin_info=f'Criador: <code>{creator}</code>',
                           details=f'Entregues: {sent}; falhas confirmadas: {failed}; sem confirmação: {unknown}.')
    except Exception:
        pass  # Registro de auditoria não modifica o resultado persistido.
