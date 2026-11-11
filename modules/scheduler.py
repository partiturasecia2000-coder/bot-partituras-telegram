"""Ciclos supervisionados, exclusões persistentes e transmissões rastreadas."""
import asyncio
import logging
import time

from telegram.error import BadRequest, Forbidden, RetryAfter

from config import load_config, save_config
from modules.scheduled_deletions import DeletionStore

logger = logging.getLogger(__name__)
_active = None


def active_scheduler():
    return _active


class TaskScheduler:
    def __init__(self, application, deletion_store=None):
        import config
        self.application = application
        self.bot = application.bot
        self.deletions = deletion_store or DeletionStore(config.BASE_DIR / 'agendamentos.db')
        self.workers = {}
        self.transmissions = {}
        self.health = {}
        self.started = False

    def cycles(self):
        from modules.recurring import process_recurring_messages_job, process_scheduled_transmissions_job
        from modules.nightmode import check_night_mode_transitions_job
        from modules.youtube_notifier import check_youtube_channels_cycle
        from modules.backup_manager import check_backup_and_report_cycle
        return {
            'Mensagens recorrentes': (lambda: process_recurring_messages_job(self.bot, job_queue=self.application.job_queue), 10, 3),
            'Transmissões': (lambda: process_scheduled_transmissions_job(self.bot), 10, 3),
            'Modo noturno': (lambda: check_night_mode_transitions_job(self.bot), 10, 3),
            'YouTube': (lambda: check_youtube_channels_cycle(self.bot), 10, 3),
            'Backup e relatórios': (lambda: check_backup_and_report_cycle(self.bot), 10, 3),
            'Exclusões': (self.delete_due_messages, 1, 0),
        }

    async def start(self):
        global _active
        if self.started:
            return
        if _active is not None and _active is not self:
            raise RuntimeError('Já existe um agendador ativo neste processo.')
        # Um envio interrompido pode ter chegado ao Telegram sem confirmação local.
        # Exigir revisão evita reenvio automático potencialmente duplicado.
        cfg = load_config()
        changed = False
        for item in cfg.get('scheduled_transmissions', []):
            if item.get('status') == 'sending':
                item.update(status='interrupted', interrupted_at=time.time())
                changed = True
        if changed and not save_config(cfg):
            raise RuntimeError('Não foi possível registrar os envios interrompidos.')
        _active = self
        self.started = True
        for name, (callback, interval, first) in self.cycles().items():
            self.workers[name] = asyncio.create_task(self._loop(name, callback, interval, first), name=name)

    async def _loop(self, name, callback, interval, first):
        await asyncio.sleep(first)
        while True:
            await self.run_cycle(name, callback)
            await asyncio.sleep(interval)

    async def run_cycle(self, name, callback):
        state = self.health.setdefault(name, {})
        state['running'] = True
        state['last_started'] = time.time()
        try:
            await callback()
            state.update(last_success=time.time(), error=None)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            state.update(error=type(exc).__name__, last_failure=time.time())
            logger.exception('Falha no ciclo %s; nova tentativa no próximo ciclo.', name)
        finally:
            state['running'] = False

    async def stop(self):
        global _active
        self.started = False
        active_ids = list(self.transmissions)
        tasks = list(self.workers.values()) + list(self.transmissions.values())
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        # Uma task cancelada antes da primeira execução não entra no try de _send.
        for item_id in active_ids:
            self._mark_transmission(item_id, 'interrupted')
        self.workers.clear()
        self.transmissions.clear()
        if _active is self:
            _active = None

    def start_transmission(self, item_id, force=False):
        if not self.started or item_id in self.transmissions:
            return False
        cfg = load_config()
        item = next((x for x in cfg.get('scheduled_transmissions', []) if x.get('id') == item_id), None)
        allowed = ('pending', 'interrupted', 'failed') if force else ('pending',)
        if not item or item.get('status') not in allowed:
            return False
        if not force and time.time() < item.get('schedule_timestamp', 0):
            return False
        item.update(status='sending', started_at=time.time())
        # Persistir antes de iniciar o envio, sem await entre leitura e reserva.
        if not save_config(cfg):
            return False
        task = asyncio.create_task(self._send(dict(item)), name=f'transmission-{item_id}')
        self.transmissions[item_id] = task
        task.add_done_callback(lambda done: self.transmissions.pop(item_id, None))
        return True

    def _mark_transmission(self, item_id, status):
        cfg = load_config()
        for item in cfg.get('scheduled_transmissions', []):
            if item.get('id') == item_id and item.get('status') == 'sending':
                item.update(status=status, interrupted_at=time.time())
                if not save_config(cfg):
                    logger.error('Não foi possível salvar o estado da transmissão %s.', item_id)
                break

    async def _send(self, item):
        from modules.recurring import _execute_scheduled_transmission
        try:
            await _execute_scheduled_transmission(self.bot, item)
        except asyncio.CancelledError:
            self._mark_transmission(item['id'], 'interrupted')
            raise
        except Exception:
            self._mark_transmission(item['id'], 'failed')
            logger.exception('Falha na transmissão %s.', item['id'])

    async def delete_due_messages(self):
        for item in self.deletions.due():
            raw_id = item['chat_id']
            chat_id = int(raw_id) if raw_id.lstrip('-').isdigit() else raw_id
            try:
                await self.bot.delete_message(chat_id, item['message_id'])
            except RetryAfter as exc:
                delay = exc.retry_after
                if hasattr(delay, 'total_seconds'):
                    delay = delay.total_seconds()
                self.deletions.retry(item, 'RetryAfter', float(delay)+1)
            except BadRequest as exc:
                if 'message to delete not found' in str(exc).lower():
                    self.deletions.complete(item)
                else:
                    self.deletions.retry(item, 'BadRequest', 0, permanent=True)
            except Forbidden:
                self.deletions.retry(item, 'Forbidden', 0, permanent=True)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self.deletions.retry(item, type(exc).__name__, 30 * (item['attempts']+1))
            else:
                self.deletions.complete(item)


def start_scheduled_transmission(item_id, force=False):
    scheduler = active_scheduler()
    return bool(scheduler and scheduler.start_transmission(item_id, force=force))
