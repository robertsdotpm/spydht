from spydht.spydht import DHT

import nacl.signing
import time
import hashlib

host1, port1 = 'localhost', 31000
key2 = nacl.signing.SigningKey.generate()

host2, port2 = 'localhost', 3101
dht2 = DHT(host2, port2, key2, boot_host=host1, boot_port=port1,  wan_ip="127.0.0.1")


time.sleep(5)

content = "x"
id = "test"

key = hashlib.sha256(id.encode("ascii") + content.encode("ascii")).hexdigest()

print(dht2[key])

print(dht2[key])

while True:
    time.sleep(1)





