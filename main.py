# coding=utf-8

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from services.text_to_speech import submit
from services.speech_to_text import execute_one
from services.microphone_speech import MicrophoneAsrClient
from services.chat import chat_messages, ChatRequest
import json
import asyncio
import os

app = FastAPI()

# 添加静态文件服务
app.mount("/static", StaticFiles(directory="frontend"), name="static")


# 首页路由，重定向到语音识别页面
@app.get("/")
async def redirect_to_mic_page():
    return FileResponse("frontend/mic_speech_recognition.html")


# 语音识别页面
@app.get("/mic")
async def mic_page():
    return FileResponse("frontend/mic_speech_recognition.html")


@app.post("/chat/")
async def chat(chat_request: ChatRequest):
    # 如果提供了语音文件，先进行语音识别
    if chat_request.audio_path:
        speech_result = await execute_one({
            'id': 1,
            'path': chat_request.audio_path
        })
        # 从语音识别结果中获取文本
        recognized_text = speech_result.get("result").get("payload_msg").get("result").get("text")
        chat_request.query = recognized_text
    elif not chat_request.query:
        raise HTTPException(status_code=400, detail="Either query or audio_path must be provided")

    # 获取聊天回复
    chat_response = await chat_messages(chat_request)

    return StreamingResponse(
        audio_generator(chat_response.answer),
        media_type="audio/mpeg",
        headers={
            "Content-Disposition": "attachment; filename=chat_response.mp3",
            "X-Conversation-Id": chat_response.conversation_id,
            "X-Message-Id": chat_response.message_id
        }
    )


@app.websocket("/mic-speech-recognition/")
async def websocket_mic_speech_recognition(websocket: WebSocket):
    """
    WebSocket端点，用于实时麦克风语音识别
    """
    await websocket.accept()
    
    client = MicrophoneAsrClient()
    recognition_task = None
    
    try:
        # 接收控制命令
        async for message in websocket.iter_text():
            cmd = json.loads(message)
            
            if cmd["action"] == "start":
                # 开始识别
                if recognition_task is None:
                    recognition_task = asyncio.create_task(process_recognition(websocket, client))
                    await websocket.send_json({"status": "started"})
                else:
                    await websocket.send_json({"status": "error", "message": "Recognition already in progress"})
                    
            elif cmd["action"] == "stop":
                # 停止识别
                if recognition_task is not None:
                    client.stop_recognition()
                    await recognition_task
                    recognition_task = None
                    final_text = client.get_recognized_text()
                    await websocket.send_json({"status": "stopped", "final_text": final_text})
                else:
                    await websocket.send_json({"status": "error", "message": "No recognition in progress"})
    
    except WebSocketDisconnect:
        # 客户端断开连接
        if recognition_task is not None:
            client.stop_recognition()
            recognition_task.cancel()
    except Exception as e:
        # 其他错误
        if recognition_task is not None:
            client.stop_recognition()
            recognition_task.cancel()
        await websocket.send_json({"status": "error", "message": str(e)})


async def process_recognition(websocket: WebSocket, client: MicrophoneAsrClient):
    """
    处理语音识别并发送结果到WebSocket客户端
    """
    async for result in client.start_recognition():
        await websocket.send_json({
            "status": "recognizing",
            "text": result["text"],
            "is_final": result["is_final"]
        })
        if result["is_final"]:
            break


async def audio_generator(text: str):
    async for chunk in submit(text):
        yield chunk
