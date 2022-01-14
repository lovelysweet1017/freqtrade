""" Binance exchange subclass """
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import arrow
import ccxt

from freqtrade.enums import CandleType, Collateral, TradingMode
from freqtrade.exceptions import (DDosProtection, InsufficientFundsError, InvalidOrderException,
                                  OperationalException, TemporaryError)
from freqtrade.exchange import Exchange
from freqtrade.exchange.common import retrier


logger = logging.getLogger(__name__)


class Binance(Exchange):

    _ft_has: Dict = {
        "stoploss_on_exchange": True,
        "order_time_in_force": ['gtc', 'fok', 'ioc'],
        "time_in_force_parameter": "timeInForce",
        "ohlcv_candle_limit": 1000,
        "trades_pagination": "id",
        "trades_pagination_arg": "fromId",
        "l2_limit_range": [5, 10, 20, 50, 100, 500, 1000],
        "ccxt_futures_name": "future"
    }

    _supported_trading_mode_collateral_pairs: List[Tuple[TradingMode, Collateral]] = [
        # TradingMode.SPOT always supported and not required in this list
        # (TradingMode.MARGIN, Collateral.CROSS),
        # (TradingMode.FUTURES, Collateral.CROSS),
        (TradingMode.FUTURES, Collateral.ISOLATED)
    ]

    def stoploss_adjust(self, stop_loss: float, order: Dict, side: str) -> bool:
        """
        Verify stop_loss against stoploss-order value (limit or price)
        Returns True if adjustment is necessary.
        :param side: "buy" or "sell"
        """

        return order['type'] == 'stop_loss_limit' and (
            (side == "sell" and stop_loss > float(order['info']['stopPrice'])) or
            (side == "buy" and stop_loss < float(order['info']['stopPrice']))
        )

    @retrier(retries=0)
    def stoploss(self, pair: str, amount: float, stop_price: float,
                 order_types: Dict, side: str, leverage: float) -> Dict:
        """
        creates a stoploss limit order.
        this stoploss-limit is binance-specific.
        It may work with a limited number of other exchanges, but this has not been tested yet.
        :param side: "buy" or "sell"
        """
        # Limit price threshold: As limit price should always be below stop-price
        limit_price_pct = order_types.get('stoploss_on_exchange_limit_ratio', 0.99)
        if side == "sell":
            # TODO: Name limit_rate in other exchange subclasses
            rate = stop_price * limit_price_pct
        else:
            rate = stop_price * (2 - limit_price_pct)

        ordertype = "stop_loss_limit"

        stop_price = self.price_to_precision(pair, stop_price)

        bad_stop_price = (stop_price <= rate) if side == "sell" else (stop_price >= rate)

        # Ensure rate is less than stop price
        if bad_stop_price:
            raise OperationalException(
                'In stoploss limit order, stop price should be better than limit price')

        if self._config['dry_run']:
            dry_order = self.create_dry_run_order(
                pair, ordertype, side, amount, stop_price, leverage)
            return dry_order

        try:
            params = self._params.copy()
            params.update({'stopPrice': stop_price})

            amount = self.amount_to_precision(pair, amount)

            rate = self.price_to_precision(pair, rate)

            self._lev_prep(pair, leverage)
            order = self._api.create_order(symbol=pair, type=ordertype, side=side,
                                           amount=amount, price=rate, params=params)
            logger.info('stoploss limit order added for %s. '
                        'stop price: %s. limit: %s', pair, stop_price, rate)
            self._log_exchange_response('create_stoploss_order', order)
            return order
        except ccxt.InsufficientFunds as e:
            raise InsufficientFundsError(
                f'Insufficient funds to create {ordertype} {side} order on market {pair}. '
                f'Tried to {side} amount {amount} at rate {rate}. '
                f'Message: {e}') from e
        except ccxt.InvalidOrder as e:
            # Errors:
            # `binance Order would trigger immediately.`
            raise InvalidOrderException(
                f'Could not create {ordertype} {side} order on market {pair}. '
                f'Tried to {side} amount {amount} at rate {rate}. '
                f'Message: {e}') from e
        except ccxt.DDoSProtection as e:
            raise DDosProtection(e) from e
        except (ccxt.NetworkError, ccxt.ExchangeError) as e:
            raise TemporaryError(
                f'Could not place {side} order due to {e.__class__.__name__}. Message: {e}') from e
        except ccxt.BaseError as e:
            raise OperationalException(e) from e

    @retrier
    def fill_leverage_brackets(self):
        """
        Assigns property _leverage_brackets to a dictionary of information about the leverage
        allowed on each pair
        """
        if self.trading_mode == TradingMode.FUTURES:
            try:
                if self._config['dry_run']:
                    leverage_brackets_path = (
                        Path(__file__).parent / 'binance_leverage_brackets.json'
                    )
                    with open(leverage_brackets_path) as json_file:
                        leverage_brackets = json.load(json_file)
                else:
                    leverage_brackets = self._api.load_leverage_brackets()

                for pair, brkts in leverage_brackets.items():
                    [amt, old_ratio] = [None, None]
                    brackets = []
                    for [notional_floor, mm_ratio] in brkts:
                        amt = (
                            (
                                (float(notional_floor) * (float(mm_ratio)) - float(old_ratio))
                            ) + amt
                        ) if old_ratio else 0
                        old_ratio = mm_ratio
                        brackets.append([
                            float(notional_floor),
                            float(mm_ratio),
                            amt,
                        ])
                    self._leverage_brackets[pair] = brackets
            except ccxt.DDoSProtection as e:
                raise DDosProtection(e) from e
            except (ccxt.NetworkError, ccxt.ExchangeError) as e:
                raise TemporaryError(f'Could not fetch leverage amounts due to'
                                     f'{e.__class__.__name__}. Message: {e}') from e
            except ccxt.BaseError as e:
                raise OperationalException(e) from e

    def get_max_leverage(self, pair: Optional[str], nominal_value: Optional[float]) -> float:
        """
        Returns the maximum leverage that a pair can be traded at
        :param pair: The base/quote currency pair being traded
        :nominal_value: The total value of the trade in quote currency (collateral + debt)
        """
        if pair not in self._leverage_brackets:
            return 1.0
        pair_brackets = self._leverage_brackets[pair]
        for [notional_floor, mm_ratio, _] in reversed(pair_brackets):
            if nominal_value >= notional_floor:
                return 1/mm_ratio
        return 1.0

    @retrier
    def _set_leverage(
        self,
        leverage: float,
        pair: Optional[str] = None,
        trading_mode: Optional[TradingMode] = None
    ):
        """
        Set's the leverage before making a trade, in order to not
        have the same leverage on every trade
        """
        trading_mode = trading_mode or self.trading_mode

        if self._config['dry_run'] or trading_mode != TradingMode.FUTURES:
            return

        try:
            self._api.set_leverage(symbol=pair, leverage=leverage)
        except ccxt.DDoSProtection as e:
            raise DDosProtection(e) from e
        except (ccxt.NetworkError, ccxt.ExchangeError) as e:
            raise TemporaryError(
                f'Could not set leverage due to {e.__class__.__name__}. Message: {e}') from e
        except ccxt.BaseError as e:
            raise OperationalException(e) from e

    async def _async_get_historic_ohlcv(self, pair: str, timeframe: str,
                                        since_ms: int, candle_type: CandleType,
                                        is_new_pair: bool = False, raise_: bool = False,
                                        ) -> Tuple[str, str, str, List]:
        """
        Overwrite to introduce "fast new pair" functionality by detecting the pair's listing date
        Does not work for other exchanges, which don't return the earliest data when called with "0"
        :param candle_type: Any of the enum CandleType (must match trading mode!)
        """
        if is_new_pair:
            x = await self._async_get_candle_history(pair, timeframe, candle_type, 0)
            if x and x[3] and x[3][0] and x[3][0][0] > since_ms:
                # Set starting date to first available candle.
                since_ms = x[3][0][0]
                logger.info(f"Candle-data for {pair} available starting with "
                            f"{arrow.get(since_ms // 1000).isoformat()}.")

        return await super()._async_get_historic_ohlcv(
            pair=pair,
            timeframe=timeframe,
            since_ms=since_ms,
            is_new_pair=is_new_pair,
            raise_=raise_,
            candle_type=candle_type
        )

    def funding_fee_cutoff(self, open_date: datetime):
        """
        :param open_date: The open date for a trade
        :return: The cutoff open time for when a funding fee is charged
        """
        return open_date.minute > 0 or (open_date.minute == 0 and open_date.second > 15)

    def get_maintenance_ratio_and_amt(
        self,
        pair: str,
        nominal_value: Optional[float] = 0.0,
    ):
        """
        Maintenance amt = Floor of Position Bracket on Level n *
          difference between
              Maintenance Margin Rate on Level n and
              Maintenance Margin Rate on Level n-1)
          + Maintenance Amount on Level n-1
          https://www.binance.com/en/support/faq/b3c689c1f50a44cabb3a84e663b81d93
        """
        if pair not in self._leverage_brackets:
            raise InvalidOrderException(f"Cannot calculate liquidation price for {pair}")
        pair_brackets = self._leverage_brackets[pair]
        for [notional_floor, mm_ratio, amt] in reversed(pair_brackets):
            if nominal_value >= notional_floor:
                return (mm_ratio, amt)
        raise OperationalException("nominal value can not be lower than 0")
        # The lowest notional_floor for any pair in loadLeverageBrackets is always 0 because it
        # describes the min amount for a bracket, and the lowest bracket will always go down to 0

    def liquidation_price_helper(
        self,
        open_rate: float,   # Entry price of position
        is_short: bool,
        leverage: float,
        trading_mode: TradingMode,
        mm_ratio: float,
        collateral: Collateral,
        maintenance_amt: Optional[float] = None,  # (Binance)
        position: Optional[float] = None,  # (Binance and Gateio) Absolute value of position size
        wallet_balance: Optional[float] = None,  # (Binance and Gateio)
        taker_fee_rate: Optional[float] = None,  # (Gateio & Okex)
        liability: Optional[float] = None,  # (Okex)
        interest: Optional[float] = None,  # (Okex)
        position_assets: Optional[float] = None,  # * (Okex) Might be same as position
        mm_ex_1: Optional[float] = 0.0,  # (Binance) Cross only
        upnl_ex_1: Optional[float] = 0.0,  # (Binance) Cross only
    ) -> Optional[float]:
        """
        MARGIN: https://www.binance.com/en/support/faq/f6b010588e55413aa58b7d63ee0125ed
        PERPETUAL: https://www.binance.com/en/support/faq/b3c689c1f50a44cabb3a84e663b81d93

        :param exchange_name:
        :param open_rate: (EP1) Entry price of position
        :param is_short: True if the trade is a short, false otherwise
        :param leverage: The amount of leverage on the trade
        :param trading_mode: SPOT, MARGIN, FUTURES, etc.
        :param position: Absolute value of position size (in base currency)
        :param mm_ratio: (MMR)
            # Binance's formula specifies maintenance margin rate which is mm_ratio * 100%
        :param collateral: Either ISOLATED or CROSS
        :param maintenance_amt: (CUM) Maintenance Amount of position
        :param wallet_balance: (WB)
            Cross-Margin Mode: crossWalletBalance
            Isolated-Margin Mode: isolatedWalletBalance
        :param position: Absolute value of position size (in base currency)

        # * Not required by Binance
        :param taker_fee_rate:
        :param liability:
        :param interest:
        :param position_assets:

        # * Only required for Cross
        :param mm_ex_1: (TMM)
            Cross-Margin Mode: Maintenance Margin of all other contracts, excluding Contract 1
            Isolated-Margin Mode: 0
        :param upnl_ex_1: (UPNL)
            Cross-Margin Mode: Unrealized PNL of all other contracts, excluding Contract 1.
            Isolated-Margin Mode: 0
        """
        if trading_mode == TradingMode.SPOT:
            return None

        if not collateral:
            raise OperationalException(
                "Parameter collateral is required by liquidation_price when trading_mode is "
                f"{trading_mode}"
            )
        if (
            (wallet_balance is None or maintenance_amt is None or position is None) or
            (collateral == Collateral.CROSS and (mm_ex_1 is None or upnl_ex_1 is None))
        ):
            required_params = "wallet_balance, maintenance_amt, position"
            if collateral == Collateral.CROSS:
                required_params += ", mm_ex_1, upnl_ex_1"
            raise OperationalException(
                f"Parameters {required_params} are required by Binance.liquidation_price"
                f"for {collateral.name} {trading_mode.name}"
            )

        side_1 = -1 if is_short else 1
        position = abs(position)
        cross_vars = upnl_ex_1 - mm_ex_1 if collateral == Collateral.CROSS else 0.0  # type: ignore

        if trading_mode == TradingMode.FUTURES:
            return (
                (
                    (wallet_balance + cross_vars + maintenance_amt) -
                    (side_1 * position * open_rate)
                ) / (
                    (position * mm_ratio) - (side_1 * position)
                )
            )

        raise OperationalException(
            f"Binance does not support {collateral.value} Mode {trading_mode.value} trading ")
