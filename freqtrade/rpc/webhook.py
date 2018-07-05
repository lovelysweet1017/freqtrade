"""
This module manages webhook communication
"""
import logging
from typing import Any,  Dict

from requests import post, RequestException

from freqtrade.rpc import RPC, RPCMessageType


logger = logging.getLogger(__name__)

logger.debug('Included module rpc.webhook ...')


class Webhook(RPC):
    """  This class handles all webhook communication """

    def __init__(self, freqtrade) -> None:
        """
        Init the Webhook class, and init the super class RPC
        :param freqtrade: Instance of a freqtrade bot
        :return: None
        """
        super().__init__(freqtrade)

        self._config = freqtrade.config

    def cleanup(self) -> None:
        """
        Cleanup pending module resources.
        This will do nothing for webhooks, they will simply not be called anymore
        """
        pass

    def send_msg(self, msg: Dict[str, Any]) -> None:
        """ Send a message to telegram channel """
        try:

            if msg['type'] == RPCMessageType.BUY_NOTIFICATION:
                valuedict = self._config['webhook'].get('webhookbuy', None)
            elif msg['type'] == RPCMessageType.SELL_NOTIFICATION:
                valuedict = self._config['webhook'].get('webhooksell', None)
            elif msg['type'] == RPCMessageType.STATUS_NOTIFICATION:
                valuedict = self._config['webhook'].get('webhookstatus', None)
            else:
                raise NotImplementedError('Unknown message type: {}'.format(msg['type']))
            if not valuedict:
                logger.info("Message type %s not configured for webhooks", msg['type'])
                return

            payload = {"value1": valuedict.get('value1', '').format(**msg),
                       "value2": valuedict.get('value2', '').format(**msg),
                       "value3": valuedict.get('value3', '').format(**msg)
                       }

            self._send_msg(payload)
        except KeyError as exc:
            logger.exception("Problem calling Webhook. Please check your webhook configuration. "
                             "Exception: %s", exc)

    def _send_msg(self, payload: dict) -> None:
        """does the actual call to the webhook"""

        try:
            url = self._config['webhook']['url']
            post(url, data=payload)
        except RequestException as exc:
            logger.warning("Could not call webhook url. Exception: %s", exc)
