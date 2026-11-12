"""Listas limitadas por página, com callbacks curtos e conteúdo escapado."""
import hashlib
import html
from telegram import InlineKeyboardButton as Button, InlineKeyboardMarkup as Markup
from telegram.helpers import escape_markdown


def page_slice(items, page=1, size=6):
    size = max(1, int(size))
    pages = max(1, (len(items)+size-1)//size)
    try:
        page = int(page)
    except (ValueError, TypeError):
        page = 1
    page = min(pages, max(1, page))
    offset = (page-1)*size
    return items[offset:offset+size], page, pages, offset


def navigation(prefix, page, pages):
    row = []
    if page > 1:
        row.append(Button('◀ Anterior', callback_data=f'{prefix}:{page-1}'))
    row.append(Button(f'{page}/{pages}', callback_data='cfg:noop'))
    if page < pages:
        row.append(Button('Próxima ▶', callback_data=f'{prefix}:{page+1}'))
    return [row]


def md(value, limit=80):
    return escape_markdown(str(value)[:limit], version=1)


STATUS = dict(draft='Prévia não confirmada',expired='Prévia expirada',pending='Aguardando', queued='Na fila', sending='Em envio', sent='Entregue',
              failed='Falha confirmada', unknown='Sem confirmação', interrupted='Interrompida',
              completed='Concluída', partial='Com pendências', cancelled='Cancelada')


def transmissions_page(cfg, page=1):
    items = list(cfg.get('scheduled_transmissions', []))
    priority = {'sending': 0, 'pending': 1, 'interrupted': 2, 'partial': 2, 'failed': 2}
    items.sort(key=lambda x: (priority.get(x.get('status'), 3), -x.get('id', 0)))
    shown, page, pages, _ = page_slice(items, page, 5)
    lines = [f'🗓️ *TRANSMISSÕES E HISTÓRICO* — {len(items)} registro(s)', f'Página {page}/{pages}\n']
    buttons = []
    for item in shown:
        item_id = item['id']
        lines.append(f'• #{item_id}: {md(STATUS.get(item.get("status"), "Sem estado"))}\n'
                     f'  {md(item.get("schedule_display", "Horário não informado"))}')
        buttons.append([Button(f'📋 Resultados #{item_id}', callback_data=f'cfg:tx:{item_id}:1')])
        if item.get('status') == 'pending':
            buttons.append([Button('🚀 Disparar agora', callback_data=f'cfg:sched:fire:{item_id}'),
                            Button('Cancelar agendamento', callback_data=f'cfg:sched:cancel:{item_id}')])
    if not shown:
        lines.append('Nenhuma transmissão registrada.')
    buttons += navigation('cfg:list:tx', page, pages)
    buttons += [[Button('📢 Nova transmissão', callback_data='cfg:wiz:start'), Button('◀ Painel', callback_data='cfg:page:1')]]
    return '\n'.join(lines), Markup(buttons)


def transmission_detail(cfg, item_id, page=1, back_page=1):
    from modules.transmission_delivery import find_entry
    item = find_entry(cfg, item_id)
    if not item:
        return 'Transmissão não encontrada.', Markup([[Button('◀ Lista', callback_data='cfg:list:tx:1')]])
    results = item.get('delivery_results', [])
    shown, page, pages, _ = page_slice(results, page, 6)
    lines = [f'<b>📋 Transmissão #{item_id}</b>', html.escape(STATUS.get(item.get('status'), 'Sem estado')),
             f'Destinos: {len(results)} — página {page}/{pages}\n']
    for row in shown:
        lines.append(f'<b>{html.escape(str(row.get("title", row["chat_id"]))[:80])}</b> '
                     f'(<code>{html.escape(str(row.get("actual_chat_id",row["chat_id"])))}</code>)\n'
                     f'• {STATUS.get(row.get("status"), "Sem estado")} — tentativas: {row.get("attempts", 0)}')
        if row.get('reason'):
            lines.append(html.escape(row['reason'][:160]))
        if row.get('pin_warning'):
            lines.append(html.escape(row['pin_warning']))
        ids = row.get('message_ids', [])
        if ids:
            lines.append('Partes confirmadas: '+', '.join(str(x) for x in ids[:6]) + (f' (+{len(ids)-6})' if len(ids)>6 else ''))
        lines.append('')
    if not results:
        lines.append(html.escape(item.get('delivery_note') or 'O detalhamento começa no primeiro envio desta versão. Envios antigos não têm resultados por destino.'))
    buttons = navigation(f'cfg:tx:{item_id}', page, pages)
    if item.get('status') not in ('sending', 'cancelled', 'pending'):
        if any(x.get('status') == 'failed' for x in results):
            buttons.append([Button('🔁 Tentar somente falhas confirmadas', callback_data=f'cfg:txretry:{item_id}')])
        if any(x.get('status') == 'pending' for x in results):
            buttons.append([Button('▶ Continuar destinos não enviados', callback_data=f'cfg:txresume:{item_id}')])
    if any(x.get('status') == 'unknown' for x in results):
        lines.append('⚠️ Envios sem confirmação ficam fora das novas tentativas. Confira-os no Telegram.')
    buttons += [[Button('🔄 Atualizar', callback_data=f'cfg:tx:{item_id}:{page}')],
                [Button('◀ Transmissões', callback_data=f'cfg:list:tx:{back_page}')]]
    return '\n'.join(lines), Markup(buttons)


def chats_page(cfg, page=1, kind='chats'):
    items = [('grp',x) for x in cfg.get('linked_groups', [])] + [('chn',x) for x in cfg.get('linked_channels', [])]
    if kind=='channels':items=[item for item in items if item[0]=='chn']
    if kind=='groups':items=[item for item in items if item[0]=='grp']
    shown, page, pages, _ = page_slice(items, page, 8)
    buttons = []
    for category, item in shown:
        star = ' ⭐' if item['id'] == cfg.get('main_group_id' if category=='grp' else 'main_channel_id') else ''
        buttons.append([Button(('👥 ' if category=='grp' else '📢 ')+str(item.get('title',item['id']))[:30]+star,
                               callback_data=f'cfg:chat:info:{category}:{item["id"]}')])
    buttons += navigation('cfg:list:'+kind,page,pages)
    buttons += [[Button('➕ Como vincular',callback_data='cfg:chats:how_to')], [Button('◀ Painel',callback_data='cfg:page:1')]]
    heading={'channels':'CANAIS VINCULADOS','groups':'GRUPOS VINCULADOS'}.get(kind,'GRUPOS E CANAIS')
    return f'🌐 *{heading}*\n{len(items)} chat(s) — página {page}/{pages}', Markup(buttons)


def responders_page(title,cfg,page=1):
    items=cfg.get('auto_responses',[])
    shown,page,pages,_=page_slice(items,page,5)
    lines=[f'🤖 *RESPOSTAS AUTOMÁTICAS*\n{len(items)} resposta(s) — página {page}/{pages}']
    buttons=[]
    for item in shown:
        lines.append(f'• #{item["id"]}: {md(item.get("title","Resposta"),60)}\n'
                     f'  Gatilho: {md(item.get("pattern",""),60)}')
        buttons.append([Button(('🟢 ' if item.get('enabled',True) else '🔴 ')+str(item.get('title',item['id']))[:30],
                               callback_data=f'cfg:resp:detail:{item["id"]}')])
    buttons+=navigation('cfg:list:resp',page,pages)
    buttons += [[Button('➕ Nova resposta',callback_data='cfg:resp:add')], [Button('◀ Painel',callback_data='cfg:page:1')]]
    return '\n'.join(lines),Markup(buttons)


def wizard_destinations(cfg,page=1):
    from config import normalize_chat_id
    groups=cfg.get('linked_groups',[]); channels=cfg.get('linked_channels',[])
    shown,page,pages,_=page_slice([('grp',x) for x in groups]+[('chn',x) for x in channels],page,6)
    buttons=[[Button('📢 Canal principal',callback_data='cfg:wiz:dest:main_channel')]] if channels else [[Button('➕ Vincular canal',callback_data='cfg:wiz:add_channel')]]
    buttons += [[Button('Todos os grupos',callback_data='cfg:wiz:dest:all_groups'),Button('Todos os canais',callback_data='cfg:wiz:dest:all_channels')],
                [Button('🌐 Todos',callback_data='cfg:wiz:dest:all')]]
    for kind,item in shown:
        buttons.append([Button(str(item.get('title',item['id']))[:32],callback_data=f'cfg:wiz:dest:{kind}:{normalize_chat_id(item["id"])}')])
    buttons+=navigation('cfg:list:dest',page,pages)
    buttons += [[Button('◀ Painel',callback_data='cfg:page:1')]]
    return f'📢 *GUIA DE TRANSMISSÃO — PASSO 1/4*\nEscolha o destino — página {page}/{pages}',Markup(buttons)


def link_key(domain):
    return hashlib.sha256(domain.encode()).hexdigest()[:20]


def allowed_links(cfg,page=1):
    from modules.whitelist import get_allowed_domains,PRESET_DOMAINS
    items=get_allowed_domains(cfg);shown,page,pages,_=page_slice(items,page,6)
    lines=[f'<b>🌐 LINKS PERMITIDOS</b>\n{len(items)} endereço(s) — página {page}/{pages}']
    buttons=[]
    for domain in shown:
        lines.append('<code>'+html.escape(domain[:200])+'</code>')
        buttons.append([Button('🗑️ '+domain[:30],callback_data=f'cfg:linkdel:{link_key(domain)}')])
    for key,preset in PRESET_DOMAINS.items():
        buttons.append([Button(preset['label'],callback_data=f'cfg:preset:link:{key}')])
    buttons+=navigation('cfg:list:links',page,pages)
    buttons += [[Button('➕ Adicionar',callback_data='cfg:add:allowed_link')],[Button('◀ Whitelist',callback_data='cfg:sub:whitelist_hub')]]
    return '\n'.join(lines),Markup(buttons)


def youtube_channels(cfg,page=1):
    items=cfg.get('youtube_notifications',{}).get('channels',[])
    shown,page,pages,offset=page_slice(items,page,6)
    buttons=[[Button('❌ '+str(ch.get('name','Canal'))[:30],callback_data=f'cfg:ytdel:{link_key(ch.get("url") or ch.get("input") or ch.get("name", ""))}')] for ch in shown]
    buttons+=navigation('cfg:list:youtube',page,pages)
    buttons += [[Button('◀ YouTube',callback_data='cfg:sub:youtube')]]
    return f'🗑️ *CANAIS DO YOUTUBE*\n{len(items)} canal(is) — página {page}/{pages}',Markup(buttons)


def banned_words(cfg,page=1):
    items=cfg.get('antispam',{}).get('banned_words',[])
    shown,page,pages,offset=page_slice(items,page,8)
    lines=[f'🚫 *PALAVRAS PROIBIDAS*\n{len(items)} palavra(s) — página {page}/{pages}']
    lines += [f'{offset+index+1}. {md(word,120)}' for index,word in enumerate(shown)]
    buttons=navigation('cfg:list:banned',page,pages)
    buttons += [[Button('➕ Adicionar',callback_data='cfg:banned:add'),Button('➖ Remover',callback_data='cfg:banned:remove')],
                [Button('◀ Configurações',callback_data='cfg:sub:banned')]]
    return '\n'.join(lines),Markup(buttons)
