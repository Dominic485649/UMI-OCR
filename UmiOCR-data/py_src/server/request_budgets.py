"""进程内 HTTP 临时空间预算，失败也必须归还预留。"""
from ..utils.runtime_i18n import tr
import threading


class ByteBudget:
    def __init__(self, limit):
        self.limit = limit
        self.used = 0
        self._lock = threading.Lock()

    def take(self, count):
        if count < 0:
            raise ValueError(tr('预算计数不能为负数。'))
        with self._lock:
            if self.used + count > self.limit:
                raise ValueError(tr('HTTP 临时空间预算已满。'))
            self.used += count

    def release(self, count):
        with self._lock:
            self.used = max(0, self.used - count)
