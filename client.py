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

client_addresses = defaultdict(list)
client_accounts = defaultdict(list)

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
        if message != "Connected":
            try:
                ws_data = json.loads(message)
                if 'address' not in ws_data:
                    logger.error('Incorrect data from client: {}'.format(ws_data))
                    raise Exception('Incorrect data from client: {}'.format(ws_data))

                logger.info(ws_data['address'])

                client_addresses[ws_data['address']].append(self)
                client_accounts[self].append(ws_data['address'])

            except Exception as e:
                logger.error("Error {}".format(e))

    def on_close(self):
        logger.info('Client disconnected - {}'.format(self))
        accounts = client_accounts[self]
        for account in accounts:
            client_addresses[account].remove(self)
            if len(client_addresses[account]) == 0:
                del client_addresses[account]
        del client_accounts[self]

application = tornado.web.Application([
    (r"/call", WSHandler),
])

async def node_events():
    async with websockets.connect(f"ws://{args.host}:{args.port}") as websocket:

        # Subscribe to both confirmation and votes
        # You can also add options here following instructions in
        #   https://github.com/nanocurrency/nano-node/wiki/WebSockets
        await websocket.send(json.dumps(subscription("confirmation", ack=True)))
        print(await websocket.recv())  # ack

        while 1:
            receive_time = time.strftime("%d/%m/%Y %H:%M:%S")
            rec = json.loads(await websocket.recv())
            message = rec["message"]
            print("Block confirmed: {}".format(message))
            if message['link_as_account'] in client_addresses:
                tracking_address = message['link_as_account']
                clients = client_addresses[tracking_address]
                for client in clients:
                    logger.info("{}: {}".format(receive_time, client, message))
                    client.write_message(message)
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