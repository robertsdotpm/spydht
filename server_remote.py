from spydht.spydht import DHT

import nacl.signing
import time
import hashlib

key1 = nacl.signing.SigningKey.generate()

host1, port1 = '176.9.147.116', 31000
dht1 = DHT(host1, port1, key1, wan_ip="176.9.147.116")

while True:
    time.sleep(1)
