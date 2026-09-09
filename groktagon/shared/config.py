"""
Groktagon - Configuração Centralizada
Bot de Sniper de Memecoins na Solana

Preencha as variáveis abaixo antes de rodar qualquer agente.
"""

import os
from dataclasses import dataclass

# ============================================================
# SEGURANÇA: Carregue sempre de variáveis de ambiente!
# Nunca cole chaves privadas diretamente aqui.
# Use: export SOLANA_PRIVATE_KEY="sua_chave_aqui"
# ============================================================

@dataclass
class Config:
    # ---- Solana ----
    # Chave privada da carteira Solana (base58)
    SOLANA_PRIVATE_KEY: str = os.getenv("SOLANA_PRIVATE_KEY", "")
    # Endereço público da carteira
    WALLET_ADDRESS: str = os.getenv("SOLANA_WALLET_ADDRESS", "")

    # ---- RPC (use um nó pago para velocidade!) ----
    # Gratuito mas lento: https://api.mainnet-beta.solana.com
    # Recomendado: https://rpc.helius.xyz/?api-key=SEU_API_KEY
    SOLANA_RPC_URL: str = os.getenv(
        "SOLANA_RPC_URL",
        "https://api.mainnet-beta.solana.com"
    )
    # Helius API Key (para WebSocket de novos tokens)
    HELIUS_API_KEY: str = os.getenv("HELIUS_API_KEY", "")

    # ---- Capital ----
    # Quantidade em SOL por snipe (começa pequeno!)
    SOL_PER_SNIPE: float = float(os.getenv("SOL_PER_SNIPE", "0.05"))  # ~$10
    # Máximo de snipes simultâneos
    MAX_CONCURRENT_SNIPES: int = int(os.getenv("MAX_CONCURRENT_SNIPES", "3"))

    # ---- Modo Simulação ----
    DRY_RUN: bool = os.getenv("GROKTAGON_DRY_RUN", "true").lower() == "true"

    # ---- Estratégia de Saída ----
    # Vender X% quando lucro atingir Y multiplicador
    TAKE_PROFIT_TIERS: list = None

    def __post_init__(self):
        if self.TAKE_PROFIT_TIERS is None:
            self.TAKE_PROFIT_TIERS = [
                {"multiplier": 2.0,  "sell_pct": 0.50},  # Tira 50% do capital no 2x
                {"multiplier": 5.0,  "sell_pct": 0.25},  # Tira 25% no 5x
                {"multiplier": 10.0, "sell_pct": 0.15},  # Tira 15% no 10x
                # Deixa 10% "moonbag" para o infinito
            ]

    # ---- Filtros de Segurança (RISK Agent) ----
    # AFROUXADO PARA SIMULAÇÃO: Deixando passar moedas lixo para ver o bot operar
    MAX_TOP10_SUPPLY_PCT: float = 100.0
    MIN_LIQUIDITY_USD: float = 1000.0
    REQUIRE_MINT_REVOKED: bool = False
    REQUIRE_LP_BURNED: bool = False
    MIN_RUGCHECK_SCORE: int = 0

    # ---- Stop Loss ----
    # Vender TUDO se cair X% do preço de entrada
    STOP_LOSS_PCT: float = 0.40  # -40%

    # ---- APIs externas ----
    RUGCHECK_API: str = "https://api.rugcheck.xyz/v1"
    DEXSCREENER_API: str = "https://api.dexscreener.com/latest"
    BIRDEYE_API: str = "https://public-api.birdeye.so/public"
    BIRDEYE_API_KEY: str = os.getenv("BIRDEYE_API_KEY", "")

    # ---- Logs ----
    LOG_DIR: str = os.path.join(os.path.dirname(__file__), "../logs")
    LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")


# Instância global
cfg = Config()

def validate_config():
    """Valida que as configurações mínimas estão presentes."""
    errors = []
    if not cfg.DRY_RUN:
        if not cfg.SOLANA_PRIVATE_KEY:
            errors.append("SOLANA_PRIVATE_KEY não configurada!")
        if not cfg.WALLET_ADDRESS:
            errors.append("SOLANA_WALLET_ADDRESS não configurada!")
    if not cfg.HELIUS_API_KEY:
        print("⚠️  HELIUS_API_KEY não configurada. Usando RPC público (mais lento).")
    if errors:
        for e in errors:
            print(f"❌ ERRO DE CONFIG: {e}")
        raise ValueError("Configure as variáveis de ambiente antes de rodar o bot.")
    print(f"✅ Config OK | DRY_RUN={'SIM' if cfg.DRY_RUN else 'NÃO - DINHEIRO REAL!'}")
    print(f"   SOL por snipe: {cfg.SOL_PER_SNIPE} SOL")
    print(f"   Max simultâneos: {cfg.MAX_CONCURRENT_SNIPES}")
