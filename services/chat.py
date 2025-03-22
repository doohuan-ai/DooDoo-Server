import json
import requests
from pydantic import BaseModel
from fastapi import HTTPException

api_key = 'app-HEgO3Ovjv7wTurbw5XtLhbWc'


class ChatRequest(BaseModel):
    query: str
    user_id: str
    conversation_id: str | None = ""


class ChatResponse(BaseModel):
    answer: str
    conversation_id: str
    message_id: str


async def chat_messages(chat_request: ChatRequest) -> ChatResponse:
    """
    文本对话，调用 dify 的 API
    """
    try:
        url = "http://127.0.0.1:8081/v1/chat-messages"

        data = {
            "inputs": {},
            "query": chat_request.query,
            "response_mode": "streaming",  # 流式模式
            "conversation_id": chat_request.conversation_id,
            "user": chat_request.user_id,
        }

        headers = {
            'Authorization': f'Bearer {api_key}',
            'Content-Type': 'application/json',
        }

        # 发送请求并获取流式响应
        response = requests.post(url, json=data, headers=headers, stream=True)
        
        if response.status_code != 200:
            raise HTTPException(status_code=response.status_code, detail=response.text)
        
        # 用于存储完整的回答
        full_answer = ""
        conversation_id = ""
        message_id = ""
        
        # 处理流式响应
        for line in response.iter_lines():
            if line:
                # 移除 "data: " 前缀并解析 JSON
                json_str = line.decode('utf-8').replace('data: ', '')
                if json_str.strip():
                    try:
                        chunk = json.loads(json_str)
                        if chunk.get("event") == "message":
                            full_answer += chunk.get("answer", "")              # 累积回答文本
                            conversation_id = chunk.get("conversation_id", "")  # 获取会话ID
                            message_id = chunk.get("id", "")                    # 获取消息ID
                    except json.JSONDecodeError:
                        continue

        return ChatResponse(
            answer=full_answer,
            conversation_id=conversation_id,
            message_id=message_id
        )

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
