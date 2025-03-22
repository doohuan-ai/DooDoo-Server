# coding=utf-8

import asyncio
import websockets
import uuid
import json
import gzip
import copy

MESSAGE_TYPES = {11: "audio-only server response",
                 12: "frontend server response",
                 15: "error message from server"}
MESSAGE_TYPE_SPECIFIC_FLAGS = {0: "no sequence number",
                               1: "sequence number > 0",
                               2: "last message from server (seq < 0)",
                               3: "sequence number < 0"}
MESSAGE_SERIALIZATION_METHODS = {0: "no serialization",
                                 1: "JSON",
                                 15: "custom type"}
MESSAGE_COMPRESSIONS = {0: "no compression",
                        1: "gzip",
                        15: "custom compression method"}

appid = "3415704595"
token = "o2nrLg4vCSnrx4Me_N2oTVQrXcU6pLTZ"
cluster = "volcano_tts"
voice_type = "ICL_zh_female_huoponvhai_tob"
host = "openspeech.bytedance.com"
api_url = f"wss://{host}/api/v1/tts/ws_binary"

# version: b0001 (4 bits)
# header size: b0001 (4 bits)
# message type: b0001 (Full client request) (4bits)
# message type specific flags: b0000 (none) (4bits)
# message serialization method: b0001 (JSON) (4 bits)
# message compression: b0001 (gzip) (4bits)
# reserved data: 0x00 (1 byte)
default_header = bytearray(b'\x11\x10\x11\x00')

request_json = {
    "app": {
        "appid": appid,
        "token": "access_token",
        "cluster": cluster
    },
    "user": {
        "uid": "388808087185088"
    },
    "audio": {
        "voice_type": "xxx",
        "encoding": "mp3",
        "speed_ratio": 1.0,
        "volume_ratio": 1.0,
        "pitch_ratio": 1.0,
    },
    "request": {
        "reqid": "xxx",
        "text": "xxx",
        "text_type": "plain",
        "operation": "xxx"
    }
}


async def submit(text: str):
    submit_request_json = copy.deepcopy(request_json)
    submit_request_json["audio"]["voice_type"] = voice_type
    submit_request_json["request"]["reqid"] = str(uuid.uuid4())
    submit_request_json["request"]["operation"] = "submit"
    submit_request_json["request"]["text"] = text
    payload_bytes = str.encode(json.dumps(submit_request_json))
    payload_bytes = gzip.compress(payload_bytes)
    full_client_request = bytearray(default_header)
    full_client_request.extend((len(payload_bytes)).to_bytes(4, 'big'))  # payload size(4 bytes)
    full_client_request.extend(payload_bytes)  # payload
    
    header = {"Authorization": f"Bearer; {token}"}
    async with websockets.connect(api_url, additional_headers=header, ping_interval=None) as ws:
        await ws.send(full_client_request)
        while True:
            res = await ws.recv()
            async for chunk in parse_and_yield_response(res):
                yield chunk
            if await should_stop(res):
                break


async def should_stop(res):
    protocol_version = res[0] >> 4
    header_size = res[0] & 0x0f
    message_type = res[1] >> 4
    message_type_specific_flags = res[1] & 0x0f
    payload = res[header_size*4:]

    if message_type == 0xb:  # audio-only server response
        if message_type_specific_flags == 0:  # no sequence number as ACK
            return False
        sequence_number = int.from_bytes(payload[:4], "big", signed=True)
        return sequence_number < 0
    elif message_type == 0xf:  # error message
        return True
    return False


async def parse_and_yield_response(res):
    protocol_version = res[0] >> 4
    header_size = res[0] & 0x0f
    message_type = res[1] >> 4
    message_type_specific_flags = res[1] & 0x0f
    serialization_method = res[2] >> 4
    message_compression = res[2] & 0x0f
    payload = res[header_size*4:]

    if message_type == 0xb:  # audio-only server response
        if message_type_specific_flags == 0:  # no sequence number as ACK
            return
        sequence_number = int.from_bytes(payload[:4], "big", signed=True)
        payload_size = int.from_bytes(payload[4:8], "big", signed=False)
        audio_data = payload[8:]
        yield audio_data
    elif message_type == 0xf:  # error message
        code = int.from_bytes(payload[:4], "big", signed=False)
        msg_size = int.from_bytes(payload[4:8], "big", signed=False)
        error_msg = payload[8:]
        if message_compression == 1:
            error_msg = gzip.decompress(error_msg)
        error_msg = str(error_msg, "utf-8")
        print(f"Error: {error_msg}")


if __name__ == '__main__':
    text = "嘿，亲爱的小朋友，欢迎来到我们的奇妙世界！从今天起，你有了一个特别的朋友——就是我！"
    loop = asyncio.get_event_loop()
    loop.run_until_complete(submit(text))
