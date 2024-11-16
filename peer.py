import socket
from concurrent.futures import ThreadPoolExecutor
from threading import Thread, Lock
from torf import Torrent
from queue import Queue
import concurrent.futures
import hashlib
import random
import math
import time
import sys
import os

from utils.dns import resolve
from utils.message import send, recv
from utils.file import read_block, write_piece, combine_files
from utils.torrent import create_torrent_file
from utils.message import get_message_type, Handshake, BitField, Request, Piece, Have
from upload_file import FileUploader
from download_file import FileDownloader

MAX_PEER_TO_ACCEPT = 30
MAX_PEERS_TO_CONNECT = 8

PIECE_SIZE = 512*1024 # 512KB
BLOCK_SIZE = 16*1024 # 16KB

class Peer:
    def __init__(self, default_ip='127.0.0.1', port=6881):
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
        self.peer_id = hashlib.sha1(("%s:%d" % (self.ip, self.port)).encode('utf-8')).digest()
        self.having_files = {}
        self.having_files_lock = Lock()
        self.piece_count = {}
        self.piece_count_lock = Lock()
        
        self.listening_executor = ThreadPoolExecutor(max_workers=MAX_PEER_TO_ACCEPT)
        self.listening_running = False
        
        self.uploader = FileUploader()
        self.downloader = FileDownloader()
        
        # self.am_choking = []
        # self.am_interested = []
        # self.peer_choking = []
        # self.peer_interested = []
        
    # METHODS FOR PEER TO PEER COMMUNICATION
    def listening_start(self):
        try:
            self.listening_running = True
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
                sock.bind((self.ip, self.port))
                sock.listen(MAX_PEER_TO_ACCEPT)
                print(f"Listening on: {self.ip}:{self.port}")
                
                while self.listening_running:
                    conn, addr = sock.accept()
                    self.listening_executor.submit(self.handle_request, conn, addr)
        except Exception as e:
            print("Error: ", e)
    
    def listening_stop(self):
        self.listening_running = False
        self.listening_executor.shutdown(wait=False)
        
    def handle_request(self, conn, addr):
        try:
            info_hash, peer_id = None, None
            while True:
                data = recv(conn, is_binary=True)
                message_type = get_message_type(data)
                if message_type == "handshake":
                    info_hash, peer_id = Handshake.from_bytes(data)
                    if info_hash not in self.having_files:
                        send(conn, b"\x00", is_binary=True)
                        conn.close()
                        return
                    
                    print(f"Handshake from {addr[0]}:{addr[1]}")
                    send(conn, bytes(Handshake(info_hash, self.peer_id)), is_binary=True)  

                if not info_hash:
                    continue
                
                if message_type == "bitfield":
                    peer_bitfield = BitField.from_bytes(data)
                    self.update_piece_count(info_hash, conn, peer_bitfield)
                    with self.having_files_lock:
                        bitfield = self.having_files[info_hash]['bitfield']
                    send(conn, bytes(BitField(bitfield)), is_binary=True)
                elif message_type == "request":
                    index, begin, length = Request.from_bytes(data)
                    data = read_block(
                        self.having_files[info_hash]['files'], 
                        index, 
                        begin,
                        length
                    )
                    
                    if data:
                        send(conn, bytes(Piece(index, begin, data)), is_binary=True)
                elif message_type == "have":
                    index = Have.from_bytes(data)
                    with self.piece_count_lock:
                        self.piece_count[info_hash].sort(key=lambda x: x['index'])
                        self.piece_count[info_hash][index]['count'] += 1
                        self.piece_count[info_hash].sort(key=lambda x: (x['count'], random.random()))
                    
                    # send a confirm message
                    send(conn, b"\x00", is_binary=True)                        
            
        except Exception as e:
            print("An error occurred:", e)
            
    def update_piece_count(self, info_hash, conn, bitfield):
        # sort piece_count by index
        with self.piece_count_lock:
            if info_hash not in self.piece_count:
                self.piece_count[info_hash] = [{ "count": 0, "index": i, "conns": [] } 
                                            for i in range (len(bitfield))]
            else:
                self.piece_count[info_hash].sort(key=lambda x: x['index'])
            
            for piece, bit in zip(self.piece_count[info_hash], bitfield):
                if bit:
                    piece['count'] += 1
                    piece['conns'].append(conn)
                    
            # sort piece_count by count
            self.piece_count[info_hash].sort(key=lambda x: (x['count'], random.random()))
            
    # METHODS FOR DOWNLOADING AND SEEDING
    def seed(self, torrent, base_folder):
        try:
            info_hash = hashlib.sha1(str(torrent.metainfo['info']).encode('utf-8')).digest()
            data = self.create_request(info_hash=info_hash, left=0)
            
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
                sock.connect(resolve(torrent.metainfo['announce']))
                send(sock, data)
                
                data = recv(sock)
                if 'failure reason' in data:
                    raise Exception(data['failure reason'])
                
            total_length, files = 0, []
            root = os.path.join(os.path.dirname(base_folder), torrent.metainfo['info']['name'])
            if 'files' in torrent.metainfo['info']:
                for file in torrent.metainfo['info']['files']:
                    total_length += file['length']
                    file_path = os.path.join(root, *file["path"])
                    files.append({"path": file_path , "length": file["length"]})
            else:
                total_length = torrent.metainfo['info']['length']
                files.append({"path": root, "length": torrent.metainfo['info']['length']})
            
            with self.having_files_lock:
                self.having_files[info_hash] = {
                    'bitfield': [True] * (math.ceil(total_length / PIECE_SIZE)),
                    'files': files
                }
                
            print("Seeding successfully")
        
        except Exception as e:
            print("An error occurred:", e)
        
    def download(self, torrent: Torrent, dest: str, max_workers=5):
        try:
            # calculate total length of files
            total_length, files = 0, []
            root = os.path.join(dest, torrent.metainfo['info']['name'])
            if 'files' in torrent.metainfo['info']:
                for file in torrent.metainfo['info']['files']:
                    total_length += file['length']
                    file_path = os.path.join(root, *file["path"])
                    files.append({"path": file_path , "length": file["length"]})
            else:
                total_length = torrent.metainfo['info']['length']
                files.append({"path": root, "length": torrent.metainfo['info']['length']})
            
            info_hash = hashlib.sha1(str(torrent.metainfo['info']).encode('utf-8')).digest()
            data = self.create_request(info_hash=info_hash, left=total_length)
        
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
                # Thêm timeout để tránh treo
                sock.settimeout(10)  
                sock.connect(resolve(torrent.metainfo['announce']))
                send(sock, data)

                data = recv(sock)
                if 'failure reason' in data:
                    raise Exception(data['failure reason'])
                
                if 'warning message' in data:
                    print("warning:", data['warning message'])
            
            interval = data.get('interval', 15*60)

            # initialize having_files            
            with self.having_files_lock:
                self.having_files[info_hash] = {
                    'bitfield': [False] * (math.ceil(total_length / PIECE_SIZE)),
                    'files': files
                }
            
            # trying to connect to peers
            connected_peers = []
            peers = [*data.get('peers', [])] * math.ceil(MAX_PEERS_TO_CONNECT / len(data.get('peers', [])))
            for peer in peers:
                if len(connected_peers) >= MAX_PEERS_TO_CONNECT:
                    break
                try:
                    conn = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                    conn.connect((peer['ip'], peer['port']))
                    connected_peers.append((conn, peer))
                    print(f"Connected to {peer['ip']}:{peer['port']} ({len(connected_peers)}/{len(peers)})")
                except Exception as e:
                    print("An error occurred:", e)
                    
            if len(connected_peers) == 0:
                print("No peers available")
                return
                
            # initialize piece count
            with self.piece_count_lock:
                self.piece_count[info_hash] = [{ "count": 0, "index": i, "conns": [] } 
                                               for i in range(math.ceil(total_length / PIECE_SIZE))]
            
            # handshake with peers and exchange bitfield
            for conn, peer in connected_peers:
                send(conn, bytes(Handshake(info_hash, self.peer_id)), is_binary=True)
                data = recv(conn, is_binary=True)
                res_info_hash, res_peer_id = Handshake.from_bytes(data)
                
                # check handshake message
                if data == b"\x00" or res_info_hash != info_hash or res_peer_id != peer['peer_id']:
                    conn.close()
                    connected_peers.remove((conn, peer))
                    continue
        
                # send bitfield
                bitfield = self.having_files[info_hash]['bitfield']
                send(conn, bytes(BitField(bitfield)), is_binary=True)
                
                # receive bitfield
                data = recv(conn, is_binary=True)
                    
                if get_message_type(data) == "bitfield":
                    self.update_piece_count(info_hash, conn, BitField.from_bytes(data))
                
            # check if missing pieces
            with self.piece_count_lock:
                for piece in self.piece_count[info_hash]:
                    if piece['count'] == 0:
                        print("Missing pieces")
                        return
            
            # download pieces
            piece_downloaded, piece_downloaded_lock = [], Lock()
            conn_in_use, conn_in_use_look = [], Lock()
            with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
                # add a thread to update progress
                executor.submit(self.update_progress, 
                                info_hash, 
                                torrent.metainfo['announce'], 
                                interval,
                                piece_downloaded,
                                piece_downloaded_lock)
                
                # max_workers - 1 threads to download pieces
                for i in range(max_workers-1):
                    executor.submit(self.handle_download, 
                                    i,
                                    info_hash, 
                                    total_length, 
                                    piece_downloaded, 
                                    piece_downloaded_lock,
                                    conn_in_use, 
                                    conn_in_use_look,
                                    connected_peers)
            
            print("Download completed")
            
            # combine files
            combine_files(piece_source='temp', files=files)
            
        except Exception as e:
            print("An error occurred:", e)
            
    def handle_download(self, thread_id, info_hash: bytes, total_length: int, piece_downloaded: list, piece_downloaded_lock: Lock, conn_in_use: list, conn_in_use_lock: Lock, connected_peers: list):
        try:
            with self.having_files_lock:
                total_piece = len(self.having_files[info_hash]['bitfield'])
                
            _connected_peers, _peer_name = [], []
            for _conn, _peer in connected_peers:
                if _conn.getpeername() not in _peer_name:
                    _peer_name.append(_conn.getpeername())
                    _connected_peers.append((_conn, _peer))
                
            while True:
                with piece_downloaded_lock:
                    if len(piece_downloaded) >= total_piece:
                        break
                    
                piece = None                    
                with self.piece_count_lock:
                    for _piece in self.piece_count[info_hash]:
                        with self.having_files_lock:
                            is_downloaded_1 = self.having_files[info_hash]['bitfield'][_piece['index']]
                        with piece_downloaded_lock:
                            is_downloaded_2 = _piece in piece_downloaded
                        if not is_downloaded_1 and not is_downloaded_2:
                            piece = _piece
                            self.piece_count[info_hash].remove(_piece)
                            break
                
                if not piece:
                    print(f"Thread {thread_id}: No piece to download")
                    time.sleep(0.5)
                    continue

                conn = None
                piece['conns'].sort(key=lambda x: random.random())
                
                for _conn in piece['conns']:
                    if _conn not in conn_in_use:
                        conn = _conn
                        with conn_in_use_lock:
                            conn_in_use.append(_conn)
                        break

                if not conn:
                    print(f"Thread {thread_id}: No connection available")
                    with self.piece_count_lock:
                        self.piece_count[info_hash].append(piece)
                        self.piece_count[info_hash].sort(key=lambda x: (x['count'], random.random()))
                    time.sleep(0.5)
                    continue
                
                piece_length = PIECE_SIZE
                if piece['index'] == total_piece - 1:
                    piece_length = total_length % PIECE_SIZE if total_length % PIECE_SIZE != 0 else PIECE_SIZE

                piece_data = self.download_piece(conn, piece['index'], piece_length)
                
                if not piece_data:
                    print(f"Thread {thread_id}: Error downloading piece {piece['index']}")
                    with self.having_files_lock:
                        self.having_files[info_hash]['bitfield'][piece['index']] = False
                    with self.piece_count_lock:
                        self.piece_count[info_hash].append(piece)
                    with conn_in_use_lock:
                        conn_in_use.remove(conn)
                    
                    time.sleep(0.5)
                    continue

                with piece_downloaded_lock:
                    piece_downloaded.append(piece)
                with self.having_files_lock:
                    self.having_files[info_hash]['bitfield'][piece['index']] = True
                with self.piece_count_lock:
                    self.piece_count[info_hash].append(piece)
                    self.piece_count[info_hash].sort(key=lambda x: (x['count'], random.random()))
                with conn_in_use_lock:
                    conn_in_use.remove(conn)
                
                write_piece(index=piece['index'], data=piece_data, piece_dest='temp')
                
                with piece_downloaded_lock:
                    print(f"Thread {thread_id}: Downloaded piece {piece['index']} \t ({len(piece_downloaded)}/{total_piece})")
                
                # send have message to all connected peers
                have = Have(piece['index'])
                for _conn, _ in _connected_peers:
                    send(_conn, bytes(have), is_binary=True)
                    res = recv(_conn, is_binary=True)
                    if res != b"\x00":
                        print(f"Thread {thread_id}: Error sending have message")
                    else:
                        print(f"Thread {thread_id}: Sent have message to {_conn.getpeername()}")
                
        except Exception as e:
            print(f"Thread {thread_id}: An error occurred:", e)
            
    def create_request(self, info_hash='', uploaded=0, downloaded=0, left=0, event='started'):
        data = {
            'info_hash': info_hash,
            'peer_id': self.peer_id,
            'port': self.port,
            'uploaded': uploaded,
            'downloaded': downloaded,
            'left': left,
            'event': event
        }
        
        return data
    
    def update_progress(self, info_hash, tracker, interval, piece_downloaded, piece_downloaded_lock):
        try:
            while True:
                with self.having_files_lock:
                    total_piece = len(self.having_files[info_hash]['bitfield'])
                
                with piece_downloaded_lock:
                    downloaded = len(piece_downloaded) * PIECE_SIZE
                    left = (total_piece - len(piece_downloaded)) * PIECE_SIZE
                
                if left == 0:
                    req = self.create_request(info_hash=info_hash, downloaded=downloaded, left=left, event='completed')
                else:
                    req = self.create_request(info_hash=info_hash, downloaded=downloaded, left=left, event='')
                    
                with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
                    sock.connect(resolve(tracker))
                    send(sock, req)
                        
                with piece_downloaded_lock:
                    if len(piece_downloaded) >= total_piece:
                        print("Download completed, stopping progress update")
                        break
                    
                time.sleep(interval)
        except Exception as e:
            print("An error occurred:", e)
            
    def download_block(self, conn, piece_index, block_offset, block_length):
        # send request for block
        request = Request(piece_index, block_offset, block_length)        
        send(conn, bytes(request), is_binary=True)
        
        # receive block
        data = recv(conn, buffer_size=block_length+13, is_binary=True)
        if get_message_type(data) == "piece":
            block = Piece.from_bytes(data)[-1]
            return block
        
        return None
    
    def download_piece(self, conn, piece_index, piece_length):
        piece_data = b''
        for i in range(math.ceil(piece_length / BLOCK_SIZE)):
            block_offset = i * BLOCK_SIZE
            block_length = min(BLOCK_SIZE, piece_length - block_offset)
            data = self.download_block(conn, piece_index, block_offset, block_length)
            if data:
                piece_data += data
            else:
                print("Error downloading piece")
                return None
        
        return piece_data
    

if __name__ == "__main__":
    default_ip = '127.0.0.1'
    port = 6881
    if (len(sys.argv) == 2):
        port = int(sys.argv[1])
    
    peer = Peer(default_ip=default_ip, port=port)
    
    listen_thread = Thread(target=peer.listening_start)
    listen_thread.start()
    time.sleep(0.1)
    
    try:
        while True:
            cmd = input("Enter command: ")
            if cmd == "upload":
                try:
                    src = input("Enter the source file/folder path: ")
                    choice = input("Do you want to create a new torrent file? (y/n): ")
                    if choice.lower() == 'y':
                        # create a torrent file
                        # dest = input("Enter the destination path to save the .torrent file: ")
                        # tracker_url = input("Tracker URL: ")
                        dest = '.'                                          # change it when complete
                        tracker_url = f'http://{default_ip}:22236/announce' # change it when complete
                        path = create_torrent_file(src, tracker_url, dest, PIECE_SIZE)
                        
                        # Upload the original file to database
                        if os.path.isfile(path):
                            file_id = peer.uploader.upload_file(path)
                            if file_id:
                                print(f"File uploaded to database with ID: {file_id}")
                    elif choice.lower() == 'n':
                        path = input("Enter the path to the .torrent file: ")
                    else:
                        print("Invalid choice")
                        continue    
                    
                    torrent = Torrent.read(path)
                    peer.seed(torrent, base_folder=src)
                except Exception as e:
                    print("An error occurred:", e)
                    
            elif cmd == "download":
                try:
                    dest = input("Enter the destination path to save the file/folder: ")
                    
                    # List available files from database
                    peer.downloader.list_files()
                    
                    # Get database file download details
                    file_id = input("\nEnter file ID to download (press Enter to skip): ").strip()
                    if file_id:
                        download_path = input("Enter download path: ")
                        if peer.downloader.download_file(file_id, download_path) is None:
                            print("Failed to download file from database")
                            continue
                    
                    # Continue with torrent download
                    path = input("Enter the path to the .torrent file: ")
                    torrent = Torrent.read(path)
                    peer.download(torrent, dest=dest)
                    
                except Exception as e:
                    print("An error occurred:", e)
                    
            elif cmd == "exit":
                peer.listening_stop()
                listen_thread.join()
                break
    except KeyboardInterrupt:
        peer.listening_stop()
        listen_thread.join()