from nicegui import events, ui
from dataclasses import dataclass, asdict

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
portfolio = [
    Holding('A200', 256, 43222, 132.62, 31, 0.53, 234, 4.12, 1342.88),
    Holding('BGBL', 1542, 93222, 73.12, 55, -0.16, -323, 6.23, 7342.89),
    Holding('VGE', 121, 11642, 73.27, 8, -0.62, -117.32, 2.74, 228.32),
    Holding('VISM', 82, 5254, 81.62, 6, 0, 0, 9.86, 512.14),
]

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

def get_total_row(data: list[Holding]) -> dict:
    return {
        'ticker': 'Total:',
        'units': sum(h.units for h in data),
        'total_paid': sum(h.total_paid for h in data),
        'current_value': sum(h.current_value for h in data),
        'weight': sum(h.weight for h in data),
        'daily_display': 'UNDEFINED',
        'daily_change_pct': sum(h.daily_change_pct for h in data),
        'daily_change_dollars': sum(h.daily_change_dollars for h in data),
        'total_change_pct': sum(h.total_change_pct for h in data),
        'total_change_dollars': sum(h.total_change_dollars for h in data),
    }

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

with ui.column().classes('items-start p-4 w-1/2'):  # LEFT-align contents to avoid full stretch
    ui.label('Compact Grid:')
    
    data = calc_table_data()
    total_row = get_total_row(portfolio)
    grid = ui.aggrid({
            'columnDefs': [
                {'headerName': 'Ticker', 'field': 'ticker', 'width': 50},
                {'headerName': 'Daily', 'field': 'daily_change_pct', 'width': 100, 'sortable': True,
                  'valueFormatter': "data.daily_display",
                  'cellClassRules': {
                     "text-green-500": "x > 0",
                     "text-red-500": "x < 0",
                     "text-white": "x === 0",
                     }
                },
                {'headerName': 'Total', 'field': 'total_display', 'width': 100,
                 'cellClassRules': {
                    'text-green-500': 'x > 0',
                    'text-red-500': 'x < 0',
                    'text-white': 'x === 0',
                }},
                {'headerName': 'Weight', 'field': 'weight', 'width': 100}],
            'rowData': calc_table_data(),
            'pinnedBottomRowData': [total_row],
            'domLayout': 'autoHeight',
        }).classes('ag-theme-balham-dark max-w-screen-md mx-auto text-lg') 



ui.run()