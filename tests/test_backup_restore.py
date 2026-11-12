"""Backups locais, validação, reversão e autorização; sem rede real."""
import asyncio
import copy
import importlib.util
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import stat
import sys
import time
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock,patch
from uuid import uuid4
import warnings
import zipfile

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
import config
_IMPORT_STATE=ROOT/'tests'/('runtime-'+uuid4().hex)
_IMPORT_STATE.mkdir()
_ORIGINAL_BASE=config.BASE_DIR;_ORIGINAL_CONFIG=config.CONFIG_PATH
config.BASE_DIR=_IMPORT_STATE;config.CONFIG_PATH=_IMPORT_STATE/'config.json'
from modules import backup_restore as restore,restore_files
from modules.acervo_database import AcervoDatabase
from modules.scheduled_deletions import DeletionStore
from modules.scheduler import TaskScheduler
config.BASE_DIR=_ORIGINAL_BASE;config.CONFIG_PATH=_ORIGINAL_CONFIG


def tearDownModule():
    assert _IMPORT_STATE.resolve().parent==(ROOT/'tests').resolve()
    shutil.rmtree(_IMPORT_STATE)


class RestoreTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.base=ROOT/'tests'/('runtime-'+uuid4().hex);self.base.mkdir()
        self.patches=[patch.object(config,'BASE_DIR',self.base),patch.object(config,'CONFIG_PATH',self.base/'config.json')]
        for item in self.patches:item.start()
        self.current=copy.deepcopy(config.DEFAULT_CONFIG)
        self.current.update(telegram_bot_token='fixture-current',panel_admin_ids=[42,43],
                            log_channel_id=-100400,recurring_messages=[],scheduled_transmissions=[],fixture='current')
        config.save_config(self.current);self.current=config.load_config()
        AcervoDatabase(self.base/'acervo_partituras.db').add_item('current',-100123,1,title='Current')
        DeletionStore(self.base/'agendamentos.db').schedule(-100123,1,3600)
        (self.base/'.env').write_text('FIXTURE_ONLY=unchanged',encoding='utf-8')
        self.bot=SimpleNamespace(get_file=AsyncMock(),send_document=AsyncMock())
        self.app=SimpleNamespace(bot=self.bot,bot_data={},job_queue=None)
        self.context=SimpleNamespace(application=self.app,user_data={},bot=self.bot)
        self.scheduler=TaskScheduler(self.app)
        self.cycles=patch.object(self.scheduler,'cycles',return_value={});self.cycles.start()
        self.app.bot_data['task_scheduler']=self.scheduler
        self.service=restore.RestorationService(self.base)
        self.app.bot_data['_restore_service']=self.service

    async def asyncTearDown(self):
        await self.scheduler.stop();self.cycles.stop()
        for item in reversed(self.patches):item.stop()
        assert self.base.resolve().parent==(ROOT/'tests').resolve()
        shutil.rmtree(self.base)

    def source_configuration(self):
        value=copy.deepcopy(config.DEFAULT_CONFIG)
        value.update(telegram_bot_token='fixture-uploaded',panel_admin_ids=[999],fixture='restored',
            log_channel_id=-100999,recurring_messages=[{'id':5,'enabled':True,'text':'Post','messages_counter_last':10}],
            scheduled_transmissions=[{'id':9,'status':'pending','text':'Do not resend'}])
        return value

    def archive(self,entries=None,include_db=True,include_queue=True):
        folder=self.base/'.restore-staging'/uuid4().hex;folder.mkdir(parents=True)
        upload=folder/'upload.zip'
        if entries is None:
            source=self.base/('source-'+uuid4().hex);source.mkdir()
            entries={'config.json':json.dumps(self.source_configuration()).encode()}
            if include_db:
                db=AcervoDatabase(source/'acervo.db');db.add_item('restored',-100555,7,title='Restored')
                entries['acervo_partituras.db']=(source/'acervo.db').read_bytes()
            if include_queue:
                queue=DeletionStore(source/'tasks.db');queue.schedule(-100555,7,3600)
                entries['agendamentos.db']=(source/'tasks.db').read_bytes()
        with zipfile.ZipFile(upload,'w',zipfile.ZIP_DEFLATED) as archive:
            for name,content in entries.items():archive.writestr(name,content)
        return upload,folder

    def validated(self,**kwargs):
        upload,folder=self.archive(**kwargs)
        return restore.validate_archive(upload,folder)

    def update(self,data='',user=42,message_id=33,chat_type='private',document=None):
        message=SimpleNamespace(message_id=message_id,caption='',document=document,
            reply_text=AsyncMock(return_value=SimpleNamespace(message_id=message_id)),reply_to_message=None)
        query=SimpleNamespace(data=data,message=message,answer=AsyncMock(),edit_message_text=AsyncMock())
        return SimpleNamespace(callback_query=query,effective_message=message,
            effective_user=SimpleNamespace(id=user),effective_chat=SimpleNamespace(id=42,type=chat_type,title=None))

    def record(self,backup):
        return dict(backup=backup,user_id=42,chat_id=42,message_id=33,expires=time.time()+300)

    def current_hashes(self):
        result={}
        for name in restore_files.DATA_FILES:
            path=self.base/name
            if path.suffix=='.db':
                connection=sqlite3.connect(path)
                try:
                    self.assertEqual(connection.execute('PRAGMA quick_check').fetchall(),[('ok',)])
                    result[name]=hashlib.sha256('\n'.join(connection.iterdump()).encode()).hexdigest()
                finally:connection.close()
            else:result[name]=restore_files.sha(path)
        return result

    async def test_generated_schema_and_archive_are_validated(self):
        backup=self.validated()
        self.assertEqual(backup.scores,1);self.assertEqual(backup.deletions,1)
        self.assertEqual(backup.configuration['fixture'],'restored')

    async def test_traversal_and_environment_files_are_rejected(self):
        for name in ('../config.json','.env','folder/config.json','config.py'):
            upload,folder=self.archive({name:b'no'})
            with self.assertRaises(restore.InvalidBackup):restore.validate_archive(upload,folder)
        self.assertEqual((self.base/'.env').read_text(encoding='utf-8'),'FIXTURE_ONLY=unchanged')

    async def test_duplicate_zip_entries_are_rejected(self):
        upload,folder=self.archive({'config.json':json.dumps(self.source_configuration())})
        with warnings.catch_warnings():
            warnings.simplefilter('ignore')
            with zipfile.ZipFile(upload,'a') as archive:archive.writestr('config.json','{}')
        with self.assertRaises(restore.InvalidBackup):restore.validate_archive(upload,folder)

    async def test_symbolic_link_entry_is_rejected(self):
        upload,folder=self.archive({})
        with zipfile.ZipFile(upload,'w') as archive:
            info=zipfile.ZipInfo('config.json');info.create_system=3;info.external_attr=(stat.S_IFLNK|0o777)<<16
            archive.writestr(info,'/elsewhere')
        with self.assertRaises(restore.InvalidBackup):restore.validate_archive(upload,folder)

    async def test_empty_invalid_and_duplicate_key_json_are_rejected(self):
        for content in ('{}','[]','{bad','{"timezone":"UTC","timezone":"UTC"}'):
            upload,folder=self.archive({'config.json':content})
            with self.assertRaises(restore.InvalidBackup):restore.validate_archive(upload,folder)

    async def test_json_with_wrong_list_structure_is_rejected(self):
        value=self.source_configuration();value['recurring_messages']={'bad':True}
        upload,folder=self.archive({'config.json':json.dumps(value)})
        with self.assertRaises(restore.InvalidBackup):restore.validate_archive(upload,folder)

    async def test_wrong_nested_types_and_non_finite_numbers_are_rejected(self):
        value=self.source_configuration();value['antispam']['enabled']='wrong'
        upload,folder=self.archive({'config.json':json.dumps(value)})
        with self.assertRaises(restore.InvalidBackup):restore.validate_archive(upload,folder)
        content=json.dumps(self.source_configuration())[:-1]+',"extra":1e9999}'
        upload,folder=self.archive({'config.json':content})
        with self.assertRaises(restore.InvalidBackup):restore.validate_archive(upload,folder)

    async def test_truncated_database_is_rejected(self):
        upload,folder=self.archive({'config.json':json.dumps(self.source_configuration()),'acervo_partituras.db':b'broken'})
        with self.assertRaises(restore.InvalidBackup):restore.validate_archive(upload,folder)

    async def test_database_with_trigger_is_rejected(self):
        source=self.base/'trigger.db';AcervoDatabase(source)
        db=sqlite3.connect(source)
        db.execute('CREATE TRIGGER unwanted BEFORE DELETE ON acervo BEGIN SELECT 1; END');db.close()
        upload,folder=self.archive({'config.json':json.dumps(self.source_configuration()),'acervo_partituras.db':source.read_bytes()})
        with self.assertRaises(restore.InvalidBackup):restore.validate_archive(upload,folder)

    async def test_wrong_database_schema_is_rejected(self):
        source=self.base/'wrong.db';db=sqlite3.connect(source);db.execute('CREATE TABLE acervo(id INTEGER)');db.close()
        upload,folder=self.archive({'config.json':json.dumps(self.source_configuration()),'acervo_partituras.db':source.read_bytes()})
        with self.assertRaises(restore.InvalidBackup):restore.validate_archive(upload,folder)

    async def test_expanded_size_limit_is_enforced(self):
        upload,folder=self.archive({'config.json':json.dumps(self.source_configuration())})
        with patch.object(restore,'MAX_EXPANDED',10):
            with self.assertRaises(restore.InvalidBackup):restore.validate_archive(upload,folder)

    async def test_preview_validation_does_not_touch_current_data(self):
        before=self.current_hashes();self.validated()
        self.assertEqual(self.current_hashes(),before)

    async def test_restore_creates_previous_backup_preserves_credentials_and_pauses_old_tasks(self):
        backup=self.validated();old=self.current_hashes();stale=config.load_config()
        await self.scheduler.start()
        safety=await self.service.apply(self.app,self.record(backup))
        self.assertTrue(self.scheduler.started)
        cfg=config.load_config()
        self.assertEqual(cfg['fixture'],'restored')
        self.assertEqual(cfg['telegram_bot_token'],'fixture-current')
        self.assertEqual(cfg['panel_admin_ids'],[42,43])
        self.assertEqual(cfg['log_channel_id'],-100400)
        self.assertFalse(cfg['recurring_messages'][0]['enabled'])
        self.assertEqual(cfg['scheduled_transmissions'][0]['status'],'interrupted')
        self.assertFalse(cfg['youtube_notifications']['enabled'])
        self.assertFalse(cfg['backup_system']['daily_backup_enabled'])
        self.assertTrue(cfg['backup_system']['enabled'])  # Pode voltar a ser ativado pelos controles do painel.
        self.assertEqual(DeletionStore(self.base/'agendamentos.db').counts(),{'paused':1})
        self.assertEqual(AcervoDatabase(self.base/'acervo_partituras.db').search('Restored')[0]['file_id'],'restored')
        self.assertEqual((self.base/'.env').read_text(encoding='utf-8'),'FIXTURE_ONLY=unchanged')
        self.assertFalse(config.save_config(stale))
        with zipfile.ZipFile(safety) as archive:
            self.assertIsNone(archive.testzip())
            self.assertEqual(json.loads(archive.read('config.json'))['fixture'],'current')
        self.assertFalse((self.base/restore_files.JOURNAL).exists())

    async def test_configuration_only_backup_does_not_replace_databases(self):
        backup=self.validated(include_db=False,include_queue=False)
        hashes={name:restore_files.sha(self.base/name) for name in ('acervo_partituras.db','agendamentos.db')}
        await self.service.apply(self.app,self.record(backup))
        self.assertEqual({name:restore_files.sha(self.base/name) for name in hashes},hashes)

    async def test_failure_to_create_previous_backup_keeps_current_state(self):
        backup=self.validated();before=self.current_hashes()
        with patch.object(restore,'create_safety_backup',side_effect=OSError('simulated')):
            with self.assertRaises(OSError):await self.service.apply(self.app,self.record(backup))
        self.assertEqual(self.current_hashes(),before)

    async def test_partial_replacement_failure_rolls_back_all_files(self):
        backup=self.validated();before=self.current_hashes()
        original=restore_files.os.replace;failed=False
        def replace(source,target):
            nonlocal failed
            if Path(target)==self.base/'config.json' and not failed:
                failed=True;raise OSError('simulated replacement failure')
            return original(source,target)
        with patch.object(restore_files.os,'replace',side_effect=replace):
            with self.assertRaises(OSError):await self.service.apply(self.app,self.record(backup))
        self.assertEqual(self.current_hashes(),before)
        self.assertFalse((self.base/restore_files.JOURNAL).exists())

    async def test_changed_staging_file_cannot_be_restored(self):
        backup=self.validated();before=self.current_hashes()
        backup.paths['config.json'].write_text('{}',encoding='utf-8')
        with self.assertRaises(restore.InvalidBackup):await self.service.apply(self.app,self.record(backup))
        self.assertEqual(self.current_hashes(),before)

    async def test_process_interruption_is_recovered_from_journal(self):
        before=self.current_hashes();new=self.base/'new.json';new.write_text('{"fixture":"changed"}',encoding='utf-8')
        original=restore_files.os.replace
        class SimulatedCrash(BaseException):pass
        def replace(source,target):
            if Path(target)==self.base/'.config_backup.json':raise SimulatedCrash()
            return original(source,target)
        with patch.object(restore_files.os,'replace',side_effect=replace):
            with self.assertRaises(SimulatedCrash):restore_files.apply_transaction(self.base,{'config.json':new,'.config_backup.json':new})
        self.assertTrue((self.base/restore_files.JOURNAL).exists())
        self.assertTrue(restore_files.recover_interrupted_restore(self.base))
        self.assertEqual(self.current_hashes(),before)

    async def test_recovery_rejects_paths_outside_transaction_directory(self):
        (self.base/restore_files.JOURNAL).write_text(json.dumps({'id':'../elsewhere','files':[]}),encoding='utf-8')
        before=(self.base/'config.json').read_bytes()
        with self.assertRaises(RuntimeError):restore_files.recover_interrupted_restore(self.base)
        self.assertEqual((self.base/'config.json').read_bytes(),before)

    async def test_upload_is_validated_and_confirmation_is_bound_to_owner(self):
        upload,folder=self.archive();content=upload.read_bytes()
        document=SimpleNamespace(file_name='backup.zip',file_size=len(content),file_id='fixture')
        async def download(custom_path):Path(custom_path).write_bytes(content)
        self.bot.get_file.return_value=SimpleNamespace(download_to_drive=AsyncMock(side_effect=download))
        self.context.user_data['_restore_upload_until']=time.time()+600
        update=self.update(document=document)
        with patch('modules.access.require_management_access',new=AsyncMock(return_value=True)):
            self.assertTrue(await restore.handle_restore_document(update,self.context))
            self.assertEqual(config.load_config()['fixture'],'current')
            token=next(iter(self.service.records))
            with patch.object(self.service,'apply',new=AsyncMock()) as apply:
                await restore.handle_restore_callback(self.update('cfg:restore:apply:'+token,user=99),self.context)
                apply.assert_not_awaited()

    async def test_cancel_discards_staging_without_changing_current_data(self):
        backup=self.validated();self.service.records['fixture']=self.record(backup);before=self.current_hashes()
        with patch('modules.access.require_management_access',new=AsyncMock(return_value=True)):
            await restore.handle_restore_callback(self.update('cfg:restore:cancel:fixture'),self.context)
        self.assertEqual(self.current_hashes(),before)
        self.assertFalse(backup.folder.exists())

    async def test_expired_confirmation_does_not_apply(self):
        backup=self.validated();record=self.record(backup);record['expires']=0;self.service.records['fixture']=record
        with patch('modules.access.require_management_access',new=AsyncMock(return_value=True)),patch.object(self.service,'apply',new=AsyncMock()) as apply:
            await restore.handle_restore_callback(self.update('cfg:restore:apply:fixture'),self.context)
        apply.assert_not_awaited();self.assertFalse(backup.folder.exists())

    async def test_revoked_permission_blocks_apply(self):
        backup=self.validated();self.service.records['fixture']=self.record(backup)
        with patch('modules.access.require_management_access',new=AsyncMock(return_value=False)),patch.object(self.service,'apply',new=AsyncMock()) as apply:
            await restore.handle_restore_callback(self.update('cfg:restore:apply:fixture'),self.context)
        apply.assert_not_awaited()

    async def test_restore_cannot_be_started_in_group(self):
        with patch('modules.access.require_management_access',new=AsyncMock(return_value=True)):
            update=self.update('cfg:restore:start',chat_type='supergroup')
            await restore.handle_restore_callback(update,self.context)
        self.assertNotIn('_restore_upload_until',self.context.user_data)

    async def test_legacy_json_command_opens_review_without_writing(self):
        content=json.dumps(self.source_configuration()).encode()
        document=SimpleNamespace(file_name='config.json',file_size=len(content),file_id='legacy')
        async def download(custom_path):Path(custom_path).write_bytes(content)
        self.bot.get_file.return_value=SimpleNamespace(download_to_drive=AsyncMock(side_effect=download))
        update=self.update(document=document)
        with patch('modules.access.require_management_access',new=AsyncMock(return_value=True)):
            await restore.start_restore_command(update,self.context)
        self.assertEqual(len(self.service.records),1)
        self.assertEqual(config.load_config()['fixture'],'current')

    async def test_legacy_database_gets_same_validation_and_preview(self):
        source=self.base/'legacy.db';AcervoDatabase(source).add_item('legacy',-100555,9,title='Legacy')
        content=source.read_bytes();document=SimpleNamespace(file_name='acervo.db',file_size=len(content),file_id='legacy')
        async def download(custom_path):Path(custom_path).write_bytes(content)
        self.bot.get_file.return_value=SimpleNamespace(download_to_drive=AsyncMock(side_effect=download))
        with patch('modules.access.require_management_access',new=AsyncMock(return_value=True)):
            await restore.start_restore_command(self.update(document=document),self.context)
        record=next(iter(self.service.records.values()))
        self.assertEqual(record['backup'].scores,1)
        self.assertEqual(AcervoDatabase(self.base/'acervo_partituras.db').search('Current')[0]['file_id'],'current')

    async def test_normal_acervo_upload_does_not_enter_restore_without_request(self):
        document=SimpleNamespace(file_name='result.json',file_size=10,file_id='normal')
        self.assertFalse(await restore.handle_restore_document(self.update(document=document),self.context))
        self.bot.get_file.assert_not_awaited()

    async def test_restore_confirmation_is_one_use_and_download_is_owner_only(self):
        backup=self.validated();self.service.records['fixture']=self.record(backup)
        destination=self.base/'backups'/'fixture.zip';destination.parent.mkdir();destination.write_bytes(b'fixture')
        with patch('modules.access.require_management_access',new=AsyncMock(return_value=True)), \
             patch.object(self.service,'apply',new=AsyncMock(return_value=destination)) as apply:
            await restore.handle_restore_callback(self.update('cfg:restore:apply:fixture'),self.context)
            await restore.handle_restore_callback(self.update('cfg:restore:apply:fixture'),self.context)
            apply.assert_awaited_once()
            token=next(iter(self.service.downloads))
            await restore.handle_restore_callback(self.update('cfg:restore:download:'+token,user=99),self.context)
            self.bot.send_document.assert_not_awaited()

    async def test_unrecoverable_runtime_rollback_keeps_bot_blocked_and_scheduler_stopped(self):
        backup=self.validated();await self.scheduler.start();original=restore_files.os.replace
        def replace(source,target):
            if Path(target)==self.base/'config.json':raise OSError('persistent simulated failure')
            return original(source,target)
        with patch.object(restore_files.os,'replace',side_effect=replace):
            with self.assertRaises(OSError):await self.service.apply(self.app,self.record(backup))
        self.assertTrue(self.app.bot_data['_restore_blocked'])
        self.assertFalse(self.scheduler.started)
        self.assertTrue((self.base/restore_files.JOURNAL).exists())

    async def test_pending_scans_and_delayed_responses_stop_before_restore(self):
        gate=asyncio.Event()
        tasks=[asyncio.create_task(gate.wait()),asyncio.create_task(gate.wait())]
        self.app.bot_data['_acervo_scan_tasks']={tasks[0]};self.app.bot_data['_delayed_response_tasks']={tasks[1]}
        await self.service.apply(self.app,self.record(self.validated()))
        self.assertTrue(all(task.cancelled() for task in tasks))

    async def test_recovery_runs_when_config_module_is_imported(self):
        before=(self.base/'config.json').read_bytes()
        new=self.base/'new.json';new.write_text('{"fixture":"changed"}',encoding='utf-8')
        original=restore_files.os.replace
        class SimulatedCrash(BaseException):pass
        def replace(source,target):
            if Path(target)==self.base/'.config_backup.json':raise SimulatedCrash()
            return original(source,target)
        with patch.object(restore_files.os,'replace',side_effect=replace):
            with self.assertRaises(SimulatedCrash):restore_files.apply_transaction(self.base,{'config.json':new,'.config_backup.json':new})
        boot=self.base/'boot_config.py';boot.write_bytes((ROOT/'config.py').read_bytes())
        spec=importlib.util.spec_from_file_location('restore_boot_fixture',boot)
        module=importlib.util.module_from_spec(spec)
        with patch.dict(os.environ,dict(os.environ)):
            spec.loader.exec_module(module)
        self.assertFalse((self.base/restore_files.JOURNAL).exists())
        self.assertEqual((self.base/'config.json').read_bytes(),before)

    async def test_restore_keeps_explicit_administrators_and_adds_operator(self):
        current=copy.deepcopy(self.current);current['panel_admin_ids']=[43]
        value=restore.normalized_restoration(self.source_configuration(),current,42)
        self.assertEqual(value['panel_admin_ids'],[43,42])
        self.assertNotIn(999,value['panel_admin_ids'])

    async def test_restore_explicit_json_caption_is_not_imported_as_acervo(self):
        from modules import inline_acervo
        from telegram.ext import ApplicationHandlerStop
        update=self.update();update.effective_message.caption='/restaurar'
        with patch.object(restore,'start_restore_command',new=AsyncMock()) as command, \
             patch.object(inline_acervo,'import_universal_json') as import_json:
            with self.assertRaises(ApplicationHandlerStop):await inline_acervo.handle_private_document(update,self.context)
        command.assert_awaited_once();import_json.assert_not_called()


if __name__=='__main__':unittest.main()
