import os
from distutils import util as dutils
from typing import List
from typing import Optional

__CFG = dict()


__CFG = dict()


def set_config(key, value):
    global __CFG
    __CFG[key] = value


def get_config(key, default=None):
    global __CFG
    return __CFG.get(key) if key in __CFG else os.environ.get(key, default)


def get_config_as_list(key, default: Optional[List] = []):
    global __CFG
    return (
        __CFG.get(key)
        if key in __CFG
        else os.environ.get(key).split(",")
        if key in os.environ
        else default
    )


def get_config_as_int(key, default=None):
    return int(get_config(key, default))


def get_config_as_bool(key, default=None):
    return dutils.strtobool(str(get_config(key, default))) == 1


def log_level() -> str:
    return get_config("LOG_LEVEL", os.environ.get("LOG_LEVEL", "INFO")).upper()
