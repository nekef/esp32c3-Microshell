# MicroShell v2.8
# A simple UNIX-like shell for MicroPython (ESP32/ESP8266)
import uos
import sys
import time
import network
import socket
import machine
import gc  # Added for memory management commands
import micropython # Added for memory tracing

# --- Global State ---
CURRENT_DIR = "/"
SHELL_RUNNING = True
IS_SCRIPTING = False
ALIASES = {} # Stores user-defined command shortcuts

# --- Network Configuration ---
WIFI_CONFIG_FILE = "/wifi_config.txt"
DEFAULT_PING_TIMEOUT = 4.0 # seconds

# --- Utility Functions ---

def resolve_path(path):
    """Resolves relative and absolute paths against the CURRENT_DIR."""
    global CURRENT_DIR
    if path.startswith('/'):
        return path
    
    # Handle single period (current directory)
    if path == '.' or path == './':
        return CURRENT_DIR
        
    # Handle double period (parent directory)
    if path == '..':
        parent = '/'.join(CURRENT_DIR.split('/')[:-1])
        return parent if parent else '/'
    if path.startswith('../'):
        # Complex relative path (e.g., ../../data)
        parts = CURRENT_DIR.split('/')
        if not parts[-1]: # Handle trailing slash case
            parts.pop()
        
        path_parts = path.split('/')
        
        for part in path_parts:
            if part == '..':
                if len(parts) > 1:
                    parts.pop()
                elif parts[0] == '': # At root
                    pass
            elif part and part != '.':
                parts.append(part)
        
        # Rebuild path, ensuring root is maintained
        resolved = '/' + '/'.join(p for p in parts if p)
        return resolved if resolved else '/'


    # Relative path from current directory
    if CURRENT_DIR == '/':
        return '/' + path
    else:
        return CURRENT_DIR + '/' + path

def rm_recursive(path):
    """Recursively removes a directory and all its contents."""
    try:
        if uos.stat(path)[0] & 0x4000:  # Check if it's a directory
            for entry in uos.listdir(path):
                sub_path = resolve_path(path + '/' + entry)
                rm_recursive(sub_path)
            uos.rmdir(path)
            print(f"Removed directory (recursive): {path}")
        else: # It's a file
            uos.remove(path)
            print(f"Removed file: {path}")
        return True
    except OSError as e:
        print(f"Error removing {path}: {e}")
        return False

def cp_recursive(src, dest):
    """Recursively copies a file or directory, handling memory safely."""
    try:
        stats = uos.stat(src)
        is_dir = stats[0] & 0x4000
        
        if is_dir:
            # 1. Create the destination directory
            try:
                uos.mkdir(dest)
            except OSError as e:
                # EEXIST (17) is fine, otherwise raise
                if e.args[0] != 17: raise e
            
            # 2. Iterate and recurse
            for entry in uos.listdir(src):
                # Ensure correct path joining
                src_path = src + ('/' if not src.endswith('/') else '') + entry
                dest_path = dest + ('/' if not dest.endswith('/') else '') + entry
                
                cp_recursive(src_path, dest_path)
        else:
            # It's a file, copy content chunk-by-chunk (512 bytes)
            with open(src, 'rb') as fin:
                with open(dest, 'wb') as fout:
                    while True:
                        buf = fin.read(512) 
                        if not buf:
                            break
                        fout.write(buf)
        return True
    except OSError as e:
        print(f"Error copying {src} to {dest}: {e}")
        return False

def du_recursive(path):
    """Recursively calculates the disk usage of a path in bytes."""
    total_size = 0
    try:
        stats = uos.stat(path)
        is_dir = stats[0] & 0x4000
        
        if is_dir:
            # Add directory entry size (usually negligible but correct for stat)
            total_size += stats[6]
            
            for entry in uos.listdir(path):
                # Skip current and parent directories if they ever appear (MicroPython doesn't list them, but safe check)
                if entry in ('.', '..'):
                    continue

                sub_path = path + ('/' if not path.endswith('/') else '') + entry
                total_size += du_recursive(sub_path)
        else:
            # It's a file, add its size
            total_size += stats[6]
            
    except OSError as e:
        # File/directory not found or inaccessible
        if e.args[0] != 2: # Ignore ENOENT (2) which means file not found/deleted mid-scan
            print(f"Warning: Error accessing {path}: {e}")
        return 0 # Return 0 size on error
        
    return total_size

def format_size(size_bytes):
    """Formats bytes into human-readable string (B, KB, MB)."""
    if size_bytes < 1024:
        return f"{size_bytes} B"
    elif size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.2f} K"
    else:
        return f"{size_bytes / (1024 * 1024):.2f} M"

# --- WiFi Functions (omitted for brevity) ---

def load_wifi_config():
    """Loads saved credentials from file."""
    try:
        with open(WIFI_CONFIG_FILE, 'r') as f:
            ssid = f.readline().strip()
            password = f.readline().strip()
            return ssid, password
    except OSError:
        return None, None

def save_wifi_config(ssid, password):
    """Saves credentials to file."""
    try:
        with open(WIFI_CONFIG_FILE, 'w') as f:
            f.write(ssid + '\n')
            f.write(password + '\n')
        print("Credentials saved for auto-connect.")
    except Exception as e:
        print(f"Error saving config: {e}")

def do_wifi_connect(args):
    """Connects to WiFi and saves credentials."""
    if len(args) != 3:
        print("Usage: wifi connect <ssid> <password>")
        return
    
    ssid, password = args[1], args[2]
    sta_if = network.WLAN(network.STA_IF)
    
    if sta_if.isconnected() and sta_if.config('essid') == ssid:
        print(f"Already connected to '{ssid}'.")
        return

    print(f"Attempting to connect to '{ssid}'...")
    sta_if.active(True)
    sta_if.connect(ssid, password)

    # Wait for connection
    max_wait = 15
    while max_wait > 0:
        if sta_if.isconnected():
            break
        print(".", end="")
        time.sleep(1)
        max_wait -= 1
    
    if sta_if.isconnected():
        print("\nConnection successful!")
        do_wifi_status(None)
        save_wifi_config(ssid, password)
    else:
        sta_if.active(False)
        print("\nConnection failed.")

def do_wifi_status(args):
    """Prints current WiFi status."""
    sta_if = network.WLAN(network.STA_IF)
    if sta_if.isconnected():
        print("Status: CONNECTED")
        print(f"SSID: {sta_if.config('essid')}")
        print(f"IP Info: {sta_if.ifconfig()}")
    else:
        print("Status: DISCONNECTED")
        print("Interface Active: " + ("Yes" if sta_if.active() else "No"))

def do_wifi_scan(args):
    """Scans for available WiFi networks."""
    sta_if = network.WLAN(network.STA_IF)
    if not sta_if.active():
        sta_if.active(True)
    
    print("Scanning for networks... (might take a few seconds)")
    networks = sta_if.scan()
    
    if not networks:
        print("No networks found.")
        return

    print("--------------------------------------------------")
    print("  SSID                     | CH | RSSI | Security")
    print("--------------------------------------------------")
    
    AUTH_MODES = {0: "Open", 1: "WEP", 2: "WPA-PSK", 3: "WPA2-PSK", 4: "WPA/WPA2-PSK", 5: "WPA2-Enterprise"}

    for ssid_bytes, bssid, channel, rssi, authmode, hidden in networks:
        ssid = ssid_bytes.decode('utf-8', 'ignore')
        security = AUTH_MODES.get(authmode, "Unknown")
        print(f"  {ssid:<24} | {channel:<2} | {rssi:<4} | {security}")
    print("--------------------------------------------------")

def do_wifi_disconnect(args):
    """Disconnects WiFi."""
    sta_if = network.WLAN(network.STA_IF)
    if sta_if.isconnected():
        sta_if.disconnect()
        print("Disconnected.")
    else:
        print("Already disconnected.")

def do_wifi_clear(args):
    """Clears saved WiFi config file."""
    try:
        uos.remove(WIFI_CONFIG_FILE)
        print("Saved WiFi configuration cleared.")
    except OSError:
        print("No saved WiFi configuration found to clear.")

def do_wifi(args):
    """Wrapper for wifi sub-commands."""
    if len(args) < 2:
        print("Usage: wifi <connect|status|scan|disconnect|clear>")
        return
    
    command = args[0]
    sub_command = args[1]

    if sub_command == "connect":
        do_wifi_connect(args)
    elif sub_command == "status":
        do_wifi_status(args)
    elif sub_command == "scan":
        do_wifi_scan(args)
    elif sub_command == "disconnect":
        do_wifi_disconnect(args)
    elif sub_command == "clear":
        do_wifi_clear(args)
    else:
        print(f"Unknown 'wifi' subcommand: {sub_command}")


# --- Shell Commands ---

def do_help(args):
    """Displays command list."""
    print("--------------------------------------------------")
    print("MicroShell Commands:")
    print("  help              - Display this list")
    print("  clear             - Clear the terminal screen")
    print("  ls [path]         - List directory contents")
    print("  cd <dir>          - Change directory")
    print("  pwd               - Print working directory")
    print("  cat <file>        - Display file content")
    print("  echo <text> > <file> - Write text to file (overwrite)")
    print("  mkdir <dir>       - Create directory")
    print("  rm <file/dir>     - Remove file or empty directory")
    print("  rm -rf <dir>      - Remove directory recursively (USE WITH CAUTION)")
    print("  mv <src> <dest>   - Move/rename file or directory")
    print("  cp <src> <dest>   - Copy file or directory (recursively)")
    print("  du [path]         - Summarize disk usage of a directory or file")
    print("  df [path]         - Display disk free space (total, used, free)")
    print("  ps                - Display process status (memory/GC info)")
    print("  alias [name=cmd]  - Define, view, or remove command aliases")
    print("  touch <file>      - Create empty file if it doesn't exist")
    print("  edit <file>       - Open minimal line-based text editor")
    print("  exec <script>     - Execute commands from a script file")
    print("  wifi [connect/status/scan/clear] - Manage WiFi connection")
    print("  ping <host> [-t <seconds>] - Check network reachability (TCP)")
    print("  reboot            - Restart the MicroPython device (hard reset)")
    print("  exit              - Exit the MicroShell")
    print("--------------------------------------------------")

def do_clear(args):
    """Clears the console using ANSI escape codes."""
    # ANSI escape code to clear screen (2J) and move cursor to top-left (H)
    sys.stdout.write('\x1b[2J\x1b[H')

def do_ls(args):
    """Lists contents of a directory."""
    path = args[1] if len(args) > 1 else CURRENT_DIR
    resolved_path = resolve_path(path)
    
    try:
        contents = sorted(uos.listdir(resolved_path))
        for item in contents:
            full_path = resolved_path + ("" if resolved_path.endswith('/') else "/") + item
            is_dir = uos.stat(full_path)[0] & 0x4000
            print(f"  {item}{'/' if is_dir else ''}")
    except OSError as e:
        print(f"Error listing directory '{resolved_path}': {e}")

def do_cd(args):
    """Changes the current working directory."""
    global CURRENT_DIR
    if len(args) < 2:
        print(f"Current directory: {CURRENT_DIR}")
        return

    path = args[1]
    resolved_path = resolve_path(path)
    
    try:
        if uos.stat(resolved_path)[0] & 0x4000: # Check if it's a directory
            # Normalize path: remove trailing slash unless it's the root '/'
            if len(resolved_path) > 1 and resolved_path.endswith('/'):
                resolved_path = resolved_path[:-1]
                
            CURRENT_DIR = resolved_path
            print(f"Changed directory to {CURRENT_DIR}")
        else:
            print(f"Error: '{path}' is not a directory.")
    except OSError:
        print(f"Error: Directory '{path}' not found.")

def do_pwd(args):
    """Prints the current working directory."""
    print(CURRENT_DIR)

def do_cat(args):
    """Displays the content of a file."""
    if len(args) < 2:
        print("Usage: cat <file>")
        return
    
    path = resolve_path(args[1])
    try:
        with open(path, 'r') as f:
            while True:
                line = f.readline()
                if not line:
                    break
                print(line.rstrip())
    except OSError as e:
        print(f"Error reading file '{path}': {e}")

def do_echo(args):
    """Writes text to a file (using >) or echoes to console."""
    if '>' in args:
        try:
            split_index = args.index('>')
            content = ' '.join(args[1:split_index])
            path = resolve_path(args[split_index + 1])
            
            with open(path, 'w') as f:
                f.write(content + '\n')
            print(f"Content written to '{path}'.")
            
        except IndexError:
            print("Usage: echo <text> > <file>")
        except OSError as e:
            print(f"Error writing to file: {e}")
    else:
        print(' '.join(args[1:]))

def do_mkdir(args):
    """Creates a new directory."""
    if len(args) < 2:
        print("Usage: mkdir <dir>")
        return
    
    path = resolve_path(args[1])
    try:
        uos.mkdir(path)
        print(f"Directory '{path}' created.")
    except OSError as e:
        print(f"Error creating directory: {e}")

def do_rm(args):
    """Removes a file or directory."""
    if len(args) < 2:
        print("Usage: rm <file/dir> or rm -rf <dir>")
        return

    # Check for -rf flag
    recursive_force = '-rf' in args or '-fr' in args
    
    # Get the target path, ignoring the flags
    path_args = [a for a in args[1:] if a not in ('-rf', '-fr')]
    if not path_args:
        print("Usage: rm <file/dir> or rm -rf <dir>")
        return
        
    path = resolve_path(path_args[0])
    
    try:
        stats = uos.stat(path)
        is_dir = stats[0] & 0x4000
        
        if is_dir:
            if recursive_force:
                rm_recursive(path)
            else:
                uos.rmdir(path)
                print(f"Removed empty directory: {path}")
        else: # It's a file
            uos.remove(path)
            print(f"Removed file: {path}")

    except OSError as e:
        if is_dir and not recursive_force:
            print(f"Error: Directory '{path}' is not empty. Use 'rm -rf' to force removal.")
        else:
            print(f"Error removing '{path}': {e}")

def do_cp(args):
    """Copies a file or directory."""
    if len(args) != 3:
        print("Usage: cp <source> <destination>")
        return

    src_path = resolve_path(args[1])
    dest_path = resolve_path(args[2])
    
    try:
        # 1. Check if source exists
        uos.stat(src_path)
    except OSError:
        print(f"Error: Source '{src_path}' not found.")
        return

    # Determine the final destination path, handling directory targets
    final_dest_path = dest_path
    try:
        # Check if destination is an existing directory
        dest_stats = uos.stat(dest_path)
        if dest_stats[0] & 0x4000: # Destination is a directory
            # Construct the final path: /dest_path/source_filename
            src_filename = src_path.split('/')[-1]
            if not src_filename: # Should only happen if copying '/' (root) which is prohibited
                 print("Error: Cannot copy root directory.")
                 return
            
            if dest_path.endswith('/'):
                final_dest_path = dest_path + src_filename
            else:
                final_dest_path = dest_path + '/' + src_filename
            
    except OSError:
        # Destination path does not exist, use it as the final destination (new file/directory name)
        pass 

    print(f"Copying '{src_path}' to '{final_dest_path}'...")

    if cp_recursive(src_path, final_dest_path):
        print("Copy successful.")
    else:
        print("Copy failed due to an error.")

def do_du(args):
    """Calculates and prints disk usage."""
    path = args[1] if len(args) > 1 else CURRENT_DIR
    resolved_path = resolve_path(path)
    
    print(f"Calculating disk usage for '{resolved_path}'...")
    size = du_recursive(resolved_path)
    
    print(f"{format_size(size):>6}\t{resolved_path}")

def do_df(args):
    """Displays disk free space (total, used, free)."""
    # Use root '/' as the default path for statvfs
    path = args[1] if len(args) > 1 else '/'
    
    try:
        stats = uos.statvfs(path)
        f_frsize = stats[1] # Fragment size (block size used for calculation)
        f_blocks = stats[2] # Total blocks
        f_bfree = stats[3] # Free blocks
        
        # Calculate sizes in bytes
        total_bytes = f_blocks * f_frsize
        free_bytes = f_bfree * f_frsize
        used_bytes = total_bytes - free_bytes

        print("Filesystem        Size    Used   Avail  Use%")
        
        if total_bytes == 0:
            use_percent = 0
        else:
            # Simple integer division for MicroPython
            use_percent = (used_bytes * 100) // total_bytes 

        print(f"{path:<18} {format_size(total_bytes):>6} {format_size(used_bytes):>6} {format_size(free_bytes):>6} {use_percent:>4}%")

    except OSError as e:
        print(f"Error accessing filesystem status for '{path}': {e}")


def do_ps(args):
    """Displays process status (memory and GC information)."""
    print("--- Memory Status (Heap) ---")
    
    # Run garbage collection for accurate numbers
    gc.collect()
    
    free = gc.mem_free()
    alloc = gc.mem_alloc()
    total = free + alloc

    print(f"Total Heap: {format_size(total)}")
    print(f"Allocated:  {format_size(alloc)} ({alloc/total:.1%} used)")
    print(f"Free:       {format_size(free)} ({free/total:.1%} free)")
    
    try:
        # MicroPython specific info
        print("\n--- MicroPython Specific ---")
        micropython.mem_info()
    except AttributeError:
        # Happens if micropython module is not available or doesn't have mem_info
        print("micropython.mem_info() not available on this platform.")

def do_alias(args):
    """Defines, views, or removes command aliases."""
    global ALIASES
    
    if len(args) == 1:
        # View all aliases
        if ALIASES:
            print("--- Current Aliases ---")
            for name, cmd in sorted(ALIASES.items()):
                print(f"alias {name}='{cmd}'")
            print("-----------------------")
        else:
            print("No aliases defined.")
        return

    # Check for name=command syntax
    arg = args[1]
    if '=' in arg:
        name, cmd = arg.split('=', 1)
        name = name.strip()
        cmd = cmd.strip().strip("'\"") # Remove quotes if present
        
        if not name or not cmd:
            print("Usage: alias <name>=<command> or alias -u <name>")
            return
            
        # Prevent aliasing 'alias' itself or critical commands like 'exit'
        if name in COMMANDS and name not in ('exit', 'help', 'clear'): 
            print(f"Warning: Aliasing reserved command '{name}'.")

        ALIASES[name] = cmd
        print(f"Alias set: {name} -> '{cmd}'")
    
    # Check for unalias flag
    elif args[1] in ('-u', '--unset'):
        if len(args) != 3:
            print("Usage: alias -u <name>")
            return
        name = args[2]
        if name in ALIASES:
            del ALIASES[name]
            print(f"Alias '{name}' removed.")
        else:
            print(f"Alias '{name}' not found.")
    
    # Check for single name to resolve/view
    elif len(args) == 2:
        name = args[1]
        if name in ALIASES:
            print(f"alias {name}='{ALIASES[name]}'")
        else:
            print(f"Alias '{name}' not found.")
    
    else:
        print("Usage: alias [name=command] or alias -u <name>")


def do_touch(args):
    """Creates an empty file if it doesn't exist."""
    if len(args) < 2:
        print("Usage: touch <file>")
        return
    
    path = resolve_path(args[1])
    try:
        # Check if file exists by trying to open for read
        uos.stat(path)
        print(f"File '{path}' already exists.")
    except OSError:
        # File doesn't exist, create it (open for append and close immediately)
        try:
            with open(path, 'a'):
                pass
            print(f"File '{path}' created.")
        except OSError as e:
            print(f"Error creating file: {e}")

def do_mv(args):
    """Moves or renames a file/directory."""
    if len(args) != 3:
        print("Usage: mv <source> <destination>")
        return

    src_path = resolve_path(args[1])
    dest_path_raw = args[2] # Keep raw for directory check
    dest_path = resolve_path(dest_path_raw)
    
    try:
        # 1. Check if source exists
        uos.stat(src_path)
    except OSError:
        print(f"Error: Source '{src_path}' not found.")
        return

    try:
        # 2. Check if destination is an existing directory
        dest_stats = uos.stat(dest_path)
        if dest_stats[0] & 0x4000: # Destination is a directory
            # Construct the final path: /dest_path/source_filename
            src_filename = src_path.split('/')[-1]
            if dest_path.endswith('/'):
                final_dest_path = dest_path + src_filename
            else:
                final_dest_path = dest_path + '/' + src_filename
            
    except OSError:
        # Destination path does not exist, so it will be a simple rename/move
        final_dest_path = dest_path

    try:
        uos.rename(src_path, final_dest_path)
        print(f"Moved/Renamed '{src_path}' to '{final_dest_path}'.")
    except OSError as e:
        print(f"Error moving/renaming: {e}")

def do_edit(args):
    """Minimal line-based text editor."""
    if len(args) < 2:
        print("Usage: edit <file>")
        return
        
    path = resolve_path(args[1])
    lines = []
    
    # Load existing content
    try:
        with open(path, 'r') as f:
            lines = [line.rstrip('\n') for line in f]
        print(f"--- Editing existing file: {path} ({len(lines)} lines) ---")
    except OSError:
        print(f"--- Creating new file: {path} ---")

    print("Commands: L<N> <new text> (Replace line N), D<N> (Delete line N)")
    print("Type '---SAVE---' to save and exit, '---END---' to exit without saving.")
    
    while True:
        # Display current content
        for i, line in enumerate(lines):
            print(f"{i+1:02d}: {line}")
            
        try:
            command = input("EDIT>> ")
        except EOFError:
            print("\nExiting editor (unsaved).")
            break
        
        if command == "---SAVE---":
            try:
                with open(path, 'w') as f:
                    f.write('\n'.join(lines))
                print(f"File saved successfully to {path}.")
            except OSError as e:
                print(f"Error saving file: {e}")
            break
        
        if command == "---END---":
            print("Exiting editor without saving changes.")
            break

        if not command:
            continue
            
        # Line Command Mode (L<N> <text> or D<N>)
        if command[0].upper() in ('L', 'D'):
            try:
                parts = command.split(' ', 1)
                action = parts[0][0].upper()
                line_num = int(parts[0][1:])
                idx = line_num - 1
                
                if idx < 0 or idx >= len(lines):
                    print(f"Error: Line number {line_num} is out of range.")
                    continue
                
                if action == 'D':
                    # Delete line
                    lines.pop(idx)
                    print(f"Line {line_num} deleted.")
                elif action == 'L':
                    # Replace line
                    new_text = parts[1] if len(parts) > 1 else ""
                    lines[idx] = new_text
                    print(f"Line {line_num} replaced.")
                
                continue
            except ValueError:
                print("Error: Invalid command format. Use L<N> <text> or D<N>.")
            except IndexError:
                print("Error: Missing text for replace command.")
        
        # Default: Append new line
        lines.append(command)
        print(f"Appended as line {len(lines)}.")

def do_exec(args):
    """Executes commands from a script file."""
    global IS_SCRIPTING
    if len(args) < 2:
        print("Usage: exec <script>")
        return
        
    path = resolve_path(args[1])
    
    try:
        print(f"--- Executing script: {path} ---")
        IS_SCRIPTING = True
        with open(path, 'r') as f:
            while True:
                command = f.readline()
                if not command:
                    break
                command = command.strip()
                
                if command.startswith('#') or not command:
                    continue # Ignore comments and empty lines
                
                print(f"[RUN] {command}")
                # Important: Do not allow 'exit' within a script
                if command.lower() == 'exit':
                    print("Warning: Command 'exit' ignored inside script execution.")
                    continue
                    
                parse_and_execute(command)
                
        IS_SCRIPTING = False
        print(f"--- Script {path} finished ---")
        
    except OSError as e:
        print(f"Error: Script file '{path}' not found or inaccessible: {e}")
    except Exception as e:
        IS_SCRIPTING = False
        print(f"Script execution aborted due to error: {e}")


def do_ping(args):
    """Pings a host using a TCP socket connection."""
    if len(args) < 2:
        print("Usage: ping <host> [port] [-t <seconds>]")
        return

    host = args[1]
    port = 80
    timeout = DEFAULT_PING_TIMEOUT
    
    # Parse optional port and timeout flag
    try:
        # Check if a specific port is provided
        if len(args) > 2 and args[2].isdigit():
            port = int(args[2])
            
        # Check for timeout flag (-t)
        if '-t' in args:
            t_index = args.index('-t')
            if t_index + 1 < len(args):
                timeout = float(args[t_index + 1])
    except (ValueError, IndexError):
        print("Invalid port or timeout value.")
        return

    if not network.WLAN(network.STA_IF).isconnected():
        print("Error: Not connected to WiFi. Use 'wifi connect' first.")
        return

    print(f"Pinging {host}:{port} with timeout {timeout:.1f}s...")

    try:
        addr = socket.getaddrinfo(host, port)[0][-1]
        s = socket.socket()
        s.settimeout(timeout)
        
        start_time = time.ticks_ms()
        s.connect(addr)
        rtt = time.ticks_diff(time.ticks_ms(), start_time)
        
        print(f"Connection successful! RTT: {rtt}ms")
        s.close()
    except OSError as e:
        print(f"Ping failed: {e}")
    except Exception as e:
        print(f"An unexpected error occurred: {e}")

def do_reboot(args):
    """Reboots the device (hard reset)."""
    print("Initiating system reboot...")
    # Give time for the print statement to flush before reset
    time.sleep(1) 
    machine.reset()

def do_exit(args):
    """Exits the shell."""
    global SHELL_RUNNING
    if IS_SCRIPTING:
        print("Warning: Command 'exit' ignored inside script execution.")
        return
    SHELL_RUNNING = False
    print("Exiting MicroShell. Back to REPL.")


COMMANDS = {
    'help': do_help,
    'clear': do_clear,
    'ls': do_ls,
    'cd': do_cd,
    'pwd': do_pwd,
    'cat': do_cat,
    'echo': do_echo,
    'mkdir': do_mkdir,
    'rm': do_rm,
    'mv': do_mv,
    'cp': do_cp, 
    'du': do_du,
    'df': do_df, # New
    'ps': do_ps,
    'alias': do_alias,
    'touch': do_touch,
    'edit': do_edit,
    'exec': do_exec,
    'wifi': do_wifi,
    'ping': do_ping,
    'reboot': do_reboot, # Added reboot command
    'exit': do_exit,
}

def parse_and_execute(command_line):
    """Parses a command line string and executes the corresponding function."""
    global ALIASES
    try:
        command_line = command_line.strip()
        if not command_line:
            return

        # 1. Check for alias expansion
        first_word = command_line.split(None, 1)[0]
        if first_word in ALIASES:
            # Replace alias with the defined command, then continue parsing
            expanded_line = ALIASES[first_word] + command_line[len(first_word):]
            print(f"[Alias Expanded] {expanded_line}")
            command_line = expanded_line
            
        # 2. Execute the (potentially expanded) command
        parts = command_line.split()
        if not parts:
            return

        command = parts[0].lower()
        
        if command in COMMANDS:
            COMMANDS[command](parts)
        else:
            print(f"MicroShell: Command not found: {command}")
            
    except Exception as e:
        print(f"An unexpected error occurred executing '{command_line}': {e}")


def run_shell():
    """The main shell loop."""
    print("--------------------------------------------------")
    print(f"MicroShell v2.8 on {sys.platform.upper()}")
    print("Type 'help' for a list of commands.")
    print("--------------------------------------------------")
    
    # 1. Initialize WiFi interface
    sta_if = network.WLAN(network.STA_IF)
    sta_if.active(True)
    
    # 2. Attempt auto-connect
    ssid, password = load_wifi_config()
    if ssid and password and not sta_if.isconnected():
        print(f"Attempting auto-connect to saved network '{ssid}'...")
        sta_if.connect(ssid, password)
        # Give a brief time for connection
        start_time = time.time()
        while not sta_if.isconnected() and (time.time() - start_time) < 5:
            time.sleep(0.5)
        
        if sta_if.isconnected():
            print("Auto-connect successful.")
            do_wifi_status(None)
        else:
            print("Auto-connect failed. Credentials stored but network unavailable.")


    global SHELL_RUNNING
    global CURRENT_DIR
    
    while SHELL_RUNNING:
        try:
            prompt = f"MicroShell:{CURRENT_DIR}$ "
            command_line = input(prompt)
            parse_and_execute(command_line)

        except KeyboardInterrupt:
            print("\nShell interrupted. Type 'exit' to quit.")
        except EOFError:
            # Handle Ctrl+D (EOF), which also should exit
            do_exit(None)
        except Exception as e:
            # Catch all unexpected runtime errors in the loop
            print(f"Runtime error: {e}")

# If imported, the user runs run_shell(). If run directly, start it.
if __name__ == "__main__":
    run_shell()
