"""Transação de arquivos com diário de reversão e recuperação antes de iniciar o bot."""
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sqlite3
import time
from uuid import uuid4
import zipfile

DATA_FILES=('config.json','.config_backup.json','acervo_partituras.db','agendamentos.db')
JOURNAL='.restore_journal.json'


def cleanup_transaction(base,folder):
    base=Path(base).resolve();folder=Path(folder).resolve()
    if folder.parent!=(base/'.restore-transactions').resolve() or not re.fullmatch('[0-9a-f]{32}',folder.name):
        raise ValueError('Diretório de transação inválido.')
    if folder.exists():shutil.rmtree(folder)


def sha(path):
    digest=hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda:stream.read(1024*1024),b''):
            digest.update(chunk)
    return digest.hexdigest()


def atomic_copy(source,target):
    target=Path(target);temp=target.with_name('.'+target.name+'.'+uuid4().hex+'.restoretmp')
    try:
        with Path(source).open('rb') as reader,temp.open('xb') as writer:
            shutil.copyfileobj(reader,writer,1024*1024)
            writer.flush();os.fsync(writer.fileno())
        os.replace(temp,target)
    finally:
        temp.unlink(missing_ok=True)


def write_marker(path,value):
    path=Path(path);temp=path.with_name(path.name+'.'+uuid4().hex+'.tmp')
    try:
        with temp.open('x',encoding='utf-8') as stream:
            json.dump(value,stream);stream.flush();os.fsync(stream.fileno())
        os.replace(temp,path)
    finally:
        temp.unlink(missing_ok=True)


def snapshot(source,target):
    """Banco consistente quando legível; arquivo bruto preservado se já estiver corrompido."""
    source=Path(source);target=Path(target)
    if source.suffix!='.db':
        shutil.copyfile(source,target);return
    first=second=None
    try:
        first=sqlite3.connect(source,timeout=10)
        second=sqlite3.connect(target)
        first.backup(second)
    except sqlite3.DatabaseError:
        if second:second.close();second=None
        if first:first.close();first=None
        target.unlink(missing_ok=True)
        shutil.copyfile(source,target)
    finally:
        if second:second.close()
        if first:first.close()


def recover_interrupted_restore(base):
    """Reverte o diário ativo; nunca usa caminhos recebidos em um ZIP."""
    base=Path(base).resolve();journal=base/JOURNAL
    if not journal.exists():return False
    plan=json.loads(journal.read_text(encoding='utf-8'))
    identifier=plan.get('id','')
    if not re.fullmatch('[0-9a-f]{32}',identifier):raise RuntimeError('Diário de recuperação inválido.')
    folder=(base/'.restore-transactions'/identifier).resolve()
    if folder.parent!=(base/'.restore-transactions').resolve():raise RuntimeError('Diretório de recuperação inválido.')
    entries=plan.get('files',[])
    if not entries or len(entries)>len(DATA_FILES):raise RuntimeError('Diário de recuperação inválido.')
    seen=set()
    for row in entries:
        name=row.get('name')
        if name not in DATA_FILES or name in seen:raise RuntimeError('Diário de recuperação inválido.')
        seen.add(name)
        if row['existed']:
            previous=folder/'previous'/name
            if not previous.is_file() or sha(previous)!=row['sha']:
                raise RuntimeError('A cópia anterior não passou na verificação; arquivos preservados.')
    for row in entries:
        target=base/row['name']
        if row['existed']:atomic_copy(folder/'previous'/row['name'],target)
        else:target.unlink(missing_ok=True)
    journal.unlink()
    try:cleanup_transaction(base,folder)
    except OSError:pass
    return True


def create_safety_backup(base):
    base=Path(base);folder=base/'backups';folder.mkdir(exist_ok=True)
    identifier=uuid4().hex
    staging=base/'.restore-transactions'/identifier/'safety'
    staging.mkdir(parents=True)
    destination=folder/f'antes_da_restauracao_{int(time.time())}_{identifier[:8]}.zip'
    try:
        with zipfile.ZipFile(destination,'x',zipfile.ZIP_DEFLATED) as archive:
            for name in DATA_FILES:
                source=base/name
                if source.exists():
                    snapshot(source,staging/name)
                    archive.write(staging/name,name)
            archive.writestr('MANIFESTO.txt','Cópia anterior à restauração. Arquivos existentes foram preservados; um banco previamente ilegível pode estar copiado em estado bruto.')
        with zipfile.ZipFile(destination) as archive:
            if archive.testzip() is not None:raise OSError('Falha na verificação da cópia anterior.')
    except Exception:
        destination.unlink(missing_ok=True);raise
    finally:
        try:cleanup_transaction(base,staging.parent)
        except OSError:pass
    return destination


def apply_transaction(base,replacements):
    base=Path(base).resolve()
    if (base/JOURNAL).exists():raise RuntimeError('Já existe restauração aguardando recuperação.')
    if not replacements or set(replacements)-set(DATA_FILES):raise ValueError('Arquivos não permitidos.')
    identifier=uuid4().hex;folder=base/'.restore-transactions'/identifier
    (folder/'previous').mkdir(parents=True);(folder/'new').mkdir()
    entries=[]
    for name,source in replacements.items():
        target=base/name;existed=target.exists()
        previous=folder/'previous'/name
        if existed:snapshot(target,previous)
        shutil.copyfile(source,folder/'new'/name)
        entries.append(dict(name=name,existed=existed,sha=sha(previous) if existed else None))
    write_marker(base/JOURNAL,dict(id=identifier,files=entries))
    try:
        for row in entries:
            os.replace(folder/'new'/row['name'],base/row['name'])
    except Exception:
        recover_interrupted_restore(base)
        raise
    # O desaparecimento do diário é o ponto de conclusão da transação.
    (base/JOURNAL).unlink()
    return folder
