#!/usr/bin/env python3
"""Hyperliquid infrastructure layer for the equity-pairs book.

Read paths are pure stdlib + requests, so research and backtests run with no
SDK installed. The write path (order placement) deliberately delegates to the
official `hyperliquid-python-sdk`: L1 action signing is msgpack action-hash +
EIP-712 phantom-agent, and a hand-rolled reimplementation that is subtly wrong
does not fail loudly -- it sends a *valid but different* order. We refuse to
trade rather than guess.

What this module knows that a naive client does not:

  * HIP-3 asset indexing. Builder-deployed perp DEXs (where the equity markets
    live) do NOT continue the core perp index space. Core perps are 0..n, spot
    is 10000+, and builder perps start at 110000 + i*10000 where `i` enumerates
    perpDexs()[1:] -- index 0 is the null/core dex. Getting this wrong points
    an order at an entirely different market.
  * Price rounding. Hyperliquid rejects prices that violate BOTH the 5
    significant-figure rule AND the (6 - szDecimals) decimal-place rule for
    perps. Integer prices are exempt from the sig-fig rule.
  * Per-dex isolation. clearinghouseState, allMids and meta are all per-dex on
    HIP-3; margin does not automatically pool across dexs.

Verified against hyperliquid-python-sdk (info.py / exchange.py / signing.py),
2026-08.
"""
from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional, Tuple

MAINNET = "https://api.hyperliquid.xyz"
TESTNET = "https://api.hyperliquid-testnet.xyz"

# Builder-deployed perp dexs start here; the i-th entry of perpDexs()[1:]
# occupies [BUILDER_BASE + i*DEX_STRIDE, ... + DEX_STRIDE).
BUILDER_BASE = 110_000
DEX_STRIDE = 10_000
SPOT_BASE = 10_000


class HLError(RuntimeError):
    pass


# --------------------------------------------------------------------------
# transport
# --------------------------------------------------------------------------
class Http:
    """Minimal POST-JSON transport with backoff. No third-party dependency."""

    def __init__(self, base_url: str = MAINNET, timeout: float = 20.0, retries: int = 4):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.retries = retries

    def post(self, path: str, body: Dict[str, Any]) -> Any:
        raw = json.dumps(body).encode()
        last: Optional[Exception] = None
        for attempt in range(self.retries):
            req = urllib.request.Request(
                self.base_url + path,
                data=raw,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            try:
                with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                    return json.loads(resp.read().decode())
            except urllib.error.HTTPError as e:
                detail = e.read().decode(errors="replace")[:400]
                # 4xx other than 429 is our bug, not congestion: fail fast.
                if e.code != 429 and 400 <= e.code < 500:
                    raise HLError(f"{path} HTTP {e.code}: {detail}") from e
                last = HLError(f"{path} HTTP {e.code}: {detail}")
            except Exception as e:  # timeout, DNS, reset, egress policy
                last = e
            if attempt < self.retries - 1:
                time.sleep(2 ** attempt)
        raise HLError(f"POST {path} failed after {self.retries} attempts: {last}")


# --------------------------------------------------------------------------
# market metadata
# --------------------------------------------------------------------------
@dataclass
class Market:
    """One perp market, resolved to everything needed to price and size it."""
    name: str               # e.g. "AAPL"
    dex: str                # "" for core perps, else the HIP-3 dex name
    asset: int              # wire asset index
    sz_decimals: int
    max_leverage: int
    only_isolated: bool = False

    @property
    def qualified(self) -> str:
        """Human-readable id that survives a name collision across dexs."""
        return f"{self.dex}:{self.name}" if self.dex else self.name

    # -- rounding ---------------------------------------------------------
    def round_sz(self, sz: float) -> float:
        return round(sz, self.sz_decimals)

    def round_px(self, px: float) -> float:
        """Hyperliquid perp tick rule: <=5 significant figures AND
        <=(6 - szDecimals) decimals. Integers are exempt from the sig-fig
        rule, so we only apply it to non-integer prices."""
        if px <= 0:
            raise ValueError(f"non-positive price {px}")
        max_dec = 6 - self.sz_decimals
        if float(px).is_integer():
            return float(round(px))
        return round(float(f"{px:.5g}"), max_dec)


class Universe:
    """Resolves market names -> wire asset indices across core and HIP-3 dexs.

    `dexs` is the list of perp dexs to load. "" means the core dex. Loading
    only what you trade keeps startup to one request per dex.
    """

    def __init__(self, http: Optional[Http] = None, dexs: Iterable[str] = ("",)):
        self.http = http or Http()
        self._offsets: Dict[str, int] = {"": 0}
        self.markets: Dict[str, Market] = {}   # qualified name -> Market
        self._by_name: Dict[str, List[Market]] = {}
        self.load(dexs)

    # -- discovery --------------------------------------------------------
    def perp_dexs(self) -> List[Optional[Dict[str, Any]]]:
        return self.http.post("/info", {"type": "perpDexs"})

    def _resolve_offsets(self) -> None:
        if len(self._offsets) > 1:
            return
        for i, d in enumerate(self.perp_dexs()[1:]):
            if d:
                self._offsets[d["name"]] = BUILDER_BASE + i * DEX_STRIDE

    def load(self, dexs: Iterable[str]) -> None:
        dexs = list(dexs)
        if any(d for d in dexs):
            self._resolve_offsets()
        for dex in dexs:
            if dex not in self._offsets:
                raise HLError(
                    f"unknown perp dex {dex!r}; available: "
                    f"{sorted(k for k in self._offsets if k)}"
                )
            meta = self.http.post("/info", {"type": "meta", "dex": dex})
            off = self._offsets[dex]
            for idx, a in enumerate(meta["universe"]):
                m = Market(
                    name=a["name"],
                    dex=dex,
                    asset=off + idx,
                    sz_decimals=int(a["szDecimals"]),
                    max_leverage=int(a.get("maxLeverage", 1)),
                    only_isolated=bool(a.get("onlyIsolated", False)),
                )
                self.markets[m.qualified] = m
                self._by_name.setdefault(m.name, []).append(m)

    # -- lookup -----------------------------------------------------------
    def get(self, name: str) -> Market:
        """Accept either "AAPL" or "somedex:AAPL". Bare names that exist on
        more than one loaded dex are an error, not a coin flip."""
        if name in self.markets:
            return self.markets[name]
        hits = self._by_name.get(name, [])
        if len(hits) == 1:
            return hits[0]
        if not hits:
            raise HLError(f"market {name!r} not found in loaded dexs")
        raise HLError(
            f"market {name!r} is ambiguous across dexs "
            f"{[m.dex for m in hits]}; qualify it as dex:NAME"
        )

    def dex_of(self, name: str) -> str:
        return self.get(name).dex


# --------------------------------------------------------------------------
# market data
# --------------------------------------------------------------------------
class MarketData:
    def __init__(self, http: Optional[Http] = None, universe: Optional[Universe] = None):
        self.http = http or Http()
        self.universe = universe

    def all_mids(self, dex: str = "") -> Dict[str, float]:
        raw = self.http.post("/info", {"type": "allMids", "dex": dex})
        return {k: float(v) for k, v in raw.items()}

    def asset_ctxs(self, dex: str = "") -> Dict[str, Dict[str, Any]]:
        """name -> context (markPx, oraclePx, funding, openInterest, ...).

        metaAndAssetCtxs takes a dex like meta does; the two arrays are
        positionally aligned.
        """
        body: Dict[str, Any] = {"type": "metaAndAssetCtxs"}
        if dex:
            body["dex"] = dex
        meta, ctxs = self.http.post("/info", body)
        return {a["name"]: c for a, c in zip(meta["universe"], ctxs)}

    def candles(self, coin: str, interval: str, start_ms: int, end_ms: int) -> List[Dict[str, Any]]:
        """Raw candles. `coin` must be the on-wire coin name.

        The endpoint caps the number of candles returned per call, so we page
        forward on the close time until we stop making progress.
        """
        out: List[Dict[str, Any]] = []
        cursor = start_ms
        while cursor < end_ms:
            batch = self.http.post(
                "/info",
                {"type": "candleSnapshot",
                 "req": {"coin": coin, "interval": interval,
                         "startTime": cursor, "endTime": end_ms}},
            )
            if not batch:
                break
            fresh = [c for c in batch if c["t"] >= cursor]
            if not fresh:
                break
            out.extend(fresh)
            nxt = max(c["t"] for c in fresh) + 1
            if nxt <= cursor:
                break
            cursor = nxt
            if len(batch) < 2:
                break
        # de-dup on open time, keep chronological
        seen: Dict[int, Dict[str, Any]] = {}
        for c in out:
            seen[c["t"]] = c
        return [seen[k] for k in sorted(seen)]

    def closes(self, coin: str, interval: str, start_ms: int, end_ms: int) -> List[Tuple[int, float]]:
        return [(c["t"], float(c["c"])) for c in self.candles(coin, interval, start_ms, end_ms)]

    def funding_history(self, coin: str, start_ms: int, end_ms: Optional[int] = None) -> List[Dict[str, Any]]:
        body: Dict[str, Any] = {"type": "fundingHistory", "coin": coin, "startTime": start_ms}
        if end_ms is not None:
            body["endTime"] = end_ms
        return self.http.post("/info", body)

    def hourly_funding(self, coin: str, start_ms: int, end_ms: Optional[int] = None) -> List[Tuple[int, float]]:
        """(timestamp_ms, hourly funding rate) -- Hyperliquid funding is paid
        hourly, and the rate in fundingHistory is already the hourly rate."""
        return [(int(f["time"]), float(f["fundingRate"]))
                for f in self.funding_history(coin, start_ms, end_ms)]


# --------------------------------------------------------------------------
# account
# --------------------------------------------------------------------------
@dataclass
class Position:
    coin: str
    szi: float          # signed size; negative = short
    entry_px: float
    position_value: float
    unrealized_pnl: float
    margin_used: float
    liquidation_px: Optional[float]
    leverage: float
    is_cross: bool


@dataclass
class AccountState:
    account_value: float
    total_margin_used: float
    total_ntl_pos: float
    withdrawable: float
    positions: Dict[str, Position] = field(default_factory=dict)

    @property
    def free_collateral(self) -> float:
        return self.account_value - self.total_margin_used

    @property
    def margin_ratio(self) -> float:
        """Maintenance headroom proxy: used margin over equity. Rises toward
        1.0 as the account approaches liquidation."""
        if self.account_value <= 0:
            return float("inf")
        return self.total_margin_used / self.account_value

    @property
    def gross_leverage(self) -> float:
        if self.account_value <= 0:
            return float("inf")
        return self.total_ntl_pos / self.account_value


class Account:
    def __init__(self, address: str, http: Optional[Http] = None):
        self.address = address
        self.http = http or Http()

    def state(self, dex: str = "") -> AccountState:
        raw = self.http.post(
            "/info",
            {"type": "clearinghouseState", "user": self.address, "dex": dex},
        )
        ms = raw.get("marginSummary", {})
        st = AccountState(
            account_value=float(ms.get("accountValue", 0) or 0),
            total_margin_used=float(ms.get("totalMarginUsed", 0) or 0),
            total_ntl_pos=float(ms.get("totalNtlPos", 0) or 0),
            withdrawable=float(raw.get("withdrawable", 0) or 0),
        )
        for ap in raw.get("assetPositions", []):
            p = ap["position"]
            lev = p.get("leverage") or {}
            st.positions[p["coin"]] = Position(
                coin=p["coin"],
                szi=float(p["szi"]),
                entry_px=float(p["entryPx"] or 0),
                position_value=float(p.get("positionValue", 0) or 0),
                unrealized_pnl=float(p.get("unrealizedPnl", 0) or 0),
                margin_used=float(p.get("marginUsed", 0) or 0),
                liquidation_px=(float(p["liquidationPx"]) if p.get("liquidationPx") else None),
                leverage=float(lev.get("value", 1) or 1),
                is_cross=(lev.get("type") == "cross"),
            )
        return st


# --------------------------------------------------------------------------
# execution (gated)
# --------------------------------------------------------------------------
@dataclass
class OrderIntent:
    """A resolved, roundable order. Produced by the strategy, consumed by the
    executor. Carries the qualified market so a HIP-3 name collision cannot
    silently retarget it."""
    market: Market
    is_buy: bool
    sz: float
    limit_px: float
    reduce_only: bool = False
    tif: str = "Ioc"
    note: str = ""

    def wire(self) -> Dict[str, Any]:
        return {
            "a": self.market.asset,
            "b": self.is_buy,
            "p": _fmt(self.market.round_px(self.limit_px)),
            "s": _fmt(self.market.round_sz(self.sz)),
            "r": self.reduce_only,
            "t": {"limit": {"tif": self.tif}},
        }

    def describe(self) -> str:
        side = "BUY " if self.is_buy else "SELL"
        ro = " reduce-only" if self.reduce_only else ""
        return (f"{side} {self.market.round_sz(self.sz):g} {self.market.qualified} "
                f"@ {self.market.round_px(self.limit_px):g} [{self.tif}]{ro} "
                f"(asset={self.market.asset}){' ' + self.note if self.note else ''}")


def _fmt(x: float) -> str:
    """Hyperliquid wire float: fixed 8dp, trailing zeros stripped."""
    s = f"{x:.8f}".rstrip("0").rstrip(".")
    return s if s not in ("", "-0") else "0"


def slippage_px(mid: float, is_buy: bool, slippage: float, market: Market) -> float:
    """Aggressive marketable limit price, rounded to a legal tick."""
    px = mid * ((1 + slippage) if is_buy else (1 - slippage))
    return market.round_px(px)


class Executor:
    """Dry-run by default. Live requires BOTH live=True and the env var
    HL_ALLOW_LIVE=1, and a secret key in HL_SECRET_KEY. Two independent
    switches, because one is too easy to flip by accident."""

    LIVE_ENV = "HL_ALLOW_LIVE"
    KEY_ENV = "HL_SECRET_KEY"
    ADDR_ENV = "HL_ACCOUNT_ADDRESS"

    def __init__(self, live: bool = False, base_url: str = MAINNET,
                 account_address: Optional[str] = None):
        self.base_url = base_url
        self.account_address = account_address or os.environ.get(self.ADDR_ENV)
        self.live = bool(live)
        self._exchange = None
        if self.live:
            self._arm()

    def _arm(self) -> None:
        if os.environ.get(self.LIVE_ENV) != "1":
            raise HLError(
                f"live execution requested but {self.LIVE_ENV}!=1 -- refusing. "
                "Set it deliberately to trade real size."
            )
        key = os.environ.get(self.KEY_ENV)
        if not key:
            raise HLError(f"live execution requires {self.KEY_ENV} (API wallet secret key)")
        try:
            from eth_account import Account as EthAccount           # type: ignore
            from hyperliquid.exchange import Exchange               # type: ignore
            from hyperliquid.info import Info                       # type: ignore
        except ImportError as e:
            raise HLError(
                "live execution needs the official SDK: pip install hyperliquid-python-sdk. "
                "We delegate L1 action signing rather than reimplement it."
            ) from e
        wallet = EthAccount.from_key(key)
        info = Info(self.base_url, skip_ws=True)
        self._exchange = Exchange(
            wallet, self.base_url, account_address=self.account_address, info=info
        )

    def send(self, intents: List[OrderIntent]) -> List[Dict[str, Any]]:
        """Submit a batch. A pair leg pair should be sent as ONE batch so both
        legs hit the same block -- legging into a market-neutral spread one
        order at a time is how a neutral book becomes a directional one."""
        if not intents:
            return []
        if not self.live:
            for i in intents:
                print(f"  [DRY-RUN] {i.describe()}")
            return [{"status": "dry-run", "order": i.describe()} for i in intents]
        if self._exchange is None:
            raise HLError("executor not armed")
        reqs = []
        for i in intents:
            reqs.append({
                "coin": i.market.name,
                "is_buy": i.is_buy,
                "sz": i.market.round_sz(i.sz),
                "limit_px": i.market.round_px(i.limit_px),
                "order_type": {"limit": {"tif": i.tif}},
                "reduce_only": i.reduce_only,
            })
        res = self._exchange.bulk_orders(reqs)
        return res if isinstance(res, list) else [res]


def now_ms() -> int:
    return int(time.time() * 1000)


def days_ago_ms(days: float) -> int:
    return now_ms() - int(days * 86_400_000)
