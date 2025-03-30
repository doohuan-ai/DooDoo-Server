# Install

python 3.10.6

```bash
pip install -r requirements.txt
pip install "fastapi[standard]"
```

# Run
```bash
fastapi dev main.py
```

# Test
确保已安装PyAudio，在Ubuntu上可能需要先安装portaudio：
```bash
sudo apt-get install portaudio19-dev
pip install pyaudio
```
运行服务器：
```bash
python run.py
```
