# # uvicorn sttApiTest:app --reload --port 8090
from fastapi import FastAPI, File, UploadFile
from fastapi.responses import JSONResponse
import whisper
from fastapi import Request
import soundfile as sf
import numpy as np
import io
import tempfile
# from pydantic import BaseModel

import numpy as np
import wave

app = FastAPI()

# 加载 Whisper 模型
model = whisper.load_model("turbo")

def process_audio(audio_file):
    # 使用 Whisper 模型进行转录
    result = model.transcribe(audio_file)
    
    # 获取转录文本
    transcription = result["text"]
    return transcription

@app.post("/generate-text/")
async def transcribe_audio(filename: Request):
    
    # 从请求体中解析 JSON 数据
    item = await filename.json()
    
    audio_filename = item.get("audio_filename")
    print(audio_filename)
    
    # 转录音频
    transcription = process_audio(audio_filename)

    return {"transcription": transcription}


