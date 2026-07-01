"""
TV-Screener 整合模組（snapshot 來源）
- 取代 buffett.get_current_prices() 的 Yahoo 逐檔呼叫
- 提供全市場 Buffett 篩選 universe（buffett_full_market.py 用）
- pairs 配對交易仍用 data.py 的 yfinance（需 365 天日線歷史，TV 沒有）
"""
from tradingview_screener import Query, col

try:
    from tradingview_screener import stocks as _tv_stocks
except ImportError:
    _tv_stocks = None


def get_snapshot(tickers: list) -> dict:
    """
    一次拉多檔現價 + 基本面（取代 buffett.get_current_prices）
    回傳 {ticker: price}，與舊 API 相容；失敗時 "_error" 提供診斷
    """
    if not tickers:
        return {}
    try:
        _, df = (
            Query()
            .select('name', 'close')
            .where(col('name').isin(tickers))
            .limit(len(tickers) + 50)
            .get_scanner_data()
        )
    except Exception as e:
        return {"_error": f"TV snapshot failed: {type(e).__name__} {e}"}

    if df is None or df.empty:
        return {"_error": "TV returned empty dataframe"}

    result = {row['name']: round(float(row['close']), 4)
              for _, row in df.iterrows()
              if row.get('close') is not None}

    missing = [t for t in tickers if t not in result]
    if missing and not result:
        return {"_error": f"TV no data for any of {tickers[:5]}..."}
    return result


def get_buffett_snapshot_full_market(
    min_market_cap: float = 2_000_000_000,   # ≥ 20 億美元市值（巴菲特 mid+ cap）
    min_price: float = 5.0,                  # 排除仙股
    require_positive_eps: bool = True,
    limit: int = 8000,
):
    """
    全市場 Buffett snapshot — 一次抓 美股全部 ≥ 1 億市值的標的
    回傳 DataFrame，欄位已對齊 buffett_screener.evaluate() 預期

    ROE / dividend_yield 已 normalize 為小數（與 yfinance 一致）
    """
    fields = [
        'name', 'description', 'close',
        'earnings_per_share_basic_ttm',
        'return_on_equity',                # TV 回 percent (25.0 = 25%)
        'debt_to_equity',                  # 倍數 (1.5 = 150%)
        'dividend_yield_recent',           # TV 回 percent
        'market_cap_basic',
        'sector', 'industry', 'exchange',
        'price_earnings_ttm',
    ]

    base = _tv_stocks('america') if _tv_stocks is not None else Query()
    q = (
        base
        .select(*fields)
        .where(
            col('market_cap_basic') >= min_market_cap,
            col('close') >= min_price,
            col('exchange').isin(['NASDAQ', 'NYSE', 'AMEX']),
            col('typespecs').has('common'),
        )
    )
    if require_positive_eps:
        q = q.where(col('earnings_per_share_basic_ttm') > 0)

    count, df = q.limit(limit).get_scanner_data()

    if df is None or df.empty:
        return count, df

    # client-side safety net：排除 OTC、優先股、NaN 市值
    df = df[df['exchange'].isin(['NASDAQ', 'NYSE', 'AMEX'])]
    df = df[~df['name'].str.contains('/', na=False)]
    df = df[~df['name'].str.contains('\\.', na=False, regex=True)]
    df = df[df['market_cap_basic'].notna() & (df['market_cap_basic'] >= min_market_cap)]

    # 排除衍生品/優先股（依名稱關鍵字；TV 的 typespecs='common' 有時把它們也算進來）
    pref_pattern = (
        r'(?i)(Depositary Shares?|DEP SHS|Preferred|Subordinated|'
        r'Cumulative|Perpetual|Notes Due|Series [A-Z]|Convertible|Trust Preferred|'
        r'1/1,000th|1/20th|Warrant)'
    )
    df = df[~df['description'].fillna('').str.contains(pref_pattern, regex=True, na=False)]

    df = df.rename(columns={
        'description':                   'name_full',
        'earnings_per_share_basic_ttm':  'eps_ttm',
        'return_on_equity':              'roe_current_pct',
        'debt_to_equity':                'debt_to_equity_ratio',
        'dividend_yield_recent':         'dividend_yield_pct',
        'market_cap_basic':              'market_cap',
        'price_earnings_ttm':            'pe_ttm',
        'close':                         'price',
    })

    # Normalize to match yfinance conventions used by buffett_screener.evaluate
    df['roe_current'] = df['roe_current_pct'] / 100.0           # 25.0 → 0.25
    df['dividend_yield'] = df['dividend_yield_pct'] / 100.0     # 2.5 → 0.025
    df['debt_to_equity_pct'] = df['debt_to_equity_ratio'] * 100  # 1.5 → 150 (yfinance 風格)

    df['ticker'] = df['name']
    return count, df
