# ============================================================================== 
# FILE: storage.py - Local filesystem storage for Paper Generator
# ==============================================================================

import base64
import os
import uuid
from pathlib import Path


def _upload_root():
    return Path(os.environ.get('UPLOAD_ROOT', 'uploads')).resolve()


def _ensure_folder(subfolder):
    folder = _upload_root() / subfolder
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def _safe_name(filename, fallback='file'):
    original_name = Path(filename or '').name
    stem = Path(original_name).stem or fallback
    suffix = Path(original_name).suffix
    return f'{stem}_{uuid.uuid4().hex}{suffix}'


def _store_bytes(file_bytes, filename, subfolder):
    if not file_bytes:
        return None
    folder = _ensure_folder(subfolder)
    safe_name = _safe_name(filename)
    full_path = folder / safe_name
    with open(full_path, 'wb') as file_handle:
        file_handle.write(file_bytes)
    return f'{subfolder}/{safe_name}'.replace('\\', '/')


def upload_file(file_storage, subfolder='misc', resource_type='auto'):
    """Store a Werkzeug FileStorage object locally and return a relative path."""
    if not file_storage:
        return None
    try:
        return _store_bytes(file_storage.read(), getattr(file_storage, 'filename', None), subfolder)
    except Exception as e:
        print(f'[LocalStorage] upload_file error: {e}')
        return None


def upload_base64(data_url, subfolder='signatures'):
    """Store a base64 data-URL string locally and return a relative path."""
    if not data_url:
        return None
    try:
        header, payload = data_url.split(',', 1)
        ext = 'png'
        if 'jpeg' in header:
            ext = 'jpg'
        elif 'gif' in header:
            ext = 'gif'
        filename = f'signature.{ext}'
        return _store_bytes(base64.b64decode(payload), filename, subfolder)
    except Exception as e:
        print(f'[LocalStorage] upload_base64 error: {e}')
        return None


def upload_bytes(file_bytes, filename, subfolder='misc', resource_type='auto'):
    """Store raw bytes locally and return a relative path."""
    try:
        return _store_bytes(file_bytes, filename, subfolder)
    except Exception as e:
        print(f'[LocalStorage] upload_bytes error: {e}')
        return None


def delete_file(public_id, resource_type='auto'):
    """Delete a locally stored file by its relative path."""
    try:
        if not public_id:
            return
        full_path = _upload_root() / str(public_id)
        if full_path.exists():
            full_path.unlink()
    except Exception as e:
        print(f'[LocalStorage] delete_file error: {e}')
