import csv
import os
from pathlib import Path
from dataclasses import dataclass
from datetime import datetime
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
    holdings_file: str = None

# ETF data
portfolio = []
summary_data = Holding(ticker="Total...")

# File paths
winfilepath = r'n:\\'
linuxfilepath = Path.home() / 'sambashare'

def load_portfolio():
    # returns a dict with current portfolio holdings and weights from a csv with following format:
    # Ticker,Units,TotalPaid,Issuer,HoldingsFile

    if os.name == 'nt':
        portfile = winfilepath + 'portfolio.csv'
    else:
        portfile = linuxfilepath / 'portfolio.csv'

    with open(portfile, 'r', encoding='utf-8') as infile:
        reader = csv.DictReader(infile)
        for row in reader:
            portfolio.append(Holding(
                ticker=row['Ticker'],
                name=row['Ticker'],
                units=int(row['Units']),
                total_paid=float(row['TotalPaid']),
                issuer=row['Issuer'],
                holdings_file=row['HoldingsFile']
            ))

def format_change(pct, val):
    sign = "▲" if val > 0 else "▼" if val < 0 else ""
    color = "springgreen" if val > 0 else "tomato" if val < 0 else "white"
    symbol = '+' if val > 0 else '-' if val < 0 else ''
    text = f"{sign} {pct:.2f}% ({symbol}${val:,.2f})"
    return html.Span(text, style={"color": color})

def generate_etf_header():
    return html.Div(
        className="etf-row",
        children=[
            html.Div("Ticker", style={"fontWeight": "bold"}),
            html.Div("Daily", style={"fontWeight": "bold"}),
            html.Div("Total", style={"fontWeight": "bold"})
        ],
    )

def generate_etf_row(etf):
    return html.Div(
        className="etf-row",
        children=[
            html.Div(etf.ticker[:-3] + ':', className="etf-name"),
            html.Div(format_change(etf.daily_change_pct, etf.daily_change_val), className="etf-daily"),
            html.Div(format_change(etf.total_change_pct, etf.total_change_val), className="etf-total"),
        ],
    )

app.layout = html.Div(
    className='main-body',
    children=[
        dcc.Interval(id="startup-trigger", interval=1*1000, n_intervals=0, max_intervals=1),
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
                                {"label": "Total Value Over Time", "value": "history"},
                                
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
        etf.daily_change_pct = curr_prices[etf.ticker]["daily_change_pct"] * 100
        etf.daily_change_val = etf.units * (curr_prices[etf.ticker]["price"] - curr_prices[etf.ticker]['yesterday_price'])
        etf.current_value = curr_prices[etf.ticker]["price"] * etf.units
        etf.total_change_pct = (etf.current_value - etf.total_paid) / etf.total_paid * 100
        etf.total_change_val = etf.current_value - etf.total_paid

    summary_data.daily_change_val = sum(etf.daily_change_val for etf in portfolio) 
    summary_data.total_change_val = sum(etf.total_change_val for etf in portfolio)
    summary_data.current_value = sum(etf.current_value for etf in portfolio)
    
    overall_total_paid = sum([etf.total_paid for etf in portfolio])

    for etf in portfolio:
        etf.weight = (etf.current_value / summary_data.current_value)
    
    summary_data.daily_change_pct = (summary_data.daily_change_val / summary_data.current_value) * 100
    summary_data.total_change_pct = (summary_data.total_change_val / overall_total_paid) * 100

@app.callback(
    Output("status-line", "children"),
    Output("etf-container", "children"),
    Output("graph-container", "children"),
    Input("refresh-button", "n_clicks"),
    Input("startup-trigger", "n_intervals"),
    Input("graph-selector", "value"),
)
def handle_all(n_clicks, n_intervals, graph_mode):
    triggered = dash.callback_context.triggered_id
    print(f"Triggered by: {triggered}")

    # Defaults
    status = dash.no_update
    container = dash.no_update
    graph = dash.no_update

    if triggered in ["refresh-button", "startup-trigger"]:
        fetch_etf_data()
        status = f"Last refreshed at {datetime.now().strftime('%I:%M:%S %p').lstrip('0')}"
        container = [generate_etf_header()] + [generate_etf_row(etf) for etf in portfolio] + [generate_etf_row(summary_data)]
        if graph_mode == "daily-impact":
            graph = dcc.Graph(figure=make_impact_graph())

    elif triggered == "graph-selector":
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
        elif graph_mode == "cumulative":
            graph = dcc.Graph(figure=make_cumulative_graph())

    return status, container, graph

def make_impact_graph(graph_type='daily'):
    # Build bar chart of weighted impact
    tickers = [etf.ticker for etf in portfolio]

    if graph_type == 'daily':
        impacts = [etf.daily_change_pct * etf.weight for etf in portfolio]  # in %
        title = "Daily Portfolio Impact by ETF"
    elif graph_type == 'total':
        impacts = [etf.total_change_pct * etf.weight for etf in portfolio]  # in %
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
    top_sectors = read_holding_csvs('sectors', 12)
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
               'Aerospace & Defense': 'Industrials',
               '"Health Care Equipment & Supplies"': 'Healthcare',
               "Diversified Telecommunication Services": 'Communication Services',
               'Finance & Credit Services': 'Financials', 
               'Food Producers': 'Consumer Staples', 'Machinery': 'Industrials',
               'Industrial Transportation': 'Industrials',
               'Construction & Materials': 'Industrials',
               "Personal Care, Drug & Grocery Stores": 'Consumer Staples',
               "Real Estate Investment & Services": 'Real Estate',
               "Investment Banking & Brokerage Services": 'Financials',
               'Health Care Providers': 'Healthcare',
               'Electronic & Electrical Equipment': 'Industrials',
               
            

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

    # generate relative weightings for items in the portfolio
    total = sum([p.weight for p in portfolio])
    port_weights = {p.ticker: (p.weight / total) for p in portfolio if p.weight > 0}

    for p in portfolio:

        # correct paths for Linux vs Windows
        if os.name == 'nt':
            filepath = winfilepath + p.holdings_file
        else:
            filepath = linuxfilepath / p.holdings_file

        with open(filepath, 'r', encoding='utf-8') as infile:
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
                                wght = round(float(row['Weight (%)'])  * port_weights[p.name], 2)
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
                            wght = round(float(row['% of net assets'][:-1])  * port_weights[p.name], 2)
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
    app.run(host='0.0.0.0', port=8050, debug=True)
