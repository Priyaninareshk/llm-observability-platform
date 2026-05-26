import logging
import re
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Optional, Dict, Any, List

logger = logging.getLogger("llm_observability.hallucination")


@dataclass
class FaithfulnessResult:
    trace_id: str
    query: str
    response: str
    context: str
    faithfulness_score: float          # 0.0 (hallucinated) – 1.0 (faithful)
    label: str                          # "faithful" | "uncertain" | "hallucinated"
    model_used: str
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    sentence_scores: List[Dict[str, Any]] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class NLIFaithfulnessScorer:
    """
    Scores LLM response faithfulness against a retrieved context using NLI.

    Pipeline:
      1. Split response into sentences.
      2. For each sentence, run NLI with the context as premise.
      3. Aggregate entailment scores → overall faithfulness.

    Thresholds
    ----------
    score >= 0.7  → faithful
    score >= 0.4  → uncertain
    score <  0.4  → hallucinated
    """

    FAITHFUL_THRESHOLD = 0.7
    UNCERTAIN_THRESHOLD = 0.4

    def __init__(self, model_name: str = "cross-encoder/nli-deberta-v3-small"):
        self.model_name = model_name
        self._pipeline = None
        self._load_model()

    def _load_model(self) -> None:
        try:
            from transformers import pipeline as hf_pipeline  # type: ignore
            self._pipeline = hf_pipeline(
                "text-classification",
                model=self.model_name,
                top_k=None,
            )
            logger.info("NLI model loaded: %s", self.model_name)
        except ImportError:
            logger.warning(
                "transformers not installed – using heuristic fallback scorer. "
                "Install with: pip install transformers torch"
            )
        except Exception as exc:
            logger.warning("Could not load NLI model (%s); using fallback. Error: %s", self.model_name, exc)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def score(
        self,
        trace_id: str,
        query: str,
        response: str,
        context: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> FaithfulnessResult:
        sentences = self._split_sentences(response)
        if not sentences:
            return self._build_result(trace_id, query, response, context, 1.0, [], metadata)

        if self._pipeline is not None:
            sentence_scores = self._score_with_nli(sentences, context)
        else:
            sentence_scores = self._score_heuristic(sentences, context)

        overall = sum(s["entailment"] for s in sentence_scores) / len(sentence_scores)
        result = self._build_result(trace_id, query, response, context, overall, sentence_scores, metadata)

        logger.info(
            "hallucination.score",
            extra={
                "trace_id": trace_id,
                "faithfulness_score": overall,
                "label": result.label,
                "sentence_count": len(sentences),
            },
        )
        return result

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _split_sentences(self, text: str) -> List[str]:
        sentences = re.split(r"(?<=[.!?])\s+", text.strip())
        return [s.strip() for s in sentences if len(s.strip()) > 10]

    def _score_with_nli(self, sentences: List[str], context: str) -> List[Dict[str, Any]]:
        results = []
        for sentence in sentences:
            try:
                outputs = self._pipeline(f"{context} [SEP] {sentence}")
                # outputs is a list of [{'label': ..., 'score': ...}, ...]
                scores_dict = {item["label"].lower(): item["score"] for item in outputs[0]}
                entailment = scores_dict.get("entailment", 0.0)
                contradiction = scores_dict.get("contradiction", 0.0)
                neutral = scores_dict.get("neutral", 0.0)
            except Exception as exc:
                logger.warning("NLI inference failed for sentence: %s", exc)
                entailment, contradiction, neutral = 0.5, 0.25, 0.25

            results.append({
                "sentence": sentence,
                "entailment": entailment,
                "contradiction": contradiction,
                "neutral": neutral,
            })
        return results

    def _score_heuristic(self, sentences: List[str], context: str) -> List[Dict[str, Any]]:
        """Keyword-overlap heuristic when the NLI model is unavailable."""
        context_words = set(re.findall(r"\b\w+\b", context.lower()))
        results = []
        for sentence in sentences:
            sent_words = set(re.findall(r"\b\w+\b", sentence.lower()))
            if not sent_words:
                overlap = 0.5
            else:
                overlap = len(sent_words & context_words) / len(sent_words)
            # Map overlap → pseudo-entailment (rough approximation)
            entailment = min(overlap * 1.5, 1.0)
            results.append({
                "sentence": sentence,
                "entailment": entailment,
                "contradiction": max(0.0, 0.5 - overlap),
                "neutral": 1.0 - entailment - max(0.0, 0.5 - overlap),
                "heuristic": True,
            })
        return results

    def _build_result(
        self,
        trace_id: str,
        query: str,
        response: str,
        context: str,
        score: float,
        sentence_scores: List[Dict[str, Any]],
        metadata: Optional[Dict[str, Any]],
    ) -> FaithfulnessResult:
        if score >= self.FAITHFUL_THRESHOLD:
            label = "faithful"
        elif score >= self.UNCERTAIN_THRESHOLD:
            label = "uncertain"
        else:
            label = "hallucinated"

        return FaithfulnessResult(
            trace_id=trace_id,
            query=query,
            response=response,
            context=context,
            faithfulness_score=round(score, 4),
            label=label,
            model_used=self.model_name if self._pipeline else "heuristic_fallback",
            sentence_scores=sentence_scores,
            metadata=metadata or {},
        )


# Singleton
faithfulness_scorer = NLIFaithfulnessScorer()
