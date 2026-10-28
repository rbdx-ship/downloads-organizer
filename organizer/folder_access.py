"""Session-scoped permission for explicitly selected local folders."""
import ctypes
import os
from pathlib import Path
from . import config

_approved = {}


def is_test_folder(folder):
    try:
        config.validate_test_folder(folder)
        return True
    except (OSError, ValueError):
        return False


def validate_external_folder(folder):
    folder = config.validate_preview_folder(folder)
    if os.name != 'nt' or str(folder).startswith('\\\\'):
        raise ValueError('Writable external folders require a local Windows drive.')
    protected = [Path.home(), config.PROJECT, Path(folder.anchor)]
    protected_trees = [Path(os.environ[key]) for key in
                       ('WINDIR', 'ProgramFiles', 'ProgramFiles(x86)', 'PROGRAMDATA',
                        'LOCALAPPDATA', 'APPDATA', 'OneDrive', 'OneDriveConsumer', 'OneDriveCommercial')
                       if os.environ.get(key)]
    if (folder in protected or config.PROJECT.resolve().is_relative_to(folder)
            or Path.home().is_relative_to(folder)
            or any(folder == p.resolve() or folder.is_relative_to(p.resolve())
                                   for p in protected_trees)
            or folder.is_relative_to(config.PROJECT.resolve())
            or any(part.startswith('.') for part in folder.parts[1:])):
        raise ValueError('Choose a dedicated data folder outside system, application, cloud-sync, and hidden folders.')
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.GetDriveTypeW.argtypes = [ctypes.c_wchar_p]
    kernel.GetDriveTypeW.restype = ctypes.c_uint
    fs = ctypes.create_unicode_buffer(32)
    kernel.GetVolumeInformationW.argtypes = [ctypes.c_wchar_p, ctypes.c_wchar_p, ctypes.c_uint,
                                           ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p,
                                           ctypes.c_wchar_p, ctypes.c_uint]
    if (kernel.GetDriveTypeW(folder.anchor) != 3 or
            not kernel.GetVolumeInformationW(folder.anchor, None, 0, None, None, None, fs, len(fs))
            or fs.value != 'NTFS'):
        raise ValueError('Writable external folders currently require a fixed local NTFS drive.')
    return folder


def authorize_folder(folder):
    """Call only after the UI's explicit writable-folder confirmation."""
    folder = validate_external_folder(folder)
    st = folder.stat()
    _approved[str(folder)] = (st.st_dev, st.st_ino)
    return folder


def validate_operation_folder(folder):
    if is_test_folder(folder):
        return config.validate_test_folder(folder)
    folder = validate_external_folder(folder)
    st = folder.stat()
    if _approved.get(str(folder)) != (st.st_dev, st.st_ino):
        raise ValueError('Select and explicitly approve this folder for file changes first.')
    return folder
