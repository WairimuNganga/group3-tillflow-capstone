from pos.api.internal import router as internal_router
from pos.api.sales import router as sales_router
from pos.api.tenants import router as tenants_router

__all__ = ["internal_router", "sales_router", "tenants_router"]
