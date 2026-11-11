"""Resources of numerical blocks, limited to a single simulation trial."""
import threading


class TrialResources:
    def __init__(self):
        self._lock = threading.RLock()
        self._blocks = []
        self._stopping = False
        self._closed = False

    def add(self, block):
        with self._lock:
            if self._closed:
                raise RuntimeError('Прогон уже завершён.')
            self._blocks.append(block)
            if self._stopping:
                block.request_stop()

    def request_stop(self):
        with self._lock:
            if self._stopping or self._closed:
                return
            self._stopping = True
            errors = []
            for block in self._blocks:
                try:
                    block.request_stop()
                except Exception as exc:
                    errors.append(str(exc))
            if errors:
                raise RuntimeError('Ошибка остановки внутренних блоков: ' + '; '.join(errors))

    def close(self):
        with self._lock:
            if self._closed:
                return
            self._closed = True
            blocks, self._blocks = self._blocks, []
            errors = []
            for block in blocks:
                try:
                    block.close_trial()
                except Exception as exc:
                    errors.append(str(exc))
            if errors:
                raise RuntimeError('Ошибка очистки внутренних блоков: ' + '; '.join(errors))
