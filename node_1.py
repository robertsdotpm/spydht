from spydht.spydht import DHT

import nacl.signing
import time
import hashlib

key1 = nacl.signing.SigningKey.generate()

host1, port1 = 'localhost', 3100
dht1 = DHT(host1, port1, key1, wan_ip="127.0.0.1")


content = "x"
id = "test"

dht1[id] = content


while True:
    time.sleep(1)
    
