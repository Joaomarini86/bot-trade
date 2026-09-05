#!/bin/bash
# ============================================================
# setup.sh — Bot Trade (Polymarket + Groktagon)
# Instala tudo automaticamente em qualquer Linux/Mac
# Uso: bash setup.sh
# ============================================================

set -e  # Para se qualquer comando falhar

echo ""
echo "╔══════════════════════════════════════════╗"
echo "║     BOT TRADE — Setup Automático         ║"
echo "║     Polymarket Bot + Groktagon           ║"
echo "╚══════════════════════════════════════════╝"
echo ""

# ---- Detectar OS ----
OS="linux"
ARCH=$(uname -m)
if [[ "$OSTYPE" == "darwin"* ]]; then
  OS="mac"
fi
echo "🖥️  Sistema: $OS ($ARCH)"

# ============================================================
# 1. NVM + Node.js 20
# ============================================================
echo ""
echo "📦 [1/4] Instalando Node.js 20 via NVM..."

export NVM_DIR="$HOME/.nvm"
if [ ! -d "$NVM_DIR" ]; then
  curl -o- https://raw.githubusercontent.com/nvm-sh/nvm/v0.40.3/install.sh | bash
fi
[ -s "$NVM_DIR/nvm.sh" ] && \. "$NVM_DIR/nvm.sh"

nvm install 20 --silent
nvm use 20 --silent
echo "✅ Node.js: $(node --version) | npm: $(npm --version)"

# ============================================================
# 2. Dependências do Polymarket Bot
# ============================================================
echo ""
echo "📦 [2/4] Instalando dependências do Polymarket Bot..."
cd polymarket-bot
npm install --silent
cd ..
echo "✅ Polymarket Bot pronto"

# ============================================================
# 3. Python venv + Groktagon
# ============================================================
echo ""
echo "📦 [3/4] Instalando dependências do Groktagon (Python)..."
cd groktagon
python3 -m venv .venv
.venv/bin/pip install --quiet --upgrade pip
.venv/bin/pip install --quiet -r requirements.txt
cd ..
echo "✅ Groktagon pronto"

# ============================================================
# 4. Configuração — .env
# ============================================================
echo ""
echo "📦 [4/4] Criando arquivos de configuração..."

# Polymarket .env
if [ ! -f "polymarket-bot/.env" ]; then
  cp polymarket-bot/.env.example polymarket-bot/.env
  echo "✅ polymarket-bot/.env criado (edite com sua chave!)"
else
  echo "⚠️  polymarket-bot/.env já existe (não sobrescrito)"
fi

# ============================================================
# 5. DNS Fix para Brasil (opcional)
# ============================================================
echo ""
echo "🌐 Verificando acesso ao Polymarket..."
if ! curl -s --max-time 5 "https://clob.polymarket.com" > /dev/null 2>&1; then
  echo "⚠️  Polymarket bloqueado por DNS. Aplicando correção..."
  echo "   (será solicitada sua senha sudo)"
  sudo bash -c 'cat >> /etc/hosts << "HOSTS"

# Polymarket + Groktagon DNS bypass
104.18.34.205 clob.polymarket.com
104.18.34.205 data-api.polymarket.com
104.18.34.205 gamma-api.polymarket.com
104.18.34.205 polymarket.com
104.18.34.205 ws-live-data.polymarket.com
23.22.130.173 client-api-2-74b1891ee9f9.herokuapp.com
104.18.38.143 api.dexscreener.com
174.138.15.144 api.rugcheck.xyz
104.20.24.29 quote-api.jup.ag
HOSTS
echo "✅ DNS corrigido!"'
else
  echo "✅ Polymarket acessível!"
fi

# ============================================================
# Pronto!
# ============================================================
echo ""
echo "╔══════════════════════════════════════════╗"
echo "║  ✅ SETUP CONCLUÍDO!                     ║"
echo "╚══════════════════════════════════════════╝"
echo ""
echo "📋 PRÓXIMOS PASSOS:"
echo ""
echo "  1. Configure sua chave privada:"
echo "     nano polymarket-bot/.env"
echo "     (coloque sua POLYMARKET_PRIVATE_KEY)"
echo ""
echo "  2. Configure o Groktagon (opcional, para Solana):"
echo "     export SOLANA_PRIVATE_KEY='sua_chave'"
echo "     export GROKTAGON_DRY_RUN=true"
echo ""
echo "  3. Rode os bots:"
echo "     bash run.sh"
echo ""
