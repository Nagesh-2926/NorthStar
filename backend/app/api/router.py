from fastapi import APIRouter
from backend.app.api.routes import (access_requests, analytics, auth, clusters, imports,
    interventions, predictions, students, study_plans)

api_router = APIRouter()
api_router.include_router(auth.router)
api_router.include_router(access_requests.router)
api_router.include_router(imports.router)
api_router.include_router(students.router)
api_router.include_router(students.enrollment_router)
api_router.include_router(predictions.router)
api_router.include_router(clusters.router)
api_router.include_router(clusters.student_router)
api_router.include_router(interventions.router)
api_router.include_router(study_plans.router)
api_router.include_router(analytics.router)
