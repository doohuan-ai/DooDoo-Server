package com.doodoo.voicechat

import android.media.AudioFormat
import android.media.AudioRecord
import android.media.MediaPlayer
import android.media.MediaRecorder
import android.util.Base64
import android.util.Log
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import org.java_websocket.client.WebSocketClient
import org.java_websocket.handshake.ServerHandshake
import org.json.JSONArray
import org.json.JSONObject
import java.io.File
import java.io.FileOutputStream
import java.net.URI
import java.nio.ByteBuffer
import java.util.UUID
import kotlin.coroutines.CoroutineContext

class VoiceChatClient(
    private val serverUrl: String,
    private val userId: String = "android_user_${UUID.randomUUID()}"
) : CoroutineScope {

    companion object {
        private const val TAG = "VoiceChatClient"
        
        // 音频录制参数
        private const val SAMPLE_RATE = 16000
        private const val CHANNEL_CONFIG = AudioFormat.CHANNEL_IN_MONO
        private const val AUDIO_FORMAT = AudioFormat.ENCODING_PCM_16BIT
        private const val BUFFER_SIZE_FACTOR = 2
        
        // WebSocket消息类型
        private const val ACTION_START = "start"
        private const val ACTION_AUDIO_DATA = "audio_data"
        private const val ACTION_STOP = "stop"
        
        // WebSocket响应状态
        private const val STATUS_STARTED = "started"
        private const val STATUS_RECOGNIZING = "recognizing"
        private const val STATUS_CHAT_RESPONSE = "chat_response"
        private const val STATUS_SYNTHESIZING = "synthesizing"
        private const val STATUS_SYNTHESIS_COMPLETE = "synthesis_complete"
        private const val STATUS_ERROR = "error"
        private const val STATUS_STOPPED = "stopped"
    }
    
    // 记录会话ID，用于连续对话
    private var conversationId: String = ""
    
    // 用于播放语音的MediaPlayer
    private var mediaPlayer: MediaPlayer? = null
    
    // 临时文件用于存储音频响应
    private var tempAudioFile: File? = null
    
    // WebSocket客户端
    private var webSocketClient: WebSocketClient? = null
    
    // 录音相关变量
    private var audioRecord: AudioRecord? = null
    private var recordingBuffer: ByteArray? = null
    private var isRecording = false
    private var recordingJob: Job? = null
    
    // 状态流，用于向UI层通知状态变化
    private val _connectionState = MutableStateFlow(ConnectionState.DISCONNECTED)
    val connectionState: StateFlow<ConnectionState> = _connectionState.asStateFlow()
    
    private val _recognitionResult = MutableStateFlow<String>("")
    val recognitionResult: StateFlow<String> = _recognitionResult.asStateFlow()
    
    private val _chatResponse = MutableStateFlow<String>("")
    val chatResponse: StateFlow<String> = _chatResponse.asStateFlow()
    
    private val _isProcessing = MutableStateFlow(false)
    val isProcessing: StateFlow<Boolean> = _isProcessing.asStateFlow()
    
    private val _isSpeaking = MutableStateFlow(false)
    val isSpeaking: StateFlow<Boolean> = _isSpeaking.asStateFlow()
    
    // 协程作用域
    private val job = Job()
    override val coroutineContext: CoroutineContext
        get() = Dispatchers.Main + job
    
    // 初始化WebSocket连接
    fun connect() {
        if (webSocketClient != null && webSocketClient?.isOpen == true) {
            Log.d(TAG, "已经连接，无需重新连接")
            return
        }
        
        _connectionState.value = ConnectionState.CONNECTING
        
        try {
            webSocketClient = object : WebSocketClient(URI(serverUrl)) {
                override fun onOpen(handshakedata: ServerHandshake?) {
                    Log.d(TAG, "WebSocket连接成功")
                    _connectionState.value = ConnectionState.CONNECTED
                }
                
                override fun onMessage(message: String?) {
                    message?.let { handleWebSocketMessage(it) }
                }
                
                override fun onClose(code: Int, reason: String?, remote: Boolean) {
                    Log.d(TAG, "WebSocket连接关闭：code=$code, reason=$reason, remote=$remote")
                    _connectionState.value = ConnectionState.DISCONNECTED
                    isRecording = false
                    recordingJob?.cancel()
                }
                
                override fun onError(ex: Exception?) {
                    Log.e(TAG, "WebSocket错误", ex)
                    _connectionState.value = ConnectionState.ERROR
                }
            }
            
            webSocketClient?.connect()
        } catch (e: Exception) {
            Log.e(TAG, "连接WebSocket时出错", e)
            _connectionState.value = ConnectionState.ERROR
        }
    }
    
    // 断开WebSocket连接
    fun disconnect() {
        stopRecording()
        webSocketClient?.close()
        webSocketClient = null
        _connectionState.value = ConnectionState.DISCONNECTED
    }
    
    // 开始录音并发送到服务器
    fun startRecording() {
        if (isRecording || webSocketClient?.isOpen != true) {
            Log.d(TAG, "无法开始录音：isRecording=$isRecording, isWebSocketOpen=${webSocketClient?.isOpen}")
            return
        }
        
        isRecording = true
        _isProcessing.value = true
        
        // 发送开始命令
        val startJson = JSONObject().apply {
            put("action", ACTION_START)
            put("user_id", userId)
            put("conversation_id", conversationId)
        }
        
        webSocketClient?.send(startJson.toString())
        
        // 初始化音频录制
        val bufferSize = AudioRecord.getMinBufferSize(
            SAMPLE_RATE,
            CHANNEL_CONFIG,
            AUDIO_FORMAT
        ) * BUFFER_SIZE_FACTOR
        
        recordingBuffer = ByteArray(bufferSize)
        
        try {
            audioRecord = AudioRecord(
                MediaRecorder.AudioSource.MIC,
                SAMPLE_RATE,
                CHANNEL_CONFIG,
                AUDIO_FORMAT,
                bufferSize
            )
            
            if (audioRecord?.state != AudioRecord.STATE_INITIALIZED) {
                Log.e(TAG, "AudioRecord未正确初始化")
                _isProcessing.value = false
                isRecording = false
                return
            }
            
            audioRecord?.startRecording()
            
            // 在协程中处理录音
            recordingJob = launch {
                try {
                    withContext(Dispatchers.IO) {
                        val buffer = recordingBuffer ?: return@withContext
                        val audioRecord = audioRecord ?: return@withContext
                        
                        while (isActive && isRecording) {
                            val readResult = audioRecord.read(buffer, 0, buffer.size)
                            
                            if (readResult > 0) {
                                // 将PCM音频数据转换为Base64并发送
                                val audioData = ByteArray(readResult)
                                System.arraycopy(buffer, 0, audioData, 0, readResult)
                                
                                val base64Audio = Base64.encodeToString(audioData, Base64.NO_WRAP)
                                
                                val audioJson = JSONObject().apply {
                                    put("action", ACTION_AUDIO_DATA)
                                    put("data", base64Audio)
                                }
                                
                                webSocketClient?.send(audioJson.toString())
                            }
                            
                            // 短暂暂停，避免发送过多数据
                            withContext(Dispatchers.IO) {
                                Thread.sleep(10)
                            }
                        }
                    }
                } catch (e: Exception) {
                    Log.e(TAG, "录音过程中出错", e)
                    withContext(Dispatchers.Main) {
                        _isProcessing.value = false
                        isRecording = false
                    }
                }
            }
            
        } catch (e: Exception) {
            Log.e(TAG, "启动录音时出错", e)
            _isProcessing.value = false
            isRecording = false
        }
    }
    
    // 停止录音
    fun stopRecording() {
        if (!isRecording) return
        
        isRecording = false
        recordingJob?.cancel()
        
        try {
            audioRecord?.stop()
            audioRecord?.release()
            audioRecord = null
            
            // 发送停止命令
            val stopJson = JSONObject().apply {
                put("action", ACTION_STOP)
            }
            webSocketClient?.send(stopJson.toString())
            
        } catch (e: Exception) {
            Log.e(TAG, "停止录音时出错", e)
        }
    }
    
    // 处理WebSocket消息
    private fun handleWebSocketMessage(message: String) {
        try {
            Log.d(TAG, "收到WebSocket消息: $message")
            val json = JSONObject(message)
            val status = json.getString("status")
            
            when (status) {
                STATUS_STARTED -> {
                    Log.d(TAG, "语音识别已开始")
                }
                
                STATUS_RECOGNIZING -> {
                    val text = json.getString("text")
                    val isFinal = json.getBoolean("is_final")
                    
                    Log.d(TAG, "识别结果: $text (isFinal=$isFinal)")
                    _recognitionResult.value = text
                    
                    if (isFinal) {
                        _isProcessing.value = true
                    }
                }
                
                STATUS_CHAT_RESPONSE -> {
                    val text = json.getString("text")
                    conversationId = json.optString("conversation_id", conversationId)
                    
                    Log.d(TAG, "对话回复: $text")
                    _chatResponse.value = text
                }
                
                STATUS_SYNTHESIZING -> {
                    Log.d(TAG, "开始语音合成")
                    _isSpeaking.value = true
                }
                
                STATUS_SYNTHESIS_COMPLETE -> {
                    Log.d(TAG, "语音合成完成")
                    val audioDataArray = json.getJSONArray("audio_data")
                    playAudioResponse(audioDataArray)
                }
                
                STATUS_ERROR -> {
                    val errorMsg = json.optString("message", "未知错误")
                    Log.e(TAG, "服务器返回错误: $errorMsg")
                    _isProcessing.value = false
                }
                
                STATUS_STOPPED -> {
                    Log.d(TAG, "语音识别已停止")
                    _isProcessing.value = false
                }
            }
            
        } catch (e: Exception) {
            Log.e(TAG, "处理WebSocket消息时出错", e)
        }
    }
    
    // 播放语音合成的响应
    private fun playAudioResponse(audioDataArray: JSONArray) {
        launch(Dispatchers.IO) {
            try {
                // 创建临时文件
                val cacheDir = File(System.getProperty("java.io.tmpdir") ?: "/tmp")
                if (!cacheDir.exists()) cacheDir.mkdirs()
                
                val tempFile = File.createTempFile("audio_response_", ".mp3", cacheDir)
                tempAudioFile = tempFile
                
                // 将Base64解码的音频数据写入文件
                FileOutputStream(tempFile).use { fos ->
                    for (i in 0 until audioDataArray.length()) {
                        val chunk = audioDataArray.getString(i)
                        val audioBytes = Base64.decode(chunk, Base64.DEFAULT)
                        fos.write(audioBytes)
                    }
                }
                
                // 在主线程中播放音频
                withContext(Dispatchers.Main) {
                    try {
                        // 释放之前的MediaPlayer
                        mediaPlayer?.release()
                        
                        // 创建新的MediaPlayer
                        mediaPlayer = MediaPlayer().apply {
                            setDataSource(tempFile.absolutePath)
                            setOnCompletionListener {
                                _isSpeaking.value = false
                                it.release()
                                tempFile.delete()
                            }
                            setOnErrorListener { _, what, extra ->
                                Log.e(TAG, "MediaPlayer错误: what=$what, extra=$extra")
                                _isSpeaking.value = false
                                true
                            }
                            prepare()
                            start()
                        }
                    } catch (e: Exception) {
                        Log.e(TAG, "播放音频时出错", e)
                        _isSpeaking.value = false
                    }
                }
                
            } catch (e: Exception) {
                Log.e(TAG, "处理音频响应时出错", e)
                withContext(Dispatchers.Main) {
                    _isSpeaking.value = false
                }
            }
        }
    }
    
    // 清理资源
    fun release() {
        stopRecording()
        disconnect()
        mediaPlayer?.release()
        mediaPlayer = null
        tempAudioFile?.delete()
        job.cancel()
    }
    
    // 连接状态枚举
    enum class ConnectionState {
        DISCONNECTED,
        CONNECTING,
        CONNECTED,
        ERROR
    }
} 