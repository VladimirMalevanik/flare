"""Owner-authorized workspace export."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse

from app.api.auth import verified_user
from app.api.routes import _database
from app.models.database import Database, MembershipRequiredError
from app.services.auth_service import AuthenticatedUser
from app.services.export_service import WorkspaceExportService


router = APIRouter(tags=["export"])


def _owner(
    user: Annotated[AuthenticatedUser, Depends(verified_user)],
) -> AuthenticatedUser:
    if user.role != "owner":
        raise HTTPException(403, "Workspace ownership is required")
    return user


@router.get("/export")
def export_workspace(
    user: Annotated[AuthenticatedUser, Depends(_owner)],
    database: Annotated[Database, Depends(_database)],
) -> StreamingResponse:
    try:
        archive = WorkspaceExportService(database, user.identity).build()
    except MembershipRequiredError:
        raise HTTPException(403, "Workspace membership is required") from None
    return StreamingResponse(
        archive.chunks(),
        media_type="application/zip",
        headers={
            "Content-Disposition": f'attachment; filename="{archive.filename}"',
            "Cache-Control": "no-store",
        },
    )
