from dataclasses import dataclass
import csv
import plotly.express as px
import pandas as pd
from yahooquery import Ticker as Ticker

'''
to do:
import holdings automatically through csv
sector/country treemaps
colour squares/etfs by daily motion - both top level and underlying held assets
central labels?
at a glance summary page
experiment with yfinance retrieval limits/throttling - 1-2K requests/hr for IP auth. VPN likely to cause issues here?
'''

@dataclass
class Holding:
    name: str
    ticker: str
    units: int = 0
    weight: float = 0
    sector: str = None
    country: str = None
    issuer: str = None
    daily_change: float = 0
    holdings_file: str = None

def render_treeview(etfs, names, weights):

    df = pd.DataFrame({
        'ETF': etfs,
        'Stock': names,
        'Portfolio_Weight': weights 
    })

    df["Label"] = df["Stock"] + "<br>" + (df["Portfolio_Weight"] * 100).round(2).astype(str) + "%"
    df["Weight_Percent"] = (df["Portfolio_Weight"] * 100).round(2)

    fig = px.treemap(
        df,
        path=['ETF', 'Stock'],
        values='Portfolio_Weight',
        custom_data=['Portfolio_Weight', 'Weight_Percent']
    )

    fig.update_layout(
        hoverlabel=dict(
            bgcolor="white",
            font_color="black",
            font_size=14,   # Optional: set size for readability
            font_family="Arial"  # Optional: consistent font
        )
    )

    fig.update_traces(
        text=df["Label"],
        textinfo='text',              
        textfont_size=12,
        hovertemplate='<b>%{label}</b><br>Weight: %{customdata[1]:.2f}%<extra></extra>'
    )

    fig.update_layout(margin=dict(t=20, l=10, r=10, b=10))
    fig.show()

def get_daily_changes(combined):
    combined.sort(key=lambda x: x[2], reverse=True)
    top = combined[:100]

    etfs, names, weights = zip(*combined)

def get_portfolio_data():
    # returns a dict with current portfolio holdings and weights from a csv with following format:
    # Ticker,Units,TotalPaid,Issuer,HoldingsFile
    portfolio = []

    with open(r'd:\tmp\portfolio.csv', 'r', encoding='utf-8') as infile:
        reader = csv.DictReader(infile)
        for row in reader:
            portfolio.append(Holding(
                name=row['Ticker'], # double up, use ticker as name
                ticker=row['Ticker'],
                units=int(row['Units']),
                weight=0,
                issuer=row['Issuer'],
                holdings_file=row['HoldingsFile']
            ))

    return portfolio

def normalize_ticker(raw_ticker, country_code=None, source='vanguard'):
    """
    Convert a raw ticker from Vanguard or Betashares into a valid Yahoo Finance ticker.

    :param raw_ticker: e.g. '2330', 'BRK/B UN', 'NESN VX'
    :param country_code: e.g. 'TW', 'US', 'JP' (from Vanguard CSV)
    :param source: 'vanguard' or 'betashares'
    :return: normalized ticker (e.g. '2330.TW', 'BRK-B', 'NESN.SW')
    """
    raw_ticker = raw_ticker.strip()

    # Bloomberg-style exchange codes (Betashares)
    bloomberg_to_yahoo = {
        'AU': '.AX',   # Australia (ASX)
        'AT': '.AX',   # Australia (ASX)
        'UW': '',      # NASDAQ
        'UN': '',      # NYSE
        'LN': '.L',    # London
        'FP': '.PA',   # Paris
        'GR': '.DE',   # Xetra
        'GY': '.DE',   # Frankfurt
        'VX': '.SW',   # Switzerland
        'SE': '.SW',   # Switzerland
        'HK': '.HK',   # Hong Kong
        'JP': '.T',    # Tokyo
        'KS': '.KS',   # South Korea
        'TW': '.TW',   # Taiwan
        'CN': '.SS',   # Shanghai
        'TI': '.MI',   # Italy (Borsa Italiana)
        'CT': '.TO',   # Canada?
    }

    if source == 'betashares':
        # Handle things like 'BRK/B UN'
        raw_ticker = raw_ticker.replace('/', '-')
        parts = raw_ticker.split()
        if len(parts) == 2:
            symbol, exch = parts
            suffix = bloomberg_to_yahoo.get(exch.upper(), '')
            return symbol + suffix
        else:
            return raw_ticker

    elif source == 'vanguard':
        # e.g. 2330 (TW), or AAPL (US)
        if raw_ticker.isdigit() and country_code:
            suffix = bloomberg_to_yahoo.get(country_code.upper(), '')
            return raw_ticker + suffix
        elif '/' in raw_ticker:
            return raw_ticker.replace('/', '-')
        else:
            return raw_ticker

    return raw_ticker

def extract_financial_data(portfolio):
    '''
    betashares header:
    Ticker,Name,Asset Class,Sector,Country,Currency,Weight (%),Shares/Units (#),Market Value (AUD),Notional Value (AUD)
    vanguard header:
    "Holding Name",Ticker,Sector,"Country code","% of net assets","Market value (AUD)","# of units"
    '''
    #etd, stock name, weight, sector, country
    all_weights = []
    etfs, names, weights, changes = [], [], [], []

    # this is the number of lines to skip at the top of each file
    skiprows = {'betashares': 6, 'vanguard': 3}

    # generate relative weightings for items in the portfolio
    total = sum([p.weight for p in portfolio])
    port_weights = {p.ticker: (p.weight / total) for p in portfolio if p.weight > 0}

    # 
    for p in portfolio:
        with open(p.holdings_file, 'r', encoding='utf-8') as infile:
            for _ in range(skiprows[p.issuer]):
                next(infile)
            
            reader = csv.DictReader(infile)
            currnames = []

            if p.issuer == 'betashares':
                for row in reader:
                    try:
                        if row['Name'] and row['Weight (%)']:
                            if row['Name'] != 'AUD - AUSTRALIA DOLLAR':
                                currnames.append(row['Name'])
                                wght = float(row['Weight (%)']) / 100 * port_weights[p.name]
                                weights.append(wght)
                                ticker = normalize_ticker(row['Ticker'], None, source='betashares')
                    except Exception as err:
                        print(f'{row} - {err}')
            else:
                for row in reader:
                    try:
                        if row['Holding Name'] and row['% of net assets']:
                            currnames.append(row['Holding Name'])
                            wght = float(row['% of net assets'][:-1]) / 100 * port_weights[p.name]
                            weights.append(wght)
                    except Exception as err:
                        print(f'{row} - {err}')

        etfs += [etf_name] * len(currnames)
        names += currnames

    combined = list(zip(etfs, names, weights))
    changes = get_daily_changes(combined)

    return etfs, names, weights

def get_yahoo_data(tickers):
    # Create Ticker object
    t = Ticker(tickers)

    # Fetch the 'price' summary data (current quote)
    quotes = t.price

    # Get both current price and daily % change
    prices = {
        symbol: {
            'price': data.get('regularMarketPrice'),
            'change_pct': data.get('regularMarketChangePercent')
        }
        for symbol, data in quotes.items()
        if isinstance(data, dict)
    }

    return prices

def main():
    # https://www.betashares.com.au/files/csv/A200_Portfolio_Holdings.csv
    # https://www.betashares.com.au/files/csv/BGBL_Portfolio_Holdings.csv

    portfolio = get_portfolio_data()
    prices = get_yahoo_data([p.ticker for p in portfolio])

    for p in portfolio:
        p.weight = round(prices[p.ticker]['price'] * p.units, 2)
        p.daily_change = round(prices[p.ticker]['change_pct'] * 100, 2)

    print(portfolio)
    print(sum(p.weight for p in portfolio))

    extract_financial_data(portfolio)
    #render_treeview(etfs, names, weights)
    

'''
    results = run_yahooquery(tickers)
    for symbol, change in results.items():
        print(f'{symbol}: {change}%')
'''

if __name__ == '__main__':
    main()

