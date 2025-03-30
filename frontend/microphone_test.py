import asyncio
from services.microphone_speech import MicrophoneAsrClient


async def test_microphone_recognition():
    """
    测试麦克风实时语音识别
    """
    print("===== 麦克风实时语音识别测试 =====")
    
    client = MicrophoneAsrClient()
    
    # 定义回调函数用于显示中间结果
    def on_recognition_result(text, is_final=False):
        if is_final:
            print(f"\n最终识别结果: {text}")
        else:
            print(f"\r实时识别结果: {text}", end="", flush=True)
    
    print("将在5秒内开始录音...")
    await asyncio.sleep(5)
    
    # 创建一个协程来运行识别
    async def run_recognition():
        async for result in client.start_recognition(callback=on_recognition_result):
            if result['is_final']:
                break
    
    # 创建一个协程在一定时间后停止录音
    async def stop_after_duration(duration):
        await asyncio.sleep(duration)
        client.stop_recognition()
        print(f"\n已录音 {duration} 秒，停止录音")
    
    # 运行时间(秒)
    duration = 15
    
    print(f"请开始对麦克风说话，录音将持续 {duration} 秒...")
    
    # 同时启动两个任务
    await asyncio.gather(
        run_recognition(),
        stop_after_duration(duration)
    )
    
    # 获取最终识别结果
    final_text = client.get_recognized_text()
    print(f"识别完成！最终结果: {final_text}")
    return final_text


def main():
    result = asyncio.run(test_microphone_recognition())
    print(f"测试完成，识别结果: {result}")


if __name__ == "__main__":
    main()
