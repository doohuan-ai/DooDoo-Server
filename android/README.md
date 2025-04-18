# DooDoo 语音聊天安卓客户端

这是DooDoo语音聊天服务的安卓客户端应用，能够与服务端进行实时语音交互。

## 功能

- 实时语音录制并发送到服务端
- 流式语音识别
- 智能对话处理
- 语音合成并播放回复

## 使用方法

1. 确保服务端已经启动并正常运行
2. 在 `MainActivity.kt` 中修改 `SERVER_URL` 为你的服务器地址
3. 构建并运行安卓应用
4. 点击"开始录音"按钮开始语音对话
5. 点击"停止录音"按钮结束语音输入，等待服务器回复

## 技术架构

- 使用WebSocket进行实时通信
- Kotlin协程处理异步操作
- 流式状态管理
- AudioRecord用于录音
- MediaPlayer用于播放语音回复

## 注意事项

- 应用需要录音权限才能正常工作
- 请确保安卓设备能够连接到服务器网络
- 建议使用WiFi网络以保证语音质量和响应速度 