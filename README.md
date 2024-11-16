# p2p file sharing
## How to run this project? 
1. clone this project and install python
2. open project in terminal
3. download packages
   ```
   pip install -r requirements.txt
   ```
4. run ```tracker.py```
   ```
   python tracker.py
   ```
5. copy ip of tracker, then open utils/dns and replace ```<IP TRACKER HERE>``` by tracker ip in  ```dns_records```
    ```
    dns_records = {
        "http://127.0.0.1:22236/announce": ("<IP TRACKER HERE>", 22236),
    }
    ```
6. open new terminal and run ```peer.py``` with a port
   ```
   python peer.py <PORT OF THIS PEER>
   ```
7. type ```upload``` or ```download``` and following the intruction
## Note, to be able to test the function of sending and receiving files, you need to create at least 2 peers with different ports.
