import io
import wave
import numpy as np
import requests
from openai import OpenAI
import webrtcvad
from transformers import pipeline
from typing import List, Optional, Generator, Tuple, Any
from utils.errors import APIError, AudioConversionError

import soundfile as sf
import os
import uuid
import base64

SAMPLE_RATE: int = 48000
FRAME_DURATION: int = 30


def detect_voice(audio: np.ndarray, sample_rate: int = SAMPLE_RATE, frame_duration: int = FRAME_DURATION) -> bool:
    """
    Detect voice activity in the given audio data.

    Args:
        audio (np.ndarray): Audio data as a numpy array.
        sample_rate (int): Sample rate of the audio. Defaults to SAMPLE_RATE.
        frame_duration (int): Duration of each frame in milliseconds. Defaults to FRAME_DURATION.

    Returns:
        bool: True if voice activity is detected, False otherwise.
    """
    
    print("function detect_voice")
    
    vad = webrtcvad.Vad(3)  # Aggressiveness mode: 3 (most aggressive)
    audio_bytes = audio.tobytes()
    num_samples_per_frame = int(sample_rate * frame_duration / 1000)
    frames = [audio_bytes[i : i + num_samples_per_frame * 2] for i in range(0, len(audio_bytes), num_samples_per_frame * 2)]

    count_speech = 0
    for frame in frames:
        if len(frame) < num_samples_per_frame * 2:
            continue
        if vad.is_speech(frame, sample_rate):
            count_speech += 1
            if count_speech > 6:
                return True
    return False


class STTManager:
    """Manages speech-to-text operations."""

    def __init__(self, config: Any):
        """
        Initialize the STTManager.

        Args:
            config (Any): Configuration object containing STT settings.
        """
        self.config = config
        self.SAMPLE_RATE: int = SAMPLE_RATE
        self.CHUNK_LENGTH: int = 5
        self.STEP_LENGTH: int = 3
        self.MAX_RELIABILITY_CUTOFF: int = self.CHUNK_LENGTH - 1
        self.status: bool = self.test_stt()
        self.streaming: bool = self.status
        if config.stt.type == "HF_LOCAL":
            self.pipe = pipeline("automatic-speech-recognition", model=config.stt.name)

    def numpy_audio_to_bytes(self, audio_data: np.ndarray) -> bytes:
        """
        Convert numpy array audio data to bytes.

        Args:
            audio_data (np.ndarray): Audio data as a numpy array.

        Returns:
            bytes: Audio data as bytes.

        Raises:
            AudioConversionError: If there's an error during conversion.
        """
        buffer = io.BytesIO()
        try:
            with wave.open(buffer, "wb") as wf:
                wf.setnchannels(1)
                wf.setsampwidth(2)
                wf.setframerate(self.SAMPLE_RATE)
                wf.writeframes(audio_data.tobytes())
            print("converting numpy array to audio bytes")
        except Exception as e:
            raise AudioConversionError(f"Error converting numpy array to audio bytes: {e}")
        return buffer.getvalue()

    def process_audio_chunk(self, audio: Tuple[int, np.ndarray], audio_buffer: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
        """
        Process an audio chunk and update the audio buffer.

        Args:
            audio (Tuple[int, np.ndarray]): Audio chunk data.
            audio_buffer (np.ndarray): Existing audio buffer.

        Returns:
            Tuple[np.ndarray, np.ndarray]: Updated audio buffer and processed audio.
        """
        
        print("function process_audio_chunk")
        
        has_voice = detect_voice(audio[1])
        ended = len(audio[1]) % 24000 != 0
        if has_voice:
            audio_buffer = np.concatenate((audio_buffer, audio[1]))
        is_short = len(audio_buffer) / self.SAMPLE_RATE < 1.0
        if is_short or (has_voice and not ended):
            return audio_buffer, np.array([], dtype=np.int16)
        
        print("function process_audio_chunk")
        
        return np.array([], dtype=np.int16), audio_buffer

    def save_audio_file(self, audio_tuple, filename):
        sample_rate = audio_tuple[0]
        audio_data = audio_tuple[1]
    
        # 保存为 WAV 文件
        sf.write(filename, audio_data, sample_rate)
    
    def process_audio_save_file(self, audio, text: str = "") -> str:
        audio_filename = "recorded_audio.wav"
        self.save_audio_file(audio, audio_filename)
        
        absolute_path = os.path.abspath(audio_filename)
    
        file = {"audio_filename": absolute_path}
        print(file)
    
        response = requests.post("http://127.0.0.1:8090/generate-text/", json=file)
    
        transcription = response.json().get("transcription", "")
        return f"{text} {transcription}".strip()
    
    def transcribe_audio(self, audioPath: str, text: str = "") -> str:
        """
        Transcribe audio data and append to existing text.

        Args:
            audioPath (np.ndarray): Audio data path.
            text (str): Existing text to append to. Defaults to empty string.

        Returns:
            str: Transcribed text appended to existing text.
        """

        transcript = self.transcribe_numpy_array(audioPath, context=text)

        return f"{text} {transcript}".strip()

    def transcribe_and_add_to_chat(self, audio: np.ndarray, chat: List[List[Optional[str]]]) -> List[List[Optional[str]]]:
        """
        Transcribe audio and add the result to the chat history.

        Args:
            audio (np.ndarray): Audio data to transcribe.
            chat (List[List[Optional[str]]]): Existing chat history.

        Returns:
            List[List[Optional[str]]]: Updated chat history with transcribed text.
        """
        text = self.transcribe_audio(audio)
        return self.add_to_chat(text, chat)

    def add_to_chat(self, text: str, chat: List[List[Optional[str]]]) -> List[List[Optional[str]]]:
        """
        Add text to the chat history.

        Args:
            text (str): Text to add to chat.
            chat (List[List[Optional[str]]]): Existing chat history.
            editable_chat (bool): Whether the chat is editable. Defaults to True.

        Returns:
            List[List[Optional[str]]]: Updated chat history.
        """
        if not text:
            return chat
        if not chat or chat[-1][0] is None:
            chat.append(["", None])
        chat[-1][0] = text
        return chat

    def transcribe_numpy_array(self, audioPath: str, _context: Optional[str]) -> str:
        """
        Transcribe audio.

        Args:
            audioPath (np.ndarray): Audio data path.
            _context (Optional[str]): Unused context parameter.

        Returns:
            str: Transcribed text.

        Raises:
            APIError: If there's an error in the API response.
        """
        file = {"audio_filename": audioPath}
        response = requests.post("http://127.0.0.1:8090/generate-text/", json=file)
    
        transcription = response.json().get("transcription", "")
        return transcription

    def test_stt(self) -> bool:
        """
        Test the STT functionality.

        Returns:
            bool: True if the test is successful, False otherwise.
        """
        try:
            import os
            absolute_path = "/Users/xiaoxia/Documents/LLM/huishiwei/project_10/interviewer/recorded_audio.wav"

            self.transcribe_audio(absolute_path)
            return True
        except:
            return False


class TTSManager:
    """Manages text-to-speech operations."""

    def __init__(self, config: Any):
        """
        Initialize the TTSManager.

        Args:
            config (Any): Configuration object containing TTS settings.
        """
        self.config = config
        self.SAMPLE_RATE: int = SAMPLE_RATE
        self.status: bool = self.test_tts(stream=False)
        self.streaming: bool = self.test_tts(stream=True) if self.status else False

    def test_tts(self, stream: bool) -> bool:
        """
        Test the TTS functionality.

        Args:
            stream (bool): Whether to test streaming TTS.

        Returns:
            bool: True if the test is successful, False otherwise.
        """
        try:
            list(self.read_text("Handshake", stream=stream))
            return True
        except:
            return False

    def ARK_read_text(self, text: str) -> Generator[bytes, None, None]:
        """
        Convert text to speech using the ARK TTS service.

        Args:
            text (str): Text to convert to speech.

        Yields:
            bytes: Audio data in bytes, representing the generated speech.

        Raises:
            Exception: If there's an error during the request to the TTS API or while processing the response.
        """
        appid = "8099188920"
        access_token = "fdciDQMeEUd70dUiCZgc6rnYHJ4PCJFY"
        # 构造请求体
        request_json = {
            "app": {
                "appid": appid,
                "token": access_token,
                "cluster": self.config.tts.name
            },
            "user": {
                "uid": "388808087185088"
            },
            "audio": {
                "voice_type": "BV700_V2_streaming",
                "encoding": "mp3",
                "speed_ratio": 1.0,
                "volume_ratio": 1.0,
                "pitch_ratio": 1.0,
            },
            "request": {
                "reqid": str(uuid.uuid4()),
                "text": text,
                "text_type": "plain",
                "operation": "query",
                "with_frontend": 1,
                "frontend_type": "unitTson"
            }
        }
        header = {"Authorization": f"Bearer;{access_token}"}

        # 发送 POST 请求到 TTS API
        try:
            resp = requests.post(self.config.tts.url, json=request_json, headers=header)
            resp_data = resp.json()

            if "data" in resp_data:
                # 解码音频数据并返回给 Gradio
                audio_data = base64.b64decode(resp_data["data"])
                sample_rate = 16000
                audio_np = np.frombuffer(audio_data, dtype=np.int16)  # 16位PCM数据
            
                # 使用生成器逐步返回音频
                yield (sample_rate, audio_np)
            else:
                return f"Error: {resp_data.get('message', 'Unknown error')}"
        except Exception as e:
            return str(e)

    def read_text(self, text: str, stream: Optional[bool] = None) -> Generator[bytes, None, None]:
        """
        Convert text to speech using the configured TTS service.

        Args:
            text (str): Text to convert to speech.
            stream (Optional[bool]): Whether to stream the audio. Defaults to self.streaming if not provided.

        Yields:
            bytes: Audio data in bytes.

        Raises:
            APIError: If there's an unexpected error during text-to-speech conversion.
        """
        if not text:
            yield b""
            return

        stream = self.streaming if stream is None else stream

        headers = {"Authorization": f"Bearer {self.config.tts.key}"}
        data = {"model": self.config.tts.name, "text": text, "voice": "alloy", "response_format": "opus"}
        
        print("========================================")
        print("function: read_text")
        print(data)
        print("========================================")

        try:
            yield from self._read_text_stream(headers, data) if stream else self._read_text_non_stream(headers, data)
        except APIError:
            raise
        except Exception as e:
            raise APIError(f"TTS Error: Unexpected error: {e}")

    def _read_text_non_stream(self, headers: dict, data: dict) -> Generator[bytes, None, None]:
        """
        Handle non-streaming TTS requests.

        Args:
            headers (dict): Request headers.
            data (dict): Request data.

        Yields:
            bytes: Audio data in bytes.

        Raises:
            APIError: If there's an error in the API response.
        """
        if self.config.tts.type == "OPENAI_API":
            url = f"{self.config.tts.url}/audio/speech"
            # print(url)
        elif self.config.tts.type == "HF_API":
            url = self.config.tts.url
        else:
            raise APIError(f"TTS Error: Unsupported TTS type: {self.config.tts.type}")

        response = requests.post(url, headers=headers, json=data)
        
        print("After function _read_text_non_stream call requests:")
        print(response) #
        
        if response.status_code != 200:
            error_details = response.json().get("error", "No error message provided")
            raise APIError(f"TTS Error: {self.config.tts.type} error", status_code=response.status_code, details=error_details)

        sample_rate = 16000  
        yield (sample_rate, np.array(response.json()["waveform"]))

    def _read_text_stream(self, headers: dict, data: dict) -> Generator[bytes, None, None]:
        """
        Handle streaming TTS requests.

        Args:
            headers (dict): Request headers.
            data (dict): Request data.

        Yields:
            bytes: Audio data in bytes.

        Raises:
            APIError: If there's an error in the API response or if streaming is not supported.
        """
        if self.config.tts.type != "OPENAI_API":
            raise APIError("TTS Error: Streaming not supported for this TTS type")

        url = f"{self.config.tts.url}/audio/speech"
        with requests.post(url, headers=headers, json=data, stream=True) as response:
            if response.status_code != 200:
                error_details = response.json().get("error", "No error message provided")
                raise APIError("TTS Error: OPENAI API error", status_code=response.status_code, details=error_details)
            yield from response.iter_content(chunk_size=1024)

    def read_last_message(self, chat_history: List[List[Optional[str]]]) -> Generator[bytes, None, None]:
        """
        Read the last message in the chat history.

        Args:
            chat_history (List[List[Optional[str]]]): Chat history.

        Yields:
            bytes: Audio data for the last message.
        """
        
        print("function: read_last_message")
        print("chat_history[-1][1]:")
        print(chat_history[-1][1])
        
        if chat_history and chat_history[-1][1]:
            if self.config.tts.type=="ARK_API":
                yield from self.ARK_read_text(chat_history[-1][1])
            else:
                yield from self.read_text(chat_history[-1][1])

    def read_chat_message(self, reply) -> Generator[bytes, None, None]:
        """
        Read the last message in the chat history.

        Args:
            chat_history (List[List[Optional[str]]]): Chat history.

        Yields:
            bytes: Audio data for the last message.
        """
        
        print("audio function: read_text")
        print("reply:")
        print(reply)
        # 去除字符串两端的方括号
        reply_str = reply.strip('[]')
        # 根据逗号分割字符串，但保留逗号和空格，以正确重建列表元素
        reply_list = [item.strip() for item in reply_str.split("', '")]
        sentence = ' '.join(reply_list)
        sentence = sentence.strip('\'')

        if self.config.tts.type=="ARK_API":
            yield from self.ARK_read_text(sentence)
        else:
            yield from self.read_text(sentence)
