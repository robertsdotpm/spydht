from spydht.spydht import DHT

import nacl.signing
import time

host1, port1 = 'localhost', 3100
key2 = nacl.signing.SigningKey.generate()

host2, port2 = 'localhost', 3101
dht2 = DHT(host2, port2, key2, boot_host=host1, boot_port=port1)


time.sleep(5)

print(dht2["test2"])

print(dht2["test2"])

while True:
    time.sleep(1)
