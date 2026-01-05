import asyncio
import os
import fcntl
import termios
import struct
import logging
import asyncssh
import serial

logger = logging.getLogger("seri_ssh.server")


def set_pty_size(fd, cols, rows):
    # TIOCSWINSZ
    winsize = struct.pack("HHHH", rows, cols, 0, 0)
    fcntl.ioctl(fd, termios.TIOCSWINSZ, winsize)


class PTYBridgeSession(asyncssh.SSHServerSession):
    def __init__(self, master_fd, slave_name, serial_port=None):
        logger.debug("PTYBridgeSession.__init__: master_fd=%s, slave_name=%s, serial_port=%s", master_fd, slave_name, serial_port is not None)
        self._chan = None
        self._master_fd = master_fd
        self._slave_name = slave_name
        self._serial_port = serial_port
        self._loop = asyncio.get_event_loop()

    def connection_made(self, chan):
        logger.debug("connection_made() called with chan=%s", chan)
        self._chan = chan
        # Start reader for master_fd or serial_port
        reader_fd = self._master_fd
        if self._serial_port is not None:
            try:
                reader_fd = self._serial_port.fileno()
                logger.debug("Got fileno() from serial_port: %s", reader_fd)
            except Exception:
                logger.exception("Failed to get fileno() from serial_port")
                reader_fd = None
        
        logger.debug("connection_made: reader_fd=%s, master_fd=%s, serial_port=%s", reader_fd, self._master_fd, self._serial_port)
        
        if reader_fd is not None:
            try:
                self._loop.add_reader(reader_fd, self._on_master_readable)
                logger.info("SSH channel opened for PTY slave=%s (fd=%s)", self._slave_name, reader_fd)
            except Exception:
                logger.exception("Failed to add_reader for fd=%s", reader_fd)
        else:
            logger.warning("Could not register reader for slave=%s", self._slave_name)

    def session_started(self):
        pass

    def pty_received(self, term, width, height, pixwidth, pixheight, modes):
        # Only set PTY size if using PTY, not serial port
        if self._master_fd is not None and self._serial_port is None:
            try:
                set_pty_size(self._master_fd, width, height)
                logger.debug("Set PTY size: %dx%d", width, height)
            except Exception:
                logger.exception("Failed to set pty size")
        else:
            logger.debug("Skipping PTY size setting (serial_port=%s)", self._serial_port)

    def shell_requested(self):
        return True

    def exec_requested(self, command):
        # Not supporting exec; open a shell
        return False

    def data_received(self, data, datatype):
        logger.debug("data_received: len=%d, serial_port=%s, data=%r", len(data), self._serial_port is not None, data[:50])
        if self._serial_port is not None:
            # PySerialを使用している場合
            try:
                bytes_data = data.encode() if isinstance(data, str) else data
                bytes_written = self._serial_port.write(bytes_data)
                logger.debug("Wrote %d bytes to serial port (requested %d bytes)", bytes_written, len(bytes_data))
                self._serial_port.flush()
                logger.debug("Flushed serial port buffer")
            except Exception:
                logger.exception("Failed to write to serial port")
        elif self._master_fd is not None:
            # PTY/PTSを使用している場合
            try:
                os.write(self._master_fd, data.encode() if isinstance(data, str) else data)
                logger.debug("Wrote data to PTY")
            except Exception:
                logger.exception("Failed to write to PTY")

    def _on_master_readable(self):
        logger.debug("_on_master_readable called")
        try:
            if self._serial_port is not None:
                # PySerialの非ブロッキング読み込み
                in_waiting = self._serial_port.in_waiting
                logger.debug("Serial port in_waiting=%s", in_waiting)
                if in_waiting > 0:
                    data = self._serial_port.read(1024)
                    logger.debug("Read %d bytes from serial port: %r", len(data), data[:50])
                else:
                    data = b""
            else:
                # PTYの読み込み
                data = os.read(self._master_fd, 1024)
                if data:
                    logger.debug("Read %d bytes from PTY: %r", len(data), data[:50])
        except (OSError, Exception) as e:
            logger.exception("Error reading from source: %s", e)
            data = b""
        
        if data:
            try:
                # Decode bytes to str for asyncssh SSHWriter
                text_data = data.decode('utf-8', errors='replace')
                self._chan.write(text_data)
                logger.debug("Wrote %d chars to SSH channel", len(text_data))
            except Exception:
                logger.exception("Failed to write to channel")
        else:
            # EOF or no data
            logger.debug("No data available, not sending EOF")

    def eof_received(self):
        try:
            if self._serial_port is not None:
                self._serial_port.close()
            else:
                os.close(self._master_fd)
        except Exception:
            logger.exception("Error closing master fd on EOF")
        return True

    def connection_lost(self, exc):
        # Remove reader
        reader_fd = self._master_fd
        if self._serial_port is not None:
            try:
                reader_fd = self._serial_port.fileno()
            except Exception:
                logger.exception("Failed to get fileno() from serial_port")
                reader_fd = None
        
        if reader_fd is not None:
            try:
                self._loop.remove_reader(reader_fd)
            except Exception:
                logger.exception("Error removing reader for fd %s", reader_fd)

        if exc:
            logger.info("SSH session connection lost with error: %r", exc)
        else:
            logger.info("SSH session connection closed")


class SimpleSSHServer(asyncssh.SSHServer):
    def __init__(self, valid_user=None, valid_password=None, serial_path=None):
        self.valid_user = valid_user
        self.valid_password = valid_password
        self.serial_path = serial_path

    def connection_made(self, conn):
        logger.info("Incoming connection: %r", conn)

    def connection_lost(self, exc):
        logger.info("Connection lost: %r", exc)

    def begin_auth(self, username):
        # Enable password auth if configured
        return self.valid_password is not None

    def password_auth_supported(self):
        return True

    def validate_password(self, username, password):
        ok = (self.valid_user == username and self.valid_password == password)
        logger.info("Password auth attempt user=%s result=%s", username, ok)
        return ok

    def session_requested(self):
        # Not used
        return None

    def create_session(self):
        # create_session not used by asyncssh.create_server; session factory used instead
        return None





async def start_server(host='0.0.0.0', port=2222, host_key='host_key', user=None, password=None, serial_path=None, baudrate=115200):
    server = SimpleSSHServer(valid_user=user, valid_password=password, serial_path=serial_path)
    async def session_factory(stdin, stdout, stderr):
        logger.debug("session_factory called with stdin=%s, stdout=%s, stderr=%s", type(stdin).__name__, type(stdout).__name__, type(stderr).__name__)
        # If a serial_path specified, open that; else create a new PTY pair
        serial_port = None
        master_fd = None
        if serial_path:
            # Open serial port using PySerial
            try:
                serial_port = serial.Serial(
                    port=serial_path,
                    baudrate=baudrate,
                    timeout=0,  # Non-blocking mode
                    bytesize=serial.EIGHTBITS,
                    parity=serial.PARITY_NONE,
                    stopbits=serial.STOPBITS_ONE,
                    xonxoff=False,  # Disable software flow control
                    rtscts=False    # Disable hardware flow control
                )
                slave_name = serial_path
                logger.info('Opened serial %s baud=%s (8N1, no flow control)', serial_path, baudrate)
                logger.debug('Serial port settings: bytesize=%s, parity=%s, stopbits=%s, xonxoff=%s, rtscts=%s',
                           serial_port.bytesize, serial_port.parity, serial_port.stopbits, 
                           serial_port.xonxoff, serial_port.rtscts)
            except Exception:
                logger.exception('Could not open serial port %s', serial_path)
                raise
        else:
            master_fd, slave_fd = os.openpty()
            slave_name = os.ttyname(slave_fd)

        logger.debug("session_factory: creating PTYBridgeSession")
        loop = asyncio.get_event_loop()
        session = PTYBridgeSession(master_fd, slave_name, serial_port=serial_port)
        session._chan = stdout  # Use stdout as the channel for writing to SSH
        session._loop = loop
        
        # Register reader for PTY/serial data
        reader_fd = master_fd
        if serial_port is not None:
            try:
                reader_fd = serial_port.fileno()
                logger.debug("Got fileno() from serial_port: %s", reader_fd)
            except Exception:
                logger.exception("Failed to get fileno() from serial_port")
                reader_fd = None
        
        if reader_fd is not None:
            try:
                loop.add_reader(reader_fd, session._on_master_readable)
                logger.info("Registered reader for fd=%s", reader_fd)
            except Exception:
                logger.exception("Failed to add_reader for fd=%s", reader_fd)
        
        logger.info("Created PTY session, slave=%s", slave_name)
        
        # Handle incoming data from SSH client
        try:
            async for data in stdin:
                logger.debug("Received from SSH: %d bytes, data=%r", len(data) if isinstance(data, (bytes, str)) else 0, 
                           data[:30] if isinstance(data, (bytes, str)) else data)
                session.data_received(data, None)
        except Exception:
            logger.exception("Error in session handler")
        finally:
            # Cleanup
            if reader_fd is not None:
                try:
                    loop.remove_reader(reader_fd)
                    logger.debug("Removed reader for fd=%s", reader_fd)
                except Exception:
                    logger.exception("Error removing reader")
            
            if serial_port is not None:
                try:
                    serial_port.close()
                    logger.info("Closed serial port")
                except Exception:
                    logger.exception("Error closing serial port")
            elif master_fd is not None:
                try:
                    os.close(master_fd)
                    logger.info("Closed master fd")
                except Exception:
                    logger.exception("Error closing master fd")

    logger.info("Starting SSH server on %s:%s (host_key=%s)", host, port, host_key)
    await asyncssh.create_server(
        lambda: server,
        '',
        port,
        server_host_keys=[host_key],
        session_factory=session_factory,
    )
