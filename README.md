# 🤖 Bot Trade — Polymarket + Groktagon

> Bot de trading automatizado com duas estratégias independentes:
> - **Polymarket Bot** — Arbitragem e copy-trading em mercados de previsão
> - **Groktagon** — Sniper de memecoins na blockchain Solana

---

## ⚡ Setup Rápido (1 comando)

```bash
git clone https://github.com/SEU_USUARIO/bot-trade.git
cd bot-trade
bash setup.sh
```

O script instala tudo automaticamente:
- Node.js 20 (via NVM)
- Dependências npm do Polymarket Bot
- Python venv + dependências do Groktagon
- Correção de DNS (necessário no Brasil 🇧🇷)

---

## ⚙️ Configuração

### 1. Polymarket Bot

Edite o arquivo `polymarket-bot/.env`:
```bash
nano polymarket-bot/.env
```

```env
POLYMARKET_PRIVATE_KEY=0xSUA_CHAVE_PRIVADA_AQUI
CAPITAL_USD=50
DRY_RUN=true
```

**Como obter a chave privada:**
- Se você se cadastrou no Polymarket com **email/Magic Link**:
  1. Acesse: https://reveal.magic.link/polymarket
  2. Clique em **Reveal** → **Copy**
- Se usou **MetaMask**:
  1. MetaMask → ⋮ → Detalhes da conta → Exportar chave privada

> ⚠️ **NUNCA compartilhe sua chave privada com ninguém!**

### 2. Groktagon (Solana Sniper)

Configure via variáveis de ambiente antes de rodar:
```bash
export SOLANA_PRIVATE_KEY="sua_chave_base58"
export SOLANA_WALLET_ADDRESS="seu_endereco_publico"
export HELIUS_API_KEY="sua_key_do_helius_dev"  # opcional, mas melhora velocidade
export SOL_PER_SNIPE="0.05"        # quanto SOL por snipe (~$10)
export GROKTAGON_DRY_RUN="true"    # MANTER true até validar
```

---

## 🚀 Como Rodar

```bash
# Rodar os dois bots em background
bash run.sh

# Rodar apenas um
bash run.sh polymarket
bash run.sh groktagon

# Ver status
bash run.sh status

# Parar tudo
bash run.sh stop
```

### Ver logs ao vivo
```bash
# Polymarket
tail -f polymarket-bot/logs/polymarket.log

# Groktagon
tail -f groktagon/logs/scout.log

# Histórico de trades simulados do Groktagon
cat groktagon/logs/trades.jsonl
```

---

## 🧠 Como Funciona

### 🎯 Polymarket Bot

Roda 3 estratégias em paralelo:

| Estratégia | O que faz |
|---|---|
| **Smart Money** | Copia os top traders do Polymarket (só os com WR > 60%) |
| **Arbitrage** | Compra SIM + NÃO quando a soma < $1,00 → lucro garantido |
| **DipArb** | Compra quedas em mercados multi-resultado |

**Dashboard** mostra em tempo real:
- PnL diário/mensal
- Trades executados
- Risk status (limites de perda)

### 🚀 Groktagon

Pipeline de 4 agentes:
```
SCOUT (detecta) → RISK (valida) → EXEC (compra) → STOP-LOSS (monitor)
```

| Agente | Arquivo | Função |
|---|---|---|
| 🔭 SCOUT | `scout/scout.py` | Escaneia DexScreener + Pump.fun a cada 15s |
| 🚨 RISK | `risk/risk.py` | RugCheck, honeypot, concentração de supply |
| ⚡ EXEC | `exec/exec.py` | Swap via Jupiter Aggregator |
| 🛡️ STOP-LOSS | embutido no main | Vende em -40% ou take-profit (2x/5x/10x) |

---

## 📊 Como Avaliar os Resultados (DRY_RUN = 3 dias)

### Polymarket — Perguntas para responder:
- O PnL diário foi positivo na maioria dos dias?
- O Drawdown ficou abaixo de 10%?
- O Arb Profit foi > $0 pelo menos uma vez?

### Groktagon — Abrir `groktagon/logs/trades.jsonl` e verificar:
- Dos tokens que o bot "compraria", quantos subiram?
- Qual o multiplicador médio (2x? 5x?)?
- Taxa de aprovação do RISK (% que passa nos filtros)

> **Regra de ouro:** Se DRY_RUN por 3 dias mostrar lucro > custo de gas → pode ligar com dinheiro real.

---

## 🖥️ Requisitos de Hardware

| Componente | Mínimo | Recomendado |
|---|---|---|
| CPU | 1 core | 2+ cores |
| RAM | 1GB | 4GB |
| Disco | 500MB | 2GB |
| Rede | Qualquer | Fibra (baixa latência p/ Groktagon) |
| OS | Linux/Mac | Ubuntu 22.04+ |

> Os bots são leves — juntos usam ~200MB de RAM e < 5% de CPU.

---

## 🔒 Segurança

- ✅ `.env` está no `.gitignore` — **nunca vai para o GitHub**
- ✅ Chaves privadas carregadas só via variável de ambiente
- ✅ `DRY_RUN=true` por padrão — não move dinheiro sem você autorizar
- ✅ Stop-loss e daily loss limit embutidos

---

## 🛠️ Estrutura do Projeto

```
bot-trade/
├── setup.sh                 ← Instala tudo
├── run.sh                   ← Inicia/para os bots
├── .gitignore               ← Protege dados sensíveis
│
├── polymarket-bot/          ← Bot de arbitragem Polymarket
│   ├── .env.example         ← Modelo de configuração
│   ├── bot-config.ts        ← Config e estratégias
│   └── src/                 ← SDK completo TypeScript
│
└── groktagon/               ← Sniper Solana
    ├── main.py              ← Orquestrador
    ├── shared/config.py     ← Configuração central
    ├── scout/scout.py       ← Detecta tokens novos
    ├── risk/risk.py         ← Valida segurança
    └── exec/exec.py         ← Executa trades
```

---

## ❓ FAQ

**Q: Posso rodar em Windows?**
R: Sim, mas recomenda-se WSL2 (Ubuntu). Os scripts `.sh` não rodam no PowerShell nativo.

**Q: Preciso de dinheiro para testar?**
R: Não! `DRY_RUN=true` simula tudo com dados reais sem mover nenhum centavo.

**Q: O bot pode me fazer perder dinheiro?**
R: Em DRY_RUN, impossível. Em modo real, sim — por isso valide 3 dias de simulação antes. Coloque só o que você está disposto a perder.

**Q: Preciso de VPN para rodar no Brasil?**
R: Não! O `setup.sh` já resolve automaticamente adicionando os IPs ao `/etc/hosts`.

---

## 📜 Licença

Uso pessoal e educacional. Não é conselho financeiro.
