"""Gravações JSON atômicas no mesmo volume do arquivo de destino."""
import json
import os
from pathlib import Path
from uuid import uuid4


def write_json_atomic(path: Path, payload: dict) -> None:
    """Uma falha antes de replace preserva o arquivo de destino completo."""
    path = Path(path)
    serialized = json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False)
    temporary = path.with_name(f'.{path.name}.{uuid4().hex}.tmp')
    try:
        with temporary.open('x', encoding='utf-8', newline='\n') as stream:
            stream.write(serialized)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def read_json_object(path: Path) -> dict:
    with Path(path).open(encoding='utf-8') as stream:
        payload = json.load(stream)
    if not isinstance(payload, dict):
        raise ValueError('A configuração precisa conter um objeto JSON.')
    return payload
