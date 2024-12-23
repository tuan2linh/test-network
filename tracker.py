import socket
from concurrent.futures import ThreadPoolExecutor 
from threading import Thread, Event
import hashlib
import random
import os
import sys
import signal

from utils.message import send, recv

MAX_PEERS_TO_RETURN = 50
MIN_PEERS_TO_RETURN = 10
INTERVAL = 1    # 1 second

class Tracker:
    def __init__(self, default_ip, port, max_workers=10):
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.connect(('8.8.8.8',1))
            ip = s.getsockname()[0]
        except Exception:
            ip = default_ip
        finally:
            s.close()

        self.ip = ip
        self.port = port
        self.tracker_id = hashlib.sha1(("%s:%d" % (self.ip, self.port)).encode('utf-8')).digest()
        self.torrents = {}
        self.socket = None
        self.max_workers = max_workers
        self.stop_event = Event()
        self.executor = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="tracker")
        
        self.is_running = False

    def start(self):
        try:
            self.is_running = True
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
                sock.bind((self.ip, self.port))
                sock.listen(self.max_workers)
                sock.settimeout(1.0)  # Add timeout to allow checking stop_event
                print(f"Listening on: {self.ip}:{self.port}")

                while not self.stop_event.is_set():
                    try:
                        conn, addr = sock.accept()
                        if not self.executor._shutdown:
                            self.executor.submit(self.handle_request, conn, addr)
                    except socket.timeout:
                        continue
                    except Exception as e:
                        if not self.stop_event.is_set():
                            print(f"Error accepting connection: {e}")
        except Exception as e:
            if not self.stop_event.is_set():
                print("Error: ", e)
            
    def stop(self):
        print("\nShutting down tracker...")
        self.stop_event.set()
        self.executor.shutdown(wait=True)
        self.is_running = False

    def handle_request(self, conn, addr):
        try:
            data = recv(conn)
            event = data.get('event', '')
            print(f"Request from {addr}")
               
            if event in ['started', 'completed', 'stopped']: 
                if (event == 'started'):
                    if data['left'] == 0:
                        self.update_progress(data['info_hash'], data['peer_id'], addr[0], data['port'], 1.0)
                        
                elif (event == 'completed'):
                    self.update_progress(data['info_hash'], data['peer_id'], addr[0], data['port'], 1.0)
                        
                elif (event == 'stopped'):
                    all_peers = self.torrents.get(data['info_hash'], [])
                    self.torrents[data['info_hash']] = [peer for peer in all_peers if peer['peer_id'] != data['peer_id']]
                    return
                        
                send(conn, self.create_response(data))
                return
                
            self.update_progress(data['info_hash'], data['peer_id'], addr[0], data['port'], data['downloaded'] / (data['left'] + data['downloaded']))
        except Exception as e:
            print(f"Error handling request from {addr}: {e}")
            send(conn, {"failure reason": str(e)})           
        finally:
            conn.close()
        
    def create_response(self, data):
        all_peers = self.torrents.get(data['info_hash'], [])
        peers = []
        complete_peers = [peer for peer in all_peers if peer['progress'] == 1.0]
        if len(complete_peers) < MAX_PEERS_TO_RETURN:
            incomplete_peers = [peer for peer in all_peers if peer['progress'] < 1.0]
            remaining_peers = MAX_PEERS_TO_RETURN - len(incomplete_peers)
            peers = complete_peers + random.choices(incomplete_peers, k=min(remaining_peers, len(incomplete_peers)))
        else:
            peers = random.choices(complete_peers, k=MAX_PEERS_TO_RETURN)
            
        if (len(peers) == 0):
            raise Exception("No peers found for this torrent.")
        
        num_complete_peers = len([peer for peer in peers if peer['progress'] == 1.0])
        response = {
            'tracker_id': self.tracker_id,
            'interval': INTERVAL,
            'complete': num_complete_peers,
            'incomplete': len(peers) - num_complete_peers,
            'peers': [{'peer_id': peer['peer_id'], 'ip': peer['ip'], 'port': peer['port']} for peer in peers]
        }
        if (len(peers) < MIN_PEERS_TO_RETURN):
            response['warning message'] = 'Too few peers returned, your download speed may be slow.'
        
        return response
    
    def update_progress(self, info_hash, peer_id, ip, port, progress):
        all_peers = self.torrents.get(info_hash, [])
        for peer in all_peers:
            if peer['peer_id'] == peer_id:
                peer['progress'] = progress
                return
        
        if info_hash not in self.torrents:
            self.torrents[info_hash] = []
        self.torrents[info_hash].append({'peer_id': peer_id, 'ip': ip, 'port': port, 'progress': progress})

if __name__ == "__main__":
    default_ip = os.getenv('HOST', '127.0.0.1') 
    port = int(os.getenv('PORT', 10000))
    is_production = os.getenv('ENVIRONMENT') == 'production'

    tracker = Tracker(default_ip, port)
    tracker_thread = Thread(target=tracker.start, name="tracker-main")
    tracker_thread.start()

    def signal_handler(signum, frame):
        print("\nReceived signal to shutdown...")
        tracker.stop()
        tracker_thread.join()
        sys.exit(0)

    # Register signal handlers
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    try:
        if is_production:
            # In production, just wait for signals
            signal.pause()
        else:
            # In development, allow command input
            while not tracker.stop_event.is_set():
                try:
                    cmd = input()
                    if cmd.strip().lower() == "stop":
                        tracker.stop()
                        break
                except EOFError:
                    break
                except KeyboardInterrupt:
                    break
    finally:
        if tracker.is_running:
            tracker.stop()
        if tracker_thread.is_alive():
            tracker_thread.join()
