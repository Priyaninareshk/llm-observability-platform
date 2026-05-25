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
