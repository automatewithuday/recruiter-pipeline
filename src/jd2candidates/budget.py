"""Per-run spend cap. add() raises before the cap would be crossed."""
import threading


class BudgetExceeded(RuntimeError):
    pass


class Budget:
    def __init__(self, cap_usd: float):
        self.cap = cap_usd
        self.spent = 0.0
        self._lock = threading.Lock()

    def add(self, usd: float) -> None:
        with self._lock:
            if self.spent + usd > self.cap + 1e-9:
                raise BudgetExceeded(f"budget {self.cap:.2f} USD reached (spent {self.spent:.4f})")
            self.spent += usd
