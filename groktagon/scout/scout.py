"""
SCOUT Agent - Groktagon
Monitora a blockchain da Solana em tempo real.
Detecta novos tokens assim que os pools de liquidez são criados na Raydium.

Critérios de alerta:
- Pool novo na Raydium/Pump.fun
- Compradores crescendo mais rápido que volume (sinal de adoção orgânica)
- Mínimo de liquidez presente

Uso:
    python scout.py            # Modo normal (loga alertas)
    python scout.py --dry-run  # Força modo simulação
"""

import asyncio
import aiohttp
import json
import logging
import time
from datetime import datetime
from pathlib import Path
import sys
import os

# Adiciona shared ao path
sys.path.insert(0, str(Path(__file__).parent.parent))
from shared.config import cfg, validate_config

# ---- Setup de Logging ----
Path(cfg.LOG_DIR).mkdir(parents=True, exist_ok=True)
logging.basicConfig(
    level=getattr(logging, cfg.LOG_LEVEL),
    format="%(asctime)s [SCOUT] %(levelname)s: %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(f"{cfg.LOG_DIR}/scout.log"),
    ],
)
log = logging.getLogger("scout")


# ============================================================
# API Clients
# ============================================================

class DexScreenerClient:
    """Cliente para monitorar novos tokens via DexScreener API."""
    BASE = "https://api.dexscreener.com/latest"

    async def get_new_solana_pairs(self, session: aiohttp.ClientSession) -> list[dict]:
        """Busca os pares mais recentes na Solana (últimas horas)."""
        url = f"{self.BASE}/dex/search?q=solana"
        try:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as r:
                if r.status == 200:
                    data = await r.json()
                    return data.get("pairs", []) or []
        except Exception as e:
            log.warning(f"DexScreener timeout: {e}")
        return []

    async def get_pair_info(self, session: aiohttp.ClientSession, pair_address: str) -> dict | None:
        """Busca informações detalhadas de um par."""
        url = f"{self.BASE}/dex/pairs/solana/{pair_address}"
        try:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as r:
                if r.status == 200:
                    data = await r.json()
                    pairs = data.get("pairs", [])
                    return pairs[0] if pairs else None
        except Exception as e:
            log.warning(f"Erro ao buscar par {pair_address}: {e}")
        return None


class PumpFunClient:
    """Monitora lançamentos no Pump.fun via API pública."""
    BASE = "https://client-api-2-74b1891ee9f9.herokuapp.com"

    async def get_latest_coins(self, session: aiohttp.ClientSession, limit: int = 50) -> list[dict]:
        """Busca os coins mais recentes no Pump.fun."""
        url = f"{self.BASE}/coins?offset=0&limit={limit}&sort=created_timestamp&order=DESC&includeNsfw=false"
        try:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as r:
                if r.status == 200:
                    return await r.json()
        except Exception as e:
            log.warning(f"Pump.fun timeout: {e}")
        return []


# ============================================================
# Lógica do Scout
# ============================================================

class ScoutAgent:
    """
    Agente SCOUT: Detecta novos tokens com potencial.
    
    Critérios de sinalização:
    1. Liquidez > MIN_LIQUIDITY_USD
    2. Token com < 30 minutos de vida
    3. Volume de transações crescendo (txns.h1 > txns.m5 * 10)
    4. Não foi visto antes (evita re-alertar)
    """

    def __init__(self):
        self.dex = DexScreenerClient()
        self.pump = PumpFunClient()
        self.seen_tokens: set[str] = set()  # Tokens já alertados
        self.alert_callbacks: list = []     # Funções chamadas ao detectar token

    def on_alert(self, callback):
        """Registra callback para quando um token é detectado."""
        self.alert_callbacks.append(callback)
        return callback

    async def _emit_alert(self, token_data: dict):
        """Emite alerta para todos os callbacks registrados."""
        for cb in self.alert_callbacks:
            try:
                if asyncio.iscoroutinefunction(cb):
                    await cb(token_data)
                else:
                    cb(token_data)
            except Exception as e:
                log.error(f"Erro no callback: {e}")

    def _score_token(self, pair: dict) -> tuple[float, list[str]]:
        """
        Pontua um token de 0 a 100 com base em sinais.
        Retorna (score, lista de razões).
        """
        score = 0.0
        reasons = []

        liquidity = pair.get("liquidity", {}).get("usd", 0) or 0
        volume_h1 = pair.get("volume", {}).get("h1", 0) or 0
        volume_h24 = pair.get("volume", {}).get("h24", 0) or 0
        txns_m5 = pair.get("txns", {}).get("m5", {})
        txns_h1 = pair.get("txns", {}).get("h1", {})
        price_change_h1 = pair.get("priceChange", {}).get("h1", 0) or 0
        age_minutes = (time.time() * 1000 - (pair.get("pairCreatedAt", time.time() * 1000))) / 60000

        # Liquidez adequada
        if liquidity >= cfg.MIN_LIQUIDITY_USD:
            score += 20
            reasons.append(f"💧 Liquidez: ${liquidity:,.0f}")

        # Token jovem (< 60 min)
        if age_minutes < 60:
            score += 25
            reasons.append(f"🆕 Token novo: {age_minutes:.0f} min")
        elif age_minutes < 180:
            score += 10

        # Volume crescente no último 1h
        if volume_h1 > 1000:
            score += 15
            reasons.append(f"📈 Volume 1h: ${volume_h1:,.0f}")

        # Txns compradores crescendo mais que vendedores
        buys_m5 = txns_m5.get("buys", 0) or 0
        sells_m5 = txns_m5.get("sells", 0) or 0
        buys_h1 = txns_h1.get("buys", 0) or 0

        if buys_m5 > sells_m5 and buys_m5 > 5:
            score += 20
            reasons.append(f"🟢 Compradores > Vendedores ({buys_m5}x vs {sells_m5}x em 5min)")

        if buys_h1 > 50:
            score += 10
            reasons.append(f"🚀 {buys_h1} compras na última hora")

        # Preço subindo (momentum positivo)
        if 0 < price_change_h1 < 500:  # Subiu, mas não é pump absurdo
            score += 10
            reasons.append(f"📊 +{price_change_h1:.0f}% na hora")

        return score, reasons

    async def scan_dexscreener(self, session: aiohttp.ClientSession):
        """Escaneia novos pares no DexScreener."""
        pairs = await self.dex.get_new_solana_pairs(session)
        log.info(f"DexScreener: {len(pairs)} pares encontrados")

        for pair in pairs:
            token_addr = pair.get("baseToken", {}).get("address", "")
            if not token_addr or token_addr in self.seen_tokens:
                continue

            liquidity = pair.get("liquidity", {}).get("usd", 0) or 0
            if liquidity < cfg.MIN_LIQUIDITY_USD:
                continue

            score, reasons = self._score_token(pair)

            if score >= 30:  # Threshold relaxado para simulação (antes 50)
                self.seen_tokens.add(token_addr)
                token_name = pair.get("baseToken", {}).get("name", "???")
                token_symbol = pair.get("baseToken", {}).get("symbol", "???")

                alert = {
                    "source": "dexscreener",
                    "token_address": token_addr,
                    "token_name": token_name,
                    "token_symbol": token_symbol,
                    "pair_address": pair.get("pairAddress", ""),
                    "dex": pair.get("dexId", "unknown"),
                    "score": score,
                    "reasons": reasons,
                    "liquidity_usd": liquidity,
                    "price_usd": pair.get("priceUsd", "0"),
                    "detected_at": datetime.utcnow().isoformat(),
                    "raw": pair,
                }

                log.info(
                    f"\n{'='*50}\n"
                    f"🎯 ALERTA: {token_name} ({token_symbol})\n"
                    f"   Endereço: {token_addr}\n"
                    f"   Score: {score:.0f}/100\n"
                    f"   " + "\n   ".join(reasons) +
                    f"\n{'='*50}"
                )
                await self._emit_alert(alert)

    async def scan_pumpfun(self, session: aiohttp.ClientSession):
        """Escaneia novos lançamentos no Pump.fun."""
        # A API gratuita do Pump.fun (Heroku) foi desativada pelos desenvolvedores.
        # Estamos dependendo do DexScreener que já indexa moedas do Pump.fun.
        pass
    async def run(self, interval_seconds: int = 15):
        """Loop principal do Scout."""
        log.info(f"🔭 SCOUT iniciado | Intervalo: {interval_seconds}s | DRY_RUN: {cfg.DRY_RUN}")
        
        async with aiohttp.ClientSession() as session:
            while True:
                try:
                    # Escaneia ambas as fontes em paralelo
                    await asyncio.gather(
                        self.scan_dexscreener(session),
                        self.scan_pumpfun(session),
                    )
                except Exception as e:
                    log.error(f"Erro no ciclo de scan: {e}")
                
                await asyncio.sleep(interval_seconds)


# ============================================================
# Entrada principal (pode rodar standalone para testar)
# ============================================================

if __name__ == "__main__":
    validate_config()

    scout = ScoutAgent()

    # Callback de exemplo: só printa
    @scout.on_alert
    async def on_token_found(token: dict):
        print(f"\n📡 TOKEN DETECTADO: {token['token_name']} ({token['token_symbol']})")
        print(f"   Score: {token['score']}/100")
        print(f"   Endereço: {token['token_address']}")
        print(f"   Fonte: {token['source'].upper()}")
        # Em produção, aqui chamaria o RISK Agent para validação

    asyncio.run(scout.run(interval_seconds=15))
