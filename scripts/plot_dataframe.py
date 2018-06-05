#!/usr/bin/env python3
"""
Script to display when the bot will buy a specific pair

Mandatory Cli parameters:
-p / --pair: pair to examine

Option but recommended
-s / --strategy: strategy to use


Optional Cli parameters
-d / --datadir: path to pair backtest data
--timerange: specify what timerange of data to use.
-l / --live: Live, to download the latest ticker for the pair
-db / --db-url: Show trades stored in database


Indicators recommended
Row 1: sma, ema3, ema5, ema10, ema50
Row 3: macd, rsi, fisher_rsi, mfi, slowd, slowk, fastd, fastk

Example of usage:
> python3 scripts/plot_dataframe.py --pair BTC/EUR -d user_data/data/ --indicators1 sma,ema3
--indicators2 fastk,fastd
"""
import logging
import os
import sys
from argparse import Namespace
from typing import Dict, List, Any
from sqlalchemy import create_engine
from plotly import tools
from plotly.offline import plot
import plotly.graph_objs as go
from freqtrade.arguments import Arguments
from freqtrade.analyze import Analyze
from freqtrade.optimize.backtesting import setup_configuration
from freqtrade import exchange
import freqtrade.optimize as optimize
from freqtrade import persistence
from freqtrade.persistence import Trade

logger = logging.getLogger(__name__)
_CONF: Dict[str, Any] = {}


def plot_analyzed_dataframe(args: Namespace) -> None:
    """
    Calls analyze() and plots the returned dataframe
    :return: None
    """

    # Load the configuration
    config = setup_configuration(args)

    # Set the pair to audit
    pair = args.pair

    if pair is None:
        logger.critical('Parameter --pair mandatory;. E.g --pair ETH/BTC')
        exit()

    if '/' not in pair:
        logger.critical('--pair format must be XXX/YYY')
        exit()


    # Set timerange to use
    timerange = Arguments.parse_timerange(args.timerange)

    # Load the strategy
    try:
        analyze = Analyze(config)
        exchange.init(config)
    except AttributeError:
        logger.critical(
            'Impossible to load the strategy. Please check the file "user_data/strategies/%s.py"',
            args.strategy
        )
        exit()

    # Set the ticker to use
    tick_interval = analyze.get_ticker_interval()

    # Load pair tickers
    tickers = {}
    if args.live:
        logger.info('Downloading pair.')
        tickers[pair] = exchange.get_ticker_history(pair, tick_interval)
    else:
        tickers = optimize.load_data(
            datadir=args.datadir,
            pairs=[pair],
            ticker_interval=tick_interval,
            refresh_pairs=config.get('refresh_pairs', False),
            timerange=timerange
        )

        # No ticker found, or impossible to download
        if tickers == {}:
            exit()

    # Get trades already made from the DB
    trades = []
    if args.db_url:
        engine = create_engine('sqlite:///' + args.db_url)
        persistence.init(_CONF, engine)
        trades = Trade.query.filter(Trade.pair.is_(pair)).all()

    dataframes = analyze.tickerdata_to_dataframe(tickers)
    dataframe = dataframes[pair]
    dataframe = analyze.populate_buy_trend(dataframe)
    dataframe = analyze.populate_sell_trend(dataframe)

    if len(dataframe.index) > 750:
        logger.warning('Ticker contained more than 750 candles, clipping.')

    fig = generate_graph(
        pair=pair,
        trades=trades,
        data=dataframe.tail(750),
        args=args
    )

    plot(fig, filename=os.path.join('user_data', 'freqtrade-plot.html'))


def generate_graph(pair, trades, data, args) -> tools.make_subplots:
    """
    Generate the graph from the data generated by Backtesting or from DB
    :param pair: Pair to Display on the graph
    :param trades: All trades created
    :param data: Dataframe
    :param args: sys.argv that contrains the two params indicators1, and indicators2
    :return: None
    """

    # Define the graph
    fig = tools.make_subplots(
        rows=3,
        cols=1,
        shared_xaxes=True,
        row_width=[1, 1, 4],
        vertical_spacing=0.0001,
    )
    fig['layout'].update(title=pair)
    fig['layout']['yaxis1'].update(title='Price')
    fig['layout']['yaxis2'].update(title='Volume')
    fig['layout']['yaxis3'].update(title='Other')

    # Common information
    candles = go.Candlestick(
        x=data.date,
        open=data.open,
        high=data.high,
        low=data.low,
        close=data.close,
        name='Price'
    )

    df_buy = data[data['buy'] == 1]
    buys = go.Scattergl(
        x=df_buy.date,
        y=df_buy.close,
        mode='markers',
        name='buy',
        marker=dict(
            symbol='triangle-up-dot',
            size=9,
            line=dict(width=1),
            color='green',
        )
    )
    df_sell = data[data['sell'] == 1]
    sells = go.Scattergl(
        x=df_sell.date,
        y=df_sell.close,
        mode='markers',
        name='sell',
        marker=dict(
            symbol='triangle-down-dot',
            size=9,
            line=dict(width=1),
            color='red',
        )
    )

    trade_buys = go.Scattergl(
        x=[t.open_date.isoformat() for t in trades],
        y=[t.open_rate for t in trades],
        mode='markers',
        name='trade_buy',
        marker=dict(
            symbol='square-open',
            size=11,
            line=dict(width=2),
            color='green'
        )
    )
    trade_sells = go.Scattergl(
        x=[t.close_date.isoformat() for t in trades],
        y=[t.close_rate for t in trades],
        mode='markers',
        name='trade_sell',
        marker=dict(
            symbol='square-open',
            size=11,
            line=dict(width=2),
            color='red'
        )
    )

    # Row 1
    fig.append_trace(candles, 1, 1)

    if 'bb_lowerband' in data and 'bb_upperband' in data:
        bb_lower = go.Scatter(
            x=data.date,
            y=data.bb_lowerband,
            name='BB lower',
            line={'color': "transparent"},
        )
        bb_upper = go.Scatter(
            x=data.date,
            y=data.bb_upperband,
            name='BB upper',
            fill="tonexty",
            fillcolor="rgba(0,176,246,0.2)",
            line={'color': "transparent"},
        )
        fig.append_trace(bb_lower, 1, 1)
        fig.append_trace(bb_upper, 1, 1)

    fig = generate_row(fig=fig, row=1, raw_indicators=args.indicators1, data=data)
    fig.append_trace(buys, 1, 1)
    fig.append_trace(sells, 1, 1)
    fig.append_trace(trade_buys, 1, 1)
    fig.append_trace(trade_sells, 1, 1)

    # Row 2
    volume = go.Bar(
        x=data['date'],
        y=data['volume'],
        name='Volume'
    )
    fig.append_trace(volume, 2, 1)

    # Row 3
    fig = generate_row(fig=fig, row=3, raw_indicators=args.indicators2, data=data)

    return fig


def generate_row(fig, row, raw_indicators, data) -> tools.make_subplots:
    """
    Generator all the indicator selected by the user for a specific row
    """
    for indicator in raw_indicators.split(','):
        if indicator in data:
            scattergl = go.Scattergl(
                x=data['date'],
                y=data[indicator],
                name=indicator
            )
            fig.append_trace(scattergl, row, 1)
        else:
            logger.info(
                'Indicator "%s" ignored. Reason: This indicator is not found '
                'in your strategy.',
                indicator
            )

    return fig


def plot_parse_args(args: List[str]) -> Namespace:
    """
    Parse args passed to the script
    :param args: Cli arguments
    :return: args: Array with all arguments
    """
    arguments = Arguments(args, 'Graph dataframe')
    arguments.scripts_options()
    arguments.parser.add_argument(
        '--indicators1',
        help='Set indicators from your strategy you want in the first row of the graph. Separate '
             'them with a coma. E.g: ema3,ema5 (default: %(default)s)',
        type=str,
        default='sma,ema3,ema5',
        dest='indicators1',
    )

    arguments.parser.add_argument(
        '--indicators2',
        help='Set indicators from your strategy you want in the third row of the graph. Separate '
             'them with a coma. E.g: fastd,fastk (default: %(default)s)',
        type=str,
        default='macd',
        dest='indicators2',
    )

    arguments.common_args_parser()
    arguments.optimizer_shared_options(arguments.parser)
    arguments.backtesting_options(arguments.parser)

    return arguments.parse_args()


def main(sysargv: List[str]) -> None:
    """
    This function will initiate the bot and start the trading loop.
    :return: None
    """
    logger.info('Starting Plot Dataframe')
    plot_analyzed_dataframe(
        plot_parse_args(sysargv)
    )


if __name__ == '__main__':
    main(sys.argv[1:])
