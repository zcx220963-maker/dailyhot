@echo off
chcp 65001 >/dev/null 2>&1
cd /d "C:\Users\xu'zhi'cheng\Desktop\agent\search-agent\gpt-researcher"
E:\python\python.exe scripts\daily_hot_push.py >> logs\daily_hot.log 2>&1
