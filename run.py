#!/usr/bin/env python
# coding=utf-8

import uvicorn

if __name__ == "__main__":
    print("启动语音聊天服务器...")
    print("请访问 http://localhost:8000 以使用语音聊天功能")
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
