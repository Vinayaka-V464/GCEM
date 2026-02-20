# ==============================================================================
# FILE: storage.py - Cloudinary File Storage for Paper Generator
# Replaces local disk uploads with permanent Cloudinary URLs
# ==============================================================================

import os
import cloudinary
import cloudinary.uploader
import cloudinary.api

# Configure Cloudinary from environment variables
cloudinary.config(
    cloud_name=os.environ.get('CLOUDINARY_CLOUD_NAME'),
    api_key=os.environ.get('CLOUDINARY_API_KEY'),
    api_secret=os.environ.get('CLOUDINARY_API_SECRET'),
    secure=True
)

# Root folder on Cloudinary for all uploads
_FOLDER = 'questgen'


def upload_file(file_storage, subfolder='misc', resource_type='auto'):
    """
    Upload a Werkzeug FileStorage object to Cloudinary.
    Returns the permanent public URL string, or None on failure.
    """
    try:
        result = cloudinary.uploader.upload(
            file_storage,
            folder=f'{_FOLDER}/{subfolder}',
            resource_type=resource_type,
            use_filename=True,
            unique_filename=True,
        )
        return result.get('secure_url')
    except Exception as e:
        print(f'[Cloudinary] upload_file error: {e}')
        return None


def upload_base64(data_url, subfolder='signatures'):
    """
    Upload a base64 data-URL string (e.g. a signature image) to Cloudinary.
    Returns the permanent public URL string, or None on failure.
    """
    if not data_url:
        return None
    try:
        result = cloudinary.uploader.upload(
            data_url,
            folder=f'{_FOLDER}/{subfolder}',
            resource_type='image',
        )
        return result.get('secure_url')
    except Exception as e:
        print(f'[Cloudinary] upload_base64 error: {e}')
        return None


def upload_bytes(file_bytes, filename, subfolder='misc', resource_type='auto'):
    """
    Upload raw bytes (e.g. a generated PDF) to Cloudinary.
    Returns the permanent public URL string, or None on failure.
    """
    if not file_bytes:
        return None
    try:
        result = cloudinary.uploader.upload(
            file_bytes,
            folder=f'{_FOLDER}/{subfolder}',
            public_id=filename,
            resource_type=resource_type,
            overwrite=True,
        )
        return result.get('secure_url')
    except Exception as e:
        print(f'[Cloudinary] upload_bytes error: {e}')
        return None


def delete_file(public_id, resource_type='auto'):
    """Delete a file from Cloudinary by its public_id."""
    try:
        cloudinary.uploader.destroy(public_id, resource_type=resource_type)
    except Exception as e:
        print(f'[Cloudinary] delete_file error: {e}')
