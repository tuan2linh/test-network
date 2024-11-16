import threading

dns_records = {
    "http://127.0.0.1:22236/announce": ("10.220.133.0", 10000),  # Sửa port thành 10000
}

lock = threading.Lock()

def register(domain, host, port):
    with lock:
        for record in dns_records.values():
            if record == (host, port):
                return False
        
        if domain not in dns_records:
            dns_records[domain] = (host, port)
            
        return True

def resolve(domain):
    with lock:
        return dns_records.get(domain, ("0.0.0.0", 0))