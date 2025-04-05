import asyncio
import pyaudio
import websockets
import uuid
import gzip
import json

from typing import AsyncGenerator, Dict, Any, Tuple

# 导入语音识别所需的常量和函数
from services.speech_to_text import (
    generate_header, generate_before_payload, 
    FULL_CLIENT_REQUEST, AUDIO_ONLY_REQUEST, 
    POS_SEQUENCE, NEG_WITH_SEQUENCE, parse_response
)

# 录音参数
CHUNK = 1024  # 每次读取的音频大小
FORMAT = pyaudio.paInt16  # 音频格式
CHANNELS = 1  # 单声道
RATE = 16000  # 采样率
BITS = 16  # 位深度
SEGMENT_DURATION = 100  # 每个片段的时长(毫秒)


class MicrophoneAsrClient:
    """
    实时麦克风语音识别客户端
    """
    
    def __init__(self, **kwargs):
        self.success_code = 1000  # 成功代码，默认为1000
        self.seg_duration = int(kwargs.get("seg_duration", SEGMENT_DURATION))
        self.ws_url = kwargs.get("ws_url", "wss://openspeech.bytedance.com/api/v3/sauc/bigmodel")
        self.uid = kwargs.get("uid", "test")
        self.rate = kwargs.get("rate", RATE)
        self.bits = kwargs.get("bits", BITS)
        self.channel = kwargs.get("channel", CHANNELS)
        self.codec = kwargs.get("codec", "raw")
        self.streaming = kwargs.get("streaming", True)
        self.format = "pcm"  # 麦克风录音使用PCM格式
        
        # 语音识别结果
        self.recognized_text = ""
        self.is_running = False
        self.audio_buffer = bytearray()
        
        # 计算每个分段的大小
        self.segment_size = int(self.rate * 2 * self.channel * self.seg_duration / 500)

    def construct_request(self, reqid):
        """
        构造请求参数
        """
        req = {
            "user": {
                "uid": self.uid,
            },
            "audio": {
                'format': self.format,
                "sample_rate": self.rate,
                "bits": self.bits,
                "channel": self.channel,
                "codec": self.codec,
            },
            "request": {
                "model_name": "bigmodel",
                "enable_punc": True,
                # "result_type": "single",
                # "vad_segment_duration": 800,
            }
        }
        return req

    @staticmethod
    def slice_data(data: bytes, chunk_size: int):
        """
        将数据切片
        """
        data_len = len(data)
        offset = 0
        while offset + chunk_size < data_len:
            yield data[offset: offset + chunk_size], False
            offset += chunk_size
        else:
            yield data[offset: data_len], True

    async def process_audio_frame(self, audio_frame: bytes, ws, seq: int) -> Tuple[int, dict]:
        """
        处理单个音频帧
        """
        payload_bytes = gzip.compress(audio_frame)
        audio_only_request = bytearray(generate_header(
            message_type=AUDIO_ONLY_REQUEST, 
            message_type_specific_flags=POS_SEQUENCE
        ))
        audio_only_request.extend(generate_before_payload(sequence=seq))
        audio_only_request.extend((len(payload_bytes)).to_bytes(4, 'big'))
        audio_only_request.extend(payload_bytes)
        
        await ws.send(audio_only_request)
        res = await ws.recv()
        result = parse_response(res)
        return seq + 1, result

    async def send_end_signal(self, ws, seq: int) -> dict:
        """
        发送结束信号
        """
        # 发送空数据，标记为结束
        empty_data = b''
        payload_bytes = gzip.compress(empty_data)
        audio_only_request = bytearray(generate_header(
            message_type=AUDIO_ONLY_REQUEST, 
            message_type_specific_flags=NEG_WITH_SEQUENCE
        ))
        audio_only_request.extend(generate_before_payload(sequence=-seq))
        audio_only_request.extend((len(payload_bytes)).to_bytes(4, 'big'))
        audio_only_request.extend(payload_bytes)
        
        await ws.send(audio_only_request)
        res = await ws.recv()
        return parse_response(res)

    async def start_recognition(self, callback=None) -> AsyncGenerator[Dict[str, Any], None]:
        """
        开始实时语音识别
        """
        self.is_running = True
        reqid = str(uuid.uuid4())
        seq = 1
        
        # 构建初始请求
        request_params = self.construct_request(reqid)
        payload_bytes = str.encode(json.dumps(request_params))
        payload_bytes = gzip.compress(payload_bytes)
        
        full_client_request = bytearray(generate_header(message_type_specific_flags=POS_SEQUENCE))
        full_client_request.extend(generate_before_payload(sequence=seq))
        full_client_request.extend((len(payload_bytes)).to_bytes(4, 'big'))
        full_client_request.extend(payload_bytes)
        
        header = {
            "X-Api-Resource-Id": "volc.bigasr.sauc.duration",
            "X-Api-Access-Key": "o2nrLg4vCSnrx4Me_N2oTVQrXcU6pLTZ",
            "X-Api-App-Key": "3415704595",
            "X-Api-Request-Id": reqid
        }
        
        # 创建音频采集对象
        p = pyaudio.PyAudio()
        stream = p.open(
            format=FORMAT,
            channels=CHANNELS,
            rate=RATE,
            input=True,
            frames_per_buffer=CHUNK
        )
        
        print("* 开始录音，请说话...")
        
        try:
            async with websockets.connect(
                self.ws_url, 
                additional_headers=header, 
                max_size=1000000000
            ) as ws:
                # 发送初始请求
                await ws.send(full_client_request)
                res = await ws.recv()
                result = parse_response(res)
                seq += 1
                
                # 开始音频处理循环
                buffer = bytearray()
                while self.is_running:
                    # 读取音频数据
                    audio_data = stream.read(CHUNK, exception_on_overflow=False)
                    buffer.extend(audio_data)
                    
                    # 当缓冲区达到足够大小时，发送数据
                    if len(buffer) >= self.segment_size:
                        chunk_data = bytes(buffer[:self.segment_size])
                        buffer = buffer[self.segment_size:]
                        
                        seq, result = await self.process_audio_frame(chunk_data, ws, seq)
                        
                        # 如果结果中包含识别文本
                        if 'payload_msg' in result and 'result' in result['payload_msg']:
                            asr_result = result['payload_msg']['result']
                            if 'text' in asr_result:
                                self.recognized_text = asr_result['text']
                                # 如果有回调函数，调用回调
                                if callback:
                                    callback(self.recognized_text)
                                # 产生结果
                                yield {
                                    "text": self.recognized_text,
                                    "is_final": False
                                }
                
                # 发送结束信号
                final_result = await self.send_end_signal(ws, seq)
                
                # 获取最终结果
                if 'payload_msg' in final_result and 'result' in final_result['payload_msg']:
                    asr_result = final_result['payload_msg']['result']
                    if 'text' in asr_result:
                        self.recognized_text = asr_result['text']
                        # 如果有回调函数，调用回调
                        if callback:
                            callback(self.recognized_text, is_final=True)
                        # 产生最终结果
                        yield {
                            "text": self.recognized_text,
                            "is_final": True
                        }
                        
        except Exception as e:
            print(f"语音识别出现错误: {e}")
            raise
        finally:
            # 关闭音频流和PyAudio
            stream.stop_stream()
            stream.close()
            p.terminate()
            print("* 录音结束")
    
    def stop_recognition(self):
        """
        停止语音识别
        """
        self.is_running = False

    def get_recognized_text(self) -> str:
        """
        获取识别的文本
        """
        return self.recognized_text
        
    async def process_android_audio_buffer(self) -> AsyncGenerator[Dict[str, Any], None]:
        """
        处理来自安卓客户端的音频缓冲区数据并进行语音识别
        """
        self.is_running = True
        reqid = str(uuid.uuid4())
        seq = 1
        
        # 构建初始请求
        request_params = self.construct_request(reqid)
        payload_bytes = str.encode(json.dumps(request_params))
        payload_bytes = gzip.compress(payload_bytes)
        
        full_client_request = bytearray(generate_header(message_type_specific_flags=POS_SEQUENCE))
        full_client_request.extend(generate_before_payload(sequence=seq))
        full_client_request.extend((len(payload_bytes)).to_bytes(4, 'big'))
        full_client_request.extend(payload_bytes)
        
        header = {
            "X-Api-Resource-Id": "volc.bigasr.sauc.duration",
            "X-Api-Access-Key": "o2nrLg4vCSnrx4Me_N2oTVQrXcU6pLTZ",
            "X-Api-App-Key": "3415704595",
            "X-Api-Request-Id": reqid
        }
        
        try:
            async with websockets.connect(
                self.ws_url, 
                additional_headers=header, 
                max_size=1000000000
            ) as ws:
                # 发送初始请求
                await ws.send(full_client_request)
                res = await ws.recv()
                result = parse_response(res)
                seq += 1
                
                # 开始音频处理循环
                while self.is_running:
                    # 检查音频缓冲区中是否有足够的数据
                    if len(self.audio_buffer) >= self.segment_size:
                        chunk_data = bytes(self.audio_buffer[:self.segment_size])
                        self.audio_buffer = self.audio_buffer[self.segment_size:]
                        
                        seq, result = await self.process_audio_frame(chunk_data, ws, seq)
                        
                        # 如果结果中包含识别文本
                        if 'payload_msg' in result and 'result' in result['payload_msg']:
                            asr_result = result['payload_msg']['result']
                            if 'text' in asr_result:
                                self.recognized_text = asr_result['text']
                                # 产生结果
                                yield {
                                    "text": self.recognized_text,
                                    "is_final": False
                                }
                    else:
                        # 如果缓冲区中数据不足，等待一小段时间
                        await asyncio.sleep(0.01)
                        
                        # 如果停止运行并且缓冲区还有剩余数据，发送最后一段数据
                        if not self.is_running and len(self.audio_buffer) > 0:
                            chunk_data = bytes(self.audio_buffer)
                            self.audio_buffer = bytearray()
                            seq, result = await self.process_audio_frame(chunk_data, ws, seq)
                
                # 发送结束信号
                final_result = await self.send_end_signal(ws, seq)
                
                # 获取最终结果
                if 'payload_msg' in final_result and 'result' in final_result['payload_msg']:
                    asr_result = final_result['payload_msg']['result']
                    if 'text' in asr_result:
                        self.recognized_text = asr_result['text']
                        # 产生最终结果
                        yield {
                            "text": self.recognized_text,
                            "is_final": True
                        }
                        
        except Exception as e:
            print(f"处理安卓音频时出现错误: {e}")
            raise
            
    def add_audio_data(self, audio_data: bytes):
        """
        添加来自安卓客户端的音频数据到缓冲区
        """
        self.audio_buffer.extend(audio_data)


async def test_microphone_recognition():
    """
    测试麦克风实时语音识别
    """
    client = MicrophoneAsrClient()
    
    # 定义回调函数
    def on_recognition_result(text, is_final=False):
        if is_final:
            print(f"最终识别结果: {text}")
        else:
            print(f"实时识别结果: {text}")
    
    # 创建一个任务来运行 10 秒钟
    async def run_for_duration():
        async for result in client.start_recognition(callback=on_recognition_result):
            print(f"结果: {result['text']}")
            if result['is_final']:
                break
    
    # 创建一个任务来运行 10 秒钟然后停止
    async def stop_after_duration(duration):
        await asyncio.sleep(duration)
        client.stop_recognition()
        print(f"已录音 {duration} 秒，停止录音")
    
    # 同时启动两个任务
    await asyncio.gather(
        run_for_duration(),
        stop_after_duration(10)  # 10 秒后停止
    )
    
    return client.get_recognized_text()


if __name__ == "__main__":
    result = asyncio.run(test_microphone_recognition())
    print(f"最终识别结果: {result}")
