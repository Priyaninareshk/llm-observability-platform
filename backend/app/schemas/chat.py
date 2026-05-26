from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    """API request schema for chat inference."""

    prompt: str = Field(..., min_length=1, description="User prompt text.")


class TokenUsagePayload(BaseModel):
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    model_name: str
    timestamp: str
    request_id: str
    trace_id: str


class CostPayload(BaseModel):
    prompt_cost: float
    completion_cost: float
    total_cost: float
    model_name: str
    pricing_found: bool


class LatencyPayload(BaseModel):
    total_ms: float
    llm_ms: float
    callback_ms: float
    middleware_ms: float


class ChatResponse(BaseModel):
    """API response schema with observability metadata."""

    response: str
    latency: LatencyPayload
    token_usage: TokenUsagePayload
    cost: CostPayload
    trace_id: str


class CostRecordPayload(BaseModel):
    timestamp: str
    trace_id: str
    request_id: str
    model_name: str
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    prompt_cost: float
    completion_cost: float
    total_cost: float
    pricing_found: bool


class CostReportPayload(BaseModel):
    total_requests: int
    total_cost_usd: float
    avg_cost_per_request_usd: float
    alert_threshold_usd: float
    by_model: dict[str, dict[str, float | int]]
    recent_records: list[CostRecordPayload]


class LangSmithStatusPayload(BaseModel):
    enabled: bool
    api_key_configured: bool
    project: str
