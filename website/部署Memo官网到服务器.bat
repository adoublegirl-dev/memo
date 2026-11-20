@echo off
chcp 65001 >nul
cd /d "D:\个人\Hanako项目文件\Memo_V0.1.0\website"
echo 正在部署 Memo 官网到服务器...
echo.
python deploy_memo_site.py
echo.
echo 部署脚本执行结束。
pause
