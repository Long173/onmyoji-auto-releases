# uncompyle6 version 3.9.3
# Python bytecode version base 3.6 (3379)
# Decompiled from: Python 3.12.10 (tags/v3.12.10:0cc8128, Apr  8 2025, 12:21:36) [MSC v.1943 64 bit (AMD64)]
# Embedded file name: Util.py
# Compiled at: 2021-09-22 16:15:28
# Size of source mod 2**32: 30688 bytes
import sys, time, winsound, inspect, ctypes

def _asyncRaise(threadId, exctype):
    threadId = ctypes.c_long(threadId)
    if not inspect.isclass(exctype):
        exctype = type(exctype)
    res = ctypes.pythonapi.PyThreadState_SetAsyncExc(threadId, ctypes.py_object(exctype))
    if res == 0:
        raise ValueError("invalid thread id")
    elif res != 1:
        ctypes.pythonapi.PyThreadState_SetAsyncExc(threadId, None)
        raise SystemError("PyThreadState_SetAsyncExc failed")


def stopThread(thread):
    if thread.is_alive():
        _asyncRaise(thread.ident, SystemExit)


def getTimeFormatted():
    return time.strftime("[%Y-%m-%d %H:%M:%S]", time.localtime())


def printWithTime(*objects, sep=" ", end="\n", file=sys.stdout, flush=False):
    print((getTimeFormatted() + ":"), sep=" ", end="")
    print(*objects, sep=" ", end="\n", file=sys.stdout, flush=False)


def inputWithTimePrompt(prompt):
    return input(getTimeFormatted() + ":" + prompt)
