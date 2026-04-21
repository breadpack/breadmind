"""Expose the prometheus_client default registry at /kb/metrics.

The legacy in-tree registry (breadmind.core.metrics) keeps serving /metrics for
back-compat. /kb/metrics serves the new spec §8.4 metric family produced by
breadmind.kb.metrics using the standard prometheus_client text encoder.
"""
from __future__ import annotations

from fastapi import APIRouter, Response
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

from breadmind.kb import metrics as kb_metrics

router = APIRouter()


@router.get("/kb/metrics", include_in_schema=False)
async def kb_metrics_endpoint() -> Response:
    body = generate_latest(kb_metrics.REGISTRY)
    return Response(content=body, media_type=CONTENT_TYPE_LATEST)
