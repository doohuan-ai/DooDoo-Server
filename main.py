# coding=utf-8

import asyncio

from fastapi import FastAPI
from services.tts_websocket import submit

app = FastAPI()


@app.post("/text-to-speech/")
async def text_to_speech(text: str):
    await submit(text)
