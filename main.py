# micropython_shell.py
# A simple UNIX-like shell for MicroPython (ESP32-C3/ESP8266)
# Commands supported: help, ls, cd, pwd, cat, echo, mkdir, rm, touch, edit, exec, wifi, ping

import os
import sys
import network # Module for network control (WiFi, Ethernet)
import socket  # Module for low-level network operations (used by ping)
import time    # Module for timing/delays

# In MicroPython, the os module is usually aliased to uos, 
# but simply importing 'os' works on most platforms.

# --- Global State ---
# The current working directory is maintained here.
# Initialized to the root directory.
cwd = '/' 
# Flag to control the main shell loop
shell_running = True
# Global for WLAN interface
shell_wlan = None

# --- Configuration Constants ---
WIFI_CONFIG_FILE = '/wifi_config.txt' 
# -------------------------------

# Helper function to resolve absolute path
def resolve_path(path):
    """Resolves a path relative to the current working directory (cwd)."""
    global cwd
    if not path.startswith('/'):
        # Relative path
        if cwd == '/':
            full_path = '/' + path
        else:
            full_path = cwd + '/' + path
    else:
        # Absolute path
        full_path = path
        
    # Clean up double slashes
    full_path = full_path.replace('//', '/')
    return full_path

# --- Persistence Helpers ---

def save_wifi_config(ssid, password):
    """Saves WiFi credentials to a persistent file."""
    try:
        # Format: ssid\npassword
        with open(WIFI_CONFIG_FILE, 'w') as f:
            f.write(f"{ssid}\n")
            f.write(f"{password}\n")
        print(f"Configuration saved to {WIFI_CONFIG_FILE}.")
    except OSError as e:
        print(f"Warning: Could not save config file. ({e})")

def load_wifi_config():
    """Loads WiFi credentials from the persistent file."""
    try:
        with open(WIFI_CONFIG_FILE, 'r') as f:
            ssid = f.readline().strip()
            password = f.readline().strip()
            if ssid and password:
                return ssid, password
            else:
                return None, None
    except OSError:
        # File not found or inaccessible, which is expected on first run
        return None, None
    except Exception as e:
        print(f"Warning: Error reading config file. ({e})")
        return None, None

def do_clear_wifi_config():
    """Deletes the persistent WiFi configuration file."""
    try:
        os.remove(WIFI_CONFIG_FILE)
        print(f"Persistent WiFi configuration cleared ({WIFI_CONFIG_FILE} removed).")
    except OSError:
        print("No persistent configuration file found to clear.")


# Function to execute before the loop starts (authentication/setup)
def setup_shell():
    """Sets the initial working directory, prints a welcome message, and initializes networking."""
    global cwd, shell_wlan
    try:
        # MicroPython's os.chdir is based on the underlying filesystem
        os.chdir(cwd)
    except OSError:
        # If the filesystem is not yet mounted or broken, this might fail
        pass
        
    # --- Network Setup ---
    try:
        # Initialize the WiFi Station (client) interface
        shell_wlan = network.WLAN(network.STA_IF)
        shell_wlan.active(True)
        print("WiFi STA interface activated.")
        
        # Check for saved config and attempt auto-connect
        ssid, password = load_wifi_config()
        if ssid and password:
            print(f"Auto-connecting to saved network '{ssid}'...")
            # Use non-blocking connect here, give it a short time to try
            shell_wlan.connect(ssid, password) 
            time.sleep(3) # Give it 3 seconds to try to connect
            if shell_wlan.isconnected():
                print(f"Auto-connect successful! IP: {shell_wlan.ifconfig()[0]}")
            else:
                print("Auto-connect failed or is still in progress.")
        
    except Exception as e:
        print(f"Warning: Failed to initialize WiFi interface. ({e})")
        
    print("-" * 50)
    print("MicroShell v2.2 (wifi scan & ping -t added) on ESP32-C3")
    print("Type 'help' for a list of commands.")
    print("-" * 50)


# --- Command Dispatch and Core Execution ---

def parse_and_execute(command_line):
    """Parses a command line string and executes the command."""
    
    parts = command_line.strip().split()
    
    if not parts:
        return
        
    cmd = parts[0].lower()
    args = parts[1:]
        
    if cmd in commands:
        try:
            commands[cmd](args)
        except Exception as e:
            # Catch unexpected errors during command execution
            print(f"An unexpected error occurred executing '{cmd}': {e}")
    else:
        print(f"Command not found: '{cmd}'.")


# --- Command Implementations ---

def do_help(args):
    """Displays the list of available commands and their usage."""
    print("Available Commands:")
    print("  help                   - Show this help message.")
    print("  ls [path]              - List contents of a directory. (e.g., ls, ls /, ls dir)")
    print("  cd <path>              - Change current directory. (e.g., cd .., cd /)")
    print("  pwd                    - Print the current working directory.")
    print("  cat <file>             - Display contents of a file (Read).")
    print("  echo <text> > <file>   - Write/overwrite <text> to <file> (Write).")
    print("  mkdir <dir_name>       - Create a new directory.")
    print("  rm <path> [-rf]        - Remove a file or an empty directory. Use -rf to delete non-empty folders.")
    print("  touch <filename>       - Create an empty file if it doesn't exist.")
    print("  edit <filename>        - Enter minimal line-by-line text editor.")
    print("  exec <filename>        - Execute commands sequentially from a script file.")
    print("  wifi <cmd>             - Manage WiFi (connect, status, disconnect, **scan**, clear).")
    print("  ping <host> [-t <timeout_s>] [port] - Check reachability with configurable timeout.")
    print("  exit                   - Exit the shell (stops execution).")

def do_pwd(args):
    """Prints the current working directory."""
    print(cwd)

def do_ls(args):
    """Lists files and directories in the specified path or current directory."""
    target_path = cwd
    if args:
        target_path = args[0]
    
    full_path = resolve_path(target_path)

    try:
        # List contents
        contents = os.listdir(full_path)
        
        # Display results
        for item in sorted(contents):
            try:
                # Stat returns information about the file/directory
                # os.stat(path)[0] & 0x4000 checks if it's a directory
                item_path = resolve_path(full_path + '/' + item)
                is_dir = os.stat(item_path)[0] & 0x4000
                if is_dir:
                    print(f"  {item}/") # Directory marker
                else:
                    print(f"  {item}")
            except OSError:
                # Fallback if stat fails (e.g., device files, weird entries)
                print(f"  {item}")
                
    except OSError as e:
        print(f"Error: Cannot access '{target_path}'. ({e})")

def do_cd(args):
    """Changes the current working directory."""
    global cwd
    if not args:
        new_path = '/'
    else:
        new_path = args[0]

    try:
        # Handle '..' explicitly for simplicity
        if new_path == '..':
            if cwd == '/':
                target = '/'
            else:
                target = os.path.dirname(cwd)
        elif new_path == '.':
            target = cwd
        else:
            target = resolve_path(new_path)

        # Clean up path end
        if target.endswith('/') and len(target) > 1:
            target = target[:-1]

        # Check if the target is a directory and exists
        if os.stat(target)[0] & 0x4000:
            os.chdir(target) # Update system's path (optional but good practice)
            cwd = target      # Update shell's path tracking
        else:
            print(f"Error: '{new_path}' is not a directory.")
            return

    except OSError as e:
        print(f"Error: Directory '{new_path}' not found. ({e})")
        return

    print(f"Changed directory to {cwd}")


def do_cat(args):
    """Prints the content of a file."""
    if not args:
        print("Usage: cat <filename>")
        return

    filename = args[0]
    full_path = resolve_path(filename)
    
    try:
        with open(full_path, 'r') as f:
            print(f.read())
    except OSError as e:
        print(f"Error: File '{filename}' not found or cannot be read. ({e})")

def do_echo(args):
    """Writes text to a file (overwrites existing content). Usage: echo <text...> > <filename>"""
    if '>' not in args:
        print("Usage: echo <text...> > <filename>")
        print("Note: This command overwrites the file content.")
        return

    try:
        delimiter_index = args.index('>')
    except ValueError:
        print("Usage: echo <text...> > <filename>")
        return
        
    if delimiter_index == len(args) - 1:
        print("Error: Missing filename after '>'.")
        return

    # Text to write is everything before '>' joined by space
    text_parts = args[:delimiter_index]
    text_to_write = ' '.join(text_parts) + '\n' 

    # Filename is the part immediately after '>'
    filename = args[delimiter_index + 1]
    
    full_path = resolve_path(filename)

    try:
        # Open in write mode ('w') which creates the file if it doesn't exist, 
        # or truncates it if it does.
        with open(full_path, 'w') as f:
            f.write(text_to_write)
        print(f"Content written to '{filename}'.")

    except OSError as e:
        print(f"Error writing to file '{filename}'. ({e})")


def do_mkdir(args):
    """Creates a new directory."""
    if not args:
        print("Usage: mkdir <dirname>")
        return

    dirname = args[0]
    full_path = resolve_path(dirname)

    try:
        os.mkdir(full_path)
        print(f"Directory '{dirname}' created.")
    except OSError as e:
        print(f"Error creating directory: '{dirname}'. ({e})")

def rm_recursive(full_path):
    """Recursively removes directory contents and the directory itself."""
    try:
        # Ensure path is actually a directory before iterating
        if not os.stat(full_path)[0] & 0x4000:
            print(f"Error: Path '{full_path}' is not a directory.")
            return False

        for item in os.listdir(full_path):
            # Construct the full path to the item
            item_path = full_path + '/' + item
            item_path = item_path.replace('//', '/') # Clean up double slashes
            
            try:
                is_dir = os.stat(item_path)[0] & 0x4000
                
                if is_dir:
                    print(f"  [RM-R] Deleting directory: {item_path}")
                    # Recursively call on subdirectory
                    if not rm_recursive(item_path):
                        return False
                else:
                    print(f"  [RM-F] Deleting file: {item_path}")
                    os.remove(item_path) # Delete file
                    
            except OSError as e:
                print(f"  [ERROR] Failed to process {item_path}: {e}")
                return False # Stop on failure
        
        # After deleting all contents, remove the now-empty directory
        os.rmdir(full_path)
        return True
        
    except OSError as e:
        print(f"Error: Cannot access or remove directory '{full_path}'. ({e})")
        return False

def do_rm(args):
    """Removes a file or an empty directory, or recursively deletes with -rf."""
    recursive_force = False
    path_args = []
    
    # Parse arguments for -rf and the path
    for arg in args:
        if arg.lower() == '-rf' or arg.lower() == '-fr':
            recursive_force = True
        else:
            path_args.append(arg)
            
    if not path_args:
        print("Usage: rm <path> [options]")
        print("Options: -rf, -fr (Recursive Force delete)")
        return
        
    # Assume only the first path argument is the target
    path_to_remove = path_args[0]
    full_path = resolve_path(path_to_remove)

    try:
        # Check if the path exists
        stat_result = os.stat(full_path)
        is_dir = stat_result[0] & 0x4000
    except OSError:
        print(f"Error: Path '{path_to_remove}' not found.")
        return

    if is_dir:
        if recursive_force:
            print(f"Starting recursive delete of directory '{path_to_remove}'...")
            if rm_recursive(full_path):
                print(f"Directory '{path_to_remove}' deleted successfully.")
            else:
                print(f"Failed to delete directory '{path_to_remove}'.")
        else:
            try:
                # Try to remove as a simple directory (must be empty)
                os.rmdir(full_path)
                print(f"Directory '{path_to_remove}' removed.")
            except OSError as e:
                print(f"Error: Directory '{path_to_remove}' is not empty. Use 'rm -rf {path_to_remove}' to delete recursively. ({e})")
    else:
        # It's a file
        try:
            os.remove(full_path)
            print(f"File '{path_to_remove}' removed.")
        except OSError as e:
            print(f"Error removing file: '{path_to_remove}'. ({e})")
            
def do_touch(args):
    """Creates an empty file if it doesn't exist."""
    if not args:
        print("Usage: touch <filename>")
        return

    filename = args[0]
    full_path = resolve_path(filename)

    try:
        # Open in append mode ('a') and immediately close. 
        # This creates the file if it doesn't exist.
        with open(full_path, 'a') as f:
            pass 
        
        print(f"File '{filename}' ensured to exist.")

    except OSError as e:
        print(f"Error creating file '{filename}'. ({e})")

def do_exec(args):
    """Executes a script file line by line."""
    if not args:
        print("Usage: exec <script_filename>")
        return

    filename = args[0]
    full_path = resolve_path(filename)
    
    try:
        print(f"--- Executing script: {filename} ---")
        with open(full_path, 'r') as f:
            for line in f:
                line = line.strip()
                # Simple check for comments/empty lines
                if line and not line.startswith('#'):
                    # Explicitly ignore 'exit' commands inside a script file
                    if line.lower().strip().split()[0] == 'exit':
                        print("Warning: 'exit' command ignored inside script execution.")
                        continue # Skip to next line
                        
                    print(f"[RUN] {line}")
                    parse_and_execute(line)
        print(f"--- Script {filename} finished ---")
        
    except OSError as e:
        print(f"Error: Script file '{filename}' not found or cannot be read. ({e})")

def do_edit(args):
    """A minimal line-based editor. Usage: edit <filename>"""
    if not args:
        print("Usage: edit <filename>")
        return

    filename = args[0]
    full_path = resolve_path(filename)
    
    content = []
    
    # Load existing content
    try:
        # Check if file exists and is a file (not a directory)
        if not os.stat(full_path)[0] & 0x4000:
            with open(full_path, 'r') as f:
                # Read content, stripping the trailing newline that MicroPython files often have
                file_content = f.read()
                content = file_content.split('\n')
                # If the last line is empty because of a trailing newline, remove it
                if content and content[-1] == '':
                    content.pop()
            print(f"Editing existing file: {filename} ({len(content)} lines)")
        else:
            print(f"Error: '{filename}' is a directory, cannot edit.")
            return

    except OSError:
        # File not found, proceed to create new file
        print(f"Creating new file: {filename}")
    
    # --- Display Current Content ---
    def display_content():
        print(f"\n--- Content of '{filename}' ({len(content)} lines) ---")
        if not content:
            print("[File is empty]")
        else:
            for i, line in enumerate(content):
                # Use left-padding for line number for alignment
                print(f"[{i+1:>3}] {line}") 
        print("--------------------------------------")
    
    display_content()
    
    # Input loop setup
    print("\n--- Line Command Mode ---")
    print("Enter a line number (e.g., '5') to REPLACE that line.")
    print("Enter 'd [NUM]' (e.g., 'd 5') to DELETE that line.")
    print("Enter 'p' to print the current buffer.")
    print("Any other input will be APPENDED as a new line.")
    print("Type '---SAVE---' to save and exit.")
    print("Type '---END---' to exit without saving.")
    
    while True:
        try:
            # We use a custom prompt that shows the filename and current line count
            line = input(f"EDIT {filename} ({len(content)} lines)>> ").strip() 
        except EOFError:
            print("\nEditor aborted (Ctrl+D). File not saved.")
            return
        except KeyboardInterrupt:
            print("\nEditor interrupted (Ctrl+C). File not saved.")
            return

        parts = line.split()
        
        if line == '---SAVE---':
            break # Exit loop to proceed to save logic
        
        if line == '---END---':
            print("Exiting editor without saving.")
            return 
            
        if not parts:
            # User just pressed Enter
            content.append("")
            print(f"[{len(content)}] '' (Appended)")
            continue
            
        cmd = parts[0].lower()
        
        # --- Print Command ---
        if cmd == 'p':
            display_content()
            continue
            
        # --- Delete Command (d [NUMBER]) ---
        if cmd == 'd' and len(parts) == 2:
            try:
                line_num = int(parts[1])
                if 1 <= line_num <= len(content):
                    deleted_line = content.pop(line_num - 1)
                    print(f"Deleted line {line_num}: '{deleted_line}'")
                else:
                    print(f"Error: Line number {line_num} out of range (1-{len(content)}).")
            except ValueError:
                print(f"Error: Invalid line number provided for delete command.")
            continue

        # --- Replacement Command ([NUMBER]) ---
        try:
            line_num = int(cmd)
            if 1 <= line_num <= len(content):
                print(f"--- Replacing line {line_num} (Current: '{content[line_num - 1]}') ---")
                
                # Enter sub-mode to get the replacement line
                # Note: We must use a separate input call here!
                try:
                    replacement_line = input(f"REPL {line_num}>> ")
                    content[line_num - 1] = replacement_line
                    print(f"Line {line_num} replaced with: '{replacement_line}'")
                except (EOFError, KeyboardInterrupt):
                    print("\nReplacement cancelled.")
            else:
                print(f"Error: Line number {line_num} out of range (1-{len(content)}). Appending instead.")
                content.append(line) # If the user types a number out of range, append the input as text
                print(f"[{len(content)}] {line} (Appended)")
                
        except ValueError:
            # --- Append Command (Default) ---
            # If not a recognized command and not a number, treat as a line to append
            content.append(line)
            print(f"[{len(content)}] {line} (Appended)")
        
    # --- Save and Exit Logic ---
    try:
        with open(full_path, 'w') as f:
            # Join lines with newline characters
            f.write('\n'.join(content) + '\n') 
        print(f"File '{filename}' saved successfully. ({len(content)} lines)")
    except OSError as e:
        print(f"Error saving file '{filename}'. ({e})")

def do_exit(args):
    """Signals the main loop to exit."""
    global shell_running
    shell_running = False

def do_wifi(args):
    """Manages the WiFi connection (connect, status, disconnect, clear, scan)."""
    global shell_wlan
    if shell_wlan is None:
        print("Error: WiFi interface is not initialized.")
        return

    if not args:
        print("Usage: wifi <connect|status|disconnect|scan|clear> [ssid] [password]")
        return
        
    cmd = args[0].lower()

    if cmd == 'status':
        config_exists = False
        try:
            # Check if the config file exists
            os.stat(WIFI_CONFIG_FILE)
            config_exists = True
        except OSError:
            pass 

        print(f"Active: {shell_wlan.active()}")
        if shell_wlan.isconnected():
            print(f"Status: CONNECTED")
            print(f"IP Info: {shell_wlan.ifconfig()}")
        else:
            print(f"Status: DISCONNECTED")
            
        print(f"Config saved: {'YES' if config_exists else 'NO'} (File: {WIFI_CONFIG_FILE})")
            
    elif cmd == 'connect':
        if len(args) < 3:
            print("Usage: wifi connect <ssid> <password>")
            return
        
        ssid = args[1]
        password = args[2]
        
        # Check if already connected to the same network
        if shell_wlan.isconnected() and shell_wlan.config('ssid') == ssid:
            print(f"Already connected to '{ssid}'.")
            return
            
        print(f"Attempting to connect to '{ssid}'...")
        shell_wlan.connect(ssid, password)
        
        # Simple blocking wait for connectivity
        max_wait = 10
        while max_wait > 0:
            if shell_wlan.isconnected():
                break
            max_wait -= 1
            time.sleep(1)
            print(".", end='') 
            
        print() # Newline after dots
        
        if shell_wlan.isconnected():
            print(f"Connected! IP Info: {shell_wlan.ifconfig()}")
            # PERSISTENCE: Save credentials after successful connect
            save_wifi_config(ssid, password)
        else:
            print("Connection failed or timed out.")

    elif cmd == 'disconnect':
        if shell_wlan.isconnected():
            shell_wlan.disconnect()
            print("Disconnected from WiFi.")
        else:
            print("Already disconnected.")
            
    elif cmd == 'clear':
        do_clear_wifi_config()
        
    elif cmd == 'scan':
        print("Scanning for networks (this may take a few seconds)...")
        # scan() returns a list of tuples: (ssid, bssid, channel, RSSI, authmode, hidden)
        scan_results = shell_wlan.scan()
        print("\n--- WiFi Scan Results ---")
        if not scan_results:
            print("No networks found.")
        else:
            # Format and display results
            # Header
            print(f"{'SSID':<30} {'RSSI':<6} {'AUTH':<10} {'CH':<4}")
            print("-" * 50)
            
            auth_modes = {
                0: "OPEN", 1: "WEP", 2: "WPA-PSK", 3: "WPA2-PSK",
                4: "WPA/WPA2-PSK", 5: "WPA2-EAP", 6: "WPA3", 
                7: "WPA2/WPA3" # Common mapping
            }
            
            for ssid, bssid, channel, rssi, authmode, hidden in scan_results:
                # ssid is returned as bytes, decode it to string
                ssid_str = ssid.decode('utf-8')
                auth_str = auth_modes.get(authmode, "UNKNOWN")
                print(f"{ssid_str:<30} {rssi:<6} {auth_str:<10} {channel:<4}")
        print("-------------------------")

    else:
        print(f"Unknown wifi command: {cmd}. Use connect, status, disconnect, scan, or clear.")

def do_ping(args):
    """Checks network reachability to a host using a TCP connection test (proxy for ping)."""
    global shell_wlan
    if shell_wlan is None or not shell_wlan.isconnected():
        print("Error: Not connected to a WiFi network. Use 'wifi connect'.")
        return

    host = None
    port = 80
    timeout = 4.0 # Default timeout (in seconds)

    # 1. Look for the -t flag and value
    try:
        t_index = args.index('-t')
        if t_index + 1 < len(args):
            timeout = float(args[t_index + 1])
            if timeout <= 0:
                raise ValueError
            # Remove -t and its value from args list temporarily
            temp_args = args[:t_index] + args[t_index+2:]
        else:
            print("Error: Missing timeout value after -t. Using default 4.0s.")
            temp_args = args
    except ValueError:
        # -t not found
        temp_args = args
    except Exception as e:
        print(f"Error: Invalid timeout value provided. ({e}). Using default 4.0s.")
        temp_args = args # Fallback
        timeout = 4.0


    # 2. Get host and optional port from remaining arguments
    if len(temp_args) > 0:
        host = temp_args[0]
    if len(temp_args) > 1:
        try:
            port = int(temp_args[1])
            if port <= 0 or port > 65535:
                raise ValueError
        except ValueError:
            print(f"Warning: Invalid port number '{temp_args[1]}' ignored. Using default port 80.")
            port = 80 # Keep default 80 if invalid port given

    if host is None:
        print("Usage: ping <host> [-t <timeout_s>] [port]")
        print("Example: ping google.com -t 2 443")
        return
            
    addr_info = None
    
    try:
        # Resolve host name to IP address
        print(f"Resolving '{host}'...")
        addr_info = socket.getaddrinfo(host, port) 
        
        if not addr_info:
            print(f"Error: Could not resolve host '{host}'.")
            return
            
        (family, socket_type, proto, canonname, sockaddr) = addr_info[0]
        ip_addr = sockaddr[0]

        print(f"Resolved to IP: {ip_addr}. Testing TCP connection on port {port} with timeout {timeout:.1f}s...")

        # Create socket
        s = socket.socket(family, socket_type, proto)
        # Set the configured timeout
        s.settimeout(timeout) 
        
        start_time = time.time()
        
        # Attempt connection
        s.connect(sockaddr)
        
        end_time = time.time()
        
        s.close()

        # Calculate RTT in milliseconds
        rtt_ms = (end_time - start_time) * 1000
        print(f"Success: {host} reachable at {ip_addr}. Time={rtt_ms:.2f}ms")
        
    except OSError as e:
        # Catch connection timeout or failure
        # OSError codes vary, but this covers general network issues
        print(f"Failure: Host '{host}' not reachable on port {port} (Error: {e}).")
    except Exception as e:
        print(f"An unexpected error occurred: {e}")
    finally:
        # Ensure the socket is closed even if an error occurred before s.close()
        if 's' in locals():
            try:
                s.close()
            except Exception:
                pass # Already closed or invalid
            

# --- Command Dispatch Table ---
# Maps command strings to their corresponding handler functions
commands = {
    'help': do_help,
    'ls': do_ls,
    'cd': do_cd,
    'pwd': do_pwd,
    'cat': do_cat,
    'echo': do_echo,
    'mkdir': do_mkdir,
    'rm': do_rm,
    'touch': do_touch,
    'edit': do_edit,
    'exec': do_exec, 
    'exit': do_exit, 
    'wifi': do_wifi, 
    'ping': do_ping, 
}


# --- Main Shell Loop ---

def run_shell():
    """The main loop that reads, parses, and executes commands."""
    setup_shell()
    global shell_running # Must declare global to use the flag
    
    while shell_running:
        try:
            # Get user input. The prompt includes the current working directory.
            # Use a unique prompt to distinguish from standard REPL.
            user_input = input(f"MicroShell:{cwd}$ ") 
        except EOFError:
            # Handle Ctrl+D or disconnection
            print("\nExiting MicroShell...")
            break
        except KeyboardInterrupt:
            # Handle Ctrl+C
            print("\nShell interrupted. Type 'exit' to quit.")
            continue
        
        # Execute the command using the refactored function
        parse_and_execute(user_input)

# Execute the shell when the script is run
if __name__ == "__main__":
    run_shell()
