#+
# Copyright 2015 iXsystems, Inc.
# All rights reserved
#
# Redistribution and use in source and binary forms, with or without
# modification, are permitted providing that the following conditions
# are met:
# 1. Redistributions of source code must retain the above copyright
#    notice, this list of conditions and the following disclaimer.
# 2. Redistributions in binary form must reproduce the above copyright
#    notice, this list of conditions and the following disclaimer in the
#    documentation and/or other materials provided with the distribution.
#
# THIS SOFTWARE IS PROVIDED BY THE AUTHOR ``AS IS'' AND ANY EXPRESS OR
# IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE IMPLIED
# WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE
# ARE DISCLAIMED.  IN NO EVENT SHALL THE AUTHOR BE LIABLE FOR ANY
# DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL
# DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS
# OR SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION)
# HOWEVER CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT,
# STRICT LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING
# IN ANY WAY OUT OF THE USE OF THIS SOFTWARE, EVEN IF ADVISED OF THE
# POSSIBILITY OF SUCH DAMAGE.
#
#####################################################################


import errno
from freenas.dispatcher import AsyncResult
from .jsonenc import loads, dumps
from .rpc import RpcException
from ws4py.client.threadedclient import WebSocketClient

# if we have py-wsaccel (accelerator) use it to hotpatch ws4py's
# utf8validator and stream to be cythonized
try:
    import wsaccel
    wsaccel.patch_ws4py()
except:
    # no worries as we can always fallback to the pure Python implementation
    pass


class ShellClient(object):
    class ShellWebsocketHandler(WebSocketClient):
        def __init__(self, uri, parent):
            super(ShellClient.ShellWebsocketHandler, self).__init__(uri)
            self.parent = parent

        def opened(self):
            pass

        def received_message(self, message):
            if not self.parent.authenticated.is_set():
                try:
                    ret = loads(message.data.decode('utf8'))
                except ValueError:
                    self.parent.authenticated.set_exception(RpcException(errno.EINVAL, 'Invalid response from server'))
                    return

                if ret['status'] == 'ok':
                    self.parent.authenticated.set(True)
                else:
                    self.parent.authenticated.set_exception(RpcException(errno.EAUTH, 'Invalid token'))

                return

            self.parent.read_callback(message.data)

        def closed(self, code, reason=None):
            if callable(self.parent.close_callback):
                self.parent.close_callback()

    def __init__(self, hostname, token, port=80, path='dispatcher/shell'):
        self.hostname = hostname
        self.path = path
        self.port = port
        self.token = token
        self.connection = None
        self.authenticated = AsyncResult()
        self.auth_result = None
        self.read_callback = None
        self.close_callback = None

    def open(self):
        self.connection = self.ShellWebsocketHandler(
            'ws://{0}:{1}/{2}'.format(self.hostname, self.port, self.path),
            self
        )
        self.connection.connect()
        self.connection.send(dumps({'token': self.token}))
        while not self.connection.terminated:
            if self.authenticated.wait(1):
                break

    def close(self):
        self.connection.close()

    def on_data(self, callback):
        self.read_callback = callback

    def on_close(self, callback):
        self.close_callback = callback

    def write(self, data):
        if self.connection.terminated:
            return

        self.connection.send(data)


class VMConsoleClient(ShellClient):
    def __init__(self, hostname, token, port=80, path='containerd/console'):
        super(VMConsoleClient, self).__init__(hostname, token, port, path)
