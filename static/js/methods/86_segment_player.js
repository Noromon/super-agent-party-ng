// 批 3 F2：自 vue_methods.js 搬移的 methods/86_segment_player.js 域（Object.assign 装配，
// 加载顺序在宿主之后、renderer 之前）。方法体互调仍走 this。
Object.assign(vue_methods, {
/* -------------------------------------------------- */
/* 1. 自动分段（复用全文算法）                       */
/* -------------------------------------------------- */
reSegment() {
  this.stopSegmentTTS();          // 停旧音频
    const {
      chunks,
      chunks_voice,
      remaining,
      remaining_voice
    } = this.splitTTSBuffer(this.readConfig.longText);

    if (remaining) {
      chunks.push(remaining);
      chunks_voice.push(remaining_voice);
    }

      /* ================= 新增：去标签 + 去空白并同步删除 ================= */
      // 1. 去 HTML 标签
      const cleanedChunks = chunks.map(txt => txt.replace(/<\/?[^>]+>/g, '').trim());

      // 2. 过滤空白并同步删除 chunks_voice 对应项
      const finalChunks       = [];
      const finalChunksVoice  = [];

      cleanedChunks.forEach((txt, idx) => {
        if (txt) {                      // 非空才保留
          finalChunks.push(txt);
          finalChunksVoice.push(chunks_voice[idx]);
        }
      });

      // 3. 覆盖原来的数组
      chunks.length       = 0;
      chunks_voice.length = 0;
      chunks.push(...finalChunks);
      chunks_voice.push(...finalChunksVoice);
      /* ================================================================ */

  this.readState.ttsChunks = chunks;
  this.readState.chunks_voice = chunks_voice;
  this.readState.audioChunks  = new Array(this.readState.ttsChunks.length);
  this.readState.currentChunk = -1;
},

/* -------------------------------------------------- */
/* 2. 播放单句（含 VRM 同步）                        */
/* -------------------------------------------------- */
async playSingleSegment(idx) {
  try{
    if (!this.readState.ttsChunks[idx]) return;
    this.isReadingOnetext = true;
    this.readState.currentChunk = idx;
    const chunk = this.readState.ttsChunks[idx];
    const voice = this.readState.chunks_voice[idx];
    const cachedAudio = this.readState.audioChunks[idx];

    // 检查缓存是否命中
    if (cachedAudio?.url && cachedAudio?.base64 && cachedAudio?.text === chunk && cachedAudio?.voice === voice) {
      this.doPlayAudio(this.readState.audioChunks[idx].url, idx, false); // false=不连播
      return;
    }
    // 未命中先合成
    await this.synthSegment(idx);
    this.doPlayAudio(this.readState.audioChunks[idx].url, idx, false);
  } finally {
    this.isReadingOnetext = false;
  }
},

/* -------------------------------------------------- */
/* 3. 连续播放开关                                   */
/* -------------------------------------------------- */
async toggleContinuousPlay() {
  if (this.readState.isPlaying) {          // 暂停
    this.stopSegmentTTS(false);
    return;
  }
  this.readState.isPlaying   = true;
  if (this.readState.currentChunk < 0 || this.readState.currentChunk >= this.readState.ttsChunks.length) { // 从头开始
    this.readState.currentChunk = 0;         // 从第一句开始
  }
  await this.playNextInQueue(true);        // true 表示连续
},

/* -------------------------------------------------- */
/* 4. 新增：仅播放下一句（播完即停）                  */
/* -------------------------------------------------- */
async playNextSegmentOnce() {
  let next = this.readState.currentChunk + 1;
  this.readState.currentChunk = next;
  if (next >= this.readState.ttsChunks.length) {
    next = 0;
    this.readState.currentChunk = next;
  }
  this.readState.isPlaying = false;      // 确保不自动连播
  await this.playSingleSegment(next);    // 播完即停
},

/* -------------------------------------------------- */
/* 5. 停止所有分段音频                               */
/* -------------------------------------------------- */
stopSegmentTTS(isEnd = true) {
  this.stopTTSActivities();
  if (isEnd){
    this.readState.currentChunk = -1;
  }
  if (this._curAudio) {
    this._curAudio.pause();
    this._curAudio = null;
  }
  this.readState.isPlaying   = false;
},

/* -------------------------------------------------- */
/* 6. 编辑段文本                                      */
/* -------------------------------------------------- */
toggleEditSegment(idx) {
  if (this.activeSegmentIdx === idx) {
    // 保存：把临时值写回正式字段
    this.readState.ttsChunks[idx] = this.segmentEditBuffer
    this.readState.chunks_voice[idx] = this.segmentVoiceEditBuffer[idx] ?? this.readState.chunks_voice[idx]
    this.activeSegmentIdx = -1
  } else {
    // 进入编辑：先给“音色临时数组”对应位置塞个初始值
    this.segmentEditBuffer = this.readState.ttsChunks[idx]
    // Vue3 直接赋值即可
    this.segmentVoiceEditBuffer[idx] = this.readState.chunks_voice[idx]
    this.activeSegmentIdx = idx
  }
},

/* 1. 合成时顺便转 base64 */
async synthSegment(idx) {
  try {
    const text  = this.readState.ttsChunks[idx];
    const voice = this.readState.chunks_voice[idx] || 'default';
    /* —— 与对话版完全一致的文本清洗 —— */
    let chunk_text = text;
    let chunk_expressions =[];
    if (text.indexOf('<') !== -1) {
      const tagReg = /<[^>]+>/g;
      chunk_expressions = (text.match(tagReg) || []).map(t => t.slice(1, -1)); // 去掉两端的 <>
      chunk_text = text.replace(tagReg, '').trim(); // 把标签从正文里删掉
    }
    const res = await fetch('/tts', {
      method : 'POST',
      headers: { 'Content-Type': 'application/json' },
      body   : JSON.stringify({ ttsSettings: this.ttsSettings, text, index: idx, voice }),
    });
    if (!res.ok) throw new Error('TTS failed');

    const blob = await res.blob();
    const url  = URL.createObjectURL(blob);

    /* 关键：同步转 base64 */
    const base64 = await new Promise((resolve, reject) => {
      const reader = new FileReader();
      reader.onload  = () => resolve(reader.result.split(',')[1]);
      reader.onerror = reject;
      reader.readAsDataURL(blob);
    });

    /* 缓存两样东西 */
    this.readState.audioChunks[idx] = {
      url,                       // 本地播放用
      expressions: chunk_expressions,
      base64: `data:${blob.type};base64,${base64}`, // VRM 播放用
      text: chunk_text,
      idx,
      voice
    };
  } catch (e) {
    console.error(`TTS chunk ${idx} error`, e);
    this.readState.audioChunks[idx] = { 
      url: null, 
      base64: null,
      expressions: [],
      text: "",
      idx 
    };
  }
},

scrollToCurrentChunk(idx) {
  // 使用 nextTick 确保 DOM 更新完成
  this.$nextTick(() => {
    const segmentList = document.querySelector('.segment-list');
    const segmentItem = document.querySelector(`.segment-item:nth-child(${idx + 1})`);
    if (segmentList && segmentItem) {
      segmentItem.scrollIntoView({
        behavior: 'smooth',
        block: 'center'
      });
    }
  });
},

async doPlayAudio(url, idx, continuous = false) {
  if (this._curAudio) {
    this._curAudio.pause();
    this.sendTTSStatusToVRM('stopSpeaking', {});
  }
  try {
    const audio = new Audio(url);
    this._curAudio = audio;

    // 滚动到当前行
    this.scrollToCurrentChunk(idx);

    const chunk = this.readState.audioChunks[idx];
    if (chunk.base64 == null) throw new Error('No base64');
    this._curAudio.volume = this.vrmOnline ? 0.0000001 : 1; // VRM在线时静音
    this.sendTTSStatusToVRM('startSpeaking', {
      audioDataUrl: chunk.base64,
      chunkIndex: idx,
      totalChunks: this.readState.ttsChunks.length,
      text: chunk.text,
      expressions: chunk.expressions || [],
      voice: this.readState.chunks_voice[idx] || 'default',
    });

    // 监听错误事件
    audio.addEventListener('error', (e) => {
      console.error('Audio load error', e);
      this.readState.currentChunk++;
      if (this.readState.currentChunk < this.readState.ttsChunks.length) {
        this.playNextInQueue(true);
      } else {
        this.stopSegmentTTS();
      }
    });

    await new Promise(resolve => {
      this._curAudio.addEventListener('ended', () => {
        this.sendTTSStatusToVRM('chunkEnded', { chunkIndex: idx });
        if (continuous && this.readState.isPlaying) {
          this.readState.currentChunk++;
          if (this.readState.currentChunk < this.readState.ttsChunks.length) {
            this.playNextInQueue(true);
          } else {
            this.stopSegmentTTS();
          }
        } else {
          this.stopSegmentTTS(false);
        }
        resolve();
      });
      console.log('play audio', `${idx + 1}`);
      audio.play().catch(e => {
        console.error('Audio play error', e);
        this.readState.currentChunk++;
        if (this.readState.currentChunk < this.readState.ttsChunks.length) {
          this.playNextInQueue(true);
        } else {
          this.stopSegmentTTS();
        }
        resolve(); // 确保 Promise 被 resolve
      });
    });
  } catch (e) {
    console.error('Read playback error', e);
    this.readState.currentChunk++;
    if (this.readState.currentChunk < this.readState.ttsChunks.length) {
      this.playNextInQueue(true);
    } else {
      this.stopSegmentTTS();
    }
  } finally {
      this.isReadingOnetext = false;
    }
},

// 连续播放专用：自动合成&播放下一帧
async playNextInQueue(continuous) {
  const idx = this.readState.currentChunk;   // 当前要播的索引
  const chunk = this.readState.ttsChunks[idx];
  const voice = this.readState.chunks_voice[idx];
  const cachedAudio = this.readState.audioChunks[idx];

  // 检查缓存是否命中
  if (cachedAudio?.url && cachedAudio?.base64 && cachedAudio?.text === chunk && cachedAudio?.voice === voice) {
    // 命中就无事发生
  }else{
    await this.synthSegment(idx);
  }
  this.doPlayAudio(this.readState.audioChunks[idx].url, idx, continuous);
},

// 清空分段
clearSegments() {
  this.stopSegmentTTS();
  this.readState.ttsChunks   = [];
  this.readState.chunks_voice = [];
  this.readState.audioChunks  = [];
  this.readState.currentChunk = -1;
}
});
