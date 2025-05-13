import threading
import spidercmd
import server

threading.Thread(target=server.serve).start()

spidercmd.MyCmd().cmdloop()
