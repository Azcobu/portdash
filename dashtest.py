import csv
from dataclasses import dataclass
from datetime import datetime
import dash
from dash import html, dcc, Output, Input, State
import plotly.graph_objs as go
from yahooquery import Ticker as Ticker

app = dash.Dash(__name__)

@dataclass
class Holding:
    ticker: str
    units: int = 0
    total_paid: float = 0
    current_value: float = 0
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

def generate_etf_header():
    return html.Div(
        className="etf-row",
        children=[
            html.Div("Ticker", style={"fontWeight": "bold"}),
            html.Div("Daily", style={"fontWeight": "bold"}),
            html.Div("Total", style={"fontWeight": "bold"})
        ],
        style={
            "justifyContent": "space-between",
            "borderBottom": "2px solid #ccc",
            "color": "#ccc"
        }
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

                # Right column
                html.Div(
                    style={"flex": "1"},
                    children=[
                        dcc.Dropdown(
                            id="graph-selector",
                            placeholder="Select a graph type...",
                            options=[
                                {"label": "Daily % Impact by ETF", "value": "impact"},
                                {"label": "Total Value Over Time", "value": "history"},
                                {"label": "Total $ Impact by ETF", "value": "value_impact"},
                            ],
                            #value="impact",
                            clearable=False,
                            style={"backgroundColor": "#222", "color": "#ccc", "marginBottom": "1rem"}
                        ),
                        dcc.Graph(id="etf-graph", style={"backgroundColor": "#222", "color": "#ccc"})
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

@app.callback(
    [Output("status-line", "children"),
    Output("etf-container", "children"),
    Output("etf-graph", "figure")], 
    [Input("refresh-button", "n_clicks"),
    Input("startup-trigger", "n_intervals")],
)
def refresh_data(n, n_intervals=None):
    #print('Retrieving price data...', end='', flush=True)
    status_text = 'Retrieving price data...'
    curr_prices = get_yahoo_data([etf.ticker for etf in portfolio])
    print('done.')

    for etf in portfolio:
        etf.daily_change_pct = curr_prices[etf.ticker]["daily_change_pct"] * 100
        etf.daily_change_val = etf.units * (curr_prices[etf.ticker]["price"] - curr_prices[etf.ticker]['yesterday_price'])
        etf.current_value = curr_prices[etf.ticker]["price"] * etf.units
        etf.total_change_pct = (etf.current_value - etf.total_paid) / etf.total_paid * 100
        etf.total_change_val = etf.current_value - etf.total_paid

    summary_data.daily_change_val = sum(etf.daily_change_val for etf in portfolio) 
    summary_data.total_change_val = sum(etf.total_change_val for etf in portfolio)
    
    overall_total_paid = sum([etf.total_paid for etf in portfolio])
    overall_total_value = sum([etf.current_value for etf in portfolio])

    for etf in portfolio:
        etf.weight = (etf.current_value / overall_total_value)
    
    summary_data.daily_change_pct = (summary_data.daily_change_val / overall_total_value) * 100
    summary_data.total_change_pct = (summary_data.total_change_val / overall_total_paid) * 100

    # Update status line
    time_str = datetime.now().strftime("%I:%M:%S %p")
    if time_str[0] == '0':
        time_str = time_str[1:]  # Remove leading zero
    status_text = f"Last refreshed at {time_str}."

    # Build bar chart of weighted impact
    tickers = [etf.ticker for etf in portfolio]
    impacts = [etf.daily_change_pct * etf.weight for etf in portfolio]  # in %
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
            "title": {"text": "Daily Portfolio Impact by ETF", "font": {"size": 20}},
            "yaxis": {"title": "Impact (%)"},
        },
    }
    
    #figure = update_graph()
    #figure = make_impact_graph()

    etf_boxes = [generate_etf_header()] + [generate_etf_row(etf) for etf in portfolio] + [generate_etf_row(summary_data)]
    return status_text, etf_boxes, figure

def make_impact_graph():
    # Build bar chart of weighted impact
    tickers = [etf.ticker for etf in portfolio]
    impacts = [etf.daily_change_pct * etf.weight for etf in portfolio]  # in %
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
            "title": {"text": "Daily Portfolio Impact by ETF", "font": {"size": 20}},
            "yaxis": {"title": "Impact (%)"},
        },
    }
    return figure
'''
@app.callback(
    Output("etf-graph", "figure"),
    [Input("graph-selector", "value")]
)
def update_graph(graph_mode):
    print('graph type changed')
    if graph_mode is None:
        graph_mode = "impact"  # Fallback default
    
    # Example response (replace with your real graph logic)
    if graph_mode == "impact":
        fig = make_impact_graph()
    elif graph_mode == "history":
        print('history')
        #fig = make_history_graph()
    elif graph_mode == "value_impact":
        print('value impact')
        #fig = make_value_impact_graph()
    else:
        fig = go.Figure()  # blank graph fallback
    
    return fig
'''

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
