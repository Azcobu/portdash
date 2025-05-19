import csv
from dataclasses import dataclass
from datetime import datetime
import dash
from dash import html, dcc, Output, Input
import plotly.graph_objs as go
from yahooquery import Ticker as Ticker

app = dash.Dash(__name__)

@dataclass
class Holding:
    ticker: str
    units: int = 0
    total_paid: float = 0
    weight: float = 0
    issuer: str = None
    daily_change_pct: float = 0
    daily_change_val: float = 0
    total_change_pct: float = 0
    total_change_val: float = 0

# ETF data
portfolio = []
summary_data = Holding(ticker="Total...")

def load_portfolio():
    # returns a dict with current portfolio holdings and weights from a csv with following format:
    # Ticker,Units,TotalPaid,Issuer,HoldingsFile
    global portfolio
    
    with open(r'd:\tmp\portfolio.csv', 'r', encoding='utf-8') as infile:
        reader = csv.DictReader(infile)
        for row in reader:
            portfolio.append(Holding(
                ticker=row['Ticker'],
                units=int(row['Units']),
                total_paid=float(row['TotalPaid']),
                issuer=row['Issuer']
            ))

def format_change(pct, val):
    sign = "▲" if val > 0 else "▼" if val < 0 else ""
    color = "springgreen" if val > 0 else "tomato" if val < 0 else "white"
    symbol = '+' if val > 0 else '-' if val < 0 else ''
    text = f"{sign} {pct:.2f}% ({symbol}${val:,.2f})"
    return html.Span(text, style={"color": color})

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
    style={"backgroundColor": "#111", "color": "#DDD", "padding": "2rem", "fontFamily": "Tahoma"},
    children=[
        dcc.Interval(id="startup-trigger", interval=1*1000, n_intervals=0, max_intervals=1),
        html.Div(
            style={"display": "flex"},
            children=[
                # Left column with ETF boxes
                html.Div(
                    id="etf-container",
                    style={
                        "flex": "1",
                        "display": "flex",
                        "flexDirection": "column",
                        "gap": "1rem",
                        "marginRight": "2rem",
                        "minWidth": "500px"
                    },
                    children=[
                        generate_etf_row(etf) for etf in portfolio
                    ] + [generate_etf_row(summary_data)]
                ),

                # Right column (placeholder for future graph)
                html.Div(
                    style={"flex": "1"},
                    children=[
                        dcc.Graph(
                            figure=go.Figure(
                                data=[go.Bar(x=["A200", "BGBL", "VISM", "VGE"], y=[10, 20, 5, 7])],
                                layout=go.Layout(
                                    plot_bgcolor="#222",
                                    paper_bgcolor="#222",
                                    font=dict(color="#DDD"),
                                    title="Mock Graph",
                                ),
                            )
                        )
                    ],
                ),
            ],
        ),
        html.Div(id="status-line", style={"color": "#ccc", "marginTop": "1rem"}),
        html.Button("Refresh", id="refresh-button", style={"marginTop": "2rem", "padding": "0.5rem 1rem", "fontSize": "1rem"})
    ],
)

@app.callback(
    Output("status-line", "children"),
    Output("etf-container", "children"),
    Input("refresh-button", "n_clicks"),
    Input("startup-trigger", "n_intervals"),
    prevent_initial_call=True
)
def refresh_data(n, n_intervals=None):
    #print('Retrieving price data...', end='', flush=True)
    status_text = 'Retrieving price data...'
    curr_prices = get_yahoo_data([etf.ticker for etf in portfolio])
    print('done.')

    for etf in portfolio:
        etf.daily_change_pct = curr_prices[etf.ticker]["daily_change_pct"] * 100
        etf.daily_change_val = etf.units * (curr_prices[etf.ticker]["price"] - curr_prices[etf.ticker]['yesterday_price'])
        current_value = curr_prices[etf.ticker]["price"] * etf.units
        etf.total_change_pct = (current_value - etf.total_paid) / etf.total_paid * 100
        etf.total_change_val = current_value - etf.total_paid

    summary_data.daily_change_val = sum(etf.daily_change_val for etf in portfolio) 
    summary_data.total_change_val = sum(etf.total_change_val for etf in portfolio)
    
    overall_total_paid = sum([etf.total_paid for etf in portfolio])
    overall_total_value = sum([etf.units * curr_prices[etf.ticker]["price"] for etf in portfolio])
    
    summary_data.daily_change_pct = (summary_data.daily_change_val / overall_total_value) * 100
    summary_data.total_change_pct = (summary_data.total_change_val / overall_total_paid) * 100

    time_str = datetime.now().strftime("%H:%M:%S")
    status_text = f"Last refreshed at {time_str}."

    return  status_text, [generate_etf_row(etf) for etf in portfolio] + [generate_etf_row(summary_data)]

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

app.index_string = app.index_string.replace(
    '</head>',
    '''
    <style>
        .etf-row {
            display: grid;
            grid-template-columns: 120px 1fr 1fr;
            background-color: #222;
            padding: 0.75rem;
            border-radius: 8px;
            font-size: 1.2rem;
        }
        .etf-name {
            font-weight: bold;
            font-size: 1.0rem;
        }
        .etf-daily, .etf-total {
            text-align: left;
        }
    </style>
    </head>
    '''
)

# init
load_portfolio()
#refresh_data(None)

if __name__ == "__main__":
    app.run(debug=False, port=8050)
