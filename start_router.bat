@echo off
REM Model Router 自启动脚本
REM 放入 shell:startup 或手动运行

cd /d "%~dp0"
python -m uvicorn model_router.app:app --host 127.0.0.1 --port 6060
echo Model Router started (http://127.0.0.1:6060)
