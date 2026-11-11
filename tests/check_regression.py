"""Verificacao offline: python tests/check_regression.py"""

import copy, inspect, json, pathlib, sys
from datetime import datetime
import uuid, shutil
root=pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root))
_scratch=root/'tests'/('bot-regression-'+uuid.uuid4().hex)
import config
config.BASE_DIR = _scratch; config.BASE_DIR.mkdir(exist_ok=True)
config.CONFIG_PATH = config.BASE_DIR / 'config.json'
config.ENV_PATH = config.BASE_DIR / '.env'
import main
from modules import panel
cfg = copy.deepcopy(config.DEFAULT_CONFIG)
class FixedDatetime(datetime):
    @classmethod
    def now(cls, tz=None):
        return cls(2026,11,11,12,0,0,tzinfo=tz)
results = {}
for name in dir(panel):
    if not name.startswith(('generate_', 'get_wizard_', 'get_recurring_')):
        continue
    fn = getattr(panel, name)
    if not inspect.isfunction(fn): continue
    fn.__globals__['datetime'] = FixedDatetime
    values = dict(cfg=cfg, chat_title='Grupo de teste', chat_type='group', target_id=-100123,
                  msg_id=1, item_id=1, selected_hour=12, is_start=True, dest_label='Grupo',
                  text_preview='Teste', media_label='Texto', buttons_count=0, pin=False,
                  target='all', state={}, m={'id':1})
    kwargs={}
    for key, p in inspect.signature(fn).parameters.items():
        if key in values: kwargs[key]=copy.deepcopy(values[key])
        elif p.default is inspect.Parameter.empty: raise AssertionError((name,key))
    value=fn(**kwargs)
    def serialize(v):
        if hasattr(v,'to_dict'): return v.to_dict()
        raise TypeError(type(v).__name__)
    results[name]=json.loads(json.dumps(value,default=serialize,ensure_ascii=False))
h=panel.InteractivePanelHandler(admin_cache=None)
h._save_wizard_state(123, {'text':'teste','target':'all'}, 'wizard_text')
assert config.load_config()['_pending_inputs']['123']['text']=='teste'
h.pending_inputs.pop(123)
assert '123' not in config.load_config()['_pending_inputs']
from modules.inline_acervo import AcervoDatabase
db=AcervoDatabase(config.BASE_DIR/'test.db')
assert db.search('inexistente')==[]
assert db.clear_all()==0
assert db.add_item('arquivo_teste', -1001234567890, 1, file_name='Partitura Teste.pdf', title='Partitura Teste')
assert len(db.search('Partitura Teste'))==1
assert db.add_item('arquivo_atualizado', -1001234567890, 1, file_name='Partitura Teste.pdf', title='Partitura Teste')
assert len(db.search('Partitura Teste'))==1
assert db.clear_channel(-1001234567890)==1
assert db.search('Partitura Teste')==[]
for value, expected in [('10m',600),('1h 30m',5400),('nunca',0),('1s',None),('2d',None),('',None)]:
    assert panel.parse_time_string_to_seconds(value)==expected
import gc
gc.collect()
assert _scratch.resolve().parent == (root/"tests").resolve()
shutil.rmtree(_scratch)
print(f"OK: {len(results)} menus; imports; estado persistente; SQLite; duracoes.")
