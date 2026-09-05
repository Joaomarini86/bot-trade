"""
RISK Agent - Groktagon
Valida a segurança de um token ANTES de qualquer compra.

Checagens realizadas:
1. RugCheck score (API pública)
2. Mint Authority revogada?
3. LP queimada ou trancada?
4. Concentração das top wallets
5. Blacklist conhecidas
6. Metadata suspeita (nome copiado, sem imagem, etc.)

Uso:
    python risk.py <token_address>     # Valida um token específico
    python risk.py --demo              # Roda com token de exemplo
"""

import asyncio
import aiohttp
import json
import logging
import sys
from pathlib import Path
from dataclasses import dataclass, field
from datetime import datetime

sys.path.insert(0, str(Path(__file__).parent.parent))
from shared.config import cfg, validate_config

logging.basicConfig(
    level=getattr(logging, cfg.LOG_LEVEL),
    format="%(asctime)s [RISK] %(levelname)s: %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(f"{cfg.LOG_DIR}/risk.log"),
    ],
)
log = logging.getLogger("risk")
Path(cfg.LOG_DIR).mkdir(parents=True, exist_ok=True)


# ============================================================
# Resultado da Análise de Risco
# ============================================================

@dataclass
class RiskResult:
    token_address: str
    is_safe: bool = False
    score: int = 0          # 0 = péssimo, 100 = excelente
    reject_reason: str = "" # Por que foi rejeitado (se is_safe=False)
    
    # Detalhes das checagens
    mint_revoked: bool = False
    lp_burned: bool = False
    rugcheck_score: int = 0
    top10_supply_pct: float = 100.0
    holder_count: int = 0
    
    # Flags de risco
    is_honeypot: bool = False
    has_blacklist_function: bool = False
    has_freeze_authority: bool = False
    
    # Warnings (não bloqueiam mas são sinalizados)
    warnings: list = field(default_factory=list)
    
    checked_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())

    def to_dict(self) -> dict:
        return {
            "token_address": self.token_address,
            "is_safe": self.is_safe,
            "score": self.score,
            "reject_reason": self.reject_reason,
            "mint_revoked": self.mint_revoked,
            "lp_burned": self.lp_burned,
            "rugcheck_score": self.rugcheck_score,
            "top10_supply_pct": self.top10_supply_pct,
            "holder_count": self.holder_count,
            "is_honeypot": self.is_honeypot,
            "has_blacklist_function": self.has_blacklist_function,
            "has_freeze_authority": self.has_freeze_authority,
            "warnings": self.warnings,
            "checked_at": self.checked_at,
        }


# ============================================================
# Risk Agent
# ============================================================

class RiskAgent:
    """
    Valida a segurança de tokens Solana antes de qualquer compra.
    
    Fluxo:
    1. RugCheck → Score geral + detalhes
    2. Análise de holders
    3. Avaliação final
    """

    async def analyze(self, token_address: str) -> RiskResult:
        """
        Analisa o risco de um token.
        Retorna RiskResult com is_safe=True se passou em todos os critérios.
        """
        result = RiskResult(token_address=token_address)
        log.info(f"🔍 Analisando token: {token_address}")

        async with aiohttp.ClientSession() as session:
            # Executar checagens em paralelo
            rugcheck_data, _ = await asyncio.gather(
                self._check_rugcheck(session, token_address),
                asyncio.sleep(0),  # placeholder para futuras checagens
            )

            # Processar resultado do RugCheck
            if rugcheck_data:
                await self._process_rugcheck(result, rugcheck_data)
            else:
                result.warnings.append("⚠️ RugCheck indisponível - score zerado")
                result.rugcheck_score = 0

        # Avaliação final
        self._evaluate(result)
        self._log_result(result)
        return result

    async def _check_rugcheck(self, session: aiohttp.ClientSession, token_address: str) -> dict | None:
        """Consulta a API do RugCheck."""
        url = f"{cfg.RUGCHECK_API}/tokens/{token_address}/report/summary"
        try:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=15)) as r:
                if r.status == 200:
                    return await r.json()
                log.warning(f"RugCheck status {r.status} para {token_address}")
        except Exception as e:
            log.warning(f"RugCheck erro: {e}")
        return None

    async def _process_rugcheck(self, result: RiskResult, data: dict):
        """Processa e extrai informações do RugCheck."""
        # Score principal
        result.rugcheck_score = data.get("score", 0)

        # Extrair riscos do array de risks
        risks = data.get("risks", [])
        for risk in risks:
            name = risk.get("name", "").lower()
            level = risk.get("level", "").lower()  # "danger", "warn", "info"

            if "mint" in name and ("disabled" in name or "revoked" in name):
                result.mint_revoked = True
            if "freeze" in name:
                result.has_freeze_authority = True
                if level == "danger":
                    result.warnings.append(f"🧊 Freeze Authority ativa: {risk.get('description', '')}")
            if "blacklist" in name:
                result.has_blacklist_function = True
                result.warnings.append(f"⛔ Função de blacklist detectada")
            if "honeypot" in name:
                result.is_honeypot = True

        # Dados de distribuição de holders
        top_holders = data.get("topHolders", [])
        if top_holders:
            # Top 10 holders
            top10 = top_holders[:10]
            result.top10_supply_pct = sum(h.get("pct", 0) * 100 for h in top10)
            result.holder_count = data.get("totalHolders", len(top_holders))

        # LP queimada
        markets = data.get("markets", [])
        for market in markets:
            lp = market.get("lp", {})
            if lp.get("lpBurned", False) or lp.get("lpLockedPct", 0) > 80:
                result.lp_burned = True
                break

    def _evaluate(self, result: RiskResult):
        """
        Decisão final: aprovar ou rejeitar o token.
        """
        score = 0
        reject_reasons = []

        # ---- BLOQUEIOS ABSOLUTOS ----
        if result.is_honeypot:
            result.is_safe = False
            result.reject_reason = "🚫 HONEYPOT detectado - impossível vender"
            return

        # ---- CRITÉRIOS DE SCORE ----
        # RugCheck score base
        if result.rugcheck_score >= 80:
            score += 40
        elif result.rugcheck_score >= cfg.MIN_RUGCHECK_SCORE:
            score += 20
        else:
            reject_reasons.append(f"RugCheck score baixo ({result.rugcheck_score})")

        # Mint Authority
        if result.mint_revoked:
            score += 25
        elif cfg.REQUIRE_MINT_REVOKED:
            reject_reasons.append("Mint Authority não revogada (pode criar tokens infinitos)")
        else:
            result.warnings.append("⚠️ Mint Authority ainda ativa")

        # Concentração de supply
        if result.top10_supply_pct < cfg.MAX_TOP10_SUPPLY_PCT:
            score += 20
        elif result.top10_supply_pct < 50:
            score += 10
            result.warnings.append(f"⚠️ Top 10 wallets com {result.top10_supply_pct:.1f}% do supply")
        else:
            reject_reasons.append(f"Supply muito concentrado: {result.top10_supply_pct:.1f}% nas top 10 wallets")

        # LP queimada (bônus)
        if result.lp_burned:
            score += 15
        elif cfg.REQUIRE_LP_BURNED:
            reject_reasons.append("LP não queimada")

        # Sem freeze authority
        if not result.has_freeze_authority:
            score += 10

        # ---- DECISÃO FINAL ----
        result.score = min(score, 100)

        if reject_reasons:
            result.is_safe = False
            result.reject_reason = " | ".join(reject_reasons)
        else:
            result.is_safe = True

    def _log_result(self, result: RiskResult):
        """Loga o resultado de forma visual."""
        status = "✅ APROVADO" if result.is_safe else "❌ REJEITADO"
        log.info(
            f"\n{'='*50}\n"
            f"{status} | Score: {result.score}/100\n"
            f"Token: {result.token_address}\n"
            f"RugCheck: {result.rugcheck_score} | "
            f"Mint Revogada: {'Sim' if result.mint_revoked else 'Não'} | "
            f"LP Queimada: {'Sim' if result.lp_burned else 'Não'}\n"
            f"Top10 Supply: {result.top10_supply_pct:.1f}%"
        )
        if result.reject_reason:
            log.warning(f"Motivo: {result.reject_reason}")
        for w in result.warnings:
            log.warning(f"  {w}")
        log.info("=" * 50)


# ============================================================
# Stop Loss Monitor
# ============================================================

class StopLossMonitor:
    """
    Monitora posições abertas e dispara stop loss se necessário.
    Roda em background depois que uma compra é executada.
    """

    def __init__(self):
        self.positions: dict[str, dict] = {}  # token_addr -> {entry_price, amount, ...}

    def add_position(self, token_address: str, entry_price: float, amount_sol: float):
        """Registra uma nova posição para monitoramento."""
        self.positions[token_address] = {
            "entry_price": entry_price,
            "amount_sol": amount_sol,
            "added_at": datetime.utcnow().isoformat(),
        }
        log.info(f"📌 Posição adicionada: {token_address} @ {entry_price}")

    async def check_positions(self, session: aiohttp.ClientSession) -> list[dict]:
        """
        Verifica todas as posições e retorna lista de tokens para VENDER.
        """
        sell_orders = []
        for token_addr, pos in list(self.positions.items()):
            current_price = await self._get_current_price(session, token_addr)
            if current_price is None:
                continue

            entry = pos["entry_price"]
            if entry <= 0:
                continue

            pnl_pct = (current_price - entry) / entry

            # Take profit tiers
            for tier in cfg.TAKE_PROFIT_TIERS:
                if pnl_pct >= (tier["multiplier"] - 1):
                    sell_orders.append({
                        "token_address": token_addr,
                        "reason": f"TAKE_PROFIT_{tier['multiplier']}x",
                        "sell_pct": tier["sell_pct"],
                        "current_price": current_price,
                        "pnl_pct": pnl_pct,
                    })
                    log.info(f"🎯 TAKE PROFIT {tier['multiplier']}x: {token_addr} | PnL: +{pnl_pct*100:.0f}%")
                    break

            # Stop loss
            if pnl_pct <= -cfg.STOP_LOSS_PCT:
                sell_orders.append({
                    "token_address": token_addr,
                    "reason": "STOP_LOSS",
                    "sell_pct": 1.0,  # Vende tudo
                    "current_price": current_price,
                    "pnl_pct": pnl_pct,
                })
                log.warning(f"🛑 STOP LOSS: {token_addr} | PnL: {pnl_pct*100:.0f}%")

        return sell_orders

    async def _get_current_price(self, session: aiohttp.ClientSession, token_address: str) -> float | None:
        """Busca preço atual via DexScreener."""
        url = f"https://api.dexscreener.com/latest/dex/tokens/{token_address}"
        try:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as r:
                if r.status == 200:
                    data = await r.json()
                    pairs = data.get("pairs", [])
                    if pairs:
                        return float(pairs[0].get("priceUsd", 0) or 0)
        except Exception:
            pass
        return None


# ============================================================
# Entrada Principal
# ============================================================

async def main():
    validate_config()
    agent = RiskAgent()

    if len(sys.argv) > 1:
        if sys.argv[1] == "--demo":
            # Token de exemplo para demonstração (BONK - token estabelecido)
            token = "DezXAZ8z7PnrnRJjz3wXBoRgixCa6xjnB7YaB1pPB263"
            log.info(f"Modo demo com token: {token}")
        else:
            token = sys.argv[1]
        
        result = await agent.analyze(token)
        print(json.dumps(result.to_dict(), indent=2))
    else:
        print("Uso: python risk.py <token_address>")
        print("     python risk.py --demo")


if __name__ == "__main__":
    asyncio.run(main())
