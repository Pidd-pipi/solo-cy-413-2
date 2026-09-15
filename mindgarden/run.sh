#!/bin/sh
# 心晴花园一键启动
cd "$(dirname "$0")"
echo "🌻 启动心晴花园 MindGarden ..."
exec python3 server.py
