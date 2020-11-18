import json
import os
import re
from io import BytesIO
from typing import List

import aiofiles
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from starlette.datastructures import Headers
from starlette.responses import Response, FileResponse, StreamingResponse
from starlette.staticfiles import NotModifiedResponse
from starlette.types import Scope

app = FastAPI()

class StreamedStaticFiles(StaticFiles):
    default_chunk_size = 1000 * 1024

    def file_response(
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
        chunk_size = self.default_chunk_size

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

        with open(full_path, mode="rb") as fh:
            fh.seek(req_start_bytes)
            file_bytes = fh.read(chunk_size)
            b = BytesIO(file_bytes)
            num_bytes_read = len(file_bytes)

        # calculate actual chunk size read from disk
        end_bytes = req_start_bytes + num_bytes_read
        response_headers = {
            "Accept-Ranges": "bytes",
            "Content-Length": str(num_bytes_read),
            "Content-Range": F"bytes {req_start_bytes}-{end_bytes-1}/{file_size}",
        }
        # print(response_headers)
        return StreamingResponse(b, media_type="video/mp4", status_code=206, headers=response_headers)

app.mount("/static", StreamedStaticFiles(directory="static"), name="static")


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

@app.get("/")
async def get():
    async with aiofiles.open(html_index_file) as fh:
        html = await fh.read()
    return HTMLResponse(html)


@app.websocket("/ws/{client_id}")
async def websocket_endpoint(websocket: WebSocket, client_id: int):
    await manager.connect(websocket)
    try:
        while True:
            data = await websocket.receive_text()
            # await manager.send_personal_message(f"You wrote: {data}", websocket)
            await manager.broadcast(json.dumps({'client_id': client_id, 'data': json.loads(data)}))
    except WebSocketDisconnect:
        manager.disconnect(websocket)
        await manager.broadcast(f"Client #{client_id} left the chat")
