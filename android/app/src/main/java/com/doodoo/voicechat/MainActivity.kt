package com.doodoo.voicechat

import android.Manifest
import android.content.pm.PackageManager
import android.os.Bundle
import android.widget.Toast
import androidx.appcompat.app.AppCompatActivity
import androidx.core.app.ActivityCompat
import androidx.core.content.ContextCompat
import androidx.lifecycle.lifecycleScope
import com.doodoo.voicechat.databinding.ActivityMainBinding
import kotlinx.coroutines.flow.collect
import kotlinx.coroutines.launch

class MainActivity : AppCompatActivity() {

    companion object {
        private const val PERMISSION_REQUEST_RECORD_AUDIO = 1001
        // 替换为你的服务器地址
        private const val SERVER_URL = "ws://192.168.1.100:8000/android/voice-chat/"
    }

    private lateinit var binding: ActivityMainBinding
    private lateinit var voiceChatClient: VoiceChatClient
    private var isRecording = false

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        binding = ActivityMainBinding.inflate(layoutInflater)
        setContentView(binding.root)

        // 初始化语音聊天客户端
        voiceChatClient = VoiceChatClient(SERVER_URL)

        // 设置按钮点击事件
        binding.btnStartStop.setOnClickListener {
            if (isRecording) {
                stopRecording()
            } else {
                if (checkPermission()) {
                    startRecording()
                } else {
                    requestPermission()
                }
            }
        }

        // 观察连接状态
        lifecycleScope.launch {
            voiceChatClient.connectionState.collect { state ->
                updateConnectionStatus(state)
            }
        }

        // 观察识别结果
        lifecycleScope.launch {
            voiceChatClient.recognitionResult.collect { result ->
                binding.tvRecognitionResult.text = result
            }
        }

        // 观察对话回复
        lifecycleScope.launch {
            voiceChatClient.chatResponse.collect { response ->
                binding.tvChatResponse.text = response
            }
        }

        // 观察语音播放状态
        lifecycleScope.launch {
            voiceChatClient.isSpeaking.collect { isSpeaking ->
                if (isSpeaking) {
                    binding.tvStatusValue.text = getString(R.string.speaking)
                } else {
                    updateConnectionStatus(voiceChatClient.connectionState.value)
                }
            }
        }

        // 观察处理状态
        lifecycleScope.launch {
            voiceChatClient.isProcessing.collect { isProcessing ->
                binding.btnStartStop.isEnabled = !isProcessing || isRecording
            }
        }

        // 初始化连接
        voiceChatClient.connect()
    }

    private fun updateConnectionStatus(state: VoiceChatClient.ConnectionState) {
        binding.tvStatusValue.text = when (state) {
            VoiceChatClient.ConnectionState.DISCONNECTED -> getString(R.string.disconnected)
            VoiceChatClient.ConnectionState.CONNECTING -> getString(R.string.connecting)
            VoiceChatClient.ConnectionState.CONNECTED -> getString(R.string.connected)
            VoiceChatClient.ConnectionState.ERROR -> getString(R.string.connection_failed)
        }
    }

    private fun startRecording() {
        isRecording = true
        binding.btnStartStop.text = getString(R.string.stop_recording)
        voiceChatClient.startRecording()
    }

    private fun stopRecording() {
        isRecording = false
        binding.btnStartStop.text = getString(R.string.start_recording)
        voiceChatClient.stopRecording()
    }

    private fun checkPermission(): Boolean {
        return ContextCompat.checkSelfPermission(
            this,
            Manifest.permission.RECORD_AUDIO
        ) == PackageManager.PERMISSION_GRANTED
    }

    private fun requestPermission() {
        ActivityCompat.requestPermissions(
            this,
            arrayOf(Manifest.permission.RECORD_AUDIO),
            PERMISSION_REQUEST_RECORD_AUDIO
        )
    }

    override fun onRequestPermissionsResult(
        requestCode: Int,
        permissions: Array<out String>,
        grantResults: IntArray
    ) {
        super.onRequestPermissionsResult(requestCode, permissions, grantResults)
        if (requestCode == PERMISSION_REQUEST_RECORD_AUDIO) {
            if (grantResults.isNotEmpty() && grantResults[0] == PackageManager.PERMISSION_GRANTED) {
                startRecording()
            } else {
                Toast.makeText(
                    this,
                    "需要录音权限才能使用语音聊天功能",
                    Toast.LENGTH_SHORT
                ).show()
            }
        }
    }

    override fun onDestroy() {
        super.onDestroy()
        voiceChatClient.release()
    }
}