# coding=utf-8

from fastapi import FastAPI
from fastapi.responses import StreamingResponse
from services.text_to_speech import submit
from services.chat import chat_messages, ChatRequest

app = FastAPI()


@app.post("/chat/")
async def chat(chat_request: ChatRequest):
    return await chat_messages(chat_request)


async def audio_generator(text: str):
    async for chunk in submit(text):
        yield chunk


@app.post("/text-to-speech/")
async def text_to_speech(text: str):
    return StreamingResponse(
        audio_generator(text),
        media_type="audio/mpeg",
        headers={
            "Content-Disposition": "attachment; filename=speech.mp3"
        }
    )
