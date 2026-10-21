// 批 3 F1：SSE/NDJSON 流读取统一层（classic script，加载于 vue_methods 之前）。
//
// 全库 9 处 fetch 流解析循环收编为两个帧迭代器（审计 03）。
// 语义拉平（批 3 已批准）：JSON 解析失败一律吞掉继续（原聊天主流为抛错
// 断流）；流结束时冲刷残缓冲（原翻译类会丢末行半截句）。
// 业务处理（delta 渲染/TTS 切分/工具帧/重试/AbortError 恢复）留在调用方回调。
//
// iterateSse         — 标准 SSE：\n\n 分事件 + "data: " 前缀（聊天主流/resume）
// iterateNdjsonLines — 行分隔 JSON：\n 分行，可选剥离 "data:" 前缀
//                      （翻译/quick-gen/browser-TTS/dashboard；stripDataPrefix 开关）
"use strict";

/**
 * 标准 SSE 帧迭代。
 * @param {Response} response fetch 响应
 * @param {(parsed: object) => (void|Promise<void>)} onFrame 每个 data: 帧（已 JSON.parse）
 * @param {{stopOnDone?: boolean}} [opts] stopOnDone=false 时 [DONE] 后继续读到流尾
 * @returns {Promise<{serverDone: boolean, eof: boolean}>}
 *          serverDone=见到 [DONE]；eof=读到流尾（调用方据此区分正常完流/异常断流）
 */
async function iterateSse(response, onFrame, opts = {}) {
  const stopOnDone = opts.stopOnDone !== false;
  let buffer = "";
  let serverDone = false;

  const flushEvents = async () => {
    while (buffer.includes("\n\n")) {
      const idx = buffer.indexOf("\n\n");
      const eventData = buffer.slice(0, idx);
      buffer = buffer.slice(idx + 2);
      if (!eventData.startsWith("data: ")) continue;
      const jsonStr = eventData.slice(6).trim();
      if (!jsonStr) continue;
      if (jsonStr === "[DONE]") { serverDone = true; return true; }
      let parsed;
      try {
        parsed = JSON.parse(jsonStr);
      } catch (e) {
        continue; // 拉平：解析失败吞掉继续
      }
      await onFrame(parsed);
    }
    return false;
  };

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let eof = false;
  while (true) {
    const r = await reader.read();
    if (r.done) { eof = true; break; }
    if (r.value) buffer += decoder.decode(r.value, { stream: true });
    if (await flushEvents()) { serverDone = true; break; }
    if (serverDone && stopOnDone) break;
  }
  decoder.decode(); // decoder 终态冲刷
  // 拉平：冲刷残缓冲里未闭合的最后一个 data: 事件
  const tail = buffer.trim();
  if (!serverDone && tail.startsWith("data: ")) {
    const jsonStr = tail.slice(6).trim();
    if (jsonStr === "[DONE]") serverDone = true;
    else if (jsonStr) {
      try {
        await onFrame(JSON.parse(jsonStr));
      } catch (e) { /* 吞 */ }
    }
  }
  return { serverDone, eof };
}

/**
 * 行分隔 JSON 帧迭代（翻译/quick-gen/browser-TTS/dashboard 变体）。
 * @param {(parsed: object) => (void|Promise<void>)} onFrame
 * @param {{stripDataPrefix?: boolean}} [opts] stripDataPrefix=兼容行内可选
 *        "data:" 前缀并跳过 [DONE] 行（L15947/L18564 两处变体）
 * @returns {Promise<{eof: boolean}>}
 */
async function iterateNdjsonLines(response, onFrame, opts = {}) {
  let buffer = "";

  const handleLine = async (rawLine) => {
    let line = rawLine;
    if (opts.stripDataPrefix) {
      line = line.trim();
      if (!line) return;
      if (line === "data: [DONE]" || line === "[DONE]") return;
      if (line.startsWith("data:")) line = line.slice(5).trim();
    }
    if (!line) return;
    let parsed;
    try {
      parsed = JSON.parse(line);
    } catch (e) {
      return; // 吞错继续（拉平语义）
    }
    await onFrame(parsed);
  };

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const lines = buffer.split("\n");
    buffer = lines.pop(); // 末行可能半截，留到下轮
    for (const ln of lines) await handleLine(ln);
  }
  decoder.decode();
  // 拉平：done 后冲刷残行（原 quick-gen 有、翻译类没有 → 全员补齐）
  await handleLine(opts.stripDataPrefix ? buffer.trim() : buffer);
  return { eof: true };
}
