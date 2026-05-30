from collections import deque


class PerformanceService:
    _search_samples = deque(maxlen=5000)

    @classmethod
    def record_search(cls, timing):
        cls._search_samples.append(dict(timing))

    @classmethod
    def search_stats(cls):
        samples = list(cls._search_samples)
        totals = sorted(float(sample.get("total_ms", sample.get("elapsed_ms", 0))) for sample in samples)
        if not totals:
            return {"count": 0, "average_ms": 0, "p95_ms": 0, "p99_ms": 0}
        return {
            "count": len(totals),
            "average_ms": round(sum(totals) / len(totals), 2),
            "p95_ms": round(cls._percentile(totals, 95), 2),
            "p99_ms": round(cls._percentile(totals, 99), 2),
        }

    @staticmethod
    def _percentile(values, percentile):
        if not values:
            return 0
        index = min(len(values) - 1, max(0, round((percentile / 100) * (len(values) - 1))))
        return values[index]
