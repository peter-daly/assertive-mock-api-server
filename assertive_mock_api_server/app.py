from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from clean_ioc.ext.fastapi import add_container_to_app, Resolve
from fastapi.responses import JSONResponse, Response

from assertive_mock_api_server.container import get_container
from assertive_mock_api_server.core import (
    MockApiRequest,
    MockApiServer,
)
from assertive_mock_api_server.payloads import (
    ApiAssertionPayload,
    MockApiRequestListViewPayload,
    StubListViewPayload,
    StubPayload,
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    container = get_container()
    async with add_container_to_app(app, container):
        yield


app = FastAPI(lifespan=lifespan)


app = FastAPI(
    title="Assertive Mock API Server",
    description="A mock API server for testing.",
    lifespan=lifespan,
    docs_url="/docs",
    openapi_url="/openapi.json",
    redoc_url=None,
)


async def extract_body(request: Request) -> str | bytes:
    """
    Extract the body from the request and return as string if possible, otherwise bytes.

    Args:
        request: The FastAPI request object

    Returns:
        The body content as string if decodable, otherwise as bytes
    """
    body_bytes = await request.body()

    # Return empty string if no body
    if not body_bytes:
        return ""

    # Try to decode as UTF-8 string
    try:
        return body_bytes.decode("utf-8")
    except UnicodeDecodeError:
        # Return raw bytes if can't be decoded
        return body_bytes


# --- Endpoints ---


@app.post("/__mock__/stubs")
async def add_stub(request: StubPayload, mock_server=Resolve(MockApiServer)):
    await mock_server.add_stub(request.to_stub())
    return {"success": True}


@app.post("/__mock__/assert")
async def assert_request(
    assertion: ApiAssertionPayload, mock_server=Resolve(MockApiServer)
):
    """
    Assert that the request matches the given assertion.
    """
    result = await mock_server.confirm_assertion(assertion.to_api_assertion())

    return {"result": result.success}


@app.get("/__mock__/requests")
async def list_requests(mock_server=Resolve(MockApiServer)):
    """
    List all requests that match the given assertion.
    """
    result = await mock_server.list_requests()

    return MockApiRequestListViewPayload.from_mock_api_requests(result)


@app.get("/__mock__/stubs")
async def list_stubs(mock_server=Resolve(MockApiServer)):
    """
    List all stubs.
    """
    stubs = await mock_server.list_stubs()
    stub_views = StubListViewPayload.from_stubs(stubs)

    return stub_views


@app.api_route(
    "/__mock__",
    methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS", "HEAD"],
)
async def mock_api_root(request: Request):
    """
    Root endpoint for the mock API server.
    """
    return JSONResponse(
        content={
            "message": "Welcome to the Assertive Mock API Server!",
            "available_endpoints": [
                "/__mock__/stubs",
                "/__mock__/assert",
                "/__mock__/requests",
            ],
        },
        status_code=200,
        headers={"Content-Type": "application/json"},
    )


@app.api_route(
    "/{path:path}",
    methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS", "HEAD"],
    include_in_schema=False,
)
async def catch_all(request: Request, mock_server=Resolve(MockApiServer)):
    """
    Catch-all endpoint for all requests.
    """
    headers = dict(request.headers)
    query = dict(request.query_params)
    method = request.method
    body = await extract_body(request)
    hostname = request.url.hostname or ""
    path = request.url.path

    api_request = MockApiRequest(
        method=method,
        path=path,
        query=query,
        headers=headers,
        body=body,
        host=hostname,
    )

    api_response = await mock_server.handle_request(api_request)

    # Convert MockApiResponse to FastAPI response
    content = api_response.body
    status_code = api_response.status_code
    headers = api_response.headers

    # Choose response type based on content
    if isinstance(content, dict) or isinstance(content, list):
        return JSONResponse(content=content, status_code=status_code, headers=headers)
    elif isinstance(content, str):
        return Response(content=content, status_code=status_code, headers=headers)
    elif isinstance(content, bytes):
        return Response(
            content=content,
            status_code=status_code,
            headers=headers,
            media_type="application/octet-stream",
        )
    else:
        # For None or other types
        return Response(status_code=status_code, headers=headers)
