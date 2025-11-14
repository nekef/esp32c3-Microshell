# MicroShell v4.5 - Stable Single-Command Mode
# A simple UNIX-like shell for MicroPython (ESP32/ESP8266)
import uos
import sys
import time
import network
import socket # usocket is imported as socket here
import machine
import gc
import micropython
import ssl # Required for HTTPS/port 443 support

# --- Global State ---
CURRENT_DIR = "/"
SHELL_RUNNING = True
IS_SCRIPTING = False
ALIASES = {} # Stores user-defined command shortcuts
# New: Environment Variables
ENV = {
    "USER": "micropython",
    "HOME": "/",
    "PATH": "/bin:/usr/bin",
    "VERSION": "4.5" # Updated version
} 

# --- Network Configuration ---
WIFI_CONFIG_FILE = "/wifi_config.txt"
DEFAULT_PING_TIMEOUT = 4.0 # seconds

# --- Utility Functions ---

def resolve_path(path):
    """Resolves relative and absolute paths against the CURRENT_DIR."""
    global CURRENT_DIR
    if path.startswith('$'):
        var_name = path[1:]
        if var_name in ENV:
            path = ENV[var_name]
        else:
            # If variable not found, treat it as literal path part later
            pass 

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
                # Use resolve_path to handle nested path construction
                sub_path = path + ('/' if not path.endswith('/') else '') + entry
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
                if entry in ('.', '..'):
                    continue

                sub_path = path + ('/' if not path.endswith('/') else '') + entry
                total_size += du_recursive(sub_path)
        else:
            # It's a file, add its size
            total_size += stats[6]
            
    except OSError as e:
        if e.args[0] != 2:
            print(f"Warning: Error accessing {path}: {e}")
        return 0
        
    return total_size

def format_size(size_bytes):
    """Formats bytes into human-readable string (B, KB, MB)."""
    if size_bytes < 1024:
        return f"{size_bytes} B"
    elif size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.2f} K"
    else:
        return f"{size_bytes / (1024 * 1024):.2f} M"

# --- System Initialization (Omitted for brevity) ---
def initialize_filesystem():
    """Ensures core directories are present (mimics system boot setup)."""
    global ENV
    print("--- Filesystem Initialization (dmesg) ---")

    home_dir = ENV['HOME']
    try:
        uos.stat(home_dir)
        print(f"[OK] HOME directory mounted: {home_dir}")
    except OSError:
        try:
            uos.mkdir(home_dir)
            print(f"[OK] HOME directory created: {home_dir}")
        except Exception as e:
            print(f"[FAIL] Could not ensure HOME directory {home_dir}: {e}")

    path_dirs = [d for d in ENV['PATH'].split(':') if d.startswith('/')]

    for full_path in path_dirs:
        try:
            uos.stat(full_path)
            print(f"[OK] System path exists: {full_path}")
            continue
        except OSError:
            pass

        path_parts = [p for p in full_path.split('/') if p]
        current_dir = ""
        success = True
        
        for part in path_parts:
            current_dir += "/" + part
            try:
                uos.stat(current_dir)
            except OSError:
                try:
                    uos.mkdir(current_dir)
                    pass 
                except Exception as e:
                    print(f"[FAIL] Error creating system path {full_path} (Failed at {current_dir}): {e}")
                    success = False
                    break
        
        if success:
            print(f"[OK] System path created: {full_path}")
                
    print("-------------------------------------------\n")


# --- WiFi Functions (Omitted for brevity) ---
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
    if len(args) != 4:
        print("Usage: wifi connect <ssid> <password>")
        return
    
    ssid, password = args[2], args[3]
    sta_if = network.WLAN(network.STA_IF)
    
    if sta_if.isconnected() and sta_if.config('essid') == ssid:
        print(f"Already connected to '{ssid}'.")
        return

    print(f"Attempting to connect to '{ssid}'...")
    sta_if.active(True)
    sta_if.connect(ssid, password)

    max_wait = 15
    while max_wait > 0:
        if sta_if.isconnected():
            break
        sys.stdout.write(".")
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
    sta_if = network.WLAN(network.WLAN_STA)
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
    print(f"MicroShell Commands (v{ENV['VERSION']} - Unrestricted Root Access):")
    print("  help              - Display this list")
    print("  clear             - Clear the terminal screen")
    print("  ls [path]         - List directory contents")
    print("  cd <dir>          - Change directory (full access)")
    print("  pwd               - Print working directory")
    print("  cat <file>        - Display file content")
    print("  echo <text> > <file> - Write text to file (overwrite)")
    print("  mkdir <dir>       - Create directory")
    print("  rm <file/dir>     - Remove file or empty directory")
    print("  rm -rf <dir>      - Remove directory recursively")
    print("  mv <src> <dest>   - Move/rename file or directory")
    print("  cp <src> <dest>   - Copy file or directory")
    print("  du [path]         - Summarize disk usage")
    print("  df [path]         - Display disk free space")
    print("  ps                - Display process status (memory/GC info)")
    print("  alias [name=cmd]  - Define, view, or remove command aliases")
    print("  export [name=val] - Define, view, or remove environment variables") 
    print("  env               - List all environment variables") 
    print("  touch <file>      - Create empty file if it's not exist")
    print("  edit <file>       - Open minimal line-based text editor")
    print("  exec <script>     - Execute commands from a script file")
    print("  wifi [...]        - Manage WiFi connection")
    print("  ping <host> [...] - Check network reachability (TCP)")
    print("  curl <url>        - Fetch content from a URL via HTTP/HTTPS GET")
    print("  ifconfig          - Display network interface configuration (IP/MAC/RSSI)")
    print("  reboot            - Restart the MicroPython device")
    print("  exit              - Exit the MicroShell to REPL")
    print("--------------------------------------------------")

def do_curl(args):
    """Fetches content from a URL via HTTP GET (basic curl)."""
    if len(args) < 2:
        sys.stdout.write("Usage: curl <http://host/path> or <https://host/path>\n")
        return

    url = args[1]
    
    is_secure = url.startswith('https://')
    port = 443 if is_secure else 80

    if url.startswith('http://'):
        url_stripped = url[7:]
    elif url.startswith('https://'):
        url_stripped = url[8:]
    else:
        sys.stdout.write("Error: URL must start with http:// or https://\n")
        return

    try:
        host, path = url_stripped.split('/', 1)
        path = '/' + path
    except ValueError:
        host = url_stripped
        path = '/'
        
    # Network check
    sta_if = network.WLAN(network.STA_IF)
    if not sta_if.isconnected():
        sys.stdout.write("Error: Not connected to WiFi. Use 'wifi connect' first.\n")
        return

    sys.stdout.write(f"Fetching {host}:{port}{path}\n")
    
    s = None
    try:
        if is_secure and 'ssl' not in sys.modules:
            sys.stdout.write("Error: HTTPS requires the 'ssl' module, which is not available in this build.\n")
            return

        # 1. Resolve host IP
        addr_info = socket.getaddrinfo(host, port)
        addr = addr_info[0][-1]

        # 2. Create socket and connect
        s = socket.socket()
        s.settimeout(10.0)

        if is_secure:
            # Wrap socket with SSL/TLS
            s.connect(addr)
            # Use server_hostname for SNI (Server Name Indication)
            s = ssl.wrap_socket(s, server_hostname=host) 
        else:
            s.connect(addr)
        
        # 3. Send HTTP GET request
        request = f"GET {path} HTTP/1.1\r\nHost: {host}\r\nUser-Agent: MicroShell/{ENV['VERSION']}\r\nConnection: close\r\n\r\n"
        s.send(request.encode())
        
        # 4. Receive and print data
        sys.stdout.write("\n--- HTTP Response Headers ---\n\n")
        
        content_started = False
        
        while True:
            data = s.recv(512)
            if not data:
                break
                
            data_str = data.decode('utf-8', 'ignore')
            
            if not content_started:
                try:
                    # Find the end of the headers (\r\n\r\n)
                    header_end = data_str.index('\r\n\r\n')
                    headers = data_str[:header_end]
                    body = data_str[header_end + 4:]
                    
                    sys.stdout.write(headers)
                    sys.stdout.write("\n\n--- Response Body ---\n\n")
                    sys.stdout.write(body)
                    content_started = True
                except ValueError:
                    # Still reading headers
                    sys.stdout.write(data_str)
            else:
                # Already past headers, just print body content
                sys.stdout.write(data_str)

        sys.stdout.write("\n")
        
    except OSError as e:
        sys.stdout.write(f"\nError connecting or receiving data: {e}\n")
    except Exception as e:
        sys.stdout.write(f"\nAn unexpected curl error occurred: {e}\n")
    finally:
        if s:
            s.close()
            sys.stdout.write("Connection closed.\n")

def do_ifconfig(args):
    """Displays detailed network interface information."""
    sta_if = network.WLAN(network.STA_IF)
    mac = ':'.join('{:02x}'.format(b) for b in sta_if.config('mac'))
    
    sys.stdout.write("\nwlan0 (Wi-Fi Station Interface)\n")
    sys.stdout.write(f"  Link status: {'UP' if sta_if.isconnected() else 'DOWN'}\n")
    sys.stdout.write(f"  MAC address: {mac}\n")
    
    if sta_if.isconnected():
        try:
            ip, netmask, gw, dns = sta_if.ifconfig()
            rssi = sta_if.status('rssi')
            ssid = sta_if.config('essid')
            
            sys.stdout.write(f"  SSID: {ssid}\n")
            sys.stdout.write(f"  IP Address: {ip}\n")
            sys.stdout.write(f"  Netmask: {netmask}\n")
            sys.stdout.write(f"  Gateway: {gw}\n")
            sys.stdout.write(f"  DNS: {dns}\n")
            sys.stdout.write(f"  Signal (RSSI): {rssi} dBm\n")
        except Exception as e:
            sys.stdout.write(f"  Warning: Could not retrieve full IP configuration: {e}\n")
    else:
        sys.stdout.write("  Status: Disconnected\n")
    sys.stdout.write("-" * 20 + '\n')


def do_env(args):
    """Lists all environment variables."""
    global ENV
    sys.stdout.write("--- Environment Variables ---\n")
    for name, value in sorted(ENV.items()):
        sys.stdout.write(f"{name}={value}\n")
    sys.stdout.write("-----------------------------\n")

def do_export(args):
    """Defines, views, or removes environment variables."""
    global ENV
    
    if len(args) == 1:
        do_env(args)
        return

    arg = args[1]
    if '=' in arg:
        name, value = arg.split('=', 1)
        name = name.strip()
        value = value.strip().strip("'\"")
        
        if not name or not value:
            print("Usage: export <NAME=value> or export <NAME> (to remove)")
            return
            
        ENV[name] = value
        print(f"Exported: {name}='{value}'")
    
    elif len(args) == 2:
        name = args[1]
        if name in ENV:
            del ENV[name]
            print(f"Variable '{name}' unset.")
        else:
            print(f"Error: Environment variable '{name}' not found.")
    
    else:
        print("Usage: export <NAME=value> or export <NAME> (to unset)")


def do_clear(args):
    """Clears the console using ANSI escape codes."""
    sys.stdout.write('\x1b[2J\x1b[H')

def do_ls(args):
    """Lists contents of a directory."""
    path = args[1] if len(args) > 1 else CURRENT_DIR
    resolved_path = resolve_path(path)
    
    try:
        contents = sorted(uos.listdir(resolved_path))
        for item in contents:
            full_path = resolved_path + ("" if resolved_path.endswith('/') else "/") + item
            # stat can fail if file system is unstable, use a try-except here
            try:
                is_dir = uos.stat(full_path)[0] & 0x4000
                is_dir_suffix = '/' if is_dir else ''
            except OSError:
                is_dir_suffix = ' (error)'
            
            # Print to standard output
            sys.stdout.write(f"  {item}{is_dir_suffix}\n") 
    except OSError as e:
        sys.stdout.write(f"Error listing directory '{resolved_path}': {e}\n")

def do_cd(args):
    """Changes the current working directory."""
    global CURRENT_DIR
    if len(args) < 2:
        print(f"Current directory: {CURRENT_DIR}")
        return

    path = args[1]
    resolved_path = resolve_path(path)
    
    try:
        if uos.stat(resolved_path)[0] & 0x4000:
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
    sys.stdout.write(CURRENT_DIR + '\n')

def do_cat(args):
    """Displays the content of a file."""
    
    if len(args) < 2:
        sys.stdout.write("Usage: cat <file>\n")
        return
    
    path = resolve_path(args[1])
    
    try:
        with open(path, 'r') as f:
            while True:
                line = f.readline()
                if not line:
                    break
                # Print to standard output
                sys.stdout.write(line) 
    except OSError as e:
        sys.stdout.write(f"Error reading file '{path}': {e}\n")

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
        # Echo to console
        sys.stdout.write(' '.join(args[1:]) + '\n')

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

    recursive_force = '-rf' in args or '-fr' in args
    
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
        else:
            uos.remove(path)
            print(f"Removed file: {path}")

    except OSError as e:
        if 'is not empty' in str(e):
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
        uos.stat(src_path)
    except OSError:
        print(f"Error: Source '{src_path}' not found.")
        return

    final_dest_path = dest_path
    try:
        dest_stats = uos.stat(dest_path)
        if dest_stats[0] & 0x4000:
            src_filename = src_path.split('/')[-1]
            if not src_filename: 
                 print("Error: Cannot copy root directory.")
                 return
            
            if dest_path.endswith('/'):
                final_dest_path = dest_path + src_filename
            else:
                final_dest_path = dest_path + '/' + src_filename
            
    except OSError:
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
    
    size = du_recursive(resolved_path)
    
    # Print in the format expected
    sys.stdout.write(f"{format_size(size):>6}\t{resolved_path}\n")

def do_df(args):
    """Displays disk free space (total, used, free)."""
    path = args[1] if len(args) > 1 else '/'
    
    try:
        stats = uos.statvfs(path)
        f_frsize = stats[1]
        f_blocks = stats[2]
        f_bfree = stats[3]
        
        total_bytes = f_blocks * f_frsize
        free_bytes = f_bfree * f_frsize
        used_bytes = total_bytes - free_bytes

        sys.stdout.write("Filesystem        Size    Used   Avail  Use%\n")
        
        if total_bytes == 0:
            use_percent = 0
        else:
            use_percent = (used_bytes * 100) // total_bytes 

        # Print in the standard format
        sys.stdout.write(f"{path:<18} {format_size(total_bytes):>6} {format_size(used_bytes):>6} {format_size(free_bytes):>6} {use_percent:>4}%\n")

    except OSError as e:
        sys.stdout.write(f"Error accessing filesystem status for '{path}': {e}\n")


def do_ps(args):
    """Displays process status (memory and GC information)."""
    
    gc.collect()
    
    free = gc.mem_free()
    alloc = gc.mem_alloc()
    total = free + alloc

    # Print to standard output
    sys.stdout.write("--- Memory Status (Heap) ---\n")
    sys.stdout.write(f"Total Heap: {format_size(total)}\n")
    sys.stdout.write(f"Allocated:  {format_size(alloc)} ({alloc/total:.1%} used)\n")
    sys.stdout.write(f"Free:       {format_size(free)} ({free/total:.1%} free)\n")
    
    try:
        sys.stdout.write("\n--- MicroPython Specific ---\n")
        micropython.mem_info() # This prints directly to stdout
    except AttributeError:
        sys.stdout.write("micropython.mem_info() not available on this platform.\n")


def do_alias(args):
    """Defines, views, or removes command aliases."""
    global ALIASES
    
    if len(args) == 1:
        if ALIASES:
            print("--- Current Aliases ---")
            for name, cmd in sorted(ALIASES.items()):
                print(f"alias {name}='{cmd}'")
            print("-----------------------")
        else:
            print("No aliases defined.")
        return
    # ... (rest of do_alias logic remains the same)
    arg = args[1]
    if '=' in arg:
        name, cmd = arg.split('=', 1)
        name = name.strip()
        cmd = cmd.strip().strip("'\"")
        
        if not name or not cmd:
            print("Usage: alias <name>=<command> or alias -u <name>")
            return
            
        ALIASES[name] = cmd
        print(f"Alias set: {name} -> '{cmd}'")
    
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
        uos.stat(path)
        print(f"File '{path}' already exists.")
    except OSError:
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
    dest_path_raw = args[2]
    dest_path = resolve_path(dest_path_raw)
    
    try:
        uos.stat(src_path)
    except OSError:
        print(f"Error: Source '{src_path}' not found.")
        return

    try:
        dest_stats = uos.stat(dest_path)
        if dest_stats[0] & 0x4000:
            src_filename = src_path.split('/')[-1]
            if dest_path.endswith('/'):
                final_dest_path = dest_path + src_filename
            else:
                final_dest_path = dest_path + '/' + src_filename
            
    except OSError:
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
    
    try:
        with open(path, 'r') as f:
            lines = [line.rstrip('\n') for line in f]
        print(f"--- Editing existing file: {path} ({len(lines)} lines) ---")
    except OSError:
        print(f"--- Creating new file: {path} ---")

    print("Commands: L<N> <new text> (Replace line N), D<N> (Delete line N)")
    print("Type '---SAVE---' to save and exit, '---END---' to exit without saving.")
    
    while True:
        for i, line in enumerate(lines):
            print(f"{i+1:02d}: {line}")
            
        try:
            command = input("EDIT>> ")
        except EOFError:
            print("\nExiting editor (unsaved).")
            break
        
        if command == "---SAVE---":
            try:
                # Use 'w' mode to overwrite and save
                with open(path, 'w') as f:
                    # Write lines and re-add newlines 
                    f.write('\n'.join(lines))
                    # Ensure file ends with a newline, but only if there are lines
                    if lines:
                        f.write('\n') 
                print(f"File saved successfully to {path}.")
            except OSError as e:
                print(f"Error saving file: {e}")
            break
        
        if command == "---END---":
            print("Exiting editor without saving changes.")
            break

        if not command:
            continue
            
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
                    lines.pop(idx)
                    print(f"Line {line_num} deleted.")
                elif action == 'L':
                    new_text = parts[1] if len(parts) > 1 else ""
                    lines[idx] = new_text
                    print(f"Line {line_num} replaced.")
                
                continue
            except ValueError:
                print("Error: Invalid command format. Use L<N> <text> or D<N>.")
            except IndexError:
                print("Error: Missing text for replace command.")
        
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
                    continue
                
                print(f"[SCRIPT] > {command}")
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
    """Pings a host using a TCP socket connection (simulating ICMP)."""
    host = None
    port = 80
    count = 4
    timeout = DEFAULT_PING_TIMEOUT

    i = 1
    while i < len(args):
        arg = args[i]
        if arg == '-c' and i + 1 < len(args):
            try:
                count = int(args[i+1])
                i += 1
            except ValueError:
                sys.stdout.write("Invalid count value for -c.\n")
                return
        elif arg == '-t' and i + 1 < len(args):
            try:
                timeout = float(args[i+1])
                i += 1
            except ValueError:
                sys.stdout.write("Invalid timeout value for -t.\n")
                return
        elif not host:
            host = arg
        else:
            try:
                port_check = int(arg)
                if port_check > 0 and port_check < 65536:
                    port = port_check
                else:
                    sys.stdout.write(f"Unknown argument: {arg}\n")
                    return
            except ValueError:
                sys.stdout.write(f"Unknown argument: {arg}\n")
                return
        i += 1
        
    if not host:
        sys.stdout.write("Error: Hostname is required.\nUsage: ping <host> [-c <count>] [-t <timeout_s>]\n")
        return

    sta_if = network.WLAN(network.STA_IF)
    if not sta_if.isconnected():
        sys.stdout.write("Error: Not connected to WiFi. Use 'wifi connect' first.\n")
        return
        
    rtts = []
    packets_sent = 0
    packets_received = 0
    
    try:
        addr_info = socket.getaddrinfo(host, port)[0]
        addr = addr_info[-1]
        ip_addr = addr[0]
    except OSError as e:
        sys.stdout.write(f"ping: cannot resolve {host}: Name or service not known ({e})\n")
        return
    
    sys.stdout.write(f"PING {host} ({ip_addr}): TCP port {port} check\n")
    
    for seq in range(1, count + 1):
        packets_sent += 1
        s = None
        try:
            s = socket.socket()
            s.settimeout(timeout)
            
            start_time = time.ticks_ms()
            s.connect(addr)
            rtt = time.ticks_diff(time.ticks_ms(), start_time)
            
            SIMULATED_DATA_BYTES = 64
            SIMULATED_TTL = 64 

            sys.stdout.write(f"{SIMULATED_DATA_BYTES} bytes from {ip_addr}: icmp_seq={seq} ttl={SIMULATED_TTL} time={rtt} ms\n")
            
            packets_received += 1
            rtts.append(rtt)
            s.close()

        except OSError as e:
            if e.args[0] == 110: 
                sys.stdout.write(f"Request timeout for icmp_seq {seq}\n")
            else:
                sys.stdout.write(f"Error for icmp_seq {seq}: {e}\n")
            if s:
                s.close()
        except Exception as e:
            sys.stdout.write(f"An unexpected error occurred for seq {seq}: {e}\n")
            if s:
                s.close()

        time.sleep(1)

    sys.stdout.write(f"\n--- {host} ping statistics ---\n")
    loss = 0.0
    if packets_sent > 0:
        loss = ((packets_sent - packets_received) / packets_sent) * 100.0

    sys.stdout.write(f"{packets_sent} packets transmitted, {packets_received} received, {loss:.1f}% packet loss\n")
    
    if rtts:
        min_rtt = min(rtts)
        max_rtt = max(rtts)
        avg_rtt = sum(rtts) / len(rtts)
        mdev = (sum(abs(r - avg_rtt) for r in rtts) / len(rtts))
        
        sys.stdout.write(f"rtt min/avg/max/mdev = {min_rtt:.3f}/{avg_rtt:.3f}/{max_rtt:.3f}/{mdev:.3f} ms\n")
    sys.stdout.write("\n")


def do_reboot(args):
    """Reboots the device (hard reset)."""
    print("Initiating system reboot...")
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
    'df': do_df,
    'ps': do_ps,
    'alias': do_alias,
    'export': do_export, 
    'env': do_env,       
    'touch': do_touch,
    'edit': do_edit,
    'exec': do_exec,
    'wifi': do_wifi, 
    'ping': do_ping,
    'curl': do_curl,
    'ifconfig': do_ifconfig, 
    'reboot': do_reboot,
    'exit': do_exit,
}

def expand_variables(text):
    """Replaces $VARIABLE with its value from the ENV dictionary."""
    global ENV
    expanded_text = text
    
    i = 0
    while i < len(expanded_text):
        if expanded_text[i] == '$':
            j = i + 1
            var_name = ""
            while j < len(expanded_text) and (expanded_text[j].isalnum() or expanded_text[j] == '_'):
                var_name += expanded_text[j]
                j += 1
            
            if var_name in ENV:
                value = ENV[var_name]
                expanded_text = expanded_text[:i] + value + expanded_text[j:]
                i += len(value)
                continue
            
        i += 1
        
    return expanded_text


def parse_and_execute(command_line):
    """Parses a single command line string, handles alias/env expansion, and executes."""
    global ALIASES
    try:
        command_line = command_line.strip()
        if not command_line:
            return
            
        # 1. Expand variables
        expanded_line = expand_variables(command_line)

        # 2. Split into arguments (for alias check)
        parts = expanded_line.split()
        if not parts:
            return

        # 3. Handle Alias Expansion
        command = parts[0].lower()
        if command in ALIASES:
            aliased_command = ALIASES[command]
            rest_of_line = expanded_line[len(command):].lstrip()
            # Reconstruct the command line with the alias definition
            expanded_line = f"{aliased_command} {rest_of_line}"
            if not IS_SCRIPTING:
                print(f"[Alias Expanded] {expanded_line}")
            
            # Re-split parts after full expansion
            parts = expanded_line.split()
            if not parts:
                return
            command = parts[0].lower() # Re-evaluate command after alias expansion

        if command not in COMMANDS:
            print(f"MicroShell: Command not found: {command}")
            return

        command_func = COMMANDS[command]
        
        # 4. Execute the command directly
        command_func(parts)
            
    except Exception as e:
        print(f"An unexpected error occurred executing '{command_line}': {e}")


def run_shell():
    """The main shell loop."""
    global ENV
    
    # 0. Initialize File System
    initialize_filesystem()
    
    print("--------------------------------------------------")
    print(f"MicroShell v{ENV['VERSION']} on {sys.platform.upper()} (Stable Single-Command Mode)")
    print("WARNING: All file operations are unrestricted.")
    print("Note: Piping (|) and 'grep' have been disabled for stability.")
    print("--------------------------------------------------")
    
    # 1. Initialize WiFi interface
    sta_if = network.WLAN(network.STA_IF)
    sta_if.active(True)
    
    # 2. Attempt auto-connect
    ssid, password = load_wifi_config()
    if ssid and password and not sta_if.isconnected():
        print(f"Attempting auto-connect to saved network '{ssid}'...")
        sta_if.connect(ssid, password)
        start_time = time.time()
        while not sta_if.isconnected() and (time.time() - start_time) < 5:
            time.sleep(0.5)
        
        if sta_if.isconnected():
            print("Auto-connect successful.")
            do_wifi_status(None)
        else:
            print("Auto-connect failed. Credentials stored but network unavailable.")


    global SHELL_RUNNING, CURRENT_DIR
    
    while SHELL_RUNNING:
        try:
            ENV['PWD'] = CURRENT_DIR
            prompt = f"{ENV['USER']}@{ENV['VERSION']}:{CURRENT_DIR} # "

            command_line = input(prompt)
            parse_and_execute(command_line)

        except KeyboardInterrupt:
            print("\nShell interrupted. Type 'exit' to quit.")
        except EOFError:
            do_exit(None)
        except Exception as e:
            print(f"Runtime error: {e}")

# If imported, the user runs run_shell(). If run directly, start it.
if __name__ == "__main__":
    run_shell()
