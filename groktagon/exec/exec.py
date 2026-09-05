"""
EXEC Agent - Groktagon
Executa compras e vendas de tokens na Solana via Jupiter Aggregator.

Responsabilidades:
- Recebe sinal aprovado do RISK
- Executa swap via Jupiter (melhor rota, menor slippage)
- Registra trades no log
- Em DRY_RUN, apenas simula sem enviar transação

Uso:
    python exec.py --demo              # Simula uma compra
    python exec.py <token_address>     # Compra token específico (DRY_RUN=true por segurança)
"""

import asyncio
import aiohttp
import json
import logging
import sys
import time
from pathlib import Path
from dataclasses import dataclass, field
from datetime import datetime

sys.path.insert(0, str(Path(__file__).parent.parent))
from shared.config import cfg, validate_config

logging.basicConfig(
    level=getattr(logging, cfg.LOG_LEVEL),
    format="%(asctime)s [EXEC] %(levelname)s: %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(f"{cfg.LOG_DIR}/exec.log"),
    ],
)
log = logging.getLogger("exec")
Path(cfg.LOG_DIR).mkdir(parents=True, exist_ok=True)

# SOL token address (nativo)
SOL_MINT = "So11111111111111111111111111111111111111112"
# USDC na Solana
USDC_MINT = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"

JUPITER_API = "https://quote-api.jup.ag/v6"


# ============================================================
# Resultado de Execução
# ============================================================

@dataclass
class ExecResult:
    token_address: str
    action: str  # "BUY" ou "SELL"
    success: bool = False
    tx_hash: str = ""
    amount_in: float = 0.0   # SOL gasto (compra) ou tokens vendidos
    amount_out: float = 0.0  # Tokens recebidos (compra) ou SOL recebido
    price_per_token: float = 0.0
    slippage_pct: float = 0.0
    dry_run: bool = True
    error: str = ""
    executed_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())

    def to_dict(self) -> dict:
        return {
            "token_address": self.token_address,
            "action": self.action,
            "success": self.success,
            "tx_hash": self.tx_hash,
            "amount_in": self.amount_in,
            "amount_out": self.amount_out,
            "price_per_token": self.price_per_token,
            "slippage_pct": self.slippage_pct,
            "dry_run": self.dry_run,
            "error": self.error,
            "executed_at": self.executed_at,
        }


# ============================================================
# Trade Logger
# ============================================================

class TradeLogger:
    """Salva todos os trades em arquivo JSONL para análise posterior."""

    def __init__(self):
        self.log_file = Path(cfg.LOG_DIR) / "trades.jsonl"

    def record(self, result: ExecResult, context: dict = None):
        """Registra um trade no arquivo de histórico."""
        entry = result.to_dict()
        if context:
            entry["context"] = context

        with open(self.log_file, "a") as f:
            f.write(json.dumps(entry) + "\n")

        mode = "[DRY RUN]" if result.dry_run else "[REAL]"
        status = "✅" if result.success else "❌"
        log.info(
            f"{status} {mode} {result.action} {result.token_address[:8]}...\n"
            f"   In: {result.amount_in:.4f} | Out: {result.amount_out:.4f}\n"
            f"   Preço: ${result.price_per_token:.8f} | TX: {result.tx_hash or 'N/A'}"
        )


# ============================================================
# EXEC Agent
# ============================================================

class ExecAgent:
    """
    Agente de Execução de Ordens.
    
    Em DRY_RUN=True: Obtém cotação real do Jupiter mas NÃO envia a transação.
    Em DRY_RUN=False: Obtém cotação E envia transação assinada.
    """

    def __init__(self):
        self.trade_logger = TradeLogger()

    async def buy(
        self,
        token_address: str,
        sol_amount: float = None,
        slippage_bps: int = 300,  # 3% de slippage padrão
        context: dict = None,
    ) -> ExecResult:
        """
        Compra um token com SOL.
        
        Args:
            token_address: Endereço do token a comprar
            sol_amount: Quantidade de SOL (padrão: cfg.SOL_PER_SNIPE)
            slippage_bps: Slippage em basis points (300 = 3%)
            context: Dados adicionais para logging (score, reasons, etc.)
        """
        sol_amount = sol_amount or cfg.SOL_PER_SNIPE
        result = ExecResult(
            token_address=token_address,
            action="BUY",
            amount_in=sol_amount,
            dry_run=cfg.DRY_RUN,
        )

        # Converter SOL para lamports (1 SOL = 1_000_000_000 lamports)
        amount_lamports = int(sol_amount * 1_000_000_000)

        log.info(
            f"{'[DRY RUN] ' if cfg.DRY_RUN else ''}BUY {sol_amount} SOL → {token_address[:8]}..."
        )

        async with aiohttp.ClientSession() as session:
            # Passo 1: Obter cotação do Jupiter
            quote = await self._get_quote(
                session,
                input_mint=SOL_MINT,
                output_mint=token_address,
                amount=amount_lamports,
                slippage_bps=slippage_bps,
            )

            if not quote:
                result.error = "Falha ao obter cotação do Jupiter"
                result.success = False
                self.trade_logger.record(result, context)
                return result

            # Calcular preço
            out_amount = int(quote.get("outAmount", 0))
            result.amount_out = out_amount / 1e9  # Aproximação (pode variar por decimais)
            result.slippage_pct = slippage_bps / 100
            if result.amount_out > 0:
                result.price_per_token = sol_amount / result.amount_out

            log.info(
                f"Cotação Jupiter: {sol_amount} SOL → {result.amount_out:.2f} tokens "
                f"(slippage: {result.slippage_pct}%)"
            )

            if cfg.DRY_RUN:
                # Modo simulação: não envia transação
                result.success = True
                result.tx_hash = f"DRY_RUN_{int(time.time())}"
                log.info(f"✅ [DRY RUN] Compra simulada com sucesso")
            else:
                # Modo real: criar e enviar transação
                tx_result = await self._execute_swap(session, quote)
                result.success = tx_result.get("success", False)
                result.tx_hash = tx_result.get("tx_hash", "")
                result.error = tx_result.get("error", "")

        self.trade_logger.record(result, context)
        return result

    async def sell(
        self,
        token_address: str,
        token_amount: float,
        sell_pct: float = 1.0,
        slippage_bps: int = 500,  # 5% slippage na venda (mais agressivo para garantir saída)
        context: dict = None,
    ) -> ExecResult:
        """
        Vende tokens por SOL.
        
        Args:
            token_address: Endereço do token a vender
            token_amount: Quantidade total de tokens (antes do sell_pct)
            sell_pct: Porcentagem a vender (1.0 = 100%, 0.5 = 50%)
            slippage_bps: Slippage em basis points
            context: Dados adicionais para logging
        """
        amount_to_sell = token_amount * sell_pct
        result = ExecResult(
            token_address=token_address,
            action="SELL",
            amount_in=amount_to_sell,
            dry_run=cfg.DRY_RUN,
        )

        log.info(
            f"{'[DRY RUN] ' if cfg.DRY_RUN else ''}SELL {sell_pct*100:.0f}% de {amount_to_sell:.2f} tokens"
        )

        # TODO: Precisamos saber os decimais do token para converter corretamente
        # Por ora, assumimos 6 decimais (padrão SPL)
        amount_raw = int(amount_to_sell * 1_000_000)

        async with aiohttp.ClientSession() as session:
            quote = await self._get_quote(
                session,
                input_mint=token_address,
                output_mint=SOL_MINT,
                amount=amount_raw,
                slippage_bps=slippage_bps,
            )

            if not quote:
                result.error = "Falha ao obter cotação de venda"
                result.success = False
                self.trade_logger.record(result, context)
                return result

            out_lamports = int(quote.get("outAmount", 0))
            result.amount_out = out_lamports / 1_000_000_000  # SOL recebido

            if cfg.DRY_RUN:
                result.success = True
                result.tx_hash = f"DRY_RUN_SELL_{int(time.time())}"
                log.info(f"✅ [DRY RUN] Venda simulada: ~{result.amount_out:.4f} SOL")
            else:
                tx_result = await self._execute_swap(session, quote)
                result.success = tx_result.get("success", False)
                result.tx_hash = tx_result.get("tx_hash", "")
                result.error = tx_result.get("error", "")

        self.trade_logger.record(result, context)
        return result

    async def _get_quote(
        self,
        session: aiohttp.ClientSession,
        input_mint: str,
        output_mint: str,
        amount: int,
        slippage_bps: int = 300,
    ) -> dict | None:
        """Obtém cotação via Jupiter Aggregator API v6."""
        params = {
            "inputMint": input_mint,
            "outputMint": output_mint,
            "amount": amount,
            "slippageBps": slippage_bps,
        }
        url = f"{JUPITER_API}/quote"
        try:
            async with session.get(url, params=params, timeout=aiohttp.ClientTimeout(total=15)) as r:
                if r.status == 200:
                    return await r.json()
                log.warning(f"Jupiter quote status: {r.status}")
        except Exception as e:
            log.error(f"Erro ao obter cotação Jupiter: {e}")
        return None

    async def _execute_swap(self, session: aiohttp.ClientSession, quote: dict) -> dict:
        """
        Cria e envia transação de swap via Jupiter.
        ATENÇÃO: Só chama em DRY_RUN=False!
        """
        if not cfg.SOLANA_PRIVATE_KEY:
            return {"success": False, "error": "SOLANA_PRIVATE_KEY não configurada"}

        try:
            # Passo 1: Obter swap transaction
            swap_payload = {
                "quoteResponse": quote,
                "userPublicKey": cfg.WALLET_ADDRESS,
                "wrapAndUnwrapSol": True,
                "dynamicComputeUnitLimit": True,
                "prioritizationFeeLamports": "auto",
            }

            async with session.post(
                f"{JUPITER_API}/swap",
                json=swap_payload,
                timeout=aiohttp.ClientTimeout(total=30),
            ) as r:
                if r.status != 200:
                    return {"success": False, "error": f"Jupiter swap error: {r.status}"}
                swap_data = await r.json()

            swap_tx = swap_data.get("swapTransaction")
            if not swap_tx:
                return {"success": False, "error": "swapTransaction vazio"}

            # Passo 2: Assinar e enviar
            # NOTA: Implementação completa requer solders ou solana-py
            # Por ora, retorna instrução para implementação posterior
            log.warning(
                "⚠️ Assinatura de transação requer solders/solana-py. "
                "Implementação completa pendente."
            )
            return {
                "success": False,
                "error": "Signing not yet implemented - instale solders",
                "swap_tx": swap_tx[:50] + "...",
            }

        except Exception as e:
            return {"success": False, "error": str(e)}


# ============================================================
# Entrada Principal
# ============================================================

async def main():
    validate_config()
    agent = ExecAgent()

    if "--demo" in sys.argv or len(sys.argv) < 2:
        # Demo: simula compra do BONK (token de exemplo, bem estabelecido)
        demo_token = "DezXAZ8z7PnrnRJjz3wXBoRgixCa6xjnB7YaB1pPB263"
        log.info(f"🎮 Demo mode | DRY_RUN={cfg.DRY_RUN}")
        result = await agent.buy(
            token_address=demo_token,
            sol_amount=0.01,  # Compra mínima para demo
            context={"source": "demo", "score": 75},
        )
        print(json.dumps(result.to_dict(), indent=2))
    elif len(sys.argv) >= 2:
        token = sys.argv[1]
        result = await agent.buy(token_address=token)
        print(json.dumps(result.to_dict(), indent=2))


if __name__ == "__main__":
    asyncio.run(main())
