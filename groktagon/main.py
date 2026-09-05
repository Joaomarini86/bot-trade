"""
Groktagon - Orquestrador Principal
Coordena os agentes SCOUT → RISK → EXEC em um pipeline completo.

Fluxo:
  1. SCOUT detecta novo token
  2. RISK valida segurança
  3. EXEC executa compra (se aprovado)
  4. StopLossMonitor monitora posição em background

Uso:
    python main.py          # Roda o bot completo
    python main.py --demo   # Roda demonstração sem dinheiro
"""

import asyncio
import logging
import sys
import json
from pathlib import Path
from datetime import datetime

# Importa os agentes
sys.path.insert(0, str(Path(__file__).parent))
from shared.config import cfg, validate_config
from scout.scout import ScoutAgent
from risk.risk import RiskAgent, StopLossMonitor
from exec.exec import ExecAgent

logging.basicConfig(
    level=getattr(logging, cfg.LOG_LEVEL),
    format="%(asctime)s [MAIN] %(levelname)s: %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(f"{cfg.LOG_DIR}/main.log"),
    ],
)
log = logging.getLogger("main")
Path(cfg.LOG_DIR).mkdir(parents=True, exist_ok=True)

# Rastreia posições abertas: token_address -> {amount, entry_price}
OPEN_POSITIONS: dict[str, dict] = {}


class Groktagon:
    """
    Orquestrador do Groktagon Squad.
    Conecta SCOUT → RISK → EXEC em pipeline automático.
    """

    def __init__(self):
        self.scout = ScoutAgent()
        self.risk = RiskAgent()
        self.executor = ExecAgent()
        self.stop_loss = StopLossMonitor()
        self.active_snipes = 0
        self.stats = {
            "tokens_detected": 0,
            "tokens_approved": 0,
            "tokens_rejected": 0,
            "buys_executed": 0,
            "sells_executed": 0,
            "total_invested_sol": 0.0,
        }

        # Registra callback do SCOUT
        @self.scout.on_alert
        async def on_token_detected(token: dict):
            await self._pipeline(token)

    async def _pipeline(self, token: dict):
        """
        Pipeline completo: RISK check → EXEC buy
        """
        self.stats["tokens_detected"] += 1
        token_addr = token["token_address"]
        token_name = token.get("token_name", "???")
        scout_score = token.get("score", 0)

        log.info(f"\n{'🔔 NOVO TOKEN':=^50}")
        log.info(f"  {token_name} | Score SCOUT: {scout_score}/100")
        log.info(f"  Endereço: {token_addr}")

        # Verificar limite de snipes simultâneos
        if self.active_snipes >= cfg.MAX_CONCURRENT_SNIPES:
            log.warning(f"⏸️  Limite de {cfg.MAX_CONCURRENT_SNIPES} snipes simultâneos atingido. Pulando.")
            return

        # RISK: Validar segurança
        log.info("🔍 Enviando para análise de risco...")
        risk_result = await self.risk.analyze(token_addr)

        if not risk_result.is_safe:
            self.stats["tokens_rejected"] += 1
            log.warning(f"❌ Token rejeitado: {risk_result.reject_reason}")
            return

        self.stats["tokens_approved"] += 1
        log.info(f"✅ Token aprovado! Score RISK: {risk_result.score}/100")

        # EXEC: Comprar
        self.active_snipes += 1
        log.info(f"⚡ Executando compra de {cfg.SOL_PER_SNIPE} SOL...")

        exec_result = await self.executor.buy(
            token_address=token_addr,
            sol_amount=cfg.SOL_PER_SNIPE,
            context={
                "token_name": token_name,
                "scout_score": scout_score,
                "risk_score": risk_result.score,
                "risk_warnings": risk_result.warnings,
                "source": token.get("source"),
            },
        )
        self.active_snipes -= 1

        if exec_result.success:
            self.stats["buys_executed"] += 1
            self.stats["total_invested_sol"] += cfg.SOL_PER_SNIPE

            # Registrar posição para stop loss
            self.stop_loss.add_position(
                token_address=token_addr,
                entry_price=exec_result.price_per_token,
                amount_sol=cfg.SOL_PER_SNIPE,
            )
            OPEN_POSITIONS[token_addr] = {
                "amount_tokens": exec_result.amount_out,
                "entry_price": exec_result.price_per_token,
                "invested_sol": cfg.SOL_PER_SNIPE,
            }

            mode = "[DRY RUN]" if cfg.DRY_RUN else "[REAL]"
            log.info(
                f"🎉 {mode} COMPRA OK! {cfg.SOL_PER_SNIPE} SOL → {exec_result.amount_out:.2f} tokens"
            )
        else:
            log.error(f"❌ Falha na compra: {exec_result.error}")

        self._print_stats()

    def _print_stats(self):
        """Exibe estatísticas atuais."""
        log.info(
            f"\n📊 Stats | Detectados: {self.stats['tokens_detected']} | "
            f"Aprovados: {self.stats['tokens_approved']} | "
            f"Rejeitados: {self.stats['tokens_rejected']} | "
            f"Compras: {self.stats['buys_executed']} | "
            f"SOL investido: {self.stats['total_invested_sol']:.3f}"
        )

    async def run(self):
        """Inicia todos os agentes em paralelo."""
        mode = "DRY RUN (simulação)" if cfg.DRY_RUN else "⚠️  REAL - DINHEIRO REAL!"
        log.info(f"""
╔══════════════════════════════════════════╗
║         GROKTAGON v1.0                   ║
║         Solana Memecoin Sniper           ║
╠══════════════════════════════════════════╣
║  Modo: {mode:<35}║
║  SOL por snipe: {cfg.SOL_PER_SNIPE:<27.3f}║
║  Max simultâneos: {cfg.MAX_CONCURRENT_SNIPES:<25}║
╚══════════════════════════════════════════╝
        """)

        # Rodar SCOUT e monitor de stop-loss em paralelo
        await asyncio.gather(
            self.scout.run(interval_seconds=15),
            self._stop_loss_loop(),
        )

    async def _stop_loss_loop(self):
        """Loop de monitoramento de stop-loss em background."""
        import aiohttp
        log.info("🛡️  Stop-Loss monitor iniciado")
        async with aiohttp.ClientSession() as session:
            while True:
                if OPEN_POSITIONS:
                    sell_orders = await self.stop_loss.check_positions(session)
                    for order in sell_orders:
                        token_addr = order["token_address"]
                        pos = OPEN_POSITIONS.get(token_addr, {})
                        amount = pos.get("amount_tokens", 0)
                        if amount > 0:
                            log.info(f"📤 Vendendo {order['sell_pct']*100:.0f}% | Motivo: {order['reason']}")
                            result = await self.executor.sell(
                                token_address=token_addr,
                                token_amount=amount,
                                sell_pct=order["sell_pct"],
                                context={"reason": order["reason"], "pnl_pct": order["pnl_pct"]},
                            )
                            if result.success and order["sell_pct"] == 1.0:
                                OPEN_POSITIONS.pop(token_addr, None)
                                self.stop_loss.positions.pop(token_addr, None)
                                self.stats["sells_executed"] += 1

                await asyncio.sleep(30)  # Checa a cada 30 segundos


# ============================================================
# Entrada Principal
# ============================================================

async def main():
    validate_config()
    bot = Groktagon()
    await bot.run()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        log.info("🛑 Groktagon encerrado pelo usuário.")
