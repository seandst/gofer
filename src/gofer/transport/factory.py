# Copyright (c) 2013 Red Hat, Inc.
#
# This software is licensed to you under the GNU General Public
# License as published by the Free Software Foundation; either version
# 2 of the License (GPLv2) or (at your option) any later version.
# There is NO WARRANTY for this software, express or implied,
# including the implied warranties of MERCHANTABILITY,
# NON-INFRINGEMENT, or FITNESS FOR A PARTICULAR PURPOSE. You should
# have received a copy of GPLv2 along with this software; if not, see
# http://www.gnu.org/licenses/old-licenses/gpl-2.0.txt.

from logging import getLogger

from gofer.transport.broker import URL


log = getLogger(__name__)


# --- constants --------------------------------------------------------------

# the default URL
DEFAULT_URL = 'tcp://localhost:5672'

# the default transport
DEFAULT_TRANSPORT = 'gofer.transport.amqplib'


# symbols required to be provided by all transports
REQUIRED = [
    'Exchange',
    'Broker',
    'Endpoint',
    'Queue',
    'Producer',
    'BinaryProducer',
    'Reader',
]


# --- factory ----------------------------------------------------------------


class Transport:
    """
    The transport API.
    :cvar packages: Transport packages mapped by URL.
    :cvar packages: dict
    """

    packages = {}

    @staticmethod
    def load(package):
        try:
            return __import__(package, {}, {}, REQUIRED)
        except ImportError:
            log.exception(package)
            msg = 'transport: %s - not installed' % package
            raise ImportError(msg)

    @classmethod
    def bind(cls, url=None, package=None):
        """
        Bind a URL to the specified package.
        :param url: The agent/broker URL.
        :type url: str, URL
        :param package: The python package providing the transport.
        :type package: str
        :return: The bound python module.
        """
        if not url:
            url = DEFAULT_URL
        if not isinstance(url, URL):
            url = URL(url)
        if not package:
            package = DEFAULT_TRANSPORT
        if not '.' in package:
            package = '.'.join((__package__, package))
        mod = Transport.load(package)
        cls.packages[url] = mod
        log.info('transport: %s bound to url: %s', mod, url)
        return mod

    def __init__(self, url=None, package=None):
        """
        :param url: The agent/broker URL.
        :type url: str, URL
        :param package: The python package providing the transport.
        :type package: str
        """
        if not url:
            url = DEFAULT_URL
        if not isinstance(url, URL):
            url = URL(url)
        self.url = url
        try:
            self.package = self.packages[url]
        except KeyError:
            self.package = self.bind(url, package)

    def broker(self):
        """
        Get an AMQP broker.
        :return: The broker provided by the transport.
        :rtype: gofer.transport.broker.Broker
        """
        return self.Broker(self.url)

    def exchange(self, name, policy=None):
        """
        Get and AMQP exchange object.
        :param name: The exchange name.
        :type name: str
        :param policy: The routing policy.
        :type policy: str
        :return: The exchange object provided by the transport.
        :rtype: gofer.transport.model.Exchange
        """
        return self.Exchange(name, policy=policy)

    def queue(self, name, exchange=None, routing_key=None):
        """
        Get an AMQP topic queue.
        :param name: The topic name.
        :param name: str
        :param exchange: An AMQP exchange.
        :param exchange: str
        :param routing_key: An AMQP routing key.
        :type routing_key: str
        :return: The queue object provided by the transport.
        :rtype: gofer.transport.node.Queue.
        """
        return self.Queue(name, exchange=exchange, routing_key=routing_key)

    def producer(self, uuid=None):
        """
        Get an AMQP message producer.
        :param uuid: The (optional) producer ID.
        :type uuid: str
        :return: The broker provided by the transport.
        :rtype: gofer.transport.endpoint.Endpoint.
        """
        return self.Producer(uuid, url=self.url)

    def binary_producer(self, uuid=None):
        """
        Get an AMQP binary message producer.
        :param uuid: The (optional) producer ID.
        :type uuid: str
        :return: The producer provided by the transport.
        :rtype: gofer.transport.endpoint.Endpoint.
        """
        return self.BinaryProducer(uuid, url=self.url)

    def reader(self, queue, uuid=None):
        """
        Get an AMQP message reader.
        :param queue: The AMQP node.
        :type queue: gofer.transport.model.Queue
        :param uuid: The (optional) producer ID.
        :type uuid: str
        :return: The reader provided by the transport.
        :rtype: gofer.transport.endpoint.Endpoint.
        """
        return self.Reader(queue, uuid=uuid, url=self.url)

    def __getattr__(self, name):
        return getattr(self.package, name)
