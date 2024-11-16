import os

PIECE_SIZE = 512 * 1024 # 512KB
BLOCK_SIZE = 16 * 1024  # 16KB

def _find_file_and_offset(files, global_offset):
    """
    Find which file contains the global offset, and the relative offset within that file.
    :param global_offset: The absolute offset in the multi-file structure.
    :return: Tuple of (file index, relative offset)
    """
    cumulative_offsets = [0]
    for f in files:
        cumulative_offsets.append(cumulative_offsets[-1] + f["length"])
        
    for i in range(len(cumulative_offsets) - 1):
        if cumulative_offsets[i] <= global_offset < cumulative_offsets[i + 1]:
            file_offset = global_offset - cumulative_offsets[i]
            return i, file_offset
    return None, None

def read_block(files, index, begin, length):
    global_offset = index * PIECE_SIZE + begin
    file_index, offset = _find_file_and_offset(files, global_offset)
    if file_index is None:
        return None
    
    block_data = b''
    while len(block_data) < length and file_index < len(files):
        file = files[file_index]
        with open(file['path'], 'rb') as f:
            f.seek(offset)
            block_data += f.read(min(length - len(block_data), file['length'] - offset))
        offset = 0
        file_index += 1
    
    return block_data
    
def write_piece(index, data, piece_dest):
    os.makedirs(piece_dest, exist_ok=True)
    
    # Rename the file to a temporary name while writing
    file_path = os.path.join(piece_dest, f"{index}.part")
    
    with open(file_path, 'wb') as f:
        f.write(data)
        
def combine_files(piece_source, files):
    print(f"Starting to combine files from {piece_source}")
    index, buffer = 0, b''
    for file in files:
        file_length, file_path = file['length'], file['path']
        
        if not os.path.exists(os.path.dirname(file_path)):
            os.makedirs(os.path.dirname(file_path), 0o0766)
            
        while len(buffer) < file_length:
            piece_path = os.path.join(piece_source, f"{index}.part")
            with open(piece_path, 'rb') as piece_file:
                data = piece_file.read()
                buffer += data
                
            os.remove(piece_path)  # Delete the piece after reading
            
            index += 1
            
        # Write the required amount to the file
        with open(file_path, 'ab') as f:
            f.write(buffer[:file_length])
        
        # Update the buffer to contain the remainder
        buffer = buffer[file_length:]
        
        print(f"Finished writing {file_path}")
        
    os.removedirs(piece_source)  # Remove the directory after all files are written