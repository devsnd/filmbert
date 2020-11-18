import json
import os
import re
from io import BytesIO
from typing import List

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from starlette.datastructures import Headers
from starlette.responses import Response, FileResponse, StreamingResponse
from starlette.staticfiles import NotModifiedResponse
from starlette.types import Scope

app = FastAPI()

class StreamedStaticFiles(StaticFiles):
    def file_response(
            self,
            full_path: str,
            stat_result: os.stat_result,
            scope: Scope,
            status_code: int = 206,
    ) -> Response:
        method = scope["method"]
        request_headers = Headers(scope=scope)
        # print(request_headers)
        # print(stat_result.st_size)
        file_size = stat_result.st_size
        range_request = request_headers.get('range')
        range_match = re.match('bytes=(\d+)-(\d*)', range_request)
        default_chunk_size = 1000 * 1024
        req_start_bytes = 0
        if range_match:
            req_start_bytes = int(range_match.group(1))
            req_end_bytes = range_match.group(2)
            if req_end_bytes:
                req_end_bytes = int(req_end_bytes)
            # print(f'asked {req_start_bytes} - {req_end_bytes}')

        with open(full_path, mode="rb") as fh:
            fh.seek(req_start_bytes)
            file_bytes = fh.read(default_chunk_size)
            b = BytesIO(file_bytes)

        end_bytes = req_start_bytes + len(file_bytes)
        response_headers = {
            "Accept-Ranges": "bytes",
            "Content-Length": str(len(file_bytes)),
            "Content-Range": F"bytes {req_start_bytes}-{end_bytes-1}/{file_size}",
        }
        # print(response_headers)
        return StreamingResponse(b, media_type="video/mp4", status_code=206, headers=response_headers)

app.mount("/static", StreamedStaticFiles(directory="static"), name="static")

html = """
<!DOCTYPE html>
<html>
    <head>
        <title>Chat</title>
        <style>
            html, body { 
                background-color: black;
            }
            .showonhover {
                opacity: 0;
            }
            .showonhover:hover{
                opacity: 1;
            }
        </style>
    </head>
    <body>
        <span style="display: none;">Your ID: <span id="ws-id"></span></span>
        <video controls autobuffer loop id="video" width="100%">
            <source src="/static/movie.low.mp4" type="video/mp4" />
        </video>
        <form action="" onsubmit="seekTo(event)" class="showonhover">
            <input type="text" id="seekPosition" autocomplete="off"/>
            <button>Jump to</button>
        </form>
        <script>
            var client_id = Date.now();
            let videoElem = null;
            document.querySelector("#ws-id").textContent = client_id;
            var ws = new WebSocket(`ws:///ws/${client_id}`);
            const seekTo = (event) => {
                const position = parseFloat(document.querySelector('#seekPosition').value);
                document.querySelector('#video').currentTime = position;
                ws.send(JSON.stringify({action: 'seekto', currentTime: position}));
                event.preventDefault();
                return false;
            }
            ws.onmessage = function(event) {
                message = JSON.parse(event.data);
                console.log(message);
                if (message.client_id === client_id) {
                    console.log('ignoring own message');
                    return;
                }
                // message from another client
                if (videoElem === null) {
                    alert('got message, but video player not initialized!');
                    return;
                }

                if (message.data.action === 'play') {
                    videoElem.play();
                }
                if (message.data.action === 'seekto') {
                    videoElem.currentTime = message.data.currentTime;
                }
                if (message.data.action === 'pause') {
                    videoElem.pause();
                }
            };
            window.onload = function() {
                videoElem = document.querySelector('#video');
                videoElem.addEventListener('timeupdate', (event) => {
                    document.querySelector('#seekPosition').value = videoElem.currentTime;
                });
                videoElem.addEventListener('pause', (event) => {
                    ws.send(JSON.stringify({action: 'pause', currentTime: videoElem.currentTime})); 
                }); 
                videoElem.addEventListener('play', (event) => {
                    ws.send(JSON.stringify({action: 'play', currentTime: videoElem.currentTime})); 
                });
                videoElem.addEventListener('seeked', (event) => {
                    ws.send(JSON.stringify({action: 'seeked', currentTime: videoElem.currentTime}));
                });
            }
        </script>
    </body>
</html>
"""


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


@app.get("/")
async def get():
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
