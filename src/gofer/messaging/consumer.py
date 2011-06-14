#
# Copyright (c) 2010 Red Hat, Inc.
#
# This software is licensed to you under the GNU General Public License,
# version 2 (GPLv2). There is NO WARRANTY for this software, express or
# implied, including the implied warranties of MERCHANTABILITY or FITNESS
# FOR A PARTICULAR PURPOSE. You should have received a copy of GPLv2
# along with this software; if not, see
# http://www.gnu.org/licenses/old-licenses/gpl-2.0.txt.
#
# Red Hat trademarks are not licensed under GPLv2. No permission is
# granted to use or replicate Red Hat trademarks that are incorporated
# in this software or its documentation.
#

"""
Provides AMQP message consumer classes.
"""

from time import sleep
from threading import Thread
from gofer.messaging import *
from gofer.messaging.endpoint import Endpoint
from gofer.messaging.producer import Producer
from gofer.messaging.dispatcher import Return
from gofer.messaging.window import *
from gofer.messaging.store import PendingQueue, PendingReceiver
from qpid.messaging import LinkError, Empty
from logging import getLogger

log = getLogger(__name__)


class ReceiverThread(Thread):
    """
    Message consumer thread.
    @cvar WAIT: How long (seconds) to wait for messages.
    @type WAIT: int
    @ivar __run: The main run latch.
    @type __run: bool
    @ivar __consumer: The (target) consumer.
    @type __consumer: L{Consumer}
    """

    WAIT = 3

    def __init__(self, consumer):
        """
        @param consumer: The (target) consumer that is notified
            when messages are fetched.
        @type consumer: L{Consumer}
        """
        self.__run = True
        self.__consumer = consumer
        Thread.__init__(self, name=consumer.id())
        self.setDaemon(True)

    def run(self):
        """
        Thread main().
        Consumer messages and forward to the (target) consumer.
        """
        msg = None
        receiver = self.__open()
        while self.__run:
            try:
                msg = self.__fetch(receiver)
                if msg:
                    self.__consumer.received(msg)
                log.debug('ready')
            except LinkError:
                log.error('aborting', exc_info=1)
                return
            except:
                log.error('failed:\n%s', msg, exc_info=1)
        receiver.close()
        log.info('stopped')
                
    def stop(self):
        """
        Stop the thread.
        """
        self.__run = False

    def __open(self):
        """
        Open the AMQP receiver.
        @return: The opened receiver.
        @rtype: Receiver
        """
        addr = self.__consumer.address()
        ssn = self.__consumer.session()
        log.debug('open %s', addr)
        return ssn.receiver(addr)
        
    def __fetch(self, receiver):
        """
        Fetch the next available message.
        @param receiver: An AMQP receiver.
        @type receiver: Receiver
        """
        try:
            return receiver.fetch(timeout=self.WAIT)
        except Empty:
            # normal
            pass
        except:
            sleep(self.WAIT)
            raise
        

class Consumer(Endpoint):
    """
    An AMQP (abstract) consumer.
    The received() method needs to be overridden.
    @ivar __started: Indicates that start() has been called.
    @type __started: bool
    @ivar __destination: The AMQP destination to consume.
    @type __destination: L{Destination}
    @ivar __thread: The receiver thread.
    @type __thread: L{ReceiverThread}
    """
    
    @classmethod
    def subject(cls, message):
        """
        Extract the message subject.
        @param message: The received message.
        @type message: qpid.messaging.Message
        @return: The message subject
        @rtype: str
        """
        return message.properties.get('qpid.subject')

    def __init__(self, destination, **options):
        """
        @param destination: The destination to consumer.
        @type destination: L{Destination}
        """
        Endpoint.__init__(self, **options)
        self.__started = False
        self.__destination = destination
        self.__thread = ReceiverThread(self)

    def id(self):
        """
        Get the endpoint id
        @return: The destination (simple) address.
        @rtype: str
        """
        self._lock()
        try:
            return repr(self.__destination)
        finally:
            self._unlock()

    def address(self):
        """
        Get the AMQP address for this endpoint.
        @return: The AMQP address.
        @rtype: str
        """
        self._lock()
        try:
            return str(self.__destination)
        finally:
            self._unlock()

    def start(self):
        """
        Start processing messages on the queue.
        """
        self._lock()
        try:
            if self.__started:
                return
            self.__thread.start()
            self.__started = True
        finally:
            self._unlock()

    def stop(self):
        """
        Stop processing requests.
        """
        self._lock()
        try:
            if not self.__started:
                return
            self.__thread.stop()
            self.__thread.join(90)
            self.__started = False
        finally:
            self._unlock()
            
    def close(self):
        """
        Close the consumer.
        Stop the receiver thread.
        """
        self._lock()
        try:
            self.stop()
        finally:
            self._unlock()
        Endpoint.close(self)

    def join(self):
        """
        Join the worker thread.
        """
        self.__thread.join()

    def received(self, message):
        """
        Process received request.
        Inject subject & destination.uuid.
        @param message: The received message.
        @type message: qpid.messaging.Message
        """
        self._lock()
        try:
            self.__received(message)
        finally:
            self._unlock()

    def valid(self, envelope):
        """
        Check to see if the envelope is valid.
        @param envelope: The received envelope.
        @type envelope: qpid.messaging.Message
        """
        valid = True
        if envelope.version != version:
            valid = False
            log.warn('{%s} version mismatch (discarded):\n%s',
                self.id(), envelope)
        return valid

    def dispatch(self, envelope):
        """
        Dispatch received request.
        @param envelope: The received envelope.
        @type envelope: qpid.messaging.Message
        """
        pass
    
    def __received(self, message):
        """
        Process received request.
        Inject subject & destination.uuid.
        @param message: The received message.
        @type message: qpid.messaging.Message
        """
        envelope = Envelope()
        subject = self.subject(message)
        envelope.load(message.content)
        if subject:
            envelope.subject = subject
        envelope.destination = Options(uuid=repr(self.id()))
        log.debug('{%s} received:\n%s', self.id(), envelope)
        if self.valid(envelope):
            self.dispatch(envelope)
        self.ack()


class Reader(Endpoint):
    """
    An AMQP message reader.
    @ivar __opened: Indicates that open() has been called.
    @type __opened: bool
    @ivar __receiver: An AMQP receiver to read.
    @type __receiver: Receiver
    @ivar __destination: The AMQP destination to read.
    @type __destination: L{Destination}
    """
    
    def __init__(self, destination, **options):
        """
        @param destination: The destination to consumer.
        @type destination: L{Destination}
        @param options: Options passed to Endpoint.
        @type options: dict
        """
        self.__opened = False
        self.__receiver = None
        self.__destination = destination
        Endpoint.__init__(self, **options)
    
    def open(self):
        """
        Open the reader.
        """
        Endpoint.open(self)
        self._lock()
        try:
            if self.__opened:
                return
            ssn = self.session()
            addr = self.address()
            log.debug('{%s} open %s', self.id(), addr)
            self.__receiver = ssn.receiver(addr)
            self.__opened = True
        finally:
            self._unlock()
    
    def close(self):
        """
        Close the reader.
        """
        self._lock()
        try:
            if not self.__opened:
                return
            self.__receiver.close()
            self.__opened = False
        finally:
            self._unlock()
        Endpoint.close(self)

    def next(self, timeout=90):
        """
        Get the next envelope from the queue.
        @param timeout: The read timeout.
        @type timeout: int
        @return: The next envelope.
        @rtype: L{Envelope}
        """
        msg = self.__fetch(timeout)
        if msg:
            envelope = Envelope()
            envelope.load(msg.content)
            log.debug('{%s} read next:\n%s', self.id(), envelope)
            return envelope

    def search(self, sn, timeout=90):
        """
        Seach the reply queue for the envelope with
        the matching serial #.
        @param sn: The expected serial number.
        @type sn: str
        @param timeout: The read timeout.
        @type timeout: int
        @return: The next envelope.
        @rtype: L{Envelope}
        """
        log.debug('{%s} searching for: sn=%s', self.id(), sn)
        while True:
            envelope = self.next(timeout)
            if not envelope:
                return
            if sn == envelope.sn:
                log.debug('{%s} search found:\n%s', self.id(), envelope)
                return envelope
            else:
                log.debug('{%s} search discarding:\n%s', self.id(), envelope)
                self.ack()
                
    def address(self):
        """
        Get the AMQP address for this endpoint.
        @return: The AMQP address.
        @rtype: str
        """
        self._lock()
        try:
            return str(self.__destination)
        finally:
            self._unlock()
                
    def __fetch(self, timeout):
        """
        Fetch the next message.
        @param timeout: The read timeout.
        @type timeout: int
        @return: The next message, or (None).
        @rtype: Message
        """
        try:
            self.open()
            return self.__receiver.fetch(timeout=timeout)
        except Empty:
            # normal
            pass
        except:
            log.error(self.id(), exc_info=1)


class RequestConsumer(Consumer):
    """
    An AMQP request consumer.
    @ivar __pending: The pending (delayed) message queue.
    @type __pending: L{PendingReceiver}
    @ivar __producer: A reply producer.
    @type __producer: L{gofer.messaging.producer.Producer}
    @ivar __started: Indicates that start() has been called.
    @type __started: bool
    @ivar __dispatcher: An RMI dispatcher.
    @type __dispatcher: L{gofer.messaging.dispatcher.Dispatcher}
    """
    
    def __init__(self, destination, **options):
        """
        @param destination: The destination to consumer.
        @type destination: L{Destination}
        @param options: Options passed to Consumer.__init__().
        @type options: dict
        """
        Consumer.__init__(self, destination, **options)
        q = PendingQueue(self.id())
        self.__pending = PendingReceiver(q, self)
        self.__producer = Producer(url=self.url)
        self.__started = False
        self.__dispatcher = None

    def start(self, dispatcher):
        """
        Start processing messages on the queue using the
        specified dispatcher.
        @param dispatcher: An RMI dispatcher.
        @type dispatcher: L{gofer.messaging.Dispatcher}
        """
        self._lock()
        try:
            if self.__started:
                return
            self.__dispatcher = dispatcher
            self.__pending.start()
            self.__started = True
            Consumer.start(self)
        finally:
            self._unlock()
        
    def stop(self):
        """
        Stop processing requests.
        """
        self._lock()
        try:
            if not self.__started:
                return
            self.__pending.stop()
            self.__pending.join(10)
            self.__started = False
            Consumer.stop(self)
        finally:
            self._unlock()

    def dispatch(self, envelope):
        """
        Dispatch received request.
        @param envelope: The received envelope.
        @type envelope: L{Envelope}
        """
        self._lock()
        try:
            return self.__dispatch(envelope)
        finally:
            self._unlock()

    def concurrent(self):
        """
        Get whether the consumer is concurrent.
        @return: based on dispatcher
        @rtype: bool
        """
        self._lock()
        try:
            return self.__dispatcher.concurrent()
        finally:
            self._unlock()
            
    def sendreply(self, envelope, result):
        """
        Send the reply if requested.
        @param envelope: The received envelope.
        @type envelope: L{Envelope}
        @param result: The request result.
        @type result: object
        """
        sn = envelope.sn
        any = envelope.any
        replyto = envelope.replyto
        if not replyto:
            return
        try:
            self.__send(
                replyto,
                sn=sn,
                any=any,
                result=result)
        except:
            log.error('send failed:\n%s', result, exc_info=True)

    def sendstarted(self, envelope):
        """
        Send the a status update if requested.
        @param envelope: The received envelope.
        @type envelope: L{Envelope}
        """
        sn = envelope.sn
        any = envelope.any
        replyto = envelope.replyto
        if not replyto:
            return
        try:
            self.__send(
                replyto,
                sn=sn,
                any=any,
                status='started')
        except:
            log.error('send (started), failed', exc_info=True)
            
    def __dispatch(self, envelope):
        """
        Dispatch received request.
        @param envelope: The received envelope.
        @type envelope: L{Envelope}
        """
        try:
            self.__checkwindow(envelope)
            self.sendstarted(envelope)
            if self.concurrent():
                self.__dispatcher.dispatch(envelope, self.sendreply)
                return
            result = self.__dispatcher.dispatch(envelope)
            self.sendreply(envelope, result)
        except WindowMissed:
            self.sendreply(envelope, Return.exception())
        except WindowPending:
            pass # ignored
        
    def __checkwindow(self, envelope):
        """
        Check the window.
        @param envelope: The received envelope.
        @type envelope: L{Envelope}
        @raise WindowPending: when window in the future.
        @raise WindowMissed: when window missed.
        """
        w = envelope.window
        if not isinstance(w, dict):
            return
        window = Window(w)
        if window.future():
            pending = self.__pending.queue
            pending.add(envelope)
            raise WindowPending(envelope.sn)
        if window.past():
            raise WindowMissed(envelope.sn)
            
    def __send(self, destination, **options):
        """
        Send an AMQP message.
        @param destination: The destination to consumer.
        @type destination: L{Destination}
        @param options: Options passed to Producer.send().
        @type options: dict
        """
        self._lock()
        try:
            self.__producer.send(destination, **options)
        finally:
            self._unlock()
