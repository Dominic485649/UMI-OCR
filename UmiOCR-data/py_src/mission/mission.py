# ==============================================
# =============== 任务管理器 基类 ===============
# ==============================================


from PySide6.QtCore import QMutex, QRunnable
from threading import Condition
from uuid import uuid4  # 唯一ID
import time

from umi_log import logger
from ..utils.thread_pool import threadRun  # 异步执行函数


class Mission:
    def __init__(self):
        self._deferAdmissions = False
        self._deferredMissions = {}
        self._msnInfoDict = {}  # 任务信息的字典
        self._msnListDict = {}  # 任务队列的字典
        self._msnPausedDict = {}  # 已暂停的任务队列
        self._msnMutex = QMutex()  # 任务队列的锁
        self._task = None  # 异步任务对象
        self._taskMutex = QMutex()  # 任务对象的锁
        # 任务队列调度方式
        # 1111 : 轮询调度，轮流取每个队列的第1个任务
        # 1234 : 顺序调度，将首个队列所有任务处理完，再进入下一个队列
        self._schedulingMode = "1111"

    # ========================= 【调用接口】 =========================

    """
    添加任务队列的格式
    mission = {
        "onStart": 任务队列开始回调函数 , (msnInfo)
        "onReady": 一项任务准备开始 , (msnInfo, msn)
        "onGet": 一项任务获取结果 , (msnInfo, msn, res)
        "onEnd": 任务队列结束 , (msnInfo, msg) // msg可选前缀： [Success] [Warning] [Error]
    }
    MissionOCR.addMissionList(mission, paths)
    """

    # 【异步】添加一条任务队列。成功返回任务ID，失败返回 startswith("[Error]")
    # msnInfo: { 回调函数 "onStart", "onReady", "onGet", "onEnd"}
    # msnList: [ 任务1, 任务2 ]
    def addMissionList(self, msnInfo, msnList):
        if len(msnList) < 1:
            return "[Error] no valid mission in msnList!"
        msnID = msnInfo.pop("_reserved_msnID", None) or str(uuid4())
        # 检查并补充回调函数
        # 队列开始，单个任务准备开始，单任务取得结果，队列结束
        cbKeys = ["onStart", "onReady", "onGet", "onEnd"]
        for k in cbKeys:
            if k not in msnInfo or not callable(msnInfo[k]):
                msnInfo[k] = lambda *e: None
        # 任务状态state:  waiting 等待开始， running 进行中， stop 要求停止
        msnInfo["state"] = "waiting"
        msnInfo["msnID"] = msnID
        # 添加到任务队列
        self._msnMutex.lock()
        deferred = self._deferAdmissions
        if deferred:
            msnInfo["_reserved_msnID"] = msnID
            self._deferredMissions[msnID] = (msnInfo, msnList)
        else:
            self._msnInfoDict[msnID] = msnInfo
            self._msnListDict[msnID] = msnList
        self._msnMutex.unlock()
        if deferred:
            return msnID
        # 启动任务
        self._startMsns()
        # 返回任务id
        return msnID

    def deferAdmissions(self, enabled):
        self._msnMutex.lock()
        self._deferAdmissions = bool(enabled)
        pending = {}
        if not enabled:
            pending, self._deferredMissions = self._deferredMissions, {}
        self._msnMutex.unlock()
        for info, items in pending.values():
            self.addMissionList(info, items)
        return "[Success]"

    # 停止一些任务队列
    def stopMissionList(self, msnIDs):
        if not isinstance(msnIDs, list):
            msnIDs = [msnIDs]
        self._msnMutex.lock()  # 上锁
        cancelled = []
        for msnID in msnIDs:
            pending = self._deferredMissions.pop(msnID, None)
            if pending:
                info, _ = pending
                cancelled.append(info)
            # 将暂停中的任务恢复
            if msnID in self._msnPausedDict:
                info, list_ = self._msnPausedDict[msnID]
                self._msnInfoDict[msnID] = info
                self._msnListDict[msnID] = list_
            # 将进行中的任务置为停止状态
            if msnID in self._msnListDict:
                self._msnInfoDict[msnID]["state"] = "stop"  # 设为停止状态
        self._msnMutex.unlock()  # 解锁
        for info in cancelled:
            self._callMissionEnd(info, "[Warning] Task stop.")
        self._startMsns()  # 拉起工作线程，使已暂停的任务可以正常结束

    # 停止全部任务
    def stopAllMissions(self):
        self._msnMutex.lock()
        pending, self._deferredMissions = self._deferredMissions, {}
        # 将暂停中的任务恢复
        for msnID in self._msnPausedDict:
            info, list_ = self._msnPausedDict[msnID]
            self._msnInfoDict[msnID] = info
            self._msnListDict[msnID] = list_
        # 将进行中的任务置为停止状态
        for msnID in self._msnListDict:
            self._msnInfoDict[msnID]["state"] = "stop"
        self._msnMutex.unlock()  # 解锁
        for info, _ in pending.values():
            self._callMissionEnd(info, "[Warning] Task stop.")
        self._startMsns()

    # 暂停一些任务队列
    def pauseMissionList(self, msnIDs):
        if not isinstance(msnIDs, list):
            msnIDs = [msnIDs]
        self._msnMutex.lock()  # 上锁
        for msnID in msnIDs:
            if msnID in self._msnListDict:
                msn = (self._msnInfoDict[msnID], self._msnListDict[msnID])
                self._msnPausedDict[msnID] = msn
                del self._msnInfoDict[msnID]
                del self._msnListDict[msnID]
        self._msnMutex.unlock()  # 解锁
        logger.debug(f"任务暂停： {msnID}")

    # 恢复一些任务队列的运行
    def resumeMissionList(self, msnIDs):
        if not isinstance(msnIDs, list):
            msnIDs = [msnIDs]
        self._msnMutex.lock()  # 上锁
        for msnID in msnIDs:
            if msnID in self._msnPausedDict:
                info, list_ = self._msnPausedDict[msnID]
                self._msnInfoDict[msnID] = info
                self._msnListDict[msnID] = list_
                del self._msnPausedDict[msnID]
        self._msnMutex.unlock()  # 解锁
        self._startMsns()  # 拉起工作线程
        logger.debug(f"任务恢复： {msnID}")

    # 获取每一条任务队列长度
    def getMissionListsLength(self):
        lenDict = {}
        self._msnMutex.lock()
        for k in self._msnListDict:
            lenDict[str(k)] = len(self._msnListDict[k])
        for key, (_, items) in self._msnPausedDict.items():
            lenDict[str(key)] = len(items)
        self._msnMutex.unlock()
        return lenDict

    # 【同步】添加一个任务或队列，等待完成，返回任务结果列表。[i]["result"]为结果
    def addMissionWait(self, argd, msnList):
        if not isinstance(msnList, list):
            msnList = [msnList]
        resList = msnList[:]  # 浅拷贝出一条结果列表
        nowIndex = 0  # 当前处理的任务
        msnLen = len(msnList)
        condition = Condition()  # 线程同步器
        endMsg = ""  # 任务结束的消息
        finished = False  # 完成谓词，避免任务过快结束时丢失 notify

        def _onGet(msnInfo, msn, res):
            nonlocal nowIndex
            resList[nowIndex]["result"] = res
            nowIndex += 1

        def _onEnd(msnInfo, msg):
            nonlocal endMsg, finished
            endMsg = msg
            with condition:  # 释放线程阻塞
                finished = True
                condition.notify()

        def _pass(*x):
            pass

        msnInfo = {
            "onStart": _pass,
            "onReady": _pass,
            "onGet": _onGet,
            "onEnd": _onEnd,
            "argd": argd,
        }
        msnID = self.addMissionList(msnInfo, msnList)
        if msnID.startswith("[Error]"):  # 添加任务失败
            endMsg = msnID
        else:  # 添加成功，线程阻塞，直到任务完成。
            with condition:
                while not finished:
                    condition.wait()
        # 补充未完成的任务
        for i in range(nowIndex, msnLen):
            if "result" not in resList[i]:
                resList[i]["result"] = {"code": 803, "data": f"任务提前结束。{endMsg}"}
        return resList

    # ========================= 【主线程 方法】 =========================

    def _startMsns(self):  # 启动异步任务，执行所有任务列表
        # 若当前异步任务对象为空，则创建工作线程
        self._taskMutex.lock()  # 上锁
        if self._task == None:
            self._task = threadRun(self._taskRun)
        self._taskMutex.unlock()  # 解锁

    # ========================= 【子线程 方法】 =========================

    def _taskRun(self):  # 异步执行任务字典的流程
        try:
            self._runMissionQueues()
        except Exception as exc:
            # Plugin preparation/inference and result callbacks run outside the
            # queue mutex.  A failure must end the affected queue and release
            # the worker slot, otherwise synchronous HTTP/CLI callers wait
            # forever and subsequent admissions cannot start another worker.
            logger.error("任务执行异常。", exc_info=True)
            active_id = getattr(self, "_activeMsnID", None)
            self._msnMutex.lock()
            try:
                info = self._msnInfoDict.get(active_id)
                if info is None:
                    paused = self._msnPausedDict.get(active_id)
                    info = paused[0] if paused else None
                self._msnDictDel(active_id)
            finally:
                self._msnMutex.unlock()
            if info is not None:
                self._callMissionEnd(info, f"[Error] Task failed: {exc}")
        finally:
            self._taskFinish()

    def _runMissionQueues(self):
        dictIndex = 0  # 当前取任务字典中的第几个任务队列
        # 循环，直到任务队列的列表为空
        while True:
            # 1. 检查api和任务字典是否为空
            self._msnMutex.lock()  # 锁1 上锁
            dl = len(self._msnInfoDict)  # 任务字典长度
            if dl == 0:  # 任务字典已空
                self._msnMutex.unlock()  # 锁1 解锁
                break

            # 2. 任务调度，取一个任务
            if self._schedulingMode == "1111":  # 轮询
                dictIndex = (dictIndex + 1) % dl
            elif self._schedulingMode == "1234":  # 顺序
                dictIndex = 0  # 始终为首个队列
            dictKey = tuple(self._msnInfoDict.keys())[dictIndex]
            msnInfo = self._msnInfoDict[dictKey]
            msnList = self._msnListDict[dictKey]
            self._activeMsnID = dictKey
            self._msnMutex.unlock()  # 锁1 解锁

            # 3. 检查任务是否要求停止
            if msnInfo["state"] == "stop":
                self._msnMutex.lock()
                self._msnDictDel(dictKey)
                self._msnMutex.unlock()
                self._callMissionEnd(msnInfo, "[Warning] Task stop.")
                continue

            # 4. 前处理，检查、更新参数
            preFlag = self.msnPreTask(msnInfo)
            if preFlag == "continue":  # 跳过本次
                logger.debug(f"任务跳过： {dictKey}")
                continue
            elif preFlag.startswith("[Error]"):  # 异常，结束该队列
                self._msnMutex.lock()
                self._msnDictDel(dictKey)
                self._msnMutex.unlock()
                self._callMissionEnd(msnInfo, preFlag)
                dictIndex -= 1  # 字典下标回退1位，下次执行正确的下一项
                continue

            if msnInfo["state"] == "stop":
                self._msnMutex.lock()
                self._msnDictDel(dictKey)
                self._msnMutex.unlock()
                self._callMissionEnd(msnInfo, "[Warning] Task stop.")
                continue

            # 5. 首次任务
            if msnInfo["state"] == "waiting":
                msnInfo["state"] = "running"
                msnInfo["onStart"](msnInfo)

            # 6. 执行任务，并记录时间
            msn = msnList[0]
            msnInfo["onReady"](msnInfo, msn)
            t1 = time.time()
            res = self.msnTask(msnInfo, msn)
            t2 = time.time()
            if isinstance(res, dict):  # 补充耗时和时间戳
                res["time"] = t2 - t1
                res["timestamp"] = t2

            # 7. 再次检查任务是否要求停止，或者已暂停
            self._msnMutex.lock()  # 锁2 上锁
            if msnInfo["state"] == "stop":
                self._msnDictDel(dictKey)
                self._msnMutex.unlock()  # 锁2 解锁
                self._callMissionEnd(msnInfo, "[Warning] Task stop.")
                continue
            if dictKey not in self._msnInfoDict:
                self._msnMutex.unlock()  # 锁2 解锁
                continue

            # 8. 不停止，则上报该任务
            msnList.pop(0)  # 弹出该任务
            self._msnMutex.unlock()  # 锁2 解锁
            # 回调。注意：回调函数执行时间长时，可能用户再次提交了任务暂停，需要后续继续判断。
            msnInfo["onGet"](msnInfo, msn, res)

            # 9. 这条任务队列完成
            if len(msnList) == 0:
                self._msnMutex.lock()  # 锁3 上锁
                self._msnDictDel(dictKey)
                self._msnMutex.unlock()  # 锁3 解锁
                self._callMissionEnd(msnInfo, "[Success]")
                dictIndex -= 1  # 字典下标回退1位，下次执行正确的下一项

    def _msnDictDel(self, dictKey):  # 停止一组任务队列
        # 正常 删除任务队列项
        if dictKey in self._msnInfoDict:
            del self._msnInfoDict[dictKey]
            del self._msnListDict[dictKey]
        # 如果该任务在暂停中，则移除暂停队列中的项
        if dictKey in self._msnPausedDict:
            del self._msnPausedDict[dictKey]
            logger.debug(f"移除暂停任务： {dictKey}")

    def _callMissionEnd(self, info, message):
        try:
            info["onEnd"](info, message)
        except Exception:
            # End callbacks are notifications, not another inference stage.
            # Do not retry a callback with side effects or strand other queues.
            logger.error("任务结束回调异常。", exc_info=True)

    def _taskFinish(self):  # 任务结束
        self._taskMutex.lock()  # 上锁
        self._task = None
        # A new queue can arrive after _taskRun observes an empty dictionary
        # but before this worker releases its task slot.  Its _startMsns then
        # sees the old task and does not schedule a replacement.  Recheck here
        # so that admission cannot leave work waiting until an unrelated call.
        self._msnMutex.lock()
        pending = bool(self._msnInfoDict)
        self._msnMutex.unlock()
        self._taskMutex.unlock()  # 解锁
        if pending:
            self._startMsns()

    # ========================= 【继承重载】 =========================

    def msnPreTask(self, msnInfo):  # 任务前处理，用于更新api和参数。
        """返回值可选：
        "" ：空字符串表示正常继续。
        "continue" ：跳过本次任务
        "[Error] xxxx" ：终止这条任务队列，返回异常信息
        """
        # return "[Error] No overloaded msnPreTask. \n【异常】未重载msnPreTask。"
        return ""

    def msnTask(self, msnInfo, msn):  # 执行任务msn，返回结果字典。
        logger.debug("mission 未重载 msnTask")
        return {"error": "[Error] No overloaded msnTask. \n【异常】未重载msnTask。"}

    def getStatus(self):  # 返回当前状态
        return "Mission 基类 返回空状态"
