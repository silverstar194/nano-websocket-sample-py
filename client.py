import asyncio
import websockets
import argparse
import socket, time, json, logging, sys
from logging.handlers import RotatingFileHandler
import tornado.gen
import tornado.ioloop
import tornado.iostream
import tornado.tcpserver
import tornado.web
import tornado.websocket
from collections import defaultdict

parser = argparse.ArgumentParser()
parser.add_argument('--host', dest='host', type=str, default='[::1]')
parser.add_argument('--port', dest='port', type=str, default='7078')
args = parser.parse_args()


logger = logging.getLogger(__name__)

file_handler = RotatingFileHandler('server.log', mode='a', maxBytes=5*1024, backupCount=2, encoding=None, delay=0)

handlers = [file_handler]

if not "--silent" in sys.argv[1:]:
    handlers.append(logging.StreamHandler(sys.stdout))

logging.basicConfig(
    level=logging.DEBUG,
    format='[%(levelname)s] %(asctime)s %(message)s',
    handlers=handlers
)

client_connections = defaultdict(list)
client_hashes = defaultdict(list)
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
        logger.info("WebSocket opened: {}".format(self))

    @tornado.gen.coroutine
    def on_message(self, message):
        logger.info('Message from client {}: {}'.format(self, message))
        logger.info(message)
        if message != "Connected":
            try:
                ws_data = json.loads(message)
                if 'hash' not in ws_data:
                    logger.error('Incorrect data from client: {}'.format(ws_data))
                    raise Exception('Incorrect data from client: {}'.format(ws_data))

                logger.info(ws_data['hash'])

                client_connections[ws_data['hash']].append(self)
                client_hashes[self].append(ws_data['hash'])

                ##handle past blocks for race condition
                for block in past_blocks:
                    logger.info("{}".format(block[1]))
                    if block[1] == ws_data['hash']:
                        for client in client_connections[ws_data['hash']]:
                            logger.info("{} {}: {}".format(block[0], block[1], block[2]))
                            client.write_message(json.dumps({"hash":block[1], "time":block[2]}))
                            logger.info("Sent data")

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
    async with websockets.connect(f"ws://{args.host}:{args.port}") as websocket:

        # Subscribe to both confirmation and votes
        # You can also add options here following instructions in
        #   https://github.com/nanocurrency/nano-node/wiki/WebSockets
        await websocket.send(json.dumps(subscription("confirmation", ack=True)))
        logger.info(await websocket.recv())  # ack

        while 1:
            logger.info("Waiting for new block from node...")
            result = (await websocket.recv())
            logger.info("Received block %s ", result)
            receive_time = int(round(time.time() * 1000))
            post_data = json.loads(result)

            logger.info(("{}: {}".format(receive_time, post_data)))
            logging.info("Post data {} ", post_data)
            block_data = post_data['message']['block']
            block_hash = post_data['message']['hash']
            past_blocks.append((block_data, block_hash, receive_time))

            logging.info(past_blocks)

            if len(past_blocks) > 500:
                del past_blocks[0]

            if block_hash in client_hashes:
                clients = client_connections[block_hash]
                for client in clients:
                    logger.info("{}: {} {}".format(receive_time, client, post_data))
                    client.write_message(json.dumps({"block_data": block_data, "time": receive_time}))
                    logger.info("Sent data")


async def socket_server():
    # websocket server
    myIP = socket.gethostbyname(socket.gethostname())
    logger.info('Websocket Server Started at %s' % myIP)

    # callback server
    application.listen(7090)

    # infinite loop
    tornado.ioloop.IOLoop.instance().start()

async def main():
    await node_events()
    await socket_server()

loop = asyncio.get_event_loop()
loop.create_task(main())
loop.run_forever()