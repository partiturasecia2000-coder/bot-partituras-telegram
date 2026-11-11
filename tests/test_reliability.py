"""Testes offline: python -m unittest discover -s tests -p test_*.py -v"""
import asyncio
import copy
import gc
import json
import os
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

STATE = ROOT / 'tests' / ('runtime-' + uuid4().hex)
STATE.mkdir()
config.BASE_DIR = STATE
config.CONFIG_PATH = STATE / 'config.json'
config.ENV_PATH = STATE / '.env'

import main
from modules import access, storage
from modules.acervo_database import AcervoDatabase
from modules.panel import InteractivePanelHandler
from modules.panel_handlers import callbacks, inputs
from modules.panel_handlers.callback_routes import CALLBACK_ROUTES
from modules.panel_handlers.input_routes import INPUT_ROUTES
from modules.utils import AdminCache


def tearDownModule():
    gc.collect()
    assert STATE.resolve().parent == (ROOT / 'tests').resolve()
    shutil.rmtree(STATE)


class StorageTests(unittest.TestCase):
    def setUp(self):
        self.directory = STATE / uuid4().hex
        self.directory.mkdir()
        self.patches = [patch.object(config, 'BASE_DIR', self.directory),
                       patch.object(config, 'CONFIG_PATH', self.directory / 'config.json')]
        for item in self.patches:
            item.start()
            self.addCleanup(item.stop)

    def test_atomic_write_failure_preserves_primary_and_backup(self):
        self.assertTrue(config.save_config({'value': 'original'}))
        with patch.object(storage.os, 'replace', side_effect=OSError('falha simulada')):
            self.assertFalse(config.save_config({'value': 'novo'}))
        self.assertEqual(storage.read_json_object(config.CONFIG_PATH), {'value': 'original'})
        self.assertEqual(storage.read_json_object(self.directory / '.config_backup.json'), {'value': 'original'})
        self.assertEqual(list(self.directory.glob('*.tmp')), [])

    def test_invalid_payload_preserves_file(self):
        config.save_config({'value': 1})
        self.assertFalse(config.save_config({'value': object()}))
        self.assertEqual(storage.read_json_object(config.CONFIG_PATH), {'value': 1})

    def test_corrupt_primary_recovers_backup(self):
        config.save_config({'custom_value': 'preservado'})
        config.CONFIG_PATH.write_text('{incompleto', encoding='utf-8')
        self.assertEqual(config.load_config()['custom_value'], 'preservado')
        self.assertEqual(storage.read_json_object(config.CONFIG_PATH)['custom_value'], 'preservado')

    def test_corrupt_primary_and_backup_remain_untouched(self):
        config.CONFIG_PATH.write_text('{incompleto', encoding='utf-8')
        backup = self.directory / '.config_backup.json'
        backup.write_text('[]', encoding='utf-8')
        with self.assertRaises(config.ConfigRecoveryError):
            config.load_config()
        self.assertEqual(config.CONFIG_PATH.read_text(encoding='utf-8'), '{incompleto')
        self.assertEqual(backup.read_text(encoding='utf-8'), '[]')

    def test_defaults_do_not_share_nested_state(self):
        original = copy.deepcopy(config.DEFAULT_CONFIG)
        cfg = config.load_config()
        cfg['welcome']['enabled'] = not cfg['welcome']['enabled']
        cfg['auto_responses'].clear()
        self.assertEqual(config.DEFAULT_CONFIG, original)

    def test_connections_close_and_transactions_rollback(self):
        db = AcervoDatabase(self.directory / 'test.db')
        with db._connection() as connection:
            connection.execute('CREATE TABLE verification(value INTEGER)')
        with self.assertRaises(Exception):
            connection.execute('SELECT 1')
        with self.assertRaises(RuntimeError):
            with db._connection() as connection:
                connection.execute('INSERT INTO verification VALUES (1)')
                raise RuntimeError('rollback')
        with db._connection() as connection:
            self.assertEqual(connection.execute('SELECT COUNT(*) FROM verification').fetchone()[0], 0)
        db.db_path.unlink()  # Windows também comprova que não ficou conexão aberta.


class AccessTests(unittest.IsolatedAsyncioTestCase):
    async def test_private_chat_requires_explicit_authorization(self):
        chat = SimpleNamespace(type='private', get_bot=lambda: SimpleNamespace(get_chat_member=AsyncMock()))
        with patch.object(access, 'load_config', return_value={'panel_admin_ids': [42]}), patch.dict(os.environ, {'BOT_ADMIN_IDS': ''}):
            self.assertTrue(await AdminCache().is_admin(chat, 42))
            self.assertFalse(await AdminCache().is_admin(chat, 99))

    async def test_private_admin_can_be_verified_in_linked_group(self):
        lookup = AsyncMock(return_value=SimpleNamespace(status='administrator'))
        chat = SimpleNamespace(type='private', get_bot=lambda: SimpleNamespace(get_chat_member=lookup))
        with patch.object(access, 'load_config', return_value={'linked_groups': [{'id': -100123}]}), patch.dict(os.environ, {'BOT_ADMIN_IDS': ''}):
            self.assertTrue(await AdminCache().is_admin(chat, 42))
        lookup.assert_awaited_once_with(-100123, 42)

    async def test_private_permission_check_failure_denies(self):
        lookup = AsyncMock(side_effect=RuntimeError('sem acesso'))
        chat = SimpleNamespace(type='private', get_bot=lambda: SimpleNamespace(get_chat_member=lookup))
        with patch.object(access, 'load_config', return_value={'main_group_id': -100123}), patch.dict(os.environ, {'BOT_ADMIN_IDS': ''}):
            self.assertFalse(await AdminCache().is_admin(chat, 42))

    async def test_group_member_is_denied_and_admin_allowed(self):
        chat = SimpleNamespace(id=-100123, type='supergroup', get_member=AsyncMock(return_value=SimpleNamespace(status='member')))
        self.assertFalse(await AdminCache().is_admin(chat, 42))
        chat.get_member.return_value.status = 'administrator'
        self.assertTrue(await AdminCache().is_admin(chat, 42))


class PanelTests(unittest.IsolatedAsyncioTestCase):
    def make_handler(self):
        with patch('modules.panel.load_config', return_value={}):
            handler = InteractivePanelHandler(AdminCache())
        handler._save_pending_inputs = lambda: None
        return handler

    def update(self, data):
        return SimpleNamespace(
            callback_query=SimpleNamespace(data=data, answer=AsyncMock(), edit_message_text=AsyncMock()),
            effective_user=SimpleNamespace(id=42),
            effective_chat=SimpleNamespace(id=-100123, title='Teste', type='supergroup'),
            effective_message=SimpleNamespace(text='teste', reply_text=AsyncMock()))

    async def test_denied_callback_does_not_load_or_change_config(self):
        handler = self.make_handler()
        handler._require_admin = AsyncMock(return_value=False)
        update = self.update('cfg:toggle:antispam')
        with patch.object(callbacks, 'load_config') as load:
            await handler.handle_callback(update, None)
        load.assert_not_called()
        update.callback_query.answer.assert_awaited_once()
        update.callback_query.edit_message_text.assert_not_awaited()

    async def test_unknown_callback_is_acknowledged(self):
        handler = self.make_handler()
        handler._require_admin = AsyncMock(return_value=True)
        update = self.update('cfg:nao_existe')
        with patch.object(callbacks, 'load_config', return_value={}), \
             patch.object(callbacks, 'handle_welcome_callback', new=AsyncMock(return_value=False)), \
             patch.object(callbacks, 'handle_whitelist_callback', new=AsyncMock(return_value=False)):
            await handler.handle_callback(update, None)
        update.callback_query.answer.assert_awaited_once()

    async def test_pending_input_rechecks_permissions(self):
        handler = self.make_handler()
        handler._require_admin = AsyncMock(return_value=False)
        handler.pending_inputs[42] = {'action': 'banned_add'}
        with patch.object(inputs, 'load_config', return_value={}):
            self.assertTrue(await handler.handle_pending_input(self.update(''), None))
        self.assertIn(42, handler.pending_inputs)

    async def test_cancellation_clears_wizard_and_pending_input(self):
        handler = self.make_handler()
        handler.pending_inputs[42] = {'action': 'wiz_text'}
        handler.wizard_states[42] = {'text': 'rascunho'}
        await handler.cmd_cancelar(self.update(''), None)
        self.assertEqual(handler.pending_inputs, {})
        self.assertEqual(handler.wizard_states, {})

    async def test_route_tables_keep_precedence(self):
        self.assertEqual(len(CALLBACK_ROUTES), 161)
        self.assertEqual(len(INPUT_ROUTES), 27)
        cases = {'cfg:rec:list:2': 'on_cfg_rec_list', 'cfg:wiz:start': 'on_cfg_wiz_start',
                 'cfg:toggle:antispam': 'on_cfg_toggle_antispam'}
        for data, expected in cases.items():
            functions = [fn for match, fn in CALLBACK_ROUTES if match(data)]
            self.assertEqual(functions[0].__name__, expected)
        # The specific duration editor must not be swallowed by welcome_ routing.
        matches = [fn for match, fn in INPUT_ROUTES if match('welcome_autodel_time')]
        self.assertEqual(matches[0].__name__, 'on_welcome_autodel_time')

    async def test_welcome_custom_duration_is_saved(self):
        from modules.panel_handlers.input_routes import settings
        handler = self.make_handler()
        handler._require_admin = AsyncMock(return_value=True)
        handler.pending_inputs[42] = {'action': 'welcome_autodel_time', 'group_id': 'general'}
        update = self.update('')
        update.effective_message.text = '10m'
        cfg = {'welcome': {}}
        with patch.object(inputs, 'load_config', return_value=cfg), \
             patch.object(inputs, 'handle_whitelist_input', new=AsyncMock(return_value=False)), \
             patch.object(settings, 'save_config', return_value=True) as save:
            self.assertTrue(await handler.handle_pending_input(update, None))
        self.assertEqual(cfg['welcome']['delete_welcome_after_seconds'], 600)
        save.assert_called_once_with(cfg)
        self.assertNotIn(42, handler.pending_inputs)

    async def test_moderation_toggle_is_dispatched_and_saved(self):
        from modules.panel_handlers.callback_routes import moderation
        handler = self.make_handler()
        handler._require_admin = AsyncMock(return_value=True)
        update = self.update('cfg:toggle:antispam')
        cfg = {'antispam': {'enabled': True}}
        with patch.object(callbacks, 'load_config', return_value=cfg), \
             patch.object(callbacks, 'handle_welcome_callback', new=AsyncMock(return_value=False)), \
             patch.object(callbacks, 'handle_whitelist_callback', new=AsyncMock(return_value=False)), \
             patch.object(moderation, 'save_config', return_value=True) as save:
            await handler.handle_callback(update, None)
        self.assertFalse(cfg['antispam']['enabled'])
        save.assert_called_once_with(cfg)
        update.callback_query.edit_message_text.assert_awaited_once()

    async def test_acervo_management_denies_unauthorized_user(self):
        from modules.inline_acervo import cmd_limpar_acervo
        update = self.update('')
        update.callback_query = None
        with patch.object(AdminCache, 'is_admin', new=AsyncMock(return_value=False)), \
             patch('modules.inline_acervo.acervo_db.clear_all') as clear:
            await cmd_limpar_acervo(update, None)
        clear.assert_not_called()
        update.effective_message.reply_text.assert_awaited_once()


class StartupTests(unittest.TestCase):
    def test_all_handlers_and_jobs_register_without_network(self):
        from telegram.ext import Application
        captured = []
        with patch.object(main, 'get_bot_token', return_value='123456:offline_test_only'), \
             patch.object(main, 'start_cloud_health_server'), \
             patch.object(Application, 'run_polling', autospec=True, side_effect=lambda app, **kwargs: captured.append(app)):
            main.main()
        self.assertEqual(len(captured), 1)
        app = captured[0]
        self.assertIsNotNone(app.job_queue)
        jobs = {job.name for job in app.job_queue.jobs()}
        self.assertEqual(jobs, set())  # ciclos periódicos pertencem ao agendador central
        self.assertIsNotNone(app.post_init)
        self.assertIsNotNone(app.post_stop)
        self.assertGreater(sum(len(group) for group in app.handlers.values()), 20)


if __name__ == '__main__':
    unittest.main()
