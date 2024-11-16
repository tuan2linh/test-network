from struct import pack, unpack
from bitarray import bitarray
import socket
import json
import base64

TIMEOUT = 90  # Tăng timeout lên 90 giây
DEFAULT_BUFFER_SIZE = 8*1024  # Tăng từ 1KB lên 8KB

def encode_binary_data(data):
    '''Recursively encode binary data to be JSON serializable'''
    if isinstance(data, bytes):
        return 'b64:' + base64.b64encode(data).decode('utf-8')
    elif isinstance(data, dict):
        return {k: encode_binary_data(v) for k, v in data.items()}
    elif isinstance(data, list):
        return [encode_binary_data(item) for item in data]
    return data

def decode_binary_data(data):
    '''Recursively decode binary data encoded with encode_binary_data'''
    if isinstance(data, str) and data.startswith('b64:'):
        return base64.b64decode(data[4:])
    elif isinstance(data, dict):
        return {k: decode_binary_data(v) for k, v in data.items()}
    elif isinstance(data, list):
        return [decode_binary_data(item) for item in data]
    return data

def send(sock: socket.socket, data, is_binary=False):
    if not is_binary:
        try:
            encoded_data = encode_binary_data(data)
            data_bytes = json.dumps(encoded_data).encode('utf-8')
            # Thêm timeout khi gửi
            sock.settimeout(TIMEOUT)  # Sử dụng timeout 90s
            sock.send(data_bytes)
        except socket.timeout:
            raise Exception(f"Send timeout after {TIMEOUT}s")
    else:
        sock.send(data)

def recv(sock: socket.socket, is_binary=False, buffer_size=DEFAULT_BUFFER_SIZE):
    try:
        # Thêm timeout khi nhận
        sock.settimeout(TIMEOUT)  # Sử dụng timeout 90s
        data = sock.recv(buffer_size)
        if not is_binary:
            data_dict = json.loads(data.decode('utf-8'))
            decoded_data = decode_binary_data(data_dict)
            return decoded_data
        return data
    except socket.timeout:
        raise Exception(f"Receive timeout after {TIMEOUT}s")


# Message types for communication between peers
def get_message_type(data):
    if not data:
        return "unknown"
    
    # check handshake message
    if len(data) >= 68 and data[:20] == b'\x13BitTorrent protocol':
        return "handshake"
    
    message_types = {
        0: "choke",
        1: "unchoke",
        2: "interested",
        3: "not interested",
        4: "have",
        5: "bitfield",
        6: "request",
        7: "piece",
        8: "cancel",
        20: "extension"
    }
    
    length, id = unpack('>IB', data[:5])
    return message_types.get(id, "unknown")

class Handshake:
    def __init__(self, info_hash, peer_id):
        self.pstr = b"BitTorrent protocol"
        self.pstrlen = len(self.pstr)
        self.reserved = b"\x00\x00\x00\x00\x00\x00\x00\x00"
        self.info_hash = info_hash
        self.peer_id = peer_id
        
    def __bytes__(self):
        return pack('>B19s8s20s20s', self.pstrlen, self.pstr, self.reserved, self.info_hash, self.peer_id)
    
    @staticmethod
    def from_bytes(data):
        pstrlen, pstr, reserved, info_hash, peer_id = unpack('>B19s8s20s20s', data)
        return info_hash, peer_id
    
    
class BitField:
    def __init__(self, bitfield):
        self.bitfield = bytes([1 if bit else 0 for bit in bitfield])
        self.length = len(self.bitfield)
        
    def __bytes__(self):
        return pack(">IB{}s".format(self.length),
                    self.length + 1,
                    5,
                    self.bitfield)
        
    @staticmethod
    def from_bytes(data):
        payload_length, message_id = unpack(">IB", data[:5])
        bitfield_length = payload_length - 1

        raw_bitfield, = unpack(">{}s".format(bitfield_length), data[5:5 + bitfield_length])
        bitfield = [bool(b) for b in raw_bitfield]
        return bitfield
    
    
class Request:
    def __init__(self, index, begin, length):
        self.index = index
        self.begin = begin
        self.length = length
        
    def __bytes__(self):
        return pack('>IBIII', 13, 6, self.index, self.begin, self.length)
    
    @staticmethod
    def from_bytes(data):
        length, id, index, begin, length = unpack('>IBIII', data)
        return index, begin, length
    

class Piece:
    def __init__(self, index, begin, block):
        self.index = index
        self.begin = begin
        self.block = block
        
    def __bytes__(self):
        return pack(">IBII{}s".format(len(self.block)),
                    9 + len(self.block),
                    7,
                    self.index,
                    self.begin,
                    self.block)
        
    @staticmethod
    def from_bytes(data):
        length, id, index, begin, block = unpack(">IBII{}s".format(len(data) - 13), data)
        return index, begin, block
        
class Have:
    def __init__(self, index):
        self.index = index
        
    def __bytes__(self):
        return pack('>IBI', 5, 4, self.index)
    
    @staticmethod
    def from_bytes(data):
        length, id, index = unpack('>IBI', data)
        return index
    
class Cancel:
    def __init__(self, index, begin, length):
        self.index = index
        self.begin = begin
        self.length = length
        
    def __bytes__(self):
        return pack('>IBIII', 13, 8, self.index, self.begin, self.length)
    
    @staticmethod
    def from_bytes(data):
        length, id, index, begin, length = unpack('>IBIII', data)
        return index, begin, length