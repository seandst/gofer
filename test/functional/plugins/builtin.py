from uuid import uuid4

from gofer.decorators import *
from gofer.agent.plugin import Plugin

from logging import getLogger

log = getLogger(__name__)
plugin = Plugin.find(__name__)


class TestAction:

    @action(hours=36)
    def hello(self):
        plugin = Plugin.find(__name__)
        log.info('Hello:\n%s', plugin.cfg())


class TestAdmin:

    @remote
    def echo(self, thing):
        return thing


class Rabbit:

    @remote
    def hop(self, n):
        return 'Rabbit hopped %d times.' % n


@remote
def echo(something):
    return something

