# uncompyle6 version 3.9.3
# Python bytecode version base 3.6 (3379)
# Decompiled from: Python 3.12.10 (tags/v3.12.10:0cc8128, Apr  8 2025, 12:21:36) [MSC v.1943 64 bit (AMD64)]
# Embedded file name: ThreadGame.py
# Compiled at: 2021-09-22 16:15:28
# Size of source mod 2**32: 30688 bytes
import threading, time
_ThreadGameLocker = threading.Lock()
_isThreadGameLockerAcquired = False

class ThreadGame(object):

    def __init__(self):
        self._ThreadGame__lastOperationTime = time.time()

    def threadGameAcquire(self):
        global _ThreadGameLocker
        global _isThreadGameLockerAcquired
        _ThreadGameLocker.acquire()
        _isThreadGameLockerAcquired = True

    def threadGameRelease(self):
        global _isThreadGameLockerAcquired
        if _isThreadGameLockerAcquired:
            _ThreadGameLocker.release()
            _isThreadGameLockerAcquired = False

    def threadGameIsAcquired(self):
        return _isThreadGameLockerAcquired

    def threadGameTryToAcquire(self):
        if _isThreadGameLockerAcquired:
            return False
        else:
            self.threadGameAcquire()
            return True

    def updateOperationTime(self):
        self.threadGameAcquire()
        self._ThreadGame__lastOperationTime = time.time()
        self.threadGameRelease()
