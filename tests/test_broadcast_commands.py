"""Prévia, mídia, comandos e histórico único sem usar a rede."""
import asyncio
import copy
import io
from datetime import datetime,timezone
from pathlib import Path
import shutil
import sys
import time
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock,patch
from uuid import uuid4

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
import config
from modules.admin_commands import AdminCommandHandler
from modules.panel import InteractivePanelHandler
from modules.scheduler import TaskScheduler
from modules.scheduled_deletions import DeletionStore
from modules import broadcast_drafts as drafts,broadcast_commands as commands
from modules import broadcast_content,transmission_delivery as delivery


class BroadcastCommandTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.base=ROOT/'tests'/('runtime-'+uuid4().hex);self.base.mkdir()
        self.patches=[patch.object(config,'BASE_DIR',self.base),patch.object(config,'CONFIG_PATH',self.base/'config.json'),
                      patch('modules.access.require_management_access',new=AsyncMock(return_value=True)),
                      patch.object(commands,'require_management_access',new=AsyncMock(return_value=True))]
        for item in self.patches:item.start()
        cfg=copy.deepcopy(config.DEFAULT_CONFIG)
        cfg.update(panel_admin_ids=[42],main_channel_id=-100111,main_group_id=-100222,
                   linked_channels=[{'id':-100111,'title':'Canal A','username':'@canala'}],
                   linked_groups=[{'id':-100222,'title':'Grupo B'}],scheduled_transmissions=[])
        config.save_config(cfg)
        self.sent=SimpleNamespace(message_id=101,pin=AsyncMock())
        self.bot=SimpleNamespace(**{name:AsyncMock(return_value=self.sent) for name in
            ('send_message','send_photo','send_video','send_document','send_audio','send_voice','copy_message','pin_chat_message')})
        self.bot.get_chat=AsyncMock()
        self.app=SimpleNamespace(bot=self.bot,bot_data={},job_queue=None)
        self.context=SimpleNamespace(bot=self.bot,application=self.app,user_data={},args=[])
        self.scheduler=TaskScheduler(self.app,DeletionStore(self.base/'tasks.db'))
        self.cycles=patch.object(self.scheduler,'cycles',return_value={});self.cycles.start()
        await self.scheduler.start()
        self.handler=AdminCommandHandler(None)

    async def asyncTearDown(self):
        await self.scheduler.stop();self.cycles.stop()
        for item in reversed(self.patches):item.stop()
        assert self.base.resolve().parent==(ROOT/'tests').resolve();shutil.rmtree(self.base)

    def update(self,text='/falar Olá',data='',user=42,message_id=33,private=True):
        message=SimpleNamespace(message_id=message_id,text=text,text_html=text,caption=None,caption_html=None,
            photo=None,document=None,audio=None,voice=None,video=None,reply_to_message=None,message_thread_id=None,
            reply_text=AsyncMock(return_value=SimpleNamespace(message_id=message_id,edit_text=AsyncMock())))
        query=SimpleNamespace(data=data,message=message,answer=AsyncMock(),edit_message_text=AsyncMock(),edit_message_reply_markup=AsyncMock())
        return SimpleNamespace(effective_message=message,effective_user=SimpleNamespace(id=user),
            effective_chat=SimpleNamespace(id=42 if private else -100222,type='private' if private else 'supergroup',title=None if private else 'Grupo B'),
            callback_query=query)

    def latest(self):return config.load_config()['scheduled_transmissions'][-1]

    async def confirm(self,item,update=None):
        update=update or self.update(data=f'cfg:draft:{item["id"]}:confirm:1')
        await drafts.handle_draft_callback(update,self.context)
        await asyncio.gather(*list(self.scheduler.transmissions.values()))
        await asyncio.sleep(0)

    async def test_falar_explicit_target_has_no_send_before_confirmation(self):
        await self.handler.cmd_say(self.update('/falar -100111 Olá'),self.context)
        item=self.latest();self.assertEqual(item['status'],'draft')
        self.bot.send_message.assert_not_awaited()
        await self.confirm(item)
        result=self.latest()
        self.assertEqual(result['source'],'falar');self.assertEqual(result['delivery_results'][0]['status'],'sent')
        self.assertEqual(result['destination_snapshot'],[{'chat_id':-100111,'title':'Canal A'}])

    async def test_falar_selector_leads_to_preview_not_delivery(self):
        await self.handler.cmd_say(self.update('/falar Olá'),self.context)
        self.assertIn('_post_selection',self.context.user_data)
        await self.handler.handle_falar_callback(self.update(data='falar:send:all_channels'),self.context)
        self.assertEqual(self.latest()['status'],'draft')
        self.bot.send_message.assert_not_awaited()

    async def test_selector_rejects_other_message_and_unlinked_target(self):
        await self.handler.cmd_say(self.update('/falar Olá'),self.context)
        await self.handler.handle_falar_callback(self.update(data='falar:send:chn:-999',message_id=99),self.context)
        self.assertEqual(config.load_config()['scheduled_transmissions'],[])
        await self.handler.handle_falar_callback(self.update(data='falar:send:chn:-999'),self.context)
        self.assertEqual(config.load_config()['scheduled_transmissions'],[])

    async def test_falar_group_retains_topic_in_preview_and_delivery(self):
        update=self.update('/falar Olá',private=False);update.effective_message.message_thread_id=17
        await self.handler.cmd_say(update,self.context)
        item=self.latest();self.assertEqual(item['message_thread_id'],17)
        await self.confirm(item,self.update(data=f'cfg:draft:{item["id"]}:confirm:1',private=False))
        call=next(x for x in self.bot.send_message.await_args_list if x.kwargs.get('chat_id')==-100222)
        self.assertEqual(call.kwargs['message_thread_id'],17)

    async def test_pdf_audio_voice_and_video_keep_media_and_history(self):
        for kind in ('document','audio','voice','video','photo'):
            with self.subTest(kind=kind):
                update=self.update('/falar -100111 Texto')
                setattr(update.effective_message,kind,[SimpleNamespace(file_id='fixture')] if kind=='photo' else SimpleNamespace(file_id='fixture'))
                await self.handler.cmd_say(update,self.context)
                item=self.latest();self.assertEqual(item['media_type'],kind)
                await self.confirm(item)
                self.assertEqual(self.latest()['delivery_results'][0]['message_ids'],[101])
                self.assertTrue(getattr(self.bot,'send_'+kind).await_count)

    async def test_anunciar_keeps_official_header_and_pin(self):
        await self.handler.cmd_anunciar(self.update('/anunciar canal Aviso'),self.context)
        item=self.latest();self.assertTrue(item['pin']);self.assertIn('[COMUNICADO OFICIAL]',item['text'])
        self.bot.send_message.assert_not_awaited()
        await self.confirm(item)
        self.sent.pin.assert_awaited_once()
        self.assertEqual(self.latest()['source'],'anunciar')

    async def test_canal_explicit_channel_and_pin_use_same_history(self):
        await self.handler.cmd_canal(self.update('/canal @canala pin Aviso'),self.context)
        item=self.latest();self.assertEqual(item['destination_snapshot'][0]['chat_id'],-100111)
        self.assertTrue(item['pin'])
        await self.confirm(item)
        self.assertEqual(self.latest()['source'],'canal')

    async def test_canal_reply_copies_original_post_and_records_message_id(self):
        update=self.update('/canal')
        update.effective_message.reply_to_message=SimpleNamespace(photo=None,document=SimpleNamespace(file_id='pdf'),
            audio=None,voice=None,video=None,text_html=None,text=None,caption_html='Legenda',caption='Legenda',
            chat=SimpleNamespace(id=42),message_id=10)
        await self.handler.cmd_canal(update,self.context)
        item=self.latest();self.assertEqual(item['copy_source'],{'chat_id':42,'message_id':10})
        await self.confirm(item)
        self.bot.copy_message.assert_awaited_once()
        self.assertEqual(self.latest()['delivery_results'][0]['message_ids'],[101])

    async def test_scheduled_wizard_stays_draft_until_confirmed(self):
        handler=InteractivePanelHandler(None)
        state={'text':'Agendada','target':'chn:-100111','buttons':[]}
        when=datetime(2099,1,1,tzinfo=timezone.utc)
        await handler.save_scheduled_transmission(self.update(),self.context,state,42,when)
        item=self.latest();self.assertEqual(item['status'],'draft')
        await self.confirm(item)
        self.assertEqual(self.latest()['status'],'pending')
        self.bot.send_message.assert_not_awaited()

    async def test_schedule_that_expired_during_preview_is_not_sent_immediately(self):
        draft=drafts.create_draft(self.update(),{'text':'Horário passado'},[-100111],schedule_timestamp=time.time()-1,schedule_display='Horário escolhido')
        await drafts.show_preview(self.update(),self.context,draft)
        await self.confirm(draft)
        self.assertEqual(self.latest()['status'],'draft');self.bot.send_message.assert_not_awaited()

    async def test_preview_shows_readable_text_instead_of_html_markup(self):
        item=drafts.create_draft(self.update(),{'text':'<b>Aviso</b> &amp; teste'},[-100111])
        text,_=drafts.render_preview(item)
        self.assertIn('Aviso &amp; teste',text)
        self.assertNotIn('&lt;b&gt;',text)

    async def test_double_confirmation_cannot_send_twice(self):
        await self.handler.cmd_say(self.update('/falar -100111 Olá'),self.context)
        item=self.latest()
        await self.confirm(item);count=self.bot.send_message.await_count
        await self.confirm(item)
        self.assertEqual(self.bot.send_message.await_count,count)

    async def test_other_user_or_message_cannot_confirm(self):
        await self.handler.cmd_say(self.update('/falar -100111 Olá'),self.context);item=self.latest()
        for user,message in ((99,33),(42,999)):
            await self.confirm(item,self.update(data=f'cfg:draft:{item["id"]}:confirm:1',user=user,message_id=message))
        self.assertEqual(self.latest()['status'],'draft');self.bot.send_message.assert_not_awaited()

    async def test_cancelled_and_expired_drafts_never_send(self):
        await self.handler.cmd_say(self.update('/falar -100111 Olá'),self.context);item=self.latest()
        await drafts.handle_draft_callback(self.update(data=f'cfg:draft:{item["id"]}:cancel:1'),self.context)
        self.assertEqual(self.latest()['status'],'cancelled')
        await self.handler.cmd_say(self.update('/falar -100111 Olá'),self.context);item=self.latest()
        cfg=config.load_config();cfg['scheduled_transmissions'][-1]['draft_expires_at']=0;config.save_config(cfg)
        await self.confirm(item)
        self.assertEqual(self.latest()['status'],'expired');self.bot.send_message.assert_not_awaited()

    async def test_changed_payload_requires_new_preview(self):
        await self.handler.cmd_say(self.update('/falar -100111 Olá'),self.context);item=self.latest()
        cfg=config.load_config();cfg['scheduled_transmissions'][-1]['text']='Alterado';config.save_config(cfg)
        await self.confirm(item)
        self.assertEqual(self.latest()['status'],'draft');self.bot.send_message.assert_not_awaited()

    async def test_removed_target_requires_new_authorization(self):
        await self.handler.cmd_say(self.update('/falar -100111 Olá'),self.context);item=self.latest()
        cfg=config.load_config();cfg['linked_channels']=[];cfg['main_channel_id']=None;config.save_config(cfg)
        self.bot.get_chat.side_effect=RuntimeError('cannot verify')
        await self.confirm(item)
        self.assertEqual(self.latest()['status'],'draft');self.bot.send_message.assert_not_awaited()

    async def test_all_text_and_targets_are_available_in_preview_pages(self):
        long_text='P'*4500+'FIM'
        targets=list(range(-100500,-100520,-1))
        item=drafts.create_draft(self.update(),{'text':long_text},targets)
        text,_=drafts.render_preview(item,'text',3);self.assertIn('FIM',text)
        text,keyboard=drafts.render_preview(item,'targets',3);self.assertIn('-100519',text)
        for row in keyboard.inline_keyboard:
            for button in row:self.assertLessEqual(len(button.callback_data.encode()),64)

    async def test_sample_only_posts_in_origin_chat_without_queueing_destinations(self):
        await self.handler.cmd_say(self.update('/falar -100111 Olá'),self.context);item=self.latest()
        await drafts.handle_draft_callback(self.update(data=f'cfg:draft:{item["id"]}:sample:1'),self.context)
        self.assertEqual(self.latest()['status'],'draft')
        self.assertEqual([call.kwargs['chat_id'] for call in self.bot.send_message.await_args_list],[42])

    async def test_group_preview_sample_is_sent_privately_not_to_the_destination_group(self):
        await self.handler.cmd_say(self.update('/falar Texto',private=False),self.context)
        item=self.latest()
        await drafts.handle_draft_callback(self.update(data=f'cfg:draft:{item["id"]}:sample:1',private=False),self.context)
        self.assertEqual([call.kwargs['chat_id'] for call in self.bot.send_message.await_args_list],[42])
        self.assertEqual(self.latest()['status'],'draft')

    async def test_restoration_blocks_draft_submission(self):
        await self.handler.cmd_say(self.update('/falar -100111 Olá'),self.context);item=self.latest()
        self.app.bot_data['_restore_active']=True
        await self.confirm(item)
        self.assertEqual(self.latest()['status'],'draft');self.bot.send_message.assert_not_awaited()

    async def test_pin_copy_response_uses_bot_pin_api(self):
        item=dict(text='Caption',copy_source={'chat_id':42,'message_id':8},pin=True,buttons=[])
        draft=drafts.create_draft(self.update(),item,[-100111]);await drafts.show_preview(self.update(),self.context,draft)
        self.bot.copy_message.return_value=SimpleNamespace(message_id=303)
        await self.confirm(draft)
        self.bot.pin_chat_message.assert_awaited_once_with(chat_id=-100111,message_id=303,disable_notification=False)

    async def test_legacy_backup_command_cannot_expose_data_to_unapproved_private_user(self):
        handler=AdminCommandHandler(SimpleNamespace(is_admin=AsyncMock(return_value=False)))
        await handler.cmd_backup(self.update('/backup',user=99),self.context)
        self.bot.send_document.assert_not_awaited()

    async def test_backup_is_exported_as_zip_only_in_authorized_private_chat(self):
        handler=AdminCommandHandler(SimpleNamespace(is_admin=AsyncMock(return_value=True)))
        with patch('modules.backup_manager.create_backup_zip',return_value=('fixture.zip',io.BytesIO(b'fixture'),7,0)) as create:
            await handler.cmd_backup(self.update('/backup'),self.context)
        create.assert_called_once()
        self.assertEqual(self.bot.send_document.await_args.kwargs['filename'],'fixture.zip')

    async def test_backup_never_posts_configuration_in_a_group(self):
        handler=AdminCommandHandler(SimpleNamespace(is_admin=AsyncMock(return_value=True)))
        with patch('modules.backup_manager.create_backup_zip') as create:
            await handler.cmd_backup(self.update('/backup',private=False),self.context)
        create.assert_not_called();self.bot.send_document.assert_not_awaited()

    async def test_caption_commands_are_routed_before_acervo_import(self):
        import main
        from telegram import Update,Message,Chat,User,Document
        from telegram.ext import Application,ApplicationHandlerStop
        captured=[]
        names=('cmd_say','cmd_anunciar','cmd_canal','cmd_restaurar')
        mocks={name:AsyncMock() for name in names}
        patches=[patch.object(AdminCommandHandler,name,new=mock) for name,mock in mocks.items()]
        for item in patches:item.start()
        try:
            with patch.object(main,'get_bot_token',return_value='123456:offline_test_only'), \
                 patch.object(main,'start_cloud_health_server'), \
                 patch.object(Application,'run_polling',autospec=True,side_effect=lambda app,**kwargs:captured.append(app)):
                main.main()
            app=captured[0];handler=app.handlers[-3][0]
            self.assertEqual(app.update_processor.max_concurrent_updates,1)
            for command,name in [('falar','cmd_say'),('anunciar','cmd_anunciar'),('canal','cmd_canal'),('restaurar','cmd_restaurar')]:
                message=Message(message_id=33,date=datetime.now(timezone.utc),chat=Chat(42,'private'),
                    from_user=User(42,'Admin',False),caption='/'+command,
                    document=Document('fixture','unique',file_name='fixture.pdf'))
                update=Update(update_id=1,message=message)
                self.assertTrue(handler.check_update(update))
                with self.assertRaises(ApplicationHandlerStop):await handler.callback(update,self.context)
                mocks[name].assert_awaited_once_with(update,self.context)
        finally:
            for item in reversed(patches):item.stop()


if __name__=='__main__':unittest.main()
