# -*- coding: utf-8 -*-
"""S300：消息内容工具（自 server.py 逐字搬移）：按 role 定位与四则增删改 + 文本抽取。

零依赖叶子模块；server/群记忆/提示词装配/引擎域共用，server 侧保留原名 re-export。
"""
from py.tool_call_guard import neutralize_leaked_blocks as _tcg_neutralize  # S300：content_append 原形引用

import json  # S309b：usage 控制帧序列化


def accumulate_usage(acc, usage_info):
    """S309b：单 POST 跨轮累计厂商计费 usage（RA-11 每轮擦除 usage_info，仪表盘需要总和）。"""
    if not isinstance(usage_info, dict):
        return acc
    out = dict(acc) if isinstance(acc, dict) else {"prompt_tokens": 0, "completion_tokens": 0,
                                                   "total_tokens": 0}
    for k in ("prompt_tokens", "completion_tokens", "total_tokens"):
        v = usage_info.get(k)
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            out[k] = int(out.get(k, 0) + v)
    return out


def usage_control_frame(acc):
    """S309b：DONE 前发出的消息级计费累计控制帧（与 context_usage 同款顶层 type）。"""
    if not isinstance(acc, dict) or not any(acc.get(k) for k in ("prompt_tokens", "completion_tokens",
                                                                 "total_tokens")):
        return None
    return "data: " + json.dumps({
        "type": "stream_usage",
        "prompt_tokens": int(acc.get("prompt_tokens", 0) or 0),
        "completion_tokens": int(acc.get("completion_tokens", 0) or 0),
        "total_tokens": int(acc.get("total_tokens", 0) or 0),
    }, ensure_ascii=False) + "\n\n"


def _get_target_message(message, role):
    """
    根据角色获取目标消息
    
    参数:
        message (list): 消息列表引用
        role (str): 要操作的角色，可选值: 'user', 'assistant', 'system'
    
    返回:
        dict: 目标消息字典
    """
    # 验证输入参数
    if not isinstance(message, list):
        raise TypeError("message必须是列表类型")
    
    if role not in ['user', 'assistant', 'system']:
        raise ValueError("role必须是'user'或'assistant'或'system'")
    
    target_message = None
    
    # 根据role决定要操作的对象
    if role == 'user':
        # 查找最后一个role为'user'的消息
        for msg in reversed(message):
            if isinstance(msg, dict) and msg['role'] == 'user':
                target_message = msg
                break
    elif role == 'assistant':
        # 检查最后一个消息
        if message and message[-1]['role'] == 'assistant':
            target_message = message[-1]
        else:
            # 如果最后一个消息不是assistant，创建一个新的
            new_assistant_msg = {'role': 'assistant', 'content': '','reasoning_content': ''}
            message.append(new_assistant_msg)
            target_message = new_assistant_msg
    elif role == 'system':
        # 查找第一个role为'system'的消息
        if message and message[0]['role'] == 'system':
            target_message = message[0]
        else:
            # 如果没有找到system消息，创建一个新的
            target_message = {'role': 'system', 'content': ''}
            message.insert(0, target_message)
    
    return target_message

def content_append(message, role, content):
    """
    将content添加到指定role消息的末尾
    """
    if role == 'assistant' and content:
        # S163：泄漏的工具调用块文本不落历史（防 few-shot 污染；用户侧流内不拦）
        content = _tcg_neutralize(content)
    target_message = _get_target_message(message, role)
    if target_message:
        current_content = target_message.get('content', '')
        target_message['content'] = current_content + content

def content_prepend(message, role, content):
    """
    将content添加到指定role消息的前面
    """
    target_message = _get_target_message(message, role)
    if target_message:
        current_content = target_message.get('content', '')
        target_message['content'] = content + current_content

def content_replace(message, role, content):
    """
    用content替换指定role消息的内容
    """
    target_message = _get_target_message(message, role)
    if target_message:
        target_message['content'] = content

def content_new(message, role, content):
    """
    用content替换指定role消息的内容
    """
    message.append({'role': role, 'content': content})

def _extract_text_content(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        texts = []
        for item in content:
            if isinstance(item, dict) and item.get("type") == "text":
                texts.append(item.get("text", ""))
        return "\n".join(filter(None, texts))
    return ""
