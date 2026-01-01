import asyncio
import os
import fcntl
import termios
import struct
import logging
import asyncssh

logger = logging.getLogger("seri_ssh.server")


def set_pty_size(fd, cols, rows):
    # TIOCSWINSZ
    winsize = struct.pack("HHHH", rows, cols, 0, 0)
    fcntl.ioctl(fd, termios.TIOCSWINSZ, winsize)


class PTYBridgeSession(asyncssh.SSHServerSession):
    def __init__(self, master_fd, slave_name):
        self._chan = None
        self._master_fd = master_fd
        self._slave_name = slave_name
        self._loop = asyncio.get_event_loop()

    def connection_made(self, chan):
        self._chan = chan
        # Start reader for master_fd
        self._loop.add_reader(self._master_fd, self._on_master_readable)
        logger.info("SSH channel opened for PTY slave=%s", self._slave_name)

    def session_started(self):
        pass

    def pty_received(self, term, width, height, pixwidth, pixheight, modes):
        try:
            set_pty_size(self._master_fd, width, height)
        except Exception:
            logger.exception("Failed to set pty size")

    def shell_requested(self):
        return True

    def exec_requested(self, command):
        # Not supporting exec; open a shell
        return False

    def data_received(self, data, datatype):
        if self._master_fd is not None:
            os.write(self._master_fd, data.encode() if isinstance(data, str) else data)

    def _on_master_readable(self):
        try:
            data = os.read(self._master_fd, 1024)
        except OSError:
            data = b""
        if data:
            try:
                self._chan.write(data)
            except Exception:
                logger.exception("Failed to write to channel")
        else:
            # EOF
            try:
                self._chan.write_eof()
            except Exception:
                logger.exception("Failed to write EOF to channel")

    def eof_received(self):
        try:
            os.close(self._master_fd)
        except Exception:
            logger.exception("Error closing master fd on EOF")
        return True

    def connection_lost(self, exc):
        try:
            self._loop.remove_reader(self._master_fd)
        except Exception:
            logger.exception("Error removing reader for master fd")

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


async def start_server(host='0.0.0.0', port=2222, host_key='host_key', user=None, password=None, serial_path=None):
    server = SimpleSSHServer(valid_user=user, valid_password=password, serial_path=serial_path)

    async def session_factory(*args):
        # If a serial_path specified, open that; else create a new PTY pair
        if serial_path:
            # Open the device as master-like FD by opening read/write
            master_fd = os.open(serial_path, os.O_RDWR | os.O_NONBLOCK)
            slave_name = serial_path
        else:
            master_fd, slave_fd = os.openpty()
            slave_name = os.ttyname(slave_fd)

        logger.info("Created PTY session, slave=%s", slave_name)
        return PTYBridgeSession(master_fd, slave_name)

    logger.info("Starting SSH server on %s:%s (host_key=%s)", host, port, host_key)
    await asyncssh.create_server(
        lambda: server,
        '',
        port,
        server_host_keys=[host_key],
        session_factory=session_factory,
    )
