"""Configure account-specific pytest temp and cache paths.

Use the process account on Windows because environment variables can identify
another account when inherited by a sandbox. Configure pytest without
--basetemp and with cache_dir = "$PYTEST_ACCOUNT_ROOT/cache".
"""

import ctypes
import getpass
import os
import re
import sys
import tempfile
from pathlib import Path

_PROJECT = Path(__file__).resolve().parent.name


def _process_account() -> str:
    """Return the process account, ignoring inherited USERNAME on Windows."""
    if sys.platform == "win32":
        size = ctypes.c_ulong(257)
        buf = ctypes.create_unicode_buffer(size.value)
        if ctypes.windll.advapi32.GetUserNameW(buf, ctypes.byref(size)):
            return buf.value
    return getpass.getuser()


_account = re.sub(r"[^\w.-]", "_", _process_account())
_root = Path(tempfile.gettempdir()) / f"{_PROJECT}-pytest-{_account}"
_root.mkdir(parents=True, exist_ok=True)

# Both are read after initial conftests load: PYTEST_DEBUG_TEMPROOT lazily by
# tmp_path_factory, PYTEST_ACCOUNT_ROOT when cache_dir is expanded. Overwrite
# on purpose: an inherited value is what makes the accounts collide.
os.environ["PYTEST_DEBUG_TEMPROOT"] = str(_root)
os.environ["PYTEST_ACCOUNT_ROOT"] = str(_root)
