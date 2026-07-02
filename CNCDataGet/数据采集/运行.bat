@echo off
REM ====================================================
REM  项目启动脚本 (V5 - 彻底解决编码问题)
REM ====================================================

REM 确保命令行支持 UTF-8 (仅用于显示 Python 应用的中文输出)
chcp 65001 > nul

REM -----------------------------------------
REM 步骤 1: 环境检测与准备
REM -----------------------------------------
if exist "dataget\Scripts\activate.bat" (
    echo.
    echo [INFO] Virtual environment found. Skipping setup.
    goto :run
)

REM --- (If environment is not found, perform first-time setup) ---

echo.
echo =========================================
echo [SETUP] Initializing environment...
echo =========================================

python -m venv dataget
if errorlevel 1 goto :error_venv

pip config set global.index-url https://mirrors.tuna.tsinghua.edu.cn/pypi/web/simple
if errorlevel 1 goto :error_pip_config

echo.
echo [SETUP] Installing dependencies (Flask, pandas, numpy, flask_sock)...

call .\dataget\Scripts\activate.bat
if errorlevel 1 goto :error_activate

pip install Flask flask-cors pandas numpy flask-sock
if errorlevel 1 goto :error_install

REM -----------------------------------------
REM 步骤 2: 启动应用和打开 HTML (核心命令不变)
REM -----------------------------------------
:run
echo.
echo =========================================
echo [INFO] Setup complete. Launching application...
echo =========================================

REM **核心启动命令**：确保 CMD /K 内没有中文，避免乱码解析错误。
cmd /k "call .\dataget\Scripts\activate.bat & start index.html & python app.py"

goto :eof

REM -----------------------------------------
REM 错误处理部分
REM -----------------------------------------
:error_venv
echo.
echo [ERROR] Failed to create virtual environment.
goto :end

:error_pip_config
echo.
echo [ERROR] Failed to set pip mirror URL.
goto :end

:error_activate
echo.
echo [ERROR] Failed to activate environment.
goto :end

:error_install
echo.
echo [ERROR] Failed to install dependencies.
goto :end

:end
echo.
echo =========================================
echo Task failed. Press any key to close...
echo =========================================
pause > nul