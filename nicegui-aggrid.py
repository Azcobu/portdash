import csv
from nicegui import events, ui
from dataclasses import dataclass, asdict
from yahooquery import Ticker as Ticker
import plotly.graph_objects as go
import plotly.express as px

ui.dark_mode().value = True

@dataclass
class Holding:
    ticker: str
    units: int = 0
    total_paid: float = 0
    current_value: float = 0
    weight: float = 0
    daily_change_pct: float = 0
    daily_change_dollars: float = 0
    total_change_pct: float = 0
    total_change_dollars: float = 0

# fake data for testing
'''
portfolio = [
    Holding('A200', 256, 43222, 132.62, 31, 0.53, 234, -4.12, -1342.88),
    Holding('BGBL', 1542, 93222, 73.12, 55, -0.16, -323, 6.23, 7342.89),
    Holding('VGE', 121, 11642, 73.27, 8, 0.62, -117.32, 2.74, 228.32),
    Holding('VISM', 82, 5254, 81.62, 6, 0, 0, 9.86, 512.14),
]
'''
portfolio = []
summary_data = Holding(ticker="Total...")
ui_refs = {}

def load_portfolio():
    # returns a dict with current portfolio holdings and weights from a csv with following format:
    # Ticker,Units,TotalPaid,Issuer,HoldingsFile
    global portfolio
    
    print('Loading portfolio data.')
    portfolio = []
    with open(r'd:\tmp\portfolio.csv', 'r', encoding='utf-8') as infile:
        reader = csv.DictReader(infile)
        for row in reader:
            portfolio.append(Holding(
                ticker=row['Ticker'],
                units=int(row['Units']),
                total_paid=float(row['TotalPaid']),
            ))

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

def fetch_etf_data():
    print('Updating ETF data.')
    curr_prices = get_yahoo_data([etf.ticker for etf in portfolio])

    for etf in portfolio:
        etf.daily_change_pct = curr_prices[etf.ticker]["daily_change_pct"] * 100
        etf.daily_change_dollars = etf.units * (curr_prices[etf.ticker]["price"] - curr_prices[etf.ticker]['yesterday_price'])
        etf.current_value = curr_prices[etf.ticker]["price"] * etf.units
        etf.total_change_pct = (etf.current_value - etf.total_paid) / etf.total_paid * 100
        etf.total_change_dollars = etf.current_value - etf.total_paid

    summary_data.daily_change_dollars = sum(etf.daily_change_dollars for etf in portfolio) 
    summary_data.total_change_dollars = sum(etf.total_change_dollars for etf in portfolio)
    
    overall_total_paid = sum([etf.total_paid for etf in portfolio])
    overall_total_value = sum([etf.current_value for etf in portfolio])

    for etf in portfolio:
        etf.weight = round((etf.current_value / overall_total_value * 100), 1)

    summary_data.daily_change_pct = (summary_data.daily_change_dollars / overall_total_value) * 100
    summary_data.total_change_pct = (summary_data.total_change_dollars / overall_total_paid) * 100

def calc_table_data():
    row_data = []
    for p in portfolio:
        p_dict = asdict(p)
        p_dict['daily_change_pct'] = p.daily_change_pct
        p_dict['daily_change_dollars'] = p.daily_change_dollars
        p_dict['daily_display'] = format_change(p.daily_change_pct, p.daily_change_dollars)
        p_dict['total_display'] = format_change(p.total_change_pct, p.total_change_dollars)
        row_data.append(p_dict)
    return row_data

def format_change(pct: float, dollars: float) -> str:
    arrow = '▲' if pct > 0 else '▼' if pct < 0 else ''
    sign = '+' if dollars > 0 else '-' if dollars < 0 else ''
    return f'{arrow} {pct:.2f}% ({sign}${abs(dollars):,.2f})'

def get_total_row() -> dict:
    return {
        'ticker': 'Total:',
        'weight': 100, #sum(h.weight for h in data),
        'daily_display': format_change(summary_data.daily_change_pct, summary_data.daily_change_dollars),
        'daily_change_pct': summary_data.daily_change_pct,
        'total_display': format_change(summary_data.total_change_pct, summary_data.total_change_dollars),
        'total_change_pct': summary_data.total_change_pct,
    }

def refresh_data():
    print('Refreshing data.')

    button = ui_refs['refresh_button']
    button.props(add='loading')
    button.disable()

    try:
        fetch_etf_data()
        grid = ui_refs['grid']
        grid.options['rowData'] = calc_table_data()
        grid.options['pinnedBottomRowData'] = [get_total_row()]
        grid.update()
        new_fig = make_impact_graph()
        ui_refs['plot'].figure = new_fig
    except Exception as err:
        print(f'Error updating data: {err}')
    finally:
        button.props(remove='loading')
        button.enable()

def make_weights_treemap():
    tickers = [etf.ticker for etf in portfolio]
    weights = [etf.weight for etf in portfolio]
    #colors
    #labels = [f'{ticker} - {weight}' for ticker, weight in zip(tickers, weights)]

    data = {'Ticker': tickers, 'Weight': weights}
    figure = px.treemap(data, path=["Ticker"], values="Weight", title="ETF Portfolio Weights")
    return figure

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

def generate_figure(graph_type: str):
    if graph_type == "Daily % Impact by ETF":
        return make_impact_graph()
    elif graph_type == "ETF Portfolio Weights":
        return make_weights_treemap()
    elif graph_type == "Total $ Impact by ETF":
        return px.bar(x=["A", "B", "C"], y=[10, 20, 15], title="Total $ Impact")
    else:
        return px.line(x=[1, 2, 3], y=[1, 4, 9], title="Value Over Time")

def update_plot(event=None):
    graph_type = ui_refs['dropdown'].value
    print(f'Updating graph to {graph_type}')
    fig = generate_figure(graph_type)
    
    ui_refs['plot'].delete()
    with ui_refs['plot_container']:
        ui_refs['plot'] = ui.plotly(fig)

ui.add_head_html('''
<style>
  .ag-theme-balham-dark {
    font-size: 18px !important;         /* whole grid font */
    font-family: "Calibri", sans-serif;
  }
  .ag-header-cell-label {
    font-size: 20px !important;         /* header font */
    font-weight: bold;
  }
  .ag-cell {
    font-size: 18px !important;         /* cell font */
  }
</style>
''')

''' formatting example for different coloure odd and even rows.
.ag-theme-balham-dark .ag-row-odd {
    background-color: rgb(238, 241, 238);
    border-radius: 10px;
}
.ag-theme-balham-dark .ag-row-even {
    background-color: white;
    border-radius: 10px;
}
'''

#sortingOrder: ["asc", "desc"]

@ui.page('/')
def main():
    ui.dark_mode().value = True
    load_portfolio()
    fetch_etf_data()

    ui.add_head_html('''
    <style>
    .ag-theme-balham-dark .ag-cell,
    .ag-theme-balham-dark .ag-header-cell {
        font-size: 20px !important;
        font-family: "Calibri", sans-serif !important;
    }
    </style>
    ''')

    with ui.row().classes('w-full'):
        with ui.column().classes('items-start p-4 w-1/2 box-border'):  # LEFT-align contents to avoid full stretch
            ui.label('ETF Performance:')
            
            ui_refs['grid'] = ui.aggrid({
                    'columnDefs': [
                        {'headerName': 'Ticker', 'field': 'ticker', 'width': 50},
                        {'headerName': 'Daily', 'field': 'daily_change_pct', 'width': 100,
                        'valueFormatter': "data.daily_display",
                        'cellClassRules': {
                            "text-green-500": "x > 0",
                            "text-red-500": "x < 0",
                            "text-white": "x === 0",
                            }
                        },
                        {'headerName': 'Total', 'field': 'total_change_pct', 'width': 100,
                        'valueFormatter': "data.total_display",
                        'cellClassRules': {
                            'text-green-500': 'x > 0',
                            'text-red-500': 'x < 0',
                            'text-white': 'x === 0',
                        }},
                        {'headerName': 'Weight', 'field': 'weight', 'width': 50}],
                    'rowData': calc_table_data(),
                    'pinnedBottomRowData': [get_total_row()],
                    'domLayout': 'autoHeight',
                }).classes('ag-theme-balham-dark max-w-screen-md mx-auto text-lg')

            ui_refs['refresh_button'] = ui.button('Refresh', on_click=refresh_data, icon='refresh')


        # right column
        with ui.column().classes('w-1/3'):
            ui_refs['dropdown'] = ui.select(
                ["Daily % Impact by ETF", "ETF Portfolio Weights","Total $ Impact by ETF", "Total Value Over Time"],
                value="Daily % Impact by ETF", on_change=update_plot, label='Select graph type:')
            #ui_refs['plot'] = ui.plotly(make_impact_graph())
            ui_refs['plot_container'] = ui.column()
            with ui_refs['plot_container']:
                ui_refs['plot'] = ui.plotly(generate_figure("Daily % Impact by ETF"))

                              
            

ui.run()