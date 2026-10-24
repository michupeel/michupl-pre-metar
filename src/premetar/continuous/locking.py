"""Single-writer guard with OS-held lock and conservative crash recovery."""

import json
import os
from pathlib import Path
from typing import TextIO


def alive(pid: int) -> bool:
    if pid <= 0:
        return True
    if os.name == "nt":
        import ctypes

        handle = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)
        if not handle:
            return bool(ctypes.windll.kernel32.GetLastError() != 87)
        code = ctypes.c_ulong()
        try:
            return (
                not ctypes.windll.kernel32.GetExitCodeProcess(handle, ctypes.byref(code))
                or code.value == 259
            )
        finally:
            ctypes.windll.kernel32.CloseHandle(handle)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def acquire(path: Path, run_id: str, recover: bool = False) -> TextIO:
    try:
        handle = path.open("x+", encoding="utf-8")
        handle.write(" ")
        handle.flush()
    except FileExistsError:
        if not recover:
            raise
        handle = path.open("r+", encoding="utf-8")
        try:
            handle.seek(1)
            info = json.loads(handle.read())
            if info.get("owner") != "michupl-pre-metar" or alive(int(info["pid"])):
                raise FileExistsError("Collector lock held or unverified")
        except (OSError, ValueError, KeyError, TypeError):
            handle.close()
            raise FileExistsError("Unknown lock; manual inspection required") from None
        except BaseException:
            handle.close()
            raise
    try:
        handle.seek(0)
        if os.name == "nt":
            import msvcrt

            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import importlib

            fcntl = importlib.import_module("fcntl")
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        handle.seek(1)
        handle.truncate()
        json.dump(dict(owner="michupl-pre-metar", pid=os.getpid(), run_id=run_id), handle)
        handle.flush()
        return handle
    except OSError:
        handle.close()
        raise FileExistsError("Collector already owns OS lock") from None
