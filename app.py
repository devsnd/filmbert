#!/bin/env python3
import json
import os
import re
import stat
from io import BytesIO
from typing import List
import sys

import aiofiles
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from starlette.datastructures import Headers, URL
from starlette.responses import Response, StreamingResponse, PlainTextResponse, \
    RedirectResponse
from starlette.types import Scope

app = FastAPI()

class StreamedStaticFiles(StaticFiles):
    default_chunk_size = 1000 * 1024

    def __init__(self, *args, chunk_size=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.chunk_size = chunk_size or self.default_chunk_size

    async def file_response(
            self,
            full_path: str,
            stat_result: os.stat_result,
            scope: Scope,
            status_code: int = 206,
    ) -> Response:
        method = scope["method"]
        request_headers = Headers(scope=scope)
        file_size = stat_result.st_size
        range_request = request_headers.get('range')

        req_start_bytes = 0
        chunk_size = self.chunk_size

        if range_request:
            range_match = re.match('bytes=(\d+)-(\d*)', range_request)
            if range_match:
                req_start_bytes = int(range_match.group(1))
                req_end_bytes = range_match.group(2)
                if req_end_bytes:
                    req_end_bytes = int(req_end_bytes)
                    # reduce chunk size if it's smaller than the default chunk size
                    requested_chunk_size = req_end_bytes - req_start_bytes
                    if requested_chunk_size < chunk_size:
                        chunk_size = requested_chunk_size

        async with aiofiles.open(full_path, mode="rb") as fh:
            await fh.seek(req_start_bytes)
            file_bytes = await fh.read(chunk_size)
            b = BytesIO(file_bytes)
            num_bytes_read = len(file_bytes)

        # calculate actual chunk size read from disk
        end_bytes = req_start_bytes + num_bytes_read
        response_headers = {
            "Accept-Ranges": "bytes",
            "Content-Length": str(num_bytes_read),
            "Content-Range": F"bytes {req_start_bytes}-{end_bytes-1}/{file_size}",
        }
        if req_start_bytes == 0 and end_bytes == file_size: # this is the whole file
            status_code = 200
        return StreamingResponse(b, media_type="video/mp4", status_code=status_code, headers=response_headers)

    async def get_response(self, path: str, scope: Scope) -> Response:
        """
        Returns an HTTP response, given the incoming path, method and request headers.
        """
        if scope["method"] not in ("GET", "HEAD"):
            return PlainTextResponse("Method Not Allowed", status_code=405)

        full_path, stat_result = await self.lookup_path(path)

        if stat_result and stat.S_ISREG(stat_result.st_mode):
            # We have a static file to serve.
            return await self.file_response(full_path, stat_result, scope)

        elif stat_result and stat.S_ISDIR(stat_result.st_mode) and self.html:
            # We're in HTML mode, and have got a directory URL.
            # Check if we have 'index.html' file to serve.
            index_path = os.path.join(path, "index.html")
            full_path, stat_result = await self.lookup_path(index_path)
            if stat_result is not None and stat.S_ISREG(stat_result.st_mode):
                if not scope["path"].endswith("/"):
                    # Directory URLs should redirect to always end in "/".
                    url = URL(scope=scope)
                    url = url.replace(path=url.path + "/")
                    return RedirectResponse(url=url)
                return await self.file_response(full_path, stat_result, scope)

        if self.html:
            # Check for '404.html' if we're in HTML mode.
            full_path, stat_result = await self.lookup_path("404.html")
            if stat_result is not None and stat.S_ISREG(stat_result.st_mode):
                return await self.file_response(
                    full_path, stat_result, scope, status_code=404
                )

        return PlainTextResponse("Not Found", status_code=404)

VIDEO_CHUNK_SIZE = os.environ.get('VIDEO_CHUNK_SIZE')
if VIDEO_CHUNK_SIZE:
    VIDEO_CHUNK_SIZE = int(VIDEO_CHUNK_SIZE)
else:
    VIDEO_CHUNK_SIZE = 1000 * 1024

app.mount("/static", StreamedStaticFiles(directory="static", chunk_size=VIDEO_CHUNK_SIZE), name="static")


class ConnectionManager:
    def __init__(self):
        self.active_connections: List[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket):
        self.active_connections.remove(websocket)

    async def send_personal_message(self, message: str, websocket: WebSocket):
        await websocket.send_text(message)

    async def broadcast(self, message: str):
        for connection in self.active_connections:
            try:
                await connection.send_text(message)
            except:
                print('error')


manager = ConnectionManager()

html_index_file = os.path.join(os.path.dirname(__file__), 'index.html')
video_url = '/static/movie.mp4'
sub_url = ''

VIDEO_URL = os.environ.get('VIDEO_URL')
if VIDEO_URL:
    if VIDEO_URL.startswith('.'):
        VIDEO_URL = VIDEO_URL[1:]
    video_url = VIDEO_URL

SUB_URL = os.environ.get('SUB_URL')
if SUB_URL:
    if SUB_URL.startswith('.'):
        SUB_URL = SUB_URL[1:]
    sub_url = SUB_URL


@app.get("/")
async def get():
    async with aiofiles.open(html_index_file) as fh:
        html = await fh.read()
        html = html.replace('[[VIDEO_URL]]', video_url)
        html = html.replace('[[SUB_URL]]', sub_url)
    return HTMLResponse(html)


@app.websocket("/ws/{client_id}")
async def websocket_endpoint(websocket: WebSocket, client_id: int):
    await manager.connect(websocket)
    try:
        while True:
            data = await websocket.receive_text()
            # await manager.send_personal_message(f"You wrote: {data}", websocket)
            message = json.loads(data)
            await manager.broadcast(json.dumps({'client_id': client_id, 'data': message}))
    except WebSocketDisconnect:
        manager.disconnect(websocket)
        await manager.broadcast(f"Client #{client_id} left the chat")


def parse_arg(argname, default):
    import sys
    try:
        return sys.argv[sys.argv.index(argname) + 1]
    except (KeyError, ValueError) as e:
        return default


if __name__ == '__main__':
    import uvicorn
    import os
    port = int(parse_arg('--port', 8080))
    host = parse_arg('--host', '0.0.0.0')
    
    video = parse_arg('--video', './static/movie.mp4')
    if not os.path.exists(video):
        print(f'File {video} does not exist')
        sys.exit(1)
    os.environ['VIDEO_URL'] = video

    subtitle = parse_arg('--subtitle', '')
    if subtitle and not os.path.exists(subtitle):
        print(f'File {subtitle} does not exist')
        sys.exit(1)
    os.environ['SUB_URL'] = subtitle
    
    print(f'Serving "{video}" with subtitle "{subtitle}"')
    uvicorn.run("app:app", port=port, host=host, reload=False, access_log=True)
