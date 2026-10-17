from collections import defaultdict, deque
from datetime import UTC, datetime, timedelta

MODEL_PRICES_PER_MILLION = {
    "haiku": (1.0, 5.0),
    "sonnet": (3.0, 15.0),
    "opus": (15.0, 75.0),
}


class HourlyRateLimiter:
    def __init__(self, limit: int) -> None:
        self.limit = limit
        self._messages: dict[int, deque[datetime]] = defaultdict(deque)

    def allow(self, user_id: int, now: datetime | None = None) -> bool:
        current = now or datetime.now(UTC)
        cutoff = current - timedelta(hours=1)
        messages = self._messages[user_id]
        while messages and messages[0] <= cutoff:
            messages.popleft()
        if len(messages) >= self.limit:
            return False
        messages.append(current)
        return True


class DailyBudget:
    def __init__(self, limit_usd: float) -> None:
        self.limit_usd = limit_usd
        self.spent_usd = 0.0
        self._day = datetime.now(UTC).date()

    def available(self, now: datetime | None = None) -> bool:
        self._rollover(now)
        return self.spent_usd < self.limit_usd

    def add_usage(
        self,
        model: str,
        input_tokens: int,
        output_tokens: int,
        now: datetime | None = None,
    ) -> float:
        self._rollover(now)
        lowered = model.lower()
        input_price, output_price = next(
            (prices for family, prices in MODEL_PRICES_PER_MILLION.items() if family in lowered),
            MODEL_PRICES_PER_MILLION["sonnet"],
        )
        cost = (input_tokens * input_price + output_tokens * output_price) / 1_000_000
        self.spent_usd += cost
        return cost

    def _rollover(self, now: datetime | None) -> None:
        current_day = (now or datetime.now(UTC)).date()
        if current_day != self._day:
            self._day = current_day
            self.spent_usd = 0.0