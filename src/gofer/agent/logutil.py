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

import os
import sys
import logging
from gofer import NAME
from logging import root, Formatter
from logging.handlers import RotatingFileHandler

LOGDIR = '/var/log/%s' % NAME
LOGFILE = 'agent.log'

TIME = '%(asctime)s'
LEVEL = ' [%(levelname)s]'
THREAD = '[%(threadName)s]'
FUNCTION = ' %(funcName)s()'
FILE = ' @ %(filename)s'
LINE = ':%(lineno)d'
MSG = ' - %(message)s'

if sys.version_info < (2,5):
    FUNCTION = ''

FMT = \
    ''.join((TIME,
            LEVEL,
            THREAD,
            FUNCTION,
            FILE,
            LINE,
            MSG,))

handler = None

def getLogger(name):
    global handler
    if not os.path.exists(LOGDIR):
        os.mkdir(LOGDIR)
    if handler is None:
        path = os.path.join(LOGDIR, LOGFILE)
        handler = RotatingFileHandler(path, maxBytes=0x100000, backupCount=5)
        handler.setFormatter(Formatter(FMT))
        root.setLevel(logging.INFO)
        root.addHandler(handler)
    log = logging.getLogger(name)
    return log
