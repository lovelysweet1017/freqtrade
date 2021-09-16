""" Binance exchange subclass """
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

import arrow
import ccxt

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
    }
    funding_fee_times: List[int] = [0, 8, 16]  # hours of the day
    _funding_interest_rates: Dict = {}  # TODO-lev: delete

    def __init__(self, config: Dict[str, Any], validate: bool = True) -> None:
        super().__init__(config, validate)
        # TODO-lev: Uncomment once lev-exchange merged in
        # if self.trading_mode == TradingMode.FUTURES:
        # self._funding_interest_rates = self._get_funding_interest_rates()

    def stoploss_adjust(self, stop_loss: float, order: Dict) -> bool:
        """
        Verify stop_loss against stoploss-order value (limit or price)
        Returns True if adjustment is necessary.
        """
        return order['type'] == 'stop_loss_limit' and stop_loss > float(order['info']['stopPrice'])

    @retrier(retries=0)
    def stoploss(self, pair: str, amount: float, stop_price: float, order_types: Dict) -> Dict:
        """
        creates a stoploss limit order.
        this stoploss-limit is binance-specific.
        It may work with a limited number of other exchanges, but this has not been tested yet.
        """
        # Limit price threshold: As limit price should always be below stop-price
        limit_price_pct = order_types.get('stoploss_on_exchange_limit_ratio', 0.99)
        rate = stop_price * limit_price_pct

        ordertype = "stop_loss_limit"

        stop_price = self.price_to_precision(pair, stop_price)

        # Ensure rate is less than stop price
        if stop_price <= rate:
            raise OperationalException(
                'In stoploss limit order, stop price should be more than limit price')

        if self._config['dry_run']:
            dry_order = self.create_dry_run_order(
                pair, ordertype, "sell", amount, stop_price)
            return dry_order

        try:
            params = self._params.copy()
            params.update({'stopPrice': stop_price})

            amount = self.amount_to_precision(pair, amount)

            rate = self.price_to_precision(pair, rate)

            order = self._api.create_order(symbol=pair, type=ordertype, side='sell',
                                           amount=amount, price=rate, params=params)
            logger.info('stoploss limit order added for %s. '
                        'stop price: %s. limit: %s', pair, stop_price, rate)
            self._log_exchange_response('create_stoploss_order', order)
            return order
        except ccxt.InsufficientFunds as e:
            raise InsufficientFundsError(
                f'Insufficient funds to create {ordertype} sell order on market {pair}. '
                f'Tried to sell amount {amount} at rate {rate}. '
                f'Message: {e}') from e
        except ccxt.InvalidOrder as e:
            # Errors:
            # `binance Order would trigger immediately.`
            raise InvalidOrderException(
                f'Could not create {ordertype} sell order on market {pair}. '
                f'Tried to sell amount {amount} at rate {rate}. '
                f'Message: {e}') from e
        except ccxt.DDoSProtection as e:
            raise DDosProtection(e) from e
        except (ccxt.NetworkError, ccxt.ExchangeError) as e:
            raise TemporaryError(
                f'Could not place sell order due to {e.__class__.__name__}. Message: {e}') from e
        except ccxt.BaseError as e:
            raise OperationalException(e) from e

    def _get_premium_index(self, pair: str, date: datetime) -> float:
        raise OperationalException(f'_get_premium_index has not been implemented on {self.name}')

    def _get_mark_price(self, pair: str, date: datetime) -> float:
        raise OperationalException(f'_get_mark_price has not been implemented on {self.name}')

    def _get_funding_interest_rates(self):
        rates = self._api.fetch_funding_rates()
        interest_rates = {}
        for pair, data in rates.items():
            interest_rates[pair] = data['interestRate']
        return interest_rates

    def _calculate_funding_rate(self, pair: str, premium_index: float) -> Optional[float]:
        """
            Get's the funding_rate for a pair at a specific date and time in the past
        """
        return (
            premium_index +
            max(min(self._funding_interest_rates[pair] - premium_index, 0.0005), -0.0005)
        )

    def _get_funding_fee(
        self,
        pair: str,
        contract_size: float,
        mark_price: float,
        premium_index: Optional[float],
    ) -> float:
        """
            Calculates a single funding fee
            :param contract_size: The amount/quanity
            :param mark_price: The price of the asset that the contract is based off of
            :param funding_rate: the interest rate and the premium
                - interest rate: 0.03% daily, BNBUSDT, LINKUSDT, and LTCUSDT are 0%
                - premium: varies by price difference between the perpetual contract and mark price
        """
        if premium_index is None:
            raise OperationalException("Premium index cannot be None for Binance._get_funding_fee")
        nominal_value = mark_price * contract_size
        funding_rate = self._calculate_funding_rate(pair, premium_index)
        if funding_rate is None:
            raise OperationalException("Funding rate should never be none on Binance")
        return nominal_value * funding_rate

    async def _async_get_historic_ohlcv(self, pair: str, timeframe: str,
                                        since_ms: int, is_new_pair: bool
                                        ) -> List:
        """
        Overwrite to introduce "fast new pair" functionality by detecting the pair's listing date
        Does not work for other exchanges, which don't return the earliest data when called with "0"
        """
        if is_new_pair:
            x = await self._async_get_candle_history(pair, timeframe, 0)
            if x and x[2] and x[2][0] and x[2][0][0] > since_ms:
                # Set starting date to first available candle.
                since_ms = x[2][0][0]
                logger.info(f"Candle-data for {pair} available starting with "
                            f"{arrow.get(since_ms // 1000).isoformat()}.")
        return await super()._async_get_historic_ohlcv(
            pair=pair, timeframe=timeframe, since_ms=since_ms, is_new_pair=is_new_pair)
