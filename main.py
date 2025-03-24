# coding=utf-8

from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from services.text_to_speech import submit
from services.speech_to_text import execute_one
from services.chat import chat_messages, ChatRequest

app = FastAPI()


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


async def audio_generator(text: str):
    async for chunk in submit(text):
        yield chunk
