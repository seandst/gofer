#
# Copyright (c) 2011 Red Hat, Inc.
#
# This software is licensed to you under the GNU Lesser General Public
# License as published by the Free Software Foundation; either version
# 2 of the License (LGPLv2) or (at your option) any later version.
# There is NO WARRANTY for this software, express or implied,
# including the implied warranties of MERCHANTABILITY,
# NON-INFRINGEMENT, or FITNESS FOR A PARTICULAR PURPOSE. You should
# have received a copy of LGPLv2 along with this software; if not, see
# http://www.gnu.org/licenses/old-licenses/lgpl-2.0.txt.
#
# Jeff Ortel <jortel@redhat.com>
#

"""
Contains request delivery policies.
"""

from gofer.messaging import Queue, Producer, Reader
from gofer.messaging.model import Envelope, getuuid
from gofer.rmi.dispatcher import *
from gofer.metrics import Timer
from logging import getLogger


log = getLogger(__name__)


# --- utils ------------------------------------------------------------------


def timeout(options, none=(None,None)):
    """
    Extract (and default as necessary) the timeout option.
    :param options: Policy options.
    :type options: dict
    :return: The timeout (<start>,<duration>)
    :rtype: tuple
    """
    tm = options.timeout
    if tm is None:
        return none
    if isinstance(tm, (list,tuple)):
        timeout = Timeout(*tm)
    else:
        timeout = Timeout(tm, tm)
    return timeout.tuple()


class Timeout:
    """
    Policy timeout.
    :cvar MINUTE: Minutes in seconds.
    :cvar HOUR: Hour is seconds
    :cvar DAY: Day in seconds
    :cvar SUFFIX: Suffix to multiplier mapping.
    """

    SECOND = 1
    MINUTE = 60
    HOUR = (MINUTE * 60)
    DAY = (HOUR * 24)

    SUFFIX = {
        's' : SECOND,
        'm' : MINUTE,
        'h' : HOUR,
        'd' : DAY,
    }

    @classmethod
    def seconds(cls, tm):
        """
        Convert tm to seconds based on suffix.
        :param tm: A timeout value.
            The string value may have a suffix of:
              (s) = seconds
              (m) = minutes
              (h) = hours
              (d) = days
        :type tm: (None|int|float|str)

        """
        if tm is None:
            return tm
        if isinstance(tm, int):
            return tm
        if isinstance(tm, float):
            return int(tm)
        if not isinstance(tm, (basestring)):
            raise TypeError(tm)
        if not len(tm):
            raise ValueError(tm)
        if cls.has_suffix(tm):
            multiplier = cls.SUFFIX[tm[-1]]
            return (multiplier * int(tm[:-1]))
        else:
            return int(tm)

    @classmethod
    def has_suffix(cls, tm):
        for k in cls.SUFFIX.keys():
            if tm.endswith(k):
                return True
        return False

    def __init__(self, start=None, duration=None):
        self.start = self.seconds(start)
        self.duration = self.seconds(duration)

    def tuple(self):
        return (self.start, self.duration)

#
# Exceptions
#

class RequestTimeout(Exception):
    """
    Request timeout.
    """

    def __init__(self, sn, index):
        """
        :param sn: The request serial number.
        :type sn: str
        """
        Exception.__init__(self, sn, index)
        
    def sn(self):
        return self.args[0]
    
    def index(self):
        return self.args[1]
        

#
# Policy
# 

class RequestMethod:
    """
    Base class for request methods.
    :ivar url: The agent URL.
    :type url: str
    """
    
    def __init__(self, url):
        """
        :param url: The agent URL.
        :type url: str
        """
        self.url = url

    def send(self, destination, request, **any):
        """
        Send the request..
        :param destination: The destination AMQP queue.
        :type destination: gofer.transport.model.Destination
        :param request: A request to send.
        :type request: object
        :keyword any: Any (extra) data.
        """
        pass

    def broadcast(self, addresses, request, **any):
        """
        Broadcast the request.
        :param addresses: A list of destination AMQP queues.
        :type addresses: [gofer.transport.node.Destination,..]
        :param request: A request to send.
        :type request: object
        :keyword any: Any (extra) data.
        """
        pass


class Synchronous(RequestMethod):
    """
    The synchronous request method.
    This method blocks until a reply is received.
    :ivar queue: An AMQP queue.
    :type queue: gofer.transport.model.Queue
    """
    
    TIMEOUT = (10, 90)

    def __init__(self, url, options):
        """
        :param url: The agent URL.
        :type url: str
        :param options: Policy options.
        :type options: dict
        """
        RequestMethod.__init__(self, url)
        self.timeout = timeout(options, self.TIMEOUT)
        self.progress = options.progress
        self.queue = Queue(getuuid(), url=url)
        self.queue.auto_delete = True
        self.queue.declare(self.url)

    def send(self, destination, request, **any):
        """
        Send the request then read the reply.
        :param destination: The destination AMQP queue.
        :type destination: gofer.transport.model.Destination
        :param request: A request to send.
        :type request: object
        :keyword any: Any (extra) data.
        :return: The result of the request.
        :rtype: object
        :raise Exception: returned by the peer.
        """
        replyto = self.queue.destination()
        producer = Producer(url=self.url)
        try:
            sn = producer.send(
                destination,
                ttl=self.timeout[0],
                replyto=replyto.dict(),
                request=request,
                **any)
        finally:
            producer.close()
        log.debug('sent (%s):\n%s', repr(destination), request)
        reader = Reader(self.queue, url=self.url)
        try:
            self.__get_started(sn, reader)
            return self.__get_reply(sn, reader)
        finally:
            reader.close()

    def __get_started(self, sn, reader):
        """
        Get the STARTED reply matched by serial number.
        :param sn: The request serial number.
        :type sn: str
        :param reader: A reader.
        :type reader: Reader
        :return: The matched reply envelope.
        :rtype: Envelope
        """
        envelope = reader.search(sn, self.timeout[0])
        if envelope:
            if envelope.status == 'started':
                log.debug('request (%s), started', sn)
            else:
                self.__on_reply(envelope)
        else:
            raise RequestTimeout(sn, 0)

    def __get_reply(self, sn, reader):
        """
        Get the reply matched by serial number.
        :param sn: The request serial number.
        :type sn: str
        :param reader: A reader.
        :type reader: Reader
        :return: The matched reply envelope.
        :rtype: Envelope
        """
        timer = Timer()
        timeout = float(self.timeout[1])
        while True:
            timer.start()
            envelope = reader.search(sn, int(timeout))
            timer.stop()
            elapsed = timer.duration()
            if elapsed > timeout:
                raise RequestTimeout(sn, 1)
            else:
                timeout -= elapsed
            if envelope:
                if envelope.status == 'progress':
                    self.__on_progress(envelope)
                else:
                    return self.__on_reply(envelope)
            else:
                raise RequestTimeout(sn, 1)
        
    def __on_reply(self, envelope):
        """
        Handle the reply.
        :param envelope: The reply envelope.
        :type envelope: Envelope
        :return: The matched reply envelope.
        :rtype: Envelope
        """
        reply = Return(envelope.result)
        if reply.succeeded():
            return reply.retval
        else:
            raise RemoteException.instance(reply)
        
    def __on_progress(self, envelope):
        """
        Handle the progress report.
        :param envelope: The status envelope.
        :type envelope: Envelope
        """
        try:
            callback = self.progress
            if callable(callback):
                report = dict(
                    sn=envelope.sn,
                    any=envelope.any,
                    total=envelope.total,
                    completed=envelope.completed,
                    details=envelope.details)
                callback(report)
        except:
            log.error('progress callback failed', exc_info=1)


class Asynchronous(RequestMethod):
    """
    The asynchronous request method.
    """

    def __init__(self, url, options):
        """
        :param url: The agent URL.
        :type url: str
        :param options: Policy options.
        :type options: dict
        """
        RequestMethod.__init__(self, url)
        self.ctag = options.ctag
        self.timeout = timeout(options)
        self.trigger = options.trigger
        self.watchdog = options.watchdog

    def send(self, destination, request, **any):
        """
        Send the specified request and redirect the reply to the
        queue for the specified reply I{correlation} tag.
        A trigger(1) specifies a I{manual} trigger.
        :param destination: The destination AMQP queue.
        :type destination: gofer.transport.model.Destination
        :param request: A request to send.
        :type request: object
        :keyword any: Any (extra) data.
        :return: The request serial number.
        :rtype: str
        """
        trigger = Trigger(self, destination, request, any)
        if self.trigger == 1:
            return trigger
        trigger()
        return trigger.sn

    def broadcast(self, destinations, request, **any):
        """
        Send the specified request and redirect the reply to the
        queue for the specified reply I{correlation} tag.
        A trigger(1) specifies a I{manual} trigger.
        :param destinations: A list of destinations.
        :type destinations: [gofer.transport.model.Destination,..]
        :param request: A request to send.
        :type request: object
        :keyword any: Any (extra) data.
        """
        triggers = []
        for destination in destinations:
            t = Trigger(self, destination, request, any)
            triggers.append(t)
        if self.trigger == 1:
            return triggers
        for trigger in triggers:
            trigger()
        return [t.sn for t in triggers]

    def replyto(self):
        """
        Get replyto based on the correlation I{tag}.
        :return: The replyto AMQP address.
        :rtype: str
        """
        if self.ctag:
            queue = Queue(self.ctag, url=self.url)
            replyto = queue.destination()
            return replyto.dict()
        else:
            return None

    def notifywatchdog(self, sn, replyto, any):
        """
        Add the request to the I{watchdog} for tacking.
        :param sn: A serial number.
        :type sn: str
        :param replyto: An AMQP address.
        :type replyto: str
        :param any: User defined data.
        :type any: any
        """
        any = Envelope(any)
        if replyto and \
           self.ctag and \
           self.timeout[0] is not None and \
           self.timeout[1] is not None and \
           self.watchdog is not None:
            self.watchdog.track(
                sn, 
                replyto,
                any.any,
                self.timeout)


class Trigger:
    """
    Asynchronous trigger.
    :ivar __pending: pending flag.
    :type __pending: bool
    :ivar __sn: serial number
    :type __sn: str
    :ivar __policy: The policy object.
    :type __policy: Asynchronous
    :ivar __destination: The AMQP queue.
    :type __destination: gofer.transport.model.Destination
    :ivar __request: A request to send.
    :type __request: object
    :ivar __any: Any (extra) data.
    :type __any: dict
    """

    def __init__(self, policy, destination, request, any):
        """
        :param policy: The policy object.
        :type policy: Asynchronous
        :param destination: The AMQP queue.
        :type destination: gofer.transport.model.Destination
        :param request: A request to send.
        :type request: object
        :keyword any: Any (extra) data.
        """
        self.__pending = True
        self.__sn = getuuid()
        self.__policy = policy
        self.__destination = destination
        self.__request = request
        self.__any = any
        
    @property
    def sn(self):
        """
        Get serial number.
        :return: The request serial number.
        :rtype: str
        """
        return self.__sn
        
    def __send(self):
        """
        Send the request using the specified policy
        object and generated serial number.
        """
        policy = self.__policy
        destination = self.__destination
        replyto = policy.replyto()
        request = self.__request
        any = self.__any
        producer = Producer(url=policy.url)
        try:
            producer.send(
                destination,
                sn=self.__sn,
                ttl=policy.timeout[0],
                replyto=replyto,
                request=request,
                **any)
        finally:
            producer.close()
        log.debug('sent (%s):\n%s', repr(destination), request)
        policy.notifywatchdog(self.__sn, replyto, any)
    
    def __str__(self):
        return self.__sn
    
    def __call__(self):
        if self.__pending:
            self.__send()
            self.__pending = False
        else:
            raise Exception('trigger already executed')
