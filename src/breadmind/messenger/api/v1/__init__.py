from fastapi import APIRouter, Request
from fastapi.responses import Response

from breadmind.messenger.errors import MessengerError, error_to_response

router = APIRouter(prefix="/api/v1")


def install_exception_handlers(app):
    @app.exception_handler(MessengerError)
    async def _handle(_: Request, exc: MessengerError) -> Response:
        return error_to_response(exc)


# Register sub-routers
from breadmind.messenger.api.v1 import workspaces  # noqa: E402
router.include_router(workspaces.router)
