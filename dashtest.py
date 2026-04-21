import csv
import json
import os
import pandas as pd
from pathlib import Path
from dataclasses import dataclass
from datetime import datetime, date, timedelta
import dash
from dash import html, dcc, Output, Input, callback_context
import plotly.graph_objs as go
from yahooquery import Ticker as Ticker
import plotly.express as px

app = dash.Dash(__name__)

@dataclass
class Holding:
    ticker: str
    name: str = ''
    units: int = 0
    total_paid: float = 0
    current_value: float = 0
    weight: float = 0
    issuer: str = None
    daily_change_pct: float = 0
    daily_change_val: float = 0
    total_change_pct: float = 0
    total_change_val: float = 0
    div_pct: float = 0
    div_val: float = 0
    grand_total_pct: float = 0
    grand_total_val: float = 0
    holdings_file: str = None

# ETF data
portfolio = []
# summary_data holds the overall totals across the entire portfolio
summary_data = Holding(ticker="Total...")

# Data directory: set PORTDASH_DATA env var to override, e.g. a samba mount point
DATA_DIR = os.environ.get('PORTDASH_DATA', os.path.dirname(os.path.abspath(__file__))) + os.sep

HISTORY_START = "2024-10-31"
HISTORY_CHUNKS = 10

def get_cache_path():
    return DATA_DIR + 'history_cache.json'

def load_price_cache():
    try:
        with open(DATA_DIR + 'price_cache.json', 'r') as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}

def save_price_cache(prices):
    tmp = DATA_DIR + 'price_cache.json.tmp'
    with open(tmp, 'w') as f:
        json.dump(prices, f)
    os.replace(tmp, DATA_DIR + 'price_cache.json')

def apply_price_cache():
    prices = load_price_cache()
    if not prices:
        return
    for etf in portfolio:
        if etf.ticker not in prices:
            continue
        p = prices[etf.ticker]
        etf.daily_change_pct = p.get('daily_change_pct', 0)
        etf.daily_change_val = p.get('daily_change_val', 0)
        etf.current_value    = p.get('current_value', 0)
        etf.total_change_val = etf.current_value - etf.total_paid
        etf.grand_total_val  = etf.total_change_val + etf.div_val
        if etf.total_paid:
            etf.total_change_pct = etf.total_change_val / etf.total_paid * 100
            etf.div_pct          = etf.div_val / etf.total_paid * 100
            etf.grand_total_pct  = etf.grand_total_val / etf.total_paid * 100
    if summary_data.current_value == 0:
        summary_data.daily_change_val = sum(e.daily_change_val for e in portfolio)
        summary_data.total_change_val = sum(e.total_change_val for e in portfolio)
        summary_data.total_paid       = sum(e.total_paid for e in portfolio)
        summary_data.current_value    = sum(e.current_value for e in portfolio)
        summary_data.div_val          = sum(e.div_val for e in portfolio)
        summary_data.grand_total_val  = summary_data.total_change_val + summary_data.div_val
        if summary_data.current_value:
            for etf in portfolio:
                etf.weight = etf.current_value / summary_data.current_value
            summary_data.daily_change_pct = summary_data.daily_change_val / summary_data.current_value * 100
        if summary_data.total_paid:
            summary_data.div_pct         = summary_data.div_val / summary_data.total_paid * 100
            summary_data.total_change_pct = summary_data.total_change_val / summary_data.total_paid * 100
            summary_data.grand_total_pct  = summary_data.grand_total_val / summary_data.total_paid * 100

def load_history_cache():
    try:
        with open(get_cache_path(), 'r') as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}

def save_history_cache(cache):
    path = get_cache_path()
    tmp_path = path + '.tmp'
    with open(tmp_path, 'w') as f:
        json.dump(cache, f)
    os.replace(tmp_path, path)

def _fetch_and_cache(cache, tickers, start_str, end_str):
    try:
        hist = Ticker(tickers).history(start=start_str, end=end_str, interval='1d')
        if isinstance(hist, str) or hist is None or (hasattr(hist, 'empty') and hist.empty):
            print(f"No history data for {start_str} to {end_str}")
            return
        for (symbol, dt), row in hist.iterrows():
            date_str = str(dt)[:10]
            cache.setdefault(symbol, {})[date_str] = row['close']
    except Exception as e:
        print(f"Error fetching history {start_str}-{end_str}: {e}")

def update_history_cache():
    if not portfolio:
        return
    cache = load_history_cache()
    meta = cache.setdefault('_meta', {'fetch_chunks_done': 0})
    tickers = [etf.ticker for etf in portfolio]

    today = date.today()
    start = date.fromisoformat(HISTORY_START)
    total_days = (today - start).days
    chunk_days = max(1, total_days // HISTORY_CHUNKS)
    chunks_done = meta.get('fetch_chunks_done', 0)

    if chunks_done < HISTORY_CHUNKS:
        chunk_start = start + timedelta(days=chunks_done * chunk_days)
        chunk_end = min(start + timedelta(days=(chunks_done + 1) * chunk_days), today)
        print(f"Fetching history chunk {chunks_done + 1}/{HISTORY_CHUNKS}: {chunk_start} to {chunk_end}")
        _fetch_and_cache(cache, tickers, chunk_start.isoformat(), chunk_end.isoformat())
        meta['fetch_chunks_done'] = chunks_done + 1

    trailing_start = (today - timedelta(days=7)).isoformat()
    print(f"Refreshing trailing week from {trailing_start}")
    _fetch_and_cache(cache, tickers, trailing_start, today.isoformat())

    save_history_cache(cache)

def _normalise_ticker(raw):
    raw = raw.strip()
    if ':' in raw:
        raw = raw.split(':')[1]
    if '.' not in raw:
        raw += '.AX'
    return raw

def _parse_trade_date(s):
    s = s.strip()
    for fmt in ('%Y-%m-%d', '%d/%m/%Y', '%m/%d/%Y'):
        try:
            return datetime.strptime(s[:10], fmt).strftime('%Y-%m-%d')
        except ValueError:
            continue
    raise ValueError(f"Cannot parse date: {s!r}")

def load_purchases():
    path = DATA_DIR + 'purchases.csv'
    trades = []
    try:
        with open(path, 'r', encoding='utf-8', errors='replace') as f:
            reader = csv.DictReader(f)
            for row in reader:
                try:
                    ticker = _normalise_ticker(row['Symbol'])
                    trade_date = _parse_trade_date(row['Closing Time'])
                    qty = float(row['Qty'])
                    side = row['Side'].strip().lower()
                    units = qty if side == 'buy' else -qty
                    raw_total = str(row.get('Total', '') or '').strip().replace(',', '').replace('$', '')
                    total = abs(float(raw_total)) if raw_total else 0.0
                    trades.append({'ticker': ticker, 'date': trade_date, 'units': units, 'total': total})
                except Exception as e:
                    print(f"Skipping trade row {row}: {e}")
    except FileNotFoundError:
        pass
    return trades

def load_dividends():
    dividends = []
    try:
        with open(DATA_DIR + 'dividends.csv', 'r', encoding='utf-8', errors='replace') as f:
            for row in csv.DictReader(f):
                try:
                    dividends.append({
                        'date': _parse_trade_date(row['Date']),
                        'ticker': _normalise_ticker(row.get('Ticker', '')),
                        'amount': float(row['Amount']),
                    })
                except Exception as e:
                    print(f"Skipping dividend row {row}: {e}")
    except FileNotFoundError:
        pass
    return dividends

def make_history_graph():
    cache = load_history_cache()
    tickers = [etf.ticker for etf in portfolio]
    portfolio_tickers = {etf.ticker for etf in portfolio}
    purchases = [t for t in load_purchases() if t['ticker'] in portfolio_tickers]
    dividends = load_dividends()
    use_purchases = bool(purchases)

    all_dates = set()
    for ticker in tickers:
        all_dates.update(cache.get(ticker, {}).keys())

    sorted_dates = sorted(d for d in all_dates if len(d) == 10)  # skip _meta key

    points = []
    for d in sorted_dates:
        total = 0
        skip = False
        for etf in portfolio:
            if use_purchases:
                units = sum(t['units'] for t in purchases if t['ticker'] == etf.ticker and t['date'] <= d)
            else:
                units = etf.units
            if units == 0:
                continue  # not yet purchased, legitimately absent
            if d not in cache.get(etf.ticker, {}):
                skip = True  # price missing for a held ETF — drop this date
                break
            total += units * cache[etf.ticker][d]
        if skip or total == 0:
            continue

        cost_basis = sum(
            (float(t.get('total', 0)) if t['units'] > 0 else -float(t.get('total', 0)))
            for t in purchases if t['date'] <= d
        ) if use_purchases else sum(etf.total_paid for etf in portfolio)

        cumulative_dividends = sum(dv['amount'] for dv in dividends if dv['date'] <= d)

        points.append((d, total, cost_basis, total + cumulative_dividends))

    chunks_done = cache.get('_meta', {}).get('fetch_chunks_done', 0)
    coverage = f" ({chunks_done}/{HISTORY_CHUNKS} history chunks loaded)" if chunks_done < HISTORY_CHUNKS else ""

    if not points:
        fig = go.Figure()
        fig.update_layout(
            plot_bgcolor="#222", paper_bgcolor="#222", font=dict(color="#ccc"),
            title=dict(text=f"Total Portfolio Value Over Time — no data yet, click Refresh{coverage}", font=dict(size=14)),
        )
        return fig

    dates, totals, costs, total_returns = zip(*points)
    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=list(dates), y=list(totals), name="Portfolio Value",
        mode='lines', line=dict(color='#636EFA', width=2),
        hovertemplate='%{x}<br>$%{y:,.0f}<extra>Portfolio Value</extra>',
    ))
    if use_purchases:
        fig.add_trace(go.Scatter(
            x=list(dates), y=list(costs), name="Cost Basis",
            mode='lines', line=dict(color='#888', width=1.5),
            hovertemplate='%{x}<br>$%{y:,.0f}<extra>Cost Basis</extra>',
        ))
    if dividends:
        fig.add_trace(go.Scatter(
            x=list(dates), y=list(total_returns), name="Total Return (inc. dividends)",
            mode='lines', line=dict(color='#00CC96', width=2),
            hovertemplate='%{x}<br>$%{y:,.0f}<extra>Total Return</extra>',
        ))
    fig.update_layout(
        plot_bgcolor="#222", paper_bgcolor="#222", font=dict(color="#ccc"),
        title=dict(text=f"Total Portfolio Value Over Time{coverage}", font=dict(size=20)),
        yaxis=dict(title="Value (AUD)", tickformat="$,.0f", gridcolor="#444"),
        xaxis=dict(title="Date", gridcolor="#444"),
        showlegend=False,
        margin=dict(t=50, l=80, r=20, b=50),
    )
    return fig

def make_profit_graph():
    cache = load_history_cache()
    portfolio_tickers = {etf.ticker for etf in portfolio}
    purchases = [t for t in load_purchases() if t['ticker'] in portfolio_tickers]
    dividends = load_dividends()
    use_purchases = bool(purchases)

    all_dates = set()
    for ticker in portfolio_tickers:
        all_dates.update(cache.get(ticker, {}).keys())

    sorted_dates = sorted(d for d in all_dates if len(d) == 10)

    points = []
    for d in sorted_dates:
        total = 0
        skip = False
        for etf in portfolio:
            if use_purchases:
                units = sum(t['units'] for t in purchases if t['ticker'] == etf.ticker and t['date'] <= d)
            else:
                units = etf.units
            if units == 0:
                continue
            if d not in cache.get(etf.ticker, {}):
                skip = True
                break
            total += units * cache[etf.ticker][d]
        if skip or total == 0:
            continue

        cost_basis = sum(
            t['total'] if t['units'] > 0 else -t['total']
            for t in purchases if t['date'] <= d
        ) if use_purchases else sum(etf.total_paid for etf in portfolio)

        cumulative_dividends = sum(dv['amount'] for dv in dividends if dv['date'] <= d)
        profit = total - cost_basis + cumulative_dividends
        points.append((d, profit))

    chunks_done = cache.get('_meta', {}).get('fetch_chunks_done', 0)
    coverage = f" ({chunks_done}/{HISTORY_CHUNKS} history chunks loaded)" if chunks_done < HISTORY_CHUNKS else ""

    if not points:
        fig = go.Figure()
        fig.update_layout(
            plot_bgcolor="#222", paper_bgcolor="#222", font=dict(color="#ccc"),
            title=dict(text=f"Portfolio Profit Over Time — no data yet, click Refresh{coverage}", font=dict(size=14)),
        )
        return fig

    dates, profits = zip(*points)
    profit_by_date = dict(zip(dates, profits))

    fig = go.Figure(go.Scatter(
        x=list(dates), y=list(profits),
        mode='lines', line=dict(color='#00CC96', width=2),
        fill='tozeroy',
        fillcolor='rgba(0,204,150,0.15)',
        hovertemplate='%{x}<br>$%{y:,.0f}<extra>Profit</extra>',
    ))

    # Group purchases by date for investment markers
    if use_purchases:
        buys_by_date = {}
        for t in purchases:
            if t['units'] > 0:
                buys_by_date.setdefault(t['date'], []).append(
                    f"{t['ticker'].split('.')[0]}: ${t['total']:,.0f}"
                )
        marker_dates, marker_profits, marker_labels = [], [], []
        for d, labels in sorted(buys_by_date.items()):
            if d in profit_by_date:
                marker_dates.append(d)
                marker_profits.append(profit_by_date[d])
                marker_labels.append('<br>'.join(labels))
        if marker_dates:
            fig.add_trace(go.Scatter(
                x=marker_dates, y=marker_profits,
                mode='markers',
                marker=dict(color='yellow', size=8, symbol='circle',
                            line=dict(color='#333', width=1)),
                hovertemplate='%{x}<br>%{customdata}<extra>Investment</extra>',
                customdata=marker_labels,
            ))

    fig.add_hline(y=0, line=dict(color='#555', width=1))
    fig.update_layout(
        plot_bgcolor="#222", paper_bgcolor="#222", font=dict(color="#ccc"),
        title=dict(text=f"Portfolio Profit Over Time{coverage}", font=dict(size=20)),
        yaxis=dict(title="Profit (AUD)", tickformat="$,.0f", gridcolor="#444"),
        xaxis=dict(title="Date", gridcolor="#444"),
        showlegend=False,
        margin=dict(t=50, l=80, r=20, b=50),
    )
    return fig

def make_etf_returns_graph():
    cache = load_history_cache()
    portfolio_tickers = {etf.ticker for etf in portfolio}
    all_purchases = [t for t in load_purchases() if t['ticker'] in portfolio_tickers]
    use_purchases = bool(all_purchases)
    palette = ['#636EFA', '#EF553B', '#00CC96', '#FECB52', '#AB63FA', '#FFA15A']

    all_dates = set()
    for ticker in portfolio_tickers:
        all_dates.update(cache.get(ticker, {}).keys())
    sorted_dates = sorted(d for d in all_dates if len(d) == 10)

    chunks_done = cache.get('_meta', {}).get('fetch_chunks_done', 0)
    coverage = f" ({chunks_done}/{HISTORY_CHUNKS} history chunks loaded)" if chunks_done < HISTORY_CHUNKS else ""

    fig = go.Figure()
    for i, etf in enumerate(portfolio):
        etf_purchases = [t for t in all_purchases if t['ticker'] == etf.ticker]
        points = []
        for d in sorted_dates:
            if use_purchases:
                units = sum(t['units'] for t in etf_purchases if t['date'] <= d)
                cost_basis = sum(
                    t['total'] if t['units'] > 0 else -t['total']
                    for t in etf_purchases if t['date'] <= d
                )
            else:
                units = etf.units
                cost_basis = etf.total_paid
            if units == 0 or cost_basis == 0:
                continue
            if d not in cache.get(etf.ticker, {}):
                continue
            value = units * cache[etf.ticker][d]
            points.append((d, (value - cost_basis) / cost_basis * 100))

        if points:
            dates, returns = zip(*points)
            label = etf.ticker.split('.')[0]
            fig.add_trace(go.Scatter(
                x=list(dates), y=list(returns),
                mode='lines', name=label,
                line=dict(color=palette[i % len(palette)], width=2),
                hovertemplate='%{x}<br>%{y:.2f}%<extra>' + label + '</extra>',
            ))

    fig.add_hline(y=0, line=dict(color='#555', width=1))
    fig.update_layout(
        plot_bgcolor="#222", paper_bgcolor="#222", font=dict(color="#ccc"),
        title=dict(text=f"Cumulative Return by ETF{coverage}", font=dict(size=20)),
        yaxis=dict(title="Return (%)", gridcolor="#444", ticksuffix="%"),
        xaxis=dict(title="Date", gridcolor="#444"),
        legend=dict(bgcolor="#333", bordercolor="#555", borderwidth=1),
        margin=dict(t=50, l=80, r=20, b=50),
    )
    return fig

def make_cumulative_dividends_graph():
    portfolio_tickers = {etf.ticker for etf in portfolio}
    dividends = sorted(
        [d for d in load_dividends() if d['ticker'] in portfolio_tickers],
        key=lambda d: d['date']
    )
    if not dividends:
        fig = go.Figure()
        fig.update_layout(
            plot_bgcolor="#222", paper_bgcolor="#222", font=dict(color="#ccc"),
            title=dict(text="Cumulative Dividends — no data found", font=dict(size=14)),
        )
        return fig

    palette = ['#636EFA', '#EF553B', '#00CC96', '#FECB52', '#AB63FA', '#FFA15A']
    tickers = sorted({d['ticker'] for d in dividends})
    all_dates = sorted({d['date'] for d in dividends})

    fig = go.Figure()
    running_total = []
    portfolio_cumulative = 0

    for i, ticker in enumerate(tickers):
        label = ticker.split('.')[0]
        cumulative = 0
        dates, amounts = [], []
        for d in all_dates:
            payment = sum(dv['amount'] for dv in dividends if dv['ticker'] == ticker and dv['date'] == d)
            if payment:
                cumulative += payment
                dates.append(d)
                amounts.append(cumulative)
        if dates:
            fig.add_trace(go.Scatter(
                x=dates, y=amounts, name=label,
                mode='lines+markers', line=dict(color=palette[i % len(palette)], width=2, shape='hv'),
                marker=dict(size=6),
                hovertemplate='%{x}<br>$%{y:,.2f}<extra>' + label + '</extra>',
            ))

    # Portfolio total line
    cumulative = 0
    dates, amounts = [], []
    for d in all_dates:
        payment = sum(dv['amount'] for dv in dividends if dv['date'] == d)
        if payment:
            cumulative += payment
            dates.append(d)
            amounts.append(cumulative)
    fig.add_trace(go.Scatter(
        x=dates, y=amounts, name="Total",
        mode='lines+markers', line=dict(color='white', width=2, dash='dot', shape='hv'),
        marker=dict(size=6),
        hovertemplate='%{x}<br>$%{y:,.2f}<extra>Total</extra>',
    ))

    fig.update_layout(
        plot_bgcolor="#222", paper_bgcolor="#222", font=dict(color="#ccc"),
        title=dict(text="Cumulative Dividends Received", font=dict(size=20)),
        yaxis=dict(title="Cumulative Amount (AUD)", tickformat="$,.0f", gridcolor="#444"),
        xaxis=dict(title="Date", gridcolor="#444"),
        legend=dict(bgcolor="#333", bordercolor="#555", borderwidth=1),
        margin=dict(t=50, l=80, r=20, b=50),
    )
    return fig

def make_avg_cost_graph():
    portfolio_tickers = {etf.ticker for etf in portfolio}
    all_purchases = sorted(
        [t for t in load_purchases() if t['ticker'] in portfolio_tickers],
        key=lambda t: t['date']
    )
    if not all_purchases:
        fig = go.Figure()
        fig.update_layout(
            plot_bgcolor="#222", paper_bgcolor="#222", font=dict(color="#ccc"),
            title=dict(text="Average Cost Per Unit — no purchases data found", font=dict(size=14)),
        )
        return fig

    palette = ['#636EFA', '#EF553B', '#00CC96', '#FECB52', '#AB63FA', '#FFA15A']
    tickers = sorted({t['ticker'] for t in all_purchases})

    fig = go.Figure()
    for i, ticker in enumerate(tickers):
        label = ticker.split('.')[0]
        cumulative_units = 0
        cumulative_cost = 0
        dates, avg_costs = [], []
        for t in [p for p in all_purchases if p['ticker'] == ticker]:
            cumulative_units += t['units']
            cumulative_cost += t['total'] if t['units'] > 0 else -t['total']
            if cumulative_units > 0:
                dates.append(t['date'])
                avg_costs.append(cumulative_cost / cumulative_units)
        if dates:
            fig.add_trace(go.Scatter(
                x=dates, y=avg_costs, name=label,
                mode='lines+markers', line=dict(color=palette[i % len(palette)], width=2, shape='hv'),
                marker=dict(size=6),
                hovertemplate='%{x}<br>$%{y:,.4f}<extra>' + label + '</extra>',
            ))

    fig.update_layout(
        plot_bgcolor="#222", paper_bgcolor="#222", font=dict(color="#ccc"),
        title=dict(text="Average Cost Per Unit by ETF", font=dict(size=20)),
        yaxis=dict(title="Avg Cost Per Unit (AUD)", tickformat="$,.2f", gridcolor="#444"),
        xaxis=dict(title="Date", gridcolor="#444"),
        legend=dict(bgcolor="#333", bordercolor="#555", borderwidth=1),
        margin=dict(t=50, l=80, r=20, b=50),
    )
    return fig

def make_avg_cost_normalised_graph():
    portfolio_tickers = {etf.ticker for etf in portfolio}
    all_purchases = sorted(
        [t for t in load_purchases() if t['ticker'] in portfolio_tickers],
        key=lambda t: t['date']
    )
    if not all_purchases:
        fig = go.Figure()
        fig.update_layout(
            plot_bgcolor="#222", paper_bgcolor="#222", font=dict(color="#ccc"),
            title=dict(text="Normalised Average Cost — no purchases data found", font=dict(size=14)),
        )
        return fig

    palette = ['#636EFA', '#EF553B', '#00CC96', '#FECB52', '#AB63FA', '#FFA15A']
    tickers = sorted({t['ticker'] for t in all_purchases})

    fig = go.Figure()
    for i, ticker in enumerate(tickers):
        label = ticker.split('.')[0]
        cumulative_units = 0
        cumulative_cost = 0
        baseline = None
        dates, normalised = [], []
        for t in [p for p in all_purchases if p['ticker'] == ticker]:
            cumulative_units += t['units']
            cumulative_cost += t['total'] if t['units'] > 0 else -t['total']
            if cumulative_units > 0:
                avg = cumulative_cost / cumulative_units
                if baseline is None:
                    baseline = avg
                dates.append(t['date'])
                normalised.append(avg / baseline * 100)
        if dates:
            fig.add_trace(go.Scatter(
                x=dates, y=normalised, name=label,
                mode='lines+markers', line=dict(color=palette[i % len(palette)], width=2, shape='hv'),
                marker=dict(size=6),
                hovertemplate='%{x}<br>%{y:.2f}%<extra>' + label + '</extra>',
            ))

    fig.add_hline(y=100, line=dict(color='#555', width=1, dash='dash'))
    fig.update_layout(
        plot_bgcolor="#222", paper_bgcolor="#222", font=dict(color="#ccc"),
        title=dict(text="Average Cost Per Unit — Normalised to First Purchase", font=dict(size=20)),
        yaxis=dict(title="Avg Cost (% of first purchase)", ticksuffix="%", gridcolor="#444"),
        xaxis=dict(title="Date", gridcolor="#444"),
        legend=dict(bgcolor="#333", bordercolor="#555", borderwidth=1),
        margin=dict(t=50, l=80, r=20, b=50),
    )
    return fig

def make_correlation_heatmap():
    cache = load_history_cache()
    tickers = [etf.ticker for etf in portfolio]
    labels = [t.split('.')[0] for t in tickers]

    # Build price series per ETF
    price_data = {}
    for ticker in tickers:
        prices = cache.get(ticker, {})
        price_data[ticker] = {d: v for d, v in prices.items() if len(d) == 10}

    # Find dates common to all ETFs
    common_dates = sorted(
        set.intersection(*[set(price_data[t].keys()) for t in tickers])
    )

    if len(common_dates) < 10:
        fig = go.Figure()
        fig.update_layout(
            plot_bgcolor="#222", paper_bgcolor="#222", font=dict(color="#ccc"),
            title=dict(text="Correlation — insufficient overlapping data, click Refresh", font=dict(size=14)),
        )
        return fig

    # Compute daily returns and correlation matrix
    df = pd.DataFrame(
        {ticker: [price_data[ticker][d] for d in common_dates] for ticker in tickers},
        index=common_dates
    )
    corr = df.pct_change().dropna().corr()
    corr.index = labels
    corr.columns = labels

    z = corr.values.tolist()

    annotations = []
    for i, row_label in enumerate(labels):
        for j, col_label in enumerate(labels):
            val = z[i][j]
            text_color = 'white' if abs(val) > 0.6 else 'black'
            annotations.append(dict(
                x=col_label, y=row_label,
                text=f"{val:.2f}",
                font=dict(color=text_color, size=13),
                showarrow=False,
            ))

    fig = go.Figure(go.Heatmap(
        z=z, x=labels, y=labels,
        colorscale='RdYlGn', zmin=-1, zmax=1,
        hovertemplate='%{y} / %{x}<br>Correlation: %{z:.2f}<extra></extra>',
    ))
    fig.update_layout(
        plot_bgcolor="#222", paper_bgcolor="#222", font=dict(color="#ccc"),
        title=dict(text="ETF Return Correlation", font=dict(size=20)),
        margin=dict(t=50, l=80, r=20, b=50),
        xaxis=dict(side="bottom"),
        annotations=annotations,
    )
    return fig

def make_drawdown_graph():
    cache = load_history_cache()
    portfolio_tickers = {etf.ticker for etf in portfolio}
    purchases = [t for t in load_purchases() if t['ticker'] in portfolio_tickers]
    use_purchases = bool(purchases)

    all_dates = set()
    for ticker in portfolio_tickers:
        all_dates.update(cache.get(ticker, {}).keys())

    sorted_dates = sorted(d for d in all_dates if len(d) == 10)

    points = []
    for d in sorted_dates:
        total = 0
        skip = False
        for etf in portfolio:
            units = sum(t['units'] for t in purchases if t['ticker'] == etf.ticker and t['date'] <= d) if use_purchases else etf.units
            if units == 0:
                continue
            if d not in cache.get(etf.ticker, {}):
                skip = True
                break
            total += units * cache[etf.ticker][d]
        if not skip and total > 0:
            points.append((d, total))

    chunks_done = cache.get('_meta', {}).get('fetch_chunks_done', 0)
    coverage = f" ({chunks_done}/{HISTORY_CHUNKS} history chunks loaded)" if chunks_done < HISTORY_CHUNKS else ""

    if not points:
        fig = go.Figure()
        fig.update_layout(
            plot_bgcolor="#222", paper_bgcolor="#222", font=dict(color="#ccc"),
            title=dict(text=f"Drawdown — no data yet, click Refresh{coverage}", font=dict(size=14)),
        )
        return fig

    dates, values = zip(*points)
    peak = 0
    drawdowns = []
    for v in values:
        peak = max(peak, v)
        drawdowns.append((v - peak) / peak * 100)

    fig = go.Figure(go.Scatter(
        x=list(dates), y=drawdowns,
        mode='lines', line=dict(color='#EF553B', width=2),
        fill='tozeroy', fillcolor='rgba(239,85,59,0.15)',
        hovertemplate='%{x}<br>%{y:.2f}%<extra>Drawdown</extra>',
    ))
    fig.add_hline(y=0, line=dict(color='#555', width=1))
    fig.update_layout(
        plot_bgcolor="#222", paper_bgcolor="#222", font=dict(color="#ccc"),
        title=dict(text=f"Portfolio Drawdown From Peak{coverage}", font=dict(size=20)),
        yaxis=dict(title="Drawdown (%)", gridcolor="#444", ticksuffix="%"),
        xaxis=dict(title="Date", gridcolor="#444"),
        showlegend=False,
        margin=dict(t=50, l=80, r=20, b=50),
    )
    return fig

def make_dividend_efficiency_graph():
    total_divs = summary_data.div_val
    total_value = summary_data.current_value
    if total_divs == 0 or total_value == 0:
        fig = go.Figure()
        fig.update_layout(
            plot_bgcolor="#222", paper_bgcolor="#222", font=dict(color="#ccc"),
            title=dict(text="Dividend Efficiency — no data", font=dict(size=14)),
        )
        return fig

    ratios = {}
    for etf in portfolio:
        div_contribution_pct = etf.div_val / total_divs * 100
        weight_pct = etf.current_value / total_value * 100
        if weight_pct == 0:
            continue
        ratios[etf.name] = div_contribution_pct / weight_pct

    ratios = sorted(ratios.items(), key=lambda x: x[1], reverse=True)
    etfs = [x[0].split('.')[0] + '  ' for x in ratios]
    vals = [x[1] for x in ratios]
    colours = ['#00CC96' if v >= 1 else '#EF553B' for v in vals]

    fig = go.Figure(go.Bar(
        x=vals, y=etfs, orientation='h',
        marker=dict(color=colours),
        hovertemplate='%{y}<br>Ratio: %{x:.2f}<extra></extra>',
    ))
    fig.add_vline(x=1.0, line=dict(color='#888', width=1, dash='dash'))
    fig.update_layout(
        plot_bgcolor="#222", paper_bgcolor="#222", font=dict(color="#ccc"),
        title=dict(text="Dividend Efficiency by ETF", font=dict(size=20)),
        xaxis=dict(title="Dividend Contribution / Portfolio Weight", gridcolor="#444"),
        margin=dict(t=50, l=100, r=20, b=50),
        yaxis=dict(autorange='reversed', ticklabelposition="outside", ticklen=10, automargin=True),
    )
    return fig

def make_dividends_bar_graph():
    portfolio_tickers = {etf.ticker for etf in portfolio}
    dividends = [d for d in load_dividends() if d['ticker'] in portfolio_tickers]
    if not dividends:
        fig = go.Figure()
        fig.update_layout(
            plot_bgcolor="#222", paper_bgcolor="#222", font=dict(color="#ccc"),
            title=dict(text="Dividend Payments — no data found", font=dict(size=14)),
        )
        return fig

    # Group by ticker so each gets its own coloured bar series
    tickers = sorted({d['ticker'] for d in dividends})
    all_dates = sorted({d['date'] for d in dividends})
    palette = ['#636EFA', '#EF553B', '#00CC96', '#FECB52', '#AB63FA', '#FFA15A']
    ticker_colours = {t: palette[i % len(palette)] for i, t in enumerate(tickers)}

    fig = go.Figure()
    for ticker in tickers:
        label = ticker.split('.')[0]
        amounts = []
        for d in all_dates:
            total = sum(dv['amount'] for dv in dividends if dv['ticker'] == ticker and dv['date'] == d)
            amounts.append(total if total else None)
        fig.add_trace(go.Bar(
            x=all_dates, y=amounts, name=label,
            marker_color=ticker_colours[ticker],
            hovertemplate='%{x}<br>$%{y:,.2f}<extra>' + label + '</extra>',
        ))

    fig.update_layout(
        plot_bgcolor="#222", paper_bgcolor="#222", font=dict(color="#ccc"),
        title=dict(text="Dividend Payments Over Time", font=dict(size=20)),
        barmode='stack',
        yaxis=dict(title="Amount (AUD)", tickformat="$,.0f", gridcolor="#444"),
        xaxis=dict(title="Date", gridcolor="#444"),
        legend=dict(bgcolor="#333", bordercolor="#555", borderwidth=1),
        margin=dict(t=50, l=80, r=20, b=50),
    )
    return fig

def load_portfolio():
    global portfolio
    portfolio = []

    # Load static config: ticker → issuer + holdings file
    config = {}
    try:
        with open(DATA_DIR + 'etf_config.csv', 'r', encoding='utf-8', errors='replace') as f:
            for row in csv.DictReader(f):
                config[row['Ticker'].strip()] = {
                    'issuer': row['Issuer'].strip(),
                    'holdings_file': row['HoldingsFile'].strip(),
                }
    except FileNotFoundError:
        print("etf_config.csv not found")
        return

    # Derive units and cost basis from purchases
    units_by_ticker = {t: 0.0 for t in config}
    paid_by_ticker  = {t: 0.0 for t in config}
    for trade in load_purchases():
        t = trade['ticker']
        if t not in config:
            continue
        units_by_ticker[t] += trade['units']
        paid_by_ticker[t]  += trade['total'] if trade['units'] > 0 else -trade['total']

    # Derive dividends from dividends.csv
    div_by_ticker = {t: 0.0 for t in config}
    for div in load_dividends():
        t = div['ticker']
        if t in config:
            div_by_ticker[t] += div['amount']

    for ticker, cfg in config.items():
        portfolio.append(Holding(
            ticker=ticker,
            name=ticker,
            units=int(round(units_by_ticker[ticker])),
            total_paid=paid_by_ticker[ticker],
            div_val=div_by_ticker[ticker],
            issuer=cfg['issuer'],
            holdings_file=cfg['holdings_file'],
        ))

def format_change(pct, val):
    sign = "▲" if val > 0 else "▼" if val < 0 else ""
    color = "springgreen" if val > 0 else "tomato" if val < 0 else "white"
    symbol = '+' if val > 0 else '-' if val < 0 else ''
    val = abs(val)
    text = f"{sign}{pct:.2f}% ({symbol}${val:,.2f})"
    return html.Span(text, style={"color": color})

def generate_etf_header():
    return html.Div(
        className="etf-row",
        children=[
            html.Div("Ticker", style={"fontWeight": "bold"}),
            html.Div("Daily CG", style={"fontWeight": "bold"}),
            html.Div("All Time CG", style={"fontWeight": "bold"}),
            html.Div("Dividends", style={"fontWeight": "bold"}),
            html.Div("Total", style={"fontWeight": "bold"})
        ],
    )

def generate_etf_row(etf):
    return html.Div(
        className="etf-row",
        children=[
            html.Div(etf.ticker.split('.')[0] + ':', className="etf-name"),
            html.Div(format_change(etf.daily_change_pct, etf.daily_change_val), className="etf-dailycg"),
            html.Div(format_change(etf.total_change_pct, etf.total_change_val), className="etf-totalcg"),
            html.Div(format_change(etf.div_pct, etf.div_val), className="etf-div"),
            html.Div(format_change(etf.grand_total_pct, etf.grand_total_val), className="etf-grandtotal"),
        ],
    )

app.layout = html.Div(
    className='main-body',
    children=[
        dcc.Interval(id="startup-trigger", interval=100, n_intervals=0, max_intervals=1),
        dcc.Interval(id="yahoo-refresh", interval=2500, n_intervals=0, max_intervals=1),
        html.Div(
            style={"display": "flex"},
            children=[
                # Left column with ETF boxes
                html.Div(
                    id="etf-container",
                    className="etf-container",
                    children=[
                        generate_etf_row(etf) for etf in portfolio] + [generate_etf_row(summary_data)]
                ),

                # Right column
                html.Div(
                    style={"flex": "1"},
                    children=[
                        dcc.Dropdown(
                            id="graph-selector",
                            placeholder="Select a graph type...",
                            options=[
                                {"label": "Daily % Impact by ETF", "value": "daily-impact"},
                                {"label": "Total % Impact by ETF", "value": "total-impact"},
                                {"label": "Total Holdings by Weight", "value": "weights"},
                                {"label": "Top Individual Holdings", "value": "top-holdings"},
                                {"label": "Top Individual Countries", "value": "top-countries"},
                                {"label": "Top Individual Sectors", "value": "top-sectors"},
                                {"label": "ETF Comparative Efficiency", "value": "efficiency"},
                                {"label": "Total Value Over Time", "value": "history"},
                                {"label": "Profit Over Time", "value": "profit"},
                                {"label": "Dividend Payments", "value": "dividends-bar"},
                                {"label": "Dividend Efficiency by ETF", "value": "dividends-efficiency"},
                                {"label": "Drawdown From Peak", "value": "drawdown"},
                                {"label": "Cumulative Return by ETF", "value": "etf-returns"},
                                {"label": "Cumulative Dividends", "value": "cumulative-dividends"},
                                {"label": "Average Cost Per Unit", "value": "avg-cost"},
                                {"label": "Average Cost Per Unit (Normalised)", "value": "avg-cost-norm"},
                                {"label": "ETF Return Correlation", "value": "correlation"},
                                
                            ],
                            value="daily-impact",
                            clearable=False,
                            style={"backgroundColor": "#222", "color": "#ccc", "marginBottom": "1rem"},
                        ),
                        #dcc.Graph(id="etf-graph", style={"backgroundColor": "#222", "color": "#ccc"})
                        dcc.Loading(children=[html.Div(id="graph-container")], type="circle"),
                        #dcc.Interval(id="startup-trigger", interval=100, n_intervals=0, max_intervals=1),
                    ],
                ),
            ],
        ),
        html.Div(
            [
                html.Button("Refresh", id="refresh-button", style={"padding": "0.5rem 1rem", "fontSize": "1rem"}),
                html.Div(id="status-line", style={"color": "#ccc", "alignSelf": "center"})
            ],
            style={"display": "flex", "alignItems": "center", "gap": "1rem", "marginBottom": "1rem"}
        )
    ],
)

def fetch_etf_data():
    print('Updating ETF data.')
    curr_prices = get_yahoo_data([etf.ticker for etf in portfolio])

    for etf in portfolio:
        if etf.ticker not in curr_prices:
            print(f"Warning: no price data for {etf.ticker}, skipping")
            continue
        price_data = curr_prices[etf.ticker]
        price = price_data.get('price') or 0
        yesterday_price = price_data.get('yesterday_price') or 0
        etf.daily_change_pct = (price_data.get('daily_change_pct') or 0) * 100
        etf.daily_change_val = etf.units * (price - yesterday_price)
        etf.current_value = price * etf.units
        etf.total_change_val = etf.current_value - etf.total_paid
        etf.grand_total_val = etf.total_change_val + etf.div_val
        if etf.total_paid != 0:
            etf.total_change_pct = etf.total_change_val / etf.total_paid * 100
            etf.div_pct = etf.div_val / etf.total_paid * 100
            etf.grand_total_pct = (etf.current_value + etf.div_val - etf.total_paid) / etf.total_paid * 100

    summary_data.daily_change_val = sum(etf.daily_change_val for etf in portfolio)
    summary_data.total_change_val = sum(etf.total_change_val for etf in portfolio)
    summary_data.total_paid = sum(etf.total_paid for etf in portfolio)
    summary_data.current_value = sum(etf.current_value for etf in portfolio)
    summary_data.div_val = sum(etf.div_val for etf in portfolio)
    summary_data.grand_total_val = summary_data.total_change_val + summary_data.div_val

    if summary_data.current_value != 0:
        for etf in portfolio:
            etf.weight = etf.current_value / summary_data.current_value
        summary_data.daily_change_pct = (summary_data.daily_change_val / summary_data.current_value) * 100

    if summary_data.total_paid != 0:
        summary_data.div_pct = summary_data.div_val / summary_data.total_paid * 100
        summary_data.total_change_pct = (summary_data.total_change_val / summary_data.total_paid) * 100
        summary_data.grand_total_pct = (summary_data.grand_total_val / summary_data.total_paid) * 100

    save_price_cache({
        etf.ticker: {
            'daily_change_pct': etf.daily_change_pct,
            'daily_change_val': etf.daily_change_val,
            'current_value':    etf.current_value,
        }
        for etf in portfolio
    })

@app.callback(
    Output("status-line", "children"),
    Output("etf-container", "children"),
    Output("graph-container", "children"),
    Input("refresh-button", "n_clicks"),
    Input("startup-trigger", "n_intervals"),
    Input("yahoo-refresh", "n_intervals"),
    Input("graph-selector", "value"),
)
def handle_all(n_clicks, n_startup, n_yahoo, graph_mode):
    triggered = dash.callback_context.triggered_id
    print(f"Triggered by: {triggered}")

    status = dash.no_update
    container = dash.no_update
    graph = dash.no_update

    if triggered == "startup-trigger":
        load_portfolio()
        apply_price_cache()
        status = "Loading live prices…"
        container = [generate_etf_header()] + [generate_etf_row(etf) for etf in portfolio] + [generate_etf_row(summary_data)]

    elif triggered in ["refresh-button", "yahoo-refresh"]:
        load_portfolio()
        fetch_etf_data()
        update_history_cache()
        status = f"Last refreshed at {datetime.now().strftime('%I:%M:%S %p').lstrip('0')}"
        container = [generate_etf_header()] + [generate_etf_row(etf) for etf in portfolio] + [generate_etf_row(summary_data)]

    if triggered in ["refresh-button", "startup-trigger", "yahoo-refresh", "graph-selector"]:
        if graph_mode == "daily-impact":
            graph = dcc.Graph(figure=make_impact_graph())
        elif graph_mode == "total-impact":
            graph = dcc.Graph(figure=make_impact_graph('total'))
        elif graph_mode == "weights":
            graph = dcc.Graph(figure=make_weights_treemap())
        elif graph_mode == "top-holdings":
            graph = dcc.Graph(figure=make_top_holdings_graph())
        elif graph_mode == "top-countries":
            graph = dcc.Graph(figure=make_top_countries_graph())
        elif graph_mode == "top-sectors":
            graph = dcc.Graph(figure=make_top_sectors_graph())
        elif graph_mode == "efficiency":
            graph = dcc.Graph(figure=make_efficiency_graph())
        elif graph_mode == "history":
            graph = dcc.Graph(figure=make_history_graph())
        elif graph_mode == "profit":
            graph = dcc.Graph(figure=make_profit_graph())
        elif graph_mode == "dividends-bar":
            graph = dcc.Graph(figure=make_dividends_bar_graph())
        elif graph_mode == "dividends-efficiency":
            graph = dcc.Graph(figure=make_dividend_efficiency_graph())
        elif graph_mode == "drawdown":
            graph = dcc.Graph(figure=make_drawdown_graph())
        elif graph_mode == "etf-returns":
            graph = dcc.Graph(figure=make_etf_returns_graph())
        elif graph_mode == "cumulative-dividends":
            graph = dcc.Graph(figure=make_cumulative_dividends_graph())
        elif graph_mode == "avg-cost":
            graph = dcc.Graph(figure=make_avg_cost_graph())
        elif graph_mode == "avg-cost-norm":
            graph = dcc.Graph(figure=make_avg_cost_normalised_graph())
        elif graph_mode == "correlation":
            graph = dcc.Graph(figure=make_correlation_heatmap())

    return status, container, graph

def make_impact_graph(graph_type='daily'):
    # Build bar chart of weighted impact
    tickers = [etf.ticker for etf in portfolio]

    if graph_type == 'daily':
        impacts = [etf.daily_change_pct * etf.weight for etf in portfolio]  # in %
        title = "Daily Portfolio Impact by ETF"
    elif graph_type == 'total':
        impacts = [etf.grand_total_pct * etf.weight for etf in portfolio] # in %
        title = "Total Portfolio Impact by ETF"

    colors = ["green" if val > 0 else "red" if val < 0 else "white" for val in impacts]
    labels = [f"{val:+.2f}%" for val in impacts]

    figure = {
        "data": [
            {
                "x": tickers,
                "y": impacts,
                "type": "bar",
                "text": labels,
                "textposition": "auto",
                "marker": {"color": colors},
            }
        ],
        "layout": {
            "plot_bgcolor": "#222",
            "paper_bgcolor": "#222",
            "font": {"color": "#ccc"},
            "title": {"text": title, "font": {"size": 20}},
            "yaxis": {"title": "Impact (%)"},
        },
    }
    return figure

def make_weights_treemap():
    tickers = [etf.ticker for etf in portfolio]
    weights = [etf.weight for etf in portfolio]

    data = {'Ticker': tickers, 'Weight': weights}
    figure = px.treemap(data, path=["Ticker"], values="Weight", custom_data=["Ticker", "Weight"], 
                        title="ETF Portfolio Weights")

    figure.update_traces(
        texttemplate="%{customdata[0]}<br>%{customdata[1]:.1%}",  # Custom text
        textfont=dict(color="black", size=16),
        marker=dict(cornerradius=10),
        hovertemplate="%{customdata[0]}<br>%{customdata[1]:.1%}"
    )

    figure.update_layout(
        plot_bgcolor="#222",  # Inside the plot area
        paper_bgcolor="#222",  # Outside the plot area (like the margin)
        font=dict(color="#ccc"),  # All text (title, labels, etc.)
        margin = dict(t=35, l=10, r=10, b=10)
    )

    return figure

def make_top_holdings_graph():
    top_holdings = read_holding_csvs('holdings', 25)
    holdings, weights = zip(*top_holdings)
    holdings = [x + ' ' for x in holdings]

    fig = go.Figure(go.Bar(
    x=weights,
    y=holdings,
    orientation='h',  # 'h' for horizontal bars
    ))

    fig.update_layout(
        plot_bgcolor="#222",  # Inside the plot area
        paper_bgcolor="#222",  # Outside the plot area (like the margin)
        font=dict(color="#ccc"),  # All text (title, labels, etc.)
        margin = dict(t=35, l=10, r=10, b=10),
        yaxis=dict(
            autorange='reversed',
            ticklabelposition="outside",
            automargin=True
        )
    )
    return fig

def make_top_countries_graph():
    top_countries = read_holding_csvs('countries', 20)
    countries, weights = zip(*top_countries)
    emerging_markets = ['Hong Kong', 'India', 'Taiwan', 'Brazil', 'Saudi Arabia', 'South Africa']
    bar_colours =  ['#EF553B' if c in emerging_markets else '#636EFA' for c in countries]
    # add spacing to name to avoid butting up against axis
    countries = [x + ' ' for x in countries] 

    fig = go.Figure(go.Bar(
    x=weights,
    y=countries,
    orientation='h',  # 'h' for horizontal bars
    marker=dict(color=bar_colours)
    ))

    fig.update_layout(
        plot_bgcolor="#222",  # Inside the plot area
        paper_bgcolor="#222",  # Outside the plot area (like the margin)
        font=dict(color="#ccc"),  # All text (title, labels, etc.)
        margin = dict(t=35, l=100, r=10, b=10),
        yaxis=dict(
            autorange='reversed',
            ticklabelposition="outside",
            ticklen=10,
            automargin=True
        )
    )
    return fig

def make_top_sectors_graph():
    top_sectors = read_holding_csvs('sectors', 11)
    sectors, weights = zip(*top_sectors)
    # add spacing to name to avoid butting up against axis
    sectors = [x + ' ' for x in sectors] 

    fig = go.Figure(go.Bar(
    x=weights,
    y=sectors,
    orientation='h',  # 'h' for horizontal bars
    ))

    fig.update_layout(
        plot_bgcolor="#222",  # Inside the plot area
        paper_bgcolor="#222",  # Outside the plot area (like the margin)
        font=dict(color="#ccc"),  # All text (title, labels, etc.)
        margin = dict(t=35, l=100, r=10, b=10),
        yaxis=dict(
            autorange='reversed',
            ticklabelposition="outside",
            ticklen=10,
            automargin=True
        )
    )
    return fig
    
def make_efficiency_graph():
    perfs = {}

    for p in portfolio:
        if summary_data.grand_total_val == 0 or summary_data.total_paid == 0:
            continue
        contribution_pct = p.grand_total_val / summary_data.grand_total_val * 100
        original_weight_pct = p.total_paid / summary_data.total_paid * 100
        if original_weight_pct == 0:
            continue
        perf_ratio = contribution_pct / original_weight_pct
        perfs[p.name] = perf_ratio

    perfs = sorted(perfs.items(), key=lambda x: x[1], reverse=True)
    etfs = [x[0] + '  ' for x in perfs]
    perf = [x[1] for x in perfs]

    fig = go.Figure(go.Bar(
    x=perf,
    y=etfs,
    orientation='h',  # 'h' for horizontal bars
    ))

    fig.update_layout(
        plot_bgcolor="#222",  # Inside the plot area
        paper_bgcolor="#222",  # Outside the plot area (like the margin)
        font=dict(color="#ccc"),  # All text (title, labels, etc.)
        margin = dict(t=35, l=100, r=10, b=10),
        yaxis=dict(
            autorange='reversed',
            ticklabelposition="outside",
            ticklen=10,
            automargin=True
        )
    )
    return fig


def translate_country_code(code):
    codes = {'HK': 'Hong Kong', 'IN': 'India', 'TW': 'Taiwan', 'US': 'United States',
             'SA': 'Saudi Arabia', 'BR': 'Brazil', 'MX': 'Mexico', 'CA': 'Canada', 
             'ZA': 'South Africa', 'DE': 'Germany', 'FR': 'France', 'ES': 'Spain',
             'GB': 'United Kingdom', 'IT': 'Italy', 'NL': 'Netherlands', 'BE': 'Belgium',
             'AU': 'Australia', 'AT': 'Austria', 'CH': 'Switzerland', 'SE': 'Sweden',
             'NO': 'Norway', 'DK': 'Denmark', 'FI': 'Finland', 'IE': 'Ireland',
             'PT': 'Portugal', 'GR': 'Greece', 'CY': 'Cyprus', 'IL': 'Israel',
             'SG': 'Singapore', 'MY': 'Malaysia', 'PH': 'Philippines', 'ID': 'Indonesia', 
    }
    return codes.get(code, code)

def translate_sector(sector):
    sectors = {'Consumer Staples Distribution & Retail': 'Consumer Staples',
               "Health Care Providers & Services": 'Healthcare',
               "Software & Computer Services": 'Information Technology',
               'Banks': 'Financials', "Technology Hardware & Equipment": 'Information Technology',
               "Telecommunications Service Providers": 'Communication Services',
               "Precious Metals & Mining": 'Materials',  'Retailers': 'Consumer Discretionary',
               "Leisure Goods": 'Consumer Discretionary', "Travel & Leisure": 'Consumer Discretionary',
               "Industrial Metals & Mining": 'Materials', 'Software': 'Information Technology',
               "Textiles, Apparel & Luxury Goods": 'Consumer Discretionary',
               "Construction & Engineering": 'Industrials', 'Insurance': 'Financials',
               'Life Insurance': 'Financials', 'Metals & Mining': 'Materials',
               'Telecommunications Equipment': 'Communication Services',
               'Beverages': 'Consumer Staples', 'Electricity': 'Utilities',
               'Pharmaceuticals & Biotechnology': 'Healthcare',
               "Real Estate Management & Development": 'Real Estate',
               'Aerospace & Defense': 'Industrials', 'Oil, Gas & Coal': 'Energy',
               '"Health Care Equipment & Supplies"': 'Healthcare',
               "Diversified Telecommunication Services": 'Communication Services',
               'Finance & Credit Services': 'Financials', 'Chemicals': 'Materials',
               'Food Producers': 'Consumer Staples', 'Machinery': 'Industrials',
               'Industrial Transportation': 'Industrials',
               'Construction & Materials': 'Industrials',
               "Personal Care, Drug & Grocery Stores": 'Consumer Staples',
               "Real Estate Investment & Services": 'Real Estate',
               "Investment Banking & Brokerage Services": 'Financials',
               'Health Care Providers': 'Healthcare', 'General Industrials': 'Industrials',
               'Electronic & Electrical Equipment': 'Industrials',
               'Non-life Insurance': 'Financials', 'Personal Goods': 'Consumer Staples',
               'Media': 'Communication Services', 'Consumer Services': 'Consumer Staples',
    }
    return sectors.get(sector, sector)

def read_holding_csvs(mode, num_returned=20):
    # mode determines returned data - can be holdings, countries or sectors
    '''
    betashares header:
    Ticker,Name,Asset Class,Sector,Country,Currency,Weight (%),Shares/Units (#),Market Value (AUD),Notional Value (AUD)
    vanguard header:
    "Holding Name",Ticker,Sector,"Country code","% of net assets","Market value (AUD)","# of units"
    '''
    #etd, stock name, weight, sector, country
    etfs, names, weights = [], [], []
    countries, sectors = {}, {}

    # this is the number of lines to skip at the top of each file
    skiprows = {'betashares': 6, 'vanguard': 3}

    total = sum(p.weight for p in portfolio)
    if total == 0:
        return []
    port_weights = {p.ticker: (p.weight / total) for p in portfolio if p.weight > 0}

    for p in portfolio:

        # correct paths for Linux vs Windows
        filepath = DATA_DIR + p.holdings_file

        with open(filepath, 'r', encoding='cp1252') as infile:
            for _ in range(skiprows[p.issuer]):
                next(infile)
            
            reader = csv.DictReader(infile)
            currnames = []

            if p.issuer == 'betashares':
                for row in reader:
                    try:
                        if row['Name'] and row['Weight (%)']:
                            if row['Name'] != 'AUD - AUSTRALIA DOLLAR':
                                holdname = f'{row["Name"].title()} ({row["Ticker"]})'
                                currnames.append(holdname) 
                                wght = round(float(row['Weight (%)'])  * port_weights[p.ticker], 2)
                                weights.append(wght)
                                countries[row['Country']] = countries.get(row['Country'], 0) + wght
                                sectors[row['Sector']] = sectors.get(row['Sector'], 0) + wght
                                #ticker = normalize_ticker(row['Ticker'], None, source='betashares')
                    except Exception as err:
                        print(f'{row} - {err}')
            else:
                for row in reader:
                    try:
                        if row['Holding Name'] and row['% of net assets']:
                            currnames.append(row['Holding Name'])
                            wght = round(float(row['% of net assets'][:-1])  * port_weights[p.ticker], 2)
                            weights.append(wght)
                            country = translate_country_code(row['Country code'])
                            countries[country] = countries.get(country, 0) + wght
                            sector = translate_sector(row['Sector'])
                            sectors[sector] = sectors.get(sector, 0) + wght
                    except Exception as err:
                        print(f'{row} - {err}')

        #etfs += [etf_name] * len(currnames)
        names += currnames

    if mode == 'holdings':
        combined = list(zip(names, weights))
        combined = sorted(combined, key=lambda x: x[1], reverse=True)
    elif mode == 'countries':
        countries = {k: v for k, v in sorted(countries.items(), key=lambda item: item[1], reverse=True)}
        country, weights = list(countries.keys()), list(countries.values())
        combined = list(zip(country, weights))
    elif mode == 'sectors':
        sectors = {k: v for k, v in sorted(sectors.items(), key=lambda item: item[1], reverse=True)}
        sectors, weights = list(sectors.keys()), list(sectors.values())
        combined = list(zip(sectors, weights))

    return combined[:num_returned]

def get_yahoo_data(tickers):
    t = Ticker(tickers)
    quotes = t.price

    prices = {
        symbol: {
            'price': data.get('regularMarketPrice'),
            'yesterday_price': data.get('regularMarketPreviousClose'),
            'daily_change_pct': data.get('regularMarketChangePercent'),
        }
        for symbol, data in quotes.items()
        if isinstance(data, dict)
    }

    return prices

# init
load_portfolio()
#fetch_etf_data()
#make_top_holdings_graph()
#refresh_data(None)

if __name__ == "__main__":
    #app.run(debug=False, port=8050)
    if os.name == 'nt':
        hostaddr = '127.0.0.1'
    else:
        hostaddr = '0.0.0.0'
    app.run(host=hostaddr, port=8050, debug=True)
