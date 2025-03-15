import asyncio
import json
import struct
import uuid
import logging
from typing import Dict, List, Any

import websockets
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

# 配置日志
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# 创建FastAPI应用
app = FastAPI()

# 添加CORS中间件
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 在生产环境中应该限制为特定域名
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 火山引擎API配置
VOLCANO_API_URL = "wss://openspeech.bytedance.com/api/v3/sauc/bigmodel"
APP_KEY = ""  # 替换为你的App Key
ACCESS_KEY = ""  # 替换为你的Access Key
RESOURCE_ID = "volc.bigasr.sauc.duration"  # 小时版

# 存储活跃的WebSocket连接
active_connections: Dict[str, WebSocket] = {}

# 构建火山引擎API请求参数
def build_request_params(audio_config=None):
    default_config = {
        "format": "wav",
        "rate": 16000,
        "bits": 16,
        "channel": 1
    }
    
    audio_config = audio_config or default_config
    
    return {
        "user": {
            "uid": str(uuid.uuid4())
        },
        "audio": audio_config,
        "request": {
            "model_name": "bigmodel",
            "enable_itn": False,
            "enable_ddc": False,
            "enable_punc": True
        }
    }

# 构建二进制协议头和消息
def build_full_request_message(params):
    # 构建二进制协议头
    version_header_size = 0x11  # 版本1，头大小1
    message_type_flags = 0x10  # 消息类型1(full client request)，标志0
    serialization_compression = 0x10  # 序列化方法1(JSON)，压缩方法0(无压缩)
    reserved = 0x00
    
    header = struct.pack('>BBBB', version_header_size, message_type_flags, 
                         serialization_compression, reserved)
    
    # 请求参数转为JSON字节
    payload = json.dumps(params).encode('utf-8')
    
    # 计算payload大小
    payload_size = struct.pack('>I', len(payload))
    
    # 组合完整消息
    return header + payload_size + payload

def build_audio_message(audio_data, is_last=False):
    # 构建二进制协议头
    version_header_size = 0x11  # 版本1，头大小1
    
    # 如果是最后一包音频，设置标志位
    if is_last:
        message_type_flags = 0x22  # 消息类型2(audio only)，标志2(最后一包)
    else:
        message_type_flags = 0x20  # 消息类型2(audio only)，标志0
    
    serialization_compression = 0x00  # 序列化方法0(无)，压缩方法0(无压缩)
    reserved = 0x00
    
    header = struct.pack('>BBBB', version_header_size, message_type_flags, 
                         serialization_compression, reserved)
    
    # 计算payload大小
    payload_size = struct.pack('>I', len(audio_data))
    
    # 组合完整消息
    return header + payload_size + audio_data

# 解析火山引擎API响应
async def parse_response(response_data):
    if len(response_data) < 12:  # 至少需要头部(4) + 序列号(4) + payload大小(4)
        logger.error("响应数据不完整")
        return None
    
    # 解析响应头
    message_type = (response_data[1] >> 4) & 0x0F
    message_flags = response_data[1] & 0x0F
    
    # 提取sequence (4字节)
    sequence = struct.unpack('>I', response_data[4:8])[0]
    
    # 计算payload大小
    payload_size = struct.unpack('>I', response_data[8:12])[0]
    
    # 提取payload
    if len(response_data) < 12 + payload_size:
        logger.error("响应数据不完整")
        return None
    
    payload = response_data[12:12+payload_size]
    
    # 解析JSON结果
    try:
        result_json = json.loads(payload.decode('utf-8'))
        logger.info(f"序列号: {sequence}, 识别结果: {json.dumps(result_json, ensure_ascii=False)}")
        
        # 检查是否是最后一包
        is_last_packet = (message_flags & 0x02) != 0
        if is_last_packet:
            logger.info("这是最后一包响应")
            
        return {
            "sequence": sequence,
            "result": result_json,
            "is_last": is_last_packet
        }
    except Exception as e:
        logger.error(f"解析响应失败: {e}")
        return None

# 处理与火山引擎API的WebSocket连接
async def volcano_websocket_handler(client_ws: WebSocket, audio_config=None):
    # 生成连接ID
    connect_id = str(uuid.uuid4())
    
    # 构建请求头
    headers = {
        "X-Api-App-Key": APP_KEY,
        "X-Api-Access-Key": ACCESS_KEY,
        "X-Api-Resource-Id": RESOURCE_ID,
        "X-Api-Connect-Id": connect_id
    }
    
    try:
        # 连接到火山引擎API
        async with websockets.connect(VOLCANO_API_URL, extra_headers=headers) as volcano_ws:
            # 获取响应头中的logId
            log_id = volcano_ws.response_headers.get("X-Tt-Logid", "未知")
            logger.info(f"连接到火山引擎API成功，logId: {log_id}")
            
            # 发送full client request
            request_params = build_request_params(audio_config)
            full_request = build_full_request_message(request_params)
            await volcano_ws.send(full_request)
            
            # 创建两个任务：一个用于从客户端接收音频数据并转发，一个用于从火山引擎接收结果并转发
            async def forward_audio():
                try:
                    while True:
                        # 从客户端接收音频数据
                        data = await client_ws.receive_bytes()
                        
                        # 解析客户端消息
                        is_last = False
                        if len(data) >= 4:  # 至少包含一个标志位
                            # 假设客户端在第一个字节中设置了是否为最后一包的标志
                            is_last = (data[0] == 1)
                            # 实际音频数据从第二个字节开始
                            audio_data = data[1:]
                        else:
                            audio_data = data
                        
                        # 构建音频消息并发送给火山引擎
                        audio_message = build_audio_message(audio_data, is_last)
                        await volcano_ws.send(audio_message)
                        
                        if is_last:
                            logger.info("发送了最后一包音频数据")
                            break
                except WebSocketDisconnect:
                    logger.info("客户端断开连接")
                except Exception as e:
                    logger.error(f"转发音频数据时出错: {e}")
            
            async def forward_results():
                try:
                    while True:
                        # 从火山引擎接收识别结果
                        response = await volcano_ws.recv()
                        
                        # 解析响应
                        parsed = await parse_response(response)
                        if parsed:
                            # 将结果转发给客户端
                            await client_ws.send_json(parsed)
                            
                            # 如果是最后一包，结束任务
                            if parsed.get("is_last", False):
                                break
                except websockets.exceptions.ConnectionClosed:
                    logger.info("火山引擎API断开连接")
                except Exception as e:
                    logger.error(f"转发识别结果时出错: {e}")
            
            # 并发运行两个任务
            await asyncio.gather(forward_audio(), forward_results())
            
    except Exception as e:
        logger.error(f"连接火山引擎API失败: {e}")
        # 通知客户端出错
        await client_ws.send_json({"error": str(e)})

@app.websocket("/ws/asr")
async def websocket_endpoint(websocket: WebSocket):
    # 接受WebSocket连接
    await websocket.accept()
    
    # 生成客户端ID
    client_id = str(uuid.uuid4())
    active_connections[client_id] = websocket
    
    try:
        logger.info(f"客户端 {client_id} 已连接")
        
        # 等待客户端发送音频配置
        config_data = await websocket.receive_json()
        audio_config = config_data.get("audio_config")
        
        # 处理与火山引擎API的WebSocket连接
        await volcano_websocket_handler(websocket, audio_config)
        
    except WebSocketDisconnect:
        logger.info(f"客户端 {client_id} 断开连接")
    except Exception as e:
        logger.error(f"处理WebSocket连接时出错: {e}")
    finally:
        # 移除连接
        if client_id in active_connections:
            del active_connections[client_id]

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
