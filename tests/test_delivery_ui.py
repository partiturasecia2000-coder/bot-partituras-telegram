"""Transmissões por destino, navegação e ações destrutivas sem rede."""
import asyncio
import copy
from pathlib import Path
import shutil
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import config
from modules import scheduler, transmission_delivery as delivery, panel_lists as lists, confirmations
from modules.panel import InteractivePanelHandler
from modules.scheduled_deletions import DeletionStore
from modules.utils import smart_send_message
from telegram.error import Forbidden, NetworkError, BadRequest


class DeliveryUITests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.directory=ROOT/'tests'/('runtime-'+uuid4().hex)
        self.directory.mkdir()
        self.patches=[patch.object(config,'BASE_DIR',self.directory),patch.object(config,'CONFIG_PATH',self.directory/'config.json')]
        for item in self.patches:
            item.start()
        self.message=SimpleNamespace(message_id=101,pin=AsyncMock())
        self.bot=SimpleNamespace(send_message=AsyncMock(return_value=self.message),
            send_photo=AsyncMock(return_value=self.message),send_video=AsyncMock(return_value=self.message))
        self.context=SimpleNamespace(application=SimpleNamespace(bot_data={},bot=self.bot,job_queue=None),user_data={},bot=self.bot)
        self.service=scheduler.TaskScheduler(self.context.application,DeletionStore(self.directory/'tasks.db'))
        self.cycles=patch.object(self.service,'cycles',return_value={});self.cycles.start()
        self.base={'main_channel_id':-100111,'linked_channels':[{'id':-100111,'title':'A'},{'id':-100222,'title':'B'}],
                   'scheduled_transmissions':[],'panel_admin_ids':[42]}
        config.save_config(self.base)

    async def asyncTearDown(self):
        await self.service.stop()
        self.cycles.stop()
        for item in reversed(self.patches): item.stop()
        assert self.directory.resolve().parent==(ROOT/'tests').resolve()
        shutil.rmtree(self.directory)

    def entry(self,**fields):
        cfg=config.load_config()
        item=dict(id=7,status='pending',target='all_channels',text='Teste',buttons=[],delay_seconds=0,schedule_timestamp=0)
        item.update(fields)
        cfg['scheduled_transmissions']=[item]
        config.save_config(cfg)
        return item

    def result(self):
        return delivery.find_entry(config.load_config(),7)

    async def send(self,mode='initial'):
        if not self.service.started: await self.service.start()
        self.assertTrue(self.service.start_transmission(7,force=True,mode=mode))
        await asyncio.gather(*list(self.service.transmissions.values()))
        await asyncio.sleep(0)

    def update(self,data,user=42,message=33):
        query=SimpleNamespace(data=data,answer=AsyncMock(),edit_message_text=AsyncMock(),
            edit_message_reply_markup=AsyncMock(),message=SimpleNamespace(message_id=message))
        return SimpleNamespace(callback_query=query,effective_user=SimpleNamespace(id=user),
            effective_chat=SimpleNamespace(id=-100333,type='supergroup',title='Teste'),
            effective_message=SimpleNamespace(reply_text=AsyncMock(return_value=SimpleNamespace(message_id=message))))

    async def test_success_persists_each_destination_and_message_id(self):
        self.entry()
        await self.send()
        result=self.result()
        self.assertEqual(result['status'],'completed')
        self.assertTrue(all(row['status']=='sent' and row['message_ids']==[101] for row in result['delivery_results']))
        self.assertEqual(len(result['delivery_results']),len(self.bot.send_message.await_args_list))

    async def test_retry_sends_only_confirmed_failures(self):
        self.entry()
        async def send(**kwargs):
            if kwargs['chat_id']==-100222: raise Forbidden('sem permissão')
            return self.message
        self.bot.send_message.side_effect=send
        await self.send()
        before=self.result()['delivery_results']
        self.assertEqual(next(x for x in before if x['chat_id']==-100222)['status'],'failed')
        self.bot.send_message.reset_mock();self.bot.send_message.side_effect=None
        await self.send('failed')
        calls=[call.kwargs['chat_id'] for call in self.bot.send_message.await_args_list]
        self.assertEqual(calls,[-100222])
        after=self.result()['delivery_results']
        self.assertEqual(next(x for x in after if x['chat_id']==-100111)['attempts'],1)
        self.assertEqual(next(x for x in after if x['chat_id']==-100222)['attempts'],2)

    async def test_network_error_is_unknown_and_not_retried(self):
        self.entry(target='chn:-100111')
        self.bot.send_message.side_effect=NetworkError('timeout')
        await self.send()
        self.assertEqual(self.result()['delivery_results'][0]['status'],'unknown')
        self.bot.send_message.assert_awaited_once()
        self.assertFalse(self.service.start_transmission(7,force=True,mode='failed'))

    async def test_split_message_failure_is_partial_not_retryable(self):
        self.entry(target='chn:-100111',text='Mensagem longa. '*650)
        self.bot.send_message.side_effect=[self.message,Forbidden('bloqueado')]
        await self.send()
        row=self.result()['delivery_results'][0]
        self.assertEqual(row['status'],'unknown')
        self.assertEqual(row['message_ids'],[101])
        self.assertFalse(self.service.start_transmission(7,force=True,mode='failed'))

    async def test_long_photo_caption_preserves_confirmed_photo_on_failure(self):
        self.entry(target='chn:-100111',media_type='photo',media_id='imagem',text='Legenda '*300)
        self.bot.send_message.side_effect=NetworkError('timeout')
        await self.send()
        row=self.result()['delivery_results'][0]
        self.assertEqual(row['status'],'unknown')
        self.assertEqual(row['message_ids'],[101])
        self.bot.send_photo.assert_awaited_once()

    async def test_pinning_failure_does_not_offer_redelivery(self):
        self.entry(target='chn:-100111',pin=True)
        self.message.pin.side_effect=Forbidden('não fixa')
        await self.send()
        row=self.result()['delivery_results'][0]
        self.assertEqual(row['status'],'sent')
        self.assertTrue(row['pin_warning'])
        self.assertFalse(self.service.start_transmission(7,force=True,mode='failed'))

    async def test_restart_marks_only_inflight_unknown_and_keeps_confirmed(self):
        self.entry(status='sending',delivery_results=[
            {'chat_id':1,'status':'sent','message_ids':[1]},
            {'chat_id':2,'status':'sending','message_ids':[]},
            {'chat_id':3,'status':'queued','message_ids':[]}])
        await self.service.start()
        self.assertEqual([x['status'] for x in self.result()['delivery_results']],['sent','unknown','pending'])

    async def test_resume_skips_unknown_and_delivered(self):
        self.entry(status='interrupted',delivery_results=[
            {'chat_id':1,'status':'sent','message_ids':[1]},
            {'chat_id':2,'status':'unknown','message_ids':[]},
            {'chat_id':3,'status':'pending','message_ids':[]}])
        await self.send('pending')
        self.assertEqual([call.kwargs['chat_id'] for call in self.bot.send_message.await_args_list],[3])

    async def test_known_destinations_are_frozen_between_retries(self):
        self.entry(target='all_channels')
        self.bot.send_message.side_effect=Forbidden('não pode')
        await self.send()
        cfg=config.load_config();cfg['linked_channels'].append({'id':-100999,'title':'Novo'})
        config.save_config(cfg)
        self.bot.send_message.reset_mock();self.bot.send_message.side_effect=None
        await self.send('failed')
        self.assertNotIn(-100999,[x.kwargs['chat_id'] for x in self.bot.send_message.await_args_list])

    async def test_legacy_completed_entry_cannot_be_replayed_as_initial(self):
        self.entry(status='completed')
        await self.service.start()
        self.assertFalse(self.service.start_transmission(7,force=True))
        self.assertFalse(self.service.start_transmission(7,force=True,mode='failed'))

    async def test_formatting_fallback_does_not_retry_network_timeout(self):
        self.bot.send_message.side_effect=NetworkError('timeout')
        with self.assertRaises(NetworkError):
            await smart_send_message(self.bot,chat_id=1,text='<b>Olá</b>')
        self.bot.send_message.assert_awaited_once()

    async def test_real_format_error_still_uses_safe_fallback(self):
        self.bot.send_message.side_effect=[BadRequest("Can't parse entities"),self.message]
        result=await smart_send_message(self.bot,chat_id=1,text='<b>Olá</b>')
        self.assertIs(result,self.message)
        self.assertEqual(self.bot.send_message.await_count,2)

    async def test_immediate_wizard_uses_same_persistent_delivery_history(self):
        handler=InteractivePanelHandler(None)
        handler.wizard_states[42]={'target':'chn:-100111','text':'Olá','buttons':[],'delay_seconds':0}
        await self.service.start()
        await handler.execute_wizard_send(self.update('cfg:wiz:send'),self.context,42)
        tasks=list(self.service.transmissions.values())
        await asyncio.gather(*tasks)
        item=config.load_config()['scheduled_transmissions'][0]
        self.assertEqual(item['delivery_results'][0]['status'],'sent')
        self.assertEqual(handler.wizard_states,{})

    async def test_destructive_panel_click_only_requests_confirmation(self):
        cfg=config.load_config();cfg['antispam']['banned_words']=['palavra']
        config.save_config(cfg)
        handler=InteractivePanelHandler(None);handler._require_admin=AsyncMock(return_value=True)
        update=self.update('cfg:banned:clear_all')
        await handler.handle_callback(update,self.context)
        self.assertEqual(config.load_config()['antispam']['banned_words'],['palavra'])
        keyboard=update.callback_query.edit_message_text.await_args.kwargs['reply_markup']
        token=keyboard.inline_keyboard[0][0].callback_data.split(':')[-1]
        with patch('modules.access.require_management_access',new=AsyncMock(return_value=True)):
            await handler.handle_callback(self.update('cfg:confirm:'+token),self.context)
        self.assertEqual(config.load_config()['antispam']['banned_words'],[])

    async def test_acervo_command_requires_confirmation_before_clearing(self):
        from modules import inline_acervo
        update=self.update('');update.callback_query=None
        with patch('modules.access.require_management_access',new=AsyncMock(return_value=True)), \
             patch.object(inline_acervo.acervo_db,'clear_all',return_value=9) as clear:
            await inline_acervo.cmd_limpar_acervo(update,self.context)
            clear.assert_not_called()
            keyboard=update.effective_message.reply_text.await_args.kwargs['reply_markup']
            callback=keyboard.inline_keyboard[0][0].callback_data
            await confirmations.handle_confirmation(self.update(callback),self.context)
            clear.assert_called_once()

    async def test_cancel_does_not_execute_and_cannot_be_reused(self):
        update=self.update('cfg:banned:clear_all')
        await confirmations.request_confirmation(update,self.context,'banned_clear',{},'Apagar?','cfg:sub:banned')
        token=next(iter(confirmations.registry(self.context).pending))
        with patch('modules.access.require_management_access',new=AsyncMock(return_value=True)), \
             patch.object(confirmations,'execute_action',new=AsyncMock()) as execute:
            await confirmations.handle_confirmation(self.update('cfg:abort:'+token),self.context)
            await confirmations.handle_confirmation(self.update('cfg:confirm:'+token),self.context)
        execute.assert_not_awaited()

    async def test_changed_item_is_not_deleted_by_stale_confirmation(self):
        cfg=config.load_config();cfg['auto_responses']=[{'id':1,'title':'Antes'}];config.save_config(cfg)
        payload={'id':1,'expected':confirmations.fingerprint({'id':1,'title':'Antes'})}
        cfg=config.load_config();cfg['auto_responses'][0]['title']='Depois';config.save_config(cfg)
        result=await confirmations.execute_action('resp_delete',payload)
        self.assertIn('alterado',result)
        self.assertEqual(config.load_config()['auto_responses'][0]['title'],'Depois')

    async def test_permission_is_rechecked_when_confirming(self):
        await confirmations.request_confirmation(self.update(''),self.context,'banned_clear',{},'Apagar?','cfg:sub:banned')
        token=next(iter(confirmations.registry(self.context).pending))
        with patch('modules.access.require_management_access',new=AsyncMock(return_value=False)), \
             patch.object(confirmations,'execute_action',new=AsyncMock()) as execute:
            await confirmations.handle_confirmation(self.update('cfg:confirm:'+token),self.context)
        execute.assert_not_awaited()

    async def test_bulk_chat_purge_waits_for_confirmation_and_keeps_newer_messages(self):
        from modules.admin_commands import AdminCommandHandler
        # Não precisa inicializar o gerenciador de comandos para verificar esta rotina.
        handler=SimpleNamespace(_require_admin=AsyncMock(return_value=True))
        update=self.update('');update.callback_query=None
        update.effective_message.message_id=100
        self.context.args=['3']
        self.bot.delete_message=AsyncMock()
        await AdminCommandHandler.cmd_limpar(handler,update,self.context)
        self.bot.delete_message.assert_not_awaited()
        callback=update.effective_message.reply_text.await_args.kwargs['reply_markup'].inline_keyboard[0][0].callback_data
        with patch('modules.access.require_management_access',new=AsyncMock(return_value=True)):
            await confirmations.handle_confirmation(self.update(callback),self.context)
        ids=[call.kwargs['message_id'] for call in self.bot.delete_message.await_args_list]
        self.assertEqual(ids,[100,99,98,97])

    async def test_empty_target_set_fails_without_repeated_pending_dispatch(self):
        self.entry(target='all_channels')
        cfg=config.load_config();cfg['linked_channels']=[];cfg['main_channel_id']=None;config.save_config(cfg)
        await self.service.start()
        with patch.object(delivery,'frozen_targets',return_value=[]):
            self.assertFalse(self.service.start_transmission(7,force=True))
        self.assertEqual(self.result()['status'],'failed')
        self.bot.send_message.assert_not_awaited()

    async def test_delivery_checkpoint_exists_before_second_destination_send(self):
        self.entry(target='all_channels')
        seen=[]
        async def send(**kwargs):
            if seen:
                previous=next(row for row in self.result()['delivery_results'] if row['chat_id']==seen[-1])
                self.assertEqual(previous['status'],'sent')
                self.assertEqual(previous['message_ids'],[101])
            seen.append(kwargs['chat_id'])
            return self.message
        self.bot.send_message.side_effect=send
        await self.send()
        self.assertGreaterEqual(len(seen),2)

    async def test_report_notification_failure_does_not_change_delivery(self):
        self.entry(target='chn:-100111',creator_id=42)
        async def send(**kwargs):
            if kwargs['chat_id']==42:
                raise NetworkError('relatório indisponível')
            return self.message
        self.bot.send_message.side_effect=send
        await self.send()
        self.assertEqual(self.result()['status'],'completed')

    async def test_new_navigation_is_usable_through_panel_dispatcher(self):
        cfg=config.load_config()
        cfg['linked_groups']=[{'id':-1000-i,'title':f'Grupo {i}'} for i in range(15)]
        config.save_config(cfg)
        handler=InteractivePanelHandler(None);handler._require_admin=AsyncMock(return_value=True)
        update=self.update('cfg:list:chats:2')
        await handler.handle_callback(update,self.context)
        self.assertIn('página 2/',update.callback_query.edit_message_text.await_args.args[0])
        self.assertEqual(self.context.user_data['_list_pages']['chats'],2)

    async def test_detail_retry_button_dispatches_only_eligible_targets(self):
        self.entry(status='partial',delivery_results=[
            {'chat_id':1,'status':'sent','message_ids':[1]},
            {'chat_id':2,'status':'failed','message_ids':[]}])
        await self.service.start()
        handler=InteractivePanelHandler(None);handler._require_admin=AsyncMock(return_value=True)
        await handler.handle_callback(self.update('cfg:txretry:7'),self.context)
        await asyncio.gather(*list(self.service.transmissions.values()))
        self.assertEqual([call.kwargs['chat_id'] for call in self.bot.send_message.await_args_list],[2])

    async def test_clear_acervo_callback_only_opens_confirmation(self):
        from modules import inline_acervo
        with patch('modules.access.require_management_access',new=AsyncMock(return_value=True)), \
             patch.object(inline_acervo.acervo_db,'purge_text_chatter') as purge:
            update=self.update('acervo:purge_chatter')
            await inline_acervo.handle_acervo_callback(update,self.context)
        purge.assert_not_called()
        self.assertIn('Confirmar ação',update.callback_query.edit_message_text.await_args.args[0])

    async def test_checkpoint_failure_after_telegram_acceptance_is_not_retried(self):
        self.entry(target='chn:-100111')
        original=delivery.save_config
        calls=0
        def save(cfg):
            nonlocal calls
            calls+=1
            return False if calls==2 else original(cfg)
        with patch.object(delivery,'save_config',side_effect=save):
            await self.send()
        self.bot.send_message.assert_awaited_once()
        row=self.result()['delivery_results'][0]
        self.assertEqual(row['status'],'unknown')
        self.assertEqual(row['message_ids'],[101])
        self.assertFalse(self.service.start_transmission(7,force=True,mode='failed'))

    async def test_telegram_confirmed_chat_id_repairs_linked_configuration(self):
        self.entry(target='chn:-100111')
        self.message.chat=SimpleNamespace(id=-100999)
        await self.send()
        self.assertEqual(self.result()['delivery_results'][0]['actual_chat_id'],-100999)
        cfg=config.load_config()
        self.assertEqual(cfg['main_channel_id'],-100999)
        self.assertTrue(any(chat['id']==-100999 for chat in cfg['linked_channels']))

    async def test_acervo_channel_links_reach_last_page(self):
        from modules import inline_acervo
        channels=[{'channel_id':-1000-index,'channel_title':f'Canal {index}','qtd':1} for index in range(17)]
        with patch.object(inline_acervo,'load_config',return_value={}), \
             patch.object(inline_acervo,'get_all_acervo_channels',return_value=channels):
            text,keyboard=inline_acervo.generate_channel_links_menu_text_and_kb(4)
        self.assertIn('Canal 16',text)
        targets=[button.callback_data for row in keyboard.inline_keyboard for button in row if button.callback_data.startswith('acervo:edit_link:')]
        self.assertEqual(len(targets),2)

    async def test_acervo_scan_chooser_reaches_previously_hidden_channels(self):
        from modules import inline_acervo
        channels=[{'id':-1000-index,'title':f'Canal {index}'} for index in range(17)]
        update=self.update('acervo:scan:page:3')
        with patch('modules.access.require_management_access',new=AsyncMock(return_value=True)), \
             patch.object(inline_acervo,'load_config',return_value={'linked_channels':channels}):
            await inline_acervo.handle_acervo_callback(update,self.context)
        keyboard=update.callback_query.edit_message_text.await_args.kwargs['reply_markup']
        targets=[button.callback_data for row in keyboard.inline_keyboard for button in row if (button.callback_data or '').startswith('acervo:scan:do:')]
        self.assertEqual(len(targets),5)

    async def test_shutdown_during_request_keeps_remaining_destinations_unsent(self):
        self.entry(target='all_channels')
        gate=asyncio.Event();entered=asyncio.Event()
        async def send(**kwargs):
            entered.set()
            await gate.wait()
            return self.message
        self.bot.send_message.side_effect=send
        await self.service.start()
        self.assertTrue(self.service.start_transmission(7,force=True))
        await asyncio.wait_for(entered.wait(),1)
        await self.service.stop()
        statuses=[row['status'] for row in self.result()['delivery_results']]
        self.assertEqual(statuses[0],'unknown')
        self.assertTrue(all(status=='pending' for status in statuses[1:]))


class RegistryAndPaginationTests(unittest.TestCase):
    def test_confirmation_is_bound_to_user_chat_message_and_single_use(self):
        store=confirmations.ConfirmationRegistry()
        token=store.issue(42,1,'x',{},now=0);store.bind(token,33)
        for user,chat,message in [(99,1,33),(42,2,33),(42,1,34)]:
            self.assertIsNone(store.consume(token,user,chat,message,now=1))
        self.assertIsNotNone(store.consume(token,42,1,33,now=1))
        self.assertIsNone(store.consume(token,42,1,33,now=1))

    def test_expired_confirmation_cannot_execute(self):
        store=confirmations.ConfirmationRegistry()
        token=store.issue(42,1,'x',{},now=0);store.bind(token,33)
        self.assertIsNone(store.consume(token,42,1,33,now=121))

    def test_all_group_channels_are_reachable_with_bounded_buttons(self):
        cfg={'linked_groups':[{'id':i,'title':str(i)} for i in range(25)],'linked_channels':[]}
        seen=[]
        for page in range(1,5):
            _,keyboard=lists.chats_page(cfg,page)
            targets=[button.callback_data for row in keyboard.inline_keyboard for button in row if button.callback_data.startswith('cfg:chat:info:')]
            self.assertLessEqual(len(targets),8)
            seen+=targets
        self.assertEqual(len(set(seen)),25)

    def test_last_page_is_clamped_after_item_removal(self):
        items,page,pages,_=lists.page_slice(list(range(7)),999,5)
        self.assertEqual((items,page,pages),([5,6],2,2))
        self.assertEqual(lists.page_slice([],0,5)[:3],([],1,1))

    def test_long_allowed_links_have_short_callbacks(self):
        cfg={'antispam':{'allowed_domains':['example.com/'+('p'*500)]}}
        text,keyboard=lists.allowed_links(cfg)
        self.assertIn('example.com',text)
        for row in keyboard.inline_keyboard:
            for button in row:
                self.assertLessEqual(len(button.callback_data.encode()),64)

    def test_destination_selection_reaches_previously_hidden_channels(self):
        cfg={'linked_groups':[],'linked_channels':[{'id':-100000-i,'title':f'C{i}'} for i in range(16)]}
        _,keyboard=lists.wizard_destinations(cfg,3)
        targets=[button.callback_data for row in keyboard.inline_keyboard for button in row if button.callback_data.startswith('cfg:wiz:dest:chn:')]
        self.assertEqual(len(targets),4)

    def test_transmission_history_includes_completed_and_failed(self):
        cfg={'scheduled_transmissions':[{'id':i,'status':'completed'} for i in range(13)]}
        _,keyboard=lists.transmissions_page(cfg,3)
        self.assertEqual(sum(button.callback_data.startswith('cfg:tx:') for row in keyboard.inline_keyboard for button in row),3)

    def test_unknown_destinations_do_not_get_retry_button(self):
        cfg={'scheduled_transmissions':[{'id':7,'status':'partial','delivery_results':[{'chat_id':1,'status':'unknown'}]}]}
        text,keyboard=lists.transmission_detail(cfg,7)
        self.assertIn('Sem confirmação',text)
        self.assertFalse(any(button.callback_data.startswith('cfg:txretry:') for row in keyboard.inline_keyboard for button in row))

    def test_banned_words_and_response_lists_are_bounded(self):
        cfg={'antispam':{'banned_words':[f'palavra{i}' for i in range(50)]},
             'auto_responses':[{'id':i,'title':str(i),'pattern':'x'} for i in range(50)]}
        text,_=lists.banned_words(cfg,7)
        self.assertIn('palavra49',text)
        self.assertNotIn('palavra0\n',text)
        _,keyboard=lists.responders_page('Chat',cfg,10)
        self.assertEqual(sum(button.callback_data.startswith('cfg:resp:detail:') for row in keyboard.inline_keyboard for button in row),5)


if __name__=='__main__':
    unittest.main()
