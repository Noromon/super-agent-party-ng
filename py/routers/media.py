# -*- coding: utf-8 -*-
"""Media endpoints (TTS / ASR / audio assets) moved verbatim out of
server.py in the R1 router migration (audit 09 item 6).  Process state
defined by server is reached through the module object bound below
(`_srv`, fully initialised long before these handlers run); shared
library/stdlib names are imported here exactly as server imported them.
server imports this module, never the other way around.  Legacy
complexity exemptions: see pyproject per-file-ignores (M-3 will split
the big handlers instead of grandfathering forever).
"""
import sys as _sys
import asyncio
import base64
import json
import os
import platform
import re
import requests
import tempfile
import uuid
from fastapi import File, Form, HTTPException, Request, UploadFile
from fastapi.responses import JSONResponse, StreamingResponse
from io import BytesIO
from openai import AsyncOpenAI
from pathlib import Path
from py.defaults import GSV_TTS_URL
from py.get_setting import TOOL_TEMP_DIR, UPLOAD_FILES_DIR, convert_to_opus_simple, load_settings
from py.load_files import sanitize_url
from py.vts_manager import vts_instance
from fastapi import APIRouter

# server runs as __main__ when launched directly; bind the module OBJECT
# once so attribute access always sees current process state
_srv = _sys.modules.get('server') or _sys.modules['__main__']

router = APIRouter()

@router.post("/asr")
async def asr_transcription(
    audio: UploadFile = File(...),
    format: str = Form(default="auto")
):
    """
    HTTP版本的ASR接口
    支持多种音频格式，根据配置自动选择ASR引擎
    """
    # 声明使用全局缓存

    try:
        # 1. 读取上传的音频文件
        audio_bytes = await audio.read()
        print(f"Received audio file: {audio.filename}, size: {len(audio_bytes)} bytes")
        
        # 2. 自动检测格式
        if format == "auto":
            if audio.filename:
                file_ext = audio.filename.split('.')[-1].lower()
                format = file_ext if file_ext in ['wav', 'mp3', 'flac', 'ogg', 'm4a'] else 'wav'
            else:
                format = 'wav'
        
        # 3. 加载设置 (为了性能，可以直接使用全局变量 settings，或者重新加载)
        current_settings = await load_settings()
        asr_settings = current_settings.get('asrSettings', {})
        asr_engine = asr_settings.get('engine', 'openai')
        
        result = ""
        
        # ==========================================
        # ASR 引擎分支：OpenAI (Whisper)
        # ==========================================
        if asr_engine == "openai":
            api_key = asr_settings.get('api_key', '')
            base_url = asr_settings.get('base_url', '') or "https://api.openai.com/v1"
            
            if not api_key:
                raise HTTPException(status_code=400, detail="OpenAI ASR API密钥未配置")

            # --- 核心改进：使用缓存的客户端 ---
            cache_key = (api_key, base_url)
            if cache_key not in _srv.openai_asr_clients_cache:
                print(f"Initializing new OpenAI ASR Client for: {base_url}")
                _srv.openai_asr_clients_cache[cache_key] = AsyncOpenAI(
                    api_key=api_key,
                    base_url=base_url
                )
            client = _srv.openai_asr_clients_cache[cache_key]
            # --------------------------------

            print(f"Using OpenAI ASR engine ({asr_settings.get('model', 'whisper-1')})")
            
            # 包装音频数据
            audio_file = BytesIO(audio_bytes)
            # OpenAI SDK 要求文件必须有特定的名字后缀来判断类型
            audio_file.name = f"audio.{format}"
            
            response = await client.audio.transcriptions.create(
                file=audio_file,
                model=asr_settings.get('model', 'whisper-1'),
            )
            result = response.text
            
        # ==========================================
        # ASR 引擎分支：FunASR
        # ==========================================
        elif asr_engine == "funasr":
            print("Using FunASR engine (offline mode)")
            # 假设 funasr_recognize_offline 内部已处理好性能问题
            result = await _srv.funasr_recognize_offline(audio_bytes, asr_settings)
            
        # ==========================================
        # ASR 引擎分支：Sherpa (本地)
        # ==========================================
        elif asr_engine == "sherpa":
            from py.sherpa_asr import sherpa_recognize
            print("Using Sherpa ASR engine")
            # Sherpa 通常是本地模型推理，损耗在于 CPU/GPU，不在连接建立
            result = await sherpa_recognize(audio_bytes)
        

        else:
            return JSONResponse(
                status_code=400,
                content={
                    "success": False,
                    "error": f"不支持的ASR引擎: {asr_engine}",
                    "text": ""
                }
            )
        
        # 4. 返回识别结果
        return JSONResponse(
            content={
                "success": True,
                "text": result.strip() if result else "",
                "engine": asr_engine,
                "format": format
            }
        )
        
    except Exception as e:
        print(f"ASR HTTP interface error: {e}")
        import traceback
        traceback.print_exc()
        
        return JSONResponse(
            status_code=500,
            content={
                "success": False,
                "error": str(e),
                "text": ""
            }
        )


@router.get("/tts/status")
async def get_tts_status():
    return {
        "vrm_connections": len(_srv.tts_manager.vrm_connections),
        "vts_active": vts_instance.is_running, # 新增
        "overlay_connections": len(_srv.tts_manager.overlay_connections),
        "main_connections": len(_srv.tts_manager.main_connections)
    }


@router.post("/tts")
async def text_to_speech(request: Request):
    import edge_tts
    import subprocess
    
    # 声明全局缓存和客户端

    try:
        data = await request.json()
        text = data.get('text', '')
        if not text:
            return JSONResponse(status_code=400, content={"error": "Text is empty"})
        
        # 移动端专用：强制使用opus格式
        mobile_optimized = data.get('mobile_optimized', False)
        target_format = "opus" if mobile_optimized else data.get('format', 'mp3')
        
        new_voice = data.get('voice', 'default')
        tts_settings = data.get('ttsSettings', {})
        
        # 处理声音配置继承逻辑
        if new_voice in tts_settings.get('newtts', {}) and new_voice != 'default':
            voice_settings = tts_settings['newtts'][new_voice]
            parent_settings = tts_settings
            
            inherited_fields = ['api_key', 'base_url', 'model', 'selectedProvider', 'vendor']
            for field in inherited_fields:
                child_value = voice_settings.get(field, '')
                parent_value = parent_settings.get(field, '')
                if not child_value and parent_value:
                    voice_settings[field] = parent_value
            
            selected_provider_id = voice_settings.get('selectedProvider')
            if selected_provider_id and not voice_settings.get('api_key'):
                model_providers = parent_settings.get('modelProviders', [])
                for provider in model_providers:
                    if provider.get('id') == selected_provider_id:
                        voice_settings['api_key'] = provider.get('apiKey', '')
                        voice_settings['base_url'] = provider.get('url', '')
                        voice_settings['model'] = provider.get('modelId', '')
                        voice_settings['vendor'] = provider.get('vendor', '')
                        break
            tts_settings = voice_settings

        index = data.get('index', 0)
        tts_engine = tts_settings.get('engine', 'edgetts')
                
        print(f"TTS请求 - 引擎: {tts_engine}, 格式: {target_format}, 移动端优化: {mobile_optimized}")
                
        # ==========================================
        # 1. EdgeTTS 引擎
        # ==========================================
        if tts_engine == 'edgetts':
            edgettsLanguage = tts_settings.get('edgettsLanguage', 'zh-CN')
            edgettsVoice = tts_settings.get('edgettsVoice', 'XiaoyiNeural')
            rate = tts_settings.get('edgettsRate', 1.0)
            full_voice_name = f"{edgettsLanguage}-{edgettsVoice}"
            
            if mobile_optimized:
                rate = min(rate * 0.95, 1.1)
            
            rate_text = "+0%"
            if rate >= 1.0:
                rate_text = f"+{int((rate - 1.0) * 100)}%"
            elif rate < 1.0:
                rate_text = f"-{int((1.0 - rate) * 100)}%"
            
            async def generate_audio():
                communicate = edge_tts.Communicate(text, full_voice_name, rate=rate_text)
                if target_format == "opus":
                    audio_chunks = []
                    async for chunk in communicate.stream():
                        if chunk["type"] == "audio":
                            audio_chunks.append(chunk["data"])
                    
                    full_audio = b''.join(audio_chunks)
                    convert_result = await asyncio.to_thread(convert_to_opus_simple, full_audio)
                    opus_audio = convert_result[0] if isinstance(convert_result, tuple) else convert_result
                    
                    chunk_size = 4096
                    for i in range(0, len(opus_audio), chunk_size):
                        yield opus_audio[i:i + chunk_size]
                else:
                    async for chunk in communicate.stream():
                        if chunk["type"] == "audio":
                            yield chunk["data"]

            media_type = "audio/ogg" if target_format == "opus" else "audio/mpeg"
            filename = f"tts_{index}.opus" if target_format == "opus" else f"tts_{index}.mp3"
            
            return StreamingResponse(
                generate_audio(),
                media_type=media_type,
                headers={"Content-Disposition": f"inline; filename={filename}", "X-Audio-Index": str(index), "X-Audio-Format": target_format}
            )

        # ==========================================
        # 2. CustomTTS 引擎 (使用全局连接池)
        # ==========================================
        elif tts_engine == 'customTTS':
            key_text = tts_settings.get('customTTSKeyText', 'text')
            key_speaker = tts_settings.get('customTTSKeySpeaker', 'speaker')
            key_speed = tts_settings.get('customTTSKeySpeed', 'speed')
            speaker_value = tts_settings.get('customTTSspeaker', '')
            speed_value = tts_settings.get('customTTSspeed', 1.0)
            
            if mobile_optimized:
                speed_value = min(speed_value * 0.95, 1.2)

            params = {key_text: text, key_speaker: speaker_value, key_speed: speed_value}
            servers = [s for s in tts_settings.get('customTTSserver', GSV_TTS_URL).split('\n') if s.strip()]
            custom_tt_server = servers[index % len(servers)]
            custom_streaming = tts_settings.get('customStream', False)
            
            async def generate_audio():
                safe_url = sanitize_url(input_url=custom_tt_server, default_base=GSV_TTS_URL, endpoint="")
                try:
                    # 使用全局客户端，无需 async with httpx.AsyncClient()
                    async with _srv.global_http_client.stream("GET", safe_url, params=params) as response:
                        response.raise_for_status()
                        if custom_streaming:
                            async for chunk in response.aiter_bytes():
                                yield chunk
                        else:
                            audio_data = await response.aread()
                            if target_format == "opus":
                                convert_result = await asyncio.to_thread(convert_to_opus_simple, audio_data)
                                audio_data = convert_result[0] if isinstance(convert_result, tuple) else convert_result
                            
                            chunk_size = 4096
                            for i in range(0, len(audio_data), chunk_size):
                                yield audio_data[i:i + chunk_size]
                except Exception as e:
                    raise HTTPException(status_code=502, detail=f"Custom TTS 连接失败: {str(e)}")

            media_type = "audio/ogg" if target_format == "opus" else "audio/wav"
            filename = f"tts_{index}.opus" if target_format == "opus" else f"tts_{index}.wav"
            return StreamingResponse(generate_audio(), media_type=media_type, headers={"Content-Disposition": f"inline; filename={filename}", "X-Audio-Index": str(index)})

        # ==========================================
        # 3. GSV 引擎 (使用全局连接池)
        # ==========================================
        elif tts_engine == 'GSV':
            audio_path = os.path.join(UPLOAD_FILES_DIR, tts_settings.get('gsvRefAudioPath', ''))
            if not os.path.exists(audio_path): audio_path = tts_settings.get('gsvRefAudioPath', '')

            gsv_params = {
                "text": text, "text_lang": tts_settings.get('gsvTextLang', 'zh'),
                "ref_audio_path": audio_path, "prompt_lang": tts_settings.get('gsvPromptLang', 'zh'),
                "prompt_text": tts_settings.get('gsvPromptText', ''), "speed_factor": tts_settings.get('gsvRate', 1.0),
                "sample_steps": tts_settings.get('gsvSample_steps', 4), "streaming_mode": True,
                "media_type": "ogg", "batch_size": 1, "seed": 42,
            }
            if mobile_optimized: gsv_params["speed_factor"] = min(gsv_params["speed_factor"] * 0.95, 1.1)
            
            servers = [s for s in tts_settings.get('gsvServer', GSV_TTS_URL).split('\n') if s.strip()]
            gsvServer = servers[index % len(servers)]
                
            async def generate_audio():
                safe_url = sanitize_url(input_url=gsvServer, default_base=GSV_TTS_URL, endpoint="/tts")
                try:
                    async with _srv.global_http_client.stream("POST", safe_url, json=gsv_params) as response:
                        response.raise_for_status()
                        async for chunk in response.aiter_bytes():
                            yield chunk
                except Exception as e:
                    raise HTTPException(status_code=502, detail=f"GSV服务错误: {str(e)}")
            
            return StreamingResponse(generate_audio(), media_type="audio/ogg", headers={"Content-Disposition": f"inline; filename=tts_{index}.opus"})

        # ==========================================
        # 4. 火山引擎 (使用全局连接池)
        # ==========================================
        elif tts_engine == 'volcengine':
            volc_app_id = tts_settings.get('volcAppId', '')
            volc_access_key = tts_settings.get('volcAccessKey', '')
            volc_resource_id = tts_settings.get('volcResourceId', 'volc_tts_release') 
            volc_voice = tts_settings.get('volcVoice', 'zh_female_cancan_mars_bigtts')
            volc_rate = float(tts_settings.get('volcRate', 1.0))
            if mobile_optimized: volc_rate = min(volc_rate * 0.95, 1.2)
            
            url = "https://openspeech.bytedance.com/api/v3/tts/unidirectional"
            headers = {"X-Api-App-Id": volc_app_id, "X-Api-Access-Key": volc_access_key, "X-Api-Resource-Id": volc_resource_id, "Content-Type": "application/json"}
            payload = {
                "user": {"uid": "123456"},
                "req_params": {
                    "text": text, "speaker": volc_voice, "speed_ratio": volc_rate, 
                    "audio_params": {"format": "mp3", "sample_rate": 24000},
                    "additions": "{\"disable_markdown_filter\":true}" 
                }
            }

            async def generate_audio():
                try:
                    async with _srv.global_http_client.stream("POST", url, headers=headers, json=payload) as response:
                        response.raise_for_status()
                        collected_audio = bytearray()
                        async for line in response.aiter_lines():
                            if not line: continue
                            data = json.loads(line)
                            if data.get("code", 0) != 0 and data.get("code", 0) != 20000000: continue
                            if "data" in data and data["data"]:
                                chunk_audio = base64.b64decode(data["data"])
                                if target_format == "opus": collected_audio.extend(chunk_audio)
                                else: yield chunk_audio
                        
                        if target_format == "opus" and collected_audio:
                            res = await asyncio.to_thread(convert_to_opus_simple, bytes(collected_audio))
                            final = res[0] if isinstance(res, tuple) else res
                            for i in range(0, len(final), 4096): yield final[i:i + 4096]
                except Exception as e:
                    raise HTTPException(status_code=502, detail=f"火山引擎错误: {str(e)}")

            media_type = "audio/ogg" if target_format == "opus" else "audio/mpeg"
            return StreamingResponse(generate_audio(), media_type=media_type)

        # ==========================================
        # 5. OpenAI TTS (使用实例缓存)
        # ==========================================
        elif tts_engine == 'openai':
            api_key = tts_settings.get('api_key', '')
            base_url = tts_settings.get('base_url', 'https://api.openai.com/v1')
            if not api_key: raise HTTPException(status_code=400, detail="API密钥未配置")
            
            # 获取或创建缓存的客户端
            cache_key = (api_key, base_url)
            if cache_key not in _srv.openai_tts_clients_cache:
                _srv.openai_tts_clients_cache[cache_key] = AsyncOpenAI(api_key=api_key, base_url=base_url)
            client = _srv.openai_tts_clients_cache[cache_key]

            speed = float(tts_settings.get('openaiSpeed', 1.0))
            if mobile_optimized: speed = min(speed * 0.95, 1.2)
            
            async def generate_audio():
                response_format = target_format if target_format in ['mp3', 'opus', 'aac', 'flac', 'wav', 'pcm'] else 'mp3'
                params = {'model': tts_settings.get('model', 'tts-1'), 'input': text, 'speed': max(0.25, min(4.0, speed)), 'response_format': response_format}
                
                ref_audio = tts_settings.get('gsvRefAudioPath', '')
                if ref_audio:
                    audio_file_path = os.path.join(UPLOAD_FILES_DIR, ref_audio)
                    audio_base64 = base64.b64encode(open(audio_file_path, "rb").read()).decode('utf-8')
                    params['extra_body'] = {"references": [{"text": tts_settings.get('gsvPromptText', ''), "audio": f"data:audio/{Path(audio_file_path).suffix[1:]};base64,{audio_base64}"}]}
                else:
                    params['voice'] = tts_settings.get('openaiVoice', 'alloy')

                if tts_settings.get('openaiStream', False):
                    async with client.audio.speech.with_streaming_response.create(**params) as response:
                        async for chunk in response.iter_bytes(chunk_size=4096): yield chunk
                else:
                    response = await client.audio.speech.create(**params)
                    content = await response.aread()
                    for i in range(0, len(content), 4096): yield content[i:i + 4096]

            media_map = {"opus": "audio/ogg", "wav": "audio/wav", "aac": "audio/aac", "flac": "audio/flac"}
            return StreamingResponse(generate_audio(), media_type=media_map.get(target_format, "audio/mpeg"))

        # ==========================================
        # 6. System TTS (系统原生)
        # ==========================================
        elif tts_engine == 'systemtts':
            system_voice_name = tts_settings.get('systemVoiceName', None)
            system_rate = int(tts_settings.get('systemRate', 200))
            if mobile_optimized: system_rate = int(system_rate * 0.95)
            
            def sync_generate_wav(input_text, voice_name, rate, req_index):
                temp_filename = os.path.join(TOOL_TEMP_DIR, f"temp_tts_{req_index}_{uuid.uuid4().hex[:8]}.wav")
                wav_data = b""
                try:
                    if platform.system() == 'Darwin':
                        cmd = ['say', '-o', temp_filename, '--data-format=LEI16@22050', input_text]
                        if voice_name: cmd.extend(['-v', voice_name])
                        if rate: cmd.extend(['-r', str(rate)])
                        subprocess.run(cmd, check=True)
                    else:
                        import pyttsx3
                        engine = pyttsx3.init()
                        engine.setProperty('rate', rate)
                        if voice_name:
                            for v in engine.getProperty('voices'):
                                if voice_name.lower() in v.name.lower() or voice_name == v.id:
                                    engine.setProperty('voice', v.id); break
                        engine.save_to_file(input_text, temp_filename)
                        engine.runAndWait()
                    if os.path.exists(temp_filename): wav_data = open(temp_filename, 'rb').read()
                finally:
                    if os.path.exists(temp_filename): os.remove(temp_filename)
                return wav_data

            async def generate_audio():
                wav_content = await asyncio.to_thread(sync_generate_wav, text, system_voice_name, system_rate, index)
                final = wav_content
                if target_format == "opus":
                    res = await asyncio.to_thread(convert_to_opus_simple, wav_content)
                    final = res[0] if isinstance(res, tuple) else res
                for i in range(0, len(final), 4096): yield final[i:i + 4096]
            
            media_type = "audio/ogg" if target_format == "opus" else "audio/wav"
            return StreamingResponse(generate_audio(), media_type=media_type)

        # ==========================================
        # 7. Tetos SDK (Azure, 百度, 谷歌, Fish, etc. - 使用实例缓存)
        # ==========================================
        elif tts_engine in ['azure', 'baidu', 'minimax', 'xunfei', 'fish', 'google']:
            selected_voice = tts_settings.get(f'{tts_engine}Voice', '') or None
            
            # 根据引擎生成缓存Key
            if tts_engine == 'azure': cache_key = (tts_engine, tts_settings.get('azureSpeechKey'), tts_settings.get('azureRegion'), selected_voice)
            elif tts_engine == 'baidu': cache_key = (tts_engine, tts_settings.get('baiduApiKey'), tts_settings.get('baiduSecretKey'), selected_voice)
            elif tts_engine == 'minimax': cache_key = (tts_engine, tts_settings.get('minimaxApiKey'), tts_settings.get('minimaxGroupId'), selected_voice)
            elif tts_engine == 'xunfei': cache_key = (tts_engine, tts_settings.get('xunfeiAppId'), tts_settings.get('xunfeiApiKey'), tts_settings.get('xunfeiApiSecret'), selected_voice)
            elif tts_engine == 'fish': cache_key = (tts_engine, tts_settings.get('fishApiKey'), selected_voice)
            elif tts_engine == 'google': cache_key = (tts_engine, hash(tts_settings.get('googleServiceAccount', '')), selected_voice)
            else: cache_key = None

            temp_filename = os.path.join(TOOL_TEMP_DIR, f"temp_tetos_{index}_{uuid.uuid4().hex[:8]}.mp3")

            def run_tetos_sync():
                if cache_key in _srv.tetos_speakers_cache:
                    speaker = _srv.tetos_speakers_cache[cache_key]
                else:
                    if tts_engine == 'azure':
                        from tetos.azure import AzureSpeaker
                        speaker = AzureSpeaker(speech_key=cache_key[1], speech_region=cache_key[2], voice=selected_voice)
                    elif tts_engine == 'baidu':
                        from tetos.baidu import BaiduSpeaker
                        speaker = BaiduSpeaker(api_key=cache_key[1], secret_key=cache_key[2], voice=selected_voice)
                    elif tts_engine == 'minimax':
                        from tetos.minimax import MinimaxSpeaker
                        speaker = MinimaxSpeaker(api_key=cache_key[1], group_id=cache_key[2], voice=selected_voice)
                    elif tts_engine == 'xunfei':
                        from tetos.xunfei import XunfeiSpeaker
                        speaker = XunfeiSpeaker(app_id=cache_key[1], api_key=cache_key[2], api_secret=cache_key[3], voice=selected_voice)
                    elif tts_engine == 'fish':
                        from tetos.fish import FishSpeaker
                        speaker = FishSpeaker(api_key=cache_key[1], voice=selected_voice)
                    elif tts_engine == 'google':
                        from tetos.google import GoogleSpeaker
                        sa_json = tts_settings.get('googleServiceAccount', '')
                        if sa_json:
                            import tempfile
                            with tempfile.NamedTemporaryFile(mode='w+', suffix='.json', delete=False) as tmp:
                                tmp.write(sa_json); os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = tmp.name
                        speaker = GoogleSpeaker(voice=selected_voice)
                    _srv.tetos_speakers_cache[cache_key] = speaker
                speaker.say(text, temp_filename)

            await asyncio.to_thread(run_tetos_sync)
            
            async def generate_from_file():
                try:
                    if os.path.exists(temp_filename):
                        data = open(temp_filename, "rb").read()
                        if target_format == "opus":
                            res = await asyncio.to_thread(convert_to_opus_simple, data)
                            data = res[0] if isinstance(res, tuple) else res
                        for i in range(0, len(data), 4096): yield data[i:i + 4096]
                finally:
                    if os.path.exists(temp_filename): os.remove(temp_filename)

            media_type = "audio/ogg" if target_format == "opus" else "audio/mpeg"
            return StreamingResponse(generate_from_file(), media_type=media_type)

        # ==========================================
        # 8. ElevenLabs TTS (最终修复版)
        # ==========================================
        elif tts_engine == 'elevenlabs':
            from elevenlabs.client import ElevenLabs as ElevenLabsClient
            
            api_key = tts_settings.get('elevenLabsApiKey', '')
            voice_id = tts_settings.get('elevenLabsVoice', '')
            model_id = tts_settings.get('elevenLabsModel', 'eleven_multilingual_v2')
            rate = float(tts_settings.get('elevenLabsRate', 1.0))
            
            if not api_key:
                raise HTTPException(status_code=400, detail="ElevenLabs API Key 未配置")
            if not voice_id:
                raise HTTPException(status_code=400, detail="ElevenLabs Voice ID 未配置")
            
            if mobile_optimized:
                rate = min(rate * 0.95, 1.2)
            
            client = ElevenLabsClient(api_key=api_key)
            
            # 1. 【修复关键点】提前建立连接和请求！如果 Voice ID 错误，这里会立即抛出异常
            # 此时因为还没有进入 StreamingResponse，抛出 HTTPException 状态码修改是完全合法的
            try:
                audio_stream = await asyncio.to_thread(
                    client.text_to_speech.convert,
                    text=text,
                    voice_id=voice_id,
                    model_id=model_id or 'eleven_multilingual_v2',
                    output_format='mp3_44100_128'
                )
            except Exception as e:
                error_msg = str(e)
                if "API key" in error_msg.lower() or "authentication" in error_msg.lower():
                    raise HTTPException(status_code=401, detail="ElevenLabs API Key 无效")
                elif "voice" in error_msg.lower() or "not found" in error_msg.lower():
                    raise HTTPException(status_code=400, detail=f"Voice ID 无效: {voice_id}")
                elif "model" in error_msg.lower():
                    raise HTTPException(status_code=400, detail=f"Model ID 无效: {model_id}")
                elif "credit" in error_msg.lower() or "quota" in error_msg.lower() or "characters" in error_msg.lower():
                    raise HTTPException(status_code=429, detail="ElevenLabs 额度不足")
                else:
                    raise HTTPException(status_code=502, detail=f"ElevenLabs 服务错误: {error_msg}")

            async def generate_audio():
                # 2. 【性能修复】利用线程池安全地拉取同步生成器的数据，避免阻塞并发循环
                def get_next_chunk():
                    try:
                        return next(audio_stream)
                    except StopIteration:
                        return None


                while True:
                    try:
                        chunk = await asyncio.to_thread(get_next_chunk)
                        if chunk is None:
                            break
                        if chunk:
                            yield chunk
                    except Exception as e:
                        # 注意：在这里如果流传输中断了，不能再 raise HTTPException 了，只需中断流即可
                        print(f"ElevenLabs 传输中断: {str(e)}")
                        break

            # 移动端：转换为 opus（需要先收集所有 chunk）
            if target_format == "opus":
                async def generate_opus():
                    collected = bytearray()
                    async for chunk in generate_audio():
                        collected.extend(chunk)
                    if collected:
                        res = await asyncio.to_thread(convert_to_opus_simple, bytes(collected))
                        final = res[0] if isinstance(res, tuple) else res
                        for i in range(0, len(final), 4096):
                            yield final[i:i + 4096]
                return StreamingResponse(
                    generate_opus(),
                    media_type="audio/ogg",
                    headers={
                        "Content-Disposition": f"inline; filename=tts_{index}.opus",
                        "X-Audio-Index": str(index),
                        "X-Audio-Format": "opus"
                    }
                )
            else:
                # MP3 直接流式返回 generator
                return StreamingResponse(
                    generate_audio(),
                    media_type="audio/mpeg",
                    headers={
                        "Content-Disposition": f"inline; filename=tts_{index}.mp3",
                        "X-Audio-Index": str(index),
                        "X-Audio-Format": "mp3"
                    }
                )
            
        # ==========================================
        # 9. MOSS TTS (纯本地 CPU 引擎，懒加载)
        # ==========================================
        elif tts_engine == 'moss':
            from py.moss_tts import moss_generate_audio
            
            # 读取 MOSS 参数设定
            moss_voice = tts_settings.get('mossVoice', 'Junhao')
            moss_speed = float(tts_settings.get('mossSpeed', 1.0))
            
            # 移动端语速安全降速
            if mobile_optimized:
                moss_speed = min(moss_speed * 0.95, 1.2)
            
            # 处理音色克隆
            # MOSS 复用已有的 gsvRefAudioPath 选择文件
            clone_audio_path = tts_settings.get('gsvRefAudioPath', '')
            abs_clone_path = ""
            if clone_audio_path:
                abs_clone_path = os.path.join(UPLOAD_FILES_DIR, clone_audio_path)
                if not os.path.exists(abs_clone_path):
                    abs_clone_path = clone_audio_path # 退避策略，万一传的是绝对路径
                    
            async def generate_moss_audio():
                try:
                    # 获取生成完的 WAV 字节流
                    wav_data = await moss_generate_audio(
                        text=text,
                        voice=moss_voice,
                        speed=moss_speed,
                        prompt_audio_path=abs_clone_path
                    )
                    
                    final_data = wav_data
                    # 如果移动端要求 OPUS，调用你已经写好的 converter
                    if target_format == "opus":
                        res = await asyncio.to_thread(convert_to_opus_simple, wav_data)
                        final_data = res[0] if isinstance(res, tuple) else res
                    
                    # 切片流式传输
                    chunk_size = 4096
                    for i in range(0, len(final_data), chunk_size):
                        yield final_data[i:i + chunk_size]
                        
                except Exception as e:
                    import traceback
                    traceback.print_exc()
                    print(f"MOSS TTS 生成错误: {e}")
                    raise HTTPException(status_code=500, detail=f"MOSS TTS 错误: {str(e)}")

            # 根据返回格式决定响应头
            media_type = "audio/ogg" if target_format == "opus" else "audio/wav"
            filename = f"tts_{index}.opus" if target_format == "opus" else f"tts_{index}.wav"
            return StreamingResponse(
                generate_moss_audio(), 
                media_type=media_type, 
                headers={
                    "Content-Disposition": f"inline; filename={filename}", 
                    "X-Audio-Index": str(index),
                    "X-Audio-Format": target_format
                }
            )

        raise HTTPException(status_code=400, detail="不支持的TTS引擎")
    
    except Exception as e:
        import traceback
        traceback.print_exc()
        return JSONResponse(status_code=500, content={"error": f"服务器内部错误: {str(e)}"})


@router.post("/tts/tetos/list_voices")
async def list_tetos_voices(request: Request):
    """
    通过 tetos 获取音色列表
    流程: 接收配置 -> 实例化 Speaker -> 调用 .list_voices()
    """
    try:
        data = await request.json()
        provider = data.get('provider', '').lower()
        config = data.get('config', {})  # 用户填写的鉴权信息

        if not provider:
            return JSONResponse(status_code=400, content={"error": "缺少 'provider' 参数"})

        # 定义同步执行函数（在线程池运行，避免阻塞）
        def _sync_fetch_voices():
            voices = []

            # ---------------------------
            # Azure TTS
            # ---------------------------
            if provider == 'azure':
                from tetos.azure import AzureSpeaker
                # 实例化
                speaker = AzureSpeaker(
                    speech_key=config.get('speech_key') or config.get('api_key'),
                    speech_region=config.get('speech_region') or config.get('region')
                )
                # 获取列表
                voices = speaker.list_voices()

            # ---------------------------
            # Baidu TTS
            # ---------------------------
            elif provider == 'baidu':
                from tetos.baidu import BaiduSpeaker
                speaker = BaiduSpeaker(
                    api_key=config.get('api_key'),
                    secret_key=config.get('secret_key')
                )
                voices = speaker.list_voices()

            # ---------------------------
            # Minimax TTS
            # ---------------------------
            elif provider == 'minimax':
                from tetos.minimax import MinimaxSpeaker
                speaker = MinimaxSpeaker(
                    api_key=config.get('api_key'),
                    group_id=config.get('group_id')
                )
                voices = speaker.list_voices()

            # ---------------------------
            # 讯飞 (Xunfei)
            # ---------------------------
            elif provider == 'xunfei':
                from tetos.xunfei import XunfeiSpeaker
                speaker = XunfeiSpeaker(
                    app_id=config.get('app_id'),
                    api_key=config.get('api_key'),
                    api_secret=config.get('api_secret')
                )
                voices = speaker.list_voices()

            elif provider == 'fish':
                api_key = config.get('api_key')
                if not api_key:
                    raise ValueError("Fish Audio 需要配置 API Key")

                # 请求 Fish Audio 官方 API
                # page_size 设置为 30 以获取更多热门音色
                url = "https://api.fish.audio/model?page_size=30&page_number=1&sort_by=score"
                headers = {
                    "Authorization": f"Bearer {api_key}",
                    "User-Agent": "Mozilla/5.0" 
                }
                
                response = requests.get(url, headers=headers, timeout=60)
                response.raise_for_status() # 检查 HTTP 错误
                res_json = response.json()
                
                # 解析返回的数据结构
                items = res_json.get("items", [])
                
                for item in items:
                    # 将 Fish Audio 的数据结构转换为前端通用的结构
                    # 前端 getVoiceValue 优先找 id
                    # 前端 getVoiceLabel 优先找 DisplayName 或 name
                    # 前端 getVoiceDesc 优先找 Locale
                    voices.append({
                        "id": item.get("_id"),            # 关键：这是实际的 voice ID
                        "name": item.get("title"),        # 显示名称
                        "DisplayName": item.get("title"), # 兼容字段
                        "Locale": item.get("languages", ["Unknown"])[0] if item.get("languages") else "" # 语言标签
                    })


            # ---------------------------
            # Google TTS
            # ---------------------------
            elif provider == 'google':
                from tetos.google import GoogleSpeaker
                # Google 特殊处理：tetos 依赖 GOOGLE_APPLICATION_CREDENTIALS 环境变量
                # 如果 config 传了 service_account 的 json 对象，我们需要临时写入文件
                
                service_account_data = config.get('service_account')
                temp_path = None
                
                try:
                    if service_account_data:
                        # 创建临时文件
                        with tempfile.NamedTemporaryFile(mode='w+', suffix='.json', delete=False) as tmp:
                            if isinstance(service_account_data, dict):
                                json.dump(service_account_data, tmp)
                            else:
                                tmp.write(str(service_account_data))
                            temp_path = tmp.name
                        
                        # 设置环境变量
                        os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = temp_path
                    
                    # GoogleSpeaker 初始化通常不需要参数，它自己去读环境变量
                    speaker = GoogleSpeaker()
                    voices = speaker.list_voices()
                    
                finally:
                    # 清理工作
                    if temp_path:
                        if os.path.exists(temp_path):
                            os.remove(temp_path)
                        # 如果是我们设置的环境变量，用完删除，以免影响其他请求
                        if os.environ.get("GOOGLE_APPLICATION_CREDENTIALS") == temp_path:
                            del os.environ["GOOGLE_APPLICATION_CREDENTIALS"]

            else:
                pass

            return voices

        # 使用 asyncio.to_thread 放入线程池执行，防止阻塞 FastAPI 主循环
        voice_list = await asyncio.to_thread(_sync_fetch_voices)

        return JSONResponse(content={
            "status": "success",
            "provider": provider,
            "data": voice_list
        })

    except Exception as e:
        print(f"获取 {provider} 音色列表失败: {e}")
        # 捕获鉴权失败、网络错误等
        return JSONResponse(status_code=500, content={
            "status": "error", 
            "message": str(e),
            "detail": f"获取 {provider} 音色列表失败，请检查密钥配置是否正确。"
        })


@router.get("/system/voices")
async def get_system_voices():
    """
    获取系统可用的 pyttsx3 音色列表。
    优化版：
    1. 优先展示 Siri/Premium 高质量音色
    2. 自动从 ID 中补全缺失的语言标识
    3. 为高质量音色添加 [Siri] 前缀
    """
    import pyttsx3
    import sys
    import re

    def fetch_voices_sync():
        try:
            # 1. 仍然保留怪诞音色黑名单 (这些声音确实没法用)
            mac_novelty_voices = {
                'Albert', 'Bad News', 'Bahh', 'Bells', 'Boing', 'Bubbles', 'Cellos',
                'Deranged', 'Good News', 'Hysterical', 'Pipe Organ', 'Trinoids', 
                'Whisper', 'Zarvox', 'Organ'
            }

            engine = pyttsx3.init()
            voices = engine.getProperty('voices')
            
            processed_voices = []

            for v in voices:
                voice_name = v.name
                voice_id = str(v.id) # 确保是字符串
                lower_id = voice_id.lower()

                # --- 过滤逻辑 ---
                if sys.platform == 'darwin':
                    if voice_name in mac_novelty_voices:
                        continue
                    
                    # 【重要修改】不要再过滤 'siri' 了！
                    # 我们只过滤那些完全无法使用的（通常 id 极其简短或是无效引用）
                    # 但保留包含 'siri', 'premium', 'compact' 的 ID

                # --- 语言解析逻辑 (增强版) ---
                lang = "Unknown"
                
                # 优先尝试从 pyttsx3 属性获取
                if hasattr(v, 'languages') and v.languages:
                    raw_lang = v.languages[0] if isinstance(v.languages, list) else v.languages
                    if isinstance(raw_lang, bytes):
                        try:
                            lang = raw_lang.decode('utf-8', errors='ignore').replace('\x05', '')
                        except:
                            lang = str(raw_lang)
                    else:
                        lang = str(raw_lang)

                # 【补全逻辑】如果属性里读不到语言，尝试从 ID 里正则提取
                # macOS 的 ID 通常长这样: com.apple.speech.synthesis.voice.zh_CN.ting-ting.premium
                if lang == "Unknown" or lang == "":
                    # 匹配 .zh_CN. 或 .en_US. 这种模式
                    match = re.search(r'\.([a-z]{2}[_-][A-Z]{2})\.', voice_id)
                    if match:
                        lang = match.group(1).replace('_', '-') # 统一格式为 zh-CN

                # --- 判断是否为 Siri/高质量音色 ---
                # 关键词：siri, premium (高品质), compact (压缩的高品质，通常是系统默认下载的)
                is_high_quality = False
                quality_tag = ""
                
                if any(k in lower_id for k in ['siri', 'premium', 'compact']):
                    is_high_quality = True
                    quality_tag = "[Siri/Premium] "
                
                # 有些系统直接在名字里就叫 "Siri Voice 1"
                if "siri" in voice_name.lower():
                    is_high_quality = True
                    quality_tag = "[Siri] "

                # 组装数据
                processed_voices.append({
                    "id": voice_id,
                    "name": f"{quality_tag}{voice_name}", # 在名字前加上标识，方便前端展示
                    "original_name": voice_name,
                    "lang": lang,
                    "gender": getattr(v, 'gender', 'Unknown'),
                    "is_siri": is_high_quality # 用于排序的标记
                })

            # --- 排序逻辑 ---
            # Python 的 sort 是稳定的。
            # key 解释: (not x['is_siri']) -> True(1) 排后面, False(0) 排前面
            # 所以 is_siri=True 的会排在最前面
            processed_voices.sort(key=lambda x: (not x['is_siri'], x['lang'], x['name']))

            return processed_voices
            
        except ImportError:
            print("错误: 未找到 pyttsx3 驱动")
            return []
        except Exception as e:
            print(f"获取系统音色错误: {str(e)}")
            return []

    try:
        available_voices = await asyncio.to_thread(fetch_voices_sync)
        return {
            "count": len(available_voices),
            "voices": available_voices
        }
    except Exception as e:
        from fastapi.responses import JSONResponse
        return JSONResponse(status_code=500, content={"error": str(e)})


@router.post("/upload_gsv_ref_audio")
async def upload_gsv_ref_audio(
    request: Request,
    file: UploadFile = File(...),
):
    fastapi_base_url = str(request.base_url)
    
    # 检查文件扩展名
    file_extension = file.filename.split('.')[-1].lower()
    if file_extension not in _srv.ALLOWED_AUDIO_EXTENSIONS:
        return JSONResponse(
            status_code=400,
            content={"success": False, "message": f"不支持的文件类型: {file_extension}"}
        )
    
    # 生成唯一文件名
    unique_filename = f"{uuid.uuid4()}.{file_extension}"
    destination = os.path.join(UPLOAD_FILES_DIR, unique_filename)
    
    try:
        # 保存文件
        with open(destination, "wb") as buffer:
            content = await file.read()
            buffer.write(content)
        
        # 构建响应
        file_link = f"{fastapi_base_url}uploaded_files/{unique_filename}"
        
        return JSONResponse(content={
            "success": True,
            "message": "参考音频上传成功",
            "file": {
                "path": file_link,
                "name": file.filename,
                "unique_filename": unique_filename
            }
        })
    
    except Exception as e:
        _srv.logger.error(f"参考音频上传失败: {str(e)}")
        return JSONResponse(
            status_code=500,
            content={"success": False, "message": f"文件保存失败: {str(e)}"}
        )


@router.delete("/delete_audio/{filename}")
async def delete_audio(filename: str):
    try:
        file_path = os.path.join(UPLOAD_FILES_DIR, filename)
        
        # 安全检查：确保文件名是UUID格式，防止路径遍历攻击
        if not re.match(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\.\w+$", filename):
            return JSONResponse(
                status_code=400,
                content={"success": False, "message": "Invalid filename"}
            )
        
        if os.path.exists(file_path):
            os.remove(file_path)
            return JSONResponse(content={
                "success": True,
                "message": "音频文件已删除"
            })
        else:
            return JSONResponse(
                status_code=404,
                content={"success": False, "message": "文件不存在"}
            )
            
    except Exception as e:
        _srv.logger.error(f"删除音频失败: {str(e)}")
        return JSONResponse(
            status_code=500,
            content={"success": False, "message": f"删除失败: {str(e)}"}
        )

