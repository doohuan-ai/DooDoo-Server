import os
import aiohttp
import asyncio


async def test_chat_audio():
    try:
        # 创建输出目录
        os.makedirs("output", exist_ok=True)
        output_file = "output/test_speech.mp3"

        print("开始测试语音对话接口...")

        url = "http://localhost:8000/chat/"
        
        test_data = {
            "audio_path": "/home/cafe100/Github/DooDoo-Server/frontend/3.wav",
            "user_id": "test_user_001",
            "conversation_id": ""
        }

        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=test_data) as response:
                if response.status == 200:
                    print(f"接口调用成功，状态码: {response.status}")
                    print("开始接收音频流...")

                    # 打开文件准备写入
                    with open(output_file, "wb") as f:
                        # 流式读取响应内容
                        async for chunk, _ in response.content.iter_chunks():
                            if chunk:
                                f.write(chunk)
                                print(f"接收到音频数据块，大小: {len(chunk)} 字节")

                    print(f"音频文件已保存到: {output_file}")
                    
                    # 打印响应头中的会话信息
                    print(f"会话ID: {response.headers.get('X-Conversation-Id')}")
                    print(f"消息ID: {response.headers.get('X-Message-Id')}")
                else:
                    print(f"接口调用失败，状态码: {response.status}")
                    error_text = await response.text()
                    print(f"错误信息: {error_text}")
    except Exception as e:
        print(f"测试过程中发生错误: {str(e)}")
        raise


def main():
    asyncio.run(test_chat_audio())


if __name__ == "__main__":
    main()
