"""Anonymous optional acquisition; bounded before decoding, fail-closed policy."""
import json
import asyncio
from fastapi import APIRouter, Request, Response
from starlette.concurrency import run_in_threadpool
from app.services.attribution_service import reference_digest
from app.services.attribution_service import AttributionService

router = APIRouter(prefix='/acquisition', tags=['acquisition'])
COOKIE = 'flare_acquisition'


def clear_acquisition(request: Request, response: Response) -> None:
    response.delete_cookie(COOKIE, path='/', httponly=True,
        secure=request.app.state.settings.secure_cookies, samesite='lax')


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('Duplicate field')
        result[key] = value
    return result


@router.get('/policy')
def policy(request: Request):
    try:
        result = AttributionService(request.app.state.database).policy()
        return result
    except Exception:
        return {'enabled': False}


@router.post('/touch', status_code=202)
async def touch(request: Request):
    response = Response(status_code=202, headers={'Cache-Control': 'no-store'})
    # Authenticated browsing is never attached to a new acquisition visitor.
    if request.cookies.get(request.app.state.settings.session_cookie_name):
        clear_acquisition(request, response)
        return response
    try:
        size = 0
        chunks = []
        async with asyncio.timeout(1):
            async for chunk in request.stream():
                size += len(chunk)
                if size > 1024:
                    return response
                chunks.append(chunk)
        payload = json.loads(b''.join(chunks), object_pairs_hook=_unique_object)
        if not isinstance(payload,dict) or set(payload) != {'touch','revision','eligible'} or payload['eligible'] is not True:
            return response
        if not isinstance(payload['revision'],str) or len(payload['revision'])>80:
            return response
        service = AttributionService(request.app.state.database)
        configured = await run_in_threadpool(service.policy)
        if not configured.get('enabled'):
            return response
        reference = await run_in_threadpool(service.touch, reference=request.cookies.get(COOKIE),
            peer=request.client.host if request.client else 'unknown',touch=payload['touch'],revision=payload['revision'],deadline_ms=configured['deadlineMs'])
        if reference:
            response.set_cookie(COOKIE,reference,httponly=True,secure=request.app.state.settings.secure_cookies,
                samesite='lax',path='/',max_age=configured['cookieSeconds'])
    except Exception:
        # No payload/error/rejection logs, no durable client retry queue.
        pass
    return response


@router.post('/forget', status_code=204)
def forget(request: Request):
    response = Response(status_code=204)
    clear_acquisition(request,response)
    try:
        with request.app.state.database.connection() as c:
            c.execute('SELECT public.acquisition_forget(%s)',(reference_digest(request.cookies.get(COOKIE)),))
    except Exception:
        pass
    # Server cleanup independently enforces expiry if this optional request failed.
    return response
