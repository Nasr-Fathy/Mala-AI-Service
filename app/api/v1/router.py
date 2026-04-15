from fastapi import APIRouter

from app.api.v1.endpoints import capture, health, mapping, pipeline

v1_router = APIRouter()

v1_router.include_router(health.router)
v1_router.include_router(capture.router)
v1_router.include_router(mapping.router)
v1_router.include_router(pipeline.router)
