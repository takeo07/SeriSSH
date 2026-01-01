import argparse
import asyncio
import os
import pathlib
import sys
from . import server, configure_logging, logger


def ensure_host_key(path: str):
    p = pathlib.Path(path)
    if not p.exists():
        # generate a simple key using asyncssh (if available at runtime)
        try:
            import asyncssh
            key = asyncssh.generate_private_key('ssh-rsa')
            p.write_text(key.export_private_key())
        except Exception:
            # fallback: create an empty file and let asyncssh error later
            p.write_text('')


def main():
    ap = argparse.ArgumentParser(description='seri-ssh - SSH to PTY bridge')
    ap.add_argument('--host-key', default='host_key', help='Path to host private key')
    ap.add_argument('--port', type=int, default=2222, help='Port to listen on')
    ap.add_argument('--user', help='Allowed username for password auth')
    ap.add_argument('--password', help='Password for the allowed user')
    ap.add_argument('--serial', help='Serial device path to bridge (e.g. /dev/ttyUSB0). If omitted a PTY pair is created and the slave path is shown in logs')

    args = ap.parse_args()

    # configure logging early
    try:
        configure_logging()
    except Exception:
        # fallback: basic logging via print
        pass

    logger.info("seri_ssh starting: port=%s serial=%s", args.port, args.serial)

    # Require an existing host key file; fail fast if missing
    if not pathlib.Path(args.host_key).exists():
        logger.error("Host key not found: %s", args.host_key)
        sys.exit(1)

    # Require a serial device path to be provided
    if not args.serial:
        logger.error("Serial device path is required (--serial)")
        sys.exit(1)

    async def _run_server():
        await server.start_server(host='0.0.0.0', port=args.port, host_key=args.host_key, user=args.user, password=args.password, serial_path=args.serial)
        # keep running until interrupted
        await asyncio.Future()

    try:
        asyncio.run(_run_server())
    except KeyboardInterrupt:
        logger.info("Interrupted, shutting down")


if __name__ == '__main__':
    main()
