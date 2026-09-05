#!/bin/bash
# ============================================================
# run.sh — Inicia os bots em background
# Uso: bash run.sh [polymarket|groktagon|all]
# ============================================================

export NVM_DIR="$HOME/.nvm"
[ -s "$NVM_DIR/nvm.sh" ] && \. "$NVM_DIR/nvm.sh"

mkdir -p polymarket-bot/logs groktagon/logs

MODE=${1:-all}

start_polymarket() {
  echo "🎯 Iniciando Polymarket Bot..."
  cd polymarket-bot
  nohup npx tsx bot-config.ts > logs/polymarket.log 2>&1 &
  echo $! > .pid
  echo "✅ Polymarket rodando! PID: $(cat .pid)"
  echo "   Ver logs: tail -f polymarket-bot/logs/polymarket.log"
  cd ..
}

start_groktagon() {
  echo "🚀 Iniciando Groktagon..."
  cd groktagon
  source .venv/bin/activate
  nohup python main.py > logs/groktagon_main.log 2>&1 &
  echo $! > .pid
  echo "✅ Groktagon rodando! PID: $(cat .pid)"
  echo "   Ver logs: tail -f groktagon/logs/scout.log"
  cd ..
}

stop_all() {
  echo "🛑 Parando bots..."
  [ -f polymarket-bot/.pid ] && kill $(cat polymarket-bot/.pid) 2>/dev/null && rm polymarket-bot/.pid && echo "✅ Polymarket parado"
  [ -f groktagon/.pid ] && kill $(cat groktagon/.pid) 2>/dev/null && rm groktagon/.pid && echo "✅ Groktagon parado"
}

status() {
  echo "📊 Status dos bots:"
  if [ -f polymarket-bot/.pid ] && kill -0 $(cat polymarket-bot/.pid) 2>/dev/null; then
    echo "  🎯 Polymarket: ✅ RODANDO (PID: $(cat polymarket-bot/.pid))"
  else
    echo "  🎯 Polymarket: ❌ Parado"
  fi
  if [ -f groktagon/.pid ] && kill -0 $(cat groktagon/.pid) 2>/dev/null; then
    echo "  🚀 Groktagon: ✅ RODANDO (PID: $(cat groktagon/.pid))"
  else
    echo "  🚀 Groktagon: ❌ Parado"
  fi
}

case $MODE in
  polymarket) start_polymarket ;;
  groktagon)  start_groktagon ;;
  stop)       stop_all ;;
  status)     status ;;
  all)
    start_polymarket
    sleep 2
    start_groktagon
    echo ""
    echo "📡 Para ver os logs ao vivo:"
    echo "   tail -f polymarket-bot/logs/polymarket.log groktagon/logs/scout.log"
    echo ""
    echo "⛔ Para parar tudo: bash run.sh stop"
    ;;
  *)
    echo "Uso: bash run.sh [all|polymarket|groktagon|stop|status]"
    ;;
esac
