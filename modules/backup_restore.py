"""Validação, prévia e restauração de backups recebidos pelo administrador."""
import asyncio
from dataclasses import dataclass,field
import json
import math
from pathlib import Path
import shutil
import sqlite3
import stat
import re
import time
from uuid import uuid4
import zipfile

from telegram import InlineKeyboardButton as Button,InlineKeyboardMarkup as Markup
from telegram.constants import ParseMode

import config
from modules.restore_files import DATA_FILES,JOURNAL,sha,create_safety_backup,apply_transaction,cleanup_transaction

MAX_UPLOAD=20*1024*1024
MAX_EXPANDED=128*1024*1024
ALLOWED=set(DATA_FILES)|{'MANIFESTO.txt'}


class InvalidBackup(ValueError):
    pass


class RestoreCommittedError(RuntimeError):
    """Os dados foram aplicados, mas o runtime precisa reiniciar."""


@dataclass
class ValidatedBackup:
    folder:Path
    paths:dict=field(repr=False)
    hashes:dict=field(repr=False)
    configuration:dict=field(repr=False)
    scores:int=0
    deletions:int=0


def _json_object(path):
    def number(text):
        value=float(text)
        if not math.isfinite(value):raise InvalidBackup('Número JSON inválido.')
        return value
    def pairs(values):
        result={}
        for key,value in values:
            if key in result:raise InvalidBackup('JSON com campos duplicados.')
            result[key]=value
        return result
    try:
        value=json.loads(path.read_text(encoding='utf-8-sig'),object_pairs_hook=pairs,parse_float=number,
                         parse_constant=lambda _:(_ for _ in ()).throw(InvalidBackup('Número JSON inválido.')))
    except (ValueError,UnicodeError,OSError,RecursionError):
        raise InvalidBackup('Configuração JSON inválida.') from None
    if not isinstance(value,dict):raise InvalidBackup('A configuração precisa ser um objeto JSON.')
    return value


def validate_configuration(value):
    if not {'timezone','antispam','auto_responses','recurring_messages'}<=set(value):
        raise InvalidBackup('Faltam campos básicos de configuração do bot.')
    try:
        from zoneinfo import ZoneInfo
        ZoneInfo(value['timezone'])
    except (ValueError,TypeError,KeyError):
        raise InvalidBackup('Fuso horário incompatível.') from None
    def known_types(item,default):
        if isinstance(default,dict):
            if not isinstance(item,dict):raise InvalidBackup('Estrutura de configuração incompatível.')
            for key,example in default.items():
                if key in item:known_types(item[key],example)
        elif isinstance(default,list):
            if not isinstance(item,list):raise InvalidBackup('Lista de configuração incompatível.')
        elif isinstance(default,bool):
            if type(item) is not bool:raise InvalidBackup('Valor de configuração incompatível.')
        elif isinstance(default,(int,float)):
            if type(item) not in (int,float):raise InvalidBackup('Valor numérico de configuração incompatível.')
        elif isinstance(default,str) and not isinstance(item,str):
            raise InvalidBackup('Texto de configuração incompatível.')
    known_types(value,config.DEFAULT_CONFIG)
    for key in ('linked_groups','linked_channels','recurring_messages','auto_responses','scheduled_transmissions'):
        rows=value.get(key,[])
        if not isinstance(rows,list) or len(rows)>20000 or any(not isinstance(row,dict) for row in rows):
            raise InvalidBackup('Lista de configuração incompatível.')
        seen=set()
        for row in rows:
            identifier=row.get('id')
            if not isinstance(identifier,(int,str)) or isinstance(identifier,bool) or str(identifier) in seen:
                raise InvalidBackup('Identificadores ausentes ou duplicados.')
            seen.add(str(identifier))
    if 'panel_admin_ids' in value and not isinstance(value['panel_admin_ids'],list):raise InvalidBackup('Lista administrativa inválida.')
    for row in value.get('scheduled_transmissions',[]):
        if row.get('status') not in ('draft','expired','pending','sending','interrupted','failed','completed','partial','cancelled'):
            raise InvalidBackup('Estado de transmissão incompatível.')
        if 'delivery_results' in row and (not isinstance(row['delivery_results'],list) or any(not isinstance(x,dict) or 'chat_id' not in x for x in row['delivery_results'])):
            raise InvalidBackup('Resultados de transmissão incompatíveis.')


def validate_database(path,kind):
    connection=None
    try:
        connection=sqlite3.connect(f'{path.resolve().as_uri()}?mode=ro',uri=True,timeout=10)
        connection.execute('PRAGMA trusted_schema=OFF')
        if connection.execute('PRAGMA quick_check').fetchall()!=[('ok',)]:raise InvalidBackup('Banco SQLite sem integridade.')
        definitions=connection.execute("SELECT type,name,sql FROM sqlite_master WHERE name NOT LIKE 'sqlite_%'").fetchall()
        tables={'acervo','varredura_progresso'} if kind=='acervo' else {'deletions'}
        for type_,name,sql in definitions:
            if type_ in ('view','trigger') or (type_=='table' and (name not in tables or 'VIRTUAL' in (sql or '').upper())):
                raise InvalidBackup('Estrutura SQLite incompatível.')
        target='acervo' if kind=='acervo' else 'deletions'
        actual_tables={name for type_,name,sql in definitions if type_=='table'}
        if not tables<=actual_tables:raise InvalidBackup('Tabelas SQLite incompletas.')
        columns={row[1] for row in connection.execute(f'PRAGMA table_info({target})')}
        required=({'id','file_id','file_unique_id','file_name','title','clean_title','file_type','file_size','file_size_str',
                   'channel_id','channel_title','channel_username','message_id','post_url','caption','created_at'}
                  if kind=='acervo' else {'chat_id','message_id','due_at','attempts','status','error'})
        if not required<=columns:raise InvalidBackup('Colunas SQLite incompatíveis.')
        return connection.execute(f'SELECT COUNT(*) FROM {target}').fetchone()[0]
    except sqlite3.DatabaseError:
        raise InvalidBackup('Arquivo SQLite inválido ou incompatível.') from None
    finally:
        if connection:connection.close()


def validate_archive(upload,folder):
    upload=Path(upload);folder=Path(folder)
    if upload.stat().st_size>MAX_UPLOAD:raise InvalidBackup('ZIP acima do limite de 20 MB.')
    paths={};total=0
    try:
        with zipfile.ZipFile(upload) as archive:
            infos=archive.infolist()
            if not infos or len(infos)>len(ALLOWED):raise InvalidBackup('Conteúdo do backup incompatível.')
            seen=set()
            for info in infos:
                mode=info.external_attr>>16
                if info.filename not in ALLOWED or info.filename in seen or info.is_dir() or stat.S_ISLNK(mode) or info.flag_bits&1:
                    raise InvalidBackup('O ZIP contém nomes, links ou arquivos não permitidos.')
                seen.add(info.filename);total+=info.file_size
                if total>MAX_EXPANDED:raise InvalidBackup('Backup descompactado acima do limite de 128 MB.')
                destination=folder/info.filename
                count=0
                with archive.open(info) as source,destination.open('xb') as target:
                    for chunk in iter(lambda:source.read(1024*1024),b''):
                        count+=len(chunk)
                        if count>info.file_size or count>MAX_EXPANDED:raise InvalidBackup('Tamanho do backup incompatível.')
                        target.write(chunk)
                paths[info.filename]=destination
    except (zipfile.BadZipFile,RuntimeError):
        raise InvalidBackup('ZIP inválido, incompleto ou criptografado.') from None
    if 'config.json' not in paths:raise InvalidBackup('O backup precisa conter config.json.')
    value=_json_object(paths['config.json']);validate_configuration(value)
    if '.config_backup.json' in paths:_json_object(paths['.config_backup.json'])
    scores=validate_database(paths['acervo_partituras.db'],'acervo') if 'acervo_partituras.db' in paths else 0
    deletions=validate_database(paths['agendamentos.db'],'deletions') if 'agendamentos.db' in paths else 0
    return ValidatedBackup(folder,paths,{name:sha(path) for name,path in paths.items()},value,scores,deletions)


def normalized_restoration(value,current,actor_id):
    import copy
    result=copy.deepcopy(value)
    result['telegram_bot_token']=current.get('telegram_bot_token','')
    result['panel_admin_ids']=list(dict.fromkeys([*current.get('panel_admin_ids',[]),actor_id]))
    result['log_channel_id']=current.get('log_channel_id')
    backup=result.setdefault('backup_system',{})
    backup['channel_id']=current.get('backup_system',{}).get('channel_id')
    # Os dois controles visíveis retomam as rotinas; não criar um bloqueio geral sem botão no painel.
    backup.update(enabled=True,daily_backup_enabled=False,weekly_report_enabled=False)
    result.setdefault('youtube_notifications',{})['enabled']=False
    result['_pending_inputs']={}
    for row in result.get('recurring_messages',[]):
        row.update(enabled=False,messages_counter_last=0,restore_review_required=True)
    for row in result.get('scheduled_transmissions',[]):
        if row.get('status')=='draft':row['status']='expired'
        if row.get('status') in ('pending','sending','interrupted','partial','failed'):
            row.update(status='interrupted',restore_review_required=True)
            for destination in row.get('delivery_results',[]):
                if destination.get('status')!='sent':
                    destination.update(status='unknown',reason='Estado de um backup antigo; confira no destino antes de criar novo envio.')
    return result


def restore_blocks_writes(application):
    return bool(application.bot_data.get('_restore_active') or application.bot_data.get('_restore_blocked'))


def service_for(context):
    if '_restore_service' not in context.application.bot_data:
        context.application.bot_data['_restore_service']=RestorationService(config.BASE_DIR)
    return context.application.bot_data['_restore_service']


class RestorationService:
    def __init__(self,base):
        self.base=Path(base).resolve();self.records={};self.downloads={};self.busy=False
        staging=self.base/'.restore-staging'
        if staging.exists():
            for folder in staging.iterdir():
                if folder.is_dir() and re.fullmatch('[0-9a-f]{32}',folder.name) and time.time()-folder.stat().st_mtime>3600:
                    self.discard_folder(folder)

    def discard_folder(self,folder):
        folder=Path(folder).resolve()
        parent=(self.base/'.restore-staging').resolve()
        if folder.parent!=parent or not re.fullmatch('[0-9a-f]{32}',folder.name):raise ValueError('Diretório temporário inválido.')
        if folder.exists():shutil.rmtree(folder)

    def prune(self):
        for token,record in list(self.records.items()):
            if time.time()>record['expires']:
                self.discard_folder(record['backup'].folder);self.records.pop(token,None)

    async def apply(self,application,record):
        if self.busy or application.bot_data.get('_restore_blocked'):raise RuntimeError('Restauração indisponível.')
        backup=record['backup']
        if any(sha(path)!=backup.hashes[name] for name,path in backup.paths.items()):raise InvalidBackup('O arquivo mudou após a validação.')
        # Revalidar os dados e bancos antes de substituir qualquer arquivo.
        validate_configuration(_json_object(backup.paths['config.json']))
        for name,kind in [('acervo_partituras.db','acervo'),('agendamentos.db','queue')]:
            if name in backup.paths:validate_database(backup.paths[name],kind)
        required=sum((self.base/name).stat().st_size for name in DATA_FILES if (self.base/name).exists())*3
        required+=sum(path.stat().st_size for path in backup.paths.values())*2+10*1024*1024
        if shutil.disk_usage(self.base).free<required:raise InvalidBackup('Espaço insuficiente para a cópia anterior e a reversão.')
        self.busy=True;application.bot_data['_restore_active']=True
        scheduler=application.bot_data.get('task_scheduler')
        was_started=bool(scheduler and scheduler.started)
        safety=None;committed=False
        try:
            if scheduler:await scheduler.stop()
            scans=list(application.bot_data.get('_acervo_scan_tasks',set()))+list(application.bot_data.get('_delayed_response_tasks',set()))
            for task in scans:task.cancel()
            if scans:await asyncio.gather(*scans,return_exceptions=True)
            # Sem await durante a troca: updates serializados e gravações protegidas.
            with config._CONFIG_LOCK:
                current=config.load_config()
                safety=create_safety_backup(self.base)
                restored=normalized_restoration(backup.configuration,current,record['user_id'])
                restored['last_restore']={'at':time.time(),'actor_id':record['user_id'],'safety_backup':safety.name}
                from modules.storage import write_json_atomic
                replacements={}
                for name in ('acervo_partituras.db','agendamentos.db'):
                    if name in backup.paths:
                        working=backup.folder/('apply_'+name)
                        shutil.copyfile(backup.paths[name],working)
                        if name=='agendamentos.db':
                            connection=sqlite3.connect(working)
                            try:
                                connection.execute("UPDATE deletions SET status='paused',error='RestoreReview' WHERE status='pending'")
                                connection.commit()
                            finally:connection.close()
                        replacements[name]=working
                for name in ('config.json','.config_backup.json'):
                    working=backup.folder/('apply_'+name.lstrip('.'))
                    write_json_atomic(working,restored);replacements[name]=working
                transaction=apply_transaction(self.base,replacements)
                committed=True
                config.invalidate_config_snapshots()
                try:cleanup_transaction(self.base,transaction)
                except OSError:pass
            panel=application.bot_data.get('_panel_handler')
            if panel:
                panel.wizard_states.clear();panel.last_received_private_messages.clear();panel.pending_inputs.clear()
                if panel.auto_responder_handler:panel.auto_responder_handler.invalidate_cache()
            from modules.recurring import GROUP_MESSAGE_COUNTS
            GROUP_MESSAGE_COUNTS.clear()
            application.bot_data.pop('_confirmations',None)
            return safety
        except Exception:
            if committed:
                application.bot_data['_restore_blocked']=True
                raise RestoreCommittedError('Dados restaurados; reinicie para atualizar o estado em memória.') from None
            # Se a reversão não pôde terminar, manter o sistema pausado até recuperar no início.
            if (self.base/JOURNAL).exists():application.bot_data['_restore_blocked']=True
            raise
        finally:
            self.busy=False;application.bot_data['_restore_active']=False
            if was_started and not application.bot_data.get('_restore_blocked'):
                try:await scheduler.start()
                except Exception:
                    application.bot_data['_restore_blocked']=True
                    if committed:raise RestoreCommittedError('Dados restaurados; reinicie o agendador.') from None
                    raise


async def handle_restore_callback(update,context):
    query=update.callback_query;data=query.data
    if not data.startswith('cfg:restore:'):return False
    from modules.access import require_management_access
    if not await require_management_access(update):return True
    if update.effective_chat.type!='private':
        await query.answer('Restaure backups na conversa privada com o bot.',show_alert=True);return True
    service=service_for(context);service.prune()
    action=data.split(':')[2]
    if action=='start':
        context.user_data['_restore_upload_until']=time.time()+600
        context.user_data.pop('_restore_legacy',None)
        await query.answer()
        await query.message.reply_text('📥 Envie aqui o ZIP de backup do bot (até 20 MB). Vou validar e mostrar os dados que serão substituídos. Nada será restaurado antes da confirmação.',
            reply_markup=Markup([[Button('Cancelar restauração',callback_data='cfg:restore:cancel_upload')]]))
        return True
    if action=='cancel_upload':
        context.user_data.pop('_restore_upload_until',None)
        context.user_data.pop('_restore_legacy',None)
        await query.answer('Recebimento cancelado.');return True
    token=data.split(':')[-1]
    if action=='download':
        record=service.downloads.get(token)
        if not record or record['user_id']!=update.effective_user.id or record['expires']<time.time():
            await query.answer('Download expirado ou de outra pessoa.',show_alert=True);return True
        await query.answer()
        with record['path'].open('rb') as stream:
            await context.bot.send_document(chat_id=update.effective_chat.id,document=stream,filename=record['path'].name,
                caption='Cópia do estado anterior à restauração. Guarde-a para recuperação.')
        return True
    record=service.records.get(token)
    if not record or record['user_id']!=update.effective_user.id or record['chat_id']!=update.effective_chat.id or record['message_id']!=query.message.message_id:
        await query.answer('Restauração expirada, já usada ou de outra mensagem/pessoa.',show_alert=True);return True
    if action=='cancel':
        service.records.pop(token,None);service.discard_folder(record['backup'].folder)
        await query.answer();await query.edit_message_text('Restauração cancelada. Dados atuais preservados.');return True
    if action!='apply':await query.answer();return True
    service.records.pop(token,None)  # Uso único, antes do primeiro await.
    await query.answer('Validando novamente e criando a cópia anterior...')
    try:
        safety=await service.apply(context.application,record)
    except RestoreCommittedError:
        await query.edit_message_text('Os dados foram restaurados e a cópia anterior foi guardada, mas o bot precisa reiniciar para atualizar suas rotinas. Reinicie a aplicação no Discloud.')
        return True
    except Exception:
        text='Não foi possível restaurar. Os arquivos anteriores foram mantidos ou revertidos.'
        if context.application.bot_data.get('_restore_blocked'):
            text='A restauração foi interrompida e o bot está pausado. Reinicie a aplicação para recuperar a cópia anterior pelo diário local.'
        await query.edit_message_text(text)
        return True
    finally:
        service.discard_folder(record['backup'].folder)
    download=uuid4().hex[:20]
    service.downloads[download]=dict(path=safety,user_id=update.effective_user.id,expires=time.time()+3600)
    await query.edit_message_text('✅ Backup restaurado. Token, ambiente e acesso do responsável foram preservados. Programações antigas, YouTube e backups automáticos estão pausados para revisão. Exclusões antigas restauradas também ficam pausadas.',
        reply_markup=Markup([[Button('💾 Baixar cópia anterior',callback_data=f'cfg:restore:download:{download}')],
                             [Button('◀ Painel',callback_data='cfg:page:1')]]))
    return True


async def start_restore_command(update,context):
    from modules.access import require_management_access
    if not await require_management_access(update):return
    if update.effective_chat.type!='private':
        await update.effective_message.reply_text('Faça a restauração na conversa privada com o bot.');return
    message=update.effective_message
    document=getattr(message,'document',None) or getattr(getattr(message,'reply_to_message',None),'document',None)
    context.user_data['_restore_upload_until']=time.time()+600
    context.user_data['_restore_legacy']=True
    if document:
        await handle_restore_document(update,context,document)
    else:
        await message.reply_text('Envie o ZIP do backup ou responda ao arquivo JSON/DB antigo com /restaurar. O arquivo será validado e terá prévia antes de qualquer substituição.')


async def handle_restore_document(update,context,document=None):
    until=context.user_data.get('_restore_upload_until',0)
    if not until:return False
    if until<time.time():
        context.user_data.pop('_restore_upload_until',None)
        await update.effective_message.reply_text('O recebimento do backup expirou. Abra Restaurar backup novamente.');return True
    from modules.access import require_management_access
    if not await require_management_access(update):return True
    if update.effective_chat.type!='private':return True
    document=document or update.effective_message.document
    extension=Path(document.file_name or '').suffix.lower()
    extensions=('.zip','.json','.db') if context.user_data.get('_restore_legacy') else ('.zip',)
    if extension not in extensions or type(document.file_size) is not int or not 0<document.file_size<=MAX_UPLOAD:
        await update.effective_message.reply_text('Envie um ZIP de backup do bot com até 20 MB.');return True
    service=service_for(context);service.prune()
    # Um arquivo em revisão por pessoa, sem acumular uploads anteriores.
    for token,old in list(service.records.items()):
        if old['user_id']==update.effective_user.id:
            service.discard_folder(old['backup'].folder);service.records.pop(token,None)
    folder=service.base/'.restore-staging'/uuid4().hex
    folder.mkdir(parents=True)
    upload=folder/'upload.zip'
    try:
        remote=await context.bot.get_file(document.file_id)
        await remote.download_to_drive(custom_path=upload)
        if upload.stat().st_size>MAX_UPLOAD:raise InvalidBackup('Arquivo acima do limite.')
        if extension in ('.json','.db'):
            wrapped=folder/'legacy.zip'
            with zipfile.ZipFile(wrapped,'x',zipfile.ZIP_DEFLATED) as archive:
                if extension=='.json':archive.write(upload,'config.json')
                else:
                    archive.write(upload,'acervo_partituras.db')
                    archive.writestr('config.json',json.dumps(config.load_config(),ensure_ascii=False))
            upload=wrapped
        backup=validate_archive(upload,folder)
    except Exception:
        service.discard_folder(folder)
        await update.effective_message.reply_text('Arquivo recusado: confira se é um backup ZIP válido do bot, com configuração JSON e bancos compatíveis. Nenhum dado foi alterado.');return True
    context.user_data.pop('_restore_upload_until',None)
    context.user_data.pop('_restore_legacy',None)
    token=uuid4().hex[:20]
    names=[name for name in DATA_FILES if name in backup.paths]
    text=('🔎 <b>PRÉVIA DA RESTAURAÇÃO</b>\n\n'
          'Arquivos do backup: '+', '.join(names)+f'\nPartituras: {backup.scores}\nExclusões registradas: {backup.deletions}\n'
          f'Grupos/canais: {len(backup.configuration.get("linked_groups",[]))+len(backup.configuration.get("linked_channels",[]))}\n'
          f'Programações: {len(backup.configuration.get("scheduled_transmissions",[]))}\n\n'
          'Os arquivos presentes substituirão os dados atuais. O espelho de configuração será recriado. '
          'Antes disso, será guardado um backup do estado atual.\n\n'
          'Token e ambiente atuais serão mantidos. IDs administrativos explícitos atuais e seu ID continuarão autorizados; IDs do backup não serão ativados. '
          'Canais atuais de backup e logs serão mantidos. Recorrências, transmissões antigas, YouTube, backups automáticos e exclusões do backup ficarão pausados para revisão.\n\n'
          'Confirmação válida por 5 minutos.')
    message=await update.effective_message.reply_text(text,parse_mode=ParseMode.HTML,reply_markup=Markup([
        [Button('✅ Confirmar restauração',callback_data=f'cfg:restore:apply:{token}')],
        [Button('Cancelar',callback_data=f'cfg:restore:cancel:{token}')]]))
    service.records[token]=dict(backup=backup,user_id=update.effective_user.id,chat_id=update.effective_chat.id,
                               message_id=message.message_id,expires=time.time()+300)
    return True
