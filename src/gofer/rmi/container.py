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
Agent base classes.
"""

from gofer.messaging.model import Options
from gofer.messaging import Queue, Exchange, Destination
from gofer.rmi.stub import Stub
from gofer.rmi.window import Window
from logging import getLogger

log = getLogger(__name__)

        
class Container:
    """
    The stub container
    :ivar __id: The peer ID.
    :type __id: str
    :ivar __options: Container options.
    :type __options: Options
    """

    def __init__(self, uuid, url, **options):
        """
        :param uuid: The peer ID.
        :type uuid: str
        :param url: The agent URL.
        :type url: str
        :param options: keyword options.
            Options:
              - async : Indicates that requests asynchronous.
                  Default = False
              - ctag : The asynchronous correlation tag.
                  When specified, it implies all requests are asynchronous.
              - window : The request window.  See I{Window}.
                  Default = any time.
              - secret : A shared secret used for request authentication.
              - timeout : The request timeout (seconds).
                  Default = (10,90) seconds.
        :type options: dict
        """
        self.__id = uuid
        self.__url = url
        self.__options = Options(window=Window())
        self.__options += options

    def __destination(self):
        """
        Get the stub destination(s).
        :return: Either a queue destination or a list of destinations.
        :rtype: gofer.transport.model.Destination
        """
        direct = Exchange.direct(self.__url)
        if isinstance(self.__id, (list, tuple)):
            destinations = []
            for d in self.__id:
                d = Destination(direct.name, d)
                destinations.append(d)
            return destinations
        else:
            return Destination(direct.name, self.__id)
    
    def __getattr__(self, name):
        """
        Get a stub by name.
        :param name: The name of a stub class.
        :type name: str
        :return: A stub object.
        :rtype: Stub
        """
        return Stub.stub(
            name,
            self.__url,
            self.__destination(),
            self.__options)
        
    def __getitem__(self, name):
        """
        Get a stub by name.
        :param name: The name of a stub class.
        :type name: str
        :return: A stub object.
        :rtype: Stub
        """
        return getattr(self, name)

    def __str__(self):
        return '{%s} opt:%s' % (self.__id, str(self.__options))
    
    def __repr__(self):
        return str(self)
