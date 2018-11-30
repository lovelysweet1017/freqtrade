"""
Static List provider

Provides lists as configured in config.json

 """
import logging
from typing import List
from cachetools import TTLCache, cached

from freqtrade.pairlist.StaticPairList import StaticPairList
from freqtrade import OperationalException
logger = logging.getLogger(__name__)


class VolumePairList(StaticPairList):

    def __init__(self, freqtrade, config: dict) -> None:
        self._freqtrade = freqtrade
        self._config = config
        self._whitelist = self._config['exchange']['pair_whitelist']
        self._blacklist = self._config['exchange'].get('pair_blacklist', [])
        self._number_pairs = self._config.get('dynamic_whitelist', None)
        if not self._freqtrade.exchange.exchange_has('fetchTickers'):
            raise OperationalException(
                'Exchange does not support dynamic whitelist.'
                'Please edit your config and restart the bot'
            )
        # self.refresh_whitelist()

    @property
    def whitelist(self) -> List[str]:
        """ Contains the current whitelist """
        return self._whitelist

    @property
    def blacklist(self) -> List[str]:
        return self._blacklist

    def refresh_whitelist(self) -> None:
        """
        Refreshes whitelist and assigns it to self._whitelist
        """
        # Generate dynamic whitelist
        pairs = self._gen_pair_whitelist(self._config['stake_currency'])
        # Validate whitelist to only have active market pairs
        self._whitelist = self._validate_whitelist(pairs)[:self._number_pairs]

    @cached(TTLCache(maxsize=1, ttl=1800))
    def _gen_pair_whitelist(self, base_currency: str, key: str = 'quoteVolume') -> List[str]:
        """
        Updates the whitelist with with a dynamically generated list
        :param base_currency: base currency as str
        :param key: sort key (defaults to 'quoteVolume')
        :return: List of pairs
        """

        tickers = self._freqtrade.exchange.get_tickers()
        # check length so that we make sure that '/' is actually in the string
        tickers = [v for k, v in tickers.items()
                   if len(k.split('/')) == 2 and k.split('/')[1] == base_currency]

        sorted_tickers = sorted(tickers, reverse=True, key=lambda t: t[key])
        pairs = [s['symbol'] for s in sorted_tickers]
        return pairs

    def _validate_whitelist(self, whitelist: List[str]) -> List[str]:
        """
        Check available markets and remove pair from whitelist if necessary
        :param whitelist: the sorted list (based on BaseVolume) of pairs the user might want to
        trade
        :return: the list of pairs the user wants to trade without the one unavailable or
        black_listed
        """
        sanitized_whitelist = whitelist
        markets = self._freqtrade.exchange.get_markets()

        # Filter to markets in stake currency
        markets = [m for m in markets if m['quote'] == self._config['stake_currency']]
        known_pairs = set()

        for market in markets:
            pair = market['symbol']
            # pair is not int the generated dynamic market, or in the blacklist ... ignore it
            if pair not in whitelist or pair in self.blacklist:
                continue
            # else the pair is valid
            known_pairs.add(pair)
            # Market is not active
            if not market['active']:
                sanitized_whitelist.remove(pair)
                logger.info(
                    'Ignoring %s from whitelist. Market is not active.',
                    pair
                )

        # We need to remove pairs that are unknown
        return [x for x in sanitized_whitelist if x in known_pairs]
