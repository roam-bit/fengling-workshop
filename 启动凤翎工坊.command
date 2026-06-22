#!/bin/bash
# 凤翎工坊本地 server 启动器 —— 双击运行,这个终端窗口保持开着,网页就能一直访问。
# 关掉这个窗口 = 关掉 server = 网页打不开(这是正常的)。
cd "$(dirname "$0")" || exit 1   # 自动用脚本所在目录,clone 到任何位置双击都能用

# 若已有 server 占着 8131,先关掉旧的(防止"端口被占用"报错)
OLD=$(lsof -ti:8131 2>/dev/null)
if [ -n "$OLD" ]; then
  echo "发现旧的 server 还在跑,先关掉它…"
  kill $OLD 2>/dev/null
  sleep 1
fi

echo "────────────────────────────────────────"
echo "  🪶 凤翎工坊 server 启动中…"
echo "  浏览器打开:  http://localhost:8131"
echo "  ⚠️ 别关这个窗口 —— 关了网页就打不开了"
echo "────────────────────────────────────────"
python3 server.py

# 走到这里说明 server 停了(正常情况它会一直运行不退出)。窗口停住,方便看清原因。
echo ""
echo "⚠️ server 已停止。如果上面有红色报错,那就是原因;否则多半是被手动关了。"
echo "   想重新开:关掉这个窗口,再双击「启动凤翎工坊.command」。"
read -p "按回车键关闭此窗口…"
