# -*- coding: utf-8 -*-
"""文件白名单常量与文件工具（批 2h1 自 server.py 迁出）。

上传/媒体/VRM/场景各域的扩展名白名单与路径工具的单一事实源；
server.py 与 py/routers/{files,media,system}.py 一律从这里 import，
新增白名单只改本文件。
"""
import os
import socket
from pathlib import Path
from typing import List

from fastapi import Request

from py.get_setting import DEFAULT_VRM_DIR

# 办公文档 / 编程开发 / 数据配置
ALLOWED_EXTENSIONS = [
    'doc', 'docx', 'ppt', 'pptx', 'xls', 'xlsx', 'pdf', 'pages',
    'numbers', 'key', 'rtf', 'odt', 'epub',
    'js', 'ts', 'py', 'java', 'c', 'cpp', 'h', 'hpp', 'go', 'rs',
    'swift', 'kt', 'dart', 'rb', 'php', 'html', 'css', 'scss', 'less',
    'vue', 'svelte', 'jsx', 'tsx', 'json', 'xml', 'yml', 'yaml',
    'sql', 'sh',
    'csv', 'tsv', 'txt', 'md', 'log', 'conf', 'ini', 'env', 'toml'
]
ALLOWED_IMAGE_EXTENSIONS = ['png', 'jpg', 'jpeg', 'gif', 'webp', 'bmp']
ALLOWED_VIDEO_EXTENSIONS = ['mp4', 'webm', 'ogg', 'mov', 'avi']
ALLOWED_AUDIO_EXTENSIONS = ['wav', 'mp3', 'ogg', 'flac', 'aac']
ALLOWED_VRM_EXTENSIONS = {'vrm'}
ALLOWED_VRMA_EXTENSIONS = {"vrma"}
# spark 支持的场景格式扩展名
ALLOWED_GAUSS = {"ply", "spz", "splat", "ksplat", "sog"}

animation_dir = os.path.join(DEFAULT_VRM_DIR, "animations")
GAUSS_DIR = os.path.join(DEFAULT_VRM_DIR, "scene")  # 默认场景目录


def make_file_url(request: Request, file_path: str) -> str:
    """将本地文件路径转成对外可访问的 URL"""
    return str(request.base_url) + file_path.lstrip("/")


def scan_motion_files(directory: str, allowed_ext: set) -> List[dict]:
    """
    扫描指定目录下所有符合扩展名的文件，返回列表：
    [
      {
        "id": "文件名(不含扩展名)",
        "name": "文件名(不含扩展名)",
        "path": "对外可访问的完整 URL",
        "type": "default" | "user"
      }
    ]
    """
    files = []
    if not os.path.exists(directory):
        return files

    for f in os.listdir(directory):
        if f.lower().endswith(tuple(allowed_ext)):
            file_id = Path(f).stem
            file_path = os.path.join(directory, f)
            # 注意：这里统一返回相对路径，后面再组装成 URL
            files.append({
                "id": file_id,
                "name": file_id,
                "path": file_path,
                "type": "default" if directory == animation_dir else "user"
            })
    files.sort(key=lambda x: x["name"])
    return files


def get_internal_ip():
    """获取本机内网 IP 地址"""
    try:
        # 创建一个 socket 连接，目标可以是任何公网地址（不真连接），只是用来获取出口 IP
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.settimeout(0)
        s.connect(("8.8.8.8", 80))  # 使用 Google DNS，不实际发送数据
        internal_ip = s.getsockname()[0]
        s.close()
        return internal_ip
    except Exception:
        return "127.0.0.1"
