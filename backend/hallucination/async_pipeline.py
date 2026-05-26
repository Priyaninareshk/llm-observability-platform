import asyncio
import logging
from dataclasses import dataclass
from typing import Optional, Dict, Any, Callable, Awaitable, List
from datetime import datetime, timezone

from hallucination.faithfulness_scorer import faithfulness_scorer, FaithfulnessResult

logger = logging.getLogger("llm_observability.hallucination.async")


@dataclass
class ScoringJob:
    trace_id: str
    query: str
    response: str
    context: str
    metadata: Optional[Dict[str, Any]] = None
    submitted_at: str = ""

    def __post_init__(self):
        if not self.submitted_at:
            self.submitted_at = datetime.now(timezone.utc).isoformat()


# Result callback type: async fn(result: FaithfulnessResult) -> None
ResultCallback = Callable[[FaithfulnessResult], Awaitable[None]]


class AsyncHallucinationPipeline:
    """
    Background worker that drains a queue of ScoringJobs.

    Usage
    -----
    pipeline = AsyncHallucinationPipeline(max_workers=2)
    await pipeline.start()                        # call once at app startup
    await pipeline.submit(job)                    # non-blocking
    await pipeline.shutdown()                     # call at app shutdown
    pipeline.register_callback(my_async_fn)       # optional result hook
    """

    def __init__(self, max_workers: int = 2, queue_maxsize: int = 500):
        self.max_workers = max_workers
        self._queue: asyncio.Queue[ScoringJob] = asyncio.Queue(maxsize=queue_maxsize)
        self._workers: List[asyncio.Task] = []
        self._callbacks: List[ResultCallback] = []
        self._results: List[Dict[str, Any]] = []   # in-memory store (last 1000)
        self._running = False

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Start background worker tasks."""
        if self._running:
            return
        self._running = True
        self._workers = [
            asyncio.create_task(self._worker(worker_id=i))
            for i in range(self.max_workers)
        ]
        logger.info("AsyncHallucinationPipeline started with %d workers", self.max_workers)

    async def shutdown(self, timeout: float = 10.0) -> None:
        """Drain the queue and stop workers."""
        self._running = False
        try:
            await asyncio.wait_for(self._queue.join(), timeout=timeout)
        except asyncio.TimeoutError:
            logger.warning("Hallucination pipeline shutdown timed out – remaining jobs dropped.")
        for w in self._workers:
            w.cancel()
        await asyncio.gather(*self._workers, return_exceptions=True)
        logger.info("AsyncHallucinationPipeline shut down.")

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def submit(self, job: ScoringJob) -> bool:
        """
        Enqueue a scoring job. Returns True if accepted, False if queue full.
        Never blocks the caller.
        """
        try:
            self._queue.put_nowait(job)
            logger.debug("Hallucination job queued: trace_id=%s", job.trace_id)
            return True
        except asyncio.QueueFull:
            logger.warning("Hallucination queue full – dropping job trace_id=%s", job.trace_id)
            return False

    def register_callback(self, fn: ResultCallback) -> None:
        """Register an async callback to receive FaithfulnessResult objects."""
        self._callbacks.append(fn)

    def get_recent_results(self, limit: int = 100) -> List[Dict[str, Any]]:
        return self._results[-limit:]

    # ------------------------------------------------------------------
    # Worker
    # ------------------------------------------------------------------

    async def _worker(self, worker_id: int) -> None:
        logger.debug("Hallucination worker-%d starting", worker_id)
        while True:
            try:
                job: ScoringJob = await self._queue.get()
            except asyncio.CancelledError:
                break

            try:
                # Run CPU-bound NLI scoring in a thread pool
                loop = asyncio.get_event_loop()
                result: FaithfulnessResult = await loop.run_in_executor(
                    None,
                    lambda j=job: faithfulness_scorer.score(
                        trace_id=j.trace_id,
                        query=j.query,
                        response=j.response,
                        context=j.context,
                        metadata=j.metadata,
                    ),
                )

                logger.info(
                    "hallucination.async.scored worker=%d trace_id=%s score=%.3f label=%s",
                    worker_id,
                    result.trace_id,
                    result.faithfulness_score,
                    result.label,
                )

                # Store result (capped at 1000)
                self._results.append(result.to_dict())
                if len(self._results) > 1000:
                    self._results.pop(0)

                # Fire callbacks
                for cb in self._callbacks:
                    try:
                        await cb(result)
                    except Exception as cb_exc:
                        logger.warning("Hallucination callback error: %s", cb_exc)

            except Exception as exc:
                logger.error("Hallucination worker-%d error: %s", worker_id, exc, exc_info=True)
            finally:
                self._queue.task_done()


# Singleton
hallucination_pipeline = AsyncHallucinationPipeline(max_workers=2)
