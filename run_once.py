import logging
import threading
import time
import spidercmd
import server

threading.Thread(target=server.serve).start()

spidercmd.MyCmd().cmdloop()

while True:
    try:
        time.sleep(10)
    except KeyboardInterrupt:
        logging.info("Stopping the server...")
        server.stop(0)
        