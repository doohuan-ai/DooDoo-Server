import aiohttp
import asyncio
import os


async def test_text_to_speech():
    # 测试文本
    text = "嘿，亲爱的小朋友，欢迎来到我们的奇妙世界！从今天起，你有了一个特别的朋友——就是我！"
    
    # 创建输出目录
    os.makedirs("output", exist_ok=True)
    output_file = "output/test_speech.mp3"
    
    print("开始测试文字转语音接口...")
    
    async with aiohttp.ClientSession() as session:
        async with session.post(
            "http://localhost:8000/text-to-speech/",
            params={"text": text}
        ) as response:
            if response.status == 200:
                print(f"接口调用成功，状态码: {response.status}")
                print("开始接收音频流...")
                
                # 打开文件准备写入
                with open(output_file, "wb") as f:
                    # 流式读取响应内容
                    async for chunk, _ in response.content.iter_chunks():
                        if chunk:  # chunk 是实际的数据
                            f.write(chunk)
                            print(f"接收到音频数据块，大小: {len(chunk)} 字节")
                
                print(f"音频文件已保存到: {output_file}")
            else:
                print(f"接口调用失败，状态码: {response.status}")
                print(f"错误信息: {await response.text()}")

if __name__ == "__main__":
    asyncio.run(test_text_to_speech())
