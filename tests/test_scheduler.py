"""Ciclos, reinício, exclusões e reserva de transmissões sem rede."""
import asyncio
from datetime import datetime, timezone
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
from modules import scheduler, recurring
from modules.scheduled_deletions import DeletionStore
from modules.utils import schedule_message_deletion


class SchedulerTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.directory = ROOT / 'tests' / ('runtime-' + uuid4().hex)
        self.directory.mkdir()
        self.patches = [patch.object(config, 'BASE_DIR', self.directory),
                        patch.object(config, 'CONFIG_PATH', self.directory/'config.json')]
        for item in self.patches:
            item.start()
        self.bot = SimpleNamespace(delete_message=AsyncMock())
        self.app = SimpleNamespace(bot=self.bot, job_queue=None)
        self.store = DeletionStore(self.directory/'agendamentos.db')
        self.service = scheduler.TaskScheduler(self.app, self.store)
        # Production cycle registration is checked separately; tests drive time explicitly.
        self.cycles = patch.object(self.service, 'cycles', return_value={})
        self.cycles.start()
        config.save_config({'scheduled_transmissions': []})

    async def asyncTearDown(self):
        await self.service.stop()
        self.cycles.stop()
        for item in reversed(self.patches):
            item.stop()
        assert self.directory.resolve().parent == (ROOT/'tests').resolve()
        shutil.rmtree(self.directory)

    async def test_start_is_idempotent_and_stop_releases_service(self):
        await self.service.start()
        await self.service.start()
        self.assertIs(scheduler.active_scheduler(), self.service)
        await self.service.stop()
        self.assertIsNone(scheduler.active_scheduler())

    async def test_a_failed_cycle_does_not_stop_other_cycles(self):
        bad = AsyncMock(side_effect=RuntimeError('simulado'))
        good = AsyncMock()
        await self.service.run_cycle('falha', bad)
        await self.service.run_cycle('outra', good)
        self.assertEqual(self.service.health['falha']['error'], 'RuntimeError')
        self.assertFalse(self.service.health['falha']['running'])
        good.assert_awaited_once()

    async def test_cycles_run_independently_and_stop_cancels_workers(self):
        self.cycles.stop()
        blocked = asyncio.Event()
        fast = asyncio.Event()
        async def slow():
            await blocked.wait()
        async def quick():
            fast.set()
        self.cycles = patch.object(self.service, 'cycles', return_value={
            'lento': (slow, 100, 0), 'rápido': (quick, 100, 0)})
        self.cycles.start()
        await self.service.start()
        await asyncio.wait_for(fast.wait(), 1)
        tasks = list(self.service.workers.values())
        await self.service.stop()
        self.assertTrue(all(task.done() for task in tasks))

    async def test_due_deletion_survives_reopening_store(self):
        self.store.schedule(-100123, 7, -1)
        self.service.deletions = DeletionStore(self.store.path)
        await self.service.delete_due_messages()
        self.bot.delete_message.assert_awaited_once_with(-100123, 7)
        self.assertEqual(self.store.counts(), {})

    async def test_future_deletion_does_not_run(self):
        self.store.schedule(-100123, 7, 3600)
        await self.service.delete_due_messages()
        self.bot.delete_message.assert_not_awaited()
        self.assertEqual(self.store.counts(), {'pending': 1})

    async def test_deletion_failure_is_retried_with_limit(self):
        self.store.schedule(-100123, 7, -1)
        self.bot.delete_message.side_effect = RuntimeError('offline')
        await self.service.delete_due_messages()
        self.assertEqual(self.store.due(), [])
        self.assertEqual(self.store.counts(), {'pending': 1})
        for _ in range(4):
            with self.store.connection() as db:
                db.execute('UPDATE deletions SET due_at=0')
            await self.service.delete_due_messages()
        self.assertEqual(self.store.counts(), {'failed': 1})

    async def test_already_deleted_message_is_complete(self):
        from telegram.error import BadRequest
        self.store.schedule(-100123, 7, -1)
        self.bot.delete_message.side_effect = BadRequest('Message to delete not found')
        await self.service.delete_due_messages()
        self.assertEqual(self.store.counts(), {})

    async def test_central_deletion_does_not_register_jobqueue_duplicate(self):
        await self.service.start()
        jq = SimpleNamespace(run_once=AsyncMock())
        schedule_message_deletion(jq, -100123, 7, 10)
        jq.run_once.assert_not_called()
        self.assertEqual(self.store.counts(), {'pending': 1})

    async def test_restart_marks_incomplete_send_for_review(self):
        config.save_config({'scheduled_transmissions': [{'id': 1, 'status': 'sending'}]})
        await self.service.start()
        self.assertEqual(config.load_config()['scheduled_transmissions'][0]['status'], 'interrupted')
        self.assertEqual(self.service.transmissions, {})

    async def test_only_one_claim_and_state_saved_before_execution(self):
        config.save_config({'scheduled_transmissions': [{'id': 1, 'status': 'pending', 'schedule_timestamp': 0}]})
        await self.service.start()
        gate = asyncio.Event()
        async def execute(bot, item):
            self.assertEqual(config.load_config()['scheduled_transmissions'][0]['status'], 'sending')
            await gate.wait()
        with patch.object(recurring, '_execute_scheduled_transmission', new=execute):
            self.assertTrue(self.service.start_transmission(1))
            self.assertFalse(self.service.start_transmission(1, force=True))
            await asyncio.sleep(0)
            await self.service.stop()
        self.assertEqual(config.load_config()['scheduled_transmissions'][0]['status'], 'interrupted')

    async def test_failed_claim_does_not_send(self):
        config.save_config({'scheduled_transmissions': [{'id': 1, 'status': 'pending'}]})
        await self.service.start()
        with patch.object(scheduler, 'save_config', return_value=False):
            self.assertFalse(self.service.start_transmission(1, force=True))
        self.assertEqual(self.service.transmissions, {})

    async def test_stop_before_task_first_runs_marks_interrupted(self):
        config.save_config({'scheduled_transmissions': [{'id': 1, 'status': 'pending'}]})
        await self.service.start()
        self.assertTrue(self.service.start_transmission(1, force=True))
        await self.service.stop()
        self.assertEqual(config.load_config()['scheduled_transmissions'][0]['status'], 'interrupted')

    async def test_production_registers_exactly_six_unique_cycles(self):
        from modules.scheduler import TaskScheduler
        self.assertEqual(len(TaskScheduler.cycles(self.service)), 6)

    async def test_application_hooks_start_and_stop_central_workers(self):
        import main
        from telegram.ext import Application
        captured = []
        with patch.object(main, 'get_bot_token', return_value='123456:offline_test_only'), \
             patch.object(main, 'start_cloud_health_server'), \
             patch.object(Application, 'run_polling', autospec=True, side_effect=lambda app, **kwargs: captured.append(app)):
            main.main()
        app = captured[0]
        bot = SimpleNamespace(set_my_commands=AsyncMock(), delete_my_commands=AsyncMock(), delete_message=AsyncMock())
        runtime = SimpleNamespace(bot=bot, bot_data={}, job_queue=None)
        with patch.object(main.acervo_db, 'purge_text_chatter', return_value=0):
            await app.post_init(runtime)
            await asyncio.sleep(0)
            service = runtime.bot_data['task_scheduler']
            self.assertEqual(len(service.workers), 6)
            await app.post_stop(runtime)
        self.assertFalse(service.started)
        self.assertEqual(service.workers, {})
        self.assertIsNone(scheduler.active_scheduler())

    async def test_backup_contains_consistent_persistent_deletion_queue(self):
        import sqlite3
        import zipfile
        from modules import backup_manager
        archive_path = self.directory/'acervo_partituras.db'
        connection = sqlite3.connect(archive_path)
        connection.execute('CREATE TABLE acervo(id INTEGER)')
        connection.close()
        self.store.schedule(-100123, 7, 3600)
        with patch.object(backup_manager, 'BASE_DIR', self.directory), \
             patch.object(backup_manager, 'CONFIG_PATH', config.CONFIG_PATH), \
             patch.object(backup_manager, 'DB_PATH', archive_path):
            _, buffer, _, _ = backup_manager.create_backup_zip()
        with zipfile.ZipFile(buffer) as archive:
            self.assertIsNone(archive.testzip())
            restored = self.directory/'restored.db'
            restored.write_bytes(archive.read('agendamentos.db'))
        self.assertEqual(DeletionStore(restored).counts(), {'pending': 1})
        self.assertEqual(list(self.directory.glob('.backup-*.db')), [])

    async def test_failed_send_is_not_left_sending(self):
        config.save_config({'scheduled_transmissions': [{'id': 1, 'status': 'pending'}]})
        await self.service.start()
        with patch.object(recurring, '_execute_scheduled_transmission', new=AsyncMock(side_effect=RuntimeError('simulado'))):
            self.assertTrue(self.service.start_transmission(1, force=True))
            await asyncio.gather(*self.service.transmissions.values())
        self.assertEqual(config.load_config()['scheduled_transmissions'][0]['status'], 'failed')

    async def test_cancelled_and_future_transmissions_do_not_send(self):
        config.save_config({'scheduled_transmissions': [
            {'id': 1, 'status': 'cancelled'},
            {'id': 2, 'status': 'pending', 'schedule_timestamp': 99999999999}]})
        await self.service.start()
        self.assertFalse(self.service.start_transmission(1, force=True))
        self.assertFalse(self.service.start_transmission(2))

    async def test_daily_recurring_catches_up_today_only_once(self):
        fixed = datetime(2026, 11, 11, 15, 0, tzinfo=timezone.utc)
        message = {'id': 1, 'chat_id': -100123, 'start_hour': 12, 'start_minute': 0,
                   'interval_minutes': 1440, 'enabled': True}
        config.save_config({'recurring_messages': [message]})
        with patch.object(recurring, 'datetime') as clock, \
             patch.object(recurring, 'send_single_recurring_message', new=AsyncMock(return_value=99)) as send:
            clock.now.return_value = fixed
            await recurring.process_recurring_messages_job(self.bot)
            await recurring.process_recurring_messages_job(self.bot)
        send.assert_awaited_once()

    async def test_progress_does_not_overwrite_new_schedules_or_message_edits(self):
        config.save_config({'recurring_messages': [{'id': 1, 'text': 'novo'}],
                            'scheduled_transmissions': [{'id': 10, 'status': 'sending'}]})
        recurring._save_recurring_progress([{'id': 1, 'text': 'antigo', 'last_message_id': 9}])
        cfg = config.load_config()
        self.assertEqual(cfg['recurring_messages'][0]['text'], 'novo')
        self.assertEqual(cfg['recurring_messages'][0]['last_message_id'], 9)
        self.assertEqual(cfg['scheduled_transmissions'][0]['status'], 'sending')


if __name__ == '__main__':
    unittest.main()
