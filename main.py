# coding=utf-8

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from services.text_to_speech import submit
from services.microphone_speech import MicrophoneAsrClient
from services.chat import chat_messages, ChatRequest
import json
import asyncio
import base64

app = FastAPI()

# 添加静态文件服务
app.mount("/static", StaticFiles(directory="web"), name="static")


# 首页路由，重定向到语音聊天页面
@app.get("/")
async def redirect_to_mic_page():
    return FileResponse("frontend/voice_chat.html")


# 语音聊天页面
@app.get("/voice-chat")
async def voice_chat_page():
    return FileResponse("frontend/voice_chat.html")


@app.post("/chat/")
async def chat(chat_request: ChatRequest):
    if not chat_request.query:
        raise HTTPException(status_code=400, detail="Either query or audio_path must be provided")

    # 获取聊天回复
    chat_response = await chat_messages(chat_request)

    # 将回答文本转为 Base64 编码，避免 HTTP 头不支持 Unicode 的问题
    answer_base64 = base64.b64encode(chat_response.answer.encode('utf-8')).decode('ascii')

    # 创建自定义响应
    response = StreamingResponse(
        audio_generator(chat_response.answer),
        media_type="audio/mpeg",
        headers={
            "Content-Disposition": "attachment; filename=chat_response.mp3",
            "X-Conversation-Id": chat_response.conversation_id,
            "X-Message-Id": chat_response.message_id,
            "X-Response-Text-Base64": answer_base64,
            "Access-Control-Expose-Headers": "X-Conversation-Id, X-Message-Id, X-Response-Text-Base64"
        }
    )
    
    return response


async def audio_generator(text: str):
    async for chunk in submit(text):
        yield chunk


@app.websocket("/voice-chat/")
async def websocket_voice_chat(websocket: WebSocket):
    """
    WebSocket端点，用于实时语音聊天（语音识别+对话+语音合成）
    """
    await websocket.accept()
    
    client = MicrophoneAsrClient()
    recognition_task = None
    
    try:
        # 接收控制命令
        async for message in websocket.iter_text():
            cmd = json.loads(message)
            
            if cmd["action"] == "start":
                # 开始语音聊天
                if recognition_task is None:
                    user_id = cmd.get("user_id", "default_user")
                    conversation_id = cmd.get("conversation_id", "")
                    recognition_task = asyncio.create_task(
                        process_voice_chat(websocket, client, user_id, conversation_id)
                    )
                    await websocket.send_json({"status": "started"})
                else:
                    await websocket.send_json({"status": "error", "message": "Recognition already in progress"})
                    
            elif cmd["action"] == "stop":
                # 停止语音聊天
                if recognition_task is not None:
                    client.stop_recognition()
                    await recognition_task
                    recognition_task = None
                    await websocket.send_json({"status": "stopped"})
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


async def process_voice_chat(websocket: WebSocket, client: MicrophoneAsrClient, user_id: str, conversation_id: str):
    """
    处理语音聊天流程：语音识别 -> 文本对话 -> 语音合成
    """
    async for result in client.start_recognition():
        # 发送实时识别结果
        await websocket.send_json({
            "status": "recognizing",
            "text": result["text"],
            "is_final": result["is_final"]
        })
        
        # 当识别完成时，发送到对话系统并获取回复
        if result["is_final"] and result["text"].strip():
            # 创建聊天请求
            chat_request = ChatRequest(
                query=result["text"],
                user_id=user_id,
                conversation_id=conversation_id
            )
            
            # 获取聊天回复
            try:
                chat_response = await chat_messages(chat_request)
                
                # 发送文本回复
                await websocket.send_json({
                    "status": "chat_response",
                    "text": chat_response.answer,
                    "conversation_id": chat_response.conversation_id,
                    "message_id": chat_response.message_id
                })
                
                # 开始语音合成并发送音频数据
                await websocket.send_json({
                    "status": "synthesizing",
                    "message": "开始语音合成..."
                })
                
                # 发送音频数据
                audio_chunks = []
                async for chunk in submit(chat_response.answer):
                    # 将二进制数据转换为Base64编码
                    chunk_base64 = base64.b64encode(chunk).decode('ascii')
                    audio_chunks.append(chunk_base64)
                
                # 发送合成完成的音频数据
                await websocket.send_json({
                    "status": "synthesis_complete",
                    "audio_data": audio_chunks
                })
                
                # 更新会话ID
                conversation_id = chat_response.conversation_id
                
            except Exception as e:
                await websocket.send_json({
                    "status": "error",
                    "message": f"对话或语音合成出错: {str(e)}"
                })


# 安卓客户端API端点
@app.websocket("/android/voice-chat/")
async def android_websocket_voice_chat(websocket: WebSocket):
    """
    用于安卓客户端的WebSocket端点，处理实时语音聊天（语音识别+对话+语音合成）
    """
    await websocket.accept()
    
    client = MicrophoneAsrClient()
    recognition_task = None
    
    try:
        # 接收控制命令
        async for message in websocket.iter_json():
            cmd = message
            
            if cmd["action"] == "start":
                # 开始语音聊天
                if recognition_task is None:
                    user_id = cmd.get("user_id", "android_user")
                    conversation_id = cmd.get("conversation_id", "")
                    recognition_task = asyncio.create_task(
                        process_android_voice_chat(websocket, client, user_id, conversation_id)
                    )
                    await websocket.send_json({"status": "started"})
                else:
                    await websocket.send_json({"status": "error", "message": "Recognition already in progress"})
                    
            elif cmd["action"] == "audio_data":
                # 接收并处理音频数据
                if recognition_task is not None:
                    # 解析Base64编码的音频数据
                    audio_data = base64.b64decode(cmd["data"])
                    client.add_audio_data(audio_data)
                else:
                    await websocket.send_json({"status": "error", "message": "Recognition not started"})
                    
            elif cmd["action"] == "stop":
                # 停止语音聊天
                if recognition_task is not None:
                    client.stop_recognition()
                    await recognition_task
                    recognition_task = None
                    await websocket.send_json({"status": "stopped"})
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


async def process_android_voice_chat(websocket: WebSocket, client: MicrophoneAsrClient, user_id: str, conversation_id: str):
    """
    处理安卓客户端的语音聊天流程：语音识别 -> 文本对话 -> 语音合成
    """
    async for result in client.process_android_audio_buffer():
        # 发送实时识别结果
        await websocket.send_json({
            "status": "recognizing",
            "text": result["text"],
            "is_final": result["is_final"]
        })
        
        # 当识别完成时，发送到对话系统并获取回复
        if result["is_final"] and result["text"].strip():
            # 创建聊天请求
            chat_request = ChatRequest(
                query=result["text"],
                user_id=user_id,
                conversation_id=conversation_id
            )
            
            # 获取聊天回复
            try:
                chat_response = await chat_messages(chat_request)
                
                # 发送文本回复
                await websocket.send_json({
                    "status": "chat_response",
                    "text": chat_response.answer,
                    "conversation_id": chat_response.conversation_id,
                    "message_id": chat_response.message_id
                })
                
                # 开始语音合成并发送音频数据
                await websocket.send_json({
                    "status": "synthesizing",
                    "message": "开始语音合成..."
                })
                
                # 发送音频数据
                audio_chunks = []
                async for chunk in submit(chat_response.answer):
                    # 将二进制数据转换为Base64编码
                    chunk_base64 = base64.b64encode(chunk).decode('ascii')
                    audio_chunks.append(chunk_base64)
                
                # 发送合成完成的音频数据
                await websocket.send_json({
                    "status": "synthesis_complete",
                    "audio_data": audio_chunks
                })
                
                # 更新会话ID
                conversation_id = chat_response.conversation_id
                
            except Exception as e:
                await websocket.send_json({
                    "status": "error",
                    "message": f"对话或语音合成出错: {str(e)}"
                })
