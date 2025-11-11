# ESP32c3-Microshell

**ESP32c3-Microshell** is an open source mini operating system for the ESP32-C3 platform, powered by MicroPython. Inspired by traditional Unix shells like `bash`, it provides a familiar environment for file management and scripting on embedded devices.

## Features

- Interactive shell interface
- File operations: create, read, write, delete
- Directory navigation: `ls`, `pwd`, etc.
- Minimal script execution and automation
- Lightweight and designed for microcontrollers
- Built-in commands similar to POSIX shells
- **Automatic startup:** The shell runs automatically upon boot—just connect and start using!

## Development Environment

- Built for the ESP32-C3 microcontroller.
- Developed with [ESP-IDF](https://docs.espressif.com/projects/esp-idf/en/latest/esp32c3/) (Espressif IoT Development Framework).
- Works with [MicroPython](https://micropython.org/download/esp32c3/).
- Easy flashing and file management using [Thonny IDE](https://thonny.org/) (recommended for beginners).

## Getting Started

### Requirements

- ESP32-C3 board
- ESP-IDF installed (for advanced development)
- MicroPython firmware for ESP32-C3 ([Download here](https://micropython.org/download/esp32c3/))
- A serial terminal (e.g., [PuTTY](https://www.putty.org/), [minicom](https://wiki.archlinux.org/title/Minicom)), or [Thonny IDE](https://thonny.org/) for easy upload and interaction

### Installation

1. **Flash MicroPython** onto your ESP32-C3:

   You can use either the ESP-IDF toolchain or a simple Python tool like `esptool.py`:

   ```
   esptool.py --chip esp32c3 --port /dev/ttyUSB0 write_flash -z 0x0 esp32c3-x.xx.x.bin
   ```

2. **Clone this repository**:
   ```
   git clone https://github.com/nekef/esp32c3-Microshell.git
   ```

3. **Upload files** to your ESP32-C3.  
   - Using Thonny:  
     - Open Thonny, select the correct interpreter/port, then upload the files to your device.
   - Or use [ampy](https://github.com/scientifichackers/ampy), [mpremote](https://docs.micropython.org/en/latest/reference/mpremote.html), or your preferred tool:
     ```
     mpremote cp /path/to/esp32c3-Microshell/* :
     ```

### Usage

After installation, simply reset or power on your ESP32-C3.  
**The Microshell will run automatically on boot.**  
Open a serial terminal or Thonny’s shell to get your prompt—no manual import needed.

Try built-in commands such as:

```
ls
pwd
cat filename.txt
rm filename.txt
echo "hello" > file.txt
```

## Example

```sh
$ ls
boot.py
main.py
file.txt

$ cat file.txt
Hello, ESP32c3-Microshell!

$ echo "test" > newfile.txt
$ ls
boot.py
main.py
file.txt
newfile.txt
```

## Contributing

Pull requests are welcome! For major changes, please open an issue first to discuss your ideas. Contributions including new commands, bug fixes, and documentation improvements are appreciated.

## License

This project is licensed under the MIT License.

## Contact

Project maintained by [nekef](https://github.com/nekef).

---

*ESP32c3-Microshell: Add a Unix-like shell to your microcontroller projects!*