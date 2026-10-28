"""No-overwrite Windows rename using a locked, verified source handle.

External folders use this instead of the legacy test-folder hard-link workflow.
Directory handles deny deletion/renaming while the operation is in progress.
"""
from contextlib import contextmanager, ExitStack
import ctypes
from ctypes import wintypes as wt
import hashlib
import msvcrt
import os
from pathlib import Path


def kernel():
    dll = ctypes.WinDLL('kernel32', use_last_error=True)
    dll.CreateFileW.argtypes = [wt.LPCWSTR, wt.DWORD, wt.DWORD, wt.LPVOID, wt.DWORD, wt.DWORD, wt.HANDLE]
    dll.CreateFileW.restype = wt.HANDLE
    dll.CloseHandle.argtypes = [wt.HANDLE]
    dll.GetFinalPathNameByHandleW.argtypes = [wt.HANDLE, wt.LPWSTR, wt.DWORD, wt.DWORD]
    dll.GetFinalPathNameByHandleW.restype = wt.DWORD
    dll.SetFileInformationByHandle.argtypes = [wt.HANDLE, ctypes.c_int, wt.LPVOID, wt.DWORD]
    dll.SetFileInformationByHandle.restype = wt.BOOL
    return dll


def opened_path(dll, handle):
    buf = ctypes.create_unicode_buffer(32768)
    length = dll.GetFinalPathNameByHandleW(handle, buf, len(buf), 0)
    if not length or length >= len(buf):
        raise ctypes.WinError(ctypes.get_last_error())
    return Path(buf.value.removeprefix('\\\\?\\'))


@contextmanager
def lock_directory(path):
    dll = kernel()
    handle = dll.CreateFileW(str(path), 0, 3, None, 3, 0x02000000 | 0x00200000, None)
    if handle == wt.HANDLE(-1).value:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        st = path.stat(follow_symlinks=False)
        if st.st_file_attributes & 0x400 or opened_path(dll, handle) != path:
            raise OSError('Linked or replaced directory blocked.')
        yield
    finally:
        dll.CloseHandle(handle)


def _rename(dll, handle, destination):
    class RenameInfo(ctypes.Structure):
        _fields_ = [('flags', wt.DWORD), ('root', wt.HANDLE),
                    ('length', wt.DWORD), ('name', wt.WCHAR * 1)]
    encoded = str(destination).encode('utf-16-le')
    size = RenameInfo.name.offset + len(encoded)
    # Keep a trailing UTF-16 NUL as required by the Win32 FILE_RENAME_INFO contract;
    # FileNameLength counts only the actual filename bytes.
    buffer = ctypes.create_string_buffer(max(size + 2, ctypes.sizeof(RenameInfo)))
    info = RenameInfo.from_buffer(buffer)
    info.flags, info.root, info.length = 0, None, len(encoded)
    ctypes.memmove(ctypes.addressof(buffer) + RenameInfo.name.offset, encoded, len(encoded))
    if not dll.SetFileInformationByHandle(handle, 3, buffer, len(buffer)):
        raise ctypes.WinError(ctypes.get_last_error())


def move_verified(source, destination, root, digest, identity=None):
    """Rename exactly the locked file, with no replace flag and no copy fallback."""
    from .folder_access import validate_operation_folder
    from .file_manager import valid_filename, safe_destination, existing_path_casefold
    source, destination, root = Path(source), Path(destination), Path(root)
    if (not valid_filename(destination.name, source.name) or
            not safe_destination(source, root, (source.parent.name,)) or
            not safe_destination(destination, root, (destination.parent.name,))):
        raise OSError('Unsafe move paths.')
    dll = kernel()
    with ExitStack() as stack:
        # Lock ancestors from the volume root downward before trusting descendants.
        directories = list(reversed(root.parents)) + [root]
        for directory in directories:
            stack.enter_context(lock_directory(directory))
        validate_operation_folder(root)
        destination.parent.mkdir(exist_ok=True)
        for parent in {source.parent, destination.parent} - {root}:
            stack.enter_context(lock_directory(parent))
        handle = dll.CreateFileW(str(source), 0x80000000 | 0x00010000, 1,
                                 None, 3, 0x00200000, None)
        if handle == wt.HANDLE(-1).value:
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            fd = msvcrt.open_osfhandle(handle, os.O_RDONLY | os.O_BINARY)
        except Exception:
            dll.CloseHandle(handle)
            raise
        with os.fdopen(fd, 'rb') as stream:
            st = os.fstat(stream.fileno())
            if (st.st_file_attributes & 0x400 or st.st_nlink != 1 or
                    opened_path(dll, handle) != source):
                raise OSError('Source is linked, replaced, or shared through hard links.')
            if identity and (st.st_dev, st.st_ino, st.st_size, st.st_mtime_ns) != tuple(identity):
                raise OSError('Source identity changed after preview.')
            if hashlib.file_digest(stream, 'sha256').hexdigest() != digest:
                raise OSError('Source content changed after preview.')
            if existing_path_casefold(destination.parent, destination.name) is not None:
                raise FileExistsError('Destination already exists.')
            _rename(dll, handle, destination)
