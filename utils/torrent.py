import os
from torf import Torrent

def create_torrent_file(file_path, tracker_url, dest, piece_size):
    torrent = Torrent(path=file_path, trackers=[tracker_url], piece_size=piece_size)
    torrent.generate()
    torrent_name = os.path.join(dest, os.path.basename(file_path) + '.torrent')
    torrent.write(torrent_name)
    return torrent_name