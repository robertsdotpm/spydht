from spydht.spydht import DHT

import nacl.signing
import time

key1 = nacl.signing.SigningKey.generate()

host1, port1 = 'localhost', 3100
dht1 = DHT(host1, port1, key1)


dht1["test2"] = ["x"]


while True:
    time.sleep(1)
    
