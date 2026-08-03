@echo off
REM Model Router 自启动脚本
REM 放入 shell:startup 或手动运行
REM 依赖: D:\AI\Hermes\venv\ 中的 Python

cd /d D:\AI\py\model_router
start "ModelRouter" /min D:\AI\Hermes\venv\Scripts\python.exe model_router_server.py
echo Model Router started (http://127.0.0.1:6060)
