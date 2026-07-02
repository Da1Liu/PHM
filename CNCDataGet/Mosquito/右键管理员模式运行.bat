@echo off
echo 正在停止 Mosquitto 服务...
net stop mosquitto
echo.
echo 正在启动 Mosquitto 服务...
net start mosquitto
echo.
echo Mosquitto 服务重启完成！
pause