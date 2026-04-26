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
from breadmind.messenger.api.v1 import users  # noqa: E402
router.include_router(users.router)
from breadmind.messenger.api.v1 import user_groups  # noqa: E402
router.include_router(user_groups.router)
from breadmind.messenger.api.v1 import channels  # noqa: E402
router.include_router(channels.router)
from breadmind.messenger.api.v1 import channel_members  # noqa: E402
router.include_router(channel_members.router)
