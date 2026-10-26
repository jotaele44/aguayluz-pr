"""Runtime application with FOOD_SYSTEM_RESILIENCE registered.

The established canonical app remains unchanged; this wrapper adds the food-resilience
read-only router and is the desktop/E2E entrypoint for the feature branch.
"""
from server.backend.app import app
from server.backend.food_resilience_api import router as food_resilience_router

app.include_router(food_resilience_router)
