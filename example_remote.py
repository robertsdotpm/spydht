import uuid
from spydht.spydht import DHT
import nacl.signing
import time
import hashlib

host1, port1 = '176.9.147.116', 31000
key2 = nacl.signing.SigningKey.generate()
host2, port2 = '0.0.0.0', 3021
dht2 = DHT(host2, port2, key2, boot_host=host1, boot_port=port1, wan_ip="your_wan_ip")
unique_id = str(uuid.uuid4())
id = unique_id
content = "my content"
key = hashlib.sha256(id.encode("ascii") + content.encode("ascii")).hexdigest()

dht2[id] = content
print(dht2[key])


while 1:
    time.sleep(1)
