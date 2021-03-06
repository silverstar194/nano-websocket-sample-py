import socket
import time
import json
import logging
import sys
import asyncio
import websockets
import argparse
import tornado.gen
import tornado.ioloop
import tornado.iostream
import tornado.tcpserver
import tornado.web
import tornado.websocket
from collections import defaultdict
from logging.handlers import RotatingFileHandler


parser = argparse.ArgumentParser()
parser.add_argument('--host', dest='host', type=str, default='[::1]')
parser.add_argument('--port', dest='port', type=str, default='7078')
parser.add_argument('--silent', dest='silent', type=str, default='True')
args = parser.parse_args()

logger = logging.getLogger(__name__)

file_handler = RotatingFileHandler('websocket_server.log', mode='a', maxBytes=5, backupCount=0, encoding=None, delay=0)

handlers = [file_handler]

logging.basicConfig(
    level=logging.INFO,
    format='[%(levelname)s] %(asctime)s %(message)s',
    handlers=handlers
)

if args.silent == 'False':
    handlers.append(logging.StreamHandler(sys.stdout))

client_connections = defaultdict(list)
client_hashes = []
past_blocks = []

def subscription(topic: str, ack: bool=False, options: dict=None):
    d = {"action": "subscribe", "topic": topic, "ack": ack}
    if options is not None:
        d["options"] = options
    return d

class WSHandler(tornado.websocket.WebSocketHandler):
    def check_origin(self, origin):
        return True

    def open(self):
        logger.info("newyork.ws.nanospeed.live opened: {}".format(self))

    @tornado.gen.coroutine
    def on_message(self, message):
        if message != "Connected":
            try:
                ws_data = json.loads(message)
                if 'hash' not in ws_data:
                    logger.error('Incorrect data from client: {}'.format(ws_data))
                    raise Exception('Incorrect data from client: {}'.format(ws_data))

                client_connections[ws_data['hash']].append(self)
                client_hashes.append(ws_data['hash'])
                logger.info('Message from client {}'.format(ws_data['hash']))

                ##handle past blocks for race condition
                for block in past_blocks:
                    logger.info("Checking past block {} for {} {}".format(block[1], ws_data['hash'], block[1] == ws_data['hash']))
                    if block[1] == ws_data['hash']:
                        for client in client_connections[ws_data['hash']]:
                            logger.info("Found block {} {}: {}".format(block[0], block[1], block[2]))
                            client.write_message(json.dumps({"hash":block[1], "time":block[2]}))

            except Exception as e:
                logger.error("Error {}".format(e))

    def on_close(self):
        logger.info('Client disconnected - {}'.format(self))
        accounts = client_connections[self]
        for account in accounts:
            client_connections[account].remove(self)
            if len(client_connections[account]) == 0:
                del client_connections[account]
        del client_connections[self]

application = tornado.web.Application([
    (r"/call", WSHandler),
])

async def node_events():
    while True:
        try:
            async with websockets.connect(f"ws://{args.host}:{args.port}") as websocket:

                # Subscribe to both confirmation and votes
                # You can also add options here following instructions in
                #   https://github.com/nanocurrency/nano-node/wiki/WebSockets
                await websocket.send(json.dumps(subscription("confirmation", ack=True, options={"include_election_info": True})))
                logger.info(await websocket.recv())  # ack

                while True:
                    result = (await websocket.recv())
                    post_data = json.loads(result)
                    receive_time = post_data['message']['election_info']['time']

                    block_data = post_data['message']['block']
                    block_hash = post_data['message']['hash']
                    past_blocks.append((block_data, block_hash, receive_time))
                    logger.info(("Received block {}".format(block_hash)))

                    if len(past_blocks) > 500:
                        del past_blocks[0]

                    if block_hash in client_hashes:
                        clients = client_connections[block_hash]
                        for client in clients:
                            client.write_message(json.dumps({"block_data": block_data, "time": receive_time}))
        except Exception as e:
            logger.error("Exception on node_events %s", e)


async def socket_server():
    # websocket server
    try:
        myIP = socket.gethostbyname("127.0.0.1")
        logger.info('Websocket Server Started at %s' % myIP)

        # callback server
        application.listen(7090)
    except Exception as e:
        logger.error("Exception socket_server %s", e)

loop = asyncio.get_event_loop()
loop.create_task(socket_server())
loop.create_task(node_events())
loop.run_forever()
