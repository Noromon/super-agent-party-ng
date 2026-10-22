# -*- coding: utf-8 -*-
"""语音通道（批 1c 自 server.py 整体迁出）：ASR 流式识别、TTS 连接编排、
VRM/字幕 WebSocket。

对外 API：router（四个 /ws/* 端点，由 server include_router 挂载）、
funasr_recognize_offline（media 路由复用）、tts_manager（连接数状态）。
状态（asr_connections/audio_buffer）为模块私产，消费方经属性访问。
"""
import asyncio
import base64
import json
import logging
import os
import struct
import tempfile
import uuid
from io import BytesIO
from typing import Any, Dict, List, Union

import websockets
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from openai import AsyncOpenAI

from py import auth as sap_auth
from py.defaults import FUNASR_WS_URL
from py.get_setting import load_settings

router = APIRouter()

# 存储活跃的ASR WebSocket连接
asr_connections = []

# 存储每个连接的音频帧数据
audio_buffer: Dict[str, Dict[str, Any]] = {}

def convert_audio_to_pcm16(audio_bytes: bytes, target_sample_rate: int = 16000) -> bytes:
    """
    将音频数据转换为PCM16格式，采样率16kHz
    """
    import numpy as np
    from scipy.io import wavfile
    try:
        # 创建临时文件
        with tempfile.NamedTemporaryFile(suffix='.wav', delete=False) as temp_file:
            temp_file.write(audio_bytes)
            temp_file_path = temp_file.name
        
        try:
            # 读取音频文件
            sample_rate, audio_data = wavfile.read(temp_file_path)
            
            # 转换为单声道
            if len(audio_data.shape) > 1:
                audio_data = np.mean(audio_data, axis=1)
            
            # 转换为float32进行重采样
            if audio_data.dtype != np.float32:
                if audio_data.dtype == np.int16:
                    audio_data = audio_data.astype(np.float32) / 32768.0
                elif audio_data.dtype == np.int32:
                    audio_data = audio_data.astype(np.float32) / 2147483648.0
                else:
                    audio_data = audio_data.astype(np.float32)
            
            # 重采样到目标采样率
            if sample_rate != target_sample_rate:
                from scipy.signal import resample
                num_samples = int(len(audio_data) * target_sample_rate / sample_rate)
                audio_data = resample(audio_data, num_samples)
            
            # 转换为int16 PCM格式
            audio_data = (audio_data * 32767).astype(np.int16)
            
            return audio_data.tobytes()
            
        finally:
            # 删除临时文件
            os.unlink(temp_file_path)
            
    except Exception as e:
        logging.getLogger("app").info(f"Audio conversion error: {e}")
        # 如果转换失败，尝试直接返回原始数据
        return audio_bytes

async def funasr_recognize(audio_data: bytes, funasr_settings: dict,ws: WebSocket,frame_id) -> str:
    """
    使用FunASR进行语音识别
    """
    try:
        # 获取FunASR服务器地址
        funasr_url = funasr_settings.get('funasr_ws_url', FUNASR_WS_URL)
        hotwords = funasr_settings.get('hotwords', '')
        if not funasr_url.startswith('ws://') and not funasr_url.startswith('wss://'):
            funasr_url = f"ws://{funasr_url}"
        
        # 连接到FunASR服务器
        async with websockets.connect(funasr_url) as websocket:
            logging.getLogger("app").info(f"Connected to FunASR server: {funasr_url}")
            
            # 1. 发送初始化配置
            init_config = {
                "chunk_size": [5, 10, 5],
                "wav_name": "python_client",
                "is_speaking": True,
                "chunk_interval": 10,
                "mode": "offline",  # 使用离线模式
                "hotwords": hotwords_to_json(hotwords),
                "use_itn": True
            }
            
            await websocket.send(json.dumps(init_config))
            logging.getLogger("app").info("Sent init config")
            
            # 2. 转换音频数据为PCM16格式
            pcm_data = convert_audio_to_pcm16(audio_data)
            logging.getLogger("app").info(f"PCM data length: {len(pcm_data)} bytes")
            
            # 3. 分块发送音频数据
            chunk_size = 960  # 30ms的音频数据 (16000 * 0.03 * 2 = 960字节)
            total_sent = 0
            
            while total_sent < len(pcm_data):
                chunk_end = min(total_sent + chunk_size, len(pcm_data))
                chunk = pcm_data[total_sent:chunk_end]
                
                # 发送二进制PCM数据
                await websocket.send(chunk)
                total_sent = chunk_end
            
            logging.getLogger("app").info(f"Sent all audio data: {total_sent} bytes")
            
            # 4. 发送结束信号
            end_config = {
                "is_speaking": False,
            }
            
            await websocket.send(json.dumps(end_config))
            logging.getLogger("app").info("Sent end signal")
            
            # 5. 等待识别结果
            result_text = ""
            timeout_count = 0
            max_timeout = 200  # 最大等待20秒
            
            while timeout_count < max_timeout:
                try:
                    # 等待响应消息
                    response = await asyncio.wait_for(websocket.recv(), timeout=0.1)
                    
                    try:
                        # 尝试解析JSON响应
                        json_response = json.loads(response)
                        logging.getLogger("app").info(f"Received response: {json_response}")
                        
                        if 'text' in json_response:
                            text = json_response['text']
                            if text and text.strip():
                                result_text += text
                                logging.getLogger("app").info(f"Got text: {text}")
                                # 发送结果
                                await ws.send_json({
                                    "type": "transcription",
                                    "id": frame_id,
                                    "text": result_text,
                                    "is_final": True
                                })
                            # 检查是否为最终结果
                            if json_response.get('is_final', False):
                                logging.getLogger("app").info("Got final result")
                                break
                                
                    except json.JSONDecodeError:
                        # 如果不是JSON格式，可能是二进制数据，忽略
                        logging.getLogger("app").info(f"Non-JSON response: {response}")
                        pass
                        
                except asyncio.TimeoutError:
                    timeout_count += 1
                    continue
                except websockets.exceptions.ConnectionClosed:
                    logging.getLogger("app").info("WebSocket connection closed")
                    break
            
            if not result_text:
                logging.getLogger("app").info("No recognition result received")
                return ""
            
            return result_text.strip()
            
    except Exception as e:
        logging.getLogger("app").info(f"FunASR recognition error: {e}")
        return f"FunASR识别错误: {str(e)}"

def hotwords_to_json(input_str):
    # 初始化结果字典
    result = {}
    
    # 按行分割输入字符串
    lines = input_str.split('\n')
    
    for line in lines:
        # 清理行首尾的空白字符
        cleaned_line = line.strip()
        
        # 跳过空行
        if not cleaned_line:
            continue
            
        # 分割词语和权重
        parts = cleaned_line.rsplit(' ', 1)  # 从右边分割一次
        
        if len(parts) != 2:
            continue  # 跳过格式不正确的行
            
        word = parts[0].strip()
        try:
            weight = int(parts[1])
        except ValueError:
            continue  # 跳过权重不是数字的行
            
        # 添加到结果字典
        result[word] = weight
    
    # 转换为JSON字符串
    return json.dumps(result, ensure_ascii=False)

# ASR WebSocket处理
async def _close_ws_quiet(ws):
    """T-3: 关闭旧 websockets 连接并安全弃引用（异常静默；close 幂等）。"""
    if ws:
        try:
            await ws.close()
        except Exception:
            pass
    return None


@router.websocket("/ws/asr")
async def asr_websocket_endpoint(websocket: WebSocket):
    if not sap_auth.ws_auth_ok(websocket):
        await websocket.close(code=4401)
        return
    await websocket.accept()
    
    # 生成唯一的连接ID
    connection_id = str(uuid.uuid4())
    asr_connections.append(websocket)
    funasr_websocket = None
    # 新增：连接状态跟踪变量
    asr_engine = None
    funasr_mode = None
    
    try:
        # 处理消息
        async for message in websocket.iter_json():
            msg_type = message.get("type")
            
            if msg_type == "init":
                # 加载设置
                settings = await load_settings()
                asr_settings = settings.get('asrSettings', {})
                asr_engine = asr_settings.get('engine', 'openai')  # 存储引擎类型
                if asr_engine == "funasr":
                    funasr_mode = asr_settings.get('funasr_mode', 'openai')  # 存储模式
                    if funasr_mode == "2pass" or funasr_mode == "online":
                        # 获取FunASR服务器地址
                        funasr_url = asr_settings.get('funasr_ws_url', FUNASR_WS_URL)
                        if not funasr_url.startswith('ws://') and not funasr_url.startswith('wss://'):
                            funasr_url = f"ws://{funasr_url}"
                        try:
                            funasr_websocket = await websockets.connect(funasr_url)
                        except Exception as e:
                            funasr_websocket = None
                            logging.getLogger("app").info(f"连接FunASR失败: {e}")
                await websocket.send_json({
                    "type": "init_response",
                    "status": "ready"
                })
                print("ASR WebSocket connected:",asr_engine)
            elif msg_type == "audio_start":
                frame_id = message.get("id")
                # 加载设置
                settings = await load_settings()
                asr_settings = settings.get('asrSettings', {})
                asr_engine = asr_settings.get('engine', 'openai')  # 存储引擎类型
                if asr_engine == "funasr":
                    funasr_mode = asr_settings.get('funasr_mode', '2pass')  # 存储模式
                    hotwords = asr_settings.get('hotwords', '')
                    if funasr_mode == "2pass":
                        # 获取FunASR服务器地址
                        funasr_url = asr_settings.get('funasr_ws_url', FUNASR_WS_URL)
                        if not funasr_url.startswith('ws://') and not funasr_url.startswith('wss://'):
                            funasr_url = f"ws://{funasr_url}"
                        try:
                            if not funasr_websocket:
                                # 连接到FunASR服务器 
                                funasr_websocket = await websockets.connect(funasr_url)
                            # 1. 发送初始化配置
                            init_config = {
                                "chunk_size": [5, 10, 5],
                                "wav_name": "python_client",
                                "is_speaking": True,
                                "chunk_interval": 10,
                                "mode": funasr_mode,  
                                "hotwords": hotwords_to_json(hotwords),
                                "use_itn": True
                            }
                            await funasr_websocket.send(json.dumps(init_config))
                            logging.getLogger("app").info("Sent init config")
                            # 2. 开启一个异步任务处理FunASR的响应
                            asyncio.create_task(handle_funasr_response(funasr_websocket, websocket))
                        except Exception as e:
                            logging.getLogger("app").info(f"连接FunASR失败: {e}")
                            await websocket.send_json({
                                "type": "error",
                                "message": f"无法连接FunASR服务器: {str(e)}"
                            })
                            # 标记连接失败，避免后续操作
                            funasr_websocket = None
                    else:
                        # T-3: 换模式=关闭旧 funasr 会话（否则悬挂泄漏+读取任务永挂）
                        funasr_websocket = await _close_ws_quiet(funasr_websocket)
                else:
                    # T-3: 换引擎=关闭旧 funasr 会话
                    funasr_websocket = await _close_ws_quiet(funasr_websocket)
            # 修改点：增加流式音频处理前的检查
            elif msg_type == "audio_stream":
                frame_id = message.get("id")
                audio_base64 = message.get("audio")

                # 关键检查：确保funasr_websocket已初始化
                if not funasr_websocket:
                    continue  # 跳过当前消息处理

                if audio_base64:
                    # 1. Base64 解码 → 得到二进制 PCM (Int16)
                    pcm_data = base64.b64decode(audio_base64)

                    # 2. 直接转发二进制给 FunASR
                    try:
                        await funasr_websocket.send(pcm_data)
                    except websockets.exceptions.ConnectionClosed:
                        funasr_websocket = None
                        # 加载设置
                        settings = await load_settings()
                        asr_settings = settings.get('asrSettings', {})
                        asr_engine = asr_settings.get('engine', 'openai')  # 存储引擎类型
                        if asr_engine == "funasr":
                            funasr_mode = asr_settings.get('funasr_mode', '2pass')  # 存储模式
                            if funasr_mode == "2pass":
                                # 获取FunASR服务器地址
                                funasr_url = asr_settings.get('funasr_ws_url', FUNASR_WS_URL)
                                if not funasr_url.startswith('ws://') and not funasr_url.startswith('wss://'):
                                    funasr_url = f"ws://{funasr_url}"
                                try:
                                    funasr_websocket = await websockets.connect(funasr_url)
                                except Exception as e:
                                    funasr_websocket = None
                                    logging.getLogger("app").info(f"连接FunASR失败: {e}")
            elif msg_type == "audio_complete":
                # 处理完整的音频数据（非流式模式）
                frame_id = message.get("id")
                audio_b64 = message.get("audio")
                audio_format = message.get("format", "wav")
                
                if audio_b64:
                    # 解码base64数据
                    audio_bytes = base64.b64decode(audio_b64)
                    logging.getLogger("app").info(f"Received audio data: {len(audio_bytes)} bytes, format: {audio_format}")
                    
                    try:
                        # 加载设置
                        settings = await load_settings()
                        asr_settings = settings.get('asrSettings', {})
                        asr_engine = asr_settings.get('engine', 'openai')
                        
                        result = ""
                        
                        if asr_engine == "openai":
                            # OpenAI ASR
                            audio_file = BytesIO(audio_bytes)
                            audio_file.name = f"audio.{audio_format}"
                            
                            client = AsyncOpenAI(
                                api_key=asr_settings.get('api_key', ''),
                                base_url=asr_settings.get('base_url', '') or "https://api.openai.com/v1"
                            )
                            response = await client.audio.transcriptions.create(
                                file=audio_file,
                                model=asr_settings.get('model', 'whisper-1'),
                            )
                            result = response.text
                            # 发送结果
                            await websocket.send_json({
                                "type": "transcription",
                                "id": frame_id,
                                "text": result,
                                "is_final": True
                            })
                        elif asr_engine == "funasr":
                            # FunASR
                            logging.getLogger("app").info("Using FunASR engine")
                            funasr_mode = asr_settings.get('funasr_mode', 'offline')
                            if funasr_mode == "offline":
                                result = await funasr_recognize(audio_bytes, asr_settings,websocket,frame_id)
                            else:
                                # 关键检查：确保连接有效
                                if not funasr_websocket:
                                    continue
                                
                                # 4. 发送结束信号
                                end_config = {
                                    "is_speaking": False  # 只需发送必要的结束标记
                                }
                                try:
                                    await funasr_websocket.send(json.dumps(end_config))
                                    logging.getLogger("app").info("Sent end signal")
                                except websockets.exceptions.ConnectionClosed:
                                    logging.getLogger("app").info("FunASR连接已关闭，无法发送结束信号")
                            funasr_websocket = None

                        elif asr_engine == "sherpa":
                            from py.sherpa_asr import sherpa_recognize
                            # 新增Sherpa处理
                            result = await sherpa_recognize(audio_bytes)
                            logging.getLogger("app").info(f"Sherpa result: {result}")
                            await websocket.send_json({
                                "type": "transcription",
                                "id": frame_id,
                                "text": result,
                                "is_final": True
                            })

                    except WebSocketDisconnect:
                        logging.getLogger("app").info(f"ASR WebSocket disconnected: {connection_id}")
                    except Exception as e:
                        logging.getLogger("app").info(f"ASR WebSocket error: {e}")
    finally:
        # 清理资源
        if connection_id in audio_buffer:
            del audio_buffer[connection_id]
        if websocket in asr_connections:
            asr_connections.remove(websocket)
        # 新增：确保关闭FunASR连接（T-3: 静默关闭，失败不阻断其余清理）
        await _close_ws_quiet(funasr_websocket)


async def funasr_recognize_offline(audio_data: bytes, funasr_settings: dict) -> str:
    """
    FunASR离线识别（专为HTTP接口优化）
    """
    try:
        # 获取FunASR服务器地址
        funasr_url = funasr_settings.get('funasr_ws_url', FUNASR_WS_URL)
        hotwords = funasr_settings.get('hotwords', '')
        if not funasr_url.startswith('ws://') and not funasr_url.startswith('wss://'):
            funasr_url = f"ws://{funasr_url}"
        
        # 连接到FunASR服务器
        async with websockets.connect(funasr_url) as websocket:
            logging.getLogger("app").info(f"Connected to FunASR server: {funasr_url}")
            
            # 1. 发送初始化配置（强制离线模式）
            init_config = {
                "chunk_size": [5, 10, 5],
                "wav_name": "http_client",
                "is_speaking": True,
                "chunk_interval": 10,
                "mode": "offline",  # 强制使用离线模式
                "hotwords": hotwords_to_json(hotwords),
                "use_itn": True
            }
            
            await websocket.send(json.dumps(init_config))
            logging.getLogger("app").info("Sent init config for offline mode")
            
            # 2. 转换音频数据为PCM16格式
            pcm_data = convert_audio_to_pcm16(audio_data)
            logging.getLogger("app").info(f"PCM data length: {len(pcm_data)} bytes")
            
            # 3. 分块发送音频数据
            chunk_size = 960  # 30ms的音频数据
            total_sent = 0
            
            while total_sent < len(pcm_data):
                chunk_end = min(total_sent + chunk_size, len(pcm_data))
                chunk = pcm_data[total_sent:chunk_end]
                await websocket.send(chunk)
                total_sent = chunk_end
            
            logging.getLogger("app").info(f"Sent all audio data: {total_sent} bytes")
            
            # 4. 发送结束信号
            end_config = {
                "is_speaking": False,
            }
            await websocket.send(json.dumps(end_config))
            logging.getLogger("app").info("Sent end signal")
            
            # 5. 等待识别结果
            result_text = ""
            timeout_count = 0
            max_timeout = 300  # 最大等待30秒（HTTP接口可以等待更久）
            
            while timeout_count < max_timeout:
                try:
                    response = await asyncio.wait_for(websocket.recv(), timeout=0.1)
                    
                    try:
                        json_response = json.loads(response)
                        logging.getLogger("app").info(f"Received response: {json_response}")
                        
                        if 'text' in json_response:
                            text = json_response['text']
                            if text and text.strip():
                                result_text += text
                                logging.getLogger("app").info(f"Got text: {text}")
                            
                            # 检查是否为最终结果
                            if json_response.get('is_final', False):
                                logging.getLogger("app").info("Got final result")
                                break
                                
                    except json.JSONDecodeError:
                        # 忽略非JSON格式的响应
                        pass
                        
                except asyncio.TimeoutError:
                    timeout_count += 1
                    continue
                except websockets.exceptions.ConnectionClosed:
                    logging.getLogger("app").info("WebSocket connection closed")
                    break
            
            if not result_text:
                logging.getLogger("app").info("No recognition result received")
                return ""
            
            return result_text.strip()
            
    except Exception as e:
        logging.getLogger("app").info(f"FunASR offline recognition error: {e}")
        return f"FunASR识别错误: {str(e)}"


async def handle_funasr_response(funasr_websocket, 
                               client_websocket: WebSocket):
    """
    处理 FunASR 服务器的响应，并将结果转发给客户端
    """
    try:
        async for message in funasr_websocket:
            try:
                if funasr_websocket:
                    # FunASR 返回的数据可能是 JSON 或二进制
                    if isinstance(message, bytes):
                        message = message.decode('utf-8')
                    
                    data = json.loads(message)
                    logging.getLogger("app").info(f"FunASR response: {data}")
                    # 解析 FunASR 响应
                    if "text" in data:  # 普通识别结果
                        if data.get('mode', '') == "2pass-online":
                            await client_websocket.send_json({
                                "type": "transcription",
                                "text": data["text"],
                                "is_final": False
                            })
                        else:
                            await client_websocket.send_json({
                                "type": "transcription",
                                "text": data["text"],
                                "is_final": True
                            })
                    elif "mode" in data:  # 初始化响应
                        logging.getLogger("app").info(f"FunASR initialized: {data}")
                    else:
                        logging.getLogger("app").info(f"Unknown FunASR response: {data}")
                else:
                    # 如果 FunASR 连接关闭，发送错误消息，退出循环，结束任务
            
                    break
            except json.JSONDecodeError:
                logging.getLogger("app").info(f"FunASR sent non-JSON data: {message[:100]}...")
            except Exception as e:
                logging.getLogger("app").info(f"Error processing FunASR response: {e}")
                break

    except websockets.exceptions.ConnectionClosed:
        logging.getLogger("app").info("FunASR connection closed")
    except Exception as e:
        logging.getLogger("app").info(f"FunASR handler error: {e}")
    finally:
        await funasr_websocket.close()

class TTSConnectionManager:
    def __init__(self):
        self.main_connections: List[WebSocket] = []
        self.vrm_connections: List[WebSocket] = []
        self.overlay_connections: list[WebSocket] = []

    async def connect_main(self, websocket: WebSocket):
        await websocket.accept()
        self.main_connections.append(websocket)
        logging.info(f"Main interface connected. Total: {len(self.main_connections)}")

    async def connect_vrm(self, websocket: WebSocket):
        await websocket.accept()
        self.vrm_connections.append(websocket)
        logging.info(f"VRM interface connected. Total: {len(self.vrm_connections)}")

    def disconnect_main(self, websocket: WebSocket):
        if websocket in self.main_connections:
            self.main_connections.remove(websocket)

    def disconnect_vrm(self, websocket: WebSocket):
        if websocket in self.vrm_connections:
            self.vrm_connections.remove(websocket)

    # 批 1c 迁出时清理：此处原有第一版 broadcast_to_vrm（只发 vrm_connections），
    # 被下方第二版（二进制→VRM、文本→VRM+字幕）覆盖 = 死代码，已删除。

    async def send_to_main(self, message: str):
        if not self.main_connections:
            return
        disconnected = []
        for connection in self.main_connections:
            try:
                await connection.send_text(message)
            except:
                disconnected.append(connection)
        for conn in disconnected:
            self.disconnect_main(conn)

    async def connect_overlay(self, websocket: WebSocket):
        """字幕页专用连接"""
        await websocket.accept()
        self.overlay_connections.append(websocket)

    def disconnect_overlay(self, websocket: WebSocket):
        if websocket in self.overlay_connections:
            self.overlay_connections.remove(websocket)

    async def broadcast_to_vrm(self, message: Union[str, bytes]):
        """核心广播逻辑：区分发送内容"""
        # 1. 如果是二进制（音频流），只发给真正的 VRM 页面
        if isinstance(message, bytes):
            for conn in list(self.vrm_connections):
                try: await conn.send_bytes(message)
                except: self.disconnect_vrm(conn)
        
        # 2. 如果是字符串（指令/文字），发给 VRM 页面 和 字幕页面
        else:
            # 发给 VRM 窗口（同步表情、UI等）
            for conn in list(self.vrm_connections):
                try: await conn.send_text(message)
                except: self.disconnect_vrm(conn)
            
            # 发给字幕窗口（显示文字）
            for conn in list(self.overlay_connections):
                try: await conn.send_text(message)
                except: self.disconnect_overlay(conn)


tts_manager = TTSConnectionManager()

# 批 1c 迁出遗留的模块级 broadcast_to_vrm 死定义（RA-12/29，S66 删除）：
# 全部调用点均走 tts_manager.broadcast_to_vrm 方法，本孤儿函数从未被引用。

from py.vts_manager import vts_instance

@router.websocket("/ws/tts")
async def tts_websocket_endpoint(websocket: WebSocket):
    if not sap_auth.ws_auth_ok(websocket):
        await websocket.close(code=4401)
        return
    await tts_manager.connect_main(websocket)
    try:
        while True:
            msg = await websocket.receive()
            
            # 1. 处理二进制（音频流）
            if "bytes" in msg:
                data_bytes = msg["bytes"]
                if len(data_bytes) > 4:
                    try:
                        json_len = struct.unpack('<I', data_bytes[:4])[0]
                        metadata_bytes = data_bytes[4 : 4 + json_len]
                        audio_file_bytes = data_bytes[4 + json_len :]
                        
                        if vts_instance.is_running and len(audio_file_bytes) > 0:
                            import subprocess
                            import imageio_ffmpeg  # 神器：自带免安装版 ffmpeg
                            # ================= 终极解码方案 =================
                            def decode_audio_to_pcm(b_data):
                                # 获取 imageio_ffmpeg 自带的免安装 ffmpeg 路径
                                ffmpeg_exe = imageio_ffmpeg.get_ffmpeg_exe()
                                
                                # 使用极速底层管道：输入任意格式字节流，输出 16-bit 24000Hz 单声道 PCM
                                process = subprocess.Popen([
                                    ffmpeg_exe,
                                    '-i', 'pipe:0',       # 从标准输入读取 (就是我们的 b_data)
                                    '-f', 's16le',        # 强制输出格式：16-bit signed little-endian PCM
                                    '-ar', '24000',       # 强制采样率：24000Hz
                                    '-ac', '1',           # 强制单声道
                                    'pipe:1'              # 输出到标准输出
                                ], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
                                
                                pcm_raw_bytes, _ = process.communicate(input=b_data)
                                return pcm_raw_bytes
                            # ===============================================

                            # 异步线程执行，绝对不卡主线程
                            pcm_raw_bytes = await asyncio.to_thread(decode_audio_to_pcm, audio_file_bytes)
                            
                            if pcm_raw_bytes:
                                asyncio.create_task(vts_instance.drive_mouth(pcm_raw_bytes))
                        
                        # 转发给前端VRM
                        await tts_manager.broadcast_to_vrm(data_bytes)
                        
                    except Exception as e:
                        logging.error(f"万能音频解码出错: {e}")
            
            # 2. 处理文本（指令/表情）
            elif "text" in msg:
                try:
                    payload = json.loads(msg["text"]) 
                    msg_type = payload.get("type")
                    
                    if msg_type == "startVTS_Driver":
                        # 1. 获取连接结果
                        success = await vts_instance.connect(payload.get("data", {}))
                        
                        # 2. 将结果反馈给前端
                        feedback = {
                            "type": "vts_connection_status",
                            "data": {
                                "success": success,
                                "message": "Connected to VTube Studio" if success else "Failed to connect. Please make sure VTube Studio is running and the API is enabled."
                            }
                        }
                        await websocket.send_text(json.dumps(feedback))
                        
                    elif msg_type == "stopVTS_Driver":
                        await vts_instance.stop()
                        # 停止也可以发一个反馈
                        await websocket.send_text(json.dumps({
                            "type": "vts_connection_status",
                            "data": {"success": False, "message": "VTS Disconnected"}
                        }))
                    elif msg_type == "startSpeaking":
                        if vts_instance.is_running:
                            data_content = payload.get("data", {})
                            expressions = data_content.get("expressions",[])
                            for exp in expressions:
                                asyncio.create_task(vts_instance.trigger_hotkey(exp))

                    await tts_manager.broadcast_to_vrm(msg["text"])
                except Exception as e:
                    logging.error(f"[PY] WS Text Error: {e}")

    except Exception as e:
        logging.error(f"[PY] WS Global Error: {e}")
    finally:
        tts_manager.disconnect_main(websocket)

@router.websocket("/ws/vrm")
async def vrm_websocket_endpoint(websocket: WebSocket):
    if not sap_auth.ws_auth_ok(websocket):
        await websocket.close(code=4401)
        return
    """VRM 窗口 WebSocket：接收主窗口发来的数据"""
    await tts_manager.connect_vrm(websocket)
    try:
        while True:
            msg = await websocket.receive()
            if "text" in msg:
                # 处理来自 VRM 的反馈（如 requestAudioData 或 animationComplete）
                data = json.loads(msg["text"])
                if data.get('type') == 'animationComplete':
                    await tts_manager.send_to_main(msg["text"])
            # VRM 窗口通常不主动给主窗口发二进制，所以这里暂不处理 bytes
    except WebSocketDisconnect:
        tts_manager.disconnect_vrm(websocket)
    except Exception as e:
        logging.error(f"WS error in VRM: {e}")
        tts_manager.disconnect_vrm(websocket)

@router.websocket("/ws/subtitles")
async def subtitles_websocket_endpoint(websocket: WebSocket):
    if not sap_auth.ws_auth_ok(websocket):
        await websocket.close(code=4401)
        return
    """字幕叠加层专用端点：不参与音频播放判断"""
    await tts_manager.connect_overlay(websocket)
    try:
        while True:
            await websocket.receive_text() # 保持心跳
    except WebSocketDisconnect:
        tts_manager.disconnect_overlay(websocket)

# 修改状态接口，让前端也能感知 VTS 是否连接（虽然不影响静音判断）





# 添加状态存储
