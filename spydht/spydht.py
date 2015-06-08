import sys, os
import json
import random
import socket
import select
import hashlib
import re
try:
    import socketserver
except:
    import SocketServer
    socketserver = SocketServer
import threading
import time

import nacl.signing
import uuid
import hashlib

from .bucketset import BucketSet
from .hashing import hash_function, random_id, id_from_addr
from .peer import Peer
from .shortlist import Shortlist

k = 20
alpha = 3
id_bits = 256
iteration_sleep = 1

class DHTRequestHandler(socketserver.BaseRequestHandler):

    def handle(self):

        with self.server.send_lock:
            #Test alive for nodes in routing table.
            main = self.server.dht
            elapsed = time.time() - main.last_ping
            if elapsed >= main.ping_interval:
                for freshness in main.buckets.node_freshness:
                    #Check freshness.
                    elapsed = time.time() - freshness["timestamp"]
                    if elapsed < main.ping_interval:
                        break

                    #Store pending ping.
                    bucket_no = freshness["bucket_no"]
                    bucket = main.buckets.buckets[bucket_no]
                    node = freshness["node"]
                    magic = hashlib.sha256(str(uuid.uuid4()).encode("ascii")).hexdigest()
                    freshness["timestamp"] = time.time()
                    main.ping_ids[magic] = {
                        "node": node,
                        "timestamp": time.time(),
                        "bucket_no": bucket_no,
                        "freshness": freshness
                    }

                    #Send ping.
                    message = {
                        "message_type": "ping",
                        "magic": magic
                    }
                    peer = Peer(node[0], node[1], node[2])
                    peer._sendmessage(message, self.server.socket, peer_id=peer.id, lock=self.server.send_lock)

                    #Indicate freshness in ordering.
                    del main.buckets.node_freshness[0]
                    main.buckets.node_freshness.append(freshness)

                    break

                #Refresh last ping.
                main.last_ping = time.time()

            #Record expired pings.
            expired = []
            for magic in list(main.ping_ids):
                ping = main.ping_ids[magic]
                elapsed = time.time() - ping["timestamp"]
                if elapsed >= main.ping_expiry:
                    expired.append(magic)

            #Timeout pending pings and remove old routing entries.
            for magic in expired:
                bucket_no = main.ping_ids[magic]
                node = main.ping_ids[node]
                main.buckets.buckets[bucket_no].remove(node)

                #More cleanup stuff so new nodes can be added.
                host, port, id = node
                if host in main.buckets.seen_ips:
                    if port in main.buckets.seen_ips[host]:
                        main.buckets.seen_ips[host].remove(port)

                    if not len(main.buckets.seen_ips[host]):
                        del main.buckets.seen_ips[host]

                del main.buckets.seen_ids[id]
                main.buckets.node_freshness.remove(main.ping_ids[magic]["freshness"])
                del main.ping_ids[magic]

            #Check for expired keys.
            if main.store_expiry:
                #Time to run check again?
                elapsed = time.time() - main.last_store_check
                if elapsed >= main.store_check_interval:
                    #Record expired keys.
                    expired = []
                    for key in list(main.data):
                        value = main.data[key]
                        elapsed = time.time() - value["timestamp"]
                        if elapsed >= main.store_expiry:
                            expired.append(key)

                    #Timeout expired keys.
                    for key in expired:
                        del main.data[key]

                    #Reset last_store_check.
                    main.last_store_check = time.time()

        #Handle replies and requests.
        message = json.loads(self.request[0].decode("utf-8").strip())
        try:
            message_type = message["message_type"]
            if message_type == "ping":
                self.handle_ping(message)
            elif message_type == "pong":
                self.handle_pong(message)
            elif message_type == "find_node":
                self.handle_find(message)
            elif message_type == "find_value":
                self.handle_find(message, find_value=True)
            elif message_type == "found_nodes":
                self.handle_found_nodes(message)
            elif message_type == "found_value":
                self.handle_found_value(message)
            elif message_type == "store":
                self.handle_store(message)
            elif message_type == "push":
                self.handle_push(message)
        except Exception as e:
            exc_type, exc_obj, exc_tb = sys.exc_info()
            fname = os.path.split(exc_tb.tb_frame.f_code.co_filename)[1]
            print(exc_type, fname, exc_tb.tb_lineno)
            return

        client_host, client_port = self.client_address
        peer_id = message["peer_id"]
        new_peer = Peer(client_host, client_port, peer_id)
        self.server.dht.buckets.insert(new_peer)

    def handle_ping(self, message):
        client_host, client_port = self.client_address
        id = message["peer_id"]
        peer = Peer(client_host, client_port, id)
        peer.pong(magic=message["magic"], socket=self.server.socket, peer_id=self.server.dht.peer.id, lock=self.server.send_lock)
        
    def handle_pong(self, message):
        #Is this a valid nonce?
        main = self.server.dht
        magic = message["magic"]
        if magic not in main.ping_ids:
            return

        #Has the right node replied?
        client_host, client_port = self.client_address
        id = message["peer_id"]
        peer = Peer(client_host, client_port, id)
        astriple = peer.astriple()
        if main.ping_ids[magic]["node"] != astriple:
            return

        #Refresh the new node details.
        bucket_no = main.ping_ids[magic]["bucket_no"]
        bucket = main.buckets.buckets[bucket_no]
        bucket.append(astriple)

        #Remove pending ping.
        del main.ping_ids[magic]
        
    def handle_find(self, message, find_value=False):
        key = message["id"]
        id = message["peer_id"]
        client_host, client_port = self.client_address
        peer = Peer(client_host, client_port, id)
        response_socket = self.request[1]
        if find_value and (key in self.server.dht.data):
            value = self.server.dht.data[key]
            peer.found_value(id, value, message["rpc_id"], socket=response_socket, peer_id=self.server.dht.peer.id, lock=self.server.send_lock)
        else:
            nearest_nodes = self.server.dht.buckets.nearest_nodes(id)
            if not nearest_nodes:
                nearest_nodes.append(self.server.dht.peer)
            nearest_nodes = [nearest_peer.astriple() for nearest_peer in nearest_nodes]
            peer.found_nodes(id, nearest_nodes, message["rpc_id"], socket=response_socket, peer_id=self.server.dht.peer.id, lock=self.server.send_lock)

    def handle_found_nodes(self, message):
        rpc_id = message["rpc_id"]
        shortlist = self.server.dht.rpc_ids[rpc_id]
        del self.server.dht.rpc_ids[rpc_id]
        nearest_nodes = [Peer(*peer) for peer in message["nearest_nodes"]]
        shortlist.update(nearest_nodes)
        
    def handle_found_value(self, message):
        rpc_id = message["rpc_id"]
        shortlist = self.server.dht.rpc_ids[rpc_id]

        #Verify key is correct.
        expected_key = hash_function(message["value"]["id"].encode("ascii") + message["value"]["content"].encode("ascii"))
        if shortlist.key != expected_key:
            return

        del self.server.dht.rpc_ids[rpc_id]
        shortlist.set_complete(message["value"])
        
    def handle_store(self, message):
        key = message["id"]

        #Check message hasn't expired.
        if self.server.dht.store_expiry:
            elapsed = time.time() - message["timestamp"]
            if elapsed >= self.server.dht.store_expiry:
                return

            #Future timestamps are invalid.
            if elapsed < 0:
                return

        #Verify updated message is signed with same key.
        if key in self.server.dht.data:
            #Signature is valid.
            #(Raises exception if not.)
            ret = nacl.signing.VerifyKey(self.server.dht.data[key]["key"], encoder=nacl.encoding.Base64Encoder).verify(nacl.encoding.Base64Encoder.decode(message["value"]["signature"]))
        else:
            ret = nacl.signing.VerifyKey(message["value"]["key"], encoder=nacl.encoding.Base64Encoder).verify(nacl.encoding.Base64Encoder.decode(message["value"]["signature"]))

        #Decode ret to unicode.
        if type(ret) == bytes:
            ret = ret.decode("utf-8")

        #Check that the signature corresponds to this message.
        message_content = message["value"]["content"]
        if ret != message_content:
            return

        #Verify key is correct.
        expected_key = hash_function(message["value"]["id"].encode("ascii") + message["value"]["content"].encode("ascii"))
        if key != expected_key:
            return

        self.server.dht.data[key] = message["value"]

    def handle_push(self, message):
        pass

class DHTServer(socketserver.ThreadingMixIn, socketserver.UDPServer):
    def __init__(self, host_address, handler_cls):
        socketserver.UDPServer.__init__(self, host_address, handler_cls)
        self.send_lock = threading.Lock()

class DHT(object):
    def __init__(self, host, port, key, id=None, boot_host=None, boot_port=None, wan_ip=None):
        #Send node pings to least fresh node every n seconds.
        self.ping_interval = 10

        #Time to reply to a ping in seconds.
        self.ping_expiry = 10

        #How long to store keys for in seconds.
        #Zero for no limit.
        self.store_expiry = 5 * 60

        #How often in seconds to check for expired keys.
        self.store_check_interval = 1 * 60

        #How often to broadcast which bind port we've taken.
        self.broadcast_interval = 1

        #Survey network for active DHT instances.
        self.broadcast_port = 31337
        broadcast = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        broadcast.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        broadcast.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        broadcast.bind(('', self.broadcast_port))
        broadcast.setblocking(0)

        #Wait for reply.
        waited = 0
        sleep_interval = 1
        observed_ports = []
        while waited < (self.broadcast_interval * 2) + 1:
            waited += sleep_interval
            r, w, e = select.select([broadcast], [], [], 0)
            for s in r:
                msg = s.recv(1024)
                msg = msg.decode("utf-8")
                ret = re.findall("^SPYDHT BIND ([0-9]+)$", msg)
                if ret:
                    observed_port, = ret
                    observed_port = int(observed_port)
                    if observed_port not in observed_ports:
                        observed_ports.append(observed_port)

            time.sleep(sleep_interval)

        #Are there any valid ports left?
        self.valid_bind_ports = [31000, 31001] #Per LAN.
        allowed_ports = self.valid_bind_ports.copy()
        for observed_port in observed_ports:
            allowed_ports.remove(observed_port)
        if not len(allowed_ports):
            raise Exception("Maximum SPYDHT instances for this LAN exceeded! Try closing some instances of this software.")

        #Indicate to LAN that this port is now reserved.
        self.port = allowed_ports[0]
        def broadcast_loop():
            while 1:
                msg = "SPYDHT BIND %s" % (str(self.port))
                msg = msg.encode("ascii")
                broadcast.sendto(msg, ('255.255.255.255', self.broadcast_port))
                time.sleep(self.broadcast_interval)
        self.broadcast_thread = threading.Thread(target=broadcast_loop)
        self.broadcast_thread.start()

        #Generic init.
        self.wan_ip = wan_ip
        if self.wan_ip == None:
            raise Exception("WAN IP required.")
        self.my_key = key
        if not id:
            id = id_from_addr(self.wan_ip, self.port)
        self.last_ping = time.time()
        self.ping_ids = {}        
        self.last_store_check = time.time()
        self.peer = Peer(str(host), self.port, id)
        self.data = {}
        self.buckets = BucketSet(k, id_bits, self.peer.id, self.valid_bind_ports)
        self.rpc_ids = {} # should probably have a lock for this
        self.server = DHTServer(self.peer.address(), DHTRequestHandler)
        self.server.dht = self
        self.server_thread = threading.Thread(target=self.server.serve_forever)
        self.server_thread.daemon = True
        self.server_thread.start()
        self.bootstrap(str(boot_host), boot_port)
    
    def iterative_find_nodes(self, key, boot_peer=None):
        shortlist = Shortlist(k, key, self)
        shortlist.update(self.buckets.nearest_nodes(key, limit=alpha))
        if boot_peer:
            rpc_id = random.getrandbits(id_bits)
            self.rpc_ids[rpc_id] = shortlist
            boot_peer.find_node(key, rpc_id, socket=self.server.socket, peer_id=self.peer.id)

        while (not shortlist.complete()) or boot_peer:
            nearest_nodes = shortlist.get_next_iteration(alpha)
            for peer in nearest_nodes:
                shortlist.mark(peer)
                rpc_id = random.getrandbits(id_bits)
                self.rpc_ids[rpc_id] = shortlist
                peer.find_node(key, rpc_id, socket=self.server.socket, peer_id=self.peer.id) ######
            time.sleep(iteration_sleep)
            boot_peer = None

        return shortlist.results()
        
    def iterative_find_value(self, key):
        shortlist = Shortlist(k, key, self)
        shortlist.update(self.buckets.nearest_nodes(key, limit=alpha))
        while not shortlist.complete():
            nearest_nodes = shortlist.get_next_iteration(alpha)
            for peer in nearest_nodes:
                shortlist.mark(peer)
                rpc_id = random.getrandbits(id_bits)
                self.rpc_ids[rpc_id] = shortlist
                peer.find_value(key, rpc_id, socket=self.server.socket, peer_id=self.peer.id) #####
            time.sleep(iteration_sleep)

        return shortlist.completion_result()
            
    def bootstrap(self, boot_host, boot_port):
        if boot_host and boot_port:
            boot_peer = Peer(boot_host, boot_port, 0)
            self.iterative_find_nodes(self.peer.id, boot_peer=boot_peer)
                    
    def __getitem__(self, key, bypass=4):
        hashed_key = int(key, 16)
        if hashed_key in self.data:
            return self.data[hashed_key]["content"]
        result = self.iterative_find_value(hashed_key)
        if result:
            return result["content"]

        if bypass != 0:
            time.sleep(0.100)
            return self.__getitem__(key, bypass - 1)

        raise KeyError
        
    def __setitem__(self, key, content):
        content = str(content)
        hashed_key = hash_function(key.encode("ascii") + content.encode("ascii"))
        nearest_nodes = self.iterative_find_nodes(hashed_key)
        value = {
            "id": key,
            "timestamp": time.time(),
            "content": content,
            "key": self.my_key.verify_key.encode(encoder=nacl.encoding.Base64Encoder).decode("utf-8"),
            "signature": nacl.encoding.Base64Encoder.encode(self.my_key.sign(content.encode("ascii"))).decode("utf-8")
        }

        if not nearest_nodes:
            self.data[hashed_key] = value
        for node in nearest_nodes:
            node.store(hashed_key, value, socket=self.server.socket, peer_id=self.peer.id)
        
    def tick():
        pass
