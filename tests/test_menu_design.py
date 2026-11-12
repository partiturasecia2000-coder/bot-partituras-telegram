"""Contratos de navegação e leitura dos menus, sem rede."""
import copy
from datetime import datetime,timezone
from pathlib import Path
import shutil
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock,patch
from uuid import uuid4

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
import config
from modules import menu_screens as menus,menu_shortcuts,panel_lists
from modules.panel import InteractivePanelHandler
from modules.utils import AdminCache


class MenuDesignTests(unittest.TestCase):
    def setUp(self):self.cfg=copy.deepcopy(config.DEFAULT_CONFIG)

    def test_main_buttons_keep_existing_destinations_and_use_wide_rows(self):
        _,keyboard=menus.main_menu('Grupo',self.cfg)
        callbacks={button.callback_data for row in keyboard.inline_keyboard for button in row}
        self.assertTrue({'cfg:hub:clean','cfg:hub:security','cfg:hub:welcome','cfg:sub:acervo',
                         'cfg:hub:messages','cfg:hub:system','cfg:close'}<=callbacks)
        for row in keyboard.inline_keyboard[1:]:self.assertEqual(len(row),1)

    def test_enabled_and_disabled_states_are_written_not_color_only(self):
        self.cfg['antispam']['enabled']=False
        text,keyboard=menus.security_menu(self.cfg)
        self.assertIn('Desativado',text)
        first=keyboard.inline_keyboard[0][0]
        self.assertEqual(first.text,'Ativar antispam')
        self.assertEqual(first.callback_data,'cfg:toggle:antispam')

    def test_screen_generation_does_not_change_configuration(self):
        before=copy.deepcopy(self.cfg)
        for fn in (menus.clean_menu,menus.security_menu,menus.welcome_menu,menus.messages_menu,menus.system_menu,
                   menus.backup_menu,menus.allowed_menu,menus.night_menu,menus.logs_menu,menus.command_clean_menu,
                   menus.spam_menu,menus.flood_menu,menus.welcome_groups,menus.welcome_editor):fn(self.cfg)
        self.assertEqual(self.cfg,before)

    def test_inactive_recurring_messages_are_not_reported_as_active(self):
        self.cfg['recurring_messages']=[{'id':1,'enabled':True},{'id':2,'enabled':False}]
        text,_=menus.messages_menu(self.cfg)
        self.assertIn('1 ativa(s) de 2',text)

    def test_special_characters_in_chat_title_do_not_break_markdown(self):
        text,_=menus.main_menu('Nome *grupo* [A] _teste_',self.cfg)
        self.assertIn(r'Nome \*grupo\* \[A] \_teste\_',text)

    def test_common_menu_labels_fit_a_wide_mobile_button(self):
        screens=[menus.main_menu('Grupo',self.cfg)]
        screens += [fn(self.cfg) for fn in (menus.clean_menu,menus.security_menu,menus.welcome_menu,menus.messages_menu,
                    menus.system_menu,menus.backup_menu,menus.night_menu,menus.logs_menu,menus.command_clean_menu,
                    menus.spam_menu,menus.flood_menu)]
        for text,keyboard in screens:
            self.assertLess(len(text),3000)
            for row in keyboard.inline_keyboard:
                for button in row:
                    self.assertLessEqual(len(button.text),36,button.text)
                    self.assertLessEqual(len(button.callback_data.encode()),64)
                    if len(row)==2:self.assertLessEqual(len(button.text),20)

    def test_backup_and_acervo_keep_critical_actions(self):
        _,keyboard=menus.backup_menu(self.cfg)
        callbacks={button.callback_data for row in keyboard.inline_keyboard for button in row}
        self.assertTrue({'cfg:bkp:now','cfg:rep:now','cfg:restore:start','cfg:toggle:daily_bkp','cfg:toggle:weekly_rep','cfg:bkp:channel'}<=callbacks)
        _,keyboard=menus.acervo_menu(self.cfg,{'total_files':500,'total_channels':3,'by_type':{}})
        self.assertTrue(any(button.switch_inline_query_current_chat=='' for row in keyboard.inline_keyboard for button in row))
        self.assertTrue(any(button.callback_data=='acervo:purge_chatter' for row in keyboard.inline_keyboard for button in row))

    def test_welcome_pages_expose_all_groups_without_long_buttons(self):
        self.cfg['linked_groups']=[{'id':-1000-i,'title':f'Grupo {i}'} for i in range(14)]
        text,keyboard=menus.welcome_groups(self.cfg,3)
        self.assertIn('Grupo 13',text)
        targets=[button.callback_data for row in keyboard.inline_keyboard for button in row if (button.callback_data or '').startswith('cfg:welcome:cfg:')]
        self.assertEqual(len(targets),3)  # modelo geral + dois grupos

    def test_filtering_channels_retains_filter_on_next_page(self):
        self.cfg['linked_groups']=[{'id':-1000,'title':'Grupo não listado'}]
        self.cfg['linked_channels']=[{'id':-2000-i,'title':f'Canal {i}'} for i in range(10)]
        text,keyboard=panel_lists.chats_page(self.cfg,2,kind='channels')
        self.assertIn('CANAIS VINCULADOS',text)
        callbacks={button.callback_data for row in keyboard.inline_keyboard for button in row}
        self.assertIn('cfg:list:channels:1',callbacks)
        self.assertFalse(any((value or '').startswith('cfg:chat:info:grp:') for value in callbacks))

    def test_reply_keyboard_labels_are_bound_and_legacy_aliases_remain(self):
        keyboard=menu_shortcuts.conversation_keyboard()
        for row in keyboard.keyboard:
            for button in row:
                self.assertIn(button.text,menu_shortcuts.SHORTCUTS)
                self.assertLessEqual(len(button.text),20)
        self.assertEqual(menu_shortcuts.SHORTCUTS['🎛️ Painel de Controle'],'panel')
        self.assertEqual(menu_shortcuts.SHORTCUTS['🛡️ Whitelist & Links'],'allowed')

    def test_clean_help_matches_confirmation_workflow(self):
        text,_=menus.clean_help()
        self.assertIn('confirmação',text)
        self.assertNotIn('instantaneamente',text)


class MenuRoutingTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.base=ROOT/'tests'/('runtime-'+uuid4().hex);self.base.mkdir()
        self.patches=[patch.object(config,'BASE_DIR',self.base),patch.object(config,'CONFIG_PATH',self.base/'config.json')]
        for item in self.patches:item.start()
        cfg=copy.deepcopy(config.DEFAULT_CONFIG);cfg.update(panel_admin_ids=[42],linked_groups=[{'id':-100222,'title':'Grupo B'}],
            linked_channels=[{'id':-100111,'title':'Canal A'}],main_channel_id=-100111)
        config.save_config(cfg)

    async def asyncTearDown(self):
        for item in reversed(self.patches):item.stop()
        assert self.base.resolve().parent==(ROOT/'tests').resolve();shutil.rmtree(self.base)

    def update(self,text):
        return SimpleNamespace(effective_message=SimpleNamespace(text=text,reply_text=AsyncMock()),
            effective_chat=SimpleNamespace(id=42,type='private',title=None),effective_user=SimpleNamespace(id=42))

    def application(self):
        import main
        from telegram.ext import Application
        captured=[]
        with patch.object(main,'get_bot_token',return_value='123456:offline_test_only'),patch.object(main,'start_cloud_health_server'), \
             patch.object(Application,'run_polling',autospec=True,side_effect=lambda app,**kwargs:captured.append(app)):
            main.main()
        return captured[0]

    async def test_new_and_old_panel_shortcuts_dispatch_to_panel(self):
        from telegram import Update,Message,Chat,User
        with patch.object(InteractivePanelHandler,'cmd_config',new=AsyncMock()) as panel:
            app=self.application()
            handler=next(handler for handler in app.handlers[0] if handler.callback.__name__=='reply_menu_shortcut')
            for label in ('⚙️ Painel','🎛️ Painel de Controle'):
                real=Update(1,message=Message(33,datetime.now(timezone.utc),Chat(42,'private'),from_user=User(42,'Admin',False),text=label))
                self.assertTrue(handler.check_update(real))
                with patch.object(AdminCache,'is_admin',new=AsyncMock(return_value=True)):
                    await handler.callback(self.update(label),SimpleNamespace())
            self.assertEqual(panel.await_count,2)

    async def test_unauthorized_reply_shortcut_does_not_open_panel(self):
        with patch.object(InteractivePanelHandler,'cmd_config',new=AsyncMock()) as panel:
            app=self.application();handler=next(handler for handler in app.handlers[0] if handler.callback.__name__=='reply_menu_shortcut')
            update=self.update('⚙️ Painel')
            with patch.object(AdminCache,'is_admin',new=AsyncMock(return_value=False)):
                await handler.callback(update,SimpleNamespace())
            panel.assert_not_awaited();update.effective_message.reply_text.assert_awaited_once()

    async def test_channel_shortcut_opens_filtered_paginated_list(self):
        app=self.application();handler=next(handler for handler in app.handlers[0] if handler.callback.__name__=='reply_menu_shortcut')
        update=self.update('📢 Canais')
        with patch.object(AdminCache,'is_admin',new=AsyncMock(return_value=True)):
            await handler.callback(update,SimpleNamespace())
        text=update.effective_message.reply_text.await_args.args[0]
        self.assertIn('CANAIS VINCULADOS',text)
        keyboard=update.effective_message.reply_text.await_args.kwargs['reply_markup']
        self.assertFalse(any((button.callback_data or '').startswith('cfg:chat:info:grp:') for row in keyboard.inline_keyboard for button in row))


if __name__=='__main__':unittest.main()
