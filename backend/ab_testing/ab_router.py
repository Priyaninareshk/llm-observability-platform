"""FastAPI router for A/B model comparison endpoints."""
from typing import List, Optional

from fastapi import APIRouter, Query
from pydantic import BaseModel, Field

from ab_testing.ab_service import ab_testing_service

router = APIRouter(prefix="/ab", tags=["ab-testing"])


class ABCompareRequest(BaseModel):
    prompt: str = Field(..., description="Prompt to test against both models")
    control_model: str = Field("llama3-8b-8192", description="Control model name")
    treatment_model: str = Field("llama3-70b-8192", description="Treatment model name")
    experiment_name: str = Field("default", description="Experiment label for grouping")


@router.post("/compare", summary="Run parallel A/B model comparison")
async def run_ab_comparison(request: ABCompareRequest):
    """
    Runs the same prompt against control and treatment models in parallel,
    returns latency, cost, response, and a winner determination.
    """
    record = await ab_testing_service.run_comparison(
        prompt=request.prompt,
        control_model=request.control_model,
        treatment_model=request.treatment_model,
        experiment_name=request.experiment_name,
    )
    return record.compare()


@router.get("/experiments", summary="List all experiment names")
async def list_experiments():
    return {"experiments": ab_testing_service.list_experiments()}


@router.get("/experiments/{experiment_name}/summary", summary="Aggregated stats for an experiment")
async def get_experiment_summary(experiment_name: str):
    return ab_testing_service.get_experiment_summary(experiment_name)


@router.get("/history", summary="Recent A/B test records")
async def get_ab_history(
    limit: int = Query(50, ge=1, le=500),
    experiment_name: Optional[str] = Query(None),
):
    return {
        "count": limit,
        "records": ab_testing_service.get_history(limit=limit, experiment_name=experiment_name),
    }
