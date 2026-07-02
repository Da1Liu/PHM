@echo off
REM 机床健康基线控制台启动脚本 (Windows)
REM 用法: 双击运行(真实模式) 或在命令行加 --mock 演示
cd /d "%~dp0\..\.."
echo 启动机床健康基线控制台...
echo 浏览器访问 http://127.0.0.1:9000
python -m phm_pipeline.server.app --port 9000 %*
pause
