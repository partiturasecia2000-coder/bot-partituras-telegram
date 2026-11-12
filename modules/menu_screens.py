"""Texto e organização dos menus; callbacks e regras continuam nos módulos existentes."""
import html
from datetime import datetime
from telegram import InlineKeyboardButton as Button,InlineKeyboardMarkup as Markup
from telegram.helpers import escape_markdown
from config import get_timezone,get_timezone_label


def md(value):return escape_markdown(str(value),version=1)


def state(value):return 'Ativado' if value else 'Desativado'


def status(value):return ('🟢 ' if value else '⚪ ')+state(value)


def action(label,value,callback):
    return Button(('Desativar ' if value else 'Ativar ')+label,callback_data=callback)


def footer(parent='cfg:page:1'):
    if parent=='cfg:page:1':return [[Button('⌂ Início',callback_data=parent),Button('Fechar painel',callback_data='cfg:close')]]
    return [[Button('‹ Voltar',callback_data=parent),Button('⌂ Início',callback_data='cfg:page:1')]]


def screen(title,intro,lines=()):
    return f'*{title}*\n{intro}\n\n'+'\n'.join(lines)


def main_menu(chat_title,cfg):
    groups=len(cfg.get('linked_groups',[]));channels=len(cfg.get('linked_channels',[]))
    pending=sum(item.get('status')=='pending' for item in cfg.get('scheduled_transmissions',[]))
    lines=[f'*Conversa:* {md(chat_title)}',f'{groups} grupo(s) · {channels} canal(is)',
           f'*Antispam:* {status(cfg.get("antispam",{}).get("enabled",True))}',
           f'*Postagens agendadas:* {pending}', '\nEscolha uma área ou use os atalhos abaixo.']
    keyboard=[
        [Button('✉️ Nova postagem',callback_data='cfg:wiz:start'),Button('🗓 Histórico',callback_data='cfg:sched:list')],
        [Button('🛡 Segurança e moderação',callback_data='cfg:hub:security')],
        [Button('👋 Entrada e boas-vindas',callback_data='cfg:hub:welcome')],
        [Button('🎼 Partituras e acervo',callback_data='cfg:sub:acervo')],
        [Button('📨 Mensagens e respostas',callback_data='cfg:hub:messages')],
        [Button('🧹 Limpeza do grupo',callback_data='cfg:hub:clean')],
        [Button('⚙️ Sistema e backups',callback_data='cfg:hub:system')],
        [Button('Fechar painel',callback_data='cfg:close')]]
    return screen('🎼 MAESTRO · PAINEL','Organize seu bot em poucos toques.',lines),Markup(keyboard)


def clean_menu(cfg):
    welcome=cfg.get('welcome',{});cleanup=cfg.get('command_cleanup',{})
    service=welcome.get('delete_service_messages',True);pinned=cfg.get('delete_pinned_service_messages',True)
    admins=cleanup.get('delete_admin_commands',True);members=cleanup.get('delete_non_admin_commands',True)
    lines=[f'*Avisos de entrada e saída:* {status(service)}',f'*Avisos de mensagem fixada:* {status(pinned)}',
           f'*Comandos de administradores:* {state(admins)}',f'*Comandos de membros:* {state(members)}',
           '\nA limpeza manual pede confirmação antes de apagar.']
    keyboard=[[action('limpeza de avisos',service,'cfg:toggle:service_msg')],
              [action('limpeza de fixados',pinned,'cfg:toggle:pin_service_msg')],
              [Button('⚙️ Limpeza de comandos',callback_data='cfg:sub:cmd_clean')],
              [Button('🗑 Como limpar mensagens',callback_data='cfg:sub:clean_help')]]+footer()
    return screen('🧹 LIMPEZA DO GRUPO','Escolha o que o bot pode remover automaticamente.',lines),Markup(keyboard)


def security_menu(cfg):
    spam=cfg.get('antispam',{});enabled=spam.get('enabled',True)
    links=spam.get('block_links',True);invites=spam.get('block_telegram_invites',True);forwards=spam.get('block_forwards',True)
    repeat=cfg.get('antirepeat',{}).get('enabled',True);flood=cfg.get('antiflood',{}).get('enabled',True)
    captcha=cfg.get('captcha',{}).get('enabled',False);words=len(spam.get('banned_words',[]))
    lines=[f'*Proteção antispam:* {status(enabled)}',
           f'*Bloqueio de links:* {state(links)}',f'*Bloqueio de convites:* {state(invites)}',
           f'*Bloqueio de encaminhadas:* {state(forwards)}',f'*Mensagens em excesso:* {state(flood)}',
           f'*Repetição:* {state(repeat)}',f'*Verificação na entrada:* {state(captcha)}',
           f'*Palavras proibidas:* {words} cadastrada(s)',
           '\nOs estados acima são as opções configuradas. Toque para alterar.']
    keyboard=[[action('antispam',enabled,'cfg:toggle:antispam')],
              [action('bloqueio de links',links,'cfg:toggle:links')],
              [action('bloqueio de convites',invites,'cfg:toggle:invites')],
              [action('bloqueio de encaminhadas',forwards,'cfg:toggle:forwards')],
              [Button('🚫 Palavras proibidas',callback_data='cfg:sub:banned')],
              [Button('🌊 Limite de mensagens',callback_data='cfg:sub:antiflood')],
              [action('antirrepetição',repeat,'cfg:toggle:user_repeat')],
              [action('verificação de entrada',captcha,'cfg:toggle:captcha')],
              [Button('✅ Pessoas e links liberados',callback_data='cfg:sub:whitelist_hub')]]+footer()
    return screen('🛡 SEGURANÇA','Controle a proteção e as exceções do grupo.',lines),Markup(keyboard)


def welcome_menu(cfg):
    from modules.panel_views.common import format_time_label
    welcome=cfg.get('welcome',{});on=welcome.get('enabled',True)
    approve=cfg.get('join_requests',{}).get('auto_approve',False);captcha=cfg.get('captcha',{}).get('enabled',False)
    seconds=welcome.get('delete_welcome_after_seconds',600)
    lines=[f'*Boas-vindas:* {status(on)}',f'*Apagar a mensagem após:* {md(format_time_label(seconds))}',
           f'*Aprovar pedidos automaticamente:* {state(approve)}',f'*Verificação de entrada:* {state(captcha)}',
           '\nUse uma mensagem geral ou personalize cada grupo.']
    keyboard=[[Button('✏️ Personalizar boas-vindas',callback_data='cfg:sub:welcome')],
              [action('boas-vindas',on,'cfg:toggle:welcome')],
              [Button('⏱ Tempo para apagar',callback_data='cfg:sub:wtime:general')],
              [action('aprovação automática',approve,'cfg:toggle:join_req')],
              [action('verificação de entrada',captcha,'cfg:toggle:captcha')]]+footer()
    return screen('👋 ENTRADA E BOAS-VINDAS','Receba os membros e ajuste a entrada no grupo.',lines),Markup(keyboard)


def messages_menu(cfg):
    scheduled=sum(item.get('status')=='pending' for item in cfg.get('scheduled_transmissions',[]))
    recurring=cfg.get('recurring_messages',[]);active=sum(item.get('enabled',True) for item in recurring)
    responses=cfg.get('auto_responses',[]);enabled=sum(item.get('enabled',True) for item in responses)
    youtube=cfg.get('youtube_notifications',{})
    lines=[f'*Agendadas:* {scheduled} aguardando envio',f'*Recorrentes:* {active} ativa(s) de {len(recurring)}',
           f'*Respostas automáticas:* {enabled} ativa(s) de {len(responses)}',
           f'*YouTube:* {state(youtube.get("enabled",True))} · {len(youtube.get("channels",[]))} canal(is)',
           '\nToda nova postagem passa por prévia e confirmação.']
    keyboard=[[Button('✉️ Preparar nova postagem',callback_data='cfg:wiz:start')],
              [Button('🗓 Agendamentos e histórico',callback_data='cfg:sched:list')],
              [Button('🔁 Postagens recorrentes',callback_data='cfg:rec:list')],
              [Button('💬 Respostas automáticas',callback_data='cfg:resp:list')],
              [Button('🎬 Vídeos do YouTube',callback_data='cfg:sub:youtube')],
              [Button('📜 Regras do grupo',callback_data='cfg:sub:rules')]]+footer()
    return screen('📨 MENSAGENS E RESPOSTAS','Prepare, programe e acompanhe suas postagens.',lines),Markup(keyboard)


def system_menu(cfg):
    backups=cfg.get('backup_system',{})
    backup_on=backups.get('enabled',True) and (backups.get('daily_backup_enabled',True) or backups.get('weekly_report_enabled',True))
    lines=[f'*Grupos:* {len(cfg.get("linked_groups",[]))} · *Canais:* {len(cfg.get("linked_channels",[]))}',
           f'*Backups automáticos:* {status(backup_on)}',f'*Registro de ações:* {"Configurado" if cfg.get("log_channel_id") else "Não configurado"}',
           f'*Modo noturno:* {state(cfg.get("night_mode",{}).get("enabled",False))}',
           f'*Fuso horário:* {md(get_timezone_label(cfg))}',
           '\nAjuste os vínculos, os horários e a recuperação dos dados.']
    keyboard=[[Button('🌐 Grupos e canais',callback_data='cfg:chats:list')],
              [Button('💾 Backup e restauração',callback_data='cfg:sub:backup')],
              [Button('📋 Registro de ações',callback_data='cfg:sub:logs')],
              [Button('🌙 Silêncio noturno',callback_data='cfg:sub:nightmode')],
              [Button('🕒 Data e fuso horário',callback_data='cfg:sub:timezone')],
              [Button('✅ Pessoas e links liberados',callback_data='cfg:sub:whitelist_hub')],
              [Button('ℹ️ Ajuda e versão',callback_data='cfg:sub:docs')]]+footer()
    return screen('⚙️ SISTEMA','Configurações gerais e proteção dos seus dados.',lines),Markup(keyboard)


def clean_help():
    lines=['Use no grupo que deseja limpar:', '`/limpar 10` · até 10 mensagens',
           '`/limpar 50` · até 50 mensagens', '`/limpar 100` · até 100 mensagens',
           '\nSomente administradores podem usar. O bot mostra uma confirmação antes de apagar; mensagens posteriores ao comando não entram na seleção.']
    return screen('🗑 LIMPEZA MANUAL','Revise a quantidade antes de confirmar.',lines),Markup(footer('cfg:hub:clean'))


def about_menu():
    lines=['*Nesta versão:* painel com botões largos e textos diretos.',
           'Postagens têm prévia, confirmação e resultado por destino.',
           'Backups podem ser conferidos e restaurados no privado.',
           '\nUse /ajuda para consultar os comandos ou abra um tutorial.']
    keyboard=[[Button('📖 Tutoriais',callback_data='tut:main')],[Button('⌨️ Comandos',callback_data='help:cat:all')]]+footer('cfg:hub:system')
    return screen('ℹ️ MAESTRO · VERSÃO 6','Administração de grupos, canais e partituras.',lines),Markup(keyboard)


def timezone_menu(cfg):
    from config import TIMEZONE_LIST
    current=cfg.get('timezone','America/Sao_Paulo');now=datetime.now(get_timezone(cfg))
    lines=[f'*Fuso configurado:* {md(get_timezone_label(cfg))}',f'*Agora nesse fuso:* {now.strftime("%d/%m/%Y %H:%M")}',
           '\nAgendamentos e modo noturno seguem este horário.']
    keyboard=[]
    for key,label in TIMEZONE_LIST:
        text=label.split('(')[0].strip()
        if len(text)>30:text=text[:29]+'…'
        keyboard.append([Button(('✓ ' if key==current else '')+text,callback_data=f'cfg:set:tz:{key}')])
    keyboard += [[Button('✏️ Informar outro fuso',callback_data='cfg:input:tz')]]+footer('cfg:hub:system')
    return screen('🕒 DATA E HORÁRIO','Confira o relógio antes de programar envios.',lines),Markup(keyboard)


def backup_menu(cfg):
    backups=cfg.get('backup_system',{})
    daily=backups.get('daily_backup_enabled',True);weekly=backups.get('weekly_report_enabled',True)
    def last(value):
        return datetime.fromtimestamp(value,get_timezone(cfg)).strftime('%d/%m %H:%M') if value else 'Ainda não registrado'
    lines=[f'*Backup automático:* {state(daily)}',f'*Último backup:* {last(backups.get("last_daily_backup_timestamp",0))}',
           f'*Relatório semanal:* {state(weekly)}',f'*Último relatório:* {last(backups.get("last_weekly_report_timestamp",0))}',
           '\nRestaurar exige validação e confirmação no privado. Uma cópia dos dados atuais é guardada antes da troca.']
    keyboard=[[Button('💾 Criar backup agora',callback_data='cfg:bkp:now')],
              [Button('♻️ Restaurar um backup',callback_data='cfg:restore:start')],
              [Button('📊 Gerar relatório',callback_data='cfg:rep:now')],
              [action('backup automático',daily,'cfg:toggle:daily_bkp')],
              [action('relatório semanal',weekly,'cfg:toggle:weekly_rep')],
              [Button('🎯 Destino dos backups',callback_data='cfg:bkp:channel')]]+footer('cfg:hub:system')
    return screen('💾 BACKUP E RESTAURAÇÃO','Guarde uma cópia e recupere os dados quando precisar.',lines),Markup(keyboard)


def allowed_menu(cfg):
    from config import get_allowed_domains,get_whitelist_users
    text=('<b>✅ PESSOAS E LINKS LIBERADOS</b>\n'
          'Defina as exceções às proteções do grupo.\n\n'
          f'<b>Pessoas liberadas:</b> {len(get_whitelist_users(cfg))}\n'
          f'<b>Endereços permitidos:</b> {len(get_allowed_domains(cfg))}\n\n'
          'Pessoas liberadas podem passar pelos filtros. Permitir um endereço libera os links correspondentes.')
    keyboard=[[Button('👤 Pessoas liberadas',callback_data='cfg:sub:whitelist_users')],
              [Button('🔗 Links permitidos',callback_data='cfg:sub:allowed_links')]]+footer('cfg:hub:security')
    return text,Markup(keyboard)


def acervo_menu(cfg,stats):
    types=stats.get('by_type',{});reply=cfg.get('acervo_group_auto_reply',False);notice=cfg.get('acervo_channel_notify_enabled',True)
    seconds=cfg.get('inline_auto_delete_seconds',0)
    from modules.panel_views.common import format_time_label
    duration=format_time_label(seconds) if seconds else 'Manter no chat'
    text=('<b>🎼 PARTITURAS E ACERVO</b>\n'
          'Busque arquivos e organize os canais de origem.\n\n'
          f'<b>Arquivos indexados:</b> {stats.get("total_files",0)}\n'
          f'Documentos: {types.get("document",0)} · Áudios: {types.get("audio",0)}\n'
          f'<b>Canais no acervo:</b> {stats.get("total_channels",0)}\n'
          f'<b>Resposta automática:</b> {state(reply)}\n'
          f'<b>Avisar novas partituras:</b> {state(notice)}\n'
          f'<b>Resultados da busca:</b> {html.escape(duration)}\n\n'
          'Para adicionar arquivos, encaminhe uma postagem ou envie o result.json exportado do Telegram Desktop. A limpeza manual pede confirmação.')
    keyboard=[[Button('🔎 Buscar partituras',switch_inline_query_current_chat='')],
              [Button('🔄 Importar e sincronizar',callback_data='acervo:scan:menu')],
              [Button('🔗 Links dos canais',callback_data='acervo:channel_links_menu')],
              [action('resposta automática',reply,'acervo:toggle:autoreply')],
              [action('avisos de partituras',notice,'acervo:toggle:group_notify')],
              [Button('⏱ Tempo dos resultados',callback_data='acervo:inline_autodel_menu')],
              [Button('🌐 Canais vinculados',callback_data='cfg:chats:list')],
              [Button('🧹 Limpar textos do acervo',callback_data='acervo:purge_chatter')]]+footer()
    return text,Markup(keyboard)


def night_menu(cfg):
    night=cfg.get('night_mode',{});on=night.get('enabled',False)
    announcements=night.get('announce_start',True) and night.get('announce_end',True)
    lines=[f'*Silêncio noturno:* {status(on)}',f'*Horário:* {md(night.get("start","23:00"))} às {md(night.get("end","07:00"))}',
           f'*Aviso de início:* {state(night.get("announce_start",True))}',f'*Aviso de fim:* {state(night.get("announce_end",True))}',
           '\nDurante o silêncio, somente administradores podem enviar mensagens. Os testes abaixo publicam um aviso no destino.']
    keyboard=[[action('modo noturno',on,'cfg:toggle:nightmode')],
              [action('avisos de horário',announcements,'cfg:toggle:nightmode_ann')],
              [Button('🧪 Testar aviso de início',callback_data='cfg:test:nightmode_start')],
              [Button('🧪 Testar aviso de fim',callback_data='cfg:test:nightmode_end')]]+footer('cfg:hub:system')
    return screen('🌙 SILÊNCIO NOTURNO','Defina quando o grupo fica em silêncio.',lines),Markup(keyboard)


def logs_menu(cfg):
    events=cfg.get('log_events',{});channel=cfg.get('log_channel_id')
    names=(('bans','Banimentos'),('mutes','Silenciamentos'),('warns','Advertências'),('spam','Ações antispam'),('joins','Entradas'))
    lines=[f'*Canal de destino:* {md(channel) if channel else "Não configurado"}',
           *[f'*{name}:* {state(events.get(key,True))}' for key,name in names],
           '\nEscolha quais ações devem ser registradas no canal.']
    keyboard=[[Button('🎯 Definir canal',callback_data='cfg:logs:set_id'),Button('🧪 Testar envio',callback_data='cfg:logs:test')]]
    for key,name in names:keyboard.append([action(name.lower(),events.get(key,True),f'cfg:logs:toggle:{key}')])
    if channel:keyboard.append([Button('Desativar canal de registros',callback_data='cfg:logs:clear')])
    keyboard+=footer('cfg:hub:system')
    return screen('📋 REGISTRO DE AÇÕES','Acompanhe o que o bot faz nos grupos.',lines),Markup(keyboard)


def command_clean_menu(cfg):
    from modules.panel_views.common import format_time_label
    clean=cfg.get('command_cleanup',{});admins=clean.get('delete_admin_commands',True);members=clean.get('delete_non_admin_commands',True)
    seconds=clean.get('bot_notice_delete_seconds',10)
    lines=[f'*Limpar comandos de admins:* {state(admins)}',f'*Limpar comandos de membros:* {state(members)}',
           f'*Prazo dos avisos do bot:* {md(format_time_label(seconds))}',
           '\nEssas opções controlam a limpeza dos comandos e avisos. Confirmações de envio e exclusão continuam sendo exigidas.']
    keyboard=[[action('limpeza de admins',admins,'cfg:toggle:clean_admin')],
              [action('limpeza de membros',members,'cfg:toggle:clean_user')],
              [Button('⏱ Alterar prazo dos avisos',callback_data='cfg:cycle:clean_notice')]]+footer('cfg:hub:clean')
    return screen('⌨️ LIMPEZA DE COMANDOS','Reduza os avisos sem perder as confirmações.',lines),Markup(keyboard)


def spam_menu(cfg):
    spam=cfg.get('antispam',{});on=spam.get('enabled',True)
    fields=(('block_links','links','cfg:toggle:links'),('block_telegram_invites','convites','cfg:toggle:invites'),('block_forwards','encaminhadas','cfg:toggle:forwards'))
    lines=[f'*Antispam:* {status(on)}',*[f'*Bloqueio de {label}:* {state(spam.get(key,True))}' for key,label,_ in fields],
           '\nPessoas e endereços liberados são gerenciados separadamente.']
    keyboard=[[action('antispam',on,'cfg:toggle:antispam')]]
    keyboard += [[action('bloqueio de '+label,spam.get(key,True),callback)] for key,label,callback in fields]
    keyboard += [[Button('🔗 Links permitidos',callback_data='cfg:sub:allowed_links')],
                 [Button('👤 Pessoas liberadas',callback_data='cfg:sub:whitelist_users')]]+footer('cfg:hub:security')
    return screen('🛡 PROTEÇÃO ANTISPAM','Ajuste os bloqueios de mensagens.',lines),Markup(keyboard)


def flood_menu(cfg):
    flood=cfg.get('antiflood',{});on=flood.get('enabled',True)
    lines=[f'*Limite de mensagens:* {status(on)}',f'*Gatilho:* mais de {flood.get("max_messages",5)} mensagens em {flood.get("time_window_seconds",5)}s',
           f'*Silenciamento:* {flood.get("mute_duration_minutes",5)} min',
           '\nO limite evita o envio de muitas mensagens em sequência.']
    keyboard=[[action('limite de mensagens',on,'cfg:toggle:flood')],
              [Button('⏱ Alterar silenciamento',callback_data='cfg:cycle:flood_mute')]]+footer('cfg:hub:security')
    return screen('🌊 MENSAGENS EM EXCESSO','Controle a quantidade de mensagens por pessoa.',lines),Markup(keyboard)


def welcome_groups(cfg,page=1):
    from config import get_welcome_mode_for_chat
    from modules.panel_lists import page_slice,navigation
    groups=cfg.get('linked_groups',[]);shown,page,pages,_=page_slice(groups,page,6)
    lines=['<b>👋 MENSAGENS DE BOAS-VINDAS</b>','Escolha a mensagem geral ou um grupo para personalizar.\n',
           f'<b>Mensagem geral:</b> {state(cfg.get("welcome",{}).get("enabled",True))}',
           f'<b>Grupos vinculados:</b> {len(groups)} · página {page}/{pages}\n']
    keyboard=[[Button('⭐ Mensagem geral',callback_data='cfg:welcome:cfg:general')]]
    modes={'inherited':'Usa a mensagem geral','custom':'Mensagem própria','disabled':'Desativada'}
    for group in shown:
        mode=get_welcome_mode_for_chat(cfg,str(group['id']))
        lines.append(f'<b>{html.escape(str(group.get("title",group["id"]))[:80])}</b> — {modes.get(mode,"Desativada")}')
        keyboard.append([Button('👥 '+str(group.get('title',group['id']))[:28],callback_data=f'cfg:welcome:cfg:{group["id"]}')])
    if not groups:lines.append('Vincule seu grupo com /setgrupo para personalizá-lo aqui.')
    keyboard+=navigation('cfg:welcome:select',page,pages)+footer('cfg:hub:welcome')
    return '\n'.join(lines),Markup(keyboard)


def welcome_editor(cfg,target_group_id='general'):
    from config import get_welcome_for_chat,get_welcome_mode_for_chat
    from modules.panel_views.common import format_time_label
    target=str(target_group_id);general=target in ('general','0','')
    mode='general' if general else get_welcome_mode_for_chat(cfg,target)
    welcome=cfg.get('welcome',{}) if general else get_welcome_for_chat(cfg,target)
    group=next((row for row in cfg.get('linked_groups',[]) if str(row['id'])==target),{})
    title='Mensagem geral' if general else group.get('title','Grupo '+target)
    on=welcome.get('enabled',True) and mode!='disabled'
    buttons=welcome.get('buttons',[]);count=sum(len(row) if isinstance(row,list) else 1 for row in buttons)
    lines=['<b>✏️ PERSONALIZAR BOAS-VINDAS</b>',html.escape(str(title)),
           f'<b>Estado:</b> {state(on)}',
           '<b>Modelo:</b> '+{'general':'Geral','inherited':'Usa a mensagem geral','custom':'Próprio deste grupo','disabled':'Desativado'}.get(mode,'Não definido'),
           f'<b>Foto:</b> {"Configurada" if welcome.get("photo") else "Sem foto"} · <b>Botões:</b> {count}',
           f'<b>Apagar após:</b> {html.escape(format_time_label(welcome.get("delete_welcome_after_seconds",600)))}',
           '\nUse a prévia para conferir a mensagem completa antes de testar no grupo.']
    keyboard=[]
    if general or mode=='custom':
        for label,key in [('✏️ Editar texto','welcome_text'),('🖼 Alterar foto','welcome_photo'),('🔗 Editar botões','welcome_buttons'),('📰 Link em destaque','welcome_article')]:
            keyboard.append([Button(label,callback_data=f'cfg:edit:{key}:{target}')])
        for label,key,present in [('Remover foto','welcome_photo',welcome.get('photo')),('Remover botões','welcome_buttons',buttons),('Remover link em destaque','welcome_article',welcome.get('article_url'))]:
            if present:keyboard.append([Button(label,callback_data=f'cfg:del:{key}:{target}')])
        keyboard += [[action('boas-vindas',on,f'cfg:toggle:welcome:{target}')],
                     [Button('⏱ Tempo para apagar',callback_data=f'cfg:sub:wtime:{target}')]]
    if not general:
        if mode=='inherited':
            keyboard += [[Button('✨ Criar mensagem própria',callback_data=f'cfg:welcome:copy:{target}')],
                         [Button('Desativar neste grupo',callback_data=f'cfg:welcome:disable:{target}')]]
        elif mode=='custom':keyboard.append([Button('Usar a mensagem geral',callback_data=f'cfg:welcome:reset:{target}')])
        elif mode=='disabled':
            keyboard += [[Button('Ativar com mensagem geral',callback_data=f'cfg:welcome:enable_default:{target}')],
                         [Button('Criar mensagem própria',callback_data=f'cfg:welcome:copy:{target}')]]
        if on:keyboard.append([Button('🧪 Testar neste grupo',callback_data=f'cfg:welcome:test:{target}')])
    keyboard += [[Button('👁 Ver prévia',callback_data=f'cfg:preview:welcome:{target}')]]+footer('cfg:welcome:select')
    return '\n'.join(lines),Markup(keyboard)
