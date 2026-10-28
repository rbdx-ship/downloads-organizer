"""Approximate classification durations; no filenames, credentials or storage."""
from dataclasses import dataclass
import math
import statistics

BATCH_SIZE = 10


def duration(seconds):
    seconds = max(0, math.ceil(seconds))
    if seconds < 60:
        return f'{seconds}s'
    minutes, seconds = divmod(seconds, 60)
    if minutes < 60:
        return f'{minutes}m {seconds}s' if seconds else f'{minutes}m'
    hours, minutes = divmod(minutes, 60)
    return f'{hours}h {minutes}m'


def time_range(low, high):
    return f'{duration(low)}–{duration(max(low, high))}'


def estimate(provider, unique_files, total_files, samples=()):
    """Fallback ranges are rough heuristics, not benchmark promises."""
    if not unique_files or provider == 'rules':
        return max(1, total_files * .002), max(2, total_files * .02)
    if samples:
        rate = statistics.median(samples)
        return max(1, rate * unique_files * .65), max(2, rate * unique_files * 1.6)
    batches = math.ceil(unique_files / BATCH_SIZE)
    if provider == 'ollama':
        return 8 * unique_files + 10 * batches, 30 * unique_files + 30 * batches
    return unique_files + 3 * batches, 5 * unique_files + 10 * batches


@dataclass
class RunTiming:
    total: int
    low: float
    high: float
    started: float
    completed: int = 0
    checkpoint: float = 0

    def observe(self, completed, now):
        self.completed = min(self.total, max(self.completed, completed))
        elapsed = max(.01, now - self.started)
        remaining = self.total - self.completed
        rate = elapsed / max(1, self.completed)
        self.low, self.high = rate * remaining * .65, rate * remaining * 1.6
        self.checkpoint = elapsed

    def text(self, now):
        elapsed = max(0, now - self.started)
        since = max(0, elapsed - self.checkpoint)
        if self.completed >= self.total:
            remaining = 'Finalizing results…'
        elif since >= self.high:
            remaining = 'Taking longer than estimated; still working…'
        else:
            remaining = 'Estimated remaining: ' + time_range(max(1, self.low - since), self.high - since)
        return f'{self.completed}/{self.total} AI files checked · Elapsed: {duration(elapsed)} · {remaining}'
