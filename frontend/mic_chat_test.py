import asyncio
import os
import aiohttp
from services.microphone_speech import MicrophoneAsrClient


async def mic_chat_test():
    """
    集成测试：麦克风语音识别 + 聊天服务
    """
    print("===== 麦克风语音识别 + 聊天集成测试 =====")
    
    # 1. 从麦克风录音并识别
    print("第一步：使用麦克风录音...")
    
    client = MicrophoneAsrClient()
    
    # 定义识别回调
    def on_recognition_result(text, is_final=False):
        if is_final:
            print(f"\n语音识别最终结果: {text}")
        else:
            print(f"\r实时识别结果: {text}", end="", flush=True)
    
    print("\n准备开始录音，将在3秒后开始...")
    await asyncio.sleep(3)
    print("请开始对麦克风说话，录音将持续10秒...")
    
    # 创建任务来运行识别和计时停止
    recognition_done = asyncio.Event()
    recognition_text = ""
    
    async def run_recognition():
        nonlocal recognition_text
        async for result in client.start_recognition(callback=on_recognition_result):
            if result['is_final']:
                recognition_text = result['text']
                recognition_done.set()
                break
    
    async def stop_after_duration(duration):
        await asyncio.sleep(duration)
        if not recognition_done.is_set():
            client.stop_recognition()
            recognition_done.set()
    
    # 同时启动两个任务
    await asyncio.gather(
        run_recognition(),
        stop_after_duration(10)
    )
    
    # 获取识别的文本
    recognized_text = client.get_recognized_text()
    if not recognized_text:
        print("没有识别到任何文本！测试结束。")
        return
    
    print(f"\n语音识别完成！识别结果: {recognized_text}")
    
    # 2. 将识别的文本发送到聊天服务
    print("\n第二步：将识别的文本发送到聊天服务...")
    
    try:
        # 创建输出目录
        os.makedirs("output", exist_ok=True)
        output_file = "output/mic_chat_response.mp3"
        
        url = "http://localhost:8000/chat/"
        
        # 设置请求数据
        chat_data = {
            "query": recognized_text,  # 使用识别的文本作为查询
            "user_id": "test_user_001",
            "conversation_id": ""
        }
        
        print(f"发送聊天请求: {chat_data}")
        
        # 发送请求到聊天服务
        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=chat_data) as response:
                if response.status == 200:
                    print(f"聊天服务调用成功，状态码: {response.status}")
                    print("开始接收音频响应...")
                    
                    # 保存响应音频
                    with open(output_file, "wb") as f:
                        async for chunk, _ in response.content.iter_chunks():
                            if chunk:
                                f.write(chunk)
                                print(f"接收到音频数据块，大小: {len(chunk)} 字节")
                    
                    print(f"音频响应已保存到: {output_file}")
                    
                    # 打印会话信息
                    print(f"会话ID: {response.headers.get('X-Conversation-Id')}")
                    print(f"消息ID: {response.headers.get('X-Message-Id')}")
                    
                    print("\n集成测试完成！")
                    print(f"识别的文本: {recognized_text}")
                    print(f"聊天响应保存到: {output_file}")
                else:
                    print(f"聊天服务调用失败，状态码: {response.status}")
                    error_text = await response.text()
                    print(f"错误信息: {error_text}")
    except Exception as e:
        print(f"聊天服务调用出错: {str(e)}")


def main():
    """
    主函数
    """
    asyncio.run(mic_chat_test())


if __name__ == "__main__":
    main()
