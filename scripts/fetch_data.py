"""
Market Dashboard Data Fetcher
- Yahoo Finance (yfinance) → KR/US 섹터·주도주 데이터
- Anthropic Claude API → 전문 매매전략 생성
- 결과를 data/market_data.json 에 저장
"""

import os
import sys
import json
import math
import time
import base64
import logging
import requests
from datetime import datetime, timezone, timedelta
from pathlib import Path

import yfinance as yf
import anthropic

# ─────────────────────────────────────────────
#  Logging
# ─────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

# ─────────────────────────────────────────────
#  Config – 환경변수 우선, fallback → config.json
# ─────────────────────────────────────────────
def load_config() -> dict:
    cfg = {
        "anthropic_api_key": os.environ.get("ANTHROPIC_API_KEY", ""),
        "github_token":      os.environ.get("GITHUB_TOKEN", ""),
        "github_owner":      os.environ.get("GITHUB_OWNER", "jinhae8971"),
        "github_repo":       os.environ.get("GITHUB_REPO",  "stock-dashboard"),
    }
    config_path = Path(__file__).parent.parent / "config.json"
    if config_path.exists():
        with open(config_path, encoding="utf-8") as f:
            for k, v in json.load(f).items():
                if not cfg.get(k):
                    cfg[k] = v
    if not cfg["anthropic_api_key"]:
        log.warning("ANTHROPIC_API_KEY 없음 – 전략 생성 스킵")
    return cfg


# ─────────────────────────────────────────────
#  한국 증시 섹터 정의 (대표 종목 기준)
# ─────────────────────────────────────────────
KR_SECTORS: dict[str, list[str]] = {
    "반도체":   ["005930.KS", "000660.KS", "042700.KS", "058470.KS", "240810.KS"],
    "IT/플랫폼": ["035420.KS", "035720.KS", "066570.KS", "251270.KS", "005290.KS"],
    "금융":     ["105560.KS", "055550.KS", "086790.KS", "316140.KS", "138930.KS", "005940.KS"],
    "자동차":   ["005380.KS", "000270.KS", "012330.KS", "011210.KS"],
    "헬스케어": ["068270.KS", "207940.KS", "000100.KS", "012450.KS", "145020.KS"],
    "화학/에너지": ["051910.KS", "096770.KS", "011170.KS", "010950.KS"],
    "철강/소재": ["005490.KS", "004020.KS", "010140.KS", "001430.KS"],
    "통신":     ["017670.KS", "030200.KS", "032640.KS"],
}

# 섹터별 종목명 (yfinance 보완용)
KR_NAMES: dict[str, str] = {
    "005930.KS": "삼성전자",  "000660.KS": "SK하이닉스",
    "042700.KS": "한미반도체", "058470.KS": "리노공업",
    "240810.KS": "원익IPS",   "035420.KS": "NAVER",
    "035720.KS": "카카오",    "066570.KS": "LG전자",
    "251270.KS": "넷마블",    "005290.KS": "동진쎄미켐",
    "105560.KS": "KB금융",    "055550.KS": "신한지주",
    "086790.KS": "하나금융지주","316140.KS":"우리금융지주",
    "138930.KS": "BNK금융지주","005380.KS": "현대차",
    "000270.KS": "기아",      "012330.KS": "현대모비스",
    "011210.KS": "현대위아",  "068270.KS": "셀트리온",
    "207940.KS": "삼성바이오로직스","000100.KS":"유한양행",
    "012450.KS": "한화에어로스페이스","145020.KS":"휴젤",
    "051910.KS": "LG화학",    "096770.KS": "SK이노베이션",
    "011170.KS": "롯데케미칼", "010950.KS": "S-Oil",
    "005940.KS": "NH투자증권", "005490.KS": "POSCO홀딩스",
    "004020.KS": "현대제철",  "010140.KS": "삼성중공업",
    "001430.KS": "세아베스틸", "017670.KS": "SK텔레콤",
    "030200.KS": "KT",        "032640.KS": "LG유플러스",
}

# ─────────────────────────────────────────────
#  미국 증시 섹터 ETF
# ─────────────────────────────────────────────
US_SECTOR_ETFS: dict[str, str] = {
    "기술":        "XLK",
    "금융":        "XLF",
    "에너지":      "XLE",
    "헬스케어":    "XLV",
    "산업재":      "XLI",
    "임의소비재":  "XLY",
    "필수소비재":  "XLP",
    "소재":        "XLB",
    "부동산":      "XLRE",
    "유틸리티":    "XLU",
    "통신서비스":  "XLC",
}

# 섹터별 상위 종목 (주도주 풀)
US_SECTOR_STOCKS: dict[str, list[str]] = {
    "기술":        ["NVDA", "AAPL", "MSFT", "AVGO", "AMD", "ORCL", "CRM"],
    "금융":        ["BRK-B", "JPM", "V", "MA", "GS", "MS", "BAC"],
    "에너지":      ["XOM", "CVX", "COP", "SLB", "EOG", "MPC", "VLO"],
    "헬스케어":    ["LLY", "UNH", "JNJ", "ABBV", "MRK", "TMO", "DHR"],
    "산업재":      ["CAT", "RTX", "HON", "DE", "GE", "UPS", "LMT"],
    "임의소비재":  ["AMZN", "TSLA", "HD", "MCD", "SBUX", "NKE", "BKNG"],
    "필수소비재":  ["WMT", "PG", "KO", "PEP", "COST", "MO", "PM"],
    "소재":        ["LIN", "APD", "SHW", "FCX", "NEM", "VMC"],
    "통신서비스":  ["META", "GOOGL", "NFLX", "T", "VZ", "DIS", "CMCSA"],
    "부동산":      ["AMT", "PLD", "CCI", "EQIX", "SPG"],
    "유틸리티":    ["NEE", "DUK", "SO", "D", "AEP", "EXC"],
}

# 인덱스 티커
INDEX_TICKERS = {
    "kospi":  "^KS11",
    "kosdaq": "^KQ11",
    "sp500":  "^GSPC",
    "nasdaq": "^IXIC",
    "dow":    "^DJI",
    "usdkrw": "KRW=X",
}


# ─────────────────────────────────────────────
#  주도주 복합 스코어링
# ─────────────────────────────────────────────
def calc_score(change_pct: float, price: float,
               volume: int, avg_volume: float) -> float:
    """
    주도주 복합 스코어 = 등락률 × log10(거래대금) × 거래량서프라이즈

    ① 등락률   : 방향성 및 강도 (음수 종목 자동 하위)
    ② log10(거래대금) : 시장 참여 규모 (거래대금 = 가격 × 당일거래량)
    ③ 거래량서프라이즈 : 당일거래량 / 평균거래량 (급등 수급 포착)
    """
    if change_pct <= 0:
        return change_pct  # 하락 종목은 음수 점수 → 자동으로 하위 정렬

    trading_value = price * volume          # 거래대금 (원 or $)
    if trading_value < 1:
        # 거래량·거래대금이 없으면 0점 → TOP 10 경합에서 자동 배제
        # (기존: change_pct를 그대로 반환 → 거래 없는 이상치가 상위 랭크되는 버그)
        return 0.0

    log_value  = math.log10(trading_value)
    vol_surge  = (volume / avg_volume) if avg_volume > 0 else 1.0
    vol_surge  = min(max(vol_surge, 0.1), 10.0)  # 0.1x ~ 10x 캡

    return round(change_pct * log_value * vol_surge, 4)


# ─────────────────────────────────────────────
#  Fetch helpers
# ─────────────────────────────────────────────
def safe_pct_change(ticker_obj) -> float | None:
    """당일 등락률 (%) 계산"""
    try:
        hist = ticker_obj.history(period="2d", interval="1d")
        if len(hist) < 2:
            # 단일 데이터만 있으면 previousClose 활용
            info = ticker_obj.fast_info
            prev = getattr(info, "previous_close", None)
            curr = getattr(info, "last_price", None)
            if prev and curr and prev != 0:
                return round((curr - prev) / prev * 100, 2)
            return None
        prev_close = hist["Close"].iloc[-2]
        last_close = hist["Close"].iloc[-1]
        if prev_close == 0:
            return None
        return round((last_close - prev_close) / prev_close * 100, 2)
    except Exception as e:
        log.debug(f"pct_change error: {e}")
        return None


# 한국 주식 법정 가격제한폭 ±30% / 미국 이상치 임계 ±50%
_CHANGE_LIMITS: dict[str, float] = {"KR": 30.0, "US": 50.0}


def validate_change_pct(chg: float, market: str = "KR",
                        ticker: str = "") -> float | None:
    """
    등락률 이상치 검증 — 가격제한폭 또는 임계값 초과 시 None 반환

    KR: KOSPI·KOSDAQ 법정 가격제한폭 ±30%
        → 초과 시 권리락·액면분할·yfinance 데이터 오류 등 가능성 → 무효화
    US: 대형주 기준 일일 ±50% 초과는 데이터 오류로 간주
    """
    limit = _CHANGE_LIMITS.get(market, 30.0)
    if abs(chg) > limit:
        hint = f" [{ticker}]" if ticker else ""
        log.warning(
            f"⚠ 등락률 이상치 감지{hint}: {chg:+.2f}%  "
            f"→ ±{limit:.0f}% 제한폭 초과, 해당 데이터 무효화"
        )
        return None
    return chg


def fetch_indices() -> dict:
    """주요 지수 데이터 수집"""
    log.info("지수 데이터 수집 중...")
    result = {}
    for key, ticker in INDEX_TICKERS.items():
        try:
            t = yf.Ticker(ticker)
            info = t.fast_info
            last = getattr(info, "last_price", None)
            prev = getattr(info, "previous_close", None)
            chg = None
            if last and prev and prev != 0:
                chg = round((last - prev) / prev * 100, 2)
            result[key] = {"value": round(last, 2) if last else None, "change_pct": chg}
            log.info(f"  {key}: {last:.2f} ({chg:+.2f}%)" if last and chg else f"  {key}: N/A")
            time.sleep(0.2)
        except Exception as e:
            log.warning(f"  {key} 실패: {e}")
            result[key] = {"value": None, "change_pct": None}
    return result


def fetch_kr_data() -> dict:
    """한국 섹터 및 주도주 데이터"""
    log.info("한국 증시 데이터 수집 중...")
    sector_results = []
    all_stocks = []

    for sector_name, tickers in KR_SECTORS.items():
        sector_changes = []
        for ticker in tickers:
            try:
                t = yf.Ticker(ticker)
                info = t.fast_info
                last     = getattr(info, "last_price", None)
                prev     = getattr(info, "previous_close", None)
                vol_day  = getattr(info, "last_volume", None) or 0        # 당일 거래량
                vol_avg  = getattr(info, "three_month_average_volume", None) or 0  # 평균 거래량

                if last and prev and prev != 0:
                    chg = round((last - prev) / prev * 100, 2)

                    # ── 검증: KR 가격제한폭 ±30% 초과 시 이상치 → 스킵 ──
                    chg = validate_change_pct(chg, "KR", ticker)
                    if chg is None:
                        time.sleep(0.15)
                        continue

                    trading_value = last * vol_day
                    vol_surge     = round(vol_day / vol_avg, 2) if vol_avg > 0 else 1.0
                    score         = calc_score(chg, last, vol_day, vol_avg)

                    sector_changes.append(chg)
                    all_stocks.append({
                        "ticker":        ticker,
                        "name":          KR_NAMES.get(ticker, ticker.replace(".KS", "")),
                        "sector":        sector_name,
                        "price":         round(last, 0),
                        "change_pct":    chg,
                        "volume":        int(vol_day),
                        "trading_value": int(trading_value),
                        "vol_surge":     vol_surge,
                        "score":         score,
                    })
                time.sleep(0.15)
            except Exception as e:
                log.debug(f"  KR {ticker} 실패: {e}")

        if sector_changes:
            avg_chg = round(sum(sector_changes) / len(sector_changes), 2)
            sector_results.append({"name": sector_name, "change_pct": avg_chg})
            log.info(f"  {sector_name}: {avg_chg:+.2f}%")

    # 주도주: 거래량 > 0 종목만 대상으로 복합 스코어 상위 10개
    # (거래량 0인 종목은 시장 참여 없는 유령 데이터 → 완전 배제)
    valid_stocks = [s for s in all_stocks if s["volume"] > 0]
    excluded = len(all_stocks) - len(valid_stocks)
    if excluded:
        log.warning(f"  KR 거래량 0 종목 {excluded}개 TOP10 후보에서 제외")
    top_stocks = sorted(valid_stocks, key=lambda x: x["score"], reverse=True)[:10]
    log.info("  [KR 주도주 스코어 TOP5]")
    for s in top_stocks[:5]:
        log.info(f"    {s['name']}: 등락 {s['change_pct']:+.2f}% | "
                 f"거래대금 {s['trading_value']/1e8:.1f}억 | "
                 f"거래량서프라이즈 {s['vol_surge']:.1f}x | 점수 {s['score']:.1f}")

    return {"sectors": sector_results, "top_stocks": top_stocks}


def fetch_us_data() -> dict:
    """미국 섹터 ETF 및 주도주 데이터"""
    log.info("미국 증시 데이터 수집 중...")
    sector_results = []
    all_stocks = []

    # 섹터 ETF 등락률
    for sector_name, etf_ticker in US_SECTOR_ETFS.items():
        try:
            t = yf.Ticker(etf_ticker)
            info = t.fast_info
            last = getattr(info, "last_price", None)
            prev = getattr(info, "previous_close", None)
            if last and prev and prev != 0:
                chg = round((last - prev) / prev * 100, 2)
                sector_results.append({"name": sector_name, "change_pct": chg})
                log.info(f"  {sector_name} ({etf_ticker}): {chg:+.2f}%")
            time.sleep(0.2)
        except Exception as e:
            log.warning(f"  US ETF {etf_ticker} 실패: {e}")

    # 상위 섹터 (등락률 기준 top 5) 종목 수집
    top_sectors = sorted(sector_results, key=lambda x: x["change_pct"], reverse=True)[:5]
    top_sector_names = {s["name"] for s in top_sectors}

    for sector_name, stocks in US_SECTOR_STOCKS.items():
        if sector_name not in top_sector_names:
            continue  # 주도 섹터 외 스킵
        for ticker in stocks[:5]:
            try:
                t = yf.Ticker(ticker)
                info = t.fast_info
                last    = getattr(info, "last_price", None)
                prev    = getattr(info, "previous_close", None)
                vol_day = getattr(info, "last_volume", None) or 0
                vol_avg = getattr(info, "three_month_average_volume", None) or 0

                if last and prev and prev != 0:
                    chg = round((last - prev) / prev * 100, 2)

                    # ── 검증: US 이상치 ±50% 초과 시 → 스킵 ──
                    chg = validate_change_pct(chg, "US", ticker)
                    if chg is None:
                        time.sleep(0.15)
                        continue

                    trading_value = last * vol_day
                    vol_surge     = round(vol_day / vol_avg, 2) if vol_avg > 0 else 1.0
                    score         = calc_score(chg, last, vol_day, vol_avg)
                    try:
                        name = t.info.get("shortName", ticker)
                    except Exception:
                        name = ticker
                    all_stocks.append({
                        "ticker":        ticker,
                        "name":          name[:18],
                        "sector":        sector_name,
                        "price":         round(last, 2),
                        "change_pct":    chg,
                        "volume":        int(vol_day),
                        "trading_value": int(trading_value),
                        "vol_surge":     vol_surge,
                        "score":         score,
                    })
                time.sleep(0.15)
            except Exception as e:
                log.debug(f"  US {ticker} 실패: {e}")

    # 주도주: 거래량 > 0 종목만 대상으로 복합 스코어 상위 10개
    valid_stocks = [s for s in all_stocks if s["volume"] > 0]
    excluded = len(all_stocks) - len(valid_stocks)
    if excluded:
        log.warning(f"  US 거래량 0 종목 {excluded}개 TOP10 후보에서 제외")
    top_stocks = sorted(valid_stocks, key=lambda x: x["score"], reverse=True)[:10]
    log.info("  [US 주도주 스코어 TOP5]")
    for s in top_stocks[:5]:
        log.info(f"    {s['name']}: 등락 {s['change_pct']:+.2f}% | "
                 f"거래대금 ${s['trading_value']/1e9:.2f}B | "
                 f"거래량서프라이즈 {s['vol_surge']:.1f}x | 점수 {s['score']:.1f}")

    return {"sectors": sector_results, "top_stocks": top_stocks}


# ─────────────────────────────────────────────
#  Claude API – 매매전략 생성
# ─────────────────────────────────────────────
def generate_strategy(api_key: str, kr_data: dict, us_data: dict, indices: dict) -> dict:
    """Claude API로 전문 매매전략 생성"""
    if not api_key:
        return {
            "overview":   "API 키 미설정으로 전략 생성 불가. ANTHROPIC_API_KEY Secret을 등록하세요.",
            "action":     "—",
            "risk":       "—",
            "watchlist":  "—",
            "date":       _today_kst(),
        }

    log.info("Claude API 호출 중...")

    # 데이터 요약 구성
    kr_top3  = kr_data.get("sectors", [])[:3]
    us_top3  = us_data.get("sectors", [])[:3]
    kr_lead  = kr_data.get("top_stocks", [])[:5]
    us_lead  = us_data.get("top_stocks", [])[:5]

    def idx_str(key):
        v = indices.get(key, {})
        val = v.get("value")
        chg = v.get("change_pct")
        if val is None: return "N/A"
        return f"{val:,.2f} ({chg:+.2f}%)" if chg is not None else f"{val:,.2f}"

    summary = f"""
[오늘 날짜] {_today_kst()}

[주요 지수]
- KOSPI: {idx_str("kospi")}
- KOSDAQ: {idx_str("kosdaq")}
- S&P 500: {idx_str("sp500")}
- NASDAQ: {idx_str("nasdaq")}
- USD/KRW: {idx_str("usdkrw")}

[한국 주도 섹터 Top3]
{chr(10).join(f"  {s['name']}: {s['change_pct']:+.2f}%" for s in kr_top3)}

[한국 주도주 Top5]
{chr(10).join(f"  {s['name']} ({s['sector']}): {s['change_pct']:+.2f}%  현재가 {s['price']:,.0f}원" for s in kr_lead)}

[미국 주도 섹터 Top3]
{chr(10).join(f"  {s['name']}: {s['change_pct']:+.2f}%" for s in us_top3)}

[미국 주도주 Top5]
{chr(10).join(f"  {s['name']} ({s['sector']}): {s['change_pct']:+.2f}%  ${s['price']:,.2f}" for s in us_lead)}
"""

    prompt = f"""당신은 20년 경력의 전문 퀀트 트레이더입니다. 아래 시장 데이터를 분석하여
오늘의 매매전략을 정확하고 실용적으로 작성하세요.

{summary}

다음 4가지 섹션으로 JSON 형식으로 응답하세요. 각 섹션은 한국어로, 2-3문장 이내로 간결하게 작성:

{{
  "overview": "시장 전반적 분위기와 오늘의 핵심 테마 (강세/약세/혼조, 섹터 로테이션 방향 등)",
  "action": "구체적 매매전략 (롱/숏 포지션, 타이밍, 진입/청산 기준)",
  "risk": "오늘 주목해야 할 리스크 요인과 손절 기준",
  "watchlist": "오늘 집중 관찰할 종목 3-4개와 간략한 이유 (종목명: 이유 형식)"
}}

JSON만 응답하고 다른 텍스트는 포함하지 마세요."""

    try:
        client = anthropic.Anthropic(api_key=api_key)
        msg = client.messages.create(
            model="claude-opus-4-5-20251101",
            max_tokens=1000,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = msg.content[0].text.strip()
        # JSON 파싱
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        result = json.loads(raw)

        # 모든 필드를 문자열로 강제 변환 (Claude가 객체/배열로 반환하는 경우 대비)
        for key in ["overview", "action", "risk", "watchlist"]:
            val = result.get(key, "")
            if isinstance(val, list):
                result[key] = "\n".join(
                    f"{k}: {v}" if isinstance(item, dict) else str(item)
                    for item in val
                    for k, v in (item.items() if isinstance(item, dict) else [(item, "")])
                ) if val and isinstance(val[0], dict) else "\n".join(str(i) for i in val)
            elif isinstance(val, dict):
                result[key] = "\n".join(f"{k}: {v}" for k, v in val.items())
            else:
                result[key] = str(val) if val else "—"

        result["date"] = _today_kst()
        log.info("전략 생성 완료")
        return result
    except json.JSONDecodeError as e:
        log.error(f"JSON 파싱 실패: {e}\n원문: {raw[:200]}")
        return {
            "overview":   "전략 파싱 오류 – Claude 응답 형식 불일치",
            "action":     raw[:300] if "raw" in dir() else "—",
            "risk":       "—",
            "watchlist":  "—",
            "date":       _today_kst(),
        }
    except Exception as e:
        log.error(f"Claude API 오류: {e}")
        return {
            "overview":   f"API 오류: {str(e)[:100]}",
            "action":     "—",
            "risk":       "—",
            "watchlist":  "—",
            "date":       _today_kst(),
        }


# ─────────────────────────────────────────────
#  Utility
# ─────────────────────────────────────────────
def _today_kst() -> str:
    kst = timezone(timedelta(hours=9))
    return datetime.now(kst).strftime("%Y년 %m월 %d일 %H:%M KST")


def save_json(data: dict, path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    log.info(f"로컬 저장: {path} ({path.stat().st_size:,} bytes)")


def upload_to_github(data: dict, token: str, owner: str, repo: str,
                     file_path: str = "data/market_data.json") -> bool:
    """git push 없이 GitHub Contents API로 직접 파일 업로드"""
    if not token:
        log.warning("GITHUB_TOKEN 없음 – GitHub API 업로드 스킵")
        return False

    url = f"https://api.github.com/repos/{owner}/{repo}/contents/{file_path}"
    headers = {
        "Authorization": f"token {token}",
        "Accept":        "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }

    content_str = json.dumps(data, ensure_ascii=False, indent=2)
    encoded     = base64.b64encode(content_str.encode("utf-8")).decode("utf-8")

    # 기존 파일 SHA 조회 (업데이트 시 필수)
    sha = None
    try:
        r = requests.get(url, headers=headers, timeout=15)
        if r.status_code == 200:
            sha = r.json().get("sha")
    except Exception as e:
        log.warning(f"SHA 조회 실패: {e}")

    body = {
        "message": f"chore: update market data {_today_kst()}",
        "content": encoded,
    }
    if sha:
        body["sha"] = sha

    try:
        r = requests.put(url, headers=headers, json=body, timeout=30)
        r.raise_for_status()
        log.info(f"GitHub API 업로드 완료 (HTTP {r.status_code})")
        return True
    except Exception as e:
        log.error(f"GitHub API 업로드 실패: {e}")
        return False


# ─────────────────────────────────────────────
#  Main
# ─────────────────────────────────────────────
def main():
    start = time.time()
    log.info("=" * 50)
    log.info("Market Dashboard Data Fetch 시작")
    log.info("=" * 50)

    cfg = load_config()

    # 1) 지수 수집
    indices = fetch_indices()

    # 2) KR 데이터
    kr_data = fetch_kr_data()

    # 3) US 데이터
    us_data = fetch_us_data()

    # 4) 매매전략 (Claude API)
    strategy = generate_strategy(cfg["anthropic_api_key"], kr_data, us_data, indices)

    # 5) 결과 조합
    output = {
        "updated_at": _today_kst(),
        "indices":    indices,
        "kr":         kr_data,
        "us":         us_data,
        "strategy":   strategy,
    }

    # 6) 로컬 저장 (백업)
    out_path = Path(__file__).parent.parent / "data" / "market_data.json"
    save_json(output, out_path)

    # 7) GitHub Contents API 직접 업로드 (git push 불필요)
    uploaded = upload_to_github(
        data=output,
        token=cfg["github_token"],
        owner=cfg["github_owner"],
        repo=cfg["github_repo"],
    )
    if not uploaded:
        log.info("GitHub API 업로드 스킵 – 로컬 파일만 저장됨")

    elapsed = round(time.time() - start, 1)
    log.info(f"완료! 소요시간: {elapsed}초")


if __name__ == "__main__":
    main()
